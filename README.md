# 📋 README - Banc de Test IoT

> Documentation personnelle pour le système de test de batteries automatisé

## 🚀 Architecture du Système

### Scripts Principaux

```
📁 Projet/
├── 🖥️ ui.py          # Interface utilisateur principale
├── 🖨️ printer.py     # Service d'impression des étiquettes
├── 🔋 banc.py        # Script de test individuel par banc
└── 📂 src/          # Modules refactorisés
```

---

## 🖥️ UI.PY - Interface Utilisateur

**Rôle :** Interface graphique pour surveiller les 4 bancs de test

### Topics MQTT Écoutés

| Topic              | Description                    | Exemple Payload                                              |
| ------------------ | ------------------------------ | ------------------------------------------------------------ |
| `bancX/step`       | Étape actuelle du test         | `2`                                                          |
| `bancX/bms/data`   | Données temps réel batterie    | `48.5,2.1,85,25,3450,3420,...`                               |
| `bancX/security`   | Alertes de sécurité            | `"Timeout BMS banc1"`                                        |
| `bancX/ri/results` | Résultats mesures RI/Diffusion | `{"ri_discharge_average": 0.025, ...}`                       |
| `bancX/state`      | État chargeur/nourrices        | `1` (0=nurses off, 1=nurses on, 2=charger off, 3=charger on) |

### Commandes Mosquitto Test

```bash
# Simuler changement d'étape
mosquitto_pub -h localhost -t "banc1/step" -m "1"

# Simuler données BMS
mosquitto_pub -h localhost -t "banc1/bms/data" -m "48.5,2.1,85,25,0,3450,0,3420,271000,13000,3435,3430,3445,3425,3440,3435,3430,3445,3425,3440,3435,3430,3445,3425,3440,1,85.5"

# Simuler alerte sécurité
mosquitto_pub -h localhost -t "banc1/security" -m "Timeout BMS detecté"

# Simuler résultats RI
mosquitto_pub -h localhost -t "banc1/ri/results" -m '{"ri_discharge_average": 0.025, "ri_charge_average": 0.023, "diffusion_discharge_average": 0.015, "diffusion_charge_average": 0.012}'

# Simuler état équipements
mosquitto_pub -h localhost -t "banc1/state" -m "1"  # Nourrices ON
```

---

## 🖨️ PRINTER.PY - Service d'Impression

**Rôle :** Gestion des étiquettes et traçabilité des batteries

### Topics MQTT Écoutés

| Topic                               | Description                    | Exemple Payload                                                                     |
| ----------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------- |
| `printer/create_label`              | Créer nouvelle étiquette       | `{"checker_name": "evan"}`                                                          |
| `printer/test_done`                 | Test terminé → actions finales | `{"serial_number": "RW-48v2710001", "timestamp_test_done": "2024-06-24T15:30:00"}`  |
| `printer/request_full_reprint`      | Réimprimer toutes étiquettes   | `"RW-48v2710001"`                                                                   |
| `printer/update_shipping_timestamp` | Marquer expédition             | `{"serial_number": "RW-48v2710001", "timestamp_expedition": "2024-06-24T16:00:00"}` |
| `printer/create_batch_labels`       | Créer lot d'étiquettes         | `"5"` (nombre d'étiquettes)                                                         |

### Commandes Mosquitto Test

```bash
# Créer nouvelle étiquette
mosquitto_pub -h localhost -t "printer/create_label" -m '{"checker_name": "evan"}'

# Signaler test terminé
mosquitto_pub -h localhost -t "printer/test_done" -m '{"serial_number": "RW-48v2710001", "timestamp_test_done": "2024-06-24T15:30:00"}'

# Demander réimpression complète
mosquitto_pub -h localhost -t "printer/request_full_reprint" -m "RW-48v2710001"

# Marquer expédition
mosquitto_pub -h localhost -t "printer/update_shipping_timestamp" -m '{"serial_number": "RW-48v2710001", "timestamp_expedition": "2024-06-24T16:00:00"}'

# Créer lot de 3 étiquettes
mosquitto_pub -h localhost -t "printer/create_batch_labels" -m "3"
```

---

## 🔋 BANC.PY - Test Individuel

**Rôle :** Execute le test d'une batterie sur un banc spécifique

