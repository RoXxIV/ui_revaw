#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, json, os, csv, io, time, threading, socket
from datetime import datetime
import paho.mqtt.client as mqtt
import shutil
from src.utils import (log, is_printer_service_running, VALID_BANCS, DATA_DIR, CONFIG_PATH as BANC_CONFIG_FILE,
                       MQTT_BROKER, MQTT_PORT)

# Traitement des arguments de la ligne de commande.
if len(sys.argv) < 3:  # Check le nombre d'arguments (nom_script, banc, serial).
    log("Usage : python banc.py <bancX> <numero_de_serie>", level="ERROR")
    sys.exit(1)
# Récupère le nom du banc et le numéro de série depuis les arguments.
BANC = sys.argv[1].lower()
serial_number = sys.argv[2]
# Valide le nom du banc par rapport à la liste dans utils.py
if BANC not in VALID_BANCS:
    log(f"Nom de banc invalide : {BANC}", level="ERROR")
    sys.exit(1)  # Quitte le script avec un code d'erreur 1 (indiquant une fin anormale).

BATTERY_FOLDER_PATH = None
current_step = 0
csv_file = None
csv_writer = None
# Constantes pour la surveillance d'activité BMS
BMS_DATA_TIMEOUT_S = 30  # Délai d'inactivité BMS avant alerte (secondes)
BMS_CHECK_INTERVAL_S = 10  # Intervalle de vérification du timeout (secondes)
NUM_CELLS = 15  # Nombre de cellules pour header CSV vvv
last_bms_data_received_time = None  # Timestamp de la dernière réception de /bms/data
FAILS_ARCHIVE_DIR = os.path.join(DATA_DIR, "archive_fails")


def on_banc_publish_simple(client, userdata, mid):
    """Callback minimaliste pour logger les MID publiés."""
    log(f"{BANC}: [ON_PUBLISH CALLBACK] Message avec MID {mid} a été publié (confirmé par le broker).",
        level="DEBUG")  # Log CRITICAL pour bien le voir


def find_battery_folder(serial_number):
    """
    Recherche le dossier correspondant à un numéro de série spécifique
    UNIQUEMENT dans le sous-dossier du banc actuel (BANC).
    Args:
        serial_number (str): Le numéro de série à rechercher.
    Returns:
        str | None: Le chemin complet du dossier trouvé, ou None s'il n'existe pas
                    dans le dossier de ce banc.
    """
    # Construit le chemin vers le sous-dossier spécifique à ce banc (ex: "data/banc1").
    banc_path = os.path.join(DATA_DIR, BANC)
    if os.path.exists(banc_path):
        try:  # Liste tous les fichiers et dossiers directement dans le sous-dossier du banc.
            for folder in os.listdir(banc_path):
                if folder.endswith(f"-{serial_number}"):
                    found_path = os.path.join(banc_path, folder)
                    log(f"{BANC}: Dossier/Item trouvé pour {serial_number} dans {banc_path}: {folder}", level="DEBUG")
                    return found_path
        except OSError as e:  # Plus spécifique
            log(f"{BANC}: Erreur d'accès au dossier {banc_path} lors de la recherche de {serial_number}: {e}",
                level="ERROR")
        except Exception as e:  # Catch-all
            log(f"{BANC}: Erreur inattendue lors de la recherche dans {banc_path}: {e}", level="ERROR")
    # Si le dossier du banc n'existe pas ou si rien n'est trouvé dedans
    return None


def create_data_csv(battery_folder):
    """
    Crée le fichier data.csv dans le dossier spécifié s'il n'existe pas déjà,
    et écrit la ligne d'en-tête (header).
    Args:
        battery_folder (str): Le chemin complet du dossier où créer le fichier CSV.
    Returns:
        None
    """
    global NUM_CELLS
    csv_path = os.path.join(battery_folder, "data.csv")
    if not os.path.exists(csv_path):
        log(f"{BANC}: Le fichier {csv_path} n'existe pas, tentative de création.", level="INFO")
        try:
            # Ouvre le fichier en mode écriture ('w')
            with open(csv_path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)  # Crée un objet pour écrire au format CSV
                # Définit la ligne d'en-tête
                header = [
                    "Timestamp", "Mode", "Voltage", "Current", "SOC", "Temperature", "MaxCellNum", "MaxCellV",
                    "MinCellNum", "MinCellV", "DischargedCapacity", "DischargedEnergy"
                ] + [f"Cell_{i+1}mV" for i in range(NUM_CELLS)] + ["HeartBeat", "AverageNurseSOC"]
                writer.writerow(header)  # Ecrit la ligne d'en-tête
                log(f"{BANC}: Fichier {csv_path} créé avec succès.", level="INFO")
        except OSError as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible de créer/écrire dans {csv_path}: {e}", level="ERROR")
        except Exception as e:
            log(f"{BANC}: Erreur inattendue lors de la création de data.csv: {e}", level="ERROR")


