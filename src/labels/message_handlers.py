"""
Handlers pour les messages MQTT du service d'impression.
"""
import json
from datetime import datetime
from src.ui.utils import log
from .csv_serial_manager import CSVSerialManager


def handle_create_label(payload_str, print_queue, queue_lock):
    """Gère la création d'une nouvelle étiquette."""
    try:
        data = json.loads(payload_str)
        checker = data.get("checker_name")
        if not checker:
            log("Demande de création reçue sans nom de checkeur. Annulation.", level="WARNING")
            return

        next_serial = CSVSerialManager.generate_next_serial_number()
        if not next_serial:
            log("Impossible de générer un nouveau numéro de série. Action annulée.", level="ERROR")
            return

        random_qr = CSVSerialManager.generate_random_code()
        dt_impression = datetime.now()
        timestamp_impression_iso = dt_impression.isoformat()

        if not CSVSerialManager.add_serial_to_csv(timestamp_impression_iso, next_serial, random_qr, checker):
            log(f"Échec de l'enregistrement dans le CSV pour {next_serial}. Action d'impression annulée.",
                level="ERROR")
            return

        fabrication_date_for_label = dt_impression.strftime("%d/%m/%Y")
        with queue_lock:
            print_queue.append(("CREATE_NEW_V1", next_serial, random_qr, fabrication_date_for_label))
            log(f"'{next_serial}' (validé par {checker}) ajouté à la file d'impression.", level="INFO")

    except json.JSONDecodeError:
        log(f"Payload JSON invalide pour create_label: {payload_str}", level="ERROR")
    except Exception as e:
        log(f"Erreur traitement create_label: {e}", level="ERROR")


def handle_test_done(payload_str, print_queue, queue_lock):
    """Gère la fin d'un test de batterie."""
    try:
        data = json.loads(payload_str)
        serial_to_process = data.get("serial_number")
        ts_test_done = data.get("timestamp_test_done")

        if serial_to_process and ts_test_done:
            log(f"Traitement consolidé pour test_done S/N {serial_to_process} à {ts_test_done}", level="INFO")

            # Action 1: Update CSV with TestDone timestamp
            if CSVSerialManager.update_csv_with_test_done_timestamp(serial_to_process, ts_test_done):
                log(f"Action 1 (test_done): CSV mis à jour pour {serial_to_process}", level="INFO")
            else:
                log(f"Action 1 (test_done) ÉCHEC: CSV non mis à jour pour {serial_to_process}", level="ERROR")

            # Action 2: Add shipping label to print queue
            with queue_lock:
                print_queue.append(("PRINT_SHIPPING", serial_to_process, None))
            log(f"Action 2 (test_done): Étiquette carton pour '{serial_to_process}' ajoutée à la file. Taille: {len(print_queue)}",
                level="INFO")

            # Action 3: Add main QR label to print queue
            _serial_reprint, random_code_reprint, _ = CSVSerialManager.get_details_for_reprint_from_csv(
                serial_to_process)
            if _serial_reprint and random_code_reprint:
                with queue_lock:
                    print_queue.append(("REPRINT_MAIN_QR", _serial_reprint, random_code_reprint))
                log(f"Action 3 (test_done): Réimpression étiquette QR standard pour '{_serial_reprint}' (QR: {random_code_reprint}) ajoutée à la file. Taille: {len(print_queue)}",
                    level="INFO")
            else:
                log(f"Action 3 (test_done) ÉCHEC: Impossible de trouver les détails (S/N, QR) pour réimprimer l'étiquette QR standard de {serial_to_process}.",
                    level="ERROR")
        else:
            log(f"Données manquantes pour traitement consolidé test_done: {payload_str}", level="ERROR")

    except json.JSONDecodeError:
        log(f"Payload JSON invalide pour test_done: {payload_str}", level="ERROR")
    except Exception as e:
        log(f"Erreur traitement test_done: {e}", level="ERROR")


def handle_full_reprint(payload_str, print_queue, queue_lock):
    """Gère la réimpression complète d'une batterie."""
    try:
        serial_to_reprint = payload_str.strip()
        if serial_to_reprint:
            _serial, random_code, original_ts_iso = CSVSerialManager.get_details_for_reprint_from_csv(serial_to_reprint)
            if _serial and random_code and original_ts_iso:
                try:
                    original_dt_impression = datetime.fromisoformat(original_ts_iso)
                    fabrication_date_for_v1_reprint = original_dt_impression.strftime("%d/%m/%Y")

                    with queue_lock:
                        # 1. Étiquette V1 (avec date de fabrication originale)
                        print_queue.append(("REPRINT_V1", _serial, random_code, fabrication_date_for_v1_reprint))
                        # 2. Étiquette principale standard (sans date de fab ni V1)
                        print_queue.append(("REPRINT_MAIN_QR", _serial, random_code))
                        # 3. Étiquette d'expédition
                        print_queue.append(("PRINT_SHIPPING", _serial, None))
                    log(f"Demande de réimpression complète pour S/N {_serial} (QR: {random_code}, Date Fab V1: {fabrication_date_for_v1_reprint}) ajoutée à la file. {len(print_queue)} items en attente.",
                        level="INFO")
                except ValueError as ve:
                    log(f"Erreur de format de date pour TimestampImpression '{original_ts_iso}' du S/N {_serial}: {ve}",
                        level="ERROR")
                except Exception as e:
                    log(f"Erreur inattendue lors de la préparation de la réimpression complète pour S/N {_serial}: {e}",
                        level="ERROR")
            else:
                log(f"Impossible de trouver les détails complets (S/N, QR, Timestamp) pour réimprimer S/N {serial_to_reprint}. Non ajouté à la file.",
                    level="ERROR")
        else:
            log(f"Payload vide reçu pour request_full_reprint", level="ERROR")

    except Exception as e:
        log(f"Erreur traitement request_full_reprint: {e}", level="ERROR")


