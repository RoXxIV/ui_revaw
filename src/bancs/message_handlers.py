"""
Handlers pour les messages MQTT des bancs de test.
"""
import sys
import time
import csv
import io
import os
import shutil
from datetime import datetime
from src.ui.utils import log, is_printer_service_running
from .banc_config import BancConfig
from .config_manager import BancConfigManager


def handle_step_message(payload_str, banc, current_step, csv_file, csv_writer, battery_folder_path, serial_number,
                        client, close_csv_func, reset_banc_config_func, update_config_func):
    """
    Gère les messages MQTT sur le topic /step.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc (str): Nom du banc (ex: "banc1")
        current_step (int): Étape actuelle stockée globalement
        csv_file: Fichier CSV ouvert
        csv_writer: Writer CSV
        battery_folder_path (str): Chemin du dossier batterie
        serial_number (str): Numéro de série de la batterie
        client: Client MQTT
        close_csv_func: Fonction pour fermer le CSV
        reset_banc_config_func: Fonction pour reset config banc
        update_config_func: Fonction pour mettre à jour config
        
    Returns:
        tuple: (new_current_step, should_exit, exit_code)
    """
    try:
        step_value = int(payload_str.strip())

        # === GESTION DES ÉTAPES SPÉCIALES D'ARRÊT ===
        if step_value == 8 or step_value == 9:
            log_reason = "d'arrêt demandé (Step 8)" if step_value == 8 else "d'arrêt manuel (Step 9)"
            log(f"{banc}: Commande {log_reason} reçue via MQTT.", level="INFO")
            close_csv_func()
            log(f"{banc}: Fichier CSV fermé suite à la commande {log_reason}.", level="INFO")
            log(f"{banc}: Arrêt du processus demandé par Step {step_value}.", level="INFO")
            return current_step, True, 0  # Terminer proprement

        # === CAS SPÉCIFIQUE POUR STEP 7 ===
        if step_value == 7:
            log(f"{banc}: ESP32 a signalé un arrêt de sécurité (Step 7).", level="ERROR")
            log(f"{banc}: Arrêt du script banc.py. La configuration du banc est conservée pour une éventuelle reprise au step {current_step}.",
                level="INFO")
            close_csv_func()
            log(f"{banc}: Fichier CSV fermé suite à Step 7.", level="INFO")

            try:
                if client and client.is_connected():
                    client.disconnect()
            except Exception as e:
                log(f"{banc}: Exception lors de la déconnexion MQTT (Step 7): {e}", level="ERROR")

            log(f"{banc}: Fin du script banc.py demandée par Step 7.", level="INFO")
            return current_step, True, 0

        # === STEP 6 - TEST ÉCHOUÉ ===
        elif step_value == 6:
            log(f"{banc}: Test ÉCHOUÉ signalé par ESP32 (Step 6).", level="ERROR")
            log(f"{banc}: Finalisation du test pour gestion nourrice, puis archivage des données et reset du banc.",
                level="INFO")

            close_csv_func()
            log(f"{banc}: Fichier CSV fermé pour test échoué.", level="INFO")

            # Archiver le dossier du test échoué
            if battery_folder_path and os.path.isdir(battery_folder_path):
                try:
                    os.makedirs(BancConfig.FAILS_ARCHIVE_DIR, exist_ok=True)
                    folder_name = os.path.basename(battery_folder_path)
                    destination_path = os.path.join(BancConfig.FAILS_ARCHIVE_DIR, folder_name)

                    # Gérer le cas où un dossier du même nom existerait déjà dans l'archive
                    if os.path.exists(destination_path):
                        timestamp_suffix = datetime.now().strftime("_%Y%m%d%H%M%S")
                        destination_path += timestamp_suffix
                        log(f"{banc}: Dossier {folder_name} existe déjà dans l'archive. Nouveau nom: {os.path.basename(destination_path)}",
                            level="WARNING")

                    shutil.move(battery_folder_path, destination_path)
                    log(f"{banc}: Dossier de test {battery_folder_path} archivé dans {destination_path}", level="INFO")
                except Exception as e:
                    log(f"{banc}: ERREUR lors de l'archivage du dossier {battery_folder_path}: {e}", level="ERROR")
            else:
                log(f"{banc}: BATTERY_FOLDER_PATH non valide ou dossier inexistant, archivage impossible.",
                    level="WARNING")

            reset_banc_config_func()  # Remet le banc à "available"
            log(f"{banc}: Configuration du banc réinitialisée dans bancs_config.json après échec.", level="INFO")

            try:
                if client and client.is_connected():
                    client.disconnect()
            except Exception as e:
                log(f"{banc}: Exception lors de la déconnexion MQTT (Step 6): {e}", level="ERROR")

            log(f"{banc}: Fin du script banc.py suite à Step 6 (Test Échoué).", level="INFO")
            return current_step, True, 0

        # === VALIDATION ET TRAITEMENT DES ÉTAPES NORMALES (1 à 5) ===
        elif step_value in [1, 2, 3, 4, 5]:
            log(f"Current step mis à jour: {step_value}, pour {banc}", level="INFO")
            new_current_step = step_value
            update_config_func(new_current_step)

            # === GESTION SPÉCIFIQUE DE LA FIN DE TEST (STEP 5) ===
            if new_current_step == 5:
                log(f"{banc}: Test terminé (Step 5 reçu). Nettoyage et arrêt.", level="INFO")
                reset_banc_config_func()
                timestamp_test_done = datetime.now().isoformat()

                # Vérification du service d'impression
                printer_service_ok = False
                try:
                    if is_printer_service_running():
                        printer_service_ok = True
                    else:
                        log(f"{banc}: AVERTISSEMENT - Service d'impression non détecté (Step 5).", level="WARNING")
                        if client.is_connected():
                            try:
                                client.publish(
                                    f"{banc}/security", "Service impression INACTIF! Actions fin compromises.", qos=0)
                            except Exception as alert_pub_e:
                                log(f"{banc}: ERREUR envoi alerte 'Service impression INACTIF': {alert_pub_e}",
                                    level="ERROR")
                except Exception as check_e:
                    log(f"{banc}: ERREUR vérification service impression: {check_e}", level="ERROR")
                    if client.is_connected():
                        try:
                            client.publish(f"{banc}/security", "Erreur vérification service impression!", qos=0)
                        except Exception:
                            pass

                # Envoi des tâches à printer.py si service OK
                if printer_service_ok:
                    log(f"{banc}: Service d'impression détecté. Envoi des tâches à printer.py.", level="INFO")
                    _send_test_done_to_printer(banc, serial_number, timestamp_test_done, client)
                else:
                    log(f"{banc}: Pas de tâches envoyées à printer.py (service inactif ou erreur vérification).",
                        level="WARNING")
                close_csv_func()
                log(f"{banc}: Fichier CSV fermé après envoi des données.", level="INFO")
                # Désabonnement et nettoyage final
                _handle_final_cleanup(banc, client)

                log(f"{banc}: Fin du processus (appel à sys.exit(0)).", level="INFO")
                return new_current_step, True, 0

            return new_current_step, False, 0

        else:  # Si la valeur reçue n'est ni 8, 9, ni 1-5
            log(f"Étape inconnue/invalide reçue sur /step : {step_value} — ignorée.", level="ERROR")
            return current_step, False, 0

    except (UnicodeDecodeError, ValueError) as e:
        log(f"{banc}: Erreur décodage/conversion payload pour /step: {e}", level="ERROR")
        return current_step, False, 0
    except Exception as e:
        log(f"{banc}: Erreur inattendue traitement /step: {e}", level="ERROR")
        return current_step, False, 0


