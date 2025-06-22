# src/config/__init__.py
"""
Module de configuration pour le système de test de batteries.

Ce module centralise toutes les configurations et templates
utilisés par l'application.
"""

from .email.email_templates import EmailTemplates
from .email.email_config import email_config, EmailConfig
from .labels.label_templates import LabelTemplates
from .labels.printer_config import PrinterConfig
# Expose les classes principales du module
__all__ = ['EmailTemplates', 'email_config', 'EmailConfig', 'LabelTemplates', 'PrinterConfig']

# Informations du module
__version__ = '1.0.0'
__author__ = 'Evan Hermier'