def load_or_create_config(battery_folder, serial_number):
    """
    Charge la configuration depuis config.json dans battery_folder s'il existe et est valide.
    Sinon, crée le battery_folder (si nécessaire), crée un fichier config.json
    par défaut avec les informations initiales (step 1, timestamps, etc.),
    crée le data.csv via create_data_csv, et retourne la configuration créée.
    Args:
        battery_folder (str): Chemin complet du dossier où config.json doit se trouver/être créé.
        serial_number (str): Numéro de série de la batterie pour la config par défaut.
    Returns:
        dict: Le dictionnaire de configuration (chargé ou nouvellement créé).
              Retourne le défaut même si un fichier existant est corrompu (il sera écrasé).
              Peut lever une exception si la création du dossier/fichier par défaut échoue.
    """
    # Construit le chemin vers le fichier config.json attendu dans le dossier de la batterie.
    config_path = os.path.join(battery_folder, "config.json")
    config_data = None

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                config_data = json.load(file)
                if not isinstance(config_data, dict):
                    log(f"{BANC}: Fichier config.json ({config_path}) ne contient pas un objet JSON valide. Recréation.",
                        level="ERROR")
                    config_data = None  # Forcer la recréation.
                else:
                    log(f"{BANC}: Configuration existante chargée depuis {config_path}", level="INFO")
                    create_data_csv(battery_folder)
                    return config_data
        except Exception as e:
            log(f"{BANC}: Erreur lecture/parsing config existante ({config_path}): {e}. Recréation fichier par défaut.",
                level="ERROR")
            config_data = None  # Assurer qu'on passe à la création.

    # Si le fichier n'existait pas OU si la lecture a échoué.
    if config_data is None:
        log(f"{BANC}: Création config.json par défaut et/ou dossier(s) nécessaire(s) dans {battery_folder}",
            level="INFO")
        try:
            # Vérification/Création des dossiers
            data_dir_existed_before = os.path.isdir(DATA_DIR)  # Verifier si le dossier principal existe.
            banc_path = os.path.join(DATA_DIR,
                                     BANC)  # Construit le chemin vers le sous-dossier du banc (ex: "data/banc1").
            # Crée le dossier final `battery_folder` ainsi que tous les dossiers parents nécessaires.
            # `exist_ok=True` évite une erreur si les dossiers existent déjà.
            banc_dir_existed_before = os.path.isdir(banc_path)
            os.makedirs(battery_folder, exist_ok=True)
            log(f"{BANC}: Vérification/Création de la structure de dossier pour {battery_folder} terminée.",
                level="DEBUG")

            # Log de création conditionnel
            # Si le dossier DATA_DIR n'existait pas avant mais existe maintenant.
            if not data_dir_existed_before and os.path.isdir(DATA_DIR):
                log(f"{BANC}: Répertoire principal '{DATA_DIR}' créé.", level="INFO")
            # Si le dossier du banc n'existait pas avant mais existe maintenant.
            if not banc_dir_existed_before and os.path.isdir(banc_path):
                log(f"{BANC}: Sous-répertoire '{banc_path}' créé.", level="INFO")

            # Création du contenu de la configuration par défaut.
            timestamp = datetime.now().isoformat()
            default_config = {
                "battery_serial": serial_number,
                "banc": BANC,
                "current_step": 1,
                "first_handle": timestamp,
                "timestamp_last_update": timestamp,
                "capacity_ah": 0,
                "capacity_wh": 0,
                "ri_discharge_average": 0,
                "ri_charge_average": 0,
                "diffusion_discharge_average": 0,
                "diffusion_charge_average": 0
            }
            config_data = default_config

            # Écriture du fichier config.json par défaut.
            with open(config_path, "w", encoding="utf-8") as file:
                # `indent=2` pour une meilleure lisibilité (indentation de 2 espaces).
                # `ensure_ascii=False` pour permettre les caractères non-ASCII (comme les accents) sans les échapper.
                json.dump(config_data, file, indent=2, ensure_ascii=False)
            log(f"{BANC}: Fichier config.json créé avec succès.", level="INFO")
            create_data_csv(battery_folder)
        except OSError as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible de créer dossier/écrire config.json par défaut ({config_path}): {e}",
                level="ERROR")
            raise  # Relance l'exception pour arrêter le script principal (main)
        except Exception as e:
            log(f"{BANC}: ERREUR CRITIQUE - Erreur inattendue création config par défaut ({config_path}): {e}",
                level="ERROR")
            raise
    # Retourne la config (chargée ou nouvellement créée)
    return config_data


def update_config(new_step):
    """
    Met à jour le fichier config.json spécifique à la batterie avec la nouvelle étape
    et le timestamp actuel. Appelle également la fonction pour mettre à jour
    l'étape dans le fichier de configuration global bancs_config.json.
    Args:
        new_step (int): La nouvelle étape (phase) à enregistrer.
    Returns:
        bool: True si la mise à jour du fichier config.json spécifique a réussi,
              False en cas d'erreur de lecture ou d'écriture.
              Note: Ne garantit pas le succès de update_bancs_config_current_step.
    """
    global BATTERY_FOLDER_PATH
    # Vérifie si le chemin est défini ET s'il correspond bien à un dossier existant.
    if not BATTERY_FOLDER_PATH or not os.path.isdir(BATTERY_FOLDER_PATH):
        log(f"{BANC}: Erreur - BATTERY_FOLDER_PATH non valide dans update_config: {BATTERY_FOLDER_PATH}", level="ERROR")
        return False
    # Construit le chemin complet vers le fichier config.json.
    config_path = os.path.join(BATTERY_FOLDER_PATH, "config.json")
    config = None
    # Lecture du fichier config.json existant.
    try:
        with open(config_path, "r", encoding="utf-8") as file:  # Mode lecture ("r").
            config = json.load(file)
        if not isinstance(config, dict):
            log(f"{BANC}: ERREUR - Contenu de {config_path} n'est pas un dictionnaire. Mise à jour annulée.",
                level="ERROR")
            return False
    except FileNotFoundError:
        log(f"{BANC}: ERREUR - Fichier {config_path} non trouvé lors de update_config. Mise à jour annulée.",
            level="ERROR")
        return False
    except json.JSONDecodeError as e:
        log(f"{BANC}: ERREUR - Fichier {config_path} corrompu (JSON invalide) lors de update_config: {e}. Mise à jour annulée.",
            level="ERROR")
        return False
    except OSError as e:
        log(f"{BANC}: ERREUR - Impossible de lire {config_path} lors de update_config: {e}. Mise à jour annulée.",
            level="ERROR")
        return False
    except Exception as e:
        log(f"{BANC}: ERREUR - Erreur inattendue lecture {config_path} dans update_config: {e}", level="ERROR")
        return False
    # Modification des données en mémoire.
    try:  # Met à jour les clés "current_step" et "timestamp_last_update".
        config["current_step"] = new_step
        config["timestamp_last_update"] = datetime.now().isoformat()
    except Exception as e:
        log(f"{BANC}: ERREUR - Erreur lors de la modification des clés dans config: {e}", level="ERROR")
        return False
    # Écriture du fichier config.json modifié.
    try:
        with open(config_path, "w", encoding="utf-8") as file:  # Mode ecriture ("w").
            json.dump(config, file, indent=2, ensure_ascii=False)
            log(f"{BANC}: Fichier {config_path} mis à jour: current_step={new_step}", level="INFO")
        # Mise à jour du fichier global bancs_config.json
        from src.utils.config_manager import update_bancs_config_current_step
        success = update_bancs_config_current_step(new_step, BANC)
        if not success:
            log(f"{BANC}: Erreur lors de la mise à jour du step dans bancs_config.json", level="ERROR")
        return True
    except OSError as e:
        log(f"{BANC}: ERREUR CRITIQUE - Impossible d'écrire les mises à jour dans {config_path}: {e}", level="ERROR")
        return False
    except TypeError as e:
        log(f"{BANC}: ERREUR CRITIQUE - Impossible de sérialiser config en JSON pour {config_path}: {e}", level="ERROR")
        return False
    except Exception as e:
        log(f"{BANC}: ERREUR CRITIQUE - Erreur inattendue écriture {config_path}: {e}", level="ERROR")
        return False


