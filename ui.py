#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tkinter as tk
from PIL import Image
import customtkinter as ctk
import json, os, time
import paho.mqtt.client as mqtt
import threading
import socket
from src.ui.scan import ScanManager
from src.ui.utils import (
    load_bancs_config,
    get_charge_duration,
    log,
    MQTT_BROKER,
    MQTT_PORT,
    get_temperature_coefficient,
    NUM_BANCS,
)
from src.ui.ui_components import (update_soc_canvas, create_block_labels, get_phase_message, _get_balance_color,
                                  _get_temp_color, _get_capacity_color, _get_energy_color)
from src.ui.email import EmailTemplates, email_config
from src.ui import get_ui_message_handlers
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ctk.set_appearance_mode("dark")


# --- FENETRE PRINCIPALE ---
class App(ctk.CTk):
    BANC_STATUS_AVAILABLE = "available"
    BANC_STATUS_OCCUPIED = "occupied"
    MIN_EXPECTED_BMS_FIELDS = 10
    SECURITY_DISPLAY_DURATION_MS = 5000
    PHASE4_NURSE_HIGH_SOC_THRESHOLD = 85.0  # Utilisé pour calculer la durée phase 4
    PHASE4_NURSE_LOW_SOC_TARGET = 80.0
    PHASE4_NURSE_HIGH_FACTOR_MIN_PER_PCT = 2.88
    PHASE4_MAIN_BATT_LOW_SOC_REF = 10.0
    PHASE4_MAIN_BATT_LOW_FACTOR_MIN_PER_UNIT = 1.3
    SECONDS_PER_MINUTE = 60
    PHASE4_MIN_DURATION_S = 5
    PHASE1_RI_DURATION_S = 200
    PHASE3_CAPA_FACTOR_MIN_PER_SOC_PCT = 1.35  # # Utilisé pour calculer la durée phase 3
    DEFAULT_DURATION_S = 10000  # Si un calcule de phase echoue
    ANIMATION_INTERVAL_MS = 1000  # interval entre les maj d'animation progress bar
    LARGE_BORDER_WIDTH_ACTIVE = 50  # step 5 / security
    NORMAL_BORDER_WIDTH = 1
    SCAN_CONFIRM_TIMEOUT_S = 15
    SERIAL_PATTERN = r"RW-48v271[A-Za-z0-9]{4}"
    NURSE_LOW_SOC_THRESHOLD_RATIO = 0.3  # Ratio (0 à 1) du SOC total nourrices

    def __init__(self):
        """
        Initialise l'application principale.
        Configure la fenetre, charge la config et crée les widgets pour chaque banc.
        initialise leur état visuel et met en place la zone de scan.
        """
        super().__init__()
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
        bancs = config.get("bancs", [])  # Création des 6 blocs bancs.

        if len(bancs) < NUM_BANCS:
            raise ValueError(f"La configuration doit contenir au moins {NUM_BANCS} bancs.")

        self.banc_widgets = {}  # Labels dynamiques de chaque banc.
        for i in range(NUM_BANCS):
            banc_id = f"banc{i+1}"  # ID du banc actuel (ex: "banc1", "banc2").
            try:
                # Calcule la position sur la grille (2 lignes, 3 colonnes).
                row = 0 if i < NUM_BANCS // 2 else 1
                col = i % (NUM_BANCS // 2)  # Utilisation de modulo pour la colonne
                frame = ctk.CTkFrame(self, corner_radius=10)  # Conteneur pour tous les widgets de ce banc
                frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
                banc_config_data = bancs[i]  # Récupère les données de config pour ce banc depuis la liste 'bancs'
                banc_text = f"{banc_config_data.get('name', banc_id)}".strip(" -")
                serial_text_init = banc_config_data.get('serial-pending') or ""  # Get le serial si existe
                current_step_init = banc_config_data.get("current_step")  # Get step sinon None (0/5)

                # --- CREATION DES WIDGETS ---
                widgets_for_banc = create_block_labels(
                    frame,
                    banc_text=banc_text,
                    serial_text=serial_text_init,
                    current_step=current_step_init,
                    icons=self.status_icons)
                self.banc_widgets[banc_id] = widgets_for_banc  # Ajoute les widgets au dictionnaire
                log(f"UI: Interface pour {banc_id} créée avec succès.", level="INFO")

            except Exception as e:
                log(f"UI: ERREUR CRITIQUE lors de l'initialisation de l'interface pour {banc_id}: {e}", level="ERROR")
                pass  # Important pour ne pas planter l'application si un seul banc échoue.

        # === INITIALISATION DE L'ÉTAT DES BANCS ===
        self.init_banc_status(config)  # Initialise l'affichage "Libre" ou le serial du test en cours.
        self.mqtt_client = None  # Initialisation du client MQTT

        # === CRÉATION DE LA ZONE DE SCAN ===
        self.frame_scan = ctk.CTkFrame(self, corner_radius=10)
        self.frame_scan.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        self.label_response1 = ctk.CTkLabel(self.frame_scan, text="- ", font=("Helvetica", 16, "bold"))
        self.label_response1.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        self.label_response2 = ctk.CTkLabel(self.frame_scan, text="- ", font=("Helvetica", 16, "bold"))
        self.label_response2.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.entry_prompt = ctk.CTkEntry(self.frame_scan, placeholder_text="Saisissez ici", font=("Helvetica", 16))
        self.entry_prompt.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.frame_scan.columnconfigure(0, weight=1)

        # === VARIABLES D'ÉTAT DE L'INTERFACE ===
        self.security_active = {f"banc{i+1}": False for i in range(NUM_BANCS)}
        self.active_phase_timers = {}  # Stockage des timers d'animation de phase.
        self.reset_enabled_for_banc = {f"banc{i+1}": False for i in range(NUM_BANCS)}
        self._security_timers = {}

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
                banc_data = bancs[i]  # Récupère le statut pour ce banc.
                status = banc_data.get("status", self.BANC_STATUS_AVAILABLE)
                if status == self.BANC_STATUS_AVAILABLE:
                    widgets["banc"].configure(text=f"{bancs[i]['name']} - Libre")
                elif status == self.BANC_STATUS_OCCUPIED:
                    serial = bancs[i].get("serial-pending", "")
                    starting_phase_raw = banc_data.get("current_step")
                    if isinstance(starting_phase_raw, int):  # Vérifie si la valeur récupérée est bien un entier.
                        starting_phase = starting_phase_raw  # Utilise cette valeur comme étape de départ.
                    else:
                        if starting_phase_raw is not None:
                            log(f"UI init: 'current_step' invalide ({type(starting_phase_raw)}) pour {banc_id}. Utilisation de 0.",
                                level="WARNING")
                        starting_phase = 0  # Valeur par défaut sécurisée.

                    widgets["current_step"] = starting_phase
                    widgets["banc"].configure(text=f"{bancs[i]['name']} - {serial}")
                    progress_bar = widgets.get("progress_bar_phase")  # Pré-remplissage de la barre de progression

                    if progress_bar:
                        if starting_phase >= 2:
                            progress_bar.progress_ri.set(1.0)  # R.I. est complétée.
                        if starting_phase >= 3:  # Charge est complétée.
                            progress_bar.progress_phase2.set(1.0)
                        if starting_phase >= 4:  # Decharge est complétée.
                            progress_bar.progress_capa.set(1.0)

                else:  # Configure le label principal pour afficher un message d'erreur.
                    log(f"Statut inconnu '{status}' pour {banc_id} dans la config.", level="WARNING")
                    widgets["banc"].configure(text=f"{banc_data['name']} - Statut Inconnu")

    def update_banc_data(self, banc_id, data):
        """
        Met à jour les widgets d'un banc avec les données BMS reçues via MQTT.
        """
        if not isinstance(data, list) or len(data) < self.MIN_EXPECTED_BMS_FIELDS:  # min 10
            log(f"UI: Données BMS invalides ou incomplètes reçues pour {banc_id}. Attendu: liste d'au moins {self.MIN_EXPECTED_BMS_FIELDS} éléments, Reçu type: {type(data)}, len: {len(data) if isinstance(data, list) else 'N/A'}. Data: {data}",
                level="WARNING")
            return

        try:
            # --- EXTRACTION DATA BMS ---
            voltage = float(data[0])
            current = float(data[1])
            soc_raw = data[2]
            temperature = float(data[3])
            maxCellV = int(data[5])
            minCellV = int(data[7])
            discharge_capacity = float(data[8]) / 1000
            discharge_energy = float(data[9]) / 1000
            balance = maxCellV - minCellV  # Calcul de l'équilibrage.
            INDEX_AVG_NURSE_SOC = 10 + 15 + 1  # DATA BMS + DATA CELLS + HeartBeat : Soit 26
            average_nurse_soc_str = data[INDEX_AVG_NURSE_SOC]
            average_nurse_soc_value = float(average_nurse_soc_str)  # pourcentage (0-100)
        except (IndexError, ValueError, TypeError) as e:
            log(f"UI: Erreur lors de l'analyse/conversion des données CSV pour {banc_id}: {e}. Data: {data}",
                level="WARNING")
            return

        # --- MISE à JOUR DES LABELS DYNAMIQUES ---
        widgets = self.banc_widgets.get(banc_id)
        if widgets:
            widgets["tension"].configure(text=f"{voltage:.1f}")  # 1 decimale.
            widgets["intensity"].configure(text=f"{current:.1f}")
            widgets["temp"].configure(text=f"{temperature:.1f}")
            widgets["discharge_capacity"].configure(text=f"{discharge_capacity:.1f}")
            widgets["discharge_energy"].configure(text=f"{discharge_energy:.1f}")
            widgets["balance"].configure(text=f"{balance:.0f}")  # entier
            current_step = widgets.get("current_step", 0)
            if current_step in [1, 2, 3, 4, 5]:
                widgets["phase"].configure(text=get_phase_message(current_step))

            # --- MISE à JOUR DES COULEURS CONDITIONNELLES ---
            widgets["temp"].configure(text_color=_get_temp_color(temperature))
            widgets["balance"].configure(text_color=_get_balance_color(balance))
            widgets["discharge_energy"].configure(text_color=_get_energy_color(discharge_energy, current_step))
            widgets["discharge_capacity"].configure(text_color=_get_capacity_color(discharge_capacity, current_step))
            # Mise à jour visuelle si test terminé (step 5).
            parent_frame = widgets.get("parent_frame")
            if parent_frame:
                # Si un message de sécurité est actif pour ce banc, on ne change pas la bordure (qui est déjà rouge).
                if self.security_active.get(banc_id, False):
                    pass
                elif current_step == 5:  # (test terminé avec succès).
                    parent_frame.configure(border_color="#6EC207", border_width=self.LARGE_BORDER_WIDTH_ACTIVE)
                else:
                    parent_frame.configure(border_color="white", border_width=self.NORMAL_BORDER_WIDTH)

            # --- MISE à JOUR DU CANVAS SOC ---
            soc_raw = data[2]
            soc_canvas = widgets.get("soc_canvas")
            if soc_canvas:
                try:  # Tente de convertir la valeur brute du SOC (chaîne) en nombre flottant.
                    soc_value = float(soc_raw)
                except (ValueError, TypeError):
                    log(f"UI: SOC invalide reçu pour {banc_id}, fallback à 0% : {soc_raw}", level="WARNING")
                    soc_value = 0.0  # valeur par défaut.
                widgets["last_soc"] = soc_value  # Stocke le dernier SOC connu.
                update_soc_canvas(soc_canvas, soc_value)

            # --- MISE à JOUR DU CANVAS NURSE SOC ---
            progress_bar_nurse = widgets.get("progress_bar_nurse")
            if progress_bar_nurse:
                # average_nurse_soc_value est un pourcentage (ex: 85.0 pour 85%)
                # progress_bar_nurse.set() attend une valeur entre 0.0 et 1.0
                progress_ratio_nurse = min(max(average_nurse_soc_value / 100.0, 0.0), 1.0)
                progress_bar_nurse.set(progress_ratio_nurse)
                low_color = "red"
                normal_color = "#6EC207"
                threshold_ratio = getattr(self, 'NURSE_LOW_SOC_THRESHOLD_RATIO', 0.5)
                is_low = progress_ratio_nurse < threshold_ratio
                final_color_nurse = low_color if is_low else normal_color
                progress_bar_nurse.configure(progress_color=final_color_nurse)
                widgets["last_avg_nurse_soc"] = average_nurse_soc_value

    def update_ri_diffusion_widgets(self, banc_id):
        """
        Lit le fichier config.json de la batterie et met à jour les widgets Ri et Diffusion.
        """
        log(f"UI: Tentative de mise à jour Ri/Diffusion pour {banc_id}", level="DEBUG")
        widgets = self.banc_widgets.get(banc_id)
        if not widgets:
            log(f"UI: Widgets non trouvés pour {banc_id}", level="ERROR")
            return

        # --- RECUPERATION DU CHEMIN Du DOSSIER  ---
        battery_folder = widgets.get("battery_folder_path")
        if not battery_folder:
            log(f"UI: Chemin 'battery_folder_path' non trouvé dans les widgets pour {banc_id}. Impossible de lire config.json.",
                level="ERROR")
            widgets["ri"].configure(text="N/A")
            widgets["diffusion"].configure(text="N/A")
            return

        # --- LECTURE DU FICHIER CONFIG.JSON ---
        config_path = os.path.join(battery_folder, "config.json")
        log(f"UI: Chemin config.json: {config_path}", level="DEBUG")
        try:
            with open(config_path, "r") as f:  # Lecture du fichier config.json.
                config_data = json.load(f)
            if not isinstance(config_data, dict):  # Vérification du type.
                log(f"UI: Le contenu de {config_path} n'est pas un dictionnaire attendu. Reçu: {type(config_data)}",
                    level="ERROR")
                widgets["ri"].configure(text="N/A")
                widgets["diffusion"].configure(text="N/A")
                return

            # --- MISE à JOUR DES WIDGETS ---
            ri_discharge = config_data.get("ri_discharge_average", 0.0)
            ri_charge = config_data.get("ri_charge_average", 0.0)
            diffusion_discharge = config_data.get("diffusion_discharge_average", 0.0)
            diffusion_charge = config_data.get("diffusion_charge_average", 0.0)
            # Vérification explicite que les valeurs sont numériques.
            values_to_check = [ri_discharge, ri_charge, diffusion_discharge, diffusion_charge]
            if not all(isinstance(v, (int, float)) for v in values_to_check):
                log(f"UI: Certaines valeurs Ri/Diffusion ne sont pas numériques dans {config_path}. Données: {config_data}",
                    level="WARNING")
                # On met à 0 les valeurs non numériques pour éviter des erreurs de calcul.
                ri_discharge = ri_discharge if isinstance(ri_discharge, (int, float)) else 0.0
                ri_charge = ri_charge if isinstance(ri_charge, (int, float)) else 0.0
                diffusion_discharge = diffusion_discharge if isinstance(diffusion_discharge, (int, float)) else 0.0
                diffusion_charge = diffusion_charge if isinstance(diffusion_charge, (int, float)) else 0.0

            # --- CALCUL DES MOYENNES Ri et Diffusion ---
            # Calculer la moyenne Ri (charge et décharge combinées).
            ri_sum = ri_charge + ri_discharge
            # Compte combien de valeurs Ri sont non nulles (pour éviter division par zéro si les deux sont 0).
            ri_count = (1 if ri_charge != 0.0 else 0) + (1 if ri_discharge != 0.0 else 0)
            # Calcule la moyenne Ri. Si ri_count est 0, la moyenne est 0.
            ri_avg = ri_sum / ri_count if ri_count > 0 else 0.0
            # Calculer la moyenne Diffusion (charge et décharge combinées).
            diffusion_sum = diffusion_charge + diffusion_discharge
            diffusion_count = (1 if diffusion_charge != 0.0 else 0) + (1 if diffusion_discharge != 0.0 else 0)
            diffusion_avg = diffusion_sum / diffusion_count if diffusion_count > 0 else 0.0
            # Récupère la température actuelle affichée dans le widget "temp".
            temp_widget = widgets.get("temp")
            if temp_widget:
                temp_str = temp_widget.cget("text").replace(",", ".")
            try:
                temperature = float(temp_str)
            except ValueError:
                log(f"UI: Impossible de lire la température depuis le widget pour {banc_id}. Utilisation de 25°C par défaut.",
                    level="WARNING")
                temperature = 25.0  # Valeur par défaut.
            # Appliquer le coefficient de température à la diffusion.
            coefficient_temp = get_temperature_coefficient(temperature)
            # Applique le coefficient à la moyenne de diffusion calculée.
            diffusion_avg_corrected = diffusion_avg * coefficient_temp
            # Mise à jour des widgets Ri et Diffusion.
            ri_widget = widgets.get("ri")
            diffusion_widget = widgets.get("diffusion")
            if ri_widget:
                ri_widget.configure(text=f"{ri_avg * 1000:.2f}")
            if diffusion_widget:
                diffusion_widget.configure(text=f"{diffusion_avg_corrected * 1000:.2f}")
            log(f"UI: Widgets Ri/Diffusion mis à jour pour {banc_id}: Ri={ri_avg*1000:.2f} mΩ, Diff={diffusion_avg_corrected*1000:.2f} mΩ",
                level="INFO")
        except FileNotFoundError:
            log(f"UI: Fichier config.json non trouvé pour {banc_id} à l'emplacement: {config_path}", level="ERROR")
            if widgets.get("ri"): widgets["ri"].configure(text="N/A")
            if widgets.get("diffusion"):
                widgets["diffusion"].configure(text="N/A")
        except json.JSONDecodeError:
            log(f"UI: Erreur de décodage JSON dans {config_path} pour {banc_id}.", level="ERROR")
            if widgets.get("ri"): widgets["ri"].configure(text="N/A")
            if widgets.get("diffusion"):
                widgets["diffusion"].configure(text="N/A")
        except Exception as e:
            log(f"UI: ERREUR INATTENDUE pendant MAJ Ri/Diff pour {banc_id}: {e}", level="ERROR")
            if widgets.get("ri"): widgets["ri"].configure(text="ERR")
            if widgets.get("diffusion"):
                widgets["diffusion"].configure(text="ERR")

    def update_banc_security(self, banc_id, security_message):
        """
        Affiche un message de sécurité temporaire sur le banc spécifié.
        """
        # --- RÉCUPERATION DES WIDGETS ---
        widgets = self.banc_widgets.get(banc_id)
        if not widgets:
            return
        # Récupère la référence au label de sécurité et au cadre parent depuis les widgets.
        label_info = widgets.get("label_security")  # Label rouge.
        parent_frame = widgets.get("parent_frame")  # Cadre du banc.
        # Annulation du timer précédent (si un message arrive avant la fin du précédent).
        previous_timer_id = getattr(self, '_security_timers', {}).pop(banc_id, None)
        if previous_timer_id:
            try:
                self.after_cancel(previous_timer_id)
                log(f"UI: Timer sécurité précédent annulé pour {banc_id}", level="DEBUG")
            except ValueError:
                log(f"UI: Tentative d'annulation d'un timer sécurité déjà expiré/invalide pour {banc_id}",
                    level="WARNING")

        # --- AFFICHAGE DU MESSAGE DE SECURITE ---
        self.security_active[banc_id] = True
        if label_info:
            label_info.configure(
                text=security_message, text_color="white", fg_color="red", font=("Helvetica", 40, "bold"))
            label_info.place(relx=0.5, rely=0.5, anchor="center")
            label_info.lift()  # Met au premier plan.
        else:
            log(f"UI: Widget 'label_security' non trouvé pour {banc_id}", level="WARNING")
        if parent_frame:  # surligne le cadre du banc en rouge.
            parent_frame.configure(border_color="red", border_width=self.LARGE_BORDER_WIDTH_ACTIVE)
        else:
            log(f"UI: Widget 'parent_frame' non trouvé pour {banc_id}", level="WARNING")
        # Cache le message de sécurité après un certain temps.
        new_timer_id = self.after(
            self.SECURITY_DISPLAY_DURATION_MS, lambda bid=banc_id: self.hide_security_display(bid))
        self._security_timers[banc_id] = new_timer_id  # # Stocke l'ID du nouveau timer

    def hide_security_display(self, banc_id):
        """Cache le label de sécurité rouge et réinitialise la bordure."""
        widgets = self.banc_widgets.get(banc_id)
        if not widgets: return
        label_security = widgets.get("label_security")
        parent_frame = widgets.get("parent_frame")
        self.security_active[banc_id] = False
        if label_security:
            label_security.lower()  # Cache le label rouge.
        if parent_frame:
            current_step = widgets.get("current_step", 0)
            if current_step == 5:  # Test terminé -> vert
                parent_frame.configure(border_color="#6EC207", border_width=self.LARGE_BORDER_WIDTH_ACTIVE)
            else:  # Autres cas -> blanc normal
                parent_frame.configure(border_color="white", border_width=self.NORMAL_BORDER_WIDTH)
        # Nettoyer la référence au timer s'il en existait une (sécurité).
        if hasattr(self, '_security_timers'):
            timer_id_to_clear = self._security_timers.pop(banc_id, None)
            if timer_id_to_clear:
                # Essayer d'annuler au cas où cette fonction serait appelée avant l'expiration du timer.
                try:
                    self.after_cancel(timer_id_to_clear)
                except ValueError:
                    pass
        log(f"UI: Affichage sécurité masqué pour {banc_id} (appel manuel/externe)", level="DEBUG")

    def animate_phase_segment(self, banc_id, phase_step):
        """
        Démarre l'animation de la barre de progression et du temps restant pour une phase donnée.
        Calcule la durée estimée de la phase et met à jour la barre de progression
        et le label de temps restant chaque seconde.
        """
        try:
            # --- INITIALISATION ET VALIDATION DES WIDGETS ---
            widgets = self.banc_widgets.get(banc_id)
            if not widgets:
                log(f"UI: Widgets non trouvés pour {banc_id} dans animate_phase_segment.", level="ERROR")
                return
            # Récupère la référence à l'objet MultiColorProgress.
            phase_bar = widgets.get("progress_bar_phase")
            label_time_left = widgets.get("time_left")
            if not phase_bar or not label_time_left:
                log(f"UI: Widgets de progression/temps manquants pour {banc_id}.", level="ERROR")
                return
            log(f"UI: Démarrage/Mise à jour animation phase {phase_step} pour {banc_id}", level="INFO")
            self.finalize_previous_phase(banc_id)  # Finalise l'animation de la phase precedente
            self.active_phase_timers[banc_id] = {"phase": phase_step, "cancel": False}

            # --- SELECTION DE LA BARRE DE PROGRESSION CIBLE ---
            target_bar = None  # Initialisation.
            if phase_step == 1:  # (RI).
                target_bar = phase_bar.progress_ri
            elif phase_step == 2:  # (Charge).
                target_bar = phase_bar.progress_phase2
            elif phase_step == 3:  # (Capacité).
                target_bar = phase_bar.progress_capa
            elif phase_step == 4:  # (Charge finale).
                target_bar = phase_bar.progress_charge
            else:  # Si phase_step n'est pas 1, 2, 3 ou 4.
                log(f"UI: Phase invalide {phase_step} pour animation sur {banc_id}", level="WARNING")
                return

            # --- CALCUL DE LA DUREE ESTIMEE DE LA PHASE ---
            voltage_str = widgets["tension"].cget("text").replace(",", ".")
            # Récupère la dernière valeur SOC connue pour la batterie de ce banc (stockée par update_banc_data). Défaut 0.0.
            soc_batterie_test = widgets.get("last_soc", 0.0)
            # Calcule le SOC moyen des nourrices pour ce banc.
            soc_nourrice_moyen = widgets.get("last_avg_nurse_soc", 0.0)
            duration = 0
            try:
                # Calcul de la durée estimée.
                if phase_step == 4:
                    duration_minutes = 0
                    # CAS 1: Nourrices SOC >= 85%.
                    if soc_nourrice_moyen >= self.PHASE4_NURSE_HIGH_SOC_THRESHOLD:
                        soc_drop_needed = soc_nourrice_moyen - self.PHASE4_NURSE_LOW_SOC_TARGET
                        duration_minutes = soc_drop_needed * self.PHASE4_NURSE_HIGH_FACTOR_MIN_PER_PCT
                        log(f"UI: Phase 4 ({banc_id}), calcul durée (nourrices >= {self.PHASE4_NURSE_HIGH_SOC_THRESHOLD}%): ({soc_nourrice_moyen:.1f} - {self.PHASE4_NURSE_LOW_SOC_TARGET}) * {self.PHASE4_NURSE_HIGH_FACTOR_MIN_PER_PCT} = {duration_minutes:.1f} min",
                            level="DEBUG")
                    else:  # CAS 2: Nourrices SOC < 85%.
                        # !!! ATTENTION : Formule des notes (10 - socBatterieTest) * 1.3 !!! vvv
                        duration_minutes = (self.PHASE4_MAIN_BATT_LOW_SOC_REF -
                                            soc_batterie_test) * self.PHASE4_MAIN_BATT_LOW_FACTOR_MIN_PER_UNIT
                        log(f"UI: Phase 4 ({banc_id}), calcul durée (nourrices < {self.PHASE4_NURSE_HIGH_SOC_THRESHOLD}%): ({self.PHASE4_MAIN_BATT_LOW_SOC_REF} - {soc_batterie_test:.1f}) * {self.PHASE4_MAIN_BATT_LOW_FACTOR_MIN_PER_UNIT} = {duration_minutes:.1f} min",
                            level="WARNING")
                        # Vérifie si le calcul a donné une durée négative (si SOC batterie > référence).
                        if duration_minutes < 0:
                            log(f"UI: Phase 4 ({banc_id}) - ATTENTION: Durée calculée négative ({duration_minutes:.1f} min) car socBatterieTest ({soc_batterie_test:.1f}%) > {self.PHASE4_MAIN_BATT_LOW_SOC_REF}. Formule inadaptée?",
                                level="ERROR")
                            duration_minutes = 0  # Force la durée à 0 pour éviter les problèmes.
                    # Convertit la durée calculée (ou forcée à 0) en secondes.
                    duration = int(duration_minutes * self.SECONDS_PER_MINUTE)
                    # Applique une durée minimale pour la phase 4.
                    duration = max(duration, self.PHASE4_MIN_DURATION_S)
                    log(f"UI: Phase 4 ({banc_id}), durée finale appliquée: {duration} s", level="DEBUG")
                else:  # Calcul pour les phases 1, 2, 3.
                    duration_dict = {
                        1: self.PHASE1_RI_DURATION_S,  # Phase 1: durée fixe.
                        2: get_charge_duration(voltage_str),  # Phase 2: durée estimée par profil de charge.
                        3: int(soc_batterie_test * self.PHASE3_CAPA_FACTOR_MIN_PER_SOC_PCT *
                               self.SECONDS_PER_MINUTE)  # Phase 3: durée basée sur SOC actuel.
                    }
                    # Utiliser la durée du dictionnaire ou une durée par défaut (en secondes).
                    duration = duration_dict.get(phase_step, self.DEFAULT_DURATION_S)
                if duration <= 0:
                    log(f"UI: Durée calculée <= 0 ({duration}s) pour phase {phase_step} banc {banc_id}. Utilisation durée par défaut {self.DEFAULT_DURATION_S}s.",
                        level="ERROR")
                    duration = self.DEFAULT_DURATION_S  # Force une durée positive par défaut.
            except Exception as calc_e:
                log(f"UI: ERREUR pendant calcul durée phase {phase_step} pour {banc_id}: {calc_e}. Animation annulée.",
                    level="ERROR")
                # Nettoyer le timer actif pour ce banc si le calcul échoue.
                self.active_phase_timers.pop(banc_id, None)
                return  # Ne pas démarrer l'animation si le calcul échoue.

            # --- DEMARRAGE DE L'ANIMATION ---
            start_time = time.time()
            if target_bar is None:
                log(f"UI: ERREUR - target_bar est None pour phase {phase_step} banc {banc_id} avant set(0.0). Animation annulée.",
                    level="ERROR")
                self.active_phase_timers.pop(banc_id, None)  # Nettoyer.
                return
            target_bar.set(0.0)  # Redémarre la barre de progression cible à 0%.

            # Fonction de mise à jour récursive (via self.after).
            def update():
                try:
                    # Vérifie si l'animation a été annulée entre temps.
                    current_timer = self.active_phase_timers.get(banc_id, {})
                    if current_timer.get("cancel", False):
                        log(f"UI: Animation annulée pour {banc_id} phase {phase_step}", level="DEBUG")
                        return  # Stoppe la récursion si annulé.

                    elapsed = time.time() - start_time  # Temps écoulé depuis le début de l'animation.
                    # Gère le cas où duration serait 0 pour éviter la division par zéro.
                    progress = min(elapsed / duration, 1.0) if duration > 0 else 1.0  # Progrès de l'animation (0-1).
                    remaining = max(int(duration - elapsed), 0)  # Temps restant en secondes.

                    # Conversion H:M:S.
                    h, m_rem = divmod(remaining, 3600)
                    m, s = divmod(m_rem, 60)

                    # Met à jour le label de temps restant et la barre de progression.
                    if label_time_left:
                        label_time_left.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
                    if target_bar:  # Re-vérifier si target_bar existe (par sécurité).
                        target_bar.set(progress)

                    # Si le timer n'est pas annulé et l'animation n'est pas finie, continue.
                    if progress < 1.0:
                        # Planifier le prochain appel et stocker l'ID.
                        if banc_id in self.active_phase_timers:
                            after_id = self.after(self.ANIMATION_INTERVAL_MS, update)
                            self.active_phase_timers[banc_id]["after_id"] = after_id
                        else:
                            # Si le timer a été annulé entre temps, annuler le after qu'on vient de créer.
                            log(f"UI: Timer pour {banc_id} non trouvé juste après self.after(). Annulation.",
                                level="WARNING")
                    else:
                        if label_time_left:
                            label_time_left.configure(text="00:00:00")
                        log(f"UI: Phase {phase_step} animation terminée pour {banc_id}", level="INFO")
                except Exception as update_e:
                    log(f"UI: ERREUR pendant mise à jour animation phase {phase_step} pour {banc_id}: {update_e}. Animation arrêtée.",
                        level="ERROR")
                    if label_time_left:
                        try:
                            label_time_left.configure(text="ERREUR")
                        except:
                            pass  # Ignorer erreur de mise à jour finale.
                    # Marquer le timer comme annulé pour éviter des problèmes futurs.
                    if banc_id in self.active_phase_timers:
                        self.active_phase_timers[banc_id]["cancel"] = True

            update()
        except Exception as main_anim_e:
            log(f"UI: ERREUR MAJEURE dans animate_phase_segment pour {banc_id}, phase {phase_step}: {main_anim_e}",
                level="ERROR")
            # Essayer de nettoyer le timer si possible
            if banc_id in self.active_phase_timers:
                timer_info = self.active_phase_timers.pop(banc_id, {})  # Retire l'entrée
                after_id = timer_info.get("after_id")
                if after_id:
                    try:
                        self.after_cancel(after_id)
                    except ValueError:
                        pass  # Ignore si déjà annulé/expiré
        # On ne propage pas l'erreur pour ne pas planter l'UI

    def finalize_previous_phase(self, banc_id):
        """
        Finalise l'animation de la phase précédente pour un banc donné.
        """
        # Récupère les informations du timer précédent pour ce banc depuis le dictionnaire d'état. Retourne {} si absent.
        old_timer = self.active_phase_timers.get(banc_id, {})
        # Récupère la référence à la barre de progression multi-segments pour ce banc.
        phase_bar = (self.banc_widgets.get(banc_id) or {}).get("progress_bar_phase")
        if not old_timer or not phase_bar:
            return
        after_id = old_timer.get("after_id")  # Récupère l'ID stocké.
        if after_id:
            try:
                self.after_cancel(after_id)
            except ValueError:
                # Logue l'erreur (peut arriver si la phase s'est terminée très vite ou si finalize est appelé plusieurs fois).
                log(f"UI: Tentative d'annulation d'un timer after invalide/expiré pour {banc_id} (ID: {after_id})",
                    level="ERROR")
            except Exception as e:  # Garder un catch-all par sécurité.
                log(f"UI: Erreur inattendue lors de after_cancel pour {banc_id} (ID: {after_id}): {e}", level="ERROR")
            old_timer["cancel"] = True  # Pour que la boucle `update` se stoppe.
        # Remplit à 100% le segment de la barre de progression correspondant à la phase qui vient de se terminer.
        old_phase = old_timer.get("phase")
        # Segment à finaliser.
        if old_phase == 1:
            target_bar_to_finalize = phase_bar.progress_ri
        elif old_phase == 2:
            target_bar_to_finalize = phase_bar.progress_phase2
        elif old_phase == 3:
            target_bar_to_finalize = phase_bar.progress_capa
        elif old_phase == 4:
            target_bar_to_finalize = phase_bar.progress_charge
        if target_bar_to_finalize:
            try:
                target_bar_to_finalize.set(1.0)
                log(f"UI: Traitement animation phase {old_phase} terminé/stoppé pour {banc_id}.", level="INFO")
            except Exception as e:
                # Sécurité si jamais .set() échoue pour une raison inconnue
                log(f"UI: Erreur lors de target_bar.set(1.0) pour finaliser phase {old_phase}, banc {banc_id}: {e}",
                    level="ERROR")
        elif old_phase is not None:  # Log seulement si on s'attendait à trouver une barre
            log(f"UI: Impossible de trouver la barre de progression pour finaliser phase {old_phase}, banc {banc_id}",
                level="WARNING")

    def update_status_icon(self, banc_id, icon_type, state):
        """
        Met à jour l'image d'une icône de statut (chargeur ou nurses).
        """
        widgets = self.banc_widgets.get(banc_id)
        if not widgets:
            return
        # Construit la clé pour trouver le widget
        widget_key = f"icon_{icon_type}"
        icon_widget = widgets.get(widget_key)
        # Construit la clé pour trouver l'image (ex: "charger_on")
        icon_image_key = f"{icon_type}_{state}"
        icon_image = self.status_icons.get(icon_image_key)
        if icon_widget and icon_image:
            # Planifie la mise à jour de l'image dans le thread principal de l'UI
            self.after(0, lambda w=icon_widget, img=icon_image: w.configure(image=img))
            log(f"UI: Mise à jour de l'icône '{widget_key}' pour '{banc_id}' à l'état '{state}'.", level="DEBUG")
        else:
            log(f"UI: ERREUR - Widget ('{widget_key}') ou image ('{icon_image_key}') non trouvé pour la mise à jour de l'icône.",
                level="ERROR")

    def handle_prompt(self, event=None):
        """
            Gère l'entrée utilisateur via le gestionnaire de scan.
    """
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
        if not widgets: return
        log(f"UI: Planification Réinitialisation UI pour {banc_id}", level="DEBUG")
        # Planifie l'appel à hide_security_display immédiatement pour s'assurer que tout affichage de sécurité est retiré.
        self.after(0, self.hide_security_display, banc_id)
        # Réinitialisation des barres de progression.
        # Récupère la référence à la barre de progression multi-segments.
        pb_phase = widgets.get("progress_bar_phase")
        # Vérifie si la barre existe ET si elle possède bien une méthode 'reset'.
        if pb_phase and hasattr(pb_phase, 'reset'):
            pb_phase.reset()
            log(f"UI: Barre de progression phase réinitialisée pour {banc_id}.", level="DEBUG")
        elif pb_phase:  # Si elle existe mais n'a pas de méthode reset.
            log(f"UI: AVERTISSEMENT - pb_phase pour {banc_id} n'a pas de méthode reset().", level="WARNING")
        # Réinitialisation des labels de données.
        if widgets.get("phase"): widgets["phase"].configure(text="-")
        if widgets.get("time_left"):
            widgets["time_left"].configure(text="--:--:--")
        if widgets.get("ri_value"): widgets["ri_value"].configure(text="-")
        if widgets.get("diffusion_value"):
            widgets["diffusion_value"].configure(text="-")
        # Réinitialisation du label titre du banc.
        label_banc_widget = widgets.get("banc")
        if label_banc_widget:
            label_banc_widget.configure(text=f"{banc_id.replace('b', 'B', 1)} : Libre")
        else:
            log(f"UI: Widget 'banc' (label titre) non trouvé pour {banc_id} lors du reset UI.", level="ERROR")
        # Vider les valeurs internes UI pour ce banc
        widgets["current_step"] = 0
        widgets["serial"] = None
        self.active_phase_timers.pop(banc_id, None)  # Nettoyer état timer

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
            self.label_response2.configure(text=self.label_response2.cget("text") + " (Config email manquante)")
            return False

        if not serial_numbers_expedies:
            log("UI: Aucune batterie à inclure dans l'email d'expédition.", level="INFO")
            return True

        # Génération du contenu via les templates
        try:
            subject = EmailTemplates.generate_expedition_subject(timestamp_expedition_str)
            text_content, html_content = EmailTemplates.generate_expedition_email_content(
                serial_numbers_expedies, timestamp_expedition_str)
        except Exception as template_error:
            log(f"UI: Erreur lors de la génération du template email: {template_error}", level="ERROR")
            self.label_response2.configure(text=self.label_response2.cget("text") + " (Erreur template)")
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

        # Tentatives d'envoi avec logique de réessai
        for attempt in range(retry_attempts):
            try:
                log(f"UI: Tentative d'envoi de l'email d'expédition à {', '.join(email_config.recipient_emails)} (Tentative {attempt + 1}/{retry_attempts})...",
                    level="INFO")

                # Connexion et envoi
                server = smtplib.SMTP_SSL(email_config.smtp_server, email_config.smtp_port)
                server.ehlo()
                server.login(email_config.gmail_user, email_config.gmail_password)
                server.sendmail(email_config.gmail_user, email_config.recipient_emails, message.as_string())
                server.close()

                log(f"UI: Email d'expédition envoyé avec succès à {', '.join(email_config.recipient_emails)} !",
                    level="INFO")
                self.label_response2.configure(text=f"Email envoyé ({len(serial_numbers_expedies)} batteries)")
                return True

            except smtplib.SMTPAuthenticationError:
                log(f"UI: Erreur d'authentification SMTP pour Gmail (Tentative {attempt + 1}/{retry_attempts}). Vérifiez la configuration email.",
                    level="ERROR")
                self.label_response2.configure(text=self.label_response2.cget("text") + " (Erreur auth email)")
                return False  # Cette erreur est probablement persistante, pas de réessai nécessaire

            except (socket.gaierror, OSError) as e:
                log(f"UI: ERREUR RÉSEAU lors de la connexion SMTP (Tentative {attempt + 1}/{retry_attempts}) : {e}. Vérifiez la connexion internet et le DNS.",
                    level="ERROR")
                self.label_response2.configure(text=self.label_response2.cget("text") + " (Erreur réseau/DNS)")
                if attempt < retry_attempts - 1:  # Si ce n'est pas la dernière tentative
                    log(f"UI: Réessai de l'envoi de l'email dans {delay_between_retries} secondes...", level="INFO")
                    time.sleep(delay_between_retries)
                else:
                    log(f"UI: Échec de l'envoi de l'email après {retry_attempts} tentatives pour cause d'erreur réseau/DNS.",
                        level="ERROR")
                    return False

            except Exception as e:
                log(f"UI: Erreur inattendue lors de l'envoi de l'email d'expédition (Tentative {attempt + 1}/{retry_attempts}) : {e}",
                    level="ERROR")
                self.label_response2.configure(text=self.label_response2.cget("text") + " (Erreur envoi email)")
                return False

        return False  # Si toutes les tentatives ont échoué


def on_connect(client, userdata, flags, rc):
    """
    Callback exécuté lors de la connexion (ou reconnexion) au broker MQTT.
    S'abonne aux topics nécessaires pour tous les bancs.
    Met à jour les labels UI si succès.
    """
    log(f"UI: Connecté avec le code {str(rc)} ", level="INFO")
    # --- Vérifie si la connexion a réussi (code 0 = success) ---
    if rc == mqtt.MQTT_ERR_SUCCESS:
        log(f"UI: Connexion MQTT réussie. Tentative d'abonnements...", level="INFO")
        if userdata is None:
            log("UI: Erreur critique - userdata est None dans on_connect.", level="WARNING")
            return
        app = userdata.get("app")
        if app is None:
            log("UI: Erreur critique - 'app' non trouvé dans userdata.", level="WARNING")
            return  # Ne peut pas continuer sans l'instance 'app'.
        # Procédure d'abonnement aux topics pour tous les bancs.
        all_subscriptions_successful = True
        for i in range(1, NUM_BANCS + 1):
            banc_id_str = f"banc{i}"  # Crée "banc1", "banc2", etc.
            # Construire la liste COMPLÈTE des topics à abonner.
            topics_to_subscribe = [
                (f"{banc_id_str}/step", 0),  # Étape actuelle du test.
                (f"{banc_id_str}/bms/data", 0),  # Données BMS brutes.
                (f"{banc_id_str}/security", 0),  # Messages d'alerte.
                (f"{banc_id_str}/ri/results", 0),  # Résultats Ri/Diffusion.
                (f"{banc_id_str}/state", 0)  # Etat chargeur et nourrices.
            ]
            try:
                # S'abonner à TOUS les topics pour ce banc en UNE SEULE FOIS.
                result, mid = client.subscribe(topics_to_subscribe)
                if result != mqtt.MQTT_ERR_SUCCESS:
                    all_subscriptions_successful = False
                    log(f"UI: ERREUR abonnement {banc_id_str}. Code: {result}", level="ERROR")
            except Exception as sub_e:
                log(f"UI: Exception abonnement {banc_id_str}: {sub_e}", level="ERROR")
                all_subscriptions_successful = False
        # Mise à jour de l'UI après les tentatives d'abonnement.
        if all_subscriptions_successful:
            log(f"UI: Abonnements MQTT terminés.", level="INFO")
            msg1 = "Système Prêt."
            msg2 = "Veuillez scanner pour commencer..."
            try:
                app.after(0, lambda w=app.label_response1, m=msg1: w.configure(text=m))
                app.after(0, lambda w=app.label_response2, m=msg2: w.configure(text=m))
                log(f"UI: Labels initiaux mis à jour.", level="DEBUG")
            except Exception as e:
                log(f"UI: Erreur maj labels initiaux: {e}", level="ERROR")
        else:
            log(f"UI: Échec d'au moins un abonnement MQTT.", level="ERROR")
            msg1 = "Erreur MQTT"
            msg2 = "Échec abonnements. Vérifier logs."
            # Mettre à jour UI pour indiquer l'erreur.
            try:
                app.after(0, lambda w=app.label_response1, m=msg1: w.configure(text=m))
                app.after(0, lambda w=app.label_response2, m=msg2: w.configure(text=m))
            except Exception as e_label:
                log(f"UI: Erreur maj labels (échec abo): {e_label}", level="ERROR")
    else:  # Si le code retour `rc` de la connexion initiale n'était pas succès.
        log(f"UI: Connexion MQTT échouée (Code: {rc}).", level="WARNING")
        # Mettre à jour UI pour indiquer l'échec connexion
        msg1 = "Erreur Connexion MQTT"
        msg2 = f"Code: {rc}. Vérifier broker/réseau."
        if userdata and "app" in userdata and userdata["app"]:
            app = userdata["app"]
            try:  # Ajout try/except
                app.after(0, lambda w=app.label_response1, m=msg1: w.configure(text=m))
                app.after(0, lambda w=app.label_response2, m=msg2: w.configure(text=m))
            except Exception as e_label_conn:
                log(f"UI: Erreur maj labels (échec connexion): {e_label_conn}", level="ERROR")


@staticmethod
def on_message(client, userdata, msg):
    """
    Callback exécuté à la réception d'un message sur un topic MQTT souscrit.
    Utilise les handlers du module ui.message_handlers pour traiter les messages.
    """
    topic = msg.topic.rstrip("/")  # Supprime un éventuel "/" à la fin.

    # Vérifie si les données utilisateur (`userdata`) sont valides et contiennent bien l'instance 'app'.
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
    topic_suffix = '/'.join(topic_parts[1:])  # ex: "step", "bms/data", "security"

    # Vérifie si l'ID extrait commence bien par "banc" ET s'il existe une entrée correspondante dans `app.banc_widgets`.
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


def safe_ui_update(app_instance, msg1, msg2):
    """Met à jour les labels de réponse de l'UI via app.after pour thread-safety."""
    if app_instance:  # Vérifie que l'instance existe
        try:
            # Vérifier si les widgets existent avant de les configurer
            if hasattr(app_instance, 'label_response1') and app_instance.label_response1:
                app_instance.label_response1.configure(text=msg1)
            if hasattr(app_instance, 'label_response2') and app_instance.label_response2:
                app_instance.label_response2.configure(text=msg2)
        except Exception as ui_e:
            log(f"UI: Erreur interne lors de la mise à jour UI via 'after': {ui_e}", level="WARNING")


def mqtt_thread(app_instance):
    """
    Fonction exécutée dans un thread séparé pour gérer la boucle MQTT.
    Se connecte au broker, reste en écoute, et gère la reconnexion automatique.
    """
    try:
        # Crée un identifiant client MQTT unique pour cette instance de l'UI (utilise le PID du processus).
        ui_client_id = f"ui_client_{os.getpid()}"
        client = mqtt.Client(
            client_id=ui_client_id,
            userdata={"app": app_instance},
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1)  # type: ignore
        # `type: ignore` est utilisé pour supprimer un avertissement potentiel de linter sur la version API.
        app_instance.mqtt_client = client  # Stocker référence au client dans App.
        client.on_connect = on_connect
        client.on_message = on_message

        # Définition du callback de déconnexion (interne à mqtt_thread).
        def on_disconnect(client, userdata, rc):
            log(f"UI: Déconnecté du broker MQTT avec le code {rc}.", level="WARNING")
            # Important: Mettre la référence du client à None dans App.
            if userdata and "app" in userdata:
                app = userdata["app"]
                if app:
                    app.mqtt_client = None
                    # Mettre à jour l'UI pour indiquer la déconnexion.
                    msg1 = "MQTT Déconnecté"
                    msg2 = "Tentative de reconnexion..."
                    # Utiliser 'after' pour l'appel thread-safe.
                    app.after(0, lambda a=app, m1=msg1, m2=msg2: safe_ui_update(a, m1, m2))

        client.on_disconnect = on_disconnect
    except Exception as client_e:
        log(f"UI: Erreur critique lors de la création du client MQTT: {client_e}", level="ERROR")
        # Si on ne peut même pas créer le client, on ne peut rien faire d'autre.
        app_instance.after(0,
                           lambda: safe_ui_update(app_instance, "Erreur Init MQTT", "Impossible de créer le client."))
        return  # Le thread s'arrête.
    # Boucle infinie pour tenter de maintenir la connexion MQTT.
    while True:
        try:
            log("UI: Tentative de connexion au broker MQTT...", level="INFO")
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            app_instance.mqtt_client = client  # Re-assigner le client en cas de reconnexion.
            log("UI: Connexion MQTT établie. Démarrage boucle de réception.", level="INFO")
            client.loop_forever()  # Bloque ici jusqu'à déconnexion ou erreur.
            # Si on sort de loop_forever proprement (ex: client.disconnect appelé ailleurs).
            log("UI: Boucle MQTT terminée normalement.", level="INFO")
            break
        # Gestion des erreurs.
        except (socket.timeout, TimeoutError, ConnectionRefusedError, socket.gaierror, OSError) as conn_e:
            log(f"UI: Erreur de connexion/réseau MQTT: {conn_e}", level="WARNING")
            # Mettre à jour l'UI via app.after pour indiquer l'échec.
            msg1 = "Erreur Réseau MQTT"
            msg2 = f"Vérifier broker ({MQTT_BROKER}:{MQTT_PORT}) et réseau."
            app_instance.after(0, lambda app=app_instance, m1=msg1, m2=msg2: safe_ui_update(app, m1, m2))
        except Exception as e:
            log(f"UI: Erreur inattendue dans la boucle MQTT: {e}", level="WARNING")
            # Mettre à jour l'UI via app.after.
            msg1 = "Erreur MQTT"
            msg2 = "Erreur interne. Tentative de reconnexion."
            app_instance.after(0, lambda app=app_instance, m1=msg1, m2=msg2: safe_ui_update(app, m1, m2))
        # --- Tentative de reconnexion ---
        log(f"UI: Prochaine tentative de connexion MQTT dans 5 secondes...", level="INFO")
        time.sleep(5)  # La boucle `while True` reprendra ensuite, relançant une tentative de connexion.
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
        print(f"Erreur critique UI: {e}")  # Afficher sur console si log ne marche pas
        return  # Ne pas continuer si l'UI n'a pas pu s'initialiser
    # Tente de créer et démarrer le thread dédié à MQTT.
    try:
        # Crée un objet Thread. `target` est la fonction à exécuter, `args` sont les arguments à lui passer.
        # `daemon=True` signifie que ce thread s'arrêtera automatiquement si le thread principal (UI) se termine.
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
