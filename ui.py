#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tkinter as tk
from PIL import Image
import customtkinter as ctk
import os, time
import paho.mqtt.client as mqtt
import threading
import socket
from src.ui.scan_manager import ScanManager
from src.ui.config_manager import load_bancs_config, NUM_BANCS
from src.ui.system_utils import log, MQTT_BROKER, MQTT_PORT
from src.ui.ui_components import (update_soc_canvas, create_block_labels, get_phase_message)
from src.ui.email import EmailTemplates, email_config
from src.ui import get_ui_message_handlers, AnimationManager, UIUpdater
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ctk.set_appearance_mode("dark")


# --- FENETRE PRINCIPALE ---
class App(ctk.CTk):
    BANC_STATUS_AVAILABLE = "available"
    BANC_STATUS_OCCUPIED = "occupied"
    LARGE_BORDER_WIDTH_ACTIVE = 50
    NORMAL_BORDER_WIDTH = 1
    SCAN_CONFIRM_TIMEOUT_S = 15
    SERIAL_PATTERN = r"RW-48v271[A-Za-z0-9]{4}"

    def __init__(self):
        """
        Initialise l'application principale.
        Configure la fenetre, charge la config et crée les widgets pour chaque banc.
        initialise leur état visuel et met en place la zone de scan.
        """
        super().__init__()
        self._last_ui_update = {}
        # === CONFIGURATION DE LA FENÊTRE ===
        self.title("Revaw")
        self.geometry("1920x1080")
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        # === CONFIGURATION DE LA GRILLE ===
        self.rowconfigure(0, weight=5)
        self.rowconfigure(1, weight=5)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)
        self.columnconfigure((0, 1), weight=1, uniform="col")
        self.bind("<Return>", self.handle_prompt)

        # === CHARGEMENT DES ICÔNES ===
        try:
            self.status_icons = {
                "charger_on": ctk.CTkImage(Image.open("assets/charger_on.png"), size=(32, 32)),
                "charger_off": ctk.CTkImage(Image.open("assets/charger_off.png"), size=(32, 32)),
                "nurses_on": ctk.CTkImage(Image.open("assets/nurses_on.png"), size=(32, 32)),
                "nurses_off": ctk.CTkImage(Image.open("assets/nurses_off.png"), size=(32, 32))
            }
        except FileNotFoundError as e:
            log(f"UI: Icône manquante: {e}", level="ERROR")
            self.status_icons = {}

        # === CRÉATION DES WIDGETS BANCS ===
        self.config_path = "bancs_config.json"
        config = load_bancs_config(self.config_path)
        bancs = config.get("bancs", [])

        if len(bancs) < NUM_BANCS:
            raise ValueError(f"La configuration doit contenir au moins {NUM_BANCS} bancs.")

        self.banc_widgets = {}
        for i in range(NUM_BANCS):
            banc_id = f"banc{i+1}"
            try:
                row = 0 if i < NUM_BANCS // 2 else 1
                col = i % (NUM_BANCS // 2)
                frame = ctk.CTkFrame(self, corner_radius=10)
                frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
                banc_config_data = bancs[i]
                banc_text = f"{banc_config_data.get('name', banc_id)}".strip(" -")
                serial_text_init = banc_config_data.get('serial-pending') or ""
                current_step_init = banc_config_data.get("current_step")

                widgets_for_banc = create_block_labels(
                    frame,
                    banc_text=banc_text,
                    serial_text=serial_text_init,
                    current_step=current_step_init,
                    icons=self.status_icons)
                self.banc_widgets[banc_id] = widgets_for_banc
                log(f"UI: Interface pour {banc_id} créée avec succès.", level="INFO")

            except Exception as e:
                log(f"UI: ERREUR CRITIQUE lors de l'initialisation de l'interface pour {banc_id}: {e}", level="ERROR")
                pass

        # === INITIALISATION DE L'ÉTAT DES BANCS ===
        self.init_banc_status(config)
        self.mqtt_client = None

        # === ZONE SCAN (layout 3/4 + 1/4) ===

        self.frame_scan = ctk.CTkFrame(self, corner_radius=10)
        self.frame_scan.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

        # Configuration colonnes
        self.frame_scan.columnconfigure(0, weight=3)  # 3/4 scan
        self.frame_scan.columnconfigure(1, weight=1)  # 1/4 système

        # Zone scan existante (déplacer tes widgets dans frame_scan_left)
        self.frame_scan_left = ctk.CTkFrame(self.frame_scan, fg_color="transparent")
        self.frame_scan_left.grid(row=0, column=0, padx=(0, 5), sticky="nsew")
        self.frame_scan_left.columnconfigure(0, weight=1)

        self.label_response1 = ctk.CTkLabel(self.frame_scan_left, text="- ", font=("Helvetica", 16, "bold"))
        self.label_response1.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        self.label_response2 = ctk.CTkLabel(self.frame_scan_left, text="- ", font=("Helvetica", 16, "bold"))
        self.label_response2.grid(row=1, column=0, padx=10, pady=5, sticky="w")

        self.entry_prompt = ctk.CTkEntry(self.frame_scan_left, placeholder_text="Saisissez ici", font=("Helvetica", 16))
        self.entry_prompt.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="ew")

        # === ZONE SYSTÈME (1/4 droite) ===
        self.frame_system = ctk.CTkFrame(self.frame_scan, corner_radius=5, border_width=1, border_color="#404040")
        self.frame_system.grid(row=0, column=1, padx=(5, 0), pady=5, sticky="nsew")

        self.system_title = ctk.CTkLabel(
            self.frame_system, text="🔧 SYSTÈME", font=("Helvetica", 12, "bold"), text_color="#B0B0B0")
        self.system_title.pack(pady=(8, 5))

        self.system_status_label = ctk.CTkLabel(
            self.frame_system,
            text="🔄 Vérification...",
            font=("Helvetica", 11),
            text_color="#FFA500",
            wraplength=150,
            justify="left")
        self.system_status_label.pack(pady=5, padx=8, fill="x")

        # === GESTIONNAIRES SPÉCIALISÉS ===
        self.animation_manager = AnimationManager(self)
        self.ui_updater = UIUpdater(self)

        # === INITIALISATION DU GESTIONNAIRE DE SCAN ===
        self.scan_manager = ScanManager(self)
        log("UI: ScanManager initialisé", level="INFO")

        # === INITIALISATION FINALE ===
        for banc_id_init, widgets_init in self.banc_widgets.items():
            canvas_init = widgets_init.get("soc_canvas")
            if canvas_init:
                self.after(500, lambda c=canvas_init: update_soc_canvas(c, 0))

        self.after(100, lambda: self.entry_prompt.focus_set())

    def init_banc_status(self, config):
        """
        Initialise l'affichage du statut de chaque banc au démarrage.
        Pré-remplit également la barre de progression si un test est déjà en cours.
        """
        bancs = config.get("bancs", [])
        for i in range(NUM_BANCS):
            banc_id = f"banc{i+1}"
            widgets = self.banc_widgets.get(banc_id)
            if widgets:
                banc_data = bancs[i]
                status = banc_data.get("status", self.BANC_STATUS_AVAILABLE)
                if status == self.BANC_STATUS_AVAILABLE:
                    widgets["banc"].configure(text=f"{bancs[i]['name']} - Libre")
                elif status == self.BANC_STATUS_OCCUPIED:
                    serial = bancs[i].get("serial-pending", "")
                    starting_phase_raw = banc_data.get("current_step")
                    if isinstance(starting_phase_raw, int):
                        starting_phase = starting_phase_raw
                    else:
                        if starting_phase_raw is not None:
                            log(f"UI init: 'current_step' invalide ({type(starting_phase_raw)}) pour {banc_id}. Utilisation de 0.",
                                level="WARNING")
                        starting_phase = 0

                    widgets["current_step"] = starting_phase
                    widgets["banc"].configure(text=f"{bancs[i]['name']} - {serial}")
                    progress_bar = widgets.get("progress_bar_phase")

                    if progress_bar:
                        if starting_phase >= 2:
                            progress_bar.progress_ri.set(1.0)
                        if starting_phase >= 3:
                            progress_bar.progress_phase2.set(1.0)
                        if starting_phase >= 4:
                            progress_bar.progress_capa.set(1.0)

                else:
                    log(f"Statut inconnu '{status}' pour {banc_id} dans la config.", level="WARNING")
                    widgets["banc"].configure(text=f"{banc_data['name']} - Statut Inconnu")

    def update_banc_data(self, banc_id, data):
        """Met à jour les widgets d'un banc avec les données BMS reçues via MQTT."""
        # Throttling : max 1 update/seconde par banc
        now = time.time()
        if banc_id in self._last_ui_update:
            if now - self._last_ui_update[banc_id] < 1.0:  # ✅ Évite spam UI
                return

        self._last_ui_update[banc_id] = now
        self.ui_updater.update_banc_data(banc_id, data)

    def update_ri_diffusion_widgets(self, banc_id):
        """Met à jour les widgets Ri et Diffusion."""
        self.ui_updater.update_ri_diffusion_widgets(banc_id)

    def update_banc_security(self, banc_id, security_message):
        """Affiche un message de sécurité temporaire."""
        self.ui_updater.update_banc_security(banc_id, security_message)

    def hide_security_display(self, banc_id):
        """Cache le label de sécurité rouge."""
        self.ui_updater.hide_security_display(banc_id)

    def animate_phase_segment(self, banc_id, phase_step):
        """Démarre l'animation de la barre de progression."""
        self.animation_manager.start_phase_animation(banc_id, phase_step)

    def finalize_previous_phase(self, banc_id):
        """Finalise l'animation de la phase précédente."""
        self.animation_manager.finalize_previous_phase(banc_id)

    def update_status_icon(self, banc_id, icon_type, state):
        """Met à jour l'image d'une icône de statut."""
        self.ui_updater.update_status_icon(banc_id, icon_type, state)

    def handle_prompt(self, event=None):
        """Gère l'entrée utilisateur via le gestionnaire de scan."""
        text = self.entry_prompt.get().strip()
        if not text:
            return

        log(f"UI: Prompt reçu: {text}", level="INFO")
        self.entry_prompt.delete(0, tk.END)

        # Déléguer au gestionnaire de scan
        self.scan_manager.process_scan(text)

    def reset_ui_for_banc(self, banc_id):
        """Réinitialise les widgets UI pour un banc spécifique."""
        widgets = self.banc_widgets.get(banc_id)
        if not widgets:
            return

        log(f"UI: Planification Réinitialisation UI pour {banc_id}", level="DEBUG")

        # Planifie l'appel à hide_security_display
        self.after(0, self.hide_security_display, banc_id)

        # Utiliser AnimationManager pour annuler les animations
        self.animation_manager.cancel_all_animations(banc_id)

        # Réinitialisation des barres de progression
        pb_phase = widgets.get("progress_bar_phase")
        if pb_phase and hasattr(pb_phase, 'reset'):
            pb_phase.reset()
            log(f"UI: Barre de progression phase réinitialisée pour {banc_id}.", level="DEBUG")
        elif pb_phase:
            log(f"UI: AVERTISSEMENT - pb_phase pour {banc_id} n'a pas de méthode reset().", level="WARNING")

        # Réinitialisation des labels de données
        if widgets.get("phase"):
            widgets["phase"].configure(text="-")
        if widgets.get("time_left"):
            widgets["time_left"].configure(text="--:--:--")
        if widgets.get("ri"):
            widgets["ri"].configure(text="0.00")
        if widgets.get("diffusion"):
            widgets["diffusion"].configure(text="0.00")

        # Réinitialisation du label titre du banc
        label_banc_widget = widgets.get("banc")
        if label_banc_widget:
            label_banc_widget.configure(text=f"{banc_id.capitalize()} - Libre")
        else:
            log(f"UI: Widget 'banc' (label titre) non trouvé pour {banc_id} lors du reset UI.", level="ERROR")

        # Vider les valeurs internes UI pour ce banc
        widgets["current_step"] = 0
        widgets["serial"] = None

    def _send_expedition_email(self,
                               serial_numbers_expedies,
                               timestamp_expedition_str,
                               retry_attempts=3,
                               delay_between_retries=10):
        """
        Envoie un e-mail récapitulatif des batteries expédiées avec logique de réessai.
        
        Version refactorisée utilisant la configuration et les templates centralisés.
        
        Args:
            serial_numbers_expedies (List[str]): Liste des numéros de série expédiés
            timestamp_expedition_str (str): Timestamp d'expédition au format ISO
            retry_attempts (int): Nombre de tentatives de réessai
            delay_between_retries (int): Délai entre les tentatives en secondes
            
        Returns:
            bool: True si l'envoi a réussi, False sinon
        """
        # Vérification de la configuration email
        if not email_config.is_configured():
            missing_items = email_config.get_missing_config_items()
            log(f"UI: Configuration email incomplète. Éléments manquants: {missing_items}. Envoi de l'email annulé.",
                level="ERROR")
            self.after(
                0, lambda: safe_ui_update(self, None, "Config email manquante", "❌ Le dernier mail n'a pas été envoyé",
                                          "red"))
            return False

        if not serial_numbers_expedies:
            log("UI: Aucune batterie à inclure dans l'email d'expédition.", level="INFO")
            self.after(
                0, lambda: safe_ui_update(self, None, "Aucune batterie à expédier", "ℹ️ Aucun email nécessaire",
                                          "#808080"))
            return True

        # Génération du contenu via les templates
        try:
            subject = EmailTemplates.generate_expedition_subject(timestamp_expedition_str)
            text_content, html_content = EmailTemplates.generate_expedition_email_content(
                serial_numbers_expedies, timestamp_expedition_str)
        except Exception as template_error:
            log(f"UI: Erreur lors de la génération du template email: {template_error}", level="ERROR")
            self.after(
                0, lambda: safe_ui_update(self, None, "Erreur template", "❌ Le dernier mail n'a pas été envoyé", "red"))
            return False

        # Création du message MIME
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = email_config.gmail_user
        message["To"] = ", ".join(email_config.recipient_emails)

        # Ajout des parties texte et HTML
        part_text = MIMEText(text_content, "plain")
        part_html = MIMEText(html_content, "html")
        message.attach(part_text)
        message.attach(part_html)
        # Indication du début de l'envoi
        self.after(0, lambda: safe_ui_update(self, None, None, "📧 Envoi email...", "#FFA500"))

        # Tentatives d'envoi avec logique de réessai
        for attempt in range(retry_attempts):
            try:
                log(f"UI: Tentative d'envoi de l'email d'expédition à {', '.join(email_config.recipient_emails)} (Tentative {attempt + 1}/{retry_attempts})...",
                    level="INFO")
                # Mise à jour du statut pour les tentatives multiples
                if attempt > 0:
                    self.after(
                        0,
                        lambda a=attempt: safe_ui_update(self, None, None, f"📧 Tentative {a + 1}/{retry_attempts}...",
                                                         "#FFA500"))
                # Connexion et envoi
                server = smtplib.SMTP_SSL(email_config.smtp_server, email_config.smtp_port)
                server.ehlo()
                server.login(email_config.gmail_user, email_config.gmail_password)
                server.sendmail(email_config.gmail_user, email_config.recipient_emails, message.as_string())
                server.close()

                log(f"UI: Email d'expédition envoyé avec succès à {', '.join(email_config.recipient_emails)} !",
                    level="INFO")
                self.after(
                    0,
                    lambda count=len(serial_numbers_expedies): safe_ui_update(
                        self, None, f"Email envoyé ({count} batteries)", "✅ Email envoyé", "green"))
                return True

            except smtplib.SMTPAuthenticationError:
                log(f"UI: Erreur d'authentification SMTP pour Gmail (Tentative {attempt + 1}/{retry_attempts}). Vérifiez la configuration email.",
                    level="ERROR")
                self.after(
                    0, lambda: safe_ui_update(self, None, "Erreur auth email", "❌ Le dernier mail n'a pas été envoyé",
                                              "red"))
                return False

            except (socket.gaierror, OSError) as e:
                log(f"UI: ERREUR RÉSEAU lors de la connexion SMTP (Tentative {attempt + 1}/{retry_attempts}) : {e}. Vérifiez la connexion internet et le DNS.",
                    level="ERROR")
                if attempt < retry_attempts - 1:
                    log(f"UI: Réessai de l'envoi de l'email dans {delay_between_retries} secondes...", level="INFO")
                    self.after(
                        0,
                        lambda a=attempt, r=retry_attempts: safe_ui_update(self, None, "Erreur réseau/DNS",
                                                                           f"⚠️ Réseau {a + 1}/{r}", "orange"))
                    time.sleep(delay_between_retries)
                else:
                    log(f"UI: Échec de l'envoi de l'email après {retry_attempts} tentatives pour cause d'erreur réseau/DNS.",
                        level="ERROR")
                    self.after(
                        0, lambda: safe_ui_update(self, None, "Erreur réseau finale",
                                                  "❌ Le dernier mail n'a pas été envoyé", "red"))
                    return False

            except Exception as e:
                log(f"UI: Erreur inattendue lors de l'envoi de l'email d'expédition (Tentative {attempt + 1}/{retry_attempts}) : {e}",
                    level="ERROR")
                self.after(
                    0, lambda: safe_ui_update(self, None, "Erreur réseau/DNS", "❌ Le dernier mail n'a pas été envoyé",
                                              "red"))
                return False
        self.after(
            0, lambda: safe_ui_update(self, None, "❌ Email échec final", "❌ Le dernier mail n'a pas été envoyé", "red"))
        return False


