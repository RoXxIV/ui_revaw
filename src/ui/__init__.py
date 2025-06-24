# -*- coding: utf-8 -*-
"""
Package 'ui' pour l'interface utilisateur et la logique associée.

Ce package regroupe tous les composants et la logique liés à l'interface
graphique, y compris la gestion des scans, l'envoi d'e-mails, les
composants graphiques réutilisables, et les handlers de messages MQTT.
"""

# --- Imports depuis les sous-modules ---

# Depuis le gestionnaire de scan
from .scan.scan_manager import ScanManager

# Depuis les composants graphiques réutilisables
from .ui_components import (create_block_labels, update_soc_canvas, MultiColorProgress)

# Depuis le module de gestion des e-mails
from .email.email_templates import EmailTemplates
from .email.email_config import email_config, EmailConfig

# Depuis les handlers de messages MQTT
from .message_handlers import get_ui_message_handlers

__all__ = [
    # Exportations de scan et email
    'ScanManager',
    'EmailTemplates',
    'email_config',
    'EmailConfig',

    # Exportations réelles de ui_components.py
    'create_block_labels',
    'update_soc_canvas',
    'MultiColorProgress',

    # Handlers MQTT
    'get_ui_message_handlers',
]
