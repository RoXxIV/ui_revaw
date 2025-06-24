#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import json
import os
import time
import threading
import socket
from datetime import datetime
import paho.mqtt.client as mqtt
from src.ui.utils import (
    log,
    VALID_BANCS,
    DATA_DIR,
    CONFIG_PATH as BANC_CONFIG_FILE,
    MQTT_BROKER,
    MQTT_PORT,
)
from src.ui.utils.config_manager import update_bancs_config_current_step
from src.bancs import (get_banc_message_handlers, BancConfig, CSVManager, BancConfigManager, FileUtils)

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
# Variable pour la surveillance d'activité BMS
last_bms_data_received_time = {'time': None}  # Utilisation d'un dict pour la référence


def on_banc_publish_simple(client, userdata, mid):
    """Callback minimaliste pour logger les MID publiés."""
    log(f"{BANC}: [ON_PUBLISH CALLBACK] Message avec MID {mid} a été publié (confirmé par le broker).", level="DEBUG")


def close_csv():
    """Ferme le fichier CSV actif s'il est ouvert et réinitialise les variables globales."""
    global csv_file, csv_writer
    csv_file, csv_writer = CSVManager.close_csv(csv_file, csv_writer, BANC)


def update_config(new_step):
    """
    Met à jour le fichier config.json spécifique à la batterie avec la nouvelle étape.
    """
    return BancConfigManager.update_config(BATTERY_FOLDER_PATH, new_step, BANC, update_bancs_config_current_step)


def update_config_bms(timestamp, cap_ah, cap_wh):
    """
    Met à jour le fichier config.json spécifique à la batterie avec les données BMS.
    """
    return BancConfigManager.update_config_bms(BATTERY_FOLDER_PATH, timestamp, cap_ah, cap_wh, BANC)


def update_config_ri_results(ri_data):
    """
    Met à jour le fichier config.json spécifique à la batterie avec les résultats RI.
    """
    return BancConfigManager.update_config_ri_results(BATTERY_FOLDER_PATH, ri_data, BANC)


def reset_banc_config():
    """
    Réinitialise les paramètres du banc actuel dans le fichier de configuration principal.
    """
    BancConfigManager.reset_banc_config(BANC, BANC_CONFIG_FILE)


def bms_activity_checker_thread_func(client):
    """
    [THREAD SÉPARÉ] Vérifie périodiquement la réception des données BMS.
    Publie sur /security si aucune donnée n'est reçue après BMS_DATA_TIMEOUT_S.

    Args:
        client (paho.mqtt.client.Client): L'instance du client MQTT pour publier.
    """
    global last_bms_data_received_time
    log(f"{BANC}: Thread surveillance activité BMS démarré (Timeout: {BancConfig.BMS_DATA_TIMEOUT_S}s, Check: {BancConfig.BMS_CHECK_INTERVAL_S}s).",
        level="INFO")

    # Démarre une boucle infinie qui s'exécutera tant que le script principal tourne.
    while True:
        # Met le thread en pause pour l'intervalle de vérification défini.
        time.sleep(BancConfig.BMS_CHECK_INTERVAL_S)
        last_known_time = last_bms_data_received_time['time']
        if last_known_time is not None:  # Vérifie si on a déjà reçu au moins une donnée BMS.
            now = time.time()
            time_since_last_data = now - last_known_time
            # Vérifie si le temps écoulé dépasse le seuil de timeout défini. 30s
            if time_since_last_data > BancConfig.BMS_DATA_TIMEOUT_S:
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
                last_bms_data_received_time = {'time': None}
        else:
            # Pas encore reçu de données depuis l'initialisation de ce thread/timer.
            log(f"{BANC}: Surveillance en attente de la première donnée BMS.", level="DEEP_DEBUG")