def handle_bms_data_message(payload_str, banc, current_step, csv_writer, csv_file, last_bms_data_received_time_dict,
                            update_config_bms_func):
    """
    Gère les messages MQTT sur le topic /bms/data.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc (str): Nom du banc
        current_step (int): Étape actuelle
        csv_writer: Writer CSV
        csv_file: Fichier CSV
        last_bms_data_received_time_dict (dict): Dictionnaire contenant le timestamp
        update_config_bms_func: Fonction pour mettre à jour config BMS
    """
    # Met à jour le timestamp de la dernière réception de données BMS
    last_bms_data_received_time_dict['time'] = time.time()

    try:
        # Utilise `csv.reader` sur un `io.StringIO` pour parser la ligne CSV
        reader = csv.reader(io.StringIO(payload_str))
        bms_values = next(reader)

        if not isinstance(bms_values, list) or len(bms_values) < 10:  # Minimum pour indices 8, 9
            log(f"{banc}: Format données /bms/data incorrect. Reçu: {bms_values}", level="ERROR")
            return

        # Obtient le timestamp actuel formaté pour l'enregistrement CSV
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Détermination du mode en fonction de l'étape
        mode_mapping = {1: "phase_ri", 2: "charge", 3: "discharge", 4: "final_charge"}
        mode_str = mode_mapping.get(current_step, "unknown")

        row_to_write = [timestamp, mode_str] + bms_values

        # Écriture dans le fichier CSV
        if csv_writer is not None and csv_file is not None:
            try:
                csv_writer.writerow(row_to_write)
                csv_file.flush()  # Force l'écriture immédiate
            except Exception as csv_e:
                log(f"{banc}: Erreur écriture ligne dans data.csv: {csv_e}", level="ERROR")
        else:
            if current_step not in [0, 5, 9]:  # Ne pas loguer d'erreur si CSV fermé volontairement
                log(f"{banc}: Avertissement - csv_writer/csv_file non défini lors de la réception de /bms/data (step={current_step})",
                    level="ERROR")

        # Mise à jour de config.json (capacité/énergie) sauf si test terminé (step 5)
        if current_step not in [5, 9]:
            try:
                capacity_val = float(bms_values[8])
                energy_val = float(bms_values[9])
                update_config_bms_func(timestamp, capacity_val, energy_val)
            except (IndexError, ValueError, TypeError) as bms_upd_e:
                log(f"{banc}: Erreur conversion/index lors de la préparation MAJ config (BMS): {bms_upd_e}. Ligne: {bms_values}",
                    level="ERROR")

    except UnicodeDecodeError as e:
        log(f"{banc}: Erreur décodage payload pour /bms/data: {e}", level="ERROR")
    except StopIteration:
        log(f"{banc}: Payload vide pour /bms/data.", level="WARNING")
    except Exception as e:
        log(f"{banc}: Erreur inattendue traitement /bms/data: {e}", level="ERROR")


