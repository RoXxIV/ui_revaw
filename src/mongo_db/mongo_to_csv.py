import os
import csv
import json
from pymongo import MongoClient

# Définir le chemin du fichier de configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'mongo_config.json')

# Charger la configuration depuis le fichier JSON
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

# Récupérer les paramètres de la config
MONGO_URI = config["MONGO_URI"]
DB_NAME = config["DB_NAME"]
COLLECTION_NAME = config["COLLECTION_NAME"]

# Champs à exporter (définis en dur ici selon ta demande)
COLUMNS = [
    "TimestampImpression", "NumeroSerie", "CodeAleatoireQR", "TimestampTestDone", "TimestampExpedition", "version"
]

CSV_FILENAME = "export.csv"

# Connexion à MongoDB
client = MongoClient(MONGO_URI)
collection = client[DB_NAME][COLLECTION_NAME]

# Récupération des documents
documents = list(collection.find())

if not documents:
    print("⚠️ La collection est vide.")
    exit()

# Création du CSV
with open(CSV_FILENAME, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS)
    writer.writeheader()
    for doc in documents:
        row = {key: doc.get(key, "") for key in COLUMNS}
        writer.writerow(row)

print(f"✅ Export terminé : {CSV_FILENAME}")
