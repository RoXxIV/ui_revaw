# -*- coding: utf-8 -*-
"""
Package 'ui' pour l'interface utilisateur et la logique associée.

Ce package regroupe tous les composants et la logique liés à l'interface
graphique, y compris la gestion des scans, l'envoi d'e-mails, les
composants graphiques réutilisables, et les handlers de messages MQTT.
"""

# --- Imports depuis les sous-modules ---

# Depuis le gestionnaire de scan
from .scan_manager import ScanManager

# Depuis les composants graphiques réutilisables
from .ui_components import (create_block_labels, update_soc_canvas, MultiColorProgress)

# Depuis le module de gestion des e-mails
from .email.email_templates import EmailTemplates
from .email.email_config import email_config, EmailConfig

# Depuis les handlers de messages MQTT
from .message_handlers import get_ui_message_handlers
# Depuis le module de gestion des phases
from .phase_calculator import PhaseCalculator
from .animation_manager import AnimationManager
from .ui_updater import UIUpdater
# Depuis le module de gestion des bancs
from .config_manager import load_bancs_config, NUM_BANCS, DATA_DIR
from .system_utils import log, MQTT_BROKER, MQTT_PORT
from .data_operations import get_charge_duration, get_temperature_coefficient

__all__ = [
    'ScanManager',
    'EmailTemplates',
    'email_config',
    'EmailConfig',
    'create_block_labels',
    'update_soc_canvas',
    'MultiColorProgress',
    'get_ui_message_handlers',
    'PhaseCalculator',
    'AnimationManager',
    'UIUpdater',
    'load_bancs_config',
    'NUM_BANCS',
    'log',
    'MQTT_BROKER',
    'MQTT_PORT',
    'get_charge_duration',
    'get_temperature_coefficient',
    'ScanManager',
    'DATA_DIR',
]
