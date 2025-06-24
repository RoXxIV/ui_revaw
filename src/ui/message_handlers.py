# -*- coding: utf-8 -*-
"""
Handlers pour les messages MQTT de l'interface utilisateur.
"""
import json
from src.ui.utils import log
from .ui_components import get_phase_message


def handle_step_message(payload_str, banc_id, app):
    """
    Gère les messages MQTT sur le topic /{banc}/step.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc_id (str): ID du banc (ex: "banc1")
        app: Instance de l'application UI
    """
    try:
        new_step = int(payload_str)
    except ValueError:
        log(f"UI: Payload /step invalide pour {banc_id}: {payload_str}", level="WARNING")
        return  # Ignorer si le step n'est pas un nombre.

    widgets = app.banc_widgets.get(banc_id)
    if not widgets:
        log(f"UI: Widgets non trouvés pour {banc_id} lors réception step {new_step}", level="WARNING")
        return

    # Récupère l'étape précédente connue par l'UI AVANT de la mettre à jour.
    previous_step = widgets.get("current_step", 0)
    widgets["current_step"] = new_step

    # Configure le label phase basé sur new_step
    label_phase_widget = widgets.get("phase")
    if label_phase_widget:
        app.after(0, lambda w=label_phase_widget, s=new_step: w.configure(text=get_phase_message(s)))

    # === GESTION DES STEPS SPÉCIAUX ===
    if new_step == 6:
        _handle_step_6_failed_test(banc_id, app, widgets)
        return
    elif new_step == 7:
        _handle_step_7_security_stop(banc_id, app, widgets)
        return
    elif new_step == 8:
        _handle_step_8_stop_requested(banc_id, app)
        return
    elif new_step == 9:
        _handle_step_9_manual_stop(banc_id, app, widgets, previous_step)
        return

    log(f"UI: {banc_id} current_step (UI) mis à jour: {new_step}", level="INFO")

    # === ÉTAPES NORMALES ===
    if new_step == 2 and previous_step == 1:
        log(f"UI: Étape 2 détectée pour {banc_id}. Planification MAJ Ri/Diffusion UI.", level="INFO")
        app.after(0, app.update_ri_diffusion_widgets, banc_id)

    # Si la nouvelle étape est une phase active à animer (1, 2, 3 ou 4).
    if new_step in [1, 2, 3, 4]:
        app.after(0, app.animate_phase_segment, banc_id, new_step)
    # Si la nouvelle étape est 5 (fin normale du test).
    elif new_step == 5:
        _handle_step_5_test_completed(banc_id, app, widgets)


def handle_bms_data_message(payload_str, banc_id, app):
    """
    Gère les messages MQTT sur le topic /{banc}/bms/data.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc_id (str): ID du banc
        app: Instance de l'application UI
    """
    data = payload_str.split(",")
    app.after(0, app.update_banc_data, banc_id, data)


def handle_security_message(payload_str, banc_id, app):
    """
    Gère les messages MQTT sur le topic /{banc}/security.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc_id (str): ID du banc
        app: Instance de l'application UI
    """
    security_message = payload_str
    app.after(0, app.update_banc_security, banc_id, security_message)


def handle_ri_results_message(payload_str, banc_id, app):
    """
    Gère les messages MQTT sur le topic /{banc}/ri/results.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc_id (str): ID du banc
        app: Instance de l'application UI
    """
    log(f"UI: Résultats RI/Diffusion disponibles pour {banc_id}. (MAJ via step 2)", level="INFO")
    # La mise à jour se fait via step 2, pas besoin d'action ici


def handle_state_message(payload_str, banc_id, app):
    """
    Gère les messages MQTT sur le topic /{banc}/state.
    
    Args:
        payload_str (str): Le payload du message MQTT
        banc_id (str): ID du banc
        app: Instance de l'application UI
    """
    # Dictionnaire pour mapper les payloads aux actions
    state_map = {'0': ('nurses', 'off'), '1': ('nurses', 'on'), '2': ('charger', 'off'), '3': ('charger', 'on')}

    # Récupère l'action correspondante (ex: ('nurses', 'on'))
    action = state_map.get(payload_str)
    if action:
        icon_type, icon_state = action
        # mettre à jour l'UI
        app.after(0, app.update_status_icon, banc_id, icon_type, icon_state)
    else:
        log(f"UI: Payload non reconnu '{payload_str}' reçu sur le topic /{banc_id}/state", level="WARNING")


# === FONCTIONS PRIVÉES POUR LES STEPS SPÉCIAUX ===


def _handle_step_6_failed_test(banc_id, app, widgets):
    """Gère le step 6 (test échoué)."""
    log(f"UI: Step 6 (Test ÉCHOUÉ) reçu pour {banc_id}. Arrêt timer et MàJ UI.", level="INFO")

    # 1. Finaliser/Stopper l'animation de la phase en cours.
    app.finalize_previous_phase(banc_id)

    # 2. Mettre à jour le label du temps restant.
    label_time_left_step6 = widgets.get("time_left")
    if label_time_left_step6:
        app.after(0, lambda w=label_time_left_step6: w.configure(text="Terminé (Échec)"))

    # 3. Mettre toutes les barres de progression des phases à 100%
    phase_bar_step6 = widgets.get("progress_bar_phase")
    if phase_bar_step6:
        try:
            if hasattr(phase_bar_step6, 'progress_ri'):
                app.after(0, phase_bar_step6.progress_ri.set, 1.0)
            if hasattr(phase_bar_step6, 'progress_phase2'):
                app.after(0, phase_bar_step6.progress_phase2.set, 1.0)
            if hasattr(phase_bar_step6, 'progress_capa'):
                app.after(0, phase_bar_step6.progress_capa.set, 1.0)
            if hasattr(phase_bar_step6, 'progress_charge'):
                app.after(0, phase_bar_step6.progress_charge.set, 1.0)
        except Exception as e:
            log(f"UI: Erreur lors de la mise à 100% des barres pour step 6 ({banc_id}): {e}", level="ERROR")

    # 4. Bordure neutre pour l'état "Test Échoué"
    parent_frame_step6 = widgets.get("parent_frame")
    if parent_frame_step6:
        app.after(
            0, lambda pf=parent_frame_step6: pf.configure(border_color="white", border_width=app.NORMAL_BORDER_WIDTH))

    log(f"UI: Traitement pour Step 6 (Test Échoué) terminé pour {banc_id}.", level="INFO")


