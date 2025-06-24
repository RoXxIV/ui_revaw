"""
Module de configuration et templates pour les emails.
"""

from .email_templates import EmailTemplates
from .email_config import email_config, EmailConfig

__all__ = ['EmailTemplates', 'email_config', 'EmailConfig']
