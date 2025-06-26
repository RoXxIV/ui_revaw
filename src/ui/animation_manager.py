# -*- coding: utf-8 -*-
import time
from .system_utils import log
from .phase_calculator import PhaseCalculator


class AnimationManager:
    """
    Classe responsable de la gestion des animations de l'interface.
    Cette classe gère les animations des barres de progression et les timers
    pour chaque phase de test, séparant cette logique de la classe App principale.
    """

    # === CONSTANTES D'ANIMATION ===
    ANIMATION_INTERVAL_MS = 1000  # Intervalle entre les mises à jour d'animation

    def __init__(self, app):
        """
        Initialise le gestionnaire d'animation.
        Args:
            app: Instance de l'application UI
        """
        self.app = app
        self.active_timers = {}  # Stockage des timers d'animation actifs

    def start_phase_animation(self, banc_id, phase_step):
        """
        Démarre l'animation pour une phase donnée.
        Args:
            banc_id (str): Identifiant du banc (ex: "banc1")
            phase_step (int): Numéro de la phase (1-4)
        """
        try:
            # Validation des widgets
            widgets = self.app.banc_widgets.get(banc_id)
            if not widgets:
                log(f"AnimationManager: Widgets non trouvés pour {banc_id}", level="ERROR")
                return

            phase_bar = widgets.get("progress_bar_phase")
            label_time_left = widgets.get("time_left")
            if not phase_bar or not label_time_left:
                log(f"AnimationManager: Widgets de progression/temps manquants pour {banc_id}", level="ERROR")
                return

            log(f"AnimationManager: Démarrage animation phase {phase_step} pour {banc_id}", level="INFO")

            # Finaliser l'animation précédente
            self.finalize_previous_phase(banc_id)

            # Initialiser le nouveau timer
            self.active_timers[banc_id] = {"phase": phase_step, "cancel": False}

            # Sélectionner la barre de progression cible
            target_bar = self._get_target_progress_bar(phase_bar, phase_step)
            if not target_bar:
                log(f"AnimationManager: Barre de progression non trouvée pour phase {phase_step}", level="ERROR")
                return

            # Calculer la durée de la phase
            duration = self._calculate_phase_duration(widgets, phase_step)
            if duration <= 0:
                log(f"AnimationManager: Durée invalide ({duration}s) pour phase {phase_step}", level="ERROR")
                duration = PhaseCalculator.DEFAULT_DURATION_S

            # Démarrer l'animation
            self._start_animation_loop(banc_id, target_bar, label_time_left, duration, phase_step)

        except Exception as e:
            log(f"AnimationManager: Erreur démarrage animation phase {phase_step} pour {banc_id}: {e}", level="ERROR")
            self.active_timers.pop(banc_id, None)

    def finalize_previous_phase(self, banc_id):
        """
        Finalise l'animation de la phase précédente.
        Args:
            banc_id (str): Identifiant du banc
        """
        old_timer = self.active_timers.get(banc_id, {})
        widgets = self.app.banc_widgets.get(banc_id)

        if not old_timer or not widgets:
            return

        phase_bar = widgets.get("progress_bar_phase")
        if not phase_bar:
            return

        # Annuler le timer précédent
        after_id = old_timer.get("after_id")
        if after_id:
            try:
                self.app.after_cancel(after_id)
            except ValueError:
                log(f"AnimationManager: Timer déjà expiré pour {banc_id}", level="DEBUG")
            except Exception as e:
                log(f"AnimationManager: Erreur annulation timer pour {banc_id}: {e}", level="ERROR")

            old_timer["cancel"] = True

        # Finaliser la barre de progression de la phase précédente
        self._finalize_progress_bar(phase_bar, old_timer.get("phase"))

    def _get_target_progress_bar(self, phase_bar, phase_step):
        """
        Retourne la barre de progression cible pour une phase donnée.
        Args:
            phase_bar: Widget MultiColorProgress
            phase_step (int): Numéro de la phase
        Returns:
            CTkProgressBar: Barre de progression cible ou None
        """
        target_bars = {
            1: getattr(phase_bar, 'progress_ri', None),
            2: getattr(phase_bar, 'progress_phase2', None),
            3: getattr(phase_bar, 'progress_capa', None),
            4: getattr(phase_bar, 'progress_charge', None)
        }

        target_bar = target_bars.get(phase_step)
        if target_bar:
            target_bar.set(0.0)  # Réinitialiser à 0%

        return target_bar

    def _calculate_phase_duration(self, widgets, phase_step):
        """
        Calcule la durée de la phase en utilisant PhaseCalculator.
        Args:
            widgets (dict): Widgets du banc
            phase_step (int): Numéro de la phase
        Returns:
            int: Durée en secondes
        """
        # Récupération des données nécessaires
        voltage_str = widgets["tension"].cget("text").replace(",", ".")
        soc_batterie_test = widgets.get("last_soc", 0.0)
        soc_nourrice_moyen = widgets.get("last_avg_nurse_soc", 0.0)

        # Calcul via PhaseCalculator
        return PhaseCalculator.calculate_phase_duration(phase_step, voltage_str, soc_batterie_test, soc_nourrice_moyen)

    def _start_animation_loop(self, banc_id, target_bar, label_time_left, duration, phase_step):
        """
        Démarre la boucle d'animation récursive.
        Args:
            banc_id (str): Identifiant du banc
            target_bar: Barre de progression cible
            label_time_left: Label d'affichage du temps restant
            duration (int): Durée totale en secondes
            phase_step (int): Numéro de la phase
        """
        start_time = time.time()

        def update():
            try:
                # Vérifier si l'animation a été annulée
                current_timer = self.active_timers.get(banc_id, {})
                if current_timer.get("cancel", False):
                    log(f"AnimationManager: Animation annulée pour {banc_id} phase {phase_step}", level="DEBUG")
                    return

                # Calculer le progrès
                elapsed = time.time() - start_time
                progress = min(elapsed / duration, 1.0) if duration > 0 else 1.0
                remaining = max(int(duration - elapsed), 0)

                # Mettre à jour l'interface
                self._update_ui_elements(label_time_left, target_bar, remaining, progress)

                # Continuer l'animation si pas terminée
                if progress < 1.0:
                    if banc_id in self.active_timers:
                        after_id = self.app.after(self.ANIMATION_INTERVAL_MS, update)
                        self.active_timers[banc_id]["after_id"] = after_id
                else:
                    # Animation terminée
                    if label_time_left:
                        label_time_left.configure(text="00:00:00")
                    log(f"AnimationManager: Phase {phase_step} animation terminée pour {banc_id}", level="INFO")

            except Exception as e:
                log(f"AnimationManager: Erreur update animation phase {phase_step} pour {banc_id}: {e}", level="ERROR")
                if label_time_left:
                    try:
                        label_time_left.configure(text="ERREUR")
                    except:
                        pass
                # Marquer comme annulé
                if banc_id in self.active_timers:
                    self.active_timers[banc_id]["cancel"] = True

        # Démarrer la première mise à jour
        update()

    def _update_ui_elements(self, label_time_left, target_bar, remaining_seconds, progress):
        """
        Met à jour les éléments de l'interface (temps et barre de progression).
        Args:
            label_time_left: Label du temps restant
            target_bar: Barre de progression
            remaining_seconds (int): Secondes restantes
            progress (float): Progrès de 0.0 à 1.0
        """
        # Mise à jour du temps restant
        if label_time_left:
            h, m_rem = divmod(remaining_seconds, 3600)
            m, s = divmod(m_rem, 60)
            label_time_left.configure(text=f"{h:02d}:{m:02d}:{s:02d}")

        # Mise à jour de la barre de progression
        if target_bar:
            target_bar.set(progress)

    def _finalize_progress_bar(self, phase_bar, old_phase):
        """
        Finalise la barre de progression de la phase précédente à 100%.
        Args:
            phase_bar: Widget MultiColorProgress
            old_phase (int): Numéro de la phase précédente
        """
        if not old_phase:
            return

        target_bars = {
            1: getattr(phase_bar, 'progress_ri', None),
            2: getattr(phase_bar, 'progress_phase2', None),
            3: getattr(phase_bar, 'progress_capa', None),
            4: getattr(phase_bar, 'progress_charge', None)
        }

        target_bar = target_bars.get(old_phase)
        if target_bar:
            try:
                target_bar.set(1.0)
                log(f"AnimationManager: Phase {old_phase} finalisée à 100%", level="DEBUG")
            except Exception as e:
                log(f"AnimationManager: Erreur finalisation phase {old_phase}: {e}", level="ERROR")

    def cancel_all_animations(self, banc_id):
        """
        Annule toutes les animations pour un banc donné.
        Args:
            banc_id (str): Identifiant du banc
        """
        timer_info = self.active_timers.get(banc_id)
        if timer_info:
            after_id = timer_info.get("after_id")
            if after_id:
                try:
                    self.app.after_cancel(after_id)
                except ValueError:
                    pass
            timer_info["cancel"] = True
            self.active_timers.pop(banc_id, None)
            log(f"AnimationManager: Toutes animations annulées pour {banc_id}", level="DEBUG")