def update_config_bms(timestamp, cap_ah, cap_wh):
    """
    Met à jour le fichier config.json spécifique à la batterie avec le timestamp,
    la capacité (Ah) et l'énergie (Wh) les plus récents.
    Args:
        timestamp (str): Le timestamp ISO de la dernière mise à jour.
        cap_ah (float | int): La dernière valeur de capacité (Ampère-heure).
        cap_wh (float | int): La dernière valeur d'énergie (Watt-heure).
    Returns:
        bool: True si la mise à jour a réussi, False sinon.
    """
    global BATTERY_FOLDER_PATH
    if not BATTERY_FOLDER_PATH or not os.path.isdir(BATTERY_FOLDER_PATH):
        log(f"{BANC}: Erreur - BATTERY_FOLDER_PATH non valide dans update_config_bms: {BATTERY_FOLDER_PATH}",
            level="ERROR")
        return False
    config_path = os.path.join(BATTERY_FOLDER_PATH, "config.json")
    config = None
    # lecture du fichier config.json existant.
    try:
        with open(config_path, "r", encoding="utf-8") as file:  # Mode lecture ("r").
            config = json.load(file)
        if not isinstance(config, dict):
            log(f"{BANC}: ERREUR - Contenu de {config_path} n'est pas un dictionnaire. Mise à jour BMS annulée.",
                level="ERROR")
            return False
    except FileNotFoundError:
        log(f"{BANC}: ERREUR - Fichier {config_path} non trouvé lors de update_config_bms. Mise à jour annulée.",
            level="ERROR")
        return False
    except json.JSONDecodeError as e:
        log(f"{BANC}: ERREUR - Fichier {config_path} corrompu (JSON invalide) lors de update_config_bms: {e}. Mise à jour annulée.",
            level="ERROR")
        return False
    except OSError as e:
        log(f"{BANC}: ERREUR - Impossible de lire {config_path} lors de update_config_bms: {e}. Mise à jour annulée.",
            level="ERROR")
        return False
    except Exception as e:
        log(f"{BANC}: ERREUR - Erreur inattendue lecture {config_path} dans update_config_bms: {e}", level="ERROR")
        return False
    # Modification des données BMS en mémoire.
    try:  # Met à jour les clés "timestamp_last_update", "capacity_ah" et "capacity_wh".
        config["timestamp_last_update"] = timestamp
        config["capacity_ah"] = cap_ah
        config["capacity_wh"] = cap_wh
    except Exception as e:
        log(f"{BANC}: ERREUR - Erreur lors de la modification des clés dans config (BMS): {e}", level="ERROR")
        return False
    # Écriture du fichier config.json modifié.
    try:
        with open(config_path, "w", encoding="utf-8") as file:  # Mode ecriture ("w").
            json.dump(config, file, indent=2, ensure_ascii=False)
        log(f"{BANC}: Update config.json (BMS): last_update={timestamp}, Capacity={cap_ah}, Energy_wh={cap_wh}",
            level="DEEP_DEBUG")
        return True
    except OSError as e:
        log(f"{BANC}: ERREUR CRITIQUE - Impossible d'écrire les mises à jour BMS dans {config_path}: {e}",
            level="ERROR")
        return False
    except TypeError as e:
        log(f"{BANC}: ERREUR CRITIQUE - Impossible de sérialiser config (BMS) en JSON pour {config_path}: {e}",
            level="ERROR")
        return False
    except Exception as e:
        log(f"{BANC}: ERREUR CRITIQUE - Erreur inattendue écriture (BMS) {config_path}: {e}", level="ERROR")
        return False


def update_config_ri_results(ri_data):
    """
    Met à jour le fichier config.json spécifique à la batterie avec les résultats
    des mesures Ri et Diffusion reçus.
    """
    global BATTERY_FOLDER_PATH
    # Vérifie si le chemin est défini ET s'il correspond bien à un dossier existant.
    if not BATTERY_FOLDER_PATH or not os.path.isdir(BATTERY_FOLDER_PATH):
        log(f"{BANC}: Erreur - BATTERY_FOLDER_PATH non valide dans update_config_ri_results: {BATTERY_FOLDER_PATH}",
            level="ERROR")
        return False

    config_path = os.path.join(BATTERY_FOLDER_PATH, "config.json")
    config = {}

    try:  # Lecture robuste du fichier config.json existant.
        with open(config_path, "r", encoding="utf-8") as file:
            loaded_content = json.load(file)
            if isinstance(loaded_content, dict):
                config = loaded_content
            else:
                log(f"Contenu de {config_path} n'est pas un dictionnaire (type: {type(loaded_content)}). Utilisation d'un config vide.",
                    level="WARNING")
    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
        log(f"{BANC}: Erreur lecture/décogage de {config_path} (MAJ RI): {e}. Utilisation d'un config vide.",
            level="WARNING")
    if not isinstance(ri_data, dict):
        log(f"{BANC}: Données RI reçues ne sont pas un dictionnaire ({type(ri_data)}). Aucune mise à jour.",
            level="ERROR")
        return False
    # Validation et Préparation des Données RI/Diffusion Reçues.
    update_payload = {}  # # Dictionnaire pour stocker les paires clé/valeur valides à mettre à jour.
    # Liste des clés attendues dans les données `ri_data`.
    data_keys_to_process = [
        "ri_discharge_average", "ri_charge_average", "diffusion_discharge_average", "diffusion_charge_average",
        "delta_ri_average", "delta_diffusion_average"
    ]
    for key in data_keys_to_process:
        if key in ri_data:
            value_from_data = ri_data[key]
            try:
                value = float(value_from_data)
                update_payload[key] = value  # Ajoute au payload si la conversion réussit
                log(f"{BANC}: Conversion OK: {key} = {value}", level="DEBUG")
            except (ValueError, TypeError):
                log(f"{BANC}: Valeur invalide pour {key} reçue: {ri_data.get(key)}. Ignorée.", level="WARNING")
    # --- validation des tableaux ---
    if "delta_ri_cells" in ri_data and isinstance(ri_data["delta_ri_cells"], list):
        update_payload["delta_ri_cells"] = ri_data["delta_ri_cells"]
        log(f"{BANC}: Tableau 'delta_ri_cells' ajouté au payload.", level="DEBUG")

    if "delta_diffusion_cells" in ri_data and isinstance(ri_data["delta_diffusion_cells"], list):
        update_payload["delta_diffusion_cells"] = ri_data["delta_diffusion_cells"]
        log(f"{BANC}: Tableau 'delta_diffusion_cells' ajouté au payload.", level="DEBUG")
    # -------------------------------------------------------------
    # Mise à Jour et Écriture du fichier config.json.
    if not update_payload:
        log(f"{BANC}: Aucune donnée RI valide reçue pour mise à jour de {config_path}.", level="WARNING")
        return True
    # Bloc pour mettre à jour le dictionnaire et écrire le fichier
    try:
        config.update(update_payload)
        with open(config_path, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2, ensure_ascii=False)
        log(f"{BANC}: config.json mis à jour avec les résultats RI: {list(update_payload.keys())}", level="INFO")
        return True
    except (OSError, TypeError) as e:
        log(f"{BANC}: ERREUR CRITIQUE - Impossible d'écrire/sérialiser les résultats RI dans {config_path}: {e}",
            level="ERROR")
        return False


