# -*- coding: utf-8 -*-
"""
Utilitaires pour la gestion des fichiers et dossiers des bancs de test.
"""
import os
from src.ui.utils import log


class FileUtils:
    """
    Classe pour gérer les opérations sur les fichiers et dossiers des bancs.
    """

    @staticmethod
    def find_battery_folder(serial_number, data_dir, banc):
        """
        Recherche le dossier correspondant à un numéro de série spécifique
        UNIQUEMENT dans le sous-dossier du banc actuel.
        
        Args:
            serial_number (str): Le numéro de série à rechercher.
            data_dir (str): Répertoire de données principal
            banc (str): Nom du banc
            
        Returns:
            str | None: Le chemin complet du dossier trouvé, ou None s'il n'existe pas
                        dans le dossier de ce banc.
        """
        # Construit le chemin vers le sous-dossier spécifique à ce banc (ex: "data/banc1").
        banc_path = os.path.join(data_dir, banc)
        if os.path.exists(banc_path):
            try:  # Liste tous les fichiers et dossiers directement dans le sous-dossier du banc.
                for folder in os.listdir(banc_path):
                    if folder.endswith(f"-{serial_number}"):
                        found_path = os.path.join(banc_path, folder)
                        log(f"{banc}: Dossier/Item trouvé pour {serial_number} dans {banc_path}: {folder}",
                            level="DEBUG")
                        return found_path
            except OSError as e:  # Plus spécifique
                log(f"{banc}: Erreur d'accès au dossier {banc_path} lors de la recherche de {serial_number}: {e}",
                    level="ERROR")
            except Exception as e:  # Catch-all
                log(f"{banc}: Erreur inattendue lors de la recherche dans {banc_path}: {e}", level="ERROR")
        # Si le dossier du banc n'existe pas ou si rien n'est trouvé dedans
        return None