def _send_test_done_to_printer(banc, serial_number, timestamp_test_done, client):
    """
    Envoie la tâche consolidée à printer.py pour la fin de test.
    """
    import json

    topic_test_done = "printer/test_done"
    payload_test_done_dict = {"serial_number": serial_number, "timestamp_test_done": timestamp_test_done}

    try:
        payload_test_done_json = json.dumps(payload_test_done_dict)
        log(f"{banc}: Préparation publish '{topic_test_done}'. Connecté: {client.is_connected()}. Payload: {payload_test_done_json}",
            level="DEBUG")

        if client.is_connected():
            import paho.mqtt.client as mqtt
            publish_result, mid = client.publish(
                topic_test_done, payload=payload_test_done_json, qos=1)  # QoS 1 pour fiabilité
            log(f"{banc}: Résultat publish tâche consolidée ({topic_test_done}): {publish_result}, MID: {mid}",
                level="INFO")
            if publish_result != mqtt.MQTT_ERR_SUCCESS:
                log(f"{banc}: ÉCHEC Paho pour {topic_test_done}. Code: {publish_result}", level="ERROR")
        else:
            log(f"{banc}: Non connecté, impossible d'envoyer à {topic_test_done}.", level="WARNING")
    except Exception as pub_e:
        log(f"{banc}: ERREUR (exception) envoi à {topic_test_done}: {pub_e}", level="ERROR")


def handle_ri_results_message(payload_str, banc, update_config_ri_results_func):
    """
    Gère les messages MQTT sur le topic /ri/results.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc (str): Nom du banc
        update_config_ri_results_func: Fonction pour mettre à jour les résultats RI
    """
    try:
        import json
        ri_data = json.loads(payload_str)
        log(f"{banc}: Données RI reçues: {ri_data}", level="INFO")
        update_config_ri_results_func(ri_data)
    except UnicodeDecodeError as e:
        log(f"{banc}: Erreur décodage payload pour /ri/results: {e}", level="ERROR")
    except json.JSONDecodeError as e:
        log(f"{banc}: Erreur décodage JSON pour /ri/results: {e}. Payload: '{payload_str}'", level="ERROR")
    except Exception as e:
        log(f"{banc}: Erreur inattendue traitement /ri/results: {e}", level="ERROR")


def _handle_final_cleanup(banc, client):
    """
    Gère le nettoyage final avant fermeture du script.
    """
    # Désabonnement APRÈS les tentatives de publication
    try:
        bms_topic = f"{banc}/bms/data"
        log(f"{banc}: Avant désabonnement {bms_topic} (après publish finaux). Connecté: {client.is_connected()}",
            level="DEBUG")
        if client.is_connected():
            client.unsubscribe(bms_topic)
            log(f"{banc}: Désabonnement du topic {bms_topic} effectué.", level="DEBUG")
        else:
            log(f"{banc}: Client non connecté, impossible de se désabonner de {bms_topic}.", level="WARNING")
    except Exception as unsub_e:
        log(f"{banc}: ERREUR lors du désabonnement de {bms_topic}: {unsub_e}", level="ERROR")

    pause_duration = BancConfig.PAUSE_DURATION_FINAL_S
    log(f"{banc}: Pause de {pause_duration}s pour traitement réseau avant déconnexion...", level="DEBUG")
    time.sleep(pause_duration)

    log(f"{banc}: Préparation à la déconnexion finale et à la sortie (sys.exit).", level="INFO")
    if client.is_connected():
        try:
            log(f"{banc}: Appel explicite de client.disconnect()", level="DEBUG")
            client.disconnect()
        except Exception as disc_e:
            log(f"{banc}: ERREUR Inattendue lors de client.disconnect(): {disc_e}", level="ERROR")
    else:
        log(f"{banc}: Client déjà déconnecté avant l'appel final à disconnect.", level="WARNING")


def get_banc_message_handlers():
    """
    Retourne un dictionnaire des handlers par topic pour les bancs.
    
    Returns:
        dict: Dictionnaire topic -> fonction handler
    """
    return {
        'step': handle_step_message,
        'bms/data': handle_bms_data_message,
        'ri/results': handle_ri_results_message,
    }
