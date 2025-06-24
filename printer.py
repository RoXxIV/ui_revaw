#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import socket
import time
import collections
import threading
import re
import paho.mqtt.client as mqtt
from src.ui.utils import log
from src.labels import LabelTemplates, PrinterConfig, CSVSerialManager, get_topic_handlers

# --- File d'attente et Verrou ---
print_queue = collections.deque()
queue_lock = threading.Lock()


def parse_hqes_response(response_str):
    """
    Analyse la réponse texte de ~HQES et retourne les flags et groupes.
    Retourne un tuple: (error_flag, error_g2_hex, error_g1_hex, warn_flag, warn_g2_hex, warn_g1_hex)
    Retourne None si le parsing échoue.
    """
    error_flag, error_g2, error_g1 = '0', '00000000', '00000000'
    warn_flag, warn_g2, warn_g1 = '0', '00000000', '00000000'
    found_errors = False
    found_warnings = False

    # Regex pour extraire les 3 parties après ERRORS: ou WARNINGS:
    # Ex: "ERRORS:   1 00000000 00000005" -> capture '1', '00000000', '00000005'
    pattern = re.compile(r"^\s*([A-Z]+):\s+(\d)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)")

    lines = response_str.splitlines()
    for line in lines:
        match = pattern.match(line)
        if match:
            section, flag, g2_hex, g1_hex = match.groups()
            if section == "ERRORS":
                error_flag, error_g2, error_g1 = flag, g2_hex, g1_hex
                found_errors = True
            elif section == "WARNINGS":
                warn_flag, warn_g2, warn_g1 = flag, g2_hex, g1_hex
                found_warnings = True

    # On considère le parsing réussi si on a trouvé au moins la ligne ERRORS
    if found_errors:
        # Padder les valeurs hex si elles sont plus courtes que 8 caractères (peu probable mais par sécurité)
        error_g2 = error_g2.zfill(8)
        error_g1 = error_g1.zfill(8)
        warn_g2 = warn_g2.zfill(8)
        warn_g1 = warn_g1.zfill(8)
        return error_flag, error_g2, error_g1, warn_flag, warn_g2, warn_g1
    else:
        log(f"Impossible de trouver la ligne 'ERRORS:' dans la réponse: {response_str}", level="ERROR")
        return None


