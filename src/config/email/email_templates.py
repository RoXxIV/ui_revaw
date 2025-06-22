# src/config/email_templates.py
"""
Templates et configuration pour les emails du système de test de batteries.

Ce module centralise tous les templates d'email utilisés par l'application,
permettant une maintenance et une personnalisation plus faciles.
"""

from datetime import datetime
from typing import List


class EmailTemplates:
    """
    Classe statique contenant tous les templates d'email utilisés par l'application.
    
    Cette classe fournit des méthodes pour générer le contenu des emails
    avec les données appropriées, en séparant clairement la logique de 
    présentation de la logique métier.
    """

    # ========================================================================
    # CONFIGURATION DES SIGNATURES
    # ========================================================================

    SENDER_NAME = "Evan Hermier"
    COMPANY_NAME = "L'équipe Revaw"

    # ========================================================================
    # TEMPLATES EMAIL EXPÉDITION
    # ========================================================================

    @staticmethod
    def generate_expedition_email_content(serial_numbers: List[str], timestamp_expedition: str) -> tuple[str, str]:
        """
        Génère le contenu complet d'un email d'expédition (texte et HTML).
        
        Args:
            serial_numbers (List[str]): Liste des numéros de série expédiés
            timestamp_expedition (str): Timestamp d'expédition au format ISO
            
        Returns:
            tuple[str, str]: (contenu_texte, contenu_html)
        """
        # Formatage de la date
        try:
            dt_expedition = datetime.fromisoformat(timestamp_expedition)
            date_formatee = dt_expedition.strftime("%d/%m/%Y à %H:%M:%S")
        except ValueError:
            date_formatee = timestamp_expedition

        # Génération du contenu texte
        contenu_texte = EmailTemplates._generate_expedition_text_content(serial_numbers, date_formatee)

        # Génération du contenu HTML
        contenu_html = EmailTemplates._generate_expedition_html_content(serial_numbers, date_formatee)

        return contenu_texte, contenu_html

    @staticmethod
    def generate_expedition_subject(timestamp_expedition: str) -> str:
        """
        Génère l'objet de l'email d'expédition.
        
        Args:
            timestamp_expedition (str): Timestamp d'expédition au format ISO
            
        Returns:
            str: L'objet de l'email formaté
        """
        try:
            dt_expedition = datetime.fromisoformat(timestamp_expedition)
            date_formatee = dt_expedition.strftime("%d/%m/%Y à %H:%M:%S")
        except ValueError:
            date_formatee = timestamp_expedition

        return f"Récapitulatif d'expedition du {date_formatee}"

    @staticmethod
    def _generate_expedition_text_content(serial_numbers: List[str], date_formatee: str) -> str:
        """
        Génère le contenu texte de l'email d'expédition.
        
        Args:
            serial_numbers (List[str]): Liste des numéros de série
            date_formatee (str): Date formatée pour l'affichage
            
        Returns:
            str: Le contenu texte complet de l'email
        """
        # Corps principal
        corps_principal = f"Bonjour,\n\nVoici la liste des batteries marquées comme expédiées le {date_formatee}:\n\n"

        # Liste des batteries
        for serial in serial_numbers:
            corps_principal += f"- {serial}\n"

        # Formule de politesse
        formule_politesse = f"\nCordialement,\n{EmailTemplates.SENDER_NAME}\n"

        # Zone de signature manuelle
        zone_signature = """
Nom : _________________________

Signature :


_________________________________________
"""

        # Signature de l'entreprise
        signature_entreprise = f"""
-- 
{EmailTemplates.COMPANY_NAME}
"""

        return corps_principal + formule_politesse + zone_signature + signature_entreprise

    @staticmethod
    def _generate_expedition_html_content(serial_numbers: List[str], date_formatee: str) -> str:
        """
        Génère le contenu HTML de l'email d'expédition.
        
        Args:
            serial_numbers (List[str]): Liste des numéros de série
            date_formatee (str): Date formatée pour l'affichage
            
        Returns:
            str: Le contenu HTML complet de l'email
        """
        # En-tête et introduction
        html_intro = f"""
        <html>
          <body>
            <p>Bonjour,</p>
            <p>Voici la liste des batteries marquées comme expédiées le <strong>{date_formatee}</strong>:</p>
            <ul>
        """

        # Liste des batteries
        html_liste = ""
        for serial in serial_numbers:
            html_liste += f"<li>{serial}</li>"

        # Fermeture de la liste et formule de politesse
        html_corps = f"""
            </ul>
            <p>Cordialement,</p>
            <p>{EmailTemplates.SENDER_NAME}</p>
        """

        # Zone de signature manuelle
        html_signature_zone = """
        <div style="margin-top: 40px; font-family: Arial, sans-serif; font-size: 14px;">
            <p><strong>Nom :</strong></p>
            <p style="margin-top: 20px;"><strong>Signature :</strong></p>
            <div style="border: 1px solid #000; height: 80px; width: 280px; margin-bottom: 5px;"></div>
        </div>
        """

        # Signature de l'entreprise
        html_signature_entreprise = f"""
        <hr>
        <p style="color: #666666; font-family: Arial, sans-serif; font-size: 12px;">
          <strong>{EmailTemplates.COMPANY_NAME}</strong><br>
        </p>
        """

        # Fermeture HTML
        html_fermeture = """
          </body>
        </html>
        """

        return (html_intro + html_liste + html_corps + html_signature_zone + html_signature_entreprise + html_fermeture)
