# -*- coding: utf-8 -*-
"""
Configuration pour le service d'impression des étiquettes.
"""


class PrinterConfig:
    """
    Configuration centralisée pour l'imprimante et les services MQTT.
    """

    # --- Configuration MQTT ---
    MQTT_BROKER_HOST = "localhost"
    MQTT_BROKER_PORT = 1883
    # Topics MQTT
    MQTT_TOPIC_CREATE_LABEL = "printer/create_label"
    MQTT_TOPIC_REQUEST_FULL_REPRINT = "printer/request_full_reprint"
    MQTT_TOPIC_UPDATE_SHIPPING_TIMESTAMP = "printer/update_shipping_timestamp"
    MQTT_TOPIC_TEST_DONE = "printer/test_done"
    MQTT_TOPIC_CREATE_BATCH_LABELS = "printer/create_batch_labels"
    # --- Configuration Imprimante ---
    PRINTER_IP = "192.168.1.100"  # ip de l'imprimante
    PRINTER_PORT = 9100
    # --- Intervalles et Timeouts (secondes) ---
    RETRY_DELAY_ON_ERROR_S = 10
    POLL_DELAY_WHEN_IDLE_S = 1
    DELAY_AFTER_SUCCESS_S = 0.5
    SOCKET_TIMEOUT_S = 3  # Timeout pour la connexion ET la réception du statut
    # --- Constantes pour les Statuts ---
    STATUS_OK = "OK"
    STATUS_MEDIA_OUT = "MEDIA_OUT"  # Plus de papier/étiquettes
    STATUS_HEAD_OPEN = "HEAD_OPEN"  # Tête d'impression ouverte
    STATUS_PAUSED = "PAUSED"  # Imprimante en pause
    STATUS_ERROR_COMM = "ERROR_COMM"  # Erreur de communication
    STATUS_ERROR_UNKNOWN = "ERROR_UNKNOWN"  # Réponse non reconnue
    # --- Masques de Bits pour les Erreurs ---
    ERROR_MASK_MEDIA_OUT = 0x01  # Bit 0
    ERROR_MASK_RIBBON_OUT = 0x02  # Bit 1 (Ignoré pour Direct Thermal)
    ERROR_MASK_HEAD_OPEN = 0x04  # Bit 2
    ERROR_MASK_CUTTER_FAULT = 0x08  # Bit 3
    # --- Configuration CSV et Sériaux ---
    SERIAL_CSV_FILE = "printed_serials.csv"
    SERIAL_PREFIX = "RW-48v271"
    SERIAL_NUMERIC_LENGTH = 4
