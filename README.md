# 🔋 Banc de Test Autonome - Batteries LFP

## 🧩 Description générale

Ce projet permet de caractériser automatiquement des batteries Lithium Fer Phosphate (LFP) sur plusieurs bancs de test indépendants (actuellement configuré pour 4).
Chaque banc est piloté par un **ESP32** (ou un simulateur) qui communique via MQTT avec une instance dédiée du script `banc.py` tournant sur un Raspberry Pi.
Une interface graphique centrale (`ui.py`, basée sur CustomTkinter) sur le Raspberry Pi permet aux opérateurs de lancer les tests via un système de scan (Banc → Serial → Banc), de suivre les mesures clés en temps réel pour chaque banc, et de visualiser la progression du test. Les données détaillées et les résultats sont stockés pour chaque test.

---

## 🖥️ Composants principaux

| Élément                | Rôle                                                                                                                                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ESP32 (ou Sim) (xN)    | Gère la mesure physique (tension, courant, T°), contrôle relais, envoie données (BMS, Step) en MQTT.                                                                                                                        |
| Raspberry Pi           | Héberge l'UI, les scripts `banc.py`, le broker MQTT (local), et stocke les données.                                                                                                                                         |
| `banc.py` (script)     | Script Python unique, lancé en **processus distinct pour chaque test**. Gère la séquence de test, enregistre les données CSV, met à jour les configurations JSON, surveille l'activité BMS, communique via MQTT.            |
| `ui.py` (script)       | Interface graphique centrale (CustomTkinter). Affiche l'état des bancs, les données temps réel, les alertes. Gère le lancement des tests et la commande d'arrêt global ("end"). S'abonne à tous les topics MQTT pertinents. |
| `utils.py` (module)    | Fonctions utilitaires partagées (log, gestion config JSON, calculs, chargement paresseux profils...).                                                                                                                       |
| `ui_components.py`     | Classes et fonctions pour les éléments graphiques réutilisables (jauge SOC, barre de progression multi-couleurs...).                                                                                                        |
| MQTT Broker (local)    | Assure la communication entre l'UI, les scripts `banc.py`, et les ESP32/simulateurs.                                                                                                                                        |
| Fichiers Configuration | `bancs_config.json` (état global), `charge_profile.csv` (profil charge), `temperature_coefficients.json`.                                                                                                                   |
| Fichiers Données       | `data/bancX/DATE-SERIAL/` contient `config.json` (spécifique au test) et `data.csv` (enregistrements BMS).                                                                                                                  |

---

## 📁 Structure des fichiers principaux

```
.
├── ui.py                      # Interface graphique principale (CustomTkinter + MQTT)
├── ui_components.py           # Composants graphiques réutilisables pour l'UI
├── banc.py                    # Script unique de gestion d'un banc (lancé N fois)
├── utils.py                   # Fonctions utilitaires communes + chargement config statique
├── requirements.txt           # Dépendances Python
├── bancs_config.json          # Fichier central de configuration/état des N bancs
├── charge_profile.csv         # Profil Tension → Durée pour estimation Phase 2 (chargé par utils.py)
├── temperature_coefficients.json # Coefficients T° pour correction Diffusion (chargé par utils.py)
├── logs.log                   # Fichier de logs applicatifs
└── data/
└──── banc1/                 # Données spécifiques au banc 1 (idem pour banc2, ...)
└────── DATE-SERIAL/       # Dossier pour un test spécifique (ex: 15042025-RW-XXXXXX)
├──────── config.json    # Configuration et résultats pour CE test (étape, capa, Ri...)
└──────── data.csv       # Données BMS brutes enregistrées pendant le test
```

## 🔁 Fonctionnement global (Mis à jour - v2025-04-15)

1.  **Lancement de `ui.py` :**

    - Charge la configuration globale `bancs_config.json` (`utils.load_bancs_config`) pour connaître l'état initial des bancs.
    - Se connecte au broker MQTT et s'abonne aux topics de tous les bancs (`bancX/step`, `bancX/bms/data`, `bancX/security`, `bancX/ri/results`, `bancX/nX`).
    - Affiche l'état des bancs ("Libre" ou "Occupé - SERIAL - Phase X/5").
    - _Note : Les fichiers `charge_profile.csv` et `temperature_coefficients.json` sont chargés par `utils.py` uniquement lors du premier appel aux fonctions `get_charge_duration` ou `get_temperature_coefficient` par l'UI ("Lazy Loading")._

