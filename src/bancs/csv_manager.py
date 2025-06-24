"""
Gestionnaire pour les fichiers CSV des bancs de test.
"""
import csv
import os
from src.ui.utils import log
from .banc_config import BancConfig


class CSVManager:
    """
    Classe pour gérer les opérations CSV des bancs de test.
    """

    @staticmethod
    def create_data_csv(battery_folder, banc):
        """
        Crée le fichier data.csv dans le dossier spécifié s'il n'existe pas déjà,
        et écrit la ligne d'en-tête (header).
        Args:
            battery_folder (str): Le chemin complet du dossier où créer le fichier CSV.
            banc (str): Nom du banc pour les logs
        Returns:
            None
        """
        csv_path = os.path.join(battery_folder, "data.csv")
        if not os.path.exists(csv_path):
            log(f"{banc}: Le fichier {csv_path} n'existe pas, tentative de création.", level="INFO")
            try:
                # Ouvre le fichier en mode écriture ('w')
                with open(csv_path, "w", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)  # Crée un objet pour écrire au format CSV
                    # Définit la ligne d'en-tête
                    header = [
                        "Timestamp", "Mode", "Voltage", "Current", "SOC", "Temperature", "MaxCellNum", "MaxCellV",
                        "MinCellNum", "MinCellV", "DischargedCapacity", "DischargedEnergy"
                    ] + [f"Cell_{i+1}mV" for i in range(BancConfig.NUM_CELLS)] + ["HeartBeat", "AverageNurseSOC"]
                    writer.writerow(header)  # Ecrit la ligne d'en-tête
                    log(f"{banc}: Fichier {csv_path} créé avec succès.", level="INFO")
            except OSError as e:
                log(f"{banc}: ERREUR CRITIQUE - Impossible de créer/écrire dans {csv_path}: {e}", level="ERROR")
            except Exception as e:
                log(f"{banc}: Erreur inattendue lors de la création de data.csv: {e}", level="ERROR")

    @staticmethod
    def close_csv(csv_file, csv_writer, banc):
        """
        Ferme le fichier CSV actif s'il est ouvert et réinitialise les variables.
        
        Args:
            csv_file: Fichier CSV ouvert
            csv_writer: Writer CSV
            banc (str): Nom du banc pour les logs
            
        Returns:
            tuple: (None, None) pour réinitialiser les variables globales
        """
        if csv_file is not None:
            log(f"{banc}: Tentative de fermeture du fichier CSV...", level="DEBUG")
            try:
                csv_file.close()
                log(f"{banc}: Fichier CSV fermé.", level="INFO")
            except Exception as e:
                log(f"Erreur lors de la fermeture du CSV : {e}", level="ERROR")
            finally:
                return None, None  # Réinitialise csv_file et csv_writer
        else:
            log(f"{banc}: Aucun fichier CSV ouvert pour fermer.", level="DEBUG")
            return None, None

    @staticmethod
    def open_csv_for_append(battery_folder_path, banc):
        """
        Ouvre le fichier CSV en mode append pour l'écriture.
        
        Args:
            battery_folder_path (str): Chemin du dossier batterie
            banc (str): Nom du banc pour les logs
            
        Returns:
            tuple: (csv_file, csv_writer) ou (None, None) en cas d'erreur
        """
        data_csv_path = os.path.join(battery_folder_path, "data.csv")
        log(f"{banc}: Ouverture du fichier CSV en mode append: {data_csv_path}", level="INFO")

        try:
            # `buffering=1` force l'écriture ligne par ligne (peut être utile en cas de crash).
            csv_file = open(data_csv_path, "a", newline="", encoding="utf-8", buffering=1)
            csv_writer = csv.writer(csv_file)
            return csv_file, csv_writer
        except Exception as e:
            log(f"{banc}: ERREUR CRITIQUE - Impossible d'ouvrir {data_csv_path} en mode append: {e}", level="ERROR")
            return None, None
