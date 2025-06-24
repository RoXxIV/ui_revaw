# -*- coding: utf-8 -*-
import tkinter as tk
import customtkinter as ctk
from src.ui.utils import log


def update_soc_canvas(canvas, soc):
    """Dessine ou met à jour la jauge semi-circulaire du SOC sur un widget Canvas.
    Efface le contenu précédent du canvas, calcule les dimensions appropriées
    en fonction de la taille du canvas, puis dessine :
    - Un arc de fond gris.
    - Un arc de couleur (vert) dont la longueur est proportionnelle à la valeur du SOC.
    - Le texte du pourcentage SOC au centre.
    - Le label "SOC" sous le pourcentage.
    Gère les cas où le canvas serait trop petit pour dessiner.
    Args:
        canvas (tk.Canvas): Le widget Canvas Tkinter cible sur lequel dessiner.
        soc (float | int): La valeur du State of Charge (en pourcentage, 0 à 100)
                        à représenter sur la jauge.
    Returns:
        None
    """
    canvas.delete("all")  # Efface le contenu précédent
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    thickness = 25
    radius = min(width, height) // 2 - (thickness // 2)
    if radius < 1:
        return

    x0 = (width // 2) - radius
    x1 = (width // 2) + radius
    y1 = height
    y0 = y1 - (2 * radius)
    # Arc gris de fond
    canvas.create_arc(x0, y0, x1, y1, start=180, extent=-180, style=tk.ARC, outline="gray", width=thickness)
    # Arc vert correspondant au SOC
    fill_extent = -180 * (soc / 100.0)
    canvas.create_arc(x0, y0, x1, y1, start=180, extent=fill_extent, style=tk.ARC, outline="#6EC207", width=thickness)
    # Texte au centre
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    canvas.create_text(cx, cy, text=f"{soc:.0f}%", fill="white", font=("Arial", 20, "bold"))
    canvas.create_text(cx, cy + 40, text="SOC", fill="white", font=("Arial", 15, "bold"))


def _create_info_widget(parent, row, column, sticky, static_text, initial_dynamic_text="0.0", dynamic_widget_width=150):
    """
    Crée un widget d'information (titre + valeur) dans une frame.
    Ce widget est conçu pour afficher une information clé (ex: Tension) avec sa valeur
    actuelle. Il est placé sur la grille du widget parent.
    Args:
        parent: Le widget parent (généralement une CTkFrame) où placer ce cadre.
        row: La ligne dans la grille du parent pour ce widget.
        column: La colonne dans la grille du parent pour ce widget.
        sticky: L'alignement dans la cellule de la grille (ex: "w", "e", "nsew").
        static_text: Le texte du label titre (ex: "Tension (V)").
        initial_dynamic_text: Le texte initial du label de valeur dynamique.
        dynamic_widget_width: La largeur fixe pour le label dynamique de valeur.
    Returns:
        customtkinter.CTkLabel: Le widget CTkLabel dynamique (valeur), pour
                                pouvoir le mettre à jour ultérieurement.
    """
    frame = ctk.CTkFrame(parent, border_width=2)
    frame.grid(row=row, column=column, padx=5, pady=5, sticky=sticky)

    label_static = ctk.CTkLabel(frame, text=static_text, font=("Helvetica", 15, "bold"))
    label_static.pack(side="top", pady=0)

    label_dynamic = ctk.CTkLabel(
        frame, text=initial_dynamic_text, font=("Helvetica", 30, "bold"), width=dynamic_widget_width)
    label_dynamic.pack(side="top", pady=0)
    return label_dynamic


def create_block_labels(parent_frame, banc_text="Banc", serial_text="Serial", current_step=None, icons=None):
    """
    Construit et retourne tous les widgets pour l'interface d'un seul banc de test.
    Configure la grille du `parent_frame`, crée tous les labels statiques et dynamiques
    (via `_create_info_widget`), le Canvas SOC, les barres de progression (nourrice et phases),
    le label de sécurité caché, et place tous les éléments.
    Retourne un dictionnaire contenant les références aux widgets qui
    doivent être mis à jour dynamiquement par l'application principale.
    Args:
        parent_frame (customtkinter.CTkFrame): Le cadre parent où ce bloc sera dessiné.
        banc_text (str, optional): Le nom initial du banc. Par défaut "Banc".
        serial_text (str, optional): Le numéro de série initial. Par défaut "Serial".
        current_step (int | None, optional): L'étape initiale du test. Par défaut None.
    Returns:
        dict: Un dictionnaire où les clés sont des noms descriptifs (ex: "tension",
              "soc_canvas", "progress_bar_phase") et les valeurs sont les instances
              des widgets correspondants, nécessaires pour les mises à jour ultérieures.
    """
    if icons is None:
        icons = {}
    widgets = {}  # Dictionnaire pour stocker les widgets
    # Configuration de la grille interne, définit comment les lignes/colonnes s'étirent
    parent_frame.rowconfigure((1, 2, 3), weight=1)  # Lignes de la jauge
    parent_frame.rowconfigure((0, 4, 5, 6), weight=0)  # Les autres lignes ne s'étirent pas
    parent_frame.columnconfigure((0, 1, 2), weight=1)  # 3 colonnes de même poids
    parent_frame.configure(border_color="white", border_width=1, corner_radius=5)
    # Référence au cadre parent pour modifier la couleur de la bordure ou autre si besoin
    widgets["parent_frame"] = parent_frame
    # LIGNE 0 : Banc - Serial Mis à jour dans init_banc_status() et handle_prompt()
    frame_banc_serial = ctk.CTkFrame(parent_frame, border_width=2)
    frame_banc_serial.grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")
    label_banc_serial = ctk.CTkLabel(
        frame_banc_serial, text=f"{banc_text} - {serial_text}", font=("Helvetica", 15, "bold"))
    label_banc_serial.pack(expand=True, fill="both")
    widgets["banc"] = label_banc_serial
    # LIGNE 1 : Balance et Temp Mis à jour dans update_banc_data()
    widgets["balance"] = _create_info_widget(parent_frame, row=1, column=0, sticky="w", static_text="Equilibrage (mv)")
    widgets["temp"] = _create_info_widget(parent_frame, row=1, column=2, sticky="e", static_text="Temp (C°)")
    # LIGNE 2 : Intensité et Tension Mis à jour dans update_banc_data()
    widgets["intensity"] = _create_info_widget(parent_frame, row=2, column=0, sticky="w", static_text="Intensité (A)")
    widgets["tension"] = _create_info_widget(parent_frame, row=2, column=2, sticky="e", static_text="Tension (V)")
    #  LIGNE 3 : Capacity et Energy Mis à jour dans update_banc_data()
    widgets["discharge_energy"] = _create_info_widget(
        parent_frame, row=3, column=0, sticky="w", static_text="Energy (Kwh)")
    widgets["discharge_capacity"] = _create_info_widget(
        parent_frame, row=3, column=2, sticky="e", static_text="Capacity (ah)")
    # CANVAS SOC (au centre) Mis à jour dans update_soc_canvas()
    soc_canvas = ctk.CTkCanvas(parent_frame, bg="#2b2b2b", highlightthickness=0)
    # row=1, column=1 avec rowspan=3 => le canvas s'étend de la ligne 1 à 3
    soc_canvas.grid(row=1, column=1, rowspan=3, padx=5, pady=(20, 0), sticky="sew")
    widgets["soc_canvas"] = soc_canvas
    # --- BLOC CENTRAL (LIGNE 4) : Icônes et Barre de Progression des Nourrices ---

    # 1. Créer un cadre principal pour tout le bloc central
    frame_nurses_wrapper = ctk.CTkFrame(parent_frame, fg_color="transparent")
    frame_nurses_wrapper.grid(row=4, column=1, pady=5, sticky="ew")

    # 2. Créer un sous-cadre juste pour les icônes, pour les centrer horizontalement
    frame_icons = ctk.CTkFrame(frame_nurses_wrapper, fg_color="transparent")
    frame_icons.pack(pady=(0, 5))  # Un peu d'espace avant la barre de progression

    # 3. Placer les icônes CÔTE À CÔTE dans leur cadre

    label_icon_nurses = ctk.CTkLabel(frame_icons, text="", image=icons.get("nurses_off"))
    label_icon_nurses.pack(side="left", padx=10)
    widgets["icon_nurses"] = label_icon_nurses
    label_icon_charger = ctk.CTkLabel(frame_icons, text="", image=icons.get("charger_off"))
    label_icon_charger.pack(side="left", padx=10)
    widgets["icon_charger"] = label_icon_charger

    # 4. Placer la barre de progression SOUS le cadre des icônes
    progress_bar_nurse = ctk.CTkProgressBar(frame_nurses_wrapper, width=200, progress_color="#c1c1c1")
    progress_bar_nurse.pack(expand=True)
    widgets["progress_bar_nurse"] = progress_bar_nurse
    # LIGNE 4 : Security Ce widget est caché, brièvement quand un message /security est reçu
    label_security = ctk.CTkLabel(
        master=parent_frame,
        text="",
        font=("Helvetica", 40, "bold"),
        fg_color="red",
        text_color="white",
        corner_radius=10,
        width=450,
        height=120,
        wraplength=320)
    label_security.place(relx=0.5, rely=0.5, anchor="center")
    label_security.lower()  # Caché au départ
    widgets["label_security"] = label_security
    # ---------------- LIGNE 5 : Ri, Phase, time left & Diffusion ----------------
    widgets["ri"] = _create_info_widget(
        parent_frame, row=5, column=0, sticky="w", static_text="Ri", initial_dynamic_text="0.00")
    frame_time_left = ctk.CTkFrame(parent_frame, border_width=2)
    frame_time_left.grid(row=5, column=1, padx=5, pady=5, sticky="nsew")
    label_phase_dynamic = ctk.CTkLabel(frame_time_left, text="-/4", font=("Helvetica", 15, "bold"))
    label_phase_dynamic.pack(side="top", pady=0)
    label_time_dynamic = ctk.CTkLabel(frame_time_left, text="00h00min", font=("Helvetica", 30, "bold"), width=150)
    label_time_dynamic.pack(side="top")
    widgets["time_left"] = label_time_dynamic  # géré dynamiquement via animate_phase_segment()
    widgets["phase"] = label_phase_dynamic
    widgets["diffusion"] = _create_info_widget(
        parent_frame, row=5, column=2, sticky="e", static_text="Diffusion", initial_dynamic_text="0.00")
    # LIGNE 6 : Barre de progression utilises la classe MultiColorProgress avec 4 segments (RI, CHARGE1, CAPA, CHARGE2).
    frame_progress_wrapper = ctk.CTkFrame(parent_frame, fg_color="transparent")
    frame_progress_wrapper.grid(row=6, column=0, columnspan=3, sticky="n", pady=5)
    progress_frame = MultiColorProgress(frame_progress_wrapper, width=600, height=15)
    progress_frame.pack(pady=5)
    #mise à jour dynamiquement par animate_phase_segment(), appelée après chaque message /step
    widgets["progress_bar_phase"] = progress_frame
    # On force l'affichage du SOC à 0% après 300ms, le temps que le canvas soit dimensionné
    #parent_frame.after(300, lambda: update_soc_canvas(soc_canvas, 0))
    #  CURRENT_STEP C’est la phase actuelle du test en cours. Sert à afficher phase 1/5, phase 2/5, etc.
    widgets["current_step"] = current_step if current_step is not None else 0
    return widgets


def get_phase_message(step):
    """Retourne le message de phase correspondant à l'étape actuelle."""
    return f"phase {step}/5" if step in [1, 2, 3, 4, 5] else "0/5"


def _get_temp_color(temperature):
    """Retourne la couleur associée à la température."""
    TEMP_THRESHOLD_OK_LOW = 10
    TEMP_THRESHOLD_OK_HIGH = 40
    TEMP_THRESHOLD_WARN_LOW = 5
    TEMP_THRESHOLD_WARN_HIGH = 50
    COLOR_OK = "#6EC207"
    COLOR_WARN = "yellow"
    COLOR_DANGER = "red"
    if TEMP_THRESHOLD_OK_LOW <= temperature <= TEMP_THRESHOLD_OK_HIGH:
        return COLOR_OK  # Vert
    elif TEMP_THRESHOLD_WARN_LOW <= temperature < TEMP_THRESHOLD_OK_LOW or TEMP_THRESHOLD_OK_HIGH < temperature <= TEMP_THRESHOLD_WARN_HIGH:
        return COLOR_WARN  # Jaune
    else:
        return COLOR_DANGER  # Rouge


def _get_balance_color(balance):
    """Retourne la couleur associée à l'équilibrage."""
    BALANCE_THRESHOLD_DANGER = 60
    BALANCE_THRESHOLD_WARN = 40
    COLOR_OK = "#6EC207"  # Déjà définie ?
    COLOR_WARN = "yellow"
    COLOR_DANGER = "red"
    if balance > BALANCE_THRESHOLD_DANGER:
        return COLOR_DANGER  # Rouge
    elif balance > BALANCE_THRESHOLD_WARN:
        return COLOR_WARN  # Jaune
    else:
        return COLOR_OK  # Vert


def _get_energy_color(discharge_energy, current_step):
    """Retourne la couleur associée à l'énergie déchargée (selon l'étape)."""
    RELEVANT_STEPS = [2, 3]  # Pertinent seulement pendant charge/décharge principale
    ENERGY_TARGET_OK = 13
    COLOR_OK = "#6EC207"
    COLOR_DANGER = "red"
    COLOR_DEFAULT = "white"
    if current_step in RELEVANT_STEPS:
        if discharge_energy >= ENERGY_TARGET_OK:
            return COLOR_OK  # Vert
        else:
            return COLOR_DANGER  # Rouge
    else:
        return COLOR_DEFAULT


def _get_capacity_color(discharge_capacity, current_step):
    """Retourne la couleur associée à la capacité déchargée (selon l'étape)."""
    RELEVANT_STEPS = [2, 3]  # Pertinent seulement pendant charge/décharge principale
    CAPACITY_TARGET_OK = 271
    COLOR_OK = "#6EC207"
    COLOR_DANGER = "red"
    COLOR_DEFAULT = "white"
    if current_step in RELEVANT_STEPS:
        if discharge_capacity >= CAPACITY_TARGET_OK:
            return COLOR_OK  # Vert
        else:
            return COLOR_DANGER  # Rouge
    else:
        return COLOR_DEFAULT


class MultiColorProgress(ctk.CTkFrame):
    """
    Widget personnalisé composé de 4 segments de barre de progression
    horizontaux pour représenter les 4 phases principales du test.
    Hérite de CTkFrame et contient 4 CTkProgressBar.
    Segments (Largeur % - Couleur):
      - Phase 1 (RI):      10% - bleu
      - Phase 2 (CHARGE):  30% - vert
      - Phase 3 (CAPA):    40% - orange
      - Phase 4 (CHARGE_FINALE): 20% - violet
    """
    SEGMENT_CONFIG = [
        {
            "key": "ri",
            "ratio": 0.10,
            "color": "blue"
        },
        {
            "key": "phase2",
            "ratio": 0.30,
            "color": "green"
        },
        {
            "key": "capa",
            "ratio": 0.40,
            "color": "orange"
        },
        {
            "key": "charge",
            "ratio": 0.20,
            "color": "#ad02d8"
        }  # Violet
    ]
    DEFAULT_WIDTH = 600  # Valeur par défaut si non spécifiée
    DEFAULT_HEIGHT = 15
    CORNER_RADIUS = 0
    PADDING = 0

    def __init__(self, master, width=400, height=15, **kwargs):
        """
        Initialise le cadre MultiColorProgress et crée les segments de barre.
        Args:
            master: Le widget parent.
            width (int, optional): Largeur totale du widget. Défaut 600.
            height (int, optional): Hauteur du widget. Défaut 15.
            **kwargs: Arguments additionnels passés à CTkFrame.
        """
        super().__init__(master, **kwargs)
        self.configure(width=width, height=height)
        # Création des 4 segments
        for config in self.SEGMENT_CONFIG:
            segment_width = int(width * config["ratio"])
            progress_bar = ctk.CTkProgressBar(
                master=self,  # Le maître est l'instance de MultiColorProgress elle-même
                orientation="horizontal",
                progress_color=config["color"],
                width=segment_width,
                height=height,
                corner_radius=self.CORNER_RADIUS)
            progress_bar.pack(side="left", padx=self.PADDING, pady=self.PADDING)
            # Stocke la référence à la barre de progression comme attribut d'instance
            # ex: self.progress_ri, self.progress_phase2, etc.
            setattr(self, f"progress_{config['key']}", progress_bar)
            # Initialise la valeur à 0
            progress_bar.set(0)

    def reset(self):
        """Réinitialise la valeur de tous les segments de la barre à 0."""
        log("MultiColorProgress: Appel de reset()", level="DEBUG")
        try:
            for config in self.SEGMENT_CONFIG:
                # Récupère la référence à la barre (ex: self.progress_ri)
                progress_bar = getattr(self, f"progress_{config['key']}")
                progress_bar.set(0)
            log("MultiColorProgress: reset() terminé.", level="DEBUG")
        except Exception as e:
            log(f"MultiColorProgress: ERREUR dans reset(): {e}", level="ERROR")
