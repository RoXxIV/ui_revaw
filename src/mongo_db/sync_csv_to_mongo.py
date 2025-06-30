#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de synchronisation CSV vers MongoDB - Version améliorée
Conçu pour fonctionner via CRON la nuit, hors production.
"""

import os
import sys
import csv
import json
import time
import glob
from datetime import datetime
from pymongo import MongoClient, UpdateOne
from pymongo.errors import (ConnectionFailure, ServerSelectionTimeoutError, BulkWriteError, PyMongoError)

# 📌 Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(SCRIPT_DIR, '../../printed_serials.csv')
DATA_FOLDER = os.path.join(SCRIPT_DIR, '../../data')
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'mongo_config.json')

# Configuration retry et timeouts
MAX_RETRIES = 3
RETRY_DELAY = 5  # secondes
CONNECTION_TIMEOUT = 10  # secondes
SERVER_SELECTION_TIMEOUT = 5  # secondes

IGNORED_FOLDERS = {'archive_fails'}
BANC_FOLDERS = [f"banc{i}" for i in range(1, 5)]


def log_message(message, level="INFO"):
    """Simple logging avec timestamp vers console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def log_to_file(message, level="INFO"):
    """Log uniquement les événements importants dans un fichier."""
    # Seulement les niveaux importants dans le fichier
    if level not in ["INFO", "WARNING", "ERROR"]:
        return

    log_file = os.path.join(SCRIPT_DIR, "mongo_sync.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{level}] {message}\n")
    except Exception:
        # Si on peut pas écrire dans le log, on continue silencieusement
        pass


def load_config():
    """Charge la configuration MongoDB avec gestion d'erreurs."""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        log_message("Configuration MongoDB chargée avec succès")
        return config
    except FileNotFoundError:
        log_message(f"Fichier de configuration non trouvé: {CONFIG_FILE}", "ERROR")
        sys.exit(1)
    except json.JSONDecodeError as e:
        log_message(f"Erreur JSON dans la configuration: {e}", "ERROR")
        sys.exit(1)


def create_mongo_client_with_retry(config):
    """Crée une connexion MongoDB avec retry et timeouts optimisés."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log_message(f"Tentative de connexion MongoDB ({attempt}/{MAX_RETRIES})")

            client = MongoClient(
                config["MONGO_URI"],
                serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT * 1000,
                connectTimeoutMS=CONNECTION_TIMEOUT * 1000,
                socketTimeoutMS=30000,  # 30s pour les opérations
                retryWrites=True,
                retryReads=True)

            # Test de connexion avec ping
            client.admin.command('ping')
            log_message("Connexion MongoDB établie avec succès")
            log_to_file("Connexion MongoDB établie avec succès")
            return client

        except ServerSelectionTimeoutError:
            log_message(f"Timeout serveur MongoDB (tentative {attempt})", "WARNING")
        except ConnectionFailure as e:
            log_message(f"Échec connexion MongoDB: {e} (tentative {attempt})", "WARNING")
        except Exception as e:
            log_message(f"Erreur inattendue MongoDB: {e} (tentative {attempt})", "ERROR")

        if attempt < MAX_RETRIES:
            wait_time = RETRY_DELAY * attempt  # Backoff progressif
            log_message(f"Retry dans {wait_time} secondes...")
            time.sleep(wait_time)

    log_message("Impossible de se connecter à MongoDB après toutes les tentatives", "ERROR")
    log_to_file("Impossible de se connecter à MongoDB après toutes les tentatives", "ERROR")
    sys.exit(1)


def parse_iso_safe(timestamp_str):
    """Parse un timestamp ISO avec gestion d'erreurs."""
    if not timestamp_str:
        return None
    try:
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        log_message(f"Timestamp invalide ignoré: {timestamp_str}", "WARNING")
        return None