def check_printer_status(printer_ip, printer_port):
    """
    Interroge l'imprimante avec ~HQES et retourne un statut simplifié.
    """
    status = PrinterConfig.STATUS_ERROR_COMM  # Statut par défaut en cas d'erreur comm
    sock = None  # Initialiser la variable socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PrinterConfig.SOCKET_TIMEOUT_S)
        sock.connect((printer_ip, printer_port))
        log(f"Connecté à {printer_ip}:{printer_port} pour statut.", level="DEBUG")

        command = b'~HQES\r\n'
        sock.sendall(command)
        log(f"Commande {command.strip()} envoyée.", level="DEBUG")

        # Recevoir la réponse
        response_bytes = b''
        try:
            while True:
                # Lire jusqu'à 1024 octets
                chunk = sock.recv(1024)
                if not chunk:
                    # Connexion fermée par l'imprimante avant la fin?
                    log("Connexion fermée pendant la réception du statut.", level="WARNING")
                    break
                response_bytes += chunk
                # Heuristique simple: on arrête si on reçoit ETX ou si ça se calme
                # Une meilleure approche serait de chercher STX et ETX explicitement
                if b'\x03' in chunk:  # ETX (End of Text)
                    log("Caractère ETX détecté dans la réponse.", level="DEBUG")
                    break
                # Petite pause pour voir si d'autres données arrivent
                # time.sleep(0.1) # Attention, peut ralentir
        except socket.timeout:
            # Si un timeout se produit APRES avoir reçu des données, on essaie de parser quand même
            if not response_bytes:
                log("Timeout lors de la réception de la réponse ~HQES.", level="DEBUG")
                return PrinterConfig.STATUS_ERROR_COMM  # Vraie erreur de communication

        # Décoder et Parser la réponse
        if response_bytes:
            # Essayer de décoder en ASCII, ignorer les erreurs (comme STX/ETX)
            response_str = response_bytes.decode('ascii', errors='ignore')
            log(f"Réponse brute reçue:\n{response_str}", level="DEBUG")

            parsed_data = parse_hqes_response(response_str)

            if parsed_data:
                error_flag, error_g2_hex, error_g1_hex, _, _, _ = parsed_data
                log(f"Parsing Status: ErrFlag={error_flag}, ErrG2={error_g2_hex}, ErrG1={error_g1_hex}", level="DEBUG")

                if error_flag == '0':
                    status = PrinterConfig.STATUS_OK  # Aucune erreur rapportée
                else:
                    try:
                        # Analyser Group 1 (8 bits les plus bas)
                        error_g1_int = int(error_g1_hex, 16)

                        if error_g1_int & PrinterConfig.ERROR_MASK_MEDIA_OUT:
                            status = PrinterConfig.STATUS_MEDIA_OUT
                        elif error_g1_int & PrinterConfig.ERROR_MASK_HEAD_OPEN:
                            status = PrinterConfig.STATUS_HEAD_OPEN
                        # Ajouter d'autres elif pour d'autres erreurs G1 ici si besoin
                        else:
                            # Erreur présente (flag=1) mais pas une qu'on gère spécifiquement
                            status = PrinterConfig.STATUS_ERROR_UNKNOWN
                            log(f"Erreur non gérée détectée: G1={error_g1_hex}, G2={error_g2_hex}", level="WARNING")

                        # On pourrait aussi analyser error_g2_int ici pour PAUSED etc.

                    except ValueError:
                        log(f"Impossible de convertir les valeurs hex du statut: G1='{error_g1_hex}'", level="ERROR")
                        status = PrinterConfig.STATUS_ERROR_UNKNOWN
            else:
                status = PrinterConfig.STATUS_ERROR_UNKNOWN  # Parsing a échoué
        else:
            log("Aucune donnée reçue en réponse à ~HQES.", level="WARNING")
            status = PrinterConfig.STATUS_ERROR_COMM

    except socket.timeout:
        log(f"Timeout lors de la connexion initiale à {printer_ip}:{printer_port} pour statut.", level="ERROR")
        status = PrinterConfig.STATUS_ERROR_COMM
    except socket.error as e:
        log(f"Erreur Socket pour statut: {e}", level="ERROR")
        status = PrinterConfig.STATUS_ERROR_COMM
    except Exception as e:
        log(f"Erreur inattendue dans check_printer_status: {e}", level="ERROR")
        status = PrinterConfig.STATUS_ERROR_UNKNOWN  # Ou ERROR_COMM?
    finally:
        if sock:
            try:
                sock.close()
                log("Socket de statut fermé.", level="DEBUG")
            except socket.error:
                pass  # Ignorer les erreurs à la fermeture
    log(f"Statut Imprimante déterminé: {status}", level="INFO")
    return status


def send_zpl_shipping_label_to_printer(serial_number_to_print, printer_ip, printer_port):
    """
    Envoie la commande ZPL pour l'étiquette simplifiée (carton).
    Retourne True si l'envoi socket a réussi, False sinon.
    """

    zpl_shipping_command = LabelTemplates.get_shipping_label_zpl(serial_number_to_print)
    log(f"Tentative d'impression étiquette carton ZPL pour: {serial_number_to_print}", level="INFO")
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PrinterConfig.SOCKET_TIMEOUT_S)
        sock.connect((printer_ip, printer_port))
        sock.sendall(zpl_shipping_command.encode('utf-8'))
        log(f"ZPL étiquette carton envoyé avec succès pour {serial_number_to_print}", level="INFO")
        return True
    except socket.timeout:
        log(f"Timeout lors de l'envoi ZPL étiquette carton pour {serial_number_to_print}", level="ERROR")
        return False
    except socket.error as e:
        log(f"Erreur Socket lors de l'envoi ZPL étiquette carton pour {serial_number_to_print}: {e}", level="ERROR")
        return False
    except Exception as e:
        log(f"Erreur inattendue lors de l'envoi ZPL étiquette carton pour {serial_number_to_print}: {e}", level="ERROR")
        return False
    finally:
        if sock:
            try:
                sock.close()
            except socket.error:
                pass


