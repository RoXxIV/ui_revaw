# -*- coding: utf-8 -*-
"""
Gestionnaire de configuration pour les bancs de test.

Ce module centralise toutes les opérations liées à la configuration
des bancs de test : chargement, sauvegarde, modification des statuts.
"""

import json
import os
import time
import random
from .system_utils import log

# Constantes importées
DATA_DIR = "data"
NUM_BANCS = 4
VALID_BANCS = [f"banc{i+1}" for i in range(NUM_BANCS)]
CONFIG_PATH = "bancs_config.json"


def create_default_config(path):
    """
    Crée un fichier de configuration JSON par défaut pour les bancs à l'emplacement spécifié.
    Le fichier contiendra une liste de N bancs avec des
    valeurs par défaut pour leur nom, statut, etc.
    
    Args:
        path (str): Le chemin complet du fichier où la configuration par défaut
                    doit être écrite.
    Returns:
        dict: Le dictionnaire de configuration par défaut qui vient d'être créé,
              ou potentiellement lève une exception si l'écriture échoue.
    """
    default_config = {
        "bancs": [{
            "name": f"Banc{i+1}",
            "serial-pending": None,
            "status": "available",
            "current_step": None
        } for i in range(NUM_BANCS)]
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
        log(f"ConfigManager: Fichier de configuration créé par défaut à: {path}", level="INFO")
        return default_config
    except OSError as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Impossible d'écrire le fichier config par défaut à {path}: {e}",
            level="ERROR")
        raise
    except Exception as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Erreur inattendue lors de la création du fichier config par défaut: {e}",
            level="ERROR")
        raise


def load_bancs_config(config_path=CONFIG_PATH):
    """
    Charge la configuration des bancs depuis un fichier JSON spécifié.
    Si le fichier n'existe pas, il appelle create_default_config pour le créer
    et retourne la configuration par défaut.
    Si le fichier existe mais est corrompu ou illisible, log une erreur
    et retourne la configuration par défaut comme solution de secours.
    
    Args:
        config_path (str, optional): Le chemin vers le fichier de configuration.
                                     Utilise la constante globale CONFIG_PATH par défaut.
    Returns:
        dict: Le dictionnaire de configuration chargé depuis le fichier, ou
              la configuration par défaut en cas d'absence de fichier ou d'erreur.
    """
    if not os.path.exists(config_path):
        log(f"ConfigManager: Fichier config '{config_path}' non trouvé. Création du fichier par défaut.",
            level="WARNING")
        return create_default_config(config_path)
    try:
        # === AJOUT : Délai aléatoire pour éviter les collisions ===
        time.sleep(random.uniform(0.01, 0.05))  # 10-50ms aléatoire

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            log(f"ConfigManager: Configuration chargée depuis {config_path}", level="INFO")
            return config_data
    except json.JSONDecodeError as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Fichier config '{config_path}' corrompu (JSON invalide): {e}. Utilisation config par défaut.",
            level="WARNING")
        return create_default_config(config_path)
    except OSError as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Impossible de lire le fichier config '{config_path}': {e}. Utilisation config par défaut.",
            level="WARNING")
        return create_default_config(config_path)
    except Exception as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Erreur inattendue lors du chargement de '{config_path}': {e}. Utilisation config par défaut.",
            level="WARNING")
        return create_default_config(config_path)


def save_bancs_config(config, config_path=CONFIG_PATH):
    """
    Sauvegarde un dictionnaire de configuration donné dans un fichier JSON.
    Écrase le contenu précédent du fichier.
    
    Args:
        config (dict): Le dictionnaire Python à sauvegarder.
        config_path (str, optional): Chemin complet du fichier où sauvegarder.
                                     Utilise CONFIG_PATH par défaut.
    Returns:
        bool: True si la sauvegarde a réussi, False en cas d'erreur.
    """
    try:
        # === AJOUT : Délai aléatoire pour éviter les collisions ===
        time.sleep(random.uniform(0.01, 0.05))  # 10-50ms aléatoire

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        log(f"ConfigManager: Configuration sauvegardée dans {config_path}", level="DEBUG")
        return True
    except OSError as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Impossible d'écrire dans le fichier config '{config_path}': {e}",
            level="ERROR")
        return False
    except TypeError as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Impossible de sérialiser la configuration en JSON pour '{config_path}': {e}",
            level="ERROR")
        return False
    except Exception as e:
        log(f"ConfigManager: ERREUR CRITIQUE - Erreur inattendue lors de la sauvegarde de '{config_path}': {e}",
            level="ERROR")
        return False