def get_config_data_for_serial(serial):
    """Recherche les données config.json pour un numéro de série."""
    for banc in BANC_FOLDERS:
        if banc in IGNORED_FOLDERS:
            continue

        banc_path = os.path.join(DATA_FOLDER, banc)
        if not os.path.isdir(banc_path):
            continue

        pattern = os.path.join(banc_path, f"*-{serial}")
        matching_dirs = glob.glob(pattern)

        for match in matching_dirs:
            config_path = os.path.join(match, "config.json")
            if os.path.isfile(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    log_message(f"Erreur lecture config pour {serial}: {e}", "WARNING")
    return None


def validate_csv_file():
    """Valide l'existence et l'accessibilité du fichier CSV."""
    if not os.path.exists(CSV_PATH):
        log_message(f"Fichier CSV non trouvé: {CSV_PATH}", "ERROR")
        sys.exit(1)

    try:
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            header = next(reader, None)
            if not header:
                log_message("Fichier CSV vide ou sans en-tête", "ERROR")
                sys.exit(1)

            required_columns = ["NumeroSerie", "TimestampImpression", "CodeAleatoireQR"]
            missing_columns = [col for col in required_columns if col not in header]
            if missing_columns:
                log_message(f"Colonnes manquantes dans le CSV: {missing_columns}", "ERROR")
                sys.exit(1)

        log_message("Validation du fichier CSV réussie")

    except Exception as e:
        log_message(f"Erreur lors de la validation du CSV: {e}", "ERROR")
        sys.exit(1)


def process_csv_with_error_handling(collection):
    """Traite le CSV avec gestion d'erreurs robuste."""
    successful_operations = 0
    failed_operations = 0

    try:
        with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            operations = []
            batch_size = 100  # Traitement par lots

            for row_num, row in enumerate(reader, 1):
                try:
                    # Construction du document
                    doc = {
                        "TimestampImpression": parse_iso_safe(row.get("TimestampImpression")),
                        "NumeroSerie": row.get("NumeroSerie", "").strip(),
                        "CodeAleatoireQR": row.get("CodeAleatoireQR", "").strip(),
                        "TimestampTestDone": parse_iso_safe(row.get("TimestampTestDone")),
                        "TimestampExpedition": parse_iso_safe(row.get("TimestampExpedition")),
                        "version": row.get("version", "").strip()
                    }

                    # Validation basique
                    if not doc["NumeroSerie"]:
                        log_message(f"Ligne {row_num}: NumeroSerie vide, ignorée", "WARNING")
                        failed_operations += 1
                        continue

                    # Enrichissement avec config.json
                    config_data = get_config_data_for_serial(doc["NumeroSerie"])
                    if config_data:
                        for field in [
                                "capacity_ah", "capacity_wh", "ri_discharge_average", "ri_charge_average",
                                "diffusion_discharge_average", "diffusion_charge_average", "delta_ri_cells",
                                "delta_diffusion_cells"
                        ]:
                            if field in config_data:
                                doc[field] = config_data[field]

                    # Ajout à la batch
                    operations.append(UpdateOne({"NumeroSerie": doc["NumeroSerie"]}, {"$set": doc}, upsert=True))

                    # Exécution par lots
                    if len(operations) >= batch_size:
                        successful_batch, failed_batch = execute_batch_operations(collection, operations)
                        successful_operations += successful_batch
                        failed_operations += failed_batch
                        operations = []

                except Exception as e:
                    log_message(f"Erreur traitement ligne {row_num}: {e}", "WARNING")
                    failed_operations += 1
                    continue

            # Traitement du dernier lot
            if operations:
                successful_batch, failed_batch = execute_batch_operations(collection, operations)
                successful_operations += successful_batch
                failed_operations += failed_batch

    except Exception as e:
        log_message(f"Erreur critique lors du traitement du CSV: {e}", "ERROR")
        return successful_operations, failed_operations + 1

    return successful_operations, failed_operations


def execute_batch_operations(collection, operations):
    """Exécute une batch d'opérations avec gestion d'erreurs."""
    try:
        result = collection.bulk_write(operations, ordered=False)
        successful = result.upserted_count + result.modified_count
        return successful, 0

    except BulkWriteError as bwe:
        # Gestion des erreurs partielles dans les bulk operations
        result = bwe.details
        successful = result.get('nUpserted', 0) + result.get('nModified', 0)
        failed = len(result.get('writeErrors', []))

        log_message(f"Bulk write partiel: {successful} réussies, {failed} échouées", "WARNING")
        log_to_file(f"Bulk write partiel: {successful} réussies, {failed} échouées", "WARNING")

        # Log des erreurs spécifiques (limité pour éviter le spam)
        for error in result.get('writeErrors', [])[:3]:  # Max 3 erreurs loggées
            log_message(f"Erreur write: {error.get('errmsg', 'Erreur inconnue')}", "WARNING")

        return successful, failed

    except Exception as e:
        log_message(f"Erreur lors de l'exécution batch: {e}", "ERROR")
        return 0, len(operations)


def create_indexes_safely(collection):
    """Crée les index de manière sécurisée."""
    try:
        # Index unique sur NumeroSerie (si pas déjà existant)
        existing_indexes = collection.list_indexes()
        index_names = [idx['name'] for idx in existing_indexes]

        if 'NumeroSerie_1' not in index_names:
            collection.create_index("NumeroSerie", unique=True)
            log_message("Index unique créé sur NumeroSerie")
        else:
            log_message("Index sur NumeroSerie déjà existant")

    except Exception as e:
        log_message(f"Erreur création index: {e}", "WARNING")


def print_summary(successful, failed, duration):
    """Affiche un résumé de l'opération."""
    total = successful + failed
    success_rate = (successful / total * 100) if total > 0 else 0

    summary_lines = [
        "=" * 50, "RÉSUMÉ DE LA SYNCHRONISATION", "=" * 50, f"📄 Opérations totales: {total}", f"✅ Succès: {successful}",
        f"❌ Échecs: {failed}", f"📊 Taux de réussite: {success_rate:.1f}%", f"⏱️  Durée: {duration:.2f} secondes",
        "=" * 50
    ]

    # Affichage console
    for line in summary_lines:
        log_message(line)

    # Log fichier (résumé compact)
    log_to_file(
        f"Synchronisation terminée: {successful} succès, {failed} échecs, {success_rate:.1f}% réussite, {duration:.2f}s"
    )


def main():
    """Fonction principale avec gestion d'erreurs complète."""
    start_time = time.time()

    try:
        log_message("🚀 Début de la synchronisation CSV -> MongoDB")
        log_to_file("Début de la synchronisation CSV -> MongoDB")

        # Validation des prérequis
        log_message("📋 Validation des prérequis...")
        config = load_config()
        validate_csv_file()

        # Connexion MongoDB
        client = create_mongo_client_with_retry(config)

        try:
            db = client[config["DB_NAME"]]
            collection = db[config["COLLECTION_NAME"]]

            # Création des index
            create_indexes_safely(collection)

            # Traitement principal
            log_message("📊 Début du traitement des données...")
            successful, failed = process_csv_with_error_handling(collection)

            # Résumé
            duration = time.time() - start_time
            print_summary(successful, failed, duration)

            # Code de sortie selon les résultats
            if failed == 0:
                log_message("✅ Synchronisation terminée avec succès")
                log_to_file("Synchronisation terminée avec succès")
                sys.exit(0)
            elif successful > 0:
                log_message("⚠️  Synchronisation terminée avec des erreurs partielles")
                log_to_file("Synchronisation terminée avec des erreurs partielles", "WARNING")
                sys.exit(0)  # Succès partiel = OK pour CRON
            else:
                log_message("❌ Synchronisation échouée")
                log_to_file("Synchronisation échouée - aucune opération réussie", "ERROR")
                sys.exit(1)

        finally:
            client.close()
            log_message("🔌 Connexion MongoDB fermée")

    except KeyboardInterrupt:
        log_message("⏹️  Arrêt demandé par l'utilisateur", "WARNING")
        sys.exit(130)
    except Exception as e:
        log_message(f"💥 Erreur critique non gérée: {e}", "ERROR")
        log_to_file(f"Erreur critique non gérée: {e}", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