def reset_banc_config():
    """
    Réinitialise les paramètres ('serial-pending', 'status', 'current_step')
    pour le banc actuel (défini par la globale BANC) dans le fichier
    de configuration principal (BANC_CONFIG_FILE).
    """
    config_data = None
    updated = False
    # Lecture du fichier de configuration principal.
    try:
        with open(BANC_CONFIG_FILE, "r", encoding="utf-8") as file:  # r = read
            config_data = json.load(file)
        if not isinstance(config_data, dict):
            log(f"{BANC}: ERREUR - Contenu de {BANC_CONFIG_FILE} n'est pas un dictionnaire. Reset annulé.",
                level="ERROR")
            return
    except FileNotFoundError:
        log(f"{BANC}: Fichier config principal {BANC_CONFIG_FILE} non trouvé. Impossible de réinitialiser.",
            level="ERROR")
        return
    except json.JSONDecodeError as e:
        log(f"{BANC}: Fichier config principal {BANC_CONFIG_FILE} corrompu (JSON invalide): {e}. Reset annulé.",
            level="ERROR")
        return
    except OSError as e:
        log(f"{BANC}: Erreur lecture fichier config principal {BANC_CONFIG_FILE}: {e}. Reset annulé.", level="ERROR")
        return
    except Exception as e:
        log(f"{BANC}: Erreur inattendue lecture {BANC_CONFIG_FILE}: {e}. Reset annulé.", level="ERROR")
        return
        # Recherche et Modification du banc dans les données lues.
    try:
        bancs = config_data.get("bancs", [])
        banc_found = False
        for banc in bancs:
            if banc.get("name", "").lower() == BANC.lower():
                # Réinitialise les valeurs.
                banc["serial-pending"] = None
                banc["status"] = "available"
                banc["current_step"] = None
                log(f"{BANC} réinitialisé dans bancs_config.json", level="INFO")
                banc_found = True
                updated = True
                break
        # Si le banc n'a pas été trouvé après la boucle.
        if not banc_found:
            log(f"{BANC}: Aucune entrée trouvée pour '{BANC}' dans {BANC_CONFIG_FILE}. Aucune réinitialisation.",
                level="ERROR")
    except Exception as e:
        log(f"{BANC}: Erreur pendant la recherche/modification des données config: {e}", level="ERROR")
        return
    if updated:
        try:
            with open(BANC_CONFIG_FILE, "w", encoding="utf-8") as file:  # w = write.
                json.dump(config_data, file, indent=4, ensure_ascii=False)
            log(f"{BANC}: Fichier {BANC_CONFIG_FILE} sauvegardé après réinitialisation.", level="DEBUG")
        except OSError as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible d'écrire les réinitialisations dans {BANC_CONFIG_FILE}: {e}",
                level="ERROR")
        except TypeError as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible de sérialiser config après reset pour {BANC_CONFIG_FILE}: {e}",
                level="ERROR")
        except Exception as e:
            log(f"{BANC}: ERREUR CRITIQUE - Erreur inattendue sauvegarde après reset de {BANC_CONFIG_FILE}: {e}",
                level="ERROR")


def update_bancs_config_current_step(new_step):
    """
    Met à jour uniquement le champ 'current_step' pour le banc actuel (BANC)
    dans le fichier de configuration principal (BANC_CONFIG_FILE).
    Args:
        new_step (int): La nouvelle étape à enregistrer.
    Returns:
        bool: True si la mise à jour et la sauvegarde ont réussi, False sinon.
    """
    config_data = None
    updated = False
    try:  # Lecture du fichier de configuration principal.
        with open(BANC_CONFIG_FILE, "r", encoding="utf-8") as file:  # r = read
            config_data = json.load(file)
        if not isinstance(config_data, dict):
            log(f"{BANC}: ERREUR - Contenu de {BANC_CONFIG_FILE} n'est pas un dictionnaire. MAJ step annulée.",
                level="ERROR")
            return False
    except FileNotFoundError:
        log(f"{BANC}: Fichier config principal {BANC_CONFIG_FILE} non trouvé. Impossible de MAJ step.", level="ERROR")
        return False
    except json.JSONDecodeError as e:
        log(f"{BANC}: Fichier config principal {BANC_CONFIG_FILE} corrompu: {e}. MAJ step annulée.", level="ERROR")
        return False
    except OSError as e:
        log(f"{BANC}: Erreur lecture fichier config principal {BANC_CONFIG_FILE}: {e}. MAJ step annulée.",
            level="ERROR")
        return False
    except Exception as e:
        log(f"{BANC}: Erreur inattendue lecture {BANC_CONFIG_FILE}: {e}. MAJ step annulée.", level="ERROR")
        return False
    try:  # Recherche et Modification de l'étape pour le banc actuel
        bancs = config_data.get("bancs", [])
        banc_found = False
        for banc in bancs:
            if banc.get("name", "").lower() == BANC.lower():
                banc["current_step"] = new_step
                log(f"bancs_config.json mis à jour pour {BANC} avec current_step={new_step}", level="INFO")
                banc_found = True
                updated = True
                break
        if not banc_found:
            log(f"{BANC}: Aucune entrée trouvée pour '{BANC}' dans {BANC_CONFIG_FILE}. Aucune MAJ step.", level="ERROR")
    except Exception as e:
        log(f"{BANC}: Erreur pendant la recherche/modification step dans config: {e}", level="ERROR")
        return False
    # Sauvegarde du fichier de configuration principal (si modifié).
    if updated:
        try:
            with open(BANC_CONFIG_FILE, "w", encoding="utf-8") as file:  # w = write
                json.dump(config_data, file, indent=4, ensure_ascii=False)
            log(f"{BANC}: {BANC_CONFIG_FILE} sauvegardé après MAJ step.", level="DEBUG")
            return True  # Succès
        except OSError as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible d'écrire MAJ step dans {BANC_CONFIG_FILE}: {e}", level="ERROR")
            return False
        except TypeError as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible de sérialiser config après MAJ step pour {BANC_CONFIG_FILE}: {e}",
                level="ERROR")
            return False
        except Exception as e:
            log(f"{BANC}: ERREUR CRITIQUE - Erreur inattendue sauvegarde après MAJ step de {BANC_CONFIG_FILE}: {e}",
                level="ERROR")
            return False
    else:
        # Si updated est False (car banc non trouvé), on retourne False pour indiquer qu'aucune MAJ n'a eu lieu
        return False