def get_banc_info(banc_name, config_path=CONFIG_PATH):
    """
    Retourne le dictionnaire de configuration complet pour un banc spécifique,
    en le cherchant par son nom dans la configuration principale.
    La recherche est insensible à la casse (ex: "Banc1" et "banc1" correspondent).
    
    Args:
        banc_name (str): Nom du banc à rechercher (ex: "banc1").
        config_path (str, optional): Chemin vers le fichier de configuration principal.
                                     Utilise CONFIG_PATH par défaut.
    Returns:
        dict | None: Le dictionnaire contenant les informations du banc trouvé,
                     ou None si aucun banc avec ce nom n'est trouvé dans la config.
    """
    config = load_bancs_config(config_path)
    bancs = config.get("bancs", [])
    for banc in bancs:
        if banc.get("name", "").lower() == banc_name.lower():
            return banc
    return None


def set_banc_status(banc_name, status, serial_pending=None, current_step=None, config_path=CONFIG_PATH):
    """
    Met à jour les informations d'un banc spécifique dans le fichier de configuration principal.
    Charge la configuration actuelle, trouve le banc par son nom (insensible à la casse),
    met à jour les champs 'status', 'serial-pending' (si fourni), et 'current_step' (si fourni),
    puis sauvegarde la configuration modifiée.
    
    Args:
        banc_name (str): Nom du banc à mettre à jour (ex: "banc1").
        status (str): Le nouveau statut à définir (ex: "occupied").
        serial_pending (str | None, optional): Le numéro de série à définir comme
                                               attendu, ou None pour l'effacer.
                                               N'est mis à jour que si une valeur est fournie.
        current_step (int | None, optional): L'étape actuelle à définir, ou None.
                                            N'est mis à jour que si une valeur est fournie.
        config_path (str, optional): Chemin vers le fichier de configuration.
                                     Utilise CONFIG_PATH par défaut.
    Returns:
        bool: True si le banc a été trouvé et la configuration sauvegardée, False sinon.
    """
    KEY_NAME = "name"
    KEY_STATUS = "status"
    KEY_SERIAL_PENDING = "serial-pending"
    KEY_CURRENT_STEP = "current_step"
    try:
        config = load_bancs_config(config_path)
        bancs = config.get("bancs", [])
        updated = False
        # Recherche le banc par son nom
        for banc in bancs:
            if banc.get(KEY_NAME, "").lower() == banc_name.lower():
                banc[KEY_STATUS] = status
                if serial_pending is not None:
                    banc[KEY_SERIAL_PENDING] = serial_pending
                if current_step is not None:
                    banc[KEY_CURRENT_STEP] = current_step
                updated = True
                log(f"ConfigManager: Mise à jour statut pour {banc_name}: status={status}, serial={serial_pending}, step={current_step}",
                    level="DEBUG")
                break
        if updated:
            save_bancs_config(config, config_path)
            return True
        else:
            log(f"ConfigManager: Banc '{banc_name}' non trouvé dans {config_path}. Aucune mise à jour.", level="ERROR")
            return False
    except Exception as e:
        log(f"ConfigManager: Erreur dans set_banc_status pour {banc_name}: {e}", level="ERROR")
        return False


