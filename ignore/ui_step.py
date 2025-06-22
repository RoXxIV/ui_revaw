import customtkinter as ctk
import paho.mqtt.client as mqtt
import json

# Configuration MQTT
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# Connexion au broker
client = mqtt.Client()
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Fenêtre principale
app = ctk.CTk()
app.title("Envoyer Step, RI et Messages Sécurité")
app.geometry("500x450")

# Liste des bancs
bancs = [f"banc{i}" for i in range(1, 5)]
selected_banc = ctk.StringVar(value=bancs[0])

# Menu déroulant
dropdown = ctk.CTkOptionMenu(app, values=bancs, variable=selected_banc)
dropdown.pack(pady=20)


# Fonction d'envoi MQTT pour les steps
def send_step(step_value):
    banc = selected_banc.get()
    topic = f"{banc}/step"
    payload = str(step_value)
    print(f"📤 Envoi → Topic: {topic}, Payload: {payload}")
    client.publish(topic, payload)


# Fonction pour envoyer les résultats RI
def send_ri_results():
    banc = selected_banc.get()
    topic = f"{banc}/ri/results"
    ri_data = {
        "ri_discharge_average": 0.00123,
        "ri_charge_average": 0.00115,
        "diffusion_discharge_average": 0.00045,
        "diffusion_charge_average": 0.00052
    }
    payload = json.dumps(ri_data)
    print(f"📤 Envoi → Topic: {topic}, Payload: {payload}")
    client.publish(topic, payload)


# Fonction pour envoyer un message sécurité
def send_security_message():
    banc = selected_banc.get()
    topic = f"{banc}/security"
    message = security_entry.get()
    if message:
        print(f"📤 Envoi → Topic: {topic}, Payload: {message}")
        client.publish(topic, message)


# Frame des boutons STEP
step_frame = ctk.CTkFrame(app)
step_frame.pack(pady=10)

for i in range(1, 10):
    btn = ctk.CTkButton(step_frame, text=str(i), width=60, command=lambda i=i: send_step(i))
    btn.pack(side="left", padx=5)

# Bouton RI
ri_button = ctk.CTkButton(app, text="Envoyer RI", width=150, command=send_ri_results)
ri_button.pack(pady=20)

# Champ de saisie + bouton pour message sécurité
security_frame = ctk.CTkFrame(app)
security_frame.pack(pady=20)

security_entry = ctk.CTkEntry(security_frame, placeholder_text="Message sécurité...")
security_entry.pack(side="left", padx=10)

security_button = ctk.CTkButton(security_frame, text="Send", command=send_security_message)
security_button.pack(side="left")

# Lancement de l’interface
app.mainloop()