def on_connect(client, userdata, flags, rc):
    """
    Callback exécuté lors de la connexion (ou reconnexion) au broker MQTT.
    S'abonne aux topics nécessaires pour tous les bancs.
    Met à jour les labels UI si succès.
    """
    log(f"UI: Connecté avec le code {str(rc)} ", level="INFO")
    if rc == mqtt.MQTT_ERR_SUCCESS:
        log(f"UI: Connexion MQTT réussie. Tentative d'abonnements...", level="INFO")
        if userdata is None:
            log("UI: Erreur critique - userdata est None dans on_connect.", level="WARNING")
            return
        app = userdata.get("app")
        if app is None:
            log("UI: Erreur critique - 'app' non trouvé dans userdata.", level="WARNING")
            return

        all_subscriptions_successful = True
        for i in range(1, NUM_BANCS + 1):
            banc_id_str = f"banc{i}"
            topics_to_subscribe = [(f"{banc_id_str}/step", 0), (f"{banc_id_str}/bms/data", 0),
                                   (f"{banc_id_str}/security", 0), (f"{banc_id_str}/ri/results", 0),
                                   (f"{banc_id_str}/state", 0)]
            try:
                result, mid = client.subscribe(topics_to_subscribe)
                if result != mqtt.MQTT_ERR_SUCCESS:
                    all_subscriptions_successful = False
                    log(f"UI: ERREUR abonnement {banc_id_str}. Code: {result}", level="ERROR")
            except Exception as sub_e:
                log(f"UI: Exception abonnement {banc_id_str}: {sub_e}", level="ERROR")
                all_subscriptions_successful = False

        if all_subscriptions_successful:
            log(f"UI: Abonnements MQTT terminés.", level="INFO")
            msg1 = "Système Prêt."
            msg2 = "Veuillez scanner pour commencer..."
            app.after(0, lambda: safe_ui_update(app, msg1, msg2, "✅ Système OK", "green"))
        else:
            log(f"UI: Échec d'au moins un abonnement MQTT.", level="ERROR")
            msg1 = "Erreur MQTT"
            msg2 = "Échec abonnements. Vérifier logs."
            app.after(0, lambda: safe_ui_update(app, msg1, msg2, "❌ Erreur MQTT", "red"))
    else:
        log(f"UI: Connexion MQTT échouée (Code: {rc}).", level="WARNING")
        msg1 = "Erreur Connexion MQTT"
        msg2 = f"Code: {rc}. Vérifier broker/réseau."
        if userdata and "app" in userdata and userdata["app"]:
            app = userdata["app"]
            app.after(0, lambda: safe_ui_update(app, msg1, msg2, "⚠️ Connexion échouée", "orange"))


