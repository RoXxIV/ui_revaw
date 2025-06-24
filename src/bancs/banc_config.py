# -*- coding: utf-8 -*-
class BancConfig:
    """
    Configuration pour banc.py
    """

    BMS_DATA_TIMEOUT_S = 30  # Délai d'inactivité BMS avant alerte (secondes)
    BMS_CHECK_INTERVAL_S = 10  # Intervalle de vérification du timeout (secondes)
    NUM_CELLS = 15  # Nombre de cellules pour header CSV

    # repertoire de sauvegarde des testsfails
    FAILS_ARCHIVE_DIR = "data/archive_fails"

    SOCKET_TIMEOUT_S = 3
    PAUSE_DURATION_FINAL_S = 5.0  # Pause avant déconnexion finale et fermeture de l'instance
