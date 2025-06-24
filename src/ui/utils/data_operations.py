"""
Gestionnaire des opérations sur les données et fichiers.

Ce module centralise toutes les opérations liées aux données :
- Recherche et validation des batteries
- Chargement des profils et coefficients
- Calculs de durée et température
"""

import json
import os
import csv
import bisect
from .system_utils import log

# Constantes
DATA_DIR = "data"
SERIALS_CSV_PATH = "printed_serials.csv"
MODULE_DIR = os.path.dirname(__file__)
CHARGE_PROFILE_PATH = os.path.join(MODULE_DIR, "charge_profile.csv")
TEMP_COEFF_PATH = os.path.join(MODULE_DIR, "temperature_coefficients.json")

# Variables globales pour les profils chargés
_charge_profile_voltage = []
_charge_profile_duration = []
_charge_profile_loaded = False
_temp_coeffs = {}
_temp_coeffs_loaded = False


def _load_charge_profile():
    """Charge et trie les données du profil de charge (usage interne)."""
    global _charge_profile_voltage, _charge_profile_duration, _charge_profile_loaded
    if _charge_profile_loaded:
        return

    log("DataOps: Chargement à la demande du profil de charge...", level="INFO")
    temp_voltage = []
    temp_duration = []
    line_count = 0
    try:
        with open(CHARGE_PROFILE_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for line_num, row in enumerate(reader, 1):
                try:
                    v = float(row["Voltage"])
                    d = int(row["DurationSeconds"])
                    temp_voltage.append(v)
                    temp_duration.append(d)
                    line_count += 1
                except (KeyError, ValueError) as conv_e:
                    log(f"DataOps: Erreur format/conversion ligne {line_num} CSV ({CHARGE_PROFILE_PATH}): {conv_e} - Ligne ignorée: {row}",
                        level="ERROR")
        log(f"DataOps: {line_count} lignes lues depuis {CHARGE_PROFILE_PATH}.", level="INFO")

        if temp_voltage and len(temp_voltage) == len(temp_duration):
            profile_pairs = list(zip(temp_voltage, temp_duration))
            profile_pairs.sort(key=lambda pair: pair[0])
            if profile_pairs:
                voltage_sorted, duration_sorted = zip(*profile_pairs)
                _charge_profile_voltage[:] = list(voltage_sorted)
                _charge_profile_duration[:] = list(duration_sorted)
                log(f"DataOps: Profil de charge trié et chargé ({len(_charge_profile_voltage)} points valides).",
                    level="INFO")
            else:
                _charge_profile_voltage[:] = []
                _charge_profile_duration[:] = []
                log(f"DataOps: Aucune donnée valide après tri pour {CHARGE_PROFILE_PATH}. Profil vide.",
                    level="WARNING")
        else:
            _charge_profile_voltage[:] = []
            _charge_profile_duration[:] = []
            log(f"DataOps: Aucune donnée valide chargée ou longueurs incohérentes depuis {CHARGE_PROFILE_PATH}. Profil vide.",
                level="ERROR")

    except FileNotFoundError:
        _charge_profile_voltage[:] = []
        _charge_profile_duration[:] = []
        log(f"DataOps: Fichier {CHARGE_PROFILE_PATH} introuvable. Profil de charge non chargé.", level="ERROR")
    except Exception as e:
        _charge_profile_voltage[:] = []
        _charge_profile_duration[:] = []
        log(f"DataOps: Erreur majeure lors du chargement du profil de charge ({CHARGE_PROFILE_PATH}): {e}",
            level="ERROR")
    finally:
        _charge_profile_loaded = True


def _load_temp_coeffs():
    """Charge les coefficients de température (usage interne)."""
    global _temp_coeffs, _temp_coeffs_loaded
    if _temp_coeffs_loaded:
        return

    log("DataOps: Chargement à la demande des coefficients de température...", level="INFO")
    try:
        with open(TEMP_COEFF_PATH, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
            _temp_coeffs.clear()
            _temp_coeffs.update({int(k): float(v) for k, v in loaded_data.items()})
        log(f"DataOps: Coefficients température chargés : {len(_temp_coeffs)} valeurs", level="INFO")
    except FileNotFoundError:
        _temp_coeffs.clear()
        log(f"DataOps: Fichier {TEMP_COEFF_PATH} introuvable.", level="ERROR")
    except Exception as e:
        _temp_coeffs.clear()
        log(f"DataOps: Erreur lors du chargement des coefficients température : {e}", level="ERROR")
    finally:
        _temp_coeffs_loaded = True


def find_battery_folder(serial_number, data_dir=DATA_DIR, valid_bancs=None):
    """
    Recherche le dossier d'une batterie via son numéro de série dans tous les
    sous-dossiers des bancs valides.
    Le nom du dossier doit se terminer par "-{serial_number}".

    Args:
        serial_number (str): Numéro de série de la batterie à rechercher.
        data_dir (str, optional): Le chemin du répertoire de données principal.
                                  Utilise la constante DATA_DIR par défaut.
        valid_bancs (list[str], optional): Liste des noms de sous-dossiers de bancs
                                           à explorer.
    Returns:
        str | None: Chemin complet du premier dossier trouvé correspondant,
                    ou None si aucun dossier n'est trouvé.
    """
    if valid_bancs is None:
        valid_bancs = [f"banc{i+1}" for i in range(4)]  # banc1, banc2, banc3, banc4

    for banc in valid_bancs:
        banc_path = os.path.join(data_dir, banc)
        if os.path.exists(banc_path):
            try:
                for folder_or_file_name in os.listdir(banc_path):
                    log(f"DataOps: Vérifie item: {folder_or_file_name} dans {banc_path}", level="DEBUG")
                    expected_suffix = f"-{serial_number}"
                    if folder_or_file_name.endswith(expected_suffix):
                        full_path = os.path.join(banc_path, folder_or_file_name)
                        log(f"DataOps: Item correspondant trouvé (dossier ou fichier): {full_path}", level="INFO")
                        return full_path
            except OSError as e:
                log(f"DataOps: Erreur d'accès au dossier {banc_path}: {e}", level="ERROR")
            except Exception as e:
                log(f"DataOps: Erreur inattendue lors du listage de {banc_path}: {e}", level="ERROR")
    return None


def is_battery_checked(serial_to_check):
    """
    Vérifie si une batterie a un 'checker_name' dans le fichier printed_serials.csv.
    
    Args:
        serial_to_check (str): Le numéro de série de la batterie à vérifier.

    Returns:
        bool: True si la batterie a été validée (checkeur présent), False sinon.
    """
    if not os.path.exists(SERIALS_CSV_PATH):
        log(f"DataOps: Fichier {SERIALS_CSV_PATH} non trouvé. Impossible de vérifier le statut du check.",
            level="ERROR")
        return False

    try:
        with open(SERIALS_CSV_PATH, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row.get('NumeroSerie') == serial_to_check:
                    checker_name = row.get('checker_name', '').strip()
                    if checker_name:
                        log(f"DataOps: Batterie {serial_to_check} validée par '{checker_name}'.", level="INFO")
                        return True
                    else:
                        log(f"DataOps: Batterie {serial_to_check} trouvée mais NON validée (pas de checkeur).",
                            level="WARNING")
                        return False

        log(f"DataOps: Batterie {serial_to_check} non trouvée dans {SERIALS_CSV_PATH}.", level="WARNING")
        return False

    except Exception as e:
        log(f"DataOps: Erreur lors de la lecture de {SERIALS_CSV_PATH} pour la vérification du checkeur : {e}",
            level="ERROR")
        return False


def get_charge_duration(volts):
    """
    Estime la durée restante de charge en secondes à partir d'une tension,
    en utilisant une interpolation linéaire sur le profil de charge pré-chargé.
    
    Args:
        volts (float | str): La tension actuelle pour laquelle estimer la durée.
                             Sera convertie en float.
    Returns:
        int: La durée estimée en secondes, ou 100 en cas d'erreur ou si les
             listes de profil sont vides.
    """
    _load_charge_profile()

    try:
        volts = float(volts)
    except (ValueError, TypeError):
        log(f"DataOps: get_charge_duration - Tension invalide non convertible en float: {volts}", level="ERROR")
        return 100

    if not _charge_profile_voltage or not _charge_profile_duration or len(_charge_profile_voltage) != len(
            _charge_profile_duration):
        log(f"DataOps: get_charge_duration - Listes de profil vides ou incohérentes après tentative de chargement.",
            level="ERROR")
        return 100

    # Gestion des cas aux limites
    if volts <= _charge_profile_voltage[0]:
        return _charge_profile_duration[0]
    elif volts >= _charge_profile_voltage[-1]:
        return _charge_profile_duration[-1]

    try:
        idx = bisect.bisect_left(_charge_profile_voltage, volts)
        if _charge_profile_voltage[idx - 1] == volts:
            return _charge_profile_duration[idx - 1]

        v1, v2 = _charge_profile_voltage[idx - 1], _charge_profile_voltage[idx]
        d1, d2 = _charge_profile_duration[idx - 1], _charge_profile_duration[idx]

        if v2 == v1:
            log(f"DataOps: get_charge_duration - Tension dupliquée ({v1}) dans le profil. Retourne d1={d1}.",
                level="ERROR")
            return d1

        ratio = (volts - v1) / (v2 - v1)
        interpolated = d1 + (d2 - d1) * ratio
        return int(interpolated)

    except IndexError:
        log(f"DataOps: get_charge_duration - Erreur d'index inattendue avec idx={idx}, volts={volts}", level="ERROR")
        return 100
    except Exception as e:
        log(f"DataOps: get_charge_duration - Erreur inattendue pendant l'interpolation: {e}", level="ERROR")
        return 100


def get_temperature_coefficient(temp):
    """
    Retourne le coefficient de température correspondant à une température donnée.
    Convertit l'entrée en float, arrondit à l'entier le plus proche, puis
    recherche cet entier comme clé dans le dictionnaire global TEMP_COEFFS.
    
    Args:
        temp (float | int | str): La température d'entrée.
    Returns:
        float: Le coefficient trouvé, ou 1.0 si la température n'est pas
               dans le dictionnaire ou en cas d'erreur de conversion.
    """
    _load_temp_coeffs()
    try:
        t = round(float(temp))
        coefficient = _temp_coeffs.get(t, 1.0)
        return float(coefficient) if isinstance(coefficient, (int, float)) else 1.0
    except (ValueError, TypeError, AttributeError) as e:
        log(f"DataOps: Erreur conversion température ou accès TEMP_COEFFS: {e}. Input temp='{temp}'. Retourne coeff 1.0",
            level="WARNING")
        return 1.0
    except Exception as e:
        log(f"DataOps: Erreur inattendue dans get_temperature_coefficient: {e}. Input temp='{temp}'. Retourne coeff 1.0",
            level="ERROR")
        return 1.0
