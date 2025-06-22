# src/config/email_config.py
"""
Gestionnaire de configuration email pour le système de test de batteries.

Ce module centralise le chargement et la gestion de la configuration email,
offrant une interface propre pour accéder aux paramètres SMTP et destinataires.
"""

import json
import os
from typing import List, Optional
from src.utils import log


class EmailConfig:
    """
    Gestionnaire de configuration email avec chargement automatique et fallback.
    
    Cette classe encapsule le chargement de la configuration email depuis
    le fichier JSON et fournit des valeurs par défaut sécurisées en cas d'erreur.
    """

    # Chemin vers le fichier de configuration (relatif au module)
    CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "email_config.json")

    def __init__(self):
        """Initialise le gestionnaire de configuration email."""
        self._config_data = {}
        self._load_config()

    def _load_config(self) -> None:
        """
        Charge la configuration email depuis le fichier JSON.
        
        En cas d'erreur, les propriétés retourneront des valeurs par défaut vides
        et un log d'erreur sera émis.
        """
        try:
            if not os.path.exists(self.CONFIG_FILE_PATH):
                log(f"EmailConfig: Fichier de configuration non trouvé: {self.CONFIG_FILE_PATH}", level="ERROR")
                return

            with open(self.CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                self._config_data = json.load(f)
                log(f"EmailConfig: Configuration email chargée depuis {self.CONFIG_FILE_PATH}", level="INFO")

        except json.JSONDecodeError as e:
            log(f"EmailConfig: Erreur de format JSON dans {self.CONFIG_FILE_PATH}: {e}", level="ERROR")
            self._config_data = {}
        except Exception as e:
            log(f"EmailConfig: Erreur lors du chargement de la configuration email: {e}", level="ERROR")
            self._config_data = {}

    @property
    def gmail_user(self) -> str:
        """
        Retourne l'adresse email Gmail utilisée pour l'envoi.
        
        Returns:
            str: L'adresse email ou chaîne vide si non configurée
        """
        return self._config_data.get("GMAIL_USER", "")

    @property
    def gmail_password(self) -> str:
        """
        Retourne le mot de passe d'application Gmail.
        
        Returns:
            str: Le mot de passe ou chaîne vide si non configuré
        """
        return self._config_data.get("GMAIL_PASSWORD", "")

    @property
    def recipient_emails(self) -> List[str]:
        """
        Retourne la liste des destinataires pour les emails.
        
        Returns:
            List[str]: Liste des adresses email destinataires (vide si non configurée)
        """
        recipients = self._config_data.get("RECIPIENT_EMAILS", [])
        if not isinstance(recipients, list):
            log("EmailConfig: RECIPIENT_EMAILS doit être une liste. Utilisation d'une liste vide.", level="WARNING")
            return []
        return recipients

    @property
    def smtp_server(self) -> str:
        """
        Retourne l'adresse du serveur SMTP.
        
        Returns:
            str: L'adresse du serveur SMTP (par défaut: smtp.gmail.com)
        """
        return self._config_data.get("GMAIL_SMTP_SERVER", "smtp.gmail.com")

    @property
    def smtp_port(self) -> int:
        """
        Retourne le port du serveur SMTP.
        
        Returns:
            int: Le port SMTP (par défaut: 465 pour SSL)
        """
        port = self._config_data.get("GMAIL_SMTP_PORT", 465)
        try:
            return int(port)
        except (ValueError, TypeError):
            log(f"EmailConfig: Port SMTP invalide '{port}'. Utilisation du port par défaut 465.", level="WARNING")
            return 465

    def is_configured(self) -> bool:
        """
        Vérifie si la configuration email est complète et utilisable.
        
        Returns:
            bool: True si la configuration est complète, False sinon
        """
        return bool(self.gmail_user and self.gmail_password and self.recipient_emails and self.smtp_server
                    and self.smtp_port)

    def get_missing_config_items(self) -> List[str]:
        """
        Retourne la liste des éléments de configuration manquants.
        
        Returns:
            List[str]: Liste des clés de configuration manquantes ou invalides
        """
        missing = []

        if not self.gmail_user:
            missing.append("GMAIL_USER")
        if not self.gmail_password:
            missing.append("GMAIL_PASSWORD")
        if not self.recipient_emails:
            missing.append("RECIPIENT_EMAILS")
        if not self.smtp_server:
            missing.append("GMAIL_SMTP_SERVER")
        if not self.smtp_port:
            missing.append("GMAIL_SMTP_PORT")

        return missing

    def reload_config(self) -> None:
        """
        Recharge la configuration depuis le fichier.
        
        Utile si le fichier de configuration a été modifié pendant l'exécution.
        """
        log("EmailConfig: Rechargement de la configuration email...", level="INFO")
        self._load_config()


# Instance globale pour l'utilisation dans l'application
email_config = EmailConfig()