def close_csv():
    """Ferme le fichier CSV actif s'il est ouvert et réinitialise les variables globales."""
    global csv_file, csv_writer
    if csv_file is not None:
        log(f"{BANC}: Tentative de fermeture du fichier CSV...", level="DEBUG")
        try:
            csv_file.close()
            log(f"{BANC}: Fichier CSV fermé.", level="INFO")
        except Exception as e:
            log(f"Erreur lors de la fermeture du CSV : {e}", level="ERROR")
        finally:
            csv_file = None
            csv_writer = None
    else:
        log(f"{BANC}: Aucun fichier CSV ouvert pour fermer.", level="DEBUG")


def bms_activity_checker_thread_func(client):
    """
    [THREAD SÉPARÉ] Vérifie périodiquement la réception des données BMS.
    Publie sur /security si aucune donnée n'est reçue après BMS_DATA_TIMEOUT_S.

    Args:
        client (paho.mqtt.client.Client): L'instance du client MQTT pour publier.
    """
    global last_bms_data_received_time
    log(f"{BANC}: Thread surveillance activité BMS démarré (Timeout: {BMS_DATA_TIMEOUT_S}s, Check: {BMS_CHECK_INTERVAL_S}s).",
        level="INFO")

    # Démarre une boucle infinie qui s'exécutera tant que le script principal tourne.
    while True:
        # Met le thread en pause pour l'intervalle de vérification défini.
        time.sleep(BMS_CHECK_INTERVAL_S)
        last_known_time = last_bms_data_received_time
        if last_known_time is not None:  # Vérifie si on a déjà reçu au moins une donnée BMS.
            now = time.time()
            time_since_last_data = now - last_known_time
            # Vérifie si le temps écoulé dépasse le seuil de timeout défini. 30s
            if time_since_last_data > BMS_DATA_TIMEOUT_S:
                log(f"{BANC}: TIMEOUT - Aucune donnée BMS reçue depuis {time_since_last_data:.0f} secondes!",
                    level="ERROR")
                # Préparation et publication de l'alerte MQTT.
                security_topic = f"{BANC}/security"
                security_payload = f"Timeout BMS {BANC}"
                try:
                    # Utilise l'instance client passée en argument
                    if client and client.is_connected():
                        client.publish(security_topic, payload=security_payload, qos=1)  # QoS 1 pour fiabilité
                        log(f"{BANC}: Alerte Timeout publiée sur {security_topic}", level="INFO")
                    else:
                        log(f"{BANC}: Client MQTT non connecté, alerte timeout non envoyée.", level="WARNING")
                except Exception as pub_e:
                    log(f"{BANC}: Erreur publication alerte security: {pub_e}", level="ERROR")

                # Réinitialiser le timer APRÈS avoir envoyé l'alerte
                last_bms_data_received_time = now
        else:
            # Pas encore reçu de données depuis l'initialisation de ce thread/timer.
            log(f"{BANC}: Surveillance en attente de la première donnée BMS.", level="DEEP_DEBUG")


