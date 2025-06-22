# print_listener_v3.py
import paho.mqtt.client as mqtt
import socket
import time
import collections
import threading
import re  # Pour l'analyse de la réponse
import random  # Ajouté
import string  # Ajouté
import csv
import os
from datetime import datetime
import json
from src.utils import log
from src.config import LabelTemplates
from src.config import LabelTemplates, PrinterConfig

# --- File d'attente et Verrou ---
print_queue = collections.deque()
queue_lock = threading.Lock()


def generate_random_code(length=6):
    """Génère une chaîne alphanumérique aléatoire de la longueur spécifiée."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(length))


def initialize_serial_csv():
    """Crée le fichier CSV avec les entêtes s'il n'existe pas."""
    if not os.path.exists(PrinterConfig.SERIAL_CSV_FILE):
        try:
            with open(PrinterConfig.SERIAL_CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "TimestampImpression", "NumeroSerie", "CodeAleatoireQR", "TimestampTestDone", "TimestampExpedition",
                    "checker_name"
                ])
            log(f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' créé avec succès.", level="INFO")
        except IOError as e:
            log(f"Impossible de créer le fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}': {e}", level="ERROR")
            # Gérer cette erreur critique, peut-être en arrêtant le script ?
            raise  # Renvoyer l'exception pour arrêter si on ne peut pas créer le CSV


def get_last_serial_from_csv():
    """Lit le CSV et retourne le dernier NumeroSerie enregistré.
       Retourne None si le fichier est vide, n'existe pas, ou en cas d'erreur."""
    try:
        if not os.path.exists(PrinterConfig.SERIAL_CSV_FILE):
            log(f"Le fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' n'existe pas. Aucun dernier sérial.", level="INFO")
            return None
        with open(PrinterConfig.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)  # Lire l'entête
            if not header:  # Fichier vide après entête (ou juste entête)
                log(f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' est vide (ou ne contient que l'entête).",
                    level="INFO")
                return None

            last_row = None
            for row in reader:
                if row:  # S'assurer que la ligne n'est pas vide
                    last_row = row

            if last_row and len(last_row) > 1:  # S'assurer qu'il y a assez de colonnes
                log(f"Dernière ligne lue du CSV: {last_row}", level="DEBUG")
                return last_row[1]  # Le NumeroSerie est dans la deuxième colonne (index 1)
            else:
                log(f"Aucune donnée trouvée dans '{PrinterConfig.SERIAL_CSV_FILE}' après l'entête.", level="INFO")
                return None
    except FileNotFoundError:
        log(f"Le fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' n'a pas été trouvé lors de la lecture du dernier sérial.",
            level="INFO")
        return None
    except IOError as e:
        log(f"Erreur d'IO lors de la lecture de '{PrinterConfig.SERIAL_CSV_FILE}': {e}", level="ERROR")
        return None
    except Exception as e:
        log(f"Erreur inattendue lors de la lecture du dernier sérial de '{PrinterConfig.SERIAL_CSV_FILE}': {e}",
            level="ERROR")
        return None


def generate_next_serial_number():
    """Génère le prochain NumeroSerie en incrémentant le dernier du CSV."""
    last_serial = get_last_serial_from_csv()

    if last_serial is None or not last_serial.startswith(PrinterConfig.SERIAL_PREFIX):
        # Aucun sérial précédent ou format incorrect, commencer à 00000
        numeric_part_int = 0
    else:
        try:
            numeric_str = last_serial[len(PrinterConfig.SERIAL_PREFIX):]
            numeric_part_int = int(numeric_str) + 1
        except ValueError:
            log(f"Impossible de parser la partie numérique du dernier sérial '{last_serial}'. Réinitialisation à 0.",
                level="ERROR")
            numeric_part_int = 0  # Réinitialiser en cas d'erreur

    # Formater la partie numérique avec des zéros initiaux sur la longueur définie
    next_numeric_part_str = str(numeric_part_int).zfill(PrinterConfig.SERIAL_NUMERIC_LENGTH)
    next_serial = f"{PrinterConfig.SERIAL_PREFIX}{next_numeric_part_str}"
    log(f"Prochain NumeroSerie généré: {next_serial}", level="INFO")
    return next_serial


def add_serial_to_csv(timestamp, numero_serie, code_aleatoire_qr, checker_name=""):
    """Ajoute une nouvelle ligne au fichier CSV des sérials."""
    try:
        with open(PrinterConfig.SERIAL_CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, numero_serie, code_aleatoire_qr, "", "", checker_name])
        log(f"Ajouté au CSV: {timestamp}, {numero_serie}, {code_aleatoire_qr}, {checker_name}", level="INFO")
        return True
    except IOError as e:
        log(f"Impossible d'écrire dans le fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}': {e}", level="ERROR")
        return False
    except Exception as e:
        log(f"Erreur inattendue lors de l'écriture dans '{PrinterConfig.SERIAL_CSV_FILE}': {e}", level="ERROR")
        return False


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


def get_details_for_reprint_from_csv(serial_number_to_find):
    """
    Cherche un NumeroSerie dans le CSV et retourne NumeroSerie, CodeAleatoireQR, et TimestampImpression.
    Retourne (None, None, None) si non trouvé.
    """
    try:
        if not os.path.exists(PrinterConfig.SERIAL_CSV_FILE):
            log(
                f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' non trouvé pour la réimpression de {serial_number_to_find}.",
                level="WARNING",
            )
            return None, None, None
        found_serial = None
        found_random_code = None
        found_timestamp_impression = None  # Nouvelle variable
        with open(PrinterConfig.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("NumeroSerie") == serial_number_to_find:
                    found_serial = row["NumeroSerie"]
                    found_random_code = row.get("CodeAleatoireQR")
                    found_timestamp_impression = row.get("TimestampImpression")  # Récupérer le timestamp
        if found_serial and found_random_code and found_timestamp_impression:
            log(
                f"Détails trouvés pour réimpression de {serial_number_to_find}: QR Code {found_random_code}, TimestampImpression {found_timestamp_impression}",
                level="INFO",
            )
            return found_serial, found_random_code, found_timestamp_impression
        else:
            log(
                f"Aucun enregistrement complet (S/N, QR, Timestamp) trouvé pour '{serial_number_to_find}' dans '{PrinterConfig.SERIAL_CSV_FILE}' pour réimpression.",
                level="WARNING",
            )
            return None, None, None
    except Exception as e:
        log(f"Erreur lors de la recherche de {serial_number_to_find} dans CSV pour réimpression: {e}", level="ERROR")
        return None, None, None


def update_csv_with_test_done_timestamp(serial_number_to_update, timestamp_done):
    if not os.path.exists(PrinterConfig.SERIAL_CSV_FILE):
        log(
            f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' non trouvé. Impossible de mettre à jour TimestampTestDone pour {serial_number_to_update}.",
            level="ERROR",
        )
        return False
    rows = []
    updated = False
    try:
        with open(PrinterConfig.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f_read:
            reader = csv.reader(f_read)
            header = next(reader)
            rows.append(header)
            for row in reader:
                if row and len(row) > 1 and row[1] == serial_number_to_update:
                    if len(row) > 3:
                        row[3] = timestamp_done
                    else:
                        row.extend([""] * (4 - len(row)))
                        row[3] = timestamp_done
                    updated = True
                    log(
                        f"Ligne pour {serial_number_to_update} marquée avec TimestampTestDone: {timestamp_done}",
                        level="INFO",
                    )
                rows.append(row)
        if updated:
            with open(PrinterConfig.SERIAL_CSV_FILE, mode='w', newline='', encoding='utf-8') as f_write:
                writer = csv.writer(f_write)
                writer.writerows(rows)
            log(
                f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' mis à jour avec TimestampTestDone pour {serial_number_to_update}.",
                level="INFO",
            )
            time.sleep(0.1)
            return True
        else:
            log(
                f"Aucun NumeroSerie correspondant à '{serial_number_to_update}' trouvé dans '{PrinterConfig.SERIAL_CSV_FILE}' pour mettre à jour TimestampTestDone.",
                level="WARNING",
            )
            return False
    except Exception as e:
        log(
            f"Erreur lors de la mise à jour de TimestampTestDone pour {serial_number_to_update} dans CSV: {e}",
            level="ERROR",
        )
        return False


def update_csv_with_shipping_timestamp(serial_number_to_update, timestamp_shipping_iso):
    """
    Met à jour le TimestampExpedition pour un NumeroSerie donné dans le CSV.
    """
    if not os.path.exists(PrinterConfig.SERIAL_CSV_FILE):
        log(
            f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' non trouvé. Impossible de mettre à jour TimestampExpedition pour {serial_number_to_update}.",
            level="ERROR",
        )
        return False

    rows_to_write = []
    updated_in_memory = False
    header_indices = {}

    try:
        with open(PrinterConfig.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f_read:
            reader = csv.reader(f_read)
            header = next(reader, None)
            if not header:
                log(f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' est vide ou n'a pas d'entête.", level="ERROR")
                return False
            rows_to_write.append(header)

            # Créer un dictionnaire pour les indices des colonnes
            for i, col_name in enumerate(header):
                header_indices[col_name] = i

            # Vérifier si les colonnes nécessaires sont présentes
            if "NumeroSerie" not in header_indices or "TimestampExpedition" not in header_indices:
                log(
                    f"Les colonnes 'NumeroSerie' ou 'TimestampExpedition' sont manquantes dans l'entête de {PrinterConfig.SERIAL_CSV_FILE}.",
                    level="ERROR",
                )
                return False

            idx_serial = header_indices["NumeroSerie"]
            idx_shipping_ts = header_indices["TimestampExpedition"]

            for row in reader:
                if row and len(row) > idx_serial and row[idx_serial] == serial_number_to_update:
                    # S'assurer que la ligne est assez longue pour l'index de TimestampExpedition
                    while len(row) <= idx_shipping_ts:
                        row.append("")  # Ajouter des colonnes vides si nécessaire
                    row[idx_shipping_ts] = timestamp_shipping_iso
                    updated_in_memory = True
                    log(
                        f"Ligne pour {serial_number_to_update} sera mise à jour avec TimestampExpedition: {timestamp_shipping_iso}",
                        level="INFO",
                    )
                rows_to_write.append(row)

        if updated_in_memory:
            with open(PrinterConfig.SERIAL_CSV_FILE, mode='w', newline='', encoding='utf-8') as f_write:
                writer = csv.writer(f_write)
                writer.writerows(rows_to_write)
            log(
                f"Fichier CSV '{PrinterConfig.SERIAL_CSV_FILE}' mis à jour avec TimestampExpedition pour {serial_number_to_update}.",
                level="INFO",
            )
            return True
        else:
            log(
                f"Aucun NumeroSerie correspondant à '{serial_number_to_update}' trouvé dans '{PrinterConfig.SERIAL_CSV_FILE}' pour mettre à jour TimestampExpedition.",
                level="WARNING",
            )
            return False
    except Exception as e:
        log(f"Erreur lors de la mise à jour de TimestampExpedition pour {serial_number_to_update} dans CSV: {e}",
            level="ERROR")
        return False


def printer_worker_thread():
    log("Thread Worker d'impression démarré.", level="INFO")
    initialize_serial_csv()
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


# --- Callbacks MQTT et Main (identiques à v2) ---


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log(f"Connecté au broker MQTT {PrinterConfig.MQTT_BROKER_HOST}:{PrinterConfig.MQTT_BROKER_PORT}", level="INFO")
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
    global print_queue
    try:
        payload_str = msg.payload.decode("utf-8")
        log(f"Message reçu sur '{msg.topic}': {payload_str}", level="INFO")

        if msg.topic == PrinterConfig.MQTT_TOPIC_CREATE_LABEL:
            data = json.loads(msg.payload.decode("utf-8"))
            checker = data.get("checker_name")
            # -- CHECKER_NAME --
            if not checker:
                log("Demande de création reçue sans nom de checkeur. Annulation.", level="WARNING")
                return
            # -- SERIAL_NUMBER --
            next_serial = generate_next_serial_number()
            if not next_serial:
                log("Impossible de générer un nouveau numéro de série. Action annulée.", level="ERROR")
                return
            random_qr = generate_random_code()
            dt_impression = datetime.now()
            timestamp_impression_iso = dt_impression.isoformat()
            if not add_serial_to_csv(timestamp_impression_iso, next_serial, random_qr, checker):
                log(f"Échec de l'enregistrement dans le CSV pour {next_serial}. Action d'impression annulée.",
                    level="ERROR")
                return
            # -- ENVOI ZPL --
            fabrication_date_for_label = dt_impression.strftime("%d/%m/%Y")
            with queue_lock:
                print_queue.append(("CREATE_NEW_V1", next_serial, random_qr, fabrication_date_for_label))
                log(f"'{next_serial}' (validé par {checker}) ajouté à la file d'impression.", level="INFO")

        elif msg.topic == PrinterConfig.MQTT_TOPIC_REQUEST_FULL_REPRINT:  # Nouveau bloc pour la réimpression complète
            serial_to_reprint = payload_str
            if serial_to_reprint:
                _serial, random_code, original_ts_iso = get_details_for_reprint_from_csv(serial_to_reprint)  #
                if _serial and random_code and original_ts_iso:
                    try:
                        # Convertir le timestamp ISO original en objet datetime, puis en format DD/MM/YYYY
                        original_dt_impression = datetime.fromisoformat(original_ts_iso)
                        fabrication_date_for_v1_reprint = original_dt_impression.strftime("%d/%m/%Y")

                        with queue_lock:
                            # 1. Étiquette V1 (avec date de fabrication originale)
                            print_queue.append(("REPRINT_V1", _serial, random_code, fabrication_date_for_v1_reprint))
                            # 2. Étiquette principale standard (sans date de fab ni V1)
                            print_queue.append(("REPRINT_MAIN_QR", _serial, random_code))
                            # 3. Étiquette d'expédition
                            print_queue.append(("PRINT_SHIPPING", _serial, None))
                        log(
                            f"Demande de réimpression complète pour S/N {_serial} (QR: {random_code}, Date Fab V1: {fabrication_date_for_v1_reprint}) ajoutée à la file. {len(print_queue)} items en attente.",
                            level="INFO",
                        )
                    except ValueError as ve:
                        log(
                            f"Erreur de format de date pour TimestampImpression '{original_ts_iso}' du S/N {_serial}: {ve}",
                            level="ERROR",
                        )
                    except Exception as e:
                        log(
                            f"Erreur inattendue lors de la préparation de la réimpression complète pour S/N {_serial}: {e}",
                            level="ERROR",
                        )
                else:
                    log(
                        f"Impossible de trouver les détails complets (S/N, QR, Timestamp) pour réimprimer S/N {serial_to_reprint}. Non ajouté à la file.",
                        level="ERROR",
                    )
            else:
                log(f"Payload vide reçu pour {PrinterConfig.MQTT_TOPIC_REQUEST_FULL_REPRINT}", level="ERROR")
        elif msg.topic == PrinterConfig.MQTT_TOPIC_CREATE_BATCH_LABELS:  # << NOUVEAU BLOC DE TRAITEMENT
            try:
                num_repetitions = int(payload_str)
                if num_repetitions <= 0:
                    log(f"Nombre de répétitions invalide pour {PrinterConfig.MQTT_TOPIC_CREATE_BATCH_LABELS}: {num_repetitions}. Doit être > 0.",
                        level="ERROR")
                    return

                log(f"Demande de création de {num_repetitions} lot(s) complet(s) d'étiquettes via {PrinterConfig.MQTT_TOPIC_CREATE_BATCH_LABELS}.",
                    level="INFO")

                for i in range(num_repetitions):
                    log(f"Traitement du lot {i+1}/{num_repetitions}", level="INFO")

                    # --- Partie 1: Simulation de la création d'une nouvelle étiquette V1 ---
                    next_serial = generate_next_serial_number()
                    if not next_serial:
                        log(f"Lot {i+1}: Impossible de générer un nouveau numéro de série. Annulation de ce lot.",
                            level="ERROR")
                        continue  # Passer au lot suivant

                    random_qr_code = generate_random_code()  # Renommé pour clarté
                    dt_impression = datetime.now()
                    timestamp_impression_iso = dt_impression.isoformat()
                    fabrication_date_for_label = dt_impression.strftime("%d/%m/%Y")

                    if not add_serial_to_csv(timestamp_impression_iso, next_serial, random_qr_code):
                        log(f"Lot {i+1}: Échec de l'enregistrement dans le CSV pour {next_serial}. Annulation de ce lot.",
                            level="ERROR")
                        continue  # Passer au lot suivant

                    with queue_lock:
                        print_queue.append(("CREATE_NEW_V1", next_serial, random_qr_code, fabrication_date_for_label))
                    log(f"Lot {i+1}: Étiquette V1 pour '{next_serial}' (QR: '{random_qr_code}', Date fab: '{fabrication_date_for_label}') ajoutée à la file.",
                        level="INFO")

                    # --- Partie 2: Simulation des actions de 'test_done' pour ce nouveau serial ---
                    # Générer un timestamp pour 'test_done' (peut être le même que l'impression ou actuel)
                    ts_test_done = datetime.now().isoformat()

                    if update_csv_with_test_done_timestamp(next_serial, ts_test_done):
                        log(f"Lot {i+1}: CSV mis à jour avec TimestampTestDone pour {next_serial}", level="INFO")
                    else:
                        # Loggue une erreur mais continue le processus d'ajout à la file d'impression pour ce lot
                        log(f"Lot {i+1} ÉCHEC: CSV non mis à jour avec TimestampTestDone pour {next_serial}.",
                            level="ERROR")

                    # Ajouter l'étiquette d'expédition à la file
                    with queue_lock:
                        print_queue.append(("PRINT_SHIPPING", next_serial, None))
                    log(f"Lot {i+1}: Étiquette carton pour '{next_serial}' ajoutée à la file.", level="INFO")

                    # Ajouter l'étiquette QR principale à la file
                    # Nous utilisons random_qr_code déjà généré et enregistré.
                    with queue_lock:
                        print_queue.append(("REPRINT_MAIN_QR", next_serial, random_qr_code))
                    log(f"Lot {i+1}: Réimpression étiquette QR standard pour '{next_serial}' (QR: '{random_qr_code}') ajoutée à la file.",
                        level="INFO")

                    log(f"Lot {i+1}/{num_repetitions} traité et ajouté à la file. Taille actuelle de la file: {len(print_queue)}",
                        level="INFO")
                    # Optionnel: petite pause si N est très grand pour ne pas surcharger trop vite ou pour la lisibilité des logs.
                    # time.sleep(0.1)

                log(f"Tous les {num_repetitions} lots ont été ajoutés à la file d'impression.", level="INFO")

            except ValueError:
                log(f"Payload invalide pour {msg.topic}: '{payload_str}'. Doit être un entier.", level="ERROR")
            except Exception as e:
                log(f"Erreur inattendue lors du traitement de {msg.topic} pour le lot: {e}", level="ERROR")

        elif msg.topic == PrinterConfig.MQTT_TOPIC_TEST_DONE:  # Ou directement "printer/test_done"
            try:
                payload_str = msg.payload.decode("utf-8")  # Assurez-vous que c'est ici aussi
                log(f"Message reçu sur '{msg.topic}': {payload_str}",
                    level="INFO")  # Déplacé ici pour logger tous les messages
                data = json.loads(payload_str)
                serial_to_process = data.get("serial_number")
                ts_test_done = data.get("timestamp_test_done")

                if serial_to_process and ts_test_done:
                    log(f"Traitement consolidé pour test_done S/N {serial_to_process} à {ts_test_done}", level="INFO")

                    # Action 1: Update CSV with TestDone timestamp
                    if update_csv_with_test_done_timestamp(serial_to_process, ts_test_done):  #
                        log(f"Action 1 (test_done): CSV mis à jour pour {serial_to_process}", level="INFO")
                    else:
                        log(f"Action 1 (test_done) ÉCHEC: CSV non mis à jour pour {serial_to_process}", level="ERROR")

                    # Action 2: Add shipping label to print queue
                    with queue_lock:
                        print_queue.append(("PRINT_SHIPPING", serial_to_process, None))  #
                    log(f"Action 2 (test_done): Étiquette carton pour '{serial_to_process}' ajoutée à la file. Taille: {len(print_queue)}",
                        level="INFO")

                    # Action 3: Add main QR label to print queue
                    _serial_reprint, random_code_reprint, _ = get_details_for_reprint_from_csv(serial_to_process)  #
                    if _serial_reprint and random_code_reprint:
                        with queue_lock:
                            print_queue.append(("REPRINT_MAIN_QR", _serial_reprint, random_code_reprint))  #
                        log(f"Action 3 (test_done): Réimpression étiquette QR standard pour '{_serial_reprint}' (QR: {random_code_reprint}) ajoutée à la file. Taille: {len(print_queue)}",
                            level="INFO")
                    else:
                        log(f"Action 3 (test_done) ÉCHEC: Impossible de trouver les détails (S/N, QR) pour réimprimer l'étiquette QR standard de {serial_to_process}.",
                            level="ERROR")
                else:
                    log(f"Données manquantes pour traitement consolidé test_done: {payload_str}", level="ERROR")
            except json.JSONDecodeError:
                log(f"Payload JSON invalide pour {msg.topic}: {payload_str}",
                    level="ERROR")  # msg.topic au lieu de MQTT_TOPIC_TEST_DONE
            except UnicodeDecodeError:  # Ajouté pour être cohérent
                log(f"Impossible de décoder le payload reçu sur {msg.topic}. Est-il en UTF-8?", level="ERROR")
            except Exception as e:
                log(f"Erreur traitement {msg.topic}: {e}", level="ERROR")  # msg.topic au lieu de MQTT_TOPIC_TEST_DONE
        elif msg.topic == PrinterConfig.MQTT_TOPIC_UPDATE_SHIPPING_TIMESTAMP:  # Nouveau bloc
            try:
                data = json.loads(payload_str)
                serial_to_update = data.get("serial_number")
                ts_shipping = data.get("timestamp_expedition")
                if serial_to_update and ts_shipping:
                    log(
                        f"Demande de mise à jour TimestampExpedition pour S/N {serial_to_update} à {ts_shipping}",
                        level="INFO",
                    )
                    update_csv_with_shipping_timestamp(serial_to_update, ts_shipping)
                else:
                    log(f"Données manquantes pour mise à jour TimestampExpedition: {payload_str}", level="ERROR")
            except json.JSONDecodeError:
                log(f"Payload JSON invalide pour {PrinterConfig.MQTT_TOPIC_UPDATE_SHIPPING_TIMESTAMP}: {payload_str}",
                    level="ERROR")
            except Exception as e:
                log(f"Erreur traitement {PrinterConfig.MQTT_TOPIC_UPDATE_SHIPPING_TIMESTAMP}: {e}", level="ERROR")
    except UnicodeDecodeError:
        log(f"Impossible de décoder le payload reçu sur {msg.topic}. Est-il en UTF-8?", level="ERROR")
    except Exception as e:
        log(f"Erreur lors du traitement du message MQTT: {e}", level="ERROR")


if __name__ == "__main__":
    # ... (identique à v2) ...
    log("Démarrage du script d'écoute MQTT v3 (avec vérification statut)...", level="INFO")
    initialize_serial_csv()  # S'assurer que le CSV existe au démarrage principal

    if PrinterConfig.PRINTER_IP == "192.168.1.100":
        log("!!! ATTENTION: L'adresse IP de l'imprimante n'a peut-être pas été configurée. Vérifiez PRINTER_IP. !!!",
            level="WARNING")

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
