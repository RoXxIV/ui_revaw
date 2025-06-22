# src/utils/__init__.py
"""
Module utilitaires centralisé pour le système de test de batteries.

Ce module regroupe toutes les fonctions utilitaires organisées par famille :
- config_manager : Gestion des configurations des bancs
- data_operations : Opérations sur les données et fichiers  
- system_utils : Utilitaires système et logging
"""

# Imports depuis les modules spécialisés
from .config_manager import (load_bancs_config, save_bancs_config, create_default_config, get_banc_info,
                             get_banc_for_serial, set_banc_status, update_bancs_config_current_step,
                             reset_specific_banc)

from .data_operations import (find_battery_folder, is_battery_checked, get_charge_duration, get_temperature_coefficient)

from .system_utils import (log, is_banc_running, is_printer_service_running, is_past_business_hours, add_business_hours)
from .config_manager import NUM_BANCS, VALID_BANCS, CONFIG_PATH
from .data_operations import DATA_DIR, SERIALS_CSV_PATH, CHARGE_PROFILE_PATH, TEMP_COEFF_PATH
from .system_utils import MQTT_BROKER, MQTT_PORT, LOG_FILE, LOG_LEVELS, CURRENT_LOG_LEVEL

# Export de toutes les fonctions pour compatibilité
__all__ = [
    # Configuration Management
    'load_bancs_config',
    'save_bancs_config',
    'create_default_config',
    'get_banc_info',
    'get_banc_for_serial',
    'set_banc_status',
    'update_bancs_config_current_step',
    'reset_specific_banc',

    # Data Operations
    'find_battery_folder',
    'is_battery_checked',
    'get_charge_duration',
    'get_temperature_coefficient',

    # System Utils
    'log',
    'is_banc_running',
    'is_printer_service_running',
    'is_past_business_hours',
    'add_business_hours',

    # Constantes
    'NUM_BANCS',
    'VALID_BANCS',
    'CONFIG_PATH',
    'DATA_DIR',
    'SERIALS_CSV_PATH',
    'CHARGE_PROFILE_PATH',
    'TEMP_COEFF_PATH',
    'MQTT_BROKER',
    'MQTT_PORT',
    'LOG_FILE',
    'LOG_LEVELS',
    'CURRENT_LOG_LEVEL'
]

# Informations du module
__version__ = '2.0.0'
__author__ = 'Revaw Team'