@staticmethod
def on_message(client, userdata, msg):
    """
    Callback exécuté à la réception d'un message sur un topic MQTT souscrit.
    Utilise les handlers du module ui.message_handlers pour traiter les messages.
    """
    topic = msg.topic.rstrip("/")

    if not userdata or "app" not in userdata:
        log("UI: Erreur critique - userdata invalide dans on_message", level="ERROR")
        return
    app = userdata["app"]

    try:
        payload_str = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        log(f"UI: Erreur décodage payload (non-UTF8?) pour topic {topic}", level="WARNING")
        return

    # Extraction du banc_id et du topic suffix
    topic_parts = topic.split("/")
    if len(topic_parts) < 2:
        log(f"UI: Topic invalide reçu: {topic}", level="ERROR")
        return

    banc_id = topic_parts[0]
    topic_suffix = '/'.join(topic_parts[1:])

    if not banc_id.startswith("banc") or banc_id not in app.banc_widgets:
        log(f"UI: Message reçu pour banc inconnu ou non géré par l'UI: {topic}", level="ERROR")
        return

    # Récupération des handlers et traitement du message
    handlers = get_ui_message_handlers()
    handler = handlers.get(topic_suffix)

    if handler:
        try:
            handler(payload_str, banc_id, app)
        except Exception as e:
            log(f"UI: Erreur dans le handler pour {topic}: {e}", level="ERROR")
    else:
        log(f"UI: Topic non reconnu ou non géré: {topic}", level="WARNING")