def on_message(client, userdata, msg):
    """
    Callback exécuté à la réception d'un message MQTT pour ce banc.
    Traite les messages sur les topics :
      - /step : Met à jour l'étape actuelle, sauvegarde la config, termine le script si step=5.
      - /bms/data : Enregistre les données dans data.csv, met à jour la config (capacité/énergie).
      - /ri/results : Met à jour la config avec les résultats RI/Diffusion.
    Ignore les autres topics.
    Modifie les variables globales: current_step, csv_file, csv_writer (via close_csv).
    """
    global current_step, csv_file, csv_writer, last_bms_data_received_time
    # Traitement du topic /step.
    if msg.topic == f"{BANC}/step":
        try:
            payload = msg.payload.decode("utf-8").strip()
            step_value = int(payload)
            # Gestion des étapes spéciales d'arrêt (8 et 9).
            if step_value == 8 or step_value == 9:
                log_reason = "d'arrêt demandé (Step 8)" if step_value == 8 else "d'arrêt manuel (Step 9)"
                log(f"{BANC}: Commande {log_reason} reçue via MQTT.", level="INFO")
                close_csv()
                log(f"{BANC}: Fichier CSV fermé suite à la commande {log_reason}.", level="INFO")
                log(f"{BANC}: Arrêt du processus demandé par Step {step_value}.", level="INFO")
                # IMPORTANT: Ne pas mettre à jour les configs ici !
                sys.exit(0)  # Terminer proprement ce script banc.py.
            # Cas spécifique pour Step 7 (sécurité ESP32, tentative de reprise)
            if step_value == 7:
                log(f"{BANC}: ESP32 a signalé un arrêt de sécurité (Step 7).", level="ERROR")
                log(f"{BANC}: Arrêt du script banc.py. La configuration du banc est conservée pour une éventuelle reprise au step {current_step}.",
                    level="INFO")
                close_csv()
                log(f"{BANC}: Fichier CSV fermé suite à Step 7.", level="INFO")
                # NE PAS appeler reset_banc_config() pour permettre une reprise

                try:
                    if client and client.is_connected():
                        client.disconnect()
                except Exception as e:
                    log(f"{BANC}: Exception lors de la déconnexion MQTT (Step 7): {e}", level="ERROR")

                log(f"{BANC}: Fin du script banc.py demandée par Step 7.", level="INFO")
                sys.exit(0)  # Termine le script
            elif step_value == 6:
                log(f"{BANC}: Test ÉCHOUÉ signalé par ESP32 (Step 6).", level="ERROR")
                log(f"{BANC}: Finalisation du test pour gestion nourrice, puis archivage des données et reset du banc.",
                    level="INFO")

                close_csv()
                log(f"{BANC}: Fichier CSV fermé pour test échoué.", level="INFO")

                # Archiver le dossier du test échoué
                if BATTERY_FOLDER_PATH and os.path.isdir(BATTERY_FOLDER_PATH):
                    try:
                        os.makedirs(FAILS_ARCHIVE_DIR, exist_ok=True)
                        folder_name = os.path.basename(BATTERY_FOLDER_PATH)
                        destination_path = os.path.join(FAILS_ARCHIVE_DIR, folder_name)

                        # Gérer le cas où un dossier du même nom existerait déjà dans l'archive
                        if os.path.exists(destination_path):
                            timestamp_suffix = datetime.now().strftime("_%Y%m%d%H%M%S")
                            destination_path += timestamp_suffix
                            log(f"{BANC}: Dossier {folder_name} existe déjà dans l'archive. Nouveau nom: {os.path.basename(destination_path)}",
                                level="WARNING")

                        shutil.move(BATTERY_FOLDER_PATH, destination_path)
                        log(f"{BANC}: Dossier de test {BATTERY_FOLDER_PATH} archivé dans {destination_path}",
                            level="INFO")
                    except Exception as e:
                        log(f"{BANC}: ERREUR lors de l'archivage du dossier {BATTERY_FOLDER_PATH}: {e}", level="ERROR")
                else:
                    log(f"{BANC}: BATTERY_FOLDER_PATH non valide ou dossier inexistant, archivage impossible.",
                        level="WARNING")

                reset_banc_config()  # Remet le banc à "available"
                log(f"{BANC}: Configuration du banc réinitialisée dans bancs_config.json après échec.", level="INFO")

                try:
                    if client and client.is_connected():
                        client.disconnect()
                except Exception as e:
                    log(f"{BANC}: Exception lors de la déconnexion MQTT (Step 6): {e}", level="ERROR")

                log(f"{BANC}: Fin du script banc.py suite à Step 6 (Test Échoué).", level="INFO")
                sys.exit(0)
            # Validation et traitement des étapes normales (1 à 5)
            elif step_value in [1, 2, 3, 4, 5]:
                # Mise à jour de l'étape actuelle
                log(f"Current step mis à jour: {step_value}, pour {BANC}", level="INFO")
                # Mise à jour de l'état global et des fichiers de config
                current_step = step_value
                update_config(current_step)
                # Gestion spécifique de la fin de test (Step 5).
                if current_step == 5:
                    log(f"{BANC}: Test terminé (Step 5 reçu). Nettoyage et arrêt.", level="INFO")
                    close_csv()
                    reset_banc_config()
                    timestamp_test_done = datetime.now().isoformat()

                    printer_service_ok = False
                    try:
                        if is_printer_service_running():
                            printer_service_ok = True
                        else:
                            log(f"{BANC}: AVERTISSEMENT - Service d'impression non détecté (Step 5).", level="WARNING")
                            if client.is_connected():
                                try:
                                    client.publish(
                                        f"{BANC}/security",
                                        "Service impression INACTIF! Actions fin compromises.",
                                        qos=0)
                                except Exception as alert_pub_e:
                                    log(f"{BANC}: ERREUR envoi alerte 'Service impression INACTIF': {alert_pub_e}",
                                        level="ERROR")
                    except Exception as check_e:
                        log(f"{BANC}: ERREUR vérification service impression: {check_e}", level="ERROR")
                        if client.is_connected():
                            try:
                                client.publish(f"{BANC}/security", "Erreur vérification service impression!", qos=0)
                            except Exception:
                                pass

                    if printer_service_ok:
                        log(f"{BANC}: Service d'impression détecté. Envoi des tâches à printer.py.", level="INFO")
                        # Action consolidée pour printer.py
                        topic_test_done = "printer/test_done"
                        payload_test_done_dict = {
                            "serial_number": serial_number,
                            "timestamp_test_done": timestamp_test_done
                        }
                        try:
                            payload_test_done_json = json.dumps(payload_test_done_dict)
                            log(f"{BANC}: Préparation publish '{topic_test_done}'. Connecté: {client.is_connected()}. Payload: {payload_test_done_json}",
                                level="DEBUG")
                            if client.is_connected():
                                publish_result, mid = client.publish(
                                    topic_test_done, payload=payload_test_done_json, qos=1)  # QoS 1 pour fiabilité
                                log(f"{BANC}: Résultat publish tâche consolidée ({topic_test_done}): {publish_result}, MID: {mid}",
                                    level="INFO")
                                if publish_result != mqtt.MQTT_ERR_SUCCESS:
                                    log(f"{BANC}: ÉCHEC Paho pour {topic_test_done}. Code: {publish_result}",
                                        level="ERROR")
                            else:
                                log(f"{BANC}: Non connecté, impossible d'envoyer à {topic_test_done}.", level="WARNING")
                        except Exception as pub_e:
                            log(f"{BANC}: ERREUR (exception) envoi à {topic_test_done}: {pub_e}", level="ERROR")
                    else:
                        log(f"{BANC}: Pas de tâches envoyées à printer.py (service inactif ou erreur vérification).",
                            level="WARNING")
                    # Désabonnement APRÈS les tentatives de publication
                    try:
                        bms_topic = f"{BANC}/bms/data"
                        log(f"{BANC}: Avant désabonnement {bms_topic} (après publish finaux). Connecté: {client.is_connected()}",
                            level="DEBUG")
                        if client.is_connected():
                            client.unsubscribe(bms_topic)
                            log(f"{BANC}: Désabonnement du topic {bms_topic} effectué.", level="DEBUG")
                            # time.sleep(0.1) # Petite pause optionnelle
                        else:
                            log(f"{BANC}: Client non connecté, impossible de se désabonner de {bms_topic}.",
                                level="WARNING")
                    except Exception as unsub_e:
                        log(f"{BANC}: ERREUR lors du désabonnement de {bms_topic}: {unsub_e}", level="ERROR")

                    pause_duration = 5.0  # Augmenter un peu la pause pour ce test
                    log(f"{BANC}: Pause de {pause_duration}s pour traitement réseau avant déconnexion...",
                        level="DEBUG")
                    time.sleep(pause_duration)

                    log(f"{BANC}: Préparation à la déconnexion finale et à la sortie (sys.exit).", level="INFO")
                    if client.is_connected():
                        try:
                            log(f"{BANC}: Appel explicite de client.disconnect()", level="DEBUG")
                            client.disconnect()
                        except Exception as disc_e:
                            log(f"{BANC}: ERREUR Inattendue lors de client.disconnect(): {disc_e}", level="ERROR")
                    else:
                        log(f"{BANC}: Client déjà déconnecté avant l'appel final à disconnect.", level="WARNING")

                    log(f"{BANC}: Fin du processus (appel à sys.exit(0)).", level="INFO")
                    #sys.exit(0)
                    return
            else:  # Si la valeur reçue n'est ni 8, 9, ni 1-5.
                log(f"Étape inconnue/invalide reçue sur {msg.topic} : {step_value} — ignorée.", level="ERROR")
                return  # Ignorer le message si l'étape est inconnue
        except (UnicodeDecodeError, ValueError) as e:
            log(f"{BANC}: Erreur décodage/conversion payload pour {msg.topic}: {e}", level="ERROR")
        except Exception as e:
            log(f"{BANC}: Erreur inattendue traitement {msg.topic}: {e}", level="ERROR")
    # Traitement du topic /bms/data.
    elif msg.topic == f"{BANC}/bms/data":
        # Met à jour le timestamp de la dernière réception de données BMS (utilisé par le thread de surveillance).
        last_bms_data_received_time = time.time()
        try:
            payload = msg.payload.decode("utf-8")
            # Utilise `csv.reader` sur un `io.StringIO` pour parser la ligne CSV (même s'il n'y a qu'une ligne).
            reader = csv.reader(io.StringIO(payload))
            # Lit la première (et unique) ligne du "fichier" CSV. `bms_values` est une liste de chaînes.
            bms_values = next(reader)
            if not isinstance(bms_values, list) or len(bms_values) < 10:  # Minimum pour indices 8, 9
                log(f"{BANC}: Format données /bms/data incorrect. Reçu: {bms_values}", level="ERROR")
                return
            # Obtient le timestamp actuel formaté pour l'enregistrement CSV.
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Détermination du mode en fonction de l'étape.
            if current_step == 1: mode_str = "phase_ri"
            elif current_step == 2: mode_str = "charge"
            elif current_step == 3: mode_str = "discharge"
            elif current_step == 4: mode_str = "final_charge"
            else: mode_str = "unknown"  # Inclut step 5 ou 0.
            row_to_write = [timestamp, mode_str] + bms_values

            # Écriture dans le fichier CSV.
            if csv_writer is not None and csv_file is not None:
                try:
                    csv_writer.writerow(row_to_write)  # Ecrit la ligne.
                    # Force l'écriture immédiate des données du buffer vers le disque (utile en cas de crash).
                    csv_file.flush()
                except Exception as csv_e:
                    log(f"{BANC}: Erreur écriture ligne dans data.csv: {csv_e}", level="ERROR")
            else:
                if current_step not in [0, 5, 9]:  # Ne pas loguer d'erreur si CSV fermé volontairement.
                    log(f"{BANC}: Avertissement - csv_writer/csv_file non défini lors de la réception de /bms/data (step={current_step})",
                        level="ERROR")
            # Mise à jour de config.json (capacité/énergie) sauf si test terminé (step 5).
            if current_step not in [5, 9]:
                try:
                    capacity_val = float(bms_values[8])
                    energy_val = float(bms_values[9])
                    update_config_bms(timestamp, capacity_val, energy_val)
                except (IndexError, ValueError, TypeError) as bms_upd_e:
                    log(f"{BANC}: Erreur conversion/index lors de la préparation MAJ config (BMS): {bms_upd_e}. Ligne: {bms_values}",
                        level="ERROR")
        except UnicodeDecodeError as e:
            log(f"{BANC}: Erreur décodage payload pour {msg.topic}: {e}", level="ERROR")
        except StopIteration:
            log(f"{BANC}: Payload vide pour {msg.topic}.", level="WARNING")
        except Exception as e:
            log(f"{BANC}: Erreur inattendue traitement {msg.topic}: {e}", level="ERROR")
    # Traitement du topic /ri/results.
    elif msg.topic == f"{BANC}/ri/results":
        try:
            payload = msg.payload.decode("utf-8")
            ri_data = json.loads(payload)
            log(f"{BANC}: Données RI reçues: {ri_data}", level="INFO")
            update_config_ri_results(ri_data)
        except UnicodeDecodeError as e:
            log(f"{BANC}: Erreur décodage payload pour {msg.topic}: {e}", level="ERROR")
        except json.JSONDecodeError as e:
            log(f"{BANC}: Erreur décodage JSON pour {msg.topic}: {e}. Payload: '{payload}'", level="ERROR")
        except Exception as e:
            log(f"{BANC}: Erreur inattendue traitement {msg.topic}: {e}", level="ERROR")
    else:
        log(f"{BANC}: Message reçu sur topic non traité: {msg.topic}", level="DEBUG")