def on_message(client, userdata, msg):
    """
    Callback exécuté à la réception d'un message MQTT pour ce banc.
    Traite les messages sur les topics en utilisant les handlers du module bancs.
    """
    global current_step, csv_file, csv_writer, last_bms_data_received_time

    # Récupération des handlers
    handlers = get_banc_message_handlers()

    # Extraction du topic sans le préfixe banc
    topic_parts = msg.topic.split('/')
    if len(topic_parts) < 2:
        log(f"{BANC}: Topic invalide reçu: {msg.topic}", level="ERROR")
        return

    topic_suffix = '/'.join(topic_parts[1:])  # Enlève le préfixe "bancX"

    # Récupération du handler approprié
    handler = handlers.get(topic_suffix)
    if not handler:
        log(f"{BANC}: Message reçu sur topic non traité: {msg.topic}", level="DEBUG")
        return

    try:
        payload_str = msg.payload.decode("utf-8")

        # Traitement selon le type de handler
        if topic_suffix == 'step':
            new_current_step, should_exit, exit_code = handler(payload_str, BANC, current_step, csv_file, csv_writer,
                                                               BATTERY_FOLDER_PATH, serial_number, client, close_csv,
                                                               reset_banc_config, update_config)
            current_step = new_current_step
            if should_exit:
                sys.exit(exit_code)

        elif topic_suffix == 'bms/data':
            handler(payload_str, BANC, current_step, csv_writer, csv_file, last_bms_data_received_time,
                    update_config_bms)

        elif topic_suffix == 'ri/results':
            handler(payload_str, BANC, update_config_ri_results)

    except UnicodeDecodeError as e:
        log(f"{BANC}: Erreur décodage payload pour {msg.topic}: {e}", level="ERROR")
    except Exception as e:
        log(f"{BANC}: Erreur inattendue traitement {msg.topic}: {e}", level="ERROR")


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

        # Ouverture du fichier CSV en mode Append via CSVManager
        csv_file, csv_writer = CSVManager.open_csv_for_append(BATTERY_FOLDER_PATH, BANC)
        if csv_file is None or csv_writer is None:
            if client and client.is_connected():
                client.disconnect()
            return

        # Initialisation du timestamp et démarrage du thread de surveillance BMS.
        last_bms_data_received_time = {'time': time.time()}
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

    # Détermine le chemin du dossier pour cette batterie via FileUtils
    battery_folder = FileUtils.find_battery_folder(serial_number, DATA_DIR, BANC)
    if battery_folder is None:  # Si non trouvé, construit le chemin pour un nouveau dossier
        timestamp = datetime.now().strftime("%d%m%Y")
        battery_folder = os.path.join(DATA_DIR, BANC, f"{timestamp}-{serial_number}")
        log(f"{BANC}: Aucun dossier existant trouvé, utilisera/créera: {battery_folder}", level="INFO")

    BATTERY_FOLDER_PATH = battery_folder  # Définit le chemin global

    # Charge la configuration existante ou crée les fichiers par défaut via BancConfigManager
    config = BancConfigManager.load_or_create_config(battery_folder, serial_number, BANC,
                                                     lambda folder: CSVManager.create_data_csv(folder, BANC))
    current_step = config.get("current_step", 1)

    # S'assurer que data.csv existe
    data_csv_path = os.path.join(BATTERY_FOLDER_PATH, "data.csv")
    if not os.path.exists(data_csv_path):
        log(f"{BANC}: data.csv non trouvé (inattendu après load_or_create_config), tentative de création...",
            level="ERROR")
        CSVManager.create_data_csv(BATTERY_FOLDER_PATH, BANC)

    log(f"{BANC}: Prêt à démarrer pour {serial_number} dans {BATTERY_FOLDER_PATH}", level="INFO")
    log(f"{BANC}: Étape initiale (depuis config): {current_step}", level="INFO")

    # Lance la configuration et la boucle MQTT principale
    global_mqtt_config(current_step)


def on_paho_log(client, userdata, level, buf):
    log(f"{BANC}: [PAHO LOG - Level {level}] {buf}", level="DEEP_DEBUG")


if __name__ == "__main__":
    main()