def send_zpl_to_printer(serial_number, random_code_for_qr, printer_ip, printer_port):
    """
    Construit la commande ZPL avec le serial_number et random_code_for_qr fournis et l'envoie.
    Retourne True si l'envoi socket a réussi, False sinon.
    """
    zpl_command = LabelTemplates.get_main_label_zpl(serial_number, random_code_for_qr)

    log(f"Tentative d'impression ZPL pour: {serial_number} avec code QR {random_code_for_qr}", level="INFO")
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PrinterConfig.SOCKET_TIMEOUT_S)  # Utiliser le même timeout
        sock.connect((printer_ip, printer_port))
        sock.sendall(zpl_command.encode('utf-8'))
        log(f"ZPL envoyé avec succès pour {serial_number}", level="INFO")
        return True
    except socket.timeout:
        log(f"Timeout lors de l'envoi ZPL pour {serial_number}", level="ERROR")
        return False
    except socket.error as e:
        log(f"Erreur Socket lors de l'envoi ZPL pour {serial_number}: {e}", level="ERROR")
        return False
    except Exception as e:
        log(f"Erreur inattendue lors de l'envoi ZPL pour {serial_number}: {e}", level="ERROR")
        return False
    finally:
        if sock:
            try:
                sock.close()
            except socket.error:
                pass


def send_zpl_v1_label_to_printer(serial_number, random_code_for_qr, fabrication_date_str, printer_ip, printer_port):
    """
    Construit la commande ZPL pour l'étiquette "V1" avec le serial_number,
    random_code_for_qr et la date de fabrication, puis l'envoie.
    Retourne True si l'envoi socket a réussi, False sinon.
    """
    zpl_v1_command = LabelTemplates.get_v1_label_zpl(serial_number, random_code_for_qr, fabrication_date_str)
    log(
        f"Tentative d'impression ZPL V1 pour: {serial_number} avec code QR {random_code_for_qr} et date fab: {fabrication_date_str}",
        level="INFO",
    )
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PrinterConfig.SOCKET_TIMEOUT_S)
        sock.connect((printer_ip, printer_port))
        sock.sendall(zpl_v1_command.encode('utf-8'))
        log(f"ZPL V1 envoyé avec succès pour {serial_number}", level="INFO")
        return True
    except socket.timeout:
        log(f"Timeout lors de l'envoi ZPL V1 pour {serial_number}", level="ERROR")
        return False
    except socket.error as e:
        log(f"Erreur Socket lors de l'envoi ZPL V1 pour {serial_number}: {e}", level="ERROR")
        return False
    except Exception as e:
        log(f"Erreur inattendue lors de l'envoi ZPL V1 pour {serial_number}: {e}", level="ERROR")
        return False
    finally:
        if sock:
            try:
                sock.close()
            except socket.error:
                pass


