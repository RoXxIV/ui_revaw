# -*- coding: utf-8 -*-
"""
Gestionnaire des mises à jour de l'UI.
"""

from .system_utils import log
from .data_operations import get_temperature_coefficient
from src.ui.ui_components import (update_soc_canvas, get_phase_message, _get_balance_color, _get_temp_color,
                                  _get_capacity_color, _get_energy_color)
import json
import os


class UIUpdater:
    """
    Classe responsable des mises à jour de l'interface utilisateur.
    Cette classe centralise toute la logique de mise à jour des widgets,
    permettant une meilleure organisation du code de l'interface.
    """

    # === CONSTANTES D'AFFICHAGE ===
    MIN_EXPECTED_BMS_FIELDS = 10
    SECURITY_DISPLAY_DURATION_MS = 5000
    NURSE_LOW_SOC_THRESHOLD_RATIO = 0.3
    LARGE_BORDER_WIDTH_ACTIVE = 50
    NORMAL_BORDER_WIDTH = 1

    def __init__(self, app):
        """
        Initialise le gestionnaire de mise à jour UI.
        Args:
            app: Instance de l'application UI
        """
        self.app = app

    def update_banc_data(self, banc_id, data):
        """
        Met à jour les widgets d'un banc avec les données BMS reçues via MQTT.
        Args:
            banc_id (str): Identifiant du banc
            data (list): Données BMS sous forme de liste
        """
        if not self._validate_bms_data(banc_id, data):
            return

        try:
            # Extraction des données BMS
            bms_data = self._extract_bms_data(data)
            if not bms_data:
                return

            # Mise à jour des widgets
            widgets = self.app.banc_widgets.get(banc_id)
            if widgets:
                self._update_basic_widgets(widgets, bms_data)
                self._update_conditional_colors(widgets, bms_data)
                self._update_soc_display(widgets, bms_data, banc_id)
                self._update_nurse_progress(widgets, bms_data)
                self._update_border_color(widgets, banc_id)

        except Exception as e:
            log(f"UIUpdater: Erreur mise à jour données BMS pour {banc_id}: {e}", level="ERROR")

    def update_ri_diffusion_widgets(self, banc_id):
        """
        Met à jour les widgets Ri et Diffusion depuis le fichier config.json.
        Args:
            banc_id (str): Identifiant du banc
        """
        log(f"UIUpdater: Mise à jour Ri/Diffusion pour {banc_id}", level="DEBUG")

        widgets = self.app.banc_widgets.get(banc_id)
        if not widgets:
            log(f"UIUpdater: Widgets non trouvés pour {banc_id}", level="ERROR")
            return

        # Récupération du chemin du dossier
        battery_folder = widgets.get("battery_folder_path")
        if not battery_folder:
            log(f"UIUpdater: 'battery_folder_path' non trouvé dans widgets pour {banc_id}, tentative de reconstruction...",
                level="WARNING")

            # Récupérer le serial depuis le label banc
            banc_label = widgets.get("banc")
            if banc_label:
                banc_text = banc_label.cget("text")
                # Extraire le serial du format "Banc1 - RW-48v2710029"
                if " - " in banc_text and "RW-48v271" in banc_text:
                    serial_number = banc_text.split(" - ")[1]
                    # Importer find_battery_folder
                    from .data_operations import find_battery_folder
                    battery_folder = find_battery_folder(serial_number)

                    if battery_folder:
                        # Stocker le chemin récupéré dans les widgets pour éviter de refaire cette recherche
                        widgets["battery_folder_path"] = battery_folder
                        log(f"UIUpdater: Chemin battery_folder_path récupéré et stocké: {battery_folder}", level="INFO")
                    else:
                        log(f"UIUpdater: Impossible de trouver le dossier pour le serial {serial_number}",
                            level="ERROR")
                else:
                    log(f"UIUpdater: Format du label banc invalide pour extraire le serial: {banc_text}", level="ERROR")

        if not battery_folder:
            log(f"UIUpdater: Chemin 'battery_folder_path' non trouvé pour {banc_id}", level="ERROR")
            self._set_widgets_to_na(widgets, ["ri", "diffusion"])
            return

        # Lecture du fichier config.json
        config_data = self._load_battery_config(battery_folder, banc_id)
        if not config_data:
            self._set_widgets_to_na(widgets, ["ri", "diffusion"])
            return

        # Calcul et mise à jour des valeurs Ri/Diffusion
        self._calculate_and_update_ri_diffusion(widgets, config_data, banc_id)

    def update_banc_security(self, banc_id, security_message):
        """
        Affiche un message de sécurité temporaire.
        Args:
            banc_id (str): Identifiant du banc
            security_message (str): Message de sécurité à afficher
        """
        widgets = self.app.banc_widgets.get(banc_id)
        if not widgets:
            return

        # Annuler le timer précédent s'il existe
        self._cancel_previous_security_timer(banc_id)

        # Afficher le message de sécurité
        self._display_security_message(widgets, security_message, banc_id)

        # Programmer la dissimulation
        self._schedule_security_hide(banc_id)

    def hide_security_display(self, banc_id):
        """
        Cache le label de sécurité rouge et réinitialise la bordure.
        Args:
            banc_id (str): Identifiant du banc
        """
        widgets = self.app.banc_widgets.get(banc_id)
        if not widgets:
            return

        # Masquer le label de sécurité
        label_security = widgets.get("label_security")
        if label_security:
            label_security.lower()

        # Réinitialiser la bordure
        self._reset_border_color(widgets, banc_id)

        # Marquer comme inactif
        self.app.security_active[banc_id] = False

        # Nettoyer la référence au timer
        self._cleanup_security_timer(banc_id)

        log(f"UIUpdater: Affichage sécurité masqué pour {banc_id}", level="DEBUG")

    def update_status_icon(self, banc_id, icon_type, state):
        """
        Met à jour l'image d'une icône de statut.
        Args:
            banc_id (str): Identifiant du banc
            icon_type (str): Type d'icône ("charger" ou "nurses")
            state (str): État ("on" ou "off")
        """
        widgets = self.app.banc_widgets.get(banc_id)
        if not widgets:
            return

        widget_key = f"icon_{icon_type}"
        icon_widget = widgets.get(widget_key)

        icon_image_key = f"{icon_type}_{state}"
        icon_image = self.app.status_icons.get(icon_image_key)

        if icon_widget and icon_image:
            self.app.after(0, lambda w=icon_widget, img=icon_image: w.configure(image=img))
            log(f"UIUpdater: Icône '{widget_key}' mise à jour pour '{banc_id}' état '{state}'", level="DEBUG")
        else:
            log(f"UIUpdater: Widget ou image non trouvé pour mise à jour icône", level="ERROR")

    # === MÉTHODES PRIVÉES ===

    def _validate_bms_data(self, banc_id, data):
        """Valide les données BMS reçues."""
        if not isinstance(data, list) or len(data) < self.MIN_EXPECTED_BMS_FIELDS:
            log(
                f"UIUpdater: Données BMS invalides pour {banc_id}. "
                f"Attendu: liste d'au moins {self.MIN_EXPECTED_BMS_FIELDS} éléments, "
                f"Reçu: {type(data)}, len: {len(data) if isinstance(data, list) else 'N/A'}",
                level="WARNING")
            return False
        return True

    def _extract_bms_data(self, data):
        """Extrait et convertit les données BMS essentielles."""
        try:
            return {
                'voltage': float(data[0]),
                'current': float(data[1]),
                'soc_raw': data[2],
                'temperature': float(data[3]),
                'max_cell_v': int(data[5]),
                'min_cell_v': int(data[7]),
                'discharge_capacity': float(data[8]) / 1000,
                'discharge_energy': float(data[9]) / 1000,
                'average_nurse_soc': float(data[26]) if len(data) > 26 else 0.0
            }
        except (IndexError, ValueError, TypeError) as e:
            log(f"UIUpdater: Erreur extraction données BMS: {e}", level="ERROR")
            return None

    def _update_basic_widgets(self, widgets, bms_data):
        """Met à jour les widgets de base avec les données BMS."""
        balance = bms_data['max_cell_v'] - bms_data['min_cell_v']

        widgets["tension"].configure(text=f"{bms_data['voltage']:.1f}")
        widgets["intensity"].configure(text=f"{bms_data['current']:.1f}")
        widgets["temp"].configure(text=f"{bms_data['temperature']:.1f}")
        widgets["discharge_capacity"].configure(text=f"{bms_data['discharge_capacity']:.1f}")
        widgets["discharge_energy"].configure(text=f"{bms_data['discharge_energy']:.1f}")
        widgets["balance"].configure(text=f"{balance:.0f}")

        # Mise à jour du label de phase
        current_step = widgets.get("current_step", 0)
        if current_step in [1, 2, 3, 4, 5]:
            widgets["phase"].configure(text=get_phase_message(current_step))

    def _update_conditional_colors(self, widgets, bms_data):
        """Met à jour les couleurs conditionnelles des widgets."""
        balance = bms_data['max_cell_v'] - bms_data['min_cell_v']
        current_step = widgets.get("current_step", 0)

        widgets["temp"].configure(text_color=_get_temp_color(bms_data['temperature']))
        widgets["balance"].configure(text_color=_get_balance_color(balance))
        widgets["discharge_energy"].configure(text_color=_get_energy_color(bms_data['discharge_energy'], current_step))
        widgets["discharge_capacity"].configure(
            text_color=_get_capacity_color(bms_data['discharge_capacity'], current_step))

    def _update_soc_display(self, widgets, bms_data, banc_id):
        """Met à jour l'affichage du SOC."""
        soc_canvas = widgets.get("soc_canvas")
        if not soc_canvas:
            return

        try:
            soc_value = float(bms_data['soc_raw'])
        except (ValueError, TypeError):
            log(f"UIUpdater: SOC invalide pour {banc_id}: {bms_data['soc_raw']}", level="WARNING")
            soc_value = 0.0

        widgets["last_soc"] = soc_value
        update_soc_canvas(soc_canvas, soc_value)

    def _update_nurse_progress(self, widgets, bms_data):
        """Met à jour la barre de progression des nourrices."""
        progress_bar_nurse = widgets.get("progress_bar_nurse")
        if not progress_bar_nurse:
            return

        progress_ratio = min(max(bms_data['average_nurse_soc'] / 100.0, 0.0), 1.0)
        progress_bar_nurse.set(progress_ratio)

        # Couleur selon le seuil
        is_low = progress_ratio < self.NURSE_LOW_SOC_THRESHOLD_RATIO
        color = "red" if is_low else "#6EC207"
        progress_bar_nurse.configure(progress_color=color)

        widgets["last_avg_nurse_soc"] = bms_data['average_nurse_soc']

    def _update_border_color(self, widgets, banc_id):
        """Met à jour la couleur de bordure selon l'état."""
        parent_frame = widgets.get("parent_frame")
        if not parent_frame:
            return

        # Ne pas modifier si un message de sécurité est actif
        if self.app.security_active.get(banc_id, False):
            return

        current_step = widgets.get("current_step", 0)
        if current_step == 5:
            parent_frame.configure(border_color="#6EC207", border_width=self.LARGE_BORDER_WIDTH_ACTIVE)
        else:
            parent_frame.configure(border_color="white", border_width=self.NORMAL_BORDER_WIDTH)

    def _load_battery_config(self, battery_folder, banc_id):
        """Charge la configuration de la batterie depuis config.json."""
        config_path = os.path.join(battery_folder, "config.json")

        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)

            if not isinstance(config_data, dict):
                log(f"UIUpdater: Contenu config.json invalide pour {banc_id}", level="ERROR")
                return None

            return config_data

        except FileNotFoundError:
            log(f"UIUpdater: Fichier config.json non trouvé pour {banc_id}: {config_path}", level="ERROR")
        except json.JSONDecodeError:
            log(f"UIUpdater: Erreur JSON dans config.json pour {banc_id}", level="ERROR")
        except Exception as e:
            log(f"UIUpdater: Erreur lecture config.json pour {banc_id}: {e}", level="ERROR")

        return None

    def _calculate_and_update_ri_diffusion(self, widgets, config_data, banc_id):
        """Calcule et met à jour les valeurs Ri et Diffusion."""
        try:
            # Extraction des valeurs
            ri_values = [config_data.get("ri_discharge_average", 0.0), config_data.get("ri_charge_average", 0.0)]
            diffusion_values = [
                config_data.get("diffusion_discharge_average", 0.0),
                config_data.get("diffusion_charge_average", 0.0)
            ]

            # Validation des types
            ri_values = [v if isinstance(v, (int, float)) else 0.0 for v in ri_values]
            diffusion_values = [v if isinstance(v, (int, float)) else 0.0 for v in diffusion_values]

            # Calcul des moyennes
            ri_avg = self._calculate_average(ri_values)
            diffusion_avg = self._calculate_average(diffusion_values)

            # Application du coefficient de température
            temperature = self._get_temperature_from_widget(widgets, banc_id)
            coefficient_temp = get_temperature_coefficient(temperature)
            diffusion_avg_corrected = diffusion_avg * coefficient_temp

            # Mise à jour des widgets
            self._update_ri_diffusion_widgets(widgets, ri_avg, diffusion_avg_corrected, banc_id)

        except Exception as e:
            log(f"UIUpdater: Erreur calcul Ri/Diffusion pour {banc_id}: {e}", level="ERROR")
            self._set_widgets_to_error(widgets, ["ri", "diffusion"])

    def _calculate_average(self, values):
        """Calcule la moyenne des valeurs non nulles."""
        non_zero_values = [v for v in values if v != 0.0]
        return sum(non_zero_values) / len(non_zero_values) if non_zero_values else 0.0

    def _get_temperature_from_widget(self, widgets, banc_id):
        """Récupère la température depuis le widget."""
        temp_widget = widgets.get("temp")
        if temp_widget:
            temp_str = temp_widget.cget("text").replace(",", ".")
            try:
                return float(temp_str)
            except ValueError:
                log(f"UIUpdater: Température invalide pour {banc_id}. Utilisation 25°C", level="WARNING")

        return 25.0  # Valeur par défaut

    def _update_ri_diffusion_widgets(self, widgets, ri_avg, diffusion_avg_corrected, banc_id):
        """Met à jour les widgets Ri et Diffusion."""
        ri_widget = widgets.get("ri")
        diffusion_widget = widgets.get("diffusion")

        if ri_widget:
            ri_widget.configure(text=f"{ri_avg * 1000:.2f}")
        if diffusion_widget:
            diffusion_widget.configure(text=f"{diffusion_avg_corrected * 1000:.2f}")

        log(
            f"UIUpdater: Ri/Diffusion mis à jour pour {banc_id}: "
            f"Ri={ri_avg*1000:.2f} mΩ, Diff={diffusion_avg_corrected*1000:.2f} mΩ",
            level="INFO")

    def _set_widgets_to_na(self, widgets, widget_names):
        """Met les widgets spécifiés à "N/A"."""
        for name in widget_names:
            widget = widgets.get(name)
            if widget:
                widget.configure(text="N/A")

    def _set_widgets_to_error(self, widgets, widget_names):
        """Met les widgets spécifiés à "ERR"."""
        for name in widget_names:
            widget = widgets.get(name)
            if widget:
                widget.configure(text="ERR")

    def _cancel_previous_security_timer(self, banc_id):
        """Annule le timer de sécurité précédent."""
        if not hasattr(self.app, '_security_timers'):
            self.app._security_timers = {}

        previous_timer_id = self.app._security_timers.pop(banc_id, None)
        if previous_timer_id:
            try:
                self.app.after_cancel(previous_timer_id)
                log(f"UIUpdater: Timer sécurité précédent annulé pour {banc_id}", level="DEBUG")
            except ValueError:
                log(f"UIUpdater: Timer sécurité déjà expiré pour {banc_id}", level="WARNING")

    def _display_security_message(self, widgets, security_message, banc_id):
        """Affiche le message de sécurité."""
        self.app.security_active[banc_id] = True

        label_security = widgets.get("label_security")
        parent_frame = widgets.get("parent_frame")

        if label_security:
            label_security.configure(
                text=security_message, text_color="white", fg_color="red", font=("Helvetica", 40, "bold"))
            label_security.place(relx=0.5, rely=0.5, anchor="center")
            label_security.lift()

        if parent_frame:
            parent_frame.configure(border_color="red", border_width=self.LARGE_BORDER_WIDTH_ACTIVE)

    def _schedule_security_hide(self, banc_id):
        """Programme la dissimulation du message de sécurité."""
        if not hasattr(self.app, '_security_timers'):
            self.app._security_timers = {}

        timer_id = self.app.after(self.SECURITY_DISPLAY_DURATION_MS, lambda: self.hide_security_display(banc_id))
        self.app._security_timers[banc_id] = timer_id

    def _reset_border_color(self, widgets, banc_id):
        """Réinitialise la couleur de bordure."""
        parent_frame = widgets.get("parent_frame")
        if not parent_frame:
            return

        current_step = widgets.get("current_step", 0)
        if current_step == 5:
            parent_frame.configure(border_color="#6EC207", border_width=self.LARGE_BORDER_WIDTH_ACTIVE)
        else:
            parent_frame.configure(border_color="white", border_width=self.NORMAL_BORDER_WIDTH)

    def _cleanup_security_timer(self, banc_id):
        """Nettoie la référence au timer de sécurité."""
        if hasattr(self.app, '_security_timers'):
            timer_id = self.app._security_timers.pop(banc_id, None)
            if timer_id:
                try:
                    self.app.after_cancel(timer_id)
                except ValueError:
                    pass

    def debug_widget_state(self, banc_id):
        """Méthode de debug pour vérifier l'état des widgets d'un banc."""
        widgets = self.app.banc_widgets.get(banc_id)
        if not widgets:
            log(f"DEBUG: Aucun widget trouvé pour {banc_id}", level="DEBUG")
            return

        log(f"DEBUG: État des widgets pour {banc_id}:", level="DEBUG")
        log(f"  - battery_folder_path: {widgets.get('battery_folder_path', 'NON DÉFINI')}", level="DEBUG")
        log(f"  - current_step: {widgets.get('current_step', 'NON DÉFINI')}", level="DEBUG")

        banc_label = widgets.get("banc")
        if banc_label:
            log(f"  - banc label text: {banc_label.cget('text')}", level="DEBUG")
        else:
            log(f"  - banc label: NON TROUVÉ", level="DEBUG")
