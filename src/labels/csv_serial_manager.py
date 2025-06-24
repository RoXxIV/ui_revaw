# -*- coding: utf-8 -*-
"""
Gestionnaire pour les fichiers CSV et la génération de numéros de série.
"""
import csv
import os
import random
import string
from datetime import datetime
from src.ui.utils import log


class CSVSerialManager:
    """
    Classe pour gérer les opérations CSV et la génération de numéros de série.
    """
    # Configuration
    SERIAL_CSV_FILE = "printed_serials.csv"
    SERIAL_PREFIX = "RW-48v271"
    SERIAL_NUMERIC_LENGTH = 4

    @staticmethod
    def generate_random_code(length=6):
        """Génère une chaîne alphanumérique aléatoire de la longueur spécifiée."""
        characters = string.ascii_letters + string.digits
        return ''.join(random.choice(characters) for i in range(length))

    @staticmethod
    def initialize_serial_csv():
        """Crée le fichier CSV avec les entêtes s'il n'existe pas."""
        if not os.path.exists(CSVSerialManager.SERIAL_CSV_FILE):
            try:
                with open(CSVSerialManager.SERIAL_CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "TimestampImpression", "NumeroSerie", "CodeAleatoireQR", "TimestampTestDone",
                        "TimestampExpedition", "checker_name"
                    ])
                log(f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' créé avec succès.", level="INFO")
            except IOError as e:
                log(f"Impossible de créer le fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}': {e}", level="ERROR")
                raise

    @staticmethod
    def get_last_serial_from_csv():
        """Lit le CSV et retourne le dernier NumeroSerie enregistré.
           Retourne None si le fichier est vide, n'existe pas, ou en cas d'erreur."""
        try:
            if not os.path.exists(CSVSerialManager.SERIAL_CSV_FILE):
                log(f"Le fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' n'existe pas. Aucun dernier sérial.",
                    level="INFO")
                return None
            with open(CSVSerialManager.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    log(f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' est vide (ou ne contient que l'entête).",
                        level="INFO")
                    return None

                last_row = None
                for row in reader:
                    if row:
                        last_row = row

                if last_row and len(last_row) > 1:
                    log(f"Dernière ligne lue du CSV: {last_row}", level="DEBUG")
                    return last_row[1]
                else:
                    log(f"Aucune donnée trouvée dans '{CSVSerialManager.SERIAL_CSV_FILE}' après l'entête.",
                        level="INFO")
                    return None
        except FileNotFoundError:
            log(f"Le fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' n'a pas été trouvé lors de la lecture du dernier sérial.",
                level="INFO")
            return None
        except IOError as e:
            log(f"Erreur d'IO lors de la lecture de '{CSVSerialManager.SERIAL_CSV_FILE}': {e}", level="ERROR")
            return None
        except Exception as e:
            log(f"Erreur inattendue lors de la lecture du dernier sérial de '{CSVSerialManager.SERIAL_CSV_FILE}': {e}",
                level="ERROR")
            return None

    @staticmethod
    def generate_next_serial_number():
        """Génère le prochain NumeroSerie en incrémentant le dernier du CSV."""
        last_serial = CSVSerialManager.get_last_serial_from_csv()

        if last_serial is None or not last_serial.startswith(CSVSerialManager.SERIAL_PREFIX):
            numeric_part_int = 0
        else:
            try:
                numeric_str = last_serial[len(CSVSerialManager.SERIAL_PREFIX):]
                numeric_part_int = int(numeric_str) + 1
            except ValueError:
                log(f"Impossible de parser la partie numérique du dernier sérial '{last_serial}'. Réinitialisation à 0.",
                    level="ERROR")
                numeric_part_int = 0

        next_numeric_part_str = str(numeric_part_int).zfill(CSVSerialManager.SERIAL_NUMERIC_LENGTH)
        next_serial = f"{CSVSerialManager.SERIAL_PREFIX}{next_numeric_part_str}"
        log(f"Prochain NumeroSerie généré: {next_serial}", level="INFO")
        return next_serial

    @staticmethod
    def add_serial_to_csv(timestamp, numero_serie, code_aleatoire_qr, checker_name=""):
        """Ajoute une nouvelle ligne au fichier CSV des sérials."""
        try:
            with open(CSVSerialManager.SERIAL_CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, numero_serie, code_aleatoire_qr, "", "", checker_name])
            log(f"Ajouté au CSV: {timestamp}, {numero_serie}, {code_aleatoire_qr}, {checker_name}", level="INFO")
            return True
        except IOError as e:
            log(f"Impossible d'écrire dans le fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}': {e}", level="ERROR")
            return False
        except Exception as e:
            log(f"Erreur inattendue lors de l'écriture dans '{CSVSerialManager.SERIAL_CSV_FILE}': {e}", level="ERROR")
            return False

    @staticmethod
    def update_csv_with_test_done_timestamp(serial_number_to_update, timestamp_done):
        """Met à jour le TimestampTestDone pour un NumeroSerie donné dans le CSV."""
        if not os.path.exists(CSVSerialManager.SERIAL_CSV_FILE):
            log(
                f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' non trouvé. Impossible de mettre à jour TimestampTestDone pour {serial_number_to_update}.",
                level="ERROR",
            )
            return False
        rows = []
        updated = False
        try:
            with open(CSVSerialManager.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f_read:
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
                with open(CSVSerialManager.SERIAL_CSV_FILE, mode='w', newline='', encoding='utf-8') as f_write:
                    writer = csv.writer(f_write)
                    writer.writerows(rows)
                log(
                    f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' mis à jour avec TimestampTestDone pour {serial_number_to_update}.",
                    level="INFO",
                )
                return True
            else:
                log(
                    f"Aucun NumeroSerie correspondant à '{serial_number_to_update}' trouvé dans '{CSVSerialManager.SERIAL_CSV_FILE}' pour mettre à jour TimestampTestDone.",
                    level="WARNING",
                )
                return False
        except Exception as e:
            log(
                f"Erreur lors de la mise à jour de TimestampTestDone pour {serial_number_to_update} dans CSV: {e}",
                level="ERROR",
            )
            return False

    @staticmethod
    def update_csv_with_shipping_timestamp(serial_number_to_update, timestamp_shipping_iso):
        """Met à jour le TimestampExpedition pour un NumeroSerie donné dans le CSV."""
        if not os.path.exists(CSVSerialManager.SERIAL_CSV_FILE):
            log(
                f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' non trouvé. Impossible de mettre à jour TimestampExpedition pour {serial_number_to_update}.",
                level="ERROR",
            )
            return False

        rows_to_write = []
        updated_in_memory = False
        header_indices = {}

        try:
            with open(CSVSerialManager.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f_read:
                reader = csv.reader(f_read)
                header = next(reader, None)
                if not header:
                    log(f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' est vide ou n'a pas d'entête.",
                        level="ERROR")
                    return False
                rows_to_write.append(header)

                for i, col_name in enumerate(header):
                    header_indices[col_name] = i

                if "NumeroSerie" not in header_indices or "TimestampExpedition" not in header_indices:
                    log(
                        f"Les colonnes 'NumeroSerie' ou 'TimestampExpedition' sont manquantes dans l'entête de {CSVSerialManager.SERIAL_CSV_FILE}.",
                        level="ERROR",
                    )
                    return False

                idx_serial = header_indices["NumeroSerie"]
                idx_shipping_ts = header_indices["TimestampExpedition"]

                for row in reader:
                    if row and len(row) > idx_serial and row[idx_serial] == serial_number_to_update:
                        while len(row) <= idx_shipping_ts:
                            row.append("")
                        row[idx_shipping_ts] = timestamp_shipping_iso
                        updated_in_memory = True
                        log(
                            f"Ligne pour {serial_number_to_update} sera mise à jour avec TimestampExpedition: {timestamp_shipping_iso}",
                            level="INFO",
                        )
                    rows_to_write.append(row)

            if updated_in_memory:
                with open(CSVSerialManager.SERIAL_CSV_FILE, mode='w', newline='', encoding='utf-8') as f_write:
                    writer = csv.writer(f_write)
                    writer.writerows(rows_to_write)
                log(
                    f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' mis à jour avec TimestampExpedition pour {serial_number_to_update}.",
                    level="INFO",
                )
                return True
            else:
                log(
                    f"Aucun NumeroSerie correspondant à '{serial_number_to_update}' trouvé dans '{CSVSerialManager.SERIAL_CSV_FILE}' pour mettre à jour TimestampExpedition.",
                    level="WARNING",
                )
                return False
        except Exception as e:
            log(f"Erreur lors de la mise à jour de TimestampExpedition pour {serial_number_to_update} dans CSV: {e}",
                level="ERROR")
            return False

    @staticmethod
    def get_details_for_reprint_from_csv(serial_number_to_find):
        """
        Cherche un NumeroSerie dans le CSV et retourne NumeroSerie, CodeAleatoireQR, et TimestampImpression.
        Retourne (None, None, None) si non trouvé.
        """
        try:
            if not os.path.exists(CSVSerialManager.SERIAL_CSV_FILE):
                log(
                    f"Fichier CSV '{CSVSerialManager.SERIAL_CSV_FILE}' non trouvé pour la réimpression de {serial_number_to_find}.",
                    level="WARNING",
                )
                return None, None, None
            found_serial = None
            found_random_code = None
            found_timestamp_impression = None
            with open(CSVSerialManager.SERIAL_CSV_FILE, mode='r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("NumeroSerie") == serial_number_to_find:
                        found_serial = row["NumeroSerie"]
                        found_random_code = row.get("CodeAleatoireQR")
                        found_timestamp_impression = row.get("TimestampImpression")
            if found_serial and found_random_code and found_timestamp_impression:
                log(
                    f"Détails trouvés pour réimpression de {serial_number_to_find}: QR Code {found_random_code}, TimestampImpression {found_timestamp_impression}",
                    level="INFO",
                )
                return found_serial, found_random_code, found_timestamp_impression
            else:
                log(
                    f"Aucun enregistrement complet (S/N, QR, Timestamp) trouvé pour '{serial_number_to_find}' dans '{CSVSerialManager.SERIAL_CSV_FILE}' pour réimpression.",
                    level="WARNING",
                )
                return None, None, None
        except Exception as e:
            log(f"Erreur lors de la recherche de {serial_number_to_find} dans CSV pour réimpression: {e}",
                level="ERROR")
            return None, None, None