def safe_ui_update(app_instance, msg1, msg2, msg_system=None, color_system=None):
    """
    Met à jour les labels de réponse de l'UI via app.after pour thread-safety.
    
    Args:
        app_instance: Instance de l'application
        msg1: Message pour label_response1 (None = pas de mise à jour)
        msg2: Message pour label_response2 (None = pas de mise à jour)  
        msg_system: Message pour system_status_label (None = pas de mise à jour)
        color_system: Couleur pour system_status_label (optionnel)
    """
    if not app_instance:
        return

    try:
        # Mise à jour msg1 si fourni
        if msg1 is not None and hasattr(app_instance, 'label_response1') and app_instance.label_response1:
            app_instance.label_response1.configure(text=msg1)

        # Mise à jour msg2 si fourni
        if msg2 is not None and hasattr(app_instance, 'label_response2') and app_instance.label_response2:
            app_instance.label_response2.configure(text=msg2)

        # Mise à jour msg_system si fourni
        if msg_system is not None and hasattr(app_instance, 'system_status_label') and app_instance.system_status_label:
            kwargs = {"text": msg_system}
            if color_system:
                kwargs["text_color"] = color_system
            app_instance.system_status_label.configure(**kwargs)

    except Exception as ui_e:
        log(f"UI: Erreur interne lors de la mise à jour UI via 'after': {ui_e}", level="WARNING")