def handle_shipping_update(payload_str, print_queue, queue_lock):
    """Gère la mise à jour du timestamp d'expédition."""
    try:
        data = json.loads(payload_str)
        serial_to_update = data.get("serial_number")
        ts_shipping = data.get("timestamp_expedition")
        if serial_to_update and ts_shipping:
            log(f"Demande de mise à jour TimestampExpedition pour S/N {serial_to_update} à {ts_shipping}", level="INFO")
            CSVSerialManager.update_csv_with_shipping_timestamp(serial_to_update, ts_shipping)
        else:
            log(f"Données manquantes pour mise à jour TimestampExpedition: {payload_str}", level="ERROR")

    except json.JSONDecodeError:
        log(f"Payload JSON invalide pour update_shipping_timestamp: {payload_str}", level="ERROR")
    except Exception as e:
        log(f"Erreur traitement update_shipping_timestamp: {e}", level="ERROR")


def handle_batch_creation(payload_str, print_queue, queue_lock):
    """Gère la création de lots d'étiquettes."""
    try:
        num_repetitions = int(payload_str)
        if num_repetitions <= 0:
            log(f"Nombre de répétitions invalide pour create_batch_labels: {num_repetitions}. Doit être > 0.",
                level="ERROR")
            return

        log(f"Demande de création de {num_repetitions} lot(s) complet(s) d'étiquettes via create_batch_labels.",
            level="INFO")

        for i in range(num_repetitions):
            log(f"Traitement du lot {i+1}/{num_repetitions}", level="INFO")

            # Simulation de la création d'une nouvelle étiquette V1
            next_serial = CSVSerialManager.generate_next_serial_number()
            if not next_serial:
                log(f"Lot {i+1}: Impossible de générer un nouveau numéro de série. Annulation de ce lot.",
                    level="ERROR")
                continue

            random_qr_code = CSVSerialManager.generate_random_code()
            dt_impression = datetime.now()
            timestamp_impression_iso = dt_impression.isoformat()
            fabrication_date_for_label = dt_impression.strftime("%d/%m/%Y")

            if not CSVSerialManager.add_serial_to_csv(timestamp_impression_iso, next_serial, random_qr_code):
                log(f"Lot {i+1}: Échec de l'enregistrement dans le CSV pour {next_serial}. Annulation de ce lot.",
                    level="ERROR")
                continue

            with queue_lock:
                print_queue.append(("CREATE_NEW_V1", next_serial, random_qr_code, fabrication_date_for_label))
            log(f"Lot {i+1}: Étiquette V1 pour '{next_serial}' (QR: '{random_qr_code}', Date fab: '{fabrication_date_for_label}') ajoutée à la file.",
                level="INFO")

            # Simulation des actions de 'test_done' pour ce nouveau serial
            ts_test_done = datetime.now().isoformat()

            if CSVSerialManager.update_csv_with_test_done_timestamp(next_serial, ts_test_done):
                log(f"Lot {i+1}: CSV mis à jour avec TimestampTestDone pour {next_serial}", level="INFO")
            else:
                log(f"Lot {i+1} ÉCHEC: CSV non mis à jour avec TimestampTestDone pour {next_serial}.", level="ERROR")

            # Ajouter l'étiquette d'expédition à la file
            with queue_lock:
                print_queue.append(("PRINT_SHIPPING", next_serial, None))
            log(f"Lot {i+1}: Étiquette carton pour '{next_serial}' ajoutée à la file.", level="INFO")

            # Ajouter l'étiquette QR principale à la file
            with queue_lock:
                print_queue.append(("REPRINT_MAIN_QR", next_serial, random_qr_code))
            log(f"Lot {i+1}: Réimpression étiquette QR standard pour '{next_serial}' (QR: '{random_qr_code}') ajoutée à la file.",
                level="INFO")

            log(f"Lot {i+1}/{num_repetitions} traité et ajouté à la file. Taille actuelle de la file: {len(print_queue)}",
                level="INFO")

        log(f"Tous les {num_repetitions} lots ont été ajoutés à la file d'impression.", level="INFO")

    except ValueError:
        log(f"Payload invalide pour create_batch_labels: '{payload_str}'. Doit être un entier.", level="ERROR")
    except Exception as e:
        log(f"Erreur inattendue lors du traitement de create_batch_labels pour le lot: {e}", level="ERROR")


# Dictionnaire de mapping topic -> handler
# Note: Les handlers ont besoin de print_queue et queue_lock, donc ils seront wrappés dans printer.py
def get_topic_handlers():
    """
    Retourne un dictionnaire des handlers par topic.
    Les handlers doivent être wrappés pour inclure print_queue et queue_lock.
    """
    return {
        'printer/create_label': handle_create_label,
        'printer/test_done': handle_test_done,
        'printer/request_full_reprint': handle_full_reprint,
        'printer/update_shipping_timestamp': handle_shipping_update,
        'printer/create_batch_labels': handle_batch_creation,
    }
