# -*- coding: utf-8 -*-
"""
Gestionnaire pour les fichiers de configuration des bancs de test.
"""
import json
import os
from datetime import datetime
from src.ui.utils import log


class BancConfigManager:
    """
    Classe pour gérer les opérations de configuration des bancs de test.
    """

    @staticmethod
    def load_or_create_config(battery_folder, serial_number, banc, create_data_csv_func):
        """
        Charge la configuration depuis config.json dans battery_folder s'il existe et est valide.
        Sinon, crée le battery_folder (si nécessaire), crée un fichier config.json
        par défaut avec les informations initiales (step 1, timestamps, etc.),
        crée le data.csv via create_data_csv, et retourne la configuration créée.
        
        Args:
            battery_folder (str): Chemin complet du dossier où config.json doit se trouver/être créé.
            serial_number (str): Numéro de série de la batterie pour la config par défaut.
            banc (str): Nom du banc pour les logs
            create_data_csv_func: Fonction pour créer le CSV
            
        Returns:
            dict: Le dictionnaire de configuration (chargé ou nouvellement créé).
                  Retourne le défaut même si un fichier existant est corrompu (il sera écrasé).
                  Peut lever une exception si la création du dossier/fichier par défaut échoue.
        """
        from src.ui.utils import DATA_DIR

        # Construit le chemin vers le fichier config.json attendu dans le dossier de la batterie.
        config_path = os.path.join(battery_folder, "config.json")
        config_data = None

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as file:
                    config_data = json.load(file)
                    if not isinstance(config_data, dict):
                        log(f"{banc}: Fichier config.json ({config_path}) ne contient pas un objet JSON valide. Recréation.",
                            level="ERROR")
                        config_data = None  # Forcer la recréation.
                    else:
                        log(f"{banc}: Configuration existante chargée depuis {config_path}", level="INFO")
                        create_data_csv_func(battery_folder)
                        return config_data
            except Exception as e:
                log(f"{banc}: Erreur lecture/parsing config existante ({config_path}): {e}. Recréation fichier par défaut.",
                    level="ERROR")
                config_data = None  # Assurer qu'on passe à la création.

        # Si le fichier n'existait pas OU si la lecture a échoué.
        if config_data is None:
            log(f"{banc}: Création config.json par défaut et/ou dossier(s) nécessaire(s) dans {battery_folder}",
                level="INFO")
            try:
                # Vérification/Création des dossiers
                data_dir_existed_before = os.path.isdir(DATA_DIR)  # Verifier si le dossier principal existe.
                banc_path = os.path.join(DATA_DIR,
                                         banc)  # Construit le chemin vers le sous-dossier du banc (ex: "data/banc1").
                # Crée le dossier final `battery_folder` ainsi que tous les dossiers parents nécessaires.
                # `exist_ok=True` évite une erreur si les dossiers existent déjà.
                banc_dir_existed_before = os.path.isdir(banc_path)
                os.makedirs(battery_folder, exist_ok=True)
                log(f"{banc}: Vérification/Création de la structure de dossier pour {battery_folder} terminée.",
                    level="DEBUG")

                # Log de création conditionnel
                # Si le dossier DATA_DIR n'existait pas avant mais existe maintenant.
                if not data_dir_existed_before and os.path.isdir(DATA_DIR):
                    log(f"{banc}: Répertoire principal '{DATA_DIR}' créé.", level="INFO")
                # Si le dossier du banc n'existait pas avant mais existe maintenant.
                if not banc_dir_existed_before and os.path.isdir(banc_path):
                    log(f"{banc}: Sous-répertoire '{banc_path}' créé.", level="INFO")

                # Création du contenu de la configuration par défaut.
                timestamp = datetime.now().isoformat()
                default_config = {
                    "battery_serial": serial_number,
                    "banc": banc,
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
                log(f"{banc}: Fichier config.json créé avec succès.", level="INFO")
                create_data_csv_func(battery_folder)
            except OSError as e:
                log(f"{banc}: ERREUR CRITIQUE - Impossible de créer dossier/écrire config.json par défaut ({config_path}): {e}",
                    level="ERROR")
                raise  # Relance l'exception pour arrêter le script principal (main)
            except Exception as e:
                log(f"{banc}: ERREUR CRITIQUE - Erreur inattendue création config par défaut ({config_path}): {e}",
                    level="ERROR")
                raise
        # Retourne la config (chargée ou nouvellement créée)
        return config_data

    @staticmethod
    def update_config(battery_folder_path, new_step, banc, update_bancs_config_current_step_func):
        """
        Met à jour le fichier config.json spécifique à la batterie avec la nouvelle étape
        et le timestamp actuel. Appelle également la fonction pour mettre à jour
        l'étape dans le fichier de configuration global bancs_config.json.
        
        Args:
            battery_folder_path (str): Chemin du dossier batterie
            new_step (int): La nouvelle étape (phase) à enregistrer.
            banc (str): Nom du banc pour les logs
            update_bancs_config_current_step_func: Fonction pour MAJ config globale
            
        Returns:
            bool: True si la mise à jour du fichier config.json spécifique a réussi,
                  False en cas d'erreur de lecture ou d'écriture.
                  Note: Ne garantit pas le succès de update_bancs_config_current_step.
        """
        # Vérifie si le chemin est défini ET s'il correspond bien à un dossier existant.
        if not battery_folder_path or not os.path.isdir(battery_folder_path):
            log(f"{banc}: Erreur - BATTERY_FOLDER_PATH non valide dans update_config: {battery_folder_path}",
                level="ERROR")
            return False
        # Construit le chemin complet vers le fichier config.json.
        config_path = os.path.join(battery_folder_path, "config.json")
        config = None
        # Lecture du fichier config.json existant.
        try:
            with open(config_path, "r", encoding="utf-8") as file:  # Mode lecture ("r").
                config = json.load(file)
            if not isinstance(config, dict):
                log(f"{banc}: ERREUR - Contenu de {config_path} n'est pas un dictionnaire. Mise à jour annulée.",
                    level="ERROR")
                return False
        except FileNotFoundError:
            log(f"{banc}: ERREUR - Fichier {config_path} non trouvé lors de update_config. Mise à jour annulée.",
                level="ERROR")
            return False
        except json.JSONDecodeError as e:
            log(f"{banc}: ERREUR - Fichier {config_path} corrompu (JSON invalide) lors de update_config: {e}. Mise à jour annulée.",
                level="ERROR")
            return False
        except OSError as e:
            log(f"{banc}: ERREUR - Impossible de lire {config_path} lors de update_config: {e}. Mise à jour annulée.",
                level="ERROR")
            return False
        except Exception as e:
            log(f"{banc}: ERREUR - Erreur inattendue lecture {config_path} dans update_config: {e}", level="ERROR")
            return False
        # Modification des données en mémoire.
        try:  # Met à jour les clés "current_step" et "timestamp_last_update".
            config["current_step"] = new_step
            config["timestamp_last_update"] = datetime.now().isoformat()
        except Exception as e:
            log(f"{banc}: ERREUR - Erreur lors de la modification des clés dans config: {e}", level="ERROR")
            return False
        # Écriture du fichier config.json modifié.
        try:
            with open(config_path, "w", encoding="utf-8") as file:  # Mode ecriture ("w").
                json.dump(config, file, indent=2, ensure_ascii=False)
                log(f"{banc}: Fichier {config_path} mis à jour: current_step={new_step}", level="INFO")
            # Mise à jour du fichier global bancs_config.json

            success = update_bancs_config_current_step_func(new_step, banc)
            if not success:
                log(f"{banc}: Erreur lors de la mise à jour du step dans bancs_config.json", level="ERROR")
            return True
        except OSError as e:
            log(f"{banc}: ERREUR CRITIQUE - Impossible d'écrire les mises à jour dans {config_path}: {e}",
                level="ERROR")
            return False
        except TypeError as e:
            log(f"{banc}: ERREUR CRITIQUE - Impossible de sérialiser config en JSON pour {config_path}: {e}",
                level="ERROR")
            return False
        except Exception as e:
            log(f"{banc}: ERREUR CRITIQUE - Erreur inattendue écriture {config_path}: {e}", level="ERROR")
            return False

    @staticmethod
    def update_config_bms(battery_folder_path, timestamp, cap_ah, cap_wh, banc):
        """
        Met à jour le fichier config.json spécifique à la batterie avec le timestamp,
        la capacité (Ah) et l'énergie (Wh) les plus récents.
        
        Args:
            battery_folder_path (str): Chemin du dossier batterie
            timestamp (str): Le timestamp ISO de la dernière mise à jour.
            cap_ah (float | int): La dernière valeur de capacité (Ampère-heure).
            cap_wh (float | int): La dernière valeur d'énergie (Watt-heure).
            banc (str): Nom du banc pour les logs
            
        Returns:
            bool: True si la mise à jour a réussi, False sinon.
        """
        if not battery_folder_path or not os.path.isdir(battery_folder_path):
            log(f"{banc}: Erreur - BATTERY_FOLDER_PATH non valide dans update_config_bms: {battery_folder_path}",
                level="ERROR")
            return False
        config_path = os.path.join(battery_folder_path, "config.json")
        config = None
        # lecture du fichier config.json existant.
        try:
            with open(config_path, "r", encoding="utf-8") as file:  # Mode lecture ("r").
                config = json.load(file)
            if not isinstance(config, dict):
                log(f"{banc}: ERREUR - Contenu de {config_path} n'est pas un dictionnaire. Mise à jour BMS annulée.",
                    level="ERROR")
                return False
        except FileNotFoundError:
            log(f"{banc}: ERREUR - Fichier {config_path} non trouvé lors de update_config_bms. Mise à jour annulée.",
                level="ERROR")
            return False
        except json.JSONDecodeError as e:
            log(f"{banc}: ERREUR - Fichier {config_path} corrompu (JSON invalide) lors de update_config_bms: {e}. Mise à jour annulée.",
                level="ERROR")
            return False
        except OSError as e:
            log(f"{banc}: ERREUR - Impossible de lire {config_path} lors de update_config_bms: {e}. Mise à jour annulée.",
                level="ERROR")
            return False
        except Exception as e:
            log(f"{banc}: ERREUR - Erreur inattendue lecture {config_path} dans update_config_bms: {e}", level="ERROR")
            return False
        # Modification des données BMS en mémoire.
        try:  # Met à jour les clés "timestamp_last_update", "capacity_ah" et "capacity_wh".
            config["timestamp_last_update"] = timestamp
            config["capacity_ah"] = cap_ah
            config["capacity_wh"] = cap_wh
        except Exception as e:
            log(f"{banc}: ERREUR - Erreur lors de la modification des clés dans config (BMS): {e}", level="ERROR")
            return False
        # Écriture du fichier config.json modifié.
        try:
            with open(config_path, "w", encoding="utf-8") as file:  # Mode ecriture ("w").
                json.dump(config, file, indent=2, ensure_ascii=False)
            log(f"{banc}: Update config.json (BMS): last_update={timestamp}, Capacity={cap_ah}, Energy_wh={cap_wh}",
                level="DEEP_DEBUG")
            return True
        except OSError as e:
            log(f"{banc}: ERREUR CRITIQUE - Impossible d'écrire les mises à jour BMS dans {config_path}: {e}",
                level="ERROR")
            return False
        except TypeError as e:
            log(f"{banc}: ERREUR CRITIQUE - Impossible de sérialiser config (BMS) en JSON pour {config_path}: {e}",
                level="ERROR")
            return False
        except Exception as e:
            log(f"{banc}: ERREUR CRITIQUE - Erreur inattendue écriture (BMS) {config_path}: {e}", level="ERROR")
            return False

    @staticmethod
    def update_config_ri_results(battery_folder_path, ri_data, banc):
        """
        Met à jour le fichier config.json spécifique à la batterie avec les résultats
        des mesures Ri et Diffusion reçus.
        
        Args:
            battery_folder_path (str): Chemin du dossier batterie
            ri_data (dict): Données RI/Diffusion
            banc (str): Nom du banc pour les logs
            
        Returns:
            bool: True si la mise à jour a réussi, False sinon.
        """
        # Vérifie si le chemin est défini ET s'il correspond bien à un dossier existant.
        if not battery_folder_path or not os.path.isdir(battery_folder_path):
            log(f"{banc}: Erreur - BATTERY_FOLDER_PATH non valide dans update_config_ri_results: {battery_folder_path}",
                level="ERROR")
            return False

        config_path = os.path.join(battery_folder_path, "config.json")
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
            log(f"{banc}: Erreur lecture/décogage de {config_path} (MAJ RI): {e}. Utilisation d'un config vide.",
                level="WARNING")
        if not isinstance(ri_data, dict):
            log(f"{banc}: Données RI reçues ne sont pas un dictionnaire ({type(ri_data)}). Aucune mise à jour.",
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
                    log(f"{banc}: Conversion OK: {key} = {value}", level="DEBUG")
                except (ValueError, TypeError):
                    log(f"{banc}: Valeur invalide pour {key} reçue: {ri_data.get(key)}. Ignorée.", level="WARNING")
        # --- validation des tableaux ---
        if "delta_ri_cells" in ri_data and isinstance(ri_data["delta_ri_cells"], list):
            update_payload["delta_ri_cells"] = ri_data["delta_ri_cells"]
            log(f"{banc}: Tableau 'delta_ri_cells' ajouté au payload.", level="DEBUG")

        if "delta_diffusion_cells" in ri_data and isinstance(ri_data["delta_diffusion_cells"], list):
            update_payload["delta_diffusion_cells"] = ri_data["delta_diffusion_cells"]
            log(f"{banc}: Tableau 'delta_diffusion_cells' ajouté au payload.", level="DEBUG")
        # -------------------------------------------------------------
        # Mise à Jour et Écriture du fichier config.json.
        if not update_payload:
            log(f"{banc}: Aucune donnée RI valide reçue pour mise à jour de {config_path}.", level="WARNING")
            return True
        # Bloc pour mettre à jour le dictionnaire et écrire le fichier
        try:
            config.update(update_payload)
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(config, file, indent=2, ensure_ascii=False)
            log(f"{banc}: config.json mis à jour avec les résultats RI: {list(update_payload.keys())}", level="INFO")
            return True
        except (OSError, TypeError) as e:
            log(f"{banc}: ERREUR CRITIQUE - Impossible d'écrire/sérialiser les résultats RI dans {config_path}: {e}",
                level="ERROR")
            return False

    @staticmethod
    def reset_banc_config(banc, banc_config_file):
        """
        Réinitialise les paramètres ('serial-pending', 'status', 'current_step')
        pour le banc actuel dans le fichier de configuration principal.
        
        Args:
            banc (str): Nom du banc
            banc_config_file (str): Chemin du fichier config principal
        """
        config_data = None
        updated = False
        # Lecture du fichier de configuration principal.
        try:
            with open(banc_config_file, "r", encoding="utf-8") as file:  # r = read
                config_data = json.load(file)
            if not isinstance(config_data, dict):
                log(f"{banc}: ERREUR - Contenu de {banc_config_file} n'est pas un dictionnaire. Reset annulé.",
                    level="ERROR")
                return
        except FileNotFoundError:
            log(f"{banc}: Fichier config principal {banc_config_file} non trouvé. Impossible de réinitialiser.",
                level="ERROR")
            return
        except json.JSONDecodeError as e:
            log(f"{banc}: Fichier config principal {banc_config_file} corrompu (JSON invalide): {e}. Reset annulé.",
                level="ERROR")
            return
        except OSError as e:
            log(f"{banc}: Erreur lecture fichier config principal {banc_config_file}: {e}. Reset annulé.",
                level="ERROR")
            return
        except Exception as e:
            log(f"{banc}: Erreur inattendue lecture {banc_config_file}: {e}. Reset annulé.", level="ERROR")
            return
            # Recherche et Modification du banc dans les données lues.
        try:
            bancs = config_data.get("bancs", [])
            banc_found = False
            for banc_config in bancs:
                if banc_config.get("name", "").lower() == banc.lower():
                    # Réinitialise les valeurs.
                    banc_config["serial-pending"] = None
                    banc_config["status"] = "available"
                    banc_config["current_step"] = None
                    log(f"{banc} réinitialisé dans bancs_config.json", level="INFO")
                    banc_found = True
                    updated = True
                    break
            # Si le banc n'a pas été trouvé après la boucle.
            if not banc_found:
                log(f"{banc}: Aucune entrée trouvée pour '{banc}' dans {banc_config_file}. Aucune réinitialisation.",
                    level="ERROR")
        except Exception as e:
            log(f"{banc}: Erreur pendant la recherche/modification des données config: {e}", level="ERROR")
            return
        if updated:
            try:
                with open(banc_config_file, "w", encoding="utf-8") as file:  # w = write.
                    json.dump(config_data, file, indent=4, ensure_ascii=False)
                log(f"{banc}: Fichier {banc_config_file} sauvegardé après réinitialisation.", level="DEBUG")
            except OSError as e:
                log(f"{banc}: ERREUR CRITIQUE - Impossible d'écrire les réinitialisations dans {banc_config_file}: {e}",
                    level="ERROR")
            except TypeError as e:
                log(f"{banc}: ERREUR CRITIQUE - Impossible de sérialiser config après reset pour {banc_config_file}: {e}",
                    level="ERROR")
            except Exception as e:
                log(f"{banc}: ERREUR CRITIQUE - Erreur inattendue sauvegarde après reset de {banc_config_file}: {e}",
                    level="ERROR")
