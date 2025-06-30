from pymongo import MongoClient

uri = "mongodb+srv://evan:dXY5yweBjuEUooUp@revaw-cluster.pq7k9lp.mongodb.net/?retryWrites=true&w=majority&appName=Revaw-cluster"
client = MongoClient(uri)

try:
    client.admin.command("ping")
    print("✅ Connexion réussie à MongoDB Atlas !")
except Exception as e:
    print("❌ Erreur de connexion :", e)
