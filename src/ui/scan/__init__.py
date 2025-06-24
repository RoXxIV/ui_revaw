# -*- coding: utf-8 -*-
"""
Ce module fournit une interface simplifiée pour la gestion des scans
via la classe ScanManager, qui encapsule toute la logique de traitement
des codes-barres et des commandes spéciales.
"""

from .scan_manager import ScanManager

# Expose la classe principale du module
__all__ = ['ScanManager']
