import os
import sys
import csv
from datetime import datetime
from pymongo import MongoClient, UpdateOne
from pymongo.errors import ConnectionFailure
import glob
import json

# 📌 Configuration
CSV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../printed_serials.csv'))
DATA_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data'))
IGNORED_FOLDERS = {'archives_fails'}
BANC_FOLDERS = [f"banc{i}" for i in range(1, 5)]

with open("mongo_config.json", "r") as f:
    config = json.load(f)

MONGO_URI = config["MONGO_URI"]
DB_NAME = config["DB_NAME"]
COLLECTION_NAME = config["COLLECTION_NAME"]
COLUMNS = config["COLUMNS"]


def parse_iso(ts):
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def get_config_data_for_serial(serial):
    for banc in BANC_FOLDERS:
        if banc in IGNORED_FOLDERS:
            continue
        banc_path = os.path.join(DATA_FOLDER, banc)
        if not os.path.isdir(banc_path):
            continue
        pattern = os.path.join(banc_path, f"*-{serial}")
        matching_dirs = glob.glob(pattern)
        if not matching_dirs:
            continue
        for match in matching_dirs:
            config_path = os.path.join(match, "config.json")
            if os.path.isfile(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    print(f"[WARN] Erreur lecture config pour {serial} : {e}")
                    return None
    return None


def main():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
    except ConnectionFailure:
        print("[ERREUR] Impossible de se connecter à MongoDB.")
        sys.exit(1)

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    collection.create_index("NumeroSerie", unique=True)

    with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        ops = []
        lignes = 0

        for row in reader:
            lignes += 1
            doc = {
                "TimestampImpression": parse_iso(row["TimestampImpression"]),
                "NumeroSerie": row["NumeroSerie"],
                "CodeAleatoireQR": row["CodeAleatoireQR"],
                "TimestampTestDone": parse_iso(row["TimestampTestDone"]),
                "TimestampExpedition": parse_iso(row["TimestampExpedition"]),
                "version": row["version"]
            }

            config_data = get_config_data_for_serial(doc["NumeroSerie"])
            if config_data:
                for field in [
                        "capacity_ah", "capacity_wh", "ri_discharge_average", "ri_charge_average",
                        "diffusion_discharge_average", "diffusion_charge_average", "delta_ri_cells",
                        "delta_diffusion_cells"
                ]:
                    if field in config_data:
                        doc[field] = config_data[field]

            ops.append(UpdateOne({"NumeroSerie": doc["NumeroSerie"]}, {"$set": doc}, upsert=True))

        if ops:
            result = collection.bulk_write(ops)
            print(f"[OK] {lignes} lignes traitées.")
            print(f"➕ {result.upserted_count} insérées")
            print(f"🔁 {result.modified_count} mises à jour")
        else:
            print("[INFO] Aucun enregistrement trouvé dans le CSV.")


if __name__ == "__main__":
    main()