def mqtt_thread(app_instance):
    """
    Fonction exécutée dans un thread séparé pour gérer la boucle MQTT.
    Se connecte au broker, reste en écoute, et gère la reconnexion automatique.
    """
    try:
        ui_client_id = f"ui_client_{os.getpid()}"
        client = mqtt.Client(
            client_id=ui_client_id,
            userdata={"app": app_instance},
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1)  # type: ignore
        app_instance.mqtt_client = client
        client.on_connect = on_connect
        client.on_message = on_message

        def on_disconnect(client, userdata, rc):
            log(f"UI: Déconnecté du broker MQTT avec le code {rc}.", level="WARNING")
            if userdata and "app" in userdata:
                app = userdata["app"]
                if app:
                    app.mqtt_client = None
                    msg1 = "MQTT Déconnecté"
                    msg2 = "Tentative de reconnexion..."
                    app.after(0, lambda: safe_ui_update(app, msg1, msg2, "❌ MQTT Déconnecté", "red"))

        client.on_disconnect = on_disconnect
    except Exception as client_e:
        log(f"UI: Erreur critique lors de la création du client MQTT: {client_e}", level="ERROR")
        app_instance.after(0,
                           lambda: safe_ui_update(app_instance, "Erreur Init MQTT", "Impossible de créer le client."))
        return

    while True:
        try:
            log("UI: Tentative de connexion au broker MQTT...", level="INFO")
            app_instance.after(0, lambda: safe_ui_update(app_instance, None, None, "🔄 Connexion...", "#FFA500"))
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            app_instance.mqtt_client = client
            log("UI: Connexion MQTT établie. Démarrage boucle de réception.", level="INFO")
            client.loop_forever()
            log("UI: Boucle MQTT terminée normalement.", level="INFO")
            break
        except (socket.timeout, TimeoutError, ConnectionRefusedError, socket.gaierror, OSError) as conn_e:
            log(f"UI: Erreur de connexion/réseau MQTT: {conn_e}", level="WARNING")
            msg1 = "Erreur Réseau MQTT"
            msg2 = f"Vérifier broker ({MQTT_BROKER}:{MQTT_PORT}) et réseau."
            app_instance.after(0, lambda: safe_ui_update(app_instance, msg1, msg2, "❌ Erreur réseau", "red"))
        except Exception as e:
            log(f"UI: Erreur inattendue dans la boucle MQTT: {e}", level="WARNING")
            msg1 = "Erreur MQTT"
            msg2 = "Erreur interne. Tentative de reconnexion."
            app_instance.after(0, lambda: safe_ui_update(app_instance, msg1, msg2, "⚠️ Erreur interne", "orange"))

        log(f"UI: Prochaine tentative de connexion MQTT dans 5 secondes...", level="INFO")
        time.sleep(5)
    log("UI: Sortie définitive du thread MQTT (ne devrait arriver que si 'break' est appelé).", level="INFO")


