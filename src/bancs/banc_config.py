"""
Configuration pour les bancs de test de batteries.
"""


class BancConfig:
    """
    Configuration centralisée pour les bancs de test.
    """

    # === CONSTANTES BMS ===
    BMS_DATA_TIMEOUT_S = 30  # Délai d'inactivité BMS avant alerte (secondes)
    BMS_CHECK_INTERVAL_S = 10  # Intervalle de vérification du timeout (secondes)
    NUM_CELLS = 15  # Nombre de cellules pour header CSV

    # === RÉPERTOIRES ===
    FAILS_ARCHIVE_DIR = "data/archive_fails"

    # === TIMEOUTS ET DÉLAIS ===
    SOCKET_TIMEOUT_S = 3
    PAUSE_DURATION_FINAL_S = 5.0  # Pause avant déconnexion finale