def _handle_step_7_security_stop(banc_id, app, widgets):
    """Gère le step 7 (arrêt sécurité ESP32)."""
    log(f"UI: Step 7 (Arrêt Sécurité ESP32) reçu pour {banc_id}. Arrêt du timer d'animation UI.", level="INFO")

    # 1. Stopper l'animation de la phase en cours sans la marquer comme "terminée à 100%"
    active_timer_info = app.active_phase_timers.get(banc_id)
    if active_timer_info:
        active_timer_info["cancel"] = True  # Signale à la boucle d'animation de s'arrêter
        after_id_to_cancel = active_timer_info.get("after_id")
        if after_id_to_cancel:
            try:
                app.after_cancel(after_id_to_cancel)
                log(f"UI: Timer d'animation (ID: {after_id_to_cancel}) pour {banc_id} annulé suite à Step 7.",
                    level="DEBUG")
            except ValueError:
                log(f"UI: Tentative d'annulation d'un timer d'animation (ID: {after_id_to_cancel}) déjà expiré/invalide pour {banc_id} (Step 7).",
                    level="WARNING")
        # Retirer l'entrée du timer pour ce banc
        app.active_phase_timers.pop(banc_id, None)
        log(f"UI: Entrée active_phase_timers pour {banc_id} retirée suite à Step 7.", level="DEBUG")

    # 2. Mettre à jour le label du temps restant
    label_time_left = widgets.get("time_left")
    if label_time_left:
        app.after(0, lambda w=label_time_left: w.configure(text="--:--:--"))


def _handle_step_8_stop_requested(banc_id, app):
    """Gère le step 8 (arrêt demandé)."""
    log(f"UI: Step 8 (Arrêt) reçu pour {banc_id}. Reset activé pour ce banc.", level="INFO")
    # Active le flag permettant le reset manuel pour ce banc.
    app.reset_enabled_for_banc[banc_id] = True
    app.finalize_previous_phase(banc_id)


def _handle_step_9_manual_stop(banc_id, app, widgets, previous_step):
    """Gère le step 9 (arrêt manuel)."""
    log(f"UI: Step 9 reçu pour {banc_id}. Arrêt timer et correction label phase.", level="INFO")

    # Arrêter l'animation/timer en cours
    app.finalize_previous_phase(banc_id)

    # Réinitialiser l'affichage du timer à 0
    label_time_left = widgets.get("time_left")
    if label_time_left:
        app.after(0, lambda w=label_time_left: w.configure(text="00:00:00"))

    # CORRIGER le label de phase qui a été mis à "0/5" par le bloc initial
    label_phase = widgets.get("phase")
    if label_phase:
        correct_phase_text = get_phase_message(previous_step)
        app.after(0, lambda w=label_phase, txt=correct_phase_text: w.configure(text=txt))
        log(f"UI: Label phase corrigé à '{correct_phase_text}' pour {banc_id} après step 9.", level="DEBUG")


def _handle_step_5_test_completed(banc_id, app, widgets):
    """Gère le step 5 (test terminé avec succès)."""
    app.finalize_previous_phase(banc_id)  # Finaliser la phase precedente.

    phase_bar = widgets.get("progress_bar_phase")
    if phase_bar:
        try:  # Tente de mettre TOUS les segments de la barre à 100% pour indiquer la complétion.
            if hasattr(phase_bar, 'progress_ri'):
                app.after(0, phase_bar.progress_ri.set, 1.0)
            if hasattr(phase_bar, 'progress_phase2'):
                app.after(0, phase_bar.progress_phase2.set, 1.0)
            if hasattr(phase_bar, 'progress_capa'):
                app.after(0, phase_bar.progress_capa.set, 1.0)
            if hasattr(phase_bar, 'progress_charge'):
                app.after(0, phase_bar.progress_charge.set, 1.0)
        except Exception as e:
            log(f"UI: Erreur mise à 100% barres step 5 pour {banc_id}: {e}", level="ERROR")

    # Remettre le timer à 0 pour step 5
    label_time_left_step5 = widgets.get("time_left")
    if label_time_left_step5:
        app.after(0, lambda w=label_time_left_step5: w.configure(text="00:00:00"))

    # Mettre la bordure en vert pour step 5
    parent_frame_step5 = widgets.get("parent_frame")
    if parent_frame_step5:
        color = "#6EC207"
        width = app.LARGE_BORDER_WIDTH_ACTIVE
        app.after(0, lambda pf=parent_frame_step5, c=color, w=width: pf.configure(border_color=c, border_width=w))

    log(f"UI: Toutes les phases finalisées pour {banc_id}", level="INFO")


def get_ui_message_handlers():
    """
    Retourne un dictionnaire des handlers par topic pour l'UI.
    
    Returns:
        dict: Dictionnaire topic_suffix -> fonction handler
    """
    return {
        'step': handle_step_message,
        'bms/data': handle_bms_data_message,
        'security': handle_security_message,
        'ri/results': handle_ri_results_message,
        'state': handle_state_message,
    }