def global_mqtt_config(initial_step):
    """
    Configure le client MQTT, s'abonne aux topics nécessaires pour ce banc,
    publie un payload initial, ouvre le fichier CSV pour l'écriture,
    puis lance la boucle principale de réception MQTT (bloquante).
    args:
        initial_step (int): Etape initiale du banc.
    Returns:
        None: La fonction boucle indéfiniment via loop_forever() ou se termine
              sur erreur critique.
    """
    global csv_file, csv_writer, BATTERY_FOLDER_PATH, last_bms_data_received_time
    if not BATTERY_FOLDER_PATH:
        log(f"{BANC}: ERREUR CRITIQUE - BATTERY_FOLDER_PATH non défini avant init MQTT.", level="ERROR")
        return

    client = None
    try:
        client = mqtt.Client(
            client_id=f"banc_script_{BANC}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1  # type: ignore [attr-defined]
        )  # voir stackoverflow pour cette erreur ?
        client.on_message = on_message
        client.on_publish = on_banc_publish_simple
        client.on_log = on_paho_log
        log(f"{BANC}: Connexion à MQTT ({MQTT_BROKER}:{MQTT_PORT})...", level="INFO")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)

        # Abonnements aux topics MQTT nécessaires pour ce banc.
        topics_to_subscribe = [
            (f"{BANC}/step", 0),  # Changements d'étape.
            (f"{BANC}/bms/data", 0),  # Données BMS.
            (f"{BANC}/ri/results", 0)  # Données RI/Diffusion.
        ]
        result, mid = client.subscribe(topics_to_subscribe)
        if result != mqtt.MQTT_ERR_SUCCESS:
            log(f"{BANC}: ERREUR CRITIQUE - Échec abonnement MQTT (Code: {result}). Arrêt.", level="ERROR")
            return  # Arrêter le script si l'abonnement initial échoue

        log(f"{BANC}: Abonnements MQTT réussis.", level="INFO")

        # Lecture config.json et publication de l'état initial
        config_path = os.path.join(BATTERY_FOLDER_PATH, "config.json")
        config_data = {}
        try:
            # Ajouter encoding
            with open(config_path, "r", encoding="utf-8") as file:  # Mode lecture ("r").
                loaded_content = json.load(file)
                if isinstance(loaded_content, dict):
                    config_data = loaded_content
                else:
                    log(f"{BANC}: Contenu {config_path} invalide lors pub init. Utilise défauts.", level="ERROR")
        except Exception as read_e:
            log(f"{BANC}: Erreur lecture {config_path} lors pub init: {read_e}. Utilise défauts.", level="ERROR")

        # Prépare le dictionnaire (payload) à envoyer à l'ESP32 via /command.
        init_payload = {
            "current_step": config_data.get("current_step", initial_step),  # Utilise initial_step si absent
            "capacity_ah": config_data.get("capacity_ah", 0),
            "capacity_wh": config_data.get("capacity_wh", 0)
        }
        try:
            payload_json = json.dumps(init_payload, ensure_ascii=False)
            command_topic_for_banc = f"{BANC}/command"
            client.publish(command_topic_for_banc, payload=payload_json, qos=1)
            log(f"{BANC}: État initial publié sur {command_topic_for_banc}: {payload_json}", level="INFO")
        except TypeError as json_e:
            log(f"{BANC}: Erreur sérialisation payload initial: {json_e}", level="ERROR")
        except Exception as pub_e:
            log(f"{BANC}: Erreur publication état initial: {pub_e}", level="ERROR")
        # Ouverture du fichier CSV en mode Append.
        data_csv_path = os.path.join(BATTERY_FOLDER_PATH, "data.csv")
        log(f"{BANC}: Ouverture du fichier CSV en mode append: {data_csv_path}", level="INFO")
        # Ouverture du fichier CSV en mode ajout (Append).
        try:
            # `buffering=1` force l'écriture ligne par ligne (peut être utile en cas de crash).
            csv_file = open(data_csv_path, "a", newline="", encoding="utf-8", buffering=1)
            csv_writer = csv.writer(csv_file)
        except Exception as e:
            log(f"{BANC}: ERREUR CRITIQUE - Impossible d'ouvrir {data_csv_path} en mode append: {e}", level="ERROR")
            if client and client.is_connected(): client.disconnect()
            return
        # Initialisation du timestamp et démarrage du thread de surveillance BMS.
        last_bms_data_received_time = time.time()
        log(f"{BANC}: Démarrage du thread de surveillance d'activité BMS...", level="INFO")
        checker_thread = threading.Thread(
            target=bms_activity_checker_thread_func,  # Fonction cible à executer.
            args=(client, ),  # Les arguments à passer à la fonction cible (l'instance client MQTT).
            daemon=True  # Le thread s'arrêtera si le thread principal (celui-ci) se termine.
        )
        # Démarre l'exécution du thread de surveillance en parallèle.
        checker_thread.start()
        # Démarrage de la boucle MQTT (bloquante).
        log(f"{BANC}: Démarrage de la boucle MQTT (loop_forever)...", level="INFO")
        # Démarre la boucle réseau de paho-mqtt. Bloque l'exécution ici.
        # Gère la réception des messages et appelle `on_message` quand nécessaire.
        # Gère aussi l'envoi des pings keepalive.
        client.loop_forever()
        log(f"{BANC}: loop_forever terminée.", level="INFO")
    except (socket.timeout, TimeoutError, ConnectionRefusedError, socket.gaierror, OSError) as conn_e:
        log(f"{BANC}: ERREUR CRITIQUE - Erreur de connexion/réseau MQTT: {conn_e}. Arrêt du script.", level="ERROR")
    except Exception as e:
        log(f"{BANC}: ERREUR CRITIQUE - Erreur inattendue dans la configuration/boucle MQTT: {e}", level="ERROR")
    finally:
        log(f"{BANC}: Nettoyage final (fermeture CSV si nécessaire)...", level="DEBUG")
        close_csv()
        if client and client.is_connected():  # S'assurer que client est défini et encore connecté
            log(f"{BANC}: Déconnexion du client MQTT dans finally (mesure de sécurité).", level="DEBUG")
            try:
                client.disconnect()
            except Exception as final_disc_e:
                log(f"{BANC}: ERREUR déconnexion client dans finally: {final_disc_e}", level="ERROR")
        else:
            log(f"{BANC}: Client non défini ou déjà déconnecté dans le bloc finally.", level="DEBUG")
        log(f"{BANC}: *** FIN DU BLOC FINALLY. global_mqtt_config VA RETOURNER. ***", level="ERROR")


