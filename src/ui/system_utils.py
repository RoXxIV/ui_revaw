# -*- coding: utf-8 -*-
"""
Utilitaires système et logging.
"""
import logging
import logging.handlers
import os
import psutil
from datetime import datetime, timedelta

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
# Configuration du logging
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "banc_test.log")
LOG_LEVELS = ["DEEP_DEBUG", "DEBUG", "INFO", "ERROR", "WARNING"]
CURRENT_LOG_LEVEL = "INFO"
LEVEL_MAPPING = {"DEEP_DEBUG": 5, "DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}

import logging
import logging.handlers
import os

# Configuration avec dossier logs/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")  # Nouveau dossier logs/
LOG_FILE = os.path.join(LOGS_DIR, "banc_test.log")  # logs/banc_test.log
# Vos niveaux
LOG_LEVELS = ["DEEP_DEBUG", "DEBUG", "INFO", "ERROR", "WARNING"]
CURRENT_LOG_LEVEL = "INFO"


def setup_logging():
    """Configuration avec structure propre dans logs/"""
    logger = logging.getLogger("banc_test")

    if logger.handlers:
        return logger

    # IMPORTANT: Créer le dossier logs/ s'il n'existe pas
    os.makedirs(LOGS_DIR, exist_ok=True)

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # Handler fichier avec rotation dans logs/
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,  # logs/banc_test.log
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,  # Garde 5 anciens
        encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


_logger = setup_logging()


def log(*args, level="INFO"):
    """Fonction log avec filtrage par niveau"""
    # Filtrage selon votre CURRENT_LOG_LEVEL
    try:
        current_level_index = LOG_LEVELS.index(CURRENT_LOG_LEVEL)
        message_level_index = LOG_LEVELS.index(level)

        if message_level_index < current_level_index:
            return
    except ValueError:
        pass

    message = " ".join(str(arg) for arg in args)

    # Mapping vers niveaux Python
    if level in ["DEEP_DEBUG", "DEBUG"]:
        _logger.debug(f"[{level}] {message}")
    elif level == "INFO":
        _logger.info(message)
    elif level == "WARNING":
        _logger.warning(message)
    elif level == "ERROR":
        _logger.error(message)
    else:
        _logger.info(message)


def is_banc_running(banc_name):
    """
    Vérifie si un processus correspondant à 'python ... banc.py [banc_name] ...'
    est actuellement en cours d'exécution.
    Utilise psutil pour itérer sur les processus et examiner leur ligne de commande.  
    Args:
        banc_name (str): Le nom du banc (ex: "banc1") à rechercher dans les
                         arguments de la ligne de commande.
    Returns:
        bool: True si un processus correspondant est trouvé, False sinon ou en cas d'erreur.
    """
    script_name_to_find = "banc.py"
    try:
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get("cmdline", [])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if not cmdline:
                continue
            script_found = any(script_name_to_find in part for part in cmdline)
            banc_arg_found = banc_name in cmdline
            if script_found and banc_arg_found:
                log(f"SystemUtils: Processus {script_name_to_find} trouvé pour {banc_name} (PID: {proc.pid})",
                    level="DEBUG")
                return True
    except Exception as e:
        log(f"SystemUtils: Erreur inattendue dans is_banc_running: {e}", level="ERROR")
        return False
    return False


def is_printer_service_running():
    """
    Vérifie si un processus correspondant à 'python ... printer.py ...'
    est actuellement en cours d'exécution.
    Returns:
        bool: True si le service d'impression est actif, False sinon.
    """
    script_name_to_find = "printer.py"
    python_executables = ["python", "python.exe", "python3", "python3.exe"]
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get("cmdline", [])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

            if not cmdline:
                continue

            # Vérifie si un des éléments de la ligne de commande est un exécutable python
            is_python_cmd = False
            if cmdline[0].lower() in python_executables or \
               any(py_exec in cmdline[0].lower() for py_exec in python_executables):
                is_python_cmd = True

            script_in_cmdline = any(script_name_to_find in part for part in cmdline)

            if is_python_cmd and script_in_cmdline:
                log(f"SystemUtils: Processus {script_name_to_find} trouvé (PID: {proc.pid}, Ligne: {' '.join(cmdline)})",
                    level="DEBUG")
                return True
    except Exception as e:
        log(f"SystemUtils: Erreur inattendue dans is_printer_service_running: {e}", level="ERROR")
        return False
    return False


def is_past_business_hours(last_update):
    """
    Vérifie si la date/heure actuelle est postérieure à un timestamp donné
    plus un certain nombre d'heures ouvrées (par défaut 48).
    Retourne True si plus de 48h ouvrées se sont écoulées depuis last_update.
    Retourne False si moins de 48h se sont écoulées, ou si last_update est invalide.
    Args:
        last_update (str): Le timestamp de départ au format ISO (ex: "YYYY-MM-DDTHH:MM:SS.ffffff").
    Returns:
        bool: True si le délai est dépassé, False sinon (ou en cas d'erreur de parsing).
    """
    try:
        last_update_time = datetime.fromisoformat(last_update)
    except (TypeError, ValueError):
        log("SystemUtils: Erreur : timestamp_last_update invalide.")
        return False

    limit_time = add_business_hours(last_update_time, 48)
    return datetime.now() > limit_time


def add_business_hours(start_time, hours):
    """
    Ajoute un nombre d'heures ouvrées (lundi-vendredi, 24h/24) à une date/heure donnée.
    Ignore les heures tombant le samedi (weekday 5) ou le dimanche (weekday 6).
    Si start_time est un week-end, le calcul commence au lundi suivant à 00:00.
    Args:
        start_time (datetime): Le moment de départ du calcul.
        hours (int): Le nombre d'heures ouvrées à ajouter.
    Returns:
        datetime: Le moment correspondant à start_time + N heures ouvrées.
    """
    end_time = start_time
    remaining_hours = hours

    # Si on commence un Samedi ou Dimanche, avancer au Lundi 00:00 suivant
    while end_time.weekday() >= 5:  # 5 = Samedi, 6 = Dimanche
        end_time += timedelta(days=1)
        # Remet à minuit en avançant au lundi
        end_time = end_time.replace(hour=0, minute=0, second=0)

    # Ajoute les heures une par une, en décomptant seulement si c'est un jour ouvré
    while remaining_hours > 0:
        end_time += timedelta(hours=1)
        # Vérifie si la NOUVELLE heure est un jour ouvré (0=Lundi, 4=Vendredi)
        if end_time.weekday() < 5:
            remaining_hours -= 1

    return end_time
