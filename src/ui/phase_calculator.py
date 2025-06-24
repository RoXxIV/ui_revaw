# -*- coding: utf-8 -*-
"""
Calculateur de durées des phases de test de batteries.

Ce module centralise tous les calculs de durée pour les différentes phases
du test de batteries, séparant ainsi la logique de calcul de l'interface utilisateur.
"""

from .data_operations import get_charge_duration
from .system_utils import log


class PhaseCalculator:
    """
    Classe responsable du calcul des durées des phases de test.
    
    Cette classe encapsule toute la logique de calcul des durées pour chaque phase,
    permettant une meilleure séparation des responsabilités et une maintenance plus facile.
    """

    # === CONSTANTES DE CALCUL ===
    PHASE4_NURSE_HIGH_SOC_THRESHOLD = 85.0
    PHASE4_NURSE_LOW_SOC_TARGET = 80.0
    PHASE4_NURSE_HIGH_FACTOR_MIN_PER_PCT = 2.88
    PHASE4_MAIN_BATT_LOW_SOC_REF = 10.0
    PHASE4_MAIN_BATT_LOW_FACTOR_MIN_PER_UNIT = 1.3
    PHASE4_MIN_DURATION_S = 5

    PHASE1_RI_DURATION_S = 200
    PHASE3_CAPA_FACTOR_MIN_PER_SOC_PCT = 1.35

    SECONDS_PER_MINUTE = 60
    DEFAULT_DURATION_S = 10000

    @classmethod
    def calculate_phase_duration(cls, phase_step, voltage_str, soc_batterie_test, soc_nourrice_moyen):
        """
        Calcule la durée estimée d'une phase de test.
        
        Args:
            phase_step (int): Numéro de la phase (1-4)
            voltage_str (str): Tension actuelle sous forme de chaîne
            soc_batterie_test (float): SOC de la batterie en test (0-100)
            soc_nourrice_moyen (float): SOC moyen des nourrices (0-100)
            
        Returns:
            int: Durée estimée en secondes
        """
        try:
            if phase_step == 1:
                return cls._calculate_phase1_duration()
            elif phase_step == 2:
                return cls._calculate_phase2_duration(voltage_str)
            elif phase_step == 3:
                return cls._calculate_phase3_duration(soc_batterie_test)
            elif phase_step == 4:
                return cls._calculate_phase4_duration(soc_batterie_test, soc_nourrice_moyen)
            else:
                log(f"PhaseCalculator: Phase invalide {phase_step}. Utilisation durée par défaut.", level="WARNING")
                return cls.DEFAULT_DURATION_S

        except Exception as e:
            log(f"PhaseCalculator: Erreur calcul phase {phase_step}: {e}. Utilisation durée par défaut.", level="ERROR")
            return cls.DEFAULT_DURATION_S

    @classmethod
    def _calculate_phase1_duration(cls):
        """
        Calcule la durée de la phase 1 (RI).
        
        Returns:
            int: Durée fixe en secondes
        """
        return cls.PHASE1_RI_DURATION_S

    @classmethod
    def _calculate_phase2_duration(cls, voltage_str):
        """
        Calcule la durée de la phase 2 (Charge) basée sur la tension.
        
        Args:
            voltage_str (str): Tension actuelle
            
        Returns:
            int: Durée estimée en secondes
        """
        try:
            # Utilise le profil de charge existant
            duration = get_charge_duration(voltage_str)
            return max(duration, 1)  # Assurer une durée minimale positive
        except Exception as e:
            log(f"PhaseCalculator: Erreur calcul phase 2 avec tension '{voltage_str}': {e}", level="ERROR")
            return cls.DEFAULT_DURATION_S

    @classmethod
    def _calculate_phase3_duration(cls, soc_batterie_test):
        """
        Calcule la durée de la phase 3 (Capacité) basée sur le SOC.
        
        Args:
            soc_batterie_test (float): SOC de la batterie en test
            
        Returns:
            int: Durée estimée en secondes
        """
        try:
            duration_seconds = int(soc_batterie_test * cls.PHASE3_CAPA_FACTOR_MIN_PER_SOC_PCT * cls.SECONDS_PER_MINUTE)
            return max(duration_seconds, 1)  # Assurer une durée minimale positive
        except Exception as e:
            log(f"PhaseCalculator: Erreur calcul phase 3 avec SOC {soc_batterie_test}: {e}", level="ERROR")
            return cls.DEFAULT_DURATION_S

    @classmethod
    def _calculate_phase4_duration(cls, soc_batterie_test, soc_nourrice_moyen):
        """
        Calcule la durée de la phase 4 (Charge finale) selon les conditions.
        
        Args:
            soc_batterie_test (float): SOC de la batterie en test
            soc_nourrice_moyen (float): SOC moyen des nourrices
            
        Returns:
            int: Durée estimée en secondes
        """
        try:
            duration_minutes = 0

            if soc_nourrice_moyen >= cls.PHASE4_NURSE_HIGH_SOC_THRESHOLD:
                # CAS 1: Nourrices SOC >= 85%
                duration_minutes = cls._calculate_phase4_high_nurse_soc(soc_nourrice_moyen)
            else:
                # CAS 2: Nourrices SOC < 85%
                duration_minutes = cls._calculate_phase4_low_nurse_soc(soc_batterie_test)

            # Conversion en secondes et application de la durée minimale
            duration_seconds = int(duration_minutes * cls.SECONDS_PER_MINUTE)
            final_duration = max(duration_seconds, cls.PHASE4_MIN_DURATION_S)

            log(f"PhaseCalculator: Phase 4 durée finale: {final_duration}s", level="DEBUG")
            return final_duration

        except Exception as e:
            log(f"PhaseCalculator: Erreur calcul phase 4: {e}", level="ERROR")
            return cls.DEFAULT_DURATION_S

    @classmethod
    def _calculate_phase4_high_nurse_soc(cls, soc_nourrice_moyen):
        """
        Calcule la durée phase 4 quand les nourrices ont un SOC élevé (>= 85%).
        
        Args:
            soc_nourrice_moyen (float): SOC moyen des nourrices
            
        Returns:
            float: Durée en minutes
        """
        soc_drop_needed = soc_nourrice_moyen - cls.PHASE4_NURSE_LOW_SOC_TARGET
        duration_minutes = soc_drop_needed * cls.PHASE4_NURSE_HIGH_FACTOR_MIN_PER_PCT

        log(
            f"PhaseCalculator: Phase 4 (nourrices >= {cls.PHASE4_NURSE_HIGH_SOC_THRESHOLD}%): "
            f"({soc_nourrice_moyen:.1f} - {cls.PHASE4_NURSE_LOW_SOC_TARGET}) * "
            f"{cls.PHASE4_NURSE_HIGH_FACTOR_MIN_PER_PCT} = {duration_minutes:.1f} min",
            level="DEBUG")

        return duration_minutes

    @classmethod
    def _calculate_phase4_low_nurse_soc(cls, soc_batterie_test):
        """
        Calcule la durée phase 4 quand les nourrices ont un SOC bas (< 85%).
        
        Args:
            soc_batterie_test (float): SOC de la batterie en test
            
        Returns:
            float: Durée en minutes
        """
        duration_minutes = (cls.PHASE4_MAIN_BATT_LOW_SOC_REF -
                            soc_batterie_test) * cls.PHASE4_MAIN_BATT_LOW_FACTOR_MIN_PER_UNIT

        log(
            f"PhaseCalculator: Phase 4 (nourrices < {cls.PHASE4_NURSE_HIGH_SOC_THRESHOLD}%): "
            f"({cls.PHASE4_MAIN_BATT_LOW_SOC_REF} - {soc_batterie_test:.1f}) * "
            f"{cls.PHASE4_MAIN_BATT_LOW_FACTOR_MIN_PER_UNIT} = {duration_minutes:.1f} min",
            level="DEBUG")

        # Vérification pour les durées négatives
        if duration_minutes < 0:
            log(
                f"PhaseCalculator: ATTENTION - Durée négative calculée ({duration_minutes:.1f} min) "
                f"car SOC batterie ({soc_batterie_test:.1f}%) > référence ({cls.PHASE4_MAIN_BATT_LOW_SOC_REF}). "
                f"Durée forcée à 0.",
                level="ERROR")
            duration_minutes = 0

        return duration_minutes
