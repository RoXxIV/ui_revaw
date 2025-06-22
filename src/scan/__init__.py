# src/scan/__init__.py
"""
Module de gestion des scans pour le système de test de batteries.

Ce module fournit une interface simplifiée pour la gestion des scans
via la classe ScanManager, qui encapsule toute la logique de traitement
des codes-barres et des commandes spéciales.
"""

from .scan_manager import ScanManager

# Expose la classe principale du module
__all__ = ['ScanManager']

# Informations du module
__version__ = '1.0.0'
__author__ = 'Evan Hermier'