2.  **Démarrage d'un test via UI (`handle_prompt` dans `ui.py`) :**

    - Opérateur scanne **Banc** (ex: `banc1`).
      - UI vérifie si `banc.py` pour `banc1` tourne déjà (`utils.is_banc_running`). Si oui, erreur.
      - UI lit l'état de `banc1` depuis `bancs_config.json` via `utils.get_banc_info`.
    - Opérateur scanne **Serial** (ex: `RW-XXX`).
      - UI valide le format du serial.
      - UI vérifie si le serial est déjà sur un _autre_ banc via `utils.get_banc_for_serial`.
      - Si le banc scanné initialement était "Libre":
        - UI cherche un dossier existant pour ce serial (`utils.find_battery_folder`).
        - Si trouvé, vérifie si dernier test > 48h ouvrées (`utils.is_past_business_hours`). Si trop récent, erreur.
      - Si le banc scanné initialement était "Occupé":
        - UI vérifie si le serial scanné correspond au `serial-pending` du banc. Si différent, erreur.
    - Opérateur re-scanne **Banc** (ex: `banc1`) pour confirmer.
      - UI vérifie si délai < Timeout (ex: 15s).
      - UI re-vérifie `is_banc_running`.
      - Si OK :
        - Met à jour `bancs_config.json` (statut='occupied', serial) via `utils.set_banc_status`.
        - Réinitialise l'affichage UI pour `banc1` (barres, timer, etc.) via `reset()` et `hide_overlay_labels`.
        - **Lance une instance de `banc.py` en subprocess** (`subprocess.Popen`) avec `banc1` et `RW-XXX` comme arguments.

3.  **Exécution de `banc.py` (Instance par test) :**

    - Au démarrage (`main`) :
      - Identifie/crée son dossier de travail (`data/bancX/DATE-SERIAL`). Vérifie/crée `data/` et `data/bancX/` si besoin (`load_or_create_config` dans `banc.py`).
      - Charge/Crée `config.json` et `data.csv` dans ce dossier (`load_or_create_config`, `create_data_csv`). Lit l'étape initiale depuis `config.json` (ou 1 si nouveau).
      - Initialise le client MQTT (ID unique type `banc_script_bancX`), s'abonne (`bancX/step`, `bancX/bms/data`, `bancX/ri/results`).
      - **Publie son état initial (étape lue) sur `bancX/command`**.
      - Ouvre `data.csv` en mode ajout (`'a'`).
      - Lance le thread de surveillance d'activité BMS (timeout 30s).
      - Démarre la boucle MQTT (`client.loop_forever()`).
    - Pendant l'exécution (`on_message` dans `banc.py`) :
      - Sur `bancX/step` (payload `1`-`5`) : Met à jour `current_step` (variable interne), appelle `utils.update_config` (qui met à jour `config.json` local ET `bancs_config.json` global). Si `step == 5`, appelle `close_csv`, `utils.reset_banc_config`, puis `sys.exit(0)`.
      - Sur `bancX/step` (payload `9`) : Appelle `close_csv`, logue l'arrêt, puis `sys.exit(0)`. **Ne met PAS à jour les configs.**
      - Sur `bancX/bms/data` : Met à jour le timer de surveillance BMS. Ajoute une ligne à `data.csv` (avec mode basé sur `current_step` interne). Appelle `utils.update_config_bms` pour maj `config.json` batterie (capa, energy, timestamp) sauf si `current_step` est 5 ou 9.
      - Sur `bancX/ri/results` : Parse le JSON, appelle `utils.update_config_ri_results` pour maj `config.json` batterie.
    - Surveillance BMS (Thread) : Si aucun message `/bms/data` reçu pendant 30s, publie une alerte sur `bancX/security`.