def printer_worker_thread():
    log("Thread Worker d'impression démarré.", level="INFO")
    CSVSerialManager.initialize_serial_csv()
    while True:
        item_to_print = None
        with queue_lock:
            if print_queue:
                item_to_print = print_queue[0]

        if item_to_print:
            action_type = item_to_print[0]
            serial_number = item_to_print[1]
            random_code_qr = None
            fabrication_date_str = None

            if action_type == "CREATE_NEW_V1" and len(item_to_print) == 4:
                random_code_qr = item_to_print[2]
                fabrication_date_str = item_to_print[3]
            elif action_type == "REPRINT_V1" and len(item_to_print) == 4:  # Nouveau
                random_code_qr = item_to_print[2]
                fabrication_date_str = item_to_print[3]
            elif action_type in ["REPRINT_MAIN_QR", "PRINT_SHIPPING"] and len(item_to_print) == 3:
                random_code_qr = item_to_print[2]  # Sera None pour PRINT_SHIPPING
            else:
                log(f"Item malformé dans la file d'impression: {item_to_print}. Retrait.", level="ERROR")
                with queue_lock:
                    if print_queue and print_queue[0] == item_to_print:
                        print_queue.popleft()
                time.sleep(
                    PrinterConfig.POLL_DELAY_WHEN_IDLE_S)  # Ajusté pour ne pas surcharger en cas d'erreur continue
                continue

            log(
                f"Traitement de la file: {action_type} pour {serial_number}. QR: {random_code_qr}, DateFab: {fabrication_date_str}. File={len(print_queue)}",
                level="INFO",
            )
            current_status = check_printer_status(PrinterConfig.PRINTER_IP, PrinterConfig.PRINTER_PORT)

            if current_status == PrinterConfig.STATUS_OK:
                log(f"Statut imprimante OK. Tentative d'impression ZPL pour {serial_number}.", level="INFO")
                success = False
                if action_type == "CREATE_NEW_V1":
                    if random_code_qr and fabrication_date_str:
                        success = send_zpl_v1_label_to_printer(serial_number, random_code_qr, fabrication_date_str,
                                                               PrinterConfig.PRINTER_IP, PrinterConfig.PRINTER_PORT)
                    else:
                        log(f"Données manquantes pour CREATE_NEW_V1 de {serial_number}.", level="ERROR")
                elif action_type == "REPRINT_V1":  # Nouveau cas
                    if random_code_qr and fabrication_date_str:
                        success = send_zpl_v1_label_to_printer(serial_number, random_code_qr, fabrication_date_str,
                                                               PrinterConfig.PRINTER_IP, PrinterConfig.PRINTER_PORT)
                    else:
                        log(f"Données manquantes pour REPRINT_V1 de {serial_number}.", level="ERROR")
                elif action_type == "REPRINT_MAIN_QR":
                    if random_code_qr:
                        success = send_zpl_to_printer(serial_number, random_code_qr, PrinterConfig.PRINTER_IP,
                                                      PrinterConfig.PRINTER_PORT)
                    else:
                        log(f"Code QR manquant pour REPRINT_MAIN_QR de {serial_number}.", level="ERROR")
                elif action_type == "PRINT_SHIPPING":
                    success = send_zpl_shipping_label_to_printer(serial_number, PrinterConfig.PRINTER_IP,
                                                                 PrinterConfig.PRINTER_PORT)
                else:
                    log(f"Type d'action inconnu: {action_type}", level="ERROR")

                if success:
                    with queue_lock:
                        if print_queue and print_queue[0] == item_to_print:
                            print_queue.popleft()
                            log(
                                f"Envoi ZPL réussi pour {serial_number} ({action_type}), retiré de la file. Restants: {len(print_queue)}",
                                level="INFO",
                            )
                    time.sleep(PrinterConfig.DELAY_AFTER_SUCCESS_S)
                else:
                    log(f"Échec envoi ZPL pour {serial_number} ({action_type}). Sera retenté.", level="ERROR")
                    time.sleep(PrinterConfig.RETRY_DELAY_ON_ERROR_S)
            elif current_status in [
                    PrinterConfig.STATUS_MEDIA_OUT, PrinterConfig.STATUS_HEAD_OPEN, PrinterConfig.STATUS_PAUSED,
                    PrinterConfig.STATUS_ERROR_UNKNOWN
            ]:
                log(f"Impression pour {serial_number} ({action_type}) reportée. Statut: {current_status}",
                    level="WARNING")
                time.sleep(PrinterConfig.RETRY_DELAY_ON_ERROR_S)
            elif current_status == PrinterConfig.STATUS_ERROR_COMM:
                log(f"Impossible de vérifier statut pour {serial_number} ({action_type}) (Erreur Comm). Retenté.",
                    level="WARNING")
                time.sleep(PrinterConfig.RETRY_DELAY_ON_ERROR_S)
            else:
                log(f"Statut non géré: {current_status}", level="WARNING")
                time.sleep(PrinterConfig.RETRY_DELAY_ON_ERROR_S)
        else:
            time.sleep(PrinterConfig.POLL_DELAY_WHEN_IDLE_S)