def update_bancs_config_current_step(new_step, banc_name, config_path=CONFIG_PATH):
    """
    Met à jour uniquement le champ 'current_step' pour le banc spécifié
    dans le fichier de configuration principal.
    
    Args:
        new_step (int): La nouvelle étape à enregistrer.
        banc_name (str): Nom du banc à mettre à jour.
        config_path (str, optional): Chemin vers le fichier de configuration principal.
                                     Utilise CONFIG_PATH par défaut.
    Returns:
        bool: True si la mise à jour et la sauvegarde ont réussi, False sinon.
    """
    config_data = None
    updated = False
    try:
        config_data = load_bancs_config(config_path)
        if not isinstance(config_data, dict):
            log(f"ConfigManager: ERREUR - Contenu de {config_path} n'est pas un dictionnaire. MAJ step annulée.",
                level="ERROR")
            return False
    except Exception as e:
        log(f"ConfigManager: Erreur lecture {config_path}: {e}. MAJ step annulée.", level="ERROR")
        return False

    try:
        bancs = config_data.get("bancs", [])
        banc_found = False
        for banc in bancs:
            if banc.get("name", "").lower() == banc_name.lower():
                banc["current_step"] = new_step
                log(f"ConfigManager: bancs_config.json mis à jour pour {banc_name} avec current_step={new_step}",
                    level="INFO")
                banc_found = True
                updated = True
                break
        if not banc_found:
            log(f"ConfigManager: Aucune entrée trouvée pour '{banc_name}' dans {config_path}. Aucune MAJ step.",
                level="ERROR")
    except Exception as e:
        log(f"ConfigManager: Erreur pendant la recherche/modification step dans config: {e}", level="ERROR")
        return False

    if updated:
        return save_bancs_config(config_data, config_path)
    else:
        return False


def get_banc_for_serial(serial_number, config_path=CONFIG_PATH):
    """
    Recherche dans la configuration principale si un banc attend spécifiquement
    une batterie avec le numéro de série donné (via la clé "serial-pending").
    
    Args:
        serial_number (str): Le numéro de série de la batterie à rechercher.
        config_path (str, optional): Chemin vers le fichier de configuration principal.
                                     Utilise CONFIG_PATH par défaut.
    Returns:
        str | None: Le nom du banc qui attend ce numéro de série, si trouvé.
                    Retourne None si aucun banc n'attend ce numéro de série.
    """
    config = load_bancs_config(config_path)
    bancs = config.get("bancs", [])
    for banc in bancs:
        if banc.get("serial-pending") == serial_number:
            return banc.get("name")
    return None


def reset_specific_banc(banc_id, config_path=CONFIG_PATH):
    """
    Réinitialise le statut d'un banc spécifique dans bancs_config.json.
    Met status='available', serial-pending=None, current_step=None.
    
    Args:
        banc_id (str): L'identifiant du banc à réinitialiser (ex: "banc1").
        config_path (str, optional): Chemin vers le fichier de configuration.
                                     Utilise CONFIG_PATH par défaut.
    Returns:
        bool: True si la mise à jour a réussi, False sinon.
    """
    log(f"ConfigManager: Tentative de réinitialisation pour {banc_id} dans {config_path}", level="INFO")
    try:
        config_data = load_bancs_config(config_path)
        banc_found = False
        for banc in config_data.get("bancs", []):
            if banc.get("name", "").lower() == banc_id.lower():
                banc["status"] = "available"
                banc["serial-pending"] = None
                banc["current_step"] = None
                banc_found = True
                break

        if banc_found:
            if save_bancs_config(config_data, config_path):
                log(f"ConfigManager: {banc_id} réinitialisé avec succès dans {config_path}.", level="INFO")
                return True
            else:
                log(f"ConfigManager: Echec sauvegarde {config_path} après tentative reset {banc_id}.", level="ERROR")
                return False
        else:
            log(f"ConfigManager: Banc {banc_id} non trouvé dans {config_path} pour reset.", level="ERROR")
            return False
    except Exception as e:
        log(f"ConfigManager: Erreur lors du reset de {banc_id} dans {config_path}: {e}", level="ERROR")
        return False