### Usage

```bash
python banc.py <bancX> <numero_serie>
# Exemple :
python banc.py banc1 RW-48v2710001
```

### Topics MQTT Publiés

| Topic            | Description         | Valeurs Possibles                                                                                                |
| ---------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `bancX/step`     | Progression du test | `1`=RI, `2`=Charge, `3`=Décharge, `4`=Charge finale, `5`=Terminé, `6`=Échec, `7`=Sécurité, `8`=Arrêt, `9`=Manuel |
| `bancX/security` | Alertes critiques   | `"Timeout BMS bancX"`                                                                                            |

### Topics MQTT Écoutés

| Topic              | Description            | Exemple Payload                                           |
| ------------------ | ---------------------- | --------------------------------------------------------- |
| `bancX/bms/data`   | Données capteurs ESP32 | `48.5,2.1,85,25,0,3450,0,3420,271000,13000,3435,3430,...` |
| `bancX/ri/results` | Résultats mesures RI   | `{"ri_discharge_average": 0.025, ...}`                    |
| `bancX/command`    | Commandes externe      | `"end"` (fin de journée)                                  |

### Commandes Mosquitto Test

```bash
# Envoyer données BMS simulées
mosquitto_pub -h localhost -t "banc1/bms/data" -m "48.5,2.1,85,25,0,3450,0,3420,271000,13000,3435,3430,3445,3425,3440,3435,3430,3445,3425,3440,3435,3430,3445,3425,3440,1,85.5"

# Envoyer résultats RI
mosquitto_pub -h localhost -t "banc1/ri/results" -m '{"ri_discharge_average": 0.025, "ri_charge_average": 0.023}'

# Commande fin de journée
mosquitto_pub -h localhost -t "banc1/command" -m "end"
```

---

## 📊 Étapes de Test (Steps)

| Step | Nom               | Description                             |
| ---- | ----------------- | --------------------------------------- |
| `1`  | **Phase RI**      | Mesure résistance interne (~3min)       |
| `2`  | **Charge**        | Charge jusqu'à tension max (variable)   |
| `3`  | **Décharge**      | Test de capacité (variable selon SOC)   |
| `4`  | **Charge Finale** | Charge finale + équilibrage nourrices   |
| `5`  | **✅ Terminé**    | Test réussi, actions finales            |
| `6`  | **❌ Échec**      | Test échoué, archivage                  |
| `7`  | **🚨 Sécurité**   | Arrêt sécurité ESP32                    |
| `8`  | **🚨 E-Stop**     | Bouton d'urgence ESP32 → Reset possible |
| `9`  | **⏹️ End**        | Fin de journée (commande "end")         |

---

## 🔧 Commandes Utiles

### Surveillance MQTT

```bash
# Écouter tous les messages
mosquitto_sub -h localhost -t "#" -v

# Écouter un banc spécifique
mosquitto_sub -h localhost -t "banc1/#" -v

# Écouter service impression
mosquitto_sub -h localhost -t "printer/#" -v
```

### Démarrage Services

```bash
# Interface utilisateur
python ui.py

# Service impression
python printer.py

# Test manuel
python banc.py banc1 RW-48v2710001
```

---

## 📁 Structure Données

### Format BMS Data (26 champs)

```
Voltage,Current,SOC,Temperature,MaxCellNum,MaxCellV,MinCellNum,MinCellV,
DischargedCapacity,DischargedEnergy,Cell_1mV,Cell_2mV,...,Cell_15mV,
HeartBeat,AverageNurseSOC
```

### Configuration Bancs (`bancs_config.json`)

```json
{
  "bancs": [
    {
      "name": "Banc1",
      "serial-pending": "RW-48v2710001",
      "status": "occupied",
      "current_step": 2
    }
  ]
}
```

---

## 🚨 Troubleshooting

### Problèmes Courants

- **Timeout BMS** : Vérifier connexion ESP32
- **Service impression inactif** : Redémarrer `python printer.py`
- **Banc bloqué** : Scanner "reset" puis le banc concerné

### Logs

- Tous les services loggent dans `logs.log`
- Niveau de log configurable dans `src/ui/utils/system_utils.py`

---

_Documentation mise à jour : Juin 2024_