def create_topic_handlers():
    """Crée les handlers MQTT avec accès aux variables globales."""
    base_handlers = get_topic_handlers()
    print(f"DEBUG: base_handlers keys: {list(base_handlers.keys())}")  # ← Ajout

    wrapped_handlers = {}
    for topic, handler_func in base_handlers.items():
        print(f"DEBUG: Wrapping {topic} -> {handler_func.__name__}")  # ← Ajout
        wrapped_handlers[topic] = lambda payload, h=handler_func: h(payload, print_queue, queue_lock)

    print(f"DEBUG: wrapped_handlers keys: {list(wrapped_handlers.keys())}")  # ← Ajout
    return wrapped_handlers


TOPIC_HANDLERS = create_topic_handlers()


# --- Callbacks MQTT et Main (identiques à v2) ---
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log(f"Connecté au broker MQTT {PrinterConfig.MQTT_BROKER_HOST}:{PrinterConfig.MQTT_BROKER_PORT}", level="INFO")
        log(f"DEBUG: MQTT_TOPIC_TEST_DONE = '{PrinterConfig.MQTT_TOPIC_TEST_DONE}'", level="INFO")
        client.subscribe([(PrinterConfig.MQTT_TOPIC_CREATE_LABEL, 1),
                          (PrinterConfig.MQTT_TOPIC_REQUEST_FULL_REPRINT, 1),
                          (PrinterConfig.MQTT_TOPIC_UPDATE_SHIPPING_TIMESTAMP, 1),
                          (PrinterConfig.MQTT_TOPIC_TEST_DONE, 1), (PrinterConfig.MQTT_TOPIC_CREATE_BATCH_LABELS, 1)])
        log(
            f"Abonné aux topics: create, update_test_done, shipping, reprint_main, request_full_reprint, update_shipping_timestamp",
            level="INFO",
        )
    else:
        log(f"Échec de la connexion MQTT, code de retour: {rc}", level="ERROR")


def on_message(client, userdata, msg):
    """
    Router simple vers les handlers spécifiques selon le topic.
    """
    try:
        payload_str = msg.payload.decode("utf-8")
        log(f"Message reçu sur '{msg.topic}': {payload_str}", level="INFO")

        # Récupère le handler pour ce topic
        handler = TOPIC_HANDLERS.get(msg.topic)
        log(f"DEBUG: Handler trouvé: {handler is not None}", level="INFO")
        if handler:
            # Appelle le handler approprié
            handler(payload_str)
        else:
            log(f"Topic non reconnu ou non géré: {msg.topic}", level="WARNING")
            log(f"DEBUG: Topics disponibles: {list(TOPIC_HANDLERS.keys())}", level="INFO")
    except UnicodeDecodeError:
        log(f"Impossible de décoder le payload reçu sur {msg.topic}. Est-il en UTF-8?", level="ERROR")
    except Exception as e:
        log(f"Erreur lors du traitement du message MQTT sur {msg.topic}: {e}", level="ERROR")


if __name__ == "__main__":
    # ... (identique à v2) ...
    log("Démarrage du script d'écoute MQTT v3 (avec vérification statut)...", level="INFO")
    CSVSerialManager.initialize_serial_csv()  # S'assurer que le CSV existe au démarrage principal

    if "192.168.1." in PrinterConfig.PRINTER_IP:
        log("!!! ATTENTION: IP imprimante semble par défaut. Vérifiez si elle a changé. !!!", level="WARNING")

    worker = threading.Thread(target=printer_worker_thread, name="PrinterWorker", daemon=True)
    worker.start()

    client = mqtt.Client(client_id="raspberrypi_printer_listener_csv")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        log(f"Tentative de connexion au broker MQTT: {PrinterConfig.MQTT_BROKER_HOST}:{PrinterConfig.MQTT_BROKER_PORT}",
            level="INFO")
        client.connect(PrinterConfig.MQTT_BROKER_HOST, PrinterConfig.MQTT_BROKER_PORT, 60)
    except Exception as e:
        log(f"Impossible de se connecter au broker MQTT initialement: {e}", level="ERROR")

    log("Démarrage de la boucle MQTT (écoute en continu)...", level="INFO")
    client.loop_forever()
    log("Boucle MQTT terminée (inattendu).", level="INFO")
