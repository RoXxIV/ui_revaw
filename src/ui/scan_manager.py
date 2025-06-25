# -*- coding: utf-8 -*-
import re
import json
import time
import os
import subprocess
import sys
from datetime import datetime
from .config_manager import (VALID_BANCS, get_banc_info, get_banc_for_serial, set_banc_status, reset_specific_banc,
                             DATA_DIR)
from .data_operations import (find_battery_folder, is_battery_checked, DATA_DIR)
from .system_utils import (log, is_banc_running, is_printer_service_running, is_past_business_hours)
from .ui_components import get_phase_message


class ScanManager:
    """
    Gestionnaire centralisé pour toutes les opérations de scan dans l'interface.
    
    Cette classe encapsule la logique de scan pour :
    - Scanner les bancs
    - Scanner les numéros de série  
    - Gérer les confirmations
    - Gérer les timeouts
    - Mettre à jour l'interface utilisateur
    
    Elle suit un pattern de machine à états (state machine) pour gérer
    les différentes étapes du processus de scan.
    """

    # === CONSTANTES D'ÉTAT ===
    STATE_IDLE = 0  # Attente scan banc
    STATE_AWAIT_SERIAL = 1  # Attente scan numéro de série
    STATE_AWAIT_CONFIRM_BANC = 2  # Attente confirmation banc
    STATE_AWAIT_RESET_BANC = 3  # Attente banc pour reset
    STATE_AWAIT_RESET_CONFIRM = 4  # Attente confirmation reset
    STATE_AWAIT_REPRINT_SERIAL = 5  # Attente numéro de série pour réimpression
    STATE_AWAIT_REPRINT_CONFIRM = 6  # Attente confirmation réimpression
    STATE_AWAIT_EXPEDITION_SERIAL = 8  # Attente numéros de série expédition
    STATE_AWAIT_EXPEDITION_CONFIRM = 9  # Attente confirmation expédition

    # === CONSTANTES DIVERSES ===
    BANC_STATUS_AVAILABLE = "available"
    BANC_STATUS_OCCUPIED = "occupied"
    SERIAL_PATTERN = r"RW-48v271[A-Za-z0-9]{4}"
    SCAN_TIMEOUT_S = 15

    def __init__(self, ui_app):
        """
        Initialise le gestionnaire de scan.
        
        Args:
            ui_app: Instance de l'application UI (classe App de ui.py)
                   Utilisée pour accéder aux widgets et méthodes de l'UI
        """
        self.app = ui_app  # Référence vers l'application UI

        # === ÉTAT DU SCAN ===
        self.current_state = self.STATE_IDLE

        # === DONNÉES TEMPORAIRES DU SCAN ===
        self.scanned_banc = None  # Banc scanné en cours de traitement
        self.scanned_serial = None  # Numéro de série scanné
        self.pending_serial = None  # Numéro de série attendu par un banc occupé
        self.banc_is_available = None  # True si le banc scanné est libre
        self.banc_to_reset = None  # Banc ciblé pour reset
        self.serial_to_reprint = None  # Numéro de série à réimprimer

        # === GESTION VALIDATION BATTERIE ===
        self.battery_validation_warning = False
        # === MODE EXPÉDITION ===

        self.expedition_mode_active = False
        self.serials_for_expedition = []  # Liste des numéros de série pour expédition

        # === GESTION DU TIMEOUT ===
        self.timeout_timer_id = None  # ID du timer de timeout

        log("ScanManager initialisé", level="INFO")

    def process_scan(self, scanned_text):
        """
        Point d'entrée principal pour traiter un scan.
        
        Cette méthode analyse le texte scanné et l'aiguille vers
        le bon handler selon l'état actuel du scan.
        
        Args:
            scanned_text (str): Le texte scanné par l'utilisateur
        """
        scanned_text = scanned_text.strip()
        if not scanned_text:
            return  # Ignorer les scans vides

        log(f"ScanManager: Traitement scan '{scanned_text}' dans état {self.current_state}", level="INFO")

        # === COMMANDES SPÉCIALES (disponibles depuis l'état IDLE) ===
        if self.current_state == self.STATE_IDLE:
            if self._handle_special_commands(scanned_text):
                return  # Commande spéciale traitée, on s'arrête ici

        # === COMMANDE CANCEL (disponible en mode expédition) ===
        if scanned_text.lower() == "cancel" and self.expedition_mode_active:
            self._handle_expedition_cancel()
            return
        elif scanned_text.lower() == "expedition":
            # Second scan "expedition" pour finaliser
            self._change_state(self.STATE_AWAIT_EXPEDITION_CONFIRM)
            self._handle_expedition_confirm()
            return

        # === DISPATCH SELON L'ÉTAT ACTUEL ===
        state_handlers = {
            self.STATE_IDLE: self._handle_idle_state,
            self.STATE_AWAIT_SERIAL: self._handle_await_serial_state,
            self.STATE_AWAIT_CONFIRM_BANC: self._handle_await_confirm_state,
            self.STATE_AWAIT_RESET_BANC: self._handle_await_reset_banc_state,
            self.STATE_AWAIT_RESET_CONFIRM: self._handle_await_reset_confirm_state,
            self.STATE_AWAIT_REPRINT_SERIAL: self._handle_await_reprint_serial_state,
            self.STATE_AWAIT_REPRINT_CONFIRM: self._handle_await_reprint_confirm_state,
            self.STATE_AWAIT_EXPEDITION_SERIAL: self._handle_await_expedition_serial_state,
        }

        handler = state_handlers.get(self.current_state)
        if handler:
            handler(scanned_text)
        else:
            log(f"ScanManager: État inconnu {self.current_state}", level="ERROR")
            self._reset_scan()

    # ========================================================================
    # GESTION DES COMMANDES SPÉCIALES
    # ========================================================================
    def _handle_special_commands(self, text):
        """
        Gère les commandes spéciales disponibles depuis l'état IDLE.
        
        Args:
            text (str): Le texte scanné
            
        Returns:
            bool: True si une commande spéciale a été traitée, False sinon
        """
        text_lower = text.lower()

        # === COMMANDE RESET ===
        if text_lower == "reset":
            return self._handle_reset_command()

        # === COMMANDE CREATE ===
        if text_lower.startswith("create "):
            return self._handle_create_command(text)

        # === COMMANDE END ===
        if text_lower == "end":
            return self._handle_end_command()

        # === COMMANDE REPRINT ===
        if text_lower == "reprint":
            return self._handle_reprint_command()

        # === COMMANDE EXPEDITION ===
        if text_lower == "expedition":
            return self._handle_expedition_command()

        return False  # Aucune commande spéciale trouvée

    def _handle_reset_command(self):
        """Gère la commande 'reset'."""
        # Vérifie si au moins un banc peut être resetté
        if not any(self.app.reset_enabled_for_banc.values()):
            self._update_ui("Reset impossible.", "Appuyer d'abord sur l'Arrêt d'Urgence du banc.")
            return True

        self._change_state(self.STATE_AWAIT_RESET_BANC)
        self._update_ui("Mode Réinitialisation Actif.", "Scanner le banc (ayant eu E-Stop) à réinitialiser.")
        return True

    def _handle_create_command(self, text):
        """Gère la commande 'create <nom>'."""
        if not is_printer_service_running():
            self._update_ui("Erreur Imprimante", "Le service d'impression ne semble pas actif.")
            return True

        # Extraction du nom du superviseur
        try:
            checker_name = text.split(" ", 1)[1].strip()
            if not checker_name:
                raise ValueError("Nom vide")
        except (IndexError, ValueError):
            self._update_ui("Format incorrect.", "Utilisez 'create <nom>'.")
            return True

        # Envoi de la commande MQTT
        if self.app.mqtt_client and self.app.mqtt_client.is_connected():
            payload = json.dumps({"checker_name": checker_name})
            self.app.mqtt_client.publish("printer/create_label", payload, qos=1)
            self._update_ui(f"Demande envoyée (validée par {checker_name.title()}).", "Vérifiez l'imprimante.")
        else:
            self._update_ui("Erreur de Connexion", "Impossible d'envoyer la commande. Vérifiez le broker MQTT.")

        return True

    def _execute_reset(self):
        """Exécute le reset d'un banc."""

        self._cancel_timeout_timer()

        if not self.banc_to_reset:
            self._update_ui("Erreur interne reset.", "Annulation.")
            self._reset_scan()
            return

        try:
            success = reset_specific_banc(self.banc_to_reset)
            if success:
                self.app.reset_ui_for_banc(self.banc_to_reset)
                self.app.reset_enabled_for_banc[self.banc_to_reset] = False
                self._update_ui(f"{self.banc_to_reset} réinitialisé.", "Veuillez scanner un banc.")
            else:
                self._update_ui(f"Erreur reset {self.banc_to_reset}.", "Vérifier logs. Scanner un banc.")
        except Exception as e:
            log(f"ScanManager: Exception lors du reset de {self.banc_to_reset}: {e}", level="ERROR")
            self._update_ui(f"Erreur reset {self.banc_to_reset}.", "Vérifier logs. Scanner un banc.")
        finally:
            self._reset_scan()

    def _send_reprint_request(self):
        """Envoie une demande de réimpression via MQTT."""
        if not (self.app.mqtt_client and self.app.mqtt_client.is_connected()):
            self._update_ui("Erreur: Client MQTT déconnecté.", "Impossible d'envoyer la demande.")
            self._reset_scan()
            return

        try:
            topic = "printer/request_full_reprint"
            self.app.mqtt_client.publish(topic, payload=self.serial_to_reprint, qos=1)
            self._update_ui("Demande réimpression envoyée.", f"Serial: {self.serial_to_reprint}")
        except Exception as e:
            log(f"ScanManager: Erreur publication réimpression: {e}", level="ERROR")
            self._update_ui("Erreur envoi demande impression.", "Vérifier connexion/logs.")
        finally:
            self._reset_scan()

    def _process_expedition(self):
        """Traite la finalisation d'une expédition."""
        log(f"ScanManager: Confirmation expédition pour {len(self.serials_for_expedition)} batteries", level="INFO")

        if not (self.app.mqtt_client and self.app.mqtt_client.is_connected()):
            self._update_ui("Erreur: Client MQTT non connecté.", "Impossible de marquer les batteries pour expédition.")
            self._reset_scan()
            return

        # Envoi des mises à jour de timestamp d'expédition
        topic_update_shipping = "printer/update_shipping_timestamp"
        current_timestamp_iso = datetime.now().isoformat()
        published_count = 0

        for serial_num in self.serials_for_expedition:
            payload_data = {"serial_number": serial_num, "timestamp_expedition": current_timestamp_iso}
            try:
                self.app.mqtt_client.publish(topic_update_shipping, payload=json.dumps(payload_data), qos=1)
                published_count += 1
            except Exception as e:
                log(f"ScanManager: Erreur publication expédition pour {serial_num}: {e}", level="ERROR")

        # Mise à jour de l'UI selon le résultat
        if published_count == len(self.serials_for_expedition):
            self._update_ui(f"{len(self.serials_for_expedition)} batterie(s) marquée(s) pour expédition.",
                            "Mise à jour CSV en cours...")

            # Tentative d'envoi d'email
            email_sent = self.app._send_expedition_email(self.serials_for_expedition, current_timestamp_iso)
            if email_sent:
                self._update_ui("", "Mise à jour CSV et Email d'expédition envoyés.")
            else:
                self._update_ui("", "Mise à jour CSV OK, erreur envoi email.")
        else:
            self._update_ui(f"Erreur partielle lors de la MàJ expédition.", "Vérifier les logs. Email non envoyé.")

        self._reset_scan()

    # ========================================================================
    # GESTION DE L'INTERFACE UTILISATEUR
    # ========================================================================
    def _update_banc_ui(self):
        """Met à jour l'interface utilisateur du banc après lancement d'un test."""
        widgets = self.app.banc_widgets.get(self.scanned_banc)
        if not widgets:
            return

        # Mise à jour des icônes
        self.app.update_status_icon(self.scanned_banc, 'charger', 'off')
        self.app.update_status_icon(self.scanned_banc, 'nurses', 'off')

        # Mise à jour du label principal
        banc_info = get_banc_info(self.scanned_banc)
        banc_name = banc_info.get("name", self.scanned_banc) if banc_info else self.scanned_banc
        widgets["banc"].configure(text=f"{banc_name} - {self.scanned_serial}")

        # Réinitialisation de l'état du banc
        widgets["current_step"] = 0

        # Réinitialisation des animations et barres de progression
        self.app.finalize_previous_phase(self.scanned_banc)

        # Réinitialisation de la bordure
        parent_frame = widgets.get("parent_frame")
        if parent_frame:
            parent_frame.configure(border_color="white", border_width=self.app.NORMAL_BORDER_WIDTH)

        # Réinitialisation de la barre de progression
        progress_bar = widgets.get("progress_bar_phase")
        if progress_bar and hasattr(progress_bar, 'reset'):
            try:
                progress_bar.reset()
            except Exception as e:
                log(f"ScanManager: Erreur reset progress_bar: {e}", level="ERROR")

        # Réinitialisation des widgets Ri/Diffusion
        if widgets.get("ri"):
            widgets["ri"].configure(text="0.00")
        if widgets.get("diffusion"):
            widgets["diffusion"].configure(text="0.00")

        # Réinitialisation des labels temps et phase
        if widgets.get("time_left"):
            widgets["time_left"].configure(text="00h00min")
        if widgets.get("phase"):
            widgets["phase"].configure(text=get_phase_message(0))

    def _setup_battery_folder(self):
        """Configure le chemin du dossier de la batterie dans les widgets."""
        widgets = self.app.banc_widgets.get(self.scanned_banc)
        if not widgets:
            return

        try:
            # Importer DATA_DIR depuis le bon module
            from .config_manager import DATA_DIR
            from .data_operations import find_battery_folder

            # Vérification que DATA_DIR est bien une string
            if not isinstance(DATA_DIR, str):
                raise ValueError("DATA_DIR must be a string")

            # Vérification que les variables nécessaires existent
            if not self.scanned_serial or not self.scanned_banc:
                raise ValueError("scanned_serial et scanned_banc doivent être définis")

            # Chercher d'abord un dossier existant
            determined_path = find_battery_folder(self.scanned_serial)

            # Si aucun dossier existant, créer le chemin pour un nouveau
            if determined_path is None:  # Explicitement vérifier None
                from datetime import datetime
                import os
                timestamp = datetime.now().strftime("%d%m%Y")
                # S'assurer que tous les arguments de join sont des strings
                determined_path = os.path.join(
                    str(DATA_DIR), str(self.scanned_banc), f"{timestamp}-{str(self.scanned_serial)}")
                log(f"ScanManager: Nouveau chemin batterie créé: {determined_path}", level="DEBUG")
            else:
                log(f"ScanManager: Dossier batterie existant trouvé: {determined_path}", level="DEBUG")

            # Stocker le chemin dans les widgets
            widgets["battery_folder_path"] = determined_path
            log(f"ScanManager: Chemin batterie stocké pour {self.scanned_banc}: {determined_path}", level="INFO")

        except Exception as e:
            log(f"ScanManager: Erreur setup battery folder: {e}", level="ERROR")

    # ========================================================================
    # GESTION DE L'ÉTAT ET DES TIMEOUTS
    # ========================================================================
    def _change_state(self, new_state):
        """
        Change l'état actuel du scan et annule le timer de timeout.
        
        Args:
            new_state (int): Le nouvel état
        """
        log(f"ScanManager: Changement d'état {self.current_state} -> {new_state}", level="DEBUG")
        self.current_state = new_state
        self._cancel_timeout_timer()

    def _start_timeout_timer(self):
        """Démarre un timer de timeout pour les opérations de scan."""
        # Ne pas démarrer de timer en mode expédition pour la saisie des serials
        if self.expedition_mode_active and self.current_state == self.STATE_AWAIT_EXPEDITION_SERIAL:
            return

        self._cancel_timeout_timer()  # Annuler l'ancien timer s'il existe

        timeout_ms = self.SCAN_TIMEOUT_S * 1000
        self.timeout_timer_id = self.app.after(timeout_ms, self._timeout_expired)
        log(f"ScanManager: Timer timeout démarré ({self.SCAN_TIMEOUT_S}s)", level="DEBUG")

    def _cancel_timeout_timer(self):
        """Annule le timer de timeout actuel."""
        if self.timeout_timer_id:
            try:
                self.app.after_cancel(self.timeout_timer_id)
                log("ScanManager: Timer timeout annulé", level="DEBUG")
            except ValueError:
                pass  # Timer déjà expiré
            self.timeout_timer_id = None

    def _timeout_expired(self):
        """Appelée quand le timer de timeout expire."""
        # Ignorer si on est en mode expédition
        if self.expedition_mode_active and self.current_state == self.STATE_AWAIT_EXPEDITION_SERIAL:
            self.timeout_timer_id = None
            return

        log(f"ScanManager: Timeout expiré dans l'état {self.current_state}", level="INFO")
        self._update_ui("Délai de scan dépassé.", "Veuillez recommencer, Scannez un Banc.")
        self._reset_scan()

    def _delayed_reset(self, delay_ms):
        """
        Programmer un reset du scan après un délai.
        
        Args:
            delay_ms (int): Délai en millisecondes
        """
        self._cancel_timeout_timer()
        self.app.after(delay_ms, self._reset_scan)

    def _reset_scan(self):
        """Remet le scan à l'état initial et nettoie toutes les variables."""
        log("ScanManager: Reset du scan", level="DEBUG")

        # Reset de l'état
        self.current_state = self.STATE_IDLE

        # Reset des données temporaires
        self.scanned_banc = None
        self.scanned_serial = None
        self.pending_serial = None
        self.banc_is_available = None
        self.banc_to_reset = None
        self.serial_to_reprint = None

        # === NOUVEAU : RESET VALIDATION WARNING ===
        self.battery_validation_warning = False

        # Reset du mode expédition
        self.expedition_mode_active = False
        self.serials_for_expedition = []

        # Annulation du timer
        self._cancel_timeout_timer()

        # Mise à jour de l'UI
        self._update_ui("Prêt.", "Veuillez scanner un banc...")

    def _update_ui(self, message1, message2):
        """
        Met à jour les labels de réponse de l'interface utilisateur.
        
        Args:
            message1 (str): Message pour le premier label
            message2 (str): Message pour le second label
        """
        print(f"DEBUG: _update_ui appelé avec '{message1}' et '{message2}'")
        if message1:  # Ne mettre à jour que si le message n'est pas vide
            self.app.label_response1.configure(text=message1)
        if message2:  # Ne mettre à jour que si le message n'est pas vide
            self.app.label_response2.configure(text=message2)

    def _handle_end_command(self):
        """Gère la commande 'end'."""
        if not (self.app.mqtt_client and self.app.mqtt_client.is_connected()):
            self._update_ui("Commande 'end' non envoyée.", "Client MQTT non connecté.")
            return True

        # Envoi à tous les bancs
        published_count = 0
        for i in range(1, 5):  # NUM_BANCS = 4
            topic = f"banc{i}/command"
            try:
                self.app.mqtt_client.publish(topic, payload="end", qos=1)
                published_count += 1
            except Exception as e:
                log(f"ScanManager: Erreur envoi 'end' sur {topic}: {e}", level="ERROR")

        if published_count == 4:
            self._update_ui("Commande 'end' envoyée aux 4 bancs.", "Processus de fin de journée en cours...")
        else:
            self._update_ui(f"Commande 'end' envoyée à {published_count}/4 bancs.", "Veuillez ressayer.")

        return True

    def _handle_reprint_command(self):
        """Gère la commande 'reprint'."""
        if not is_printer_service_running():
            self._update_ui("Erreur Imprimante", "Service d'impression inactif. Réimpression impossible.")
            return True

        self._change_state(self.STATE_AWAIT_REPRINT_SERIAL)
        self._update_ui("Mode Réimpression Actif.", "Scanner l'URL/Serial de la batterie à réimprimer.")
        self._start_timeout_timer()
        return True

    def _handle_expedition_command(self):
        """Gère la commande 'expedition'."""
        if self.current_state == self.STATE_IDLE:
            # Premier scan "expedition" - démarrer le mode
            if not is_printer_service_running():
                self._update_ui("Erreur Service", "Service d'impression/CSV inactif. Expédition impossible.")
                return True

            self._change_state(self.STATE_AWAIT_EXPEDITION_SERIAL)
            self.expedition_mode_active = True
            self.serials_for_expedition = []
            self._update_ui(
                "Mode Expédition : En attente des numéros de série.",
                "Scannez les S/N des batteries. Scannez 'expedition' à nouveau pour terminer ou 'cancel' pour stopper.")
            return True

        return False

    def _handle_expedition_cancel(self):
        """Gère l'annulation du mode expédition."""
        log("ScanManager: Annulation du mode expédition", level="INFO")
        self._update_ui("Processus d'expédition annulé.", "Vous pouvez recommencer.")
        self._reset_scan()

    # ========================================================================
    # GESTION DES ÉTATS PRINCIPAUX
    # ========================================================================
    def _handle_idle_state(self, text):
        """Gère l'état IDLE (attente scan banc)."""
        banc_code = text.lower()

        # Vérification que c'est un banc valide
        if banc_code not in VALID_BANCS:
            self._update_ui("", f"'{text}' non reconnu. Scanner 'banc1' à 'banc4'.")
            return

        # Vérification que le banc n'est pas déjà en cours de test
        if is_banc_running(banc_code):
            self._update_ui(f"{banc_code} est déjà en cours de test. Annulation.", "Veuillez scanner un autre banc.")
            return

        # Récupération des infos du banc
        banc_info = get_banc_info(banc_code)
        if banc_info:
            status = banc_info.get("status", self.BANC_STATUS_AVAILABLE)
            self.pending_serial = banc_info.get("serial-pending")
        else:
            status = self.BANC_STATUS_AVAILABLE
            self.pending_serial = None

        # Stockage des informations
        self.scanned_banc = banc_code
        self.banc_is_available = (status == self.BANC_STATUS_AVAILABLE)

        # Mise à jour de l'UI
        message = f"{banc_code} est {'Libre' if self.banc_is_available else 'Occupé'}"
        if not self.banc_is_available and self.pending_serial:
            message += f", serial attendu: '{self.pending_serial}'"

        self._update_ui(message, "Veuillez scanner le numéro de série.")

        # Passage à l'état suivant
        self._change_state(self.STATE_AWAIT_SERIAL)
        self._start_timeout_timer()

    def _handle_await_serial_state(self, text):
        """Gère l'état d'attente du numéro de série."""
        # Extraction du numéro de série
        serial_number = self._extract_serial_number(text)
        if not serial_number:
            self._update_ui(f"'{text}' invalide ou incorrect. Annulation.", "Veuillez recommencer (scanner un banc).")
            self._delayed_reset(2000)
            return

        self.scanned_serial = serial_number

        # === LOGIQUE DIFFÉRENTE SELON L'ÉTAT DU BANC ===
        if not self.banc_is_available:
            # === CAS 1: BANC OCCUPÉ - Vérifier d'abord si c'est le bon serial ===
            if self.scanned_serial != self.pending_serial:
                # ❌ Mauvais serial pour ce banc occupé
                self._update_ui(f"❌ Serial incorrect pour ce banc occupé !",
                                f"Serial attendu: {self.pending_serial}. Scannez le bon serial ou un autre banc.")
                self._delayed_reset(3000)  # Laisser le temps de lire
                return

            # ✅ Bon serial pour ce banc occupé - Maintenant vérifier la validation
            battery_is_validated = is_battery_checked(serial_number)
            if not battery_is_validated:
                self.battery_validation_warning = True
                log(f"ScanManager: AVERTISSEMENT - Serial correct mais batterie {serial_number} non validée",
                    level="WARNING")
                self._update_ui(f"⚠️  Serial correct mais batterie NON VALIDÉE !",
                                f"Re-scanner le {self.scanned_banc} pour continuer malgré tout.")
            else:
                self.battery_validation_warning = False
                log(f"ScanManager: Serial correct et batterie {serial_number} validée", level="INFO")
                self._update_ui("✅ Numéro de série correspondant et validé.",
                                f"Re-scanner le {self.scanned_banc} pour confirmer.")

            self._change_state(self.STATE_AWAIT_CONFIRM_BANC)
            self._start_timeout_timer()
            return

        # === CAS 2: BANC LIBRE - Vérifications normales ===

        # Vérification que le serial n'est pas assigné à un autre banc
        other_banc = get_banc_for_serial(serial_number)
        if other_banc and other_banc.lower() != self.scanned_banc:
            self._update_ui(f"Batterie {serial_number} déjà associée au {other_banc}. Annulation.",
                            "Veuillez scanner un banc.")
            self._reset_scan()
            return

        # Vérification de la validation de la batterie
        battery_is_validated = is_battery_checked(serial_number)
        if not battery_is_validated:
            self.battery_validation_warning = True
            log(f"ScanManager: AVERTISSEMENT - Batterie {serial_number} non validée pour banc libre", level="WARNING")
        else:
            self.battery_validation_warning = False
            log(f"ScanManager: Batterie {serial_number} validée pour banc libre", level="INFO")

        # Validation des conditions de nouveau test
        if self._validate_new_test():
            self._change_state(self.STATE_AWAIT_CONFIRM_BANC)

            # Messages selon la validation
            if self.battery_validation_warning:
                self._update_ui(
                    f"⚠️  ATTENTION: Batterie {serial_number} NON VALIDÉE !",
                    f"Re-scanner le {self.scanned_banc} pour continuer MALGRÉ TOUT, ou scanner un autre banc.")
            else:
                self._update_ui("✅ Batterie validée.", f"Re-scanner le {self.scanned_banc} pour confirmer.")

            self._start_timeout_timer()

    def _handle_await_confirm_state(self, text):
        """Gère l'état d'attente de confirmation du banc."""
        banc_code = text.lower()

        if banc_code != self.scanned_banc:
            self._update_ui(f"Mauvais banc scanné ({banc_code}). Attendu: {self.scanned_banc}. Annulation.",
                            "Veuillez recommencer en scannant un banc.")
            self._reset_scan()
            return

        # Vérification finale que le banc n'est pas devenu occupé entre temps
        if is_banc_running(self.scanned_banc):
            self._update_ui(f"{self.scanned_banc} est déjà en cours de test (vérification finale). Annulation.",
                            "Veuillez scanner un autre banc.")
            self._reset_scan()
            return

        # Lancement du test
        self._launch_test()

    def _handle_await_reset_banc_state(self, text):
        """Gère l'état d'attente du banc à resetter."""
        banc_id = text.lower()

        if banc_id not in VALID_BANCS:
            self._update_ui(f"'{banc_id}' n'est pas un banc valide.",
                            "Scanner un banc valide ou 'reset' pour recommencer.")
            return

        if not self.app.reset_enabled_for_banc.get(banc_id, False):
            self._update_ui(f"Reset non activé pour {banc_id}.", "Utiliser E-Stop puis rescanner 'reset' + banc.")
            self._reset_scan()
            return

        if is_banc_running(banc_id):
            self._update_ui(f"ERREUR: Processus {banc_id} tourne encore !",
                            "Arrêt complet nécessaire avant reset. Annulation.")
            self._reset_scan()
            return

        self.banc_to_reset = banc_id
        self._change_state(self.STATE_AWAIT_RESET_CONFIRM)
        self._update_ui(f"Prêt à réinitialiser {self.banc_to_reset}.", "Scanner 'reset' à nouveau pour confirmer.")
        self._start_timeout_timer()

    def _handle_await_reset_confirm_state(self, text):
        """Gère l'état d'attente de confirmation du reset."""
        if text.lower() != "reset":
            self._update_ui(f"Scan '{text}' incorrect. Attendu: 'reset'. Annulation.",
                            "Veuillez recommencer le processus si besoin.")
            self._reset_scan()
            return

        # Exécution du reset
        self._execute_reset()

    def _handle_await_reprint_serial_state(self, text):
        """Gère l'état d'attente du numéro de série pour réimpression."""
        serial_number = self._extract_serial_number(text)
        if not serial_number:
            self._update_ui(f"'{text}' invalide.", "Scanner URL/Serial valide")
            self._delayed_reset(2000)
            return

        self.serial_to_reprint = serial_number
        self._change_state(self.STATE_AWAIT_REPRINT_CONFIRM)
        self._update_ui(f"Serial '{serial_number}' prêt pour réimpression.",
                        "Scanner 'reprint' à nouveau pour confirmer.")
        self._start_timeout_timer()

    def _handle_await_reprint_confirm_state(self, text):
        """Gère l'état d'attente de confirmation de réimpression."""
        if text.lower() != "reprint":
            self._update_ui(f"Scan '{text}' incorrect. Attendu: 'reprint'. Annulation.", "Veuillez recommencer.")
            self._reset_scan()
            return

        # Vérification finale du service d'impression
        if not is_printer_service_running():
            self._update_ui("Erreur Imprimante", "Service d'impression inactif. Réimpression échouée.")
            self._reset_scan()
            return

        # Envoi de la demande de réimpression
        self._send_reprint_request()

    def _handle_await_expedition_serial_state(self, text):
        """Gère l'état d'attente des numéros de série pour expédition."""
        serial_number = self._extract_serial_number(text)
        if not serial_number:
            self._update_ui(f"Scan '{text}' non reconnu comme S/N.",
                            "Scanner un S/N valide, 'expedition' pour valider, ou 'cancel'.")
            return

        if serial_number not in self.serials_for_expedition:
            self.serials_for_expedition.append(serial_number)
            self._update_ui(f"Batterie {serial_number} ajoutée.", "")
        else:
            self._update_ui(f"Batterie {serial_number} déjà listée.", "")

        count = len(self.serials_for_expedition)
        self._update_ui("", f"{count} batterie(s) scannée(s). Scanner 'expedition' pour valider ou 'cancel'.")

    def _handle_expedition_confirm(self):
        """Finalise le processus d'expédition."""
        if not self.serials_for_expedition:
            self._update_ui("Aucune batterie n'a été scannée pour l'expédition.", "Processus d'expédition annulé.")
            self._reset_scan()
            return

        if not is_printer_service_running():
            self._update_ui("Erreur Service", "Service d'impression/CSV inactif. Mise à jour impossible.")
            self._reset_scan()
            return

        # Traitement de l'expédition (logique existante)
        self._process_expedition()

    # ========================================================================
    # UTILITAIRES DE TRAITEMENT
    # ========================================================================
    def _extract_serial_number(self, text):
        """
        Extrait un numéro de série d'un texte en utilisant une regex.
        
        Args:
            text (str): Le texte à analyser
            
        Returns:
            str|None: Le numéro de série extrait ou None si non trouvé
        """
        # === VÉRIFICATION STRICTE AVEC REGEX ===
        match = re.search(self.SERIAL_PATTERN, text)
        if match:
            extracted_serial = match.group(0)
            log(f"ScanManager: Serial extrait via regex: '{extracted_serial}'", level="DEBUG")
            return extracted_serial

        # === AUCUN SERIAL VALIDE TROUVÉ ===
        log(f"ScanManager: Aucun serial valide trouvé dans '{text}'", level="DEBUG")
        return None

    def _validate_new_test(self):
        """
        Valide qu'un nouveau test peut être lancé pour cette batterie.
        
        Returns:
            bool: True si le test peut être lancé, False sinon
        """
        # Recherche d'un dossier existant pour cette batterie
        battery_folder = find_battery_folder(self.scanned_serial)
        if not battery_folder:
            # Nouvelle batterie
            self._update_ui("Nouvelle batterie détectée.", "")
            return True

        # Batterie existante : vérifier le délai depuis le dernier test
        self._update_ui("", f"Batterie existante trouvée: {battery_folder}")

        try:
            import os
            config_path = os.path.join(battery_folder, "config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                battery_config = json.load(f)
            last_update = battery_config.get("timestamp_last_update")
        except Exception as e:
            log(f"ScanManager: Erreur lecture config batterie {self.scanned_serial}: {e}", level="ERROR")
            last_update = None

        # Vérification du délai de 48h ouvrées
        if last_update and not is_past_business_hours(last_update):
            self._update_ui(f"Dernier test < 48h ouvrées ({last_update}). Annulation.",
                            "Veuillez choisir une autre batterie ou attendre.")
            self._delayed_reset(2000)
            return False

        self._update_ui("Batterie OK pour nouveau test.", "")
        return True

    # ========================================================================
    # ACTIONS MÉTIER
    # ========================================================================
    def _launch_test(self):
        """Lance un nouveau test de batterie."""

        self._cancel_timeout_timer()

        # === AVERTISSEMENT FINAL SI BATTERIE NON VALIDÉE ===
        if self.battery_validation_warning:
            log(f"ScanManager: LANCEMENT DE TEST AVEC BATTERIE NON VALIDÉE: {self.scanned_serial}", level="WARNING")
            self._update_ui(f"⚠️  TEST LANCÉ avec batterie NON VALIDÉE: {self.scanned_serial}",
                            "Pensez à la faire valider après le test !")
            # Petite pause pour que l'utilisateur voit le message
            time.sleep(2)

        # Préparation et lancement du test
        self._update_ui(f"Confirmation {self.scanned_banc} OK.", f"Lancement du test pour {self.scanned_serial}...")

        # Mise à jour du statut si le banc était libre
        if self.banc_is_available:
            set_banc_status(self.scanned_banc, self.BANC_STATUS_OCCUPIED, serial_pending=self.scanned_serial)

            # Mise à jour de l'UI du banc
            self._update_banc_ui()

            # Détermination du chemin du dossier batterie
            self._setup_battery_folder()

        # Lancement du script banc.py
        try:
            script_path = os.path.abspath("banc.py")
            python_executable = sys.executable
            command = [python_executable, script_path, self.scanned_banc, self.scanned_serial]

            log(f"ScanManager: Lancement subprocess: {' '.join(command)}", level="INFO")
            subprocess.Popen(command)

            banc_name = self.scanned_banc
            self._update_ui(f"Test lancé sur {banc_name}.", "Scanner un banc pour démarrer un autre test.")
            self._reset_scan()

        except Exception as e:
            log(f"ScanManager: Échec lancement subprocess: {e}", level="ERROR")
            self._update_ui(f"Erreur lors du lancement du test sur {self.scanned_banc}.",
                            "Vérifier les logs. Veuillez recommencer.")

            # Restaurer le statut si nécessaire
            if self.banc_is_available:
                set_banc_status(self.scanned_banc, self.BANC_STATUS_AVAILABLE, serial_pending=None)

            self._reset_scan()