4.  **Interaction UI (`on_message` dans `ui.py`) :**

    - Reçoit les messages MQTT de tous les `banc.py`/ESP actifs.
    - Sur `bancX/step` (payload `1`-`5`) : Met à jour `widgets["current_step"]` pour l'UI. Met à jour l'affichage `widgets["phase"]` (`get_phase_message`). Lance/arrête les animations (`animate_phase_segment`, `finalize_previous_phase`). Finalise toutes les barres si `step == 5`. Cache l'alerte sécurité si active. Déclenche la MAJ Ri/Diff si `step == 2`.
    - Sur `bancX/step` (payload `9`) : Appelle `finalize_previous_phase` (arrête animation), remet `widgets["time_left"]` à "00:00:00", **corrige** `widgets["phase"]` pour afficher l'étape _précédente_.
    - Sur `bancX/bms/data` : Appelle `update_banc_data` (via `after`) pour mettre à jour tous les labels de mesure (tension, courant, SOC, temp, capa, energy, balance) et les couleurs associées. Met à jour aussi la jauge SOC. **Ne met à jour le label `phase` que si l'étape interne UI est 1-5.**
    - Sur `bancX/security` : Appelle `update_banc_security` (via `after`) pour afficher une alerte rouge temporaire.
    - Sur `bancX/ri/results` : Ne fait rien directement (l'info sera lue depuis `config.json` par `update_ri_diffusion_widgets` lorsque step 2 arrive).
    - Sur `bancX/nX` : Met à jour la variable `app.nurse_soc` et la barre `widgets["progress_bar_nurse"]`.

5.  **Arrêt Global Fin de Journée (via UI) :**
    - Opérateur scanne "end".
    - `ui.py` (`handle_prompt`) publie le payload `"end"` sur `banc1/command`, `banc2/command`, `banc3/command`, `banc4/command`.
    - (Logique ESP32 à définir : Doit réagir à "end" en envoyant `9` sur `bancX/step`).

---

## 📡 MQTT Topics utilisés (Révisé)

| Topic              | Émetteur(s)                         | Destinataire(s)    | Utilisation                                    | QoS | Retained |
| ------------------ | ----------------------------------- | ------------------ | ---------------------------------------------- | :-: | :------: |
| `bancX/step`       | **ESP32/Sim**                       | `banc.py`, `ui.py` | Phase actuelle du test (1-5) ou Arrêt (9)      | 0?  |   Non    |
| `bancX/bms/data`   | **ESP32/Sim**                       | `banc.py`, `ui.py` | Données BMS (string CSV)                       | 0?  |   Non    |
| `bancX/security`   | `banc.py` (Timeout), **ESP32/Sim?** | `ui.py`            | Message alerte sécurité (ex: "Timeout BMS")    |  1  |   Non    |
| `bancX/ri/results` | **ESP32/Sim?**                      | `banc.py`          | Résultats Ri/Diffusion (JSON)                  | 1?  |   Non    |
| `bancX/nJ` (J=1-6) | **ESP32/Sim**                       | `ui.py`            | SOC nourrice J (int 0-100)                     | 0?  |   Non    |
| `bancX/command`    | `banc.py` (Init), `ui.py` ("end")   | **ESP32/Sim**      | Commande pour ESP (état initial, arrêt global) |  1  |   Non    |

_Note : QoS et Retained à vérifier/définir selon les besoins de fiabilité._
_Note : L'émetteur de `/ri/results` est à confirmer (ESP ou banc.py si calcul local ? Actuellement reçu par banc.py)._

---

## 📖 Fichiers JSON (Exemples)

### `bancs_config.json`

État global des bancs (maintenu par `utils.py`, lu/écrit par `ui.py` et `banc.py`).

```json
{
  "bancs": [
    {
      "name": "Banc1",
      "status": "occupied",
      "serial-pending": "RW-48v29155551",
      "current_step": 3
    },
    {
      "name": "Banc2",
      "status": "available",
      "serial-pending": null,
      "current_step": null
    }
    // ... autres bancs
  ]
}
```

config.json (par test dans data/bancX/DATE-SERIAL/)

Configuration et résultats spécifiques à un test (maintenu par banc.py via utils.py).

```json
{
  "battery_serial": "RW-48v29155551",
  "banc": "banc1",
  "current_step": 3, // Dernière étape valide atteinte
  "first_handle": "2025-04-15T21:04:09.123456", // ISO Format
  "timestamp_last_update": "2025-04-15T21:05:48.987654", // ISO Format
  "capacity_ah": 95.8,
  "capacity_wh": 562.1,
  "ri_discharge_average": 0.00123,
  "ri_charge_average": 0.00115,
  "diffusion_discharge_average": 0.00045,
  "diffusion_charge_average": 0.00052
}
```

⚙️ Fonctions Utilitaires Clés (utils.py)

| Fonction                             | Rôle                                                                           | Utilisé par                     |
| :----------------------------------- | :----------------------------------------------------------------------------- | :------------------------------ |
| `log()`                              | Log console + fichier `logs.log` avec niveaux                                  | `ui.py`, `banc.py`              |
| `_load_charge_profile()`             | Charge `charge_profile.csv` (appelée par `get_charge_duration`)                | `utils.py` (interne)            |
| `_load_temp_coeffs()`                | Charge `temperature_coefficients.json` (appelée par `get_temp_coeff`)          | `utils.py` (interne)            |
| `get_charge_duration()`              | Estime durée Phase 2 (via profil chargé à la demande)                          | `ui.py`                         |
| `get_temperature_coefficient()`      | Récupère coeff T° (via coeffs chargés à la demande)                            | `ui.py`                         |
| `create_default_config()`            | Crée `bancs_config.json` par défaut si inexistant                              | `utils.py` (interne)            |
| `load_bancs_config()`                | Charge `bancs_config.json` (appelle `create_default_config` si besoin)         | `utils.py`                      |
| `save_bancs_config()`                | Sauvegarde `bancs_config.json`                                                 | `utils.py`                      |
| `get_banc_info()`                    | Récupère info d'un banc depuis `bancs_config.json`                             | `ui.py`                         |
| `get_banc_for_serial()`              | Trouve quel banc attend un serial dans `bancs_config.json`                     | `ui.py`                         |
| `find_battery_folder()`              | Trouve le dossier existant `data/bancX/DATE-SERIAL` pour une batterie          | `ui.py`                         |
| `is_past_business_hours()`           | Vérifie délai > 48h ouvrées pour reprise test                                  | `ui.py`                         |
| `add_business_hours()`               | Helper pour calculer les heures ouvrées                                        | `utils.py` (interne)            |
| `is_banc_running()`                  | Vérifie si processus `banc.py` tourne pour un banc donné (via `psutil`)        | `ui.py`                         |
| `set_banc_status()`                  | Met à jour statut/serial/step pour un banc dans `bancs_config.json`            | `ui.py`                         |
| `update_bancs_config_current_step()` | Met à jour **seulement** `current_step` dans `bancs_config.json`               | `banc.py` (via `update_config`) |
| `reset_banc_config()`                | **Réinitialise le banc COURANT** (`BANC` global) dans `bancs_config.json`      | `banc.py`                       |
| `load_or_create_config()`            | Charge/Crée `config.json` **spécifique batterie**                              | `banc.py`                       |
| `create_data_csv()`                  | Crée `data.csv` avec en-têtes si inexistant                                    | `banc.py`                       |
| `update_config()`                    | Met à jour `config.json` batterie + appelle `update_bancs_config_current_step` | `banc.py`                       |
| `update_config_bms()`                | Met à jour `config.json` batterie (capa, energy, timestamp)                    | `banc.py`                       |
| `update_config_ri_results()`         | Met à jour `config.json` batterie (Ri, Diffusion)                              | `banc.py`                       |

✅ Prochaines Étapes / Idées d’amélioration

    Comportement ESP32 : Étudier et définir clairement le comportement de l'ESP32 en cas de perte de connexion MQTT (sécurité primordiale).
    Commande "reset" UI : Implémenter la commande "reset" dans l'UI pour nettoyer l'état d'un banc dans bancs_config.json (après clarification comportement ESP32 et ajout check is_banc_running).
    Logging : (Optionnel) Migrer la fonction log vers le module standard logging de Python pour une meilleure gestion de la concurrence et des formats.
    Gestion Erreurs Robustes : Ajouter des alertes sécurité (/security) pour les erreurs critiques (ex: échec écriture CSV répétée, disque plein).
    Graphiques : (Fonctionnalité) Ajouter une option pour visualiser les données d'un data.csv terminé.
    Tests Unitaires : (Qualité) Compléter les tests pour les fonctions critiques (notamment dans utils.py).

## 🔧 Configuration du Nombre de Bancs

Le système est conçu pour être adaptable au nombre de bancs de test physiques disponibles. Pour changer le nombre de bancs gérés (par exemple, passer de 4 à 6) :

1.  **Modifier la Constante Centrale (`utils.py`)**

    - Ouvrez le fichier `utils.py`.
    - Localisez la constante `NUM_BANCS` au début du fichier.
    - Changez sa valeur pour le nombre désiré (ex: `NUM_BANCS = 4`).

2.  **Adapter l'Affichage de l'Interface Utilisateur (`ui.py`)**
    - Ouvrez le fichier `ui.py`.
    - Dans la méthode `App.__init__`, localisez et modifier la ligne `self.columnconfigure(...)...`.
    - Modifiez le premier argument (la liste des colonnes) pour qu'il corresponde au nombre de colonnes nécessaires. exemple :
    - 4 bancs sur deux colonnes `self.columnconfigure((0, 1), weight=1, uniform="col")`
    - 6 bancs sur 3 colonnes `self.columnconfigure((0, 1, 2), weight=1, uniform="col")`
    - modifier egalement le `columnspan` dans `self.frame_scan.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")`. doit correspondre au nombre de colonnes
3.  **Réinitialiser le Fichier d'État (`bancs_config.json`)**
    - **Supprimez** le fichier `bancs_config.json` existant.
    - Au prochain lancement de `ui.py`, le fichier sera automatiquement recréé avec le bon nombre de bancs.

## Installation et Configuration sur Raspberry Pi

Ce guide explique comment installer et configurer l'application pour qu'elle s'exécute automatiquement au démarrage sur un Raspberry Pi. Il est basé sur l'utilisateur `user` et le chemin de projet `/home/user/Desktop/Banc_final_pi`. Adaptez ces informations si votre configuration diffère.

### 1. Prérequis Système

Assurez-vous que votre Raspberry Pi est à jour et que les paquets nécessaires sont installés. Ouvrez un terminal sur le Pi et exécutez :

```bash
sudo apt update
sudo apt upgrade -y
# Venv pour l'environnement isolé, Tk pour customtkinter, Git si besoin, Mosquitto pour le broker MQTT
sudo apt install -y python3-venv python3-tk git mosquitto mosquitto-clients
```

### 2. Préparation du Projet

1. Récupérez le code source : Clonez le dépôt Git ou copiez les fichiers du projet sur le Pi dans le dossier souhaité. Pour ce guide, nous utilisons `/home/user/Desktop/Banc_final_pi.`

```
# Allez dans le dossier du projet
cd /home/user/Desktop/Banc_final_pi
```

2. Créez l'environnement virtuel Python :

```
python3 -m venv venv
```

3. Activez l'environnement virtuel :

```
source venv/bin/activate
```

4. Installez les dépendances Python : (Assurez-vous d'avoir un fichier `requirements.txt` à jour).

```
pip install -r requirements.txt
```

5. Désactivez l'environnement virtuel :

```
deactivate
```

6. Rendez le script principal exécutable :

```
chmod +x ui.py
```

### 3. Configuration du Lancement Automatique (systemd)

Nous utilisons `systemd` pour gérer le lancement automatique de l'application après le démarrage du système et de l'interface graphique.

1. Créez le fichier de service systemd :

```
sudo nano /etc/systemd/system/banc_test_ui.service
```

2. Collez le contenu suivant dans l'éditeur nano. Ce contenu est spécifique à l'utilisateur user et au chemin `/home/user/Desktop/Banc_final_pi`.

```Ini, TOML
[Unit]
Description=Application UI pour Banc de Test Final PI
# Attend que le réseau soit opérationnel ET que la session graphique soit prête
After=graphical.target network-online.target
Wants=network-online.target

[Service]
# Utilisateur qui lance l'application
User=user
Group=user

# Dossier de travail du projet
WorkingDirectory=/home/user/Desktop/Banc_final_pi/

# Commande pour lancer le script via le python du venv
ExecStart=/home/user/Desktop/Banc_final_pi/venv/bin/python /home/user/Desktop/Banc_final_pi/ui.py

# Variables d'environnement cruciales pour une application GUI (customtkinter)
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/user/.Xauthority"

# Redémarrer si le script plante
Restart=on-failure
RestartSec=5s

# Type de service
Type=simple

[Install]
# Lance ce service quand la cible graphique est atteinte
WantedBy=graphical.target
```

3. Sauvegardez et fermez l'éditeur (`Ctrl+O`, `Entrée`, `Ctrl+X`).
4. Activez le service pour qu'il soit lancé au démarrage :

```
sudo systemctl enable banc_test_ui.service
```

(Note : Le service Mosquitto installé précédemment est déjà activé par défaut)

### 4. Démarrage et Vérification

1. Redémarrez le Raspberry Pi pour appliquer la configuration :

```
sudo reboot
```

2. Après le redémarrage, l'application `ui.py` devrait se lancer automatiquement en plein écran. Le broker Mosquitto tourne aussi en arrière-plan.

3. Lancez le script simulateur sur votre PC (configuré avec l'IP du Pi). Les données devraient maintenant apparaître dans l'interface sur le Pi.

4. Commandes utiles pour gérer/vérifier le service :

   - Vérifier le statut : `sudo systemctl status banc_test_ui.service`
   - Voir les logs en direct : `journalctl -u banc_test_ui.service -f`
   - Arrêter le service manuellement : `sudo systemctl stop banc_test_ui.service`
   - Démarrer le service manuellement : `sudo systemctl start banc_test_ui.service`