def run_ui():
    """
    Point d'entrée principal de l'application UI.
    Initialise l'instance de l'application `App`, démarre le thread
    dédié à la communication MQTT en arrière-plan, puis lance la
    boucle principale de l'interface graphique Tkinter.
    """
    try:
        app = App()
    except Exception as e:
        log(f"UI: Erreur critique lors de l'initialisation de App(): {e}", level="WARNING")
        print(f"Erreur critique UI: {e}")
        return

    try:
        mqtt_thread_instance = threading.Thread(target=mqtt_thread, args=(app, ), daemon=True)
        mqtt_thread_instance.start()
    except Exception as e:
        log(f"UI: Erreur critique lors du démarrage du thread MQTT: {e}", level="WARNING")
        try:
            app.label_response1.configure(text="Erreur Critique")
            app.label_response2.configure(text="Impossible de démarrer le service MQTT.")
        except Exception as ui_e:
            log(f"UI: Impossible d'afficher l'erreur de démarrage MQTT dans l'UI: {ui_e}", level="WARNING")

    log("UI: Démarrage de la boucle principale Tkinter (mainloop).", level="INFO")
    app.mainloop()
    log("UI: Application terminée.", level="INFO")


# Point d'entrée principal du script
if __name__ == "__main__":
    run_ui()