def main():
    """
    Fonction principale d'exécution du script banc.py.
    Initialise l'environnement pour un test de batterie spécifique :
    - Détermine le dossier de données de la batterie (le crée si nécessaire).
    - Charge ou crée les fichiers config.json et data.csv.
    - Définit l'état initial (current_step).
    - Lance la boucle principale MQTT pour ce banc.
    """
    global BATTERY_FOLDER_PATH, current_step
    # Détermine le chemin du dossier pour cette batterie
    # (BANC et serial_number sont déjà définis globalement à partir des arguments sys.argv).
    battery_folder = find_battery_folder(serial_number)
    if battery_folder is None:  # Si non trouvé, construit le chemin pour un nouveau dossier
        timestamp = datetime.now().strftime("%d%m%Y")
        battery_folder = os.path.join(DATA_DIR, BANC, f"{timestamp}-{serial_number}")
        log(f"{BANC}: Aucun dossier existant trouvé, utilisera/créera: {battery_folder}", level="INFO")

    BATTERY_FOLDER_PATH = battery_folder  # Définit le chemin global
    # Charge la configuration existante ou crée les fichiers par défaut
    # Cette fonction gère la création du dossier et de data.csv si nécessaire
    config = load_or_create_config(battery_folder, serial_number)
    current_step = config.get("current_step", 1)
    # S'assurer que data.csv existe
    data_csv_path = os.path.join(BATTERY_FOLDER_PATH, "data.csv")
    if not os.path.exists(data_csv_path):
        log(f"{BANC}: data.csv non trouvé (inattendu après load_or_create_config), tentative de création...",
            level="ERROR")
        create_data_csv(BATTERY_FOLDER_PATH)
    log(f"{BANC}: Prêt à démarrer pour {serial_number} dans {BATTERY_FOLDER_PATH}", level="INFO")
    log(f"{BANC}: Étape initiale (depuis config): {current_step}", level="INFO")
    # Lance la configuration et la boucle MQTT principale
    global_mqtt_config(current_step)


def on_paho_log(client, userdata, level, buf):
    log(f"{BANC}: [PAHO LOG - Level {level}] {buf}", level="DEEP_DEBUG")  # ou INFO


if __name__ == "__main__":
    main()
