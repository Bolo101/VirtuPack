"""
Shared dark theme for P2V Converter GUI suite
"""
import tkinter as tk
from tkinter import ttk

# ── Palette ───────────────────────────────────────────────
BG          = "#1e1e2e"   # fond principal
BG_CARD     = "#252535"   # cartes / LabelFrames
BG_INPUT    = "#2a2a3e"   # champs de saisie
ACCENT      = "#7c6af7"   # violet doux – accent primaire
ACCENT_DARK = "#5c4ed6"   # bouton primaire hover
SUCCESS     = "#4ade80"   # vert succès
WARNING     = "#fb923c"   # orange warning
ERROR       = "#f87171"   # rouge erreur
INFO        = "#60a5fa"   # bleu info
TEXT_PRIMARY   = "#e2e8f0"
TEXT_SECONDARY = "#94a3b8"
TEXT_MUTED     = "#64748b"
BORDER      = "#3d3d5c"
BORDER_FOCUS = "#7c6af7"

FONT_TITLE    = ("Segoe UI", 16, "bold")
FONT_SUBTITLE = ("Segoe UI", 10)
FONT_LABEL    = ("Segoe UI", 10, "bold")
FONT_NORMAL   = ("Segoe UI", 9)
FONT_SMALL    = ("Segoe UI", 8)
FONT_MONO     = ("Consolas", 9)
FONT_BTN_PRIMARY = ("Segoe UI", 10, "bold")


def apply_theme(root: tk.Misc) -> ttk.Style:
    """Apply the dark theme to the given root/toplevel and return the Style object."""
    root.configure(bg=BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # ── General ──────────────────────────────────────────
    style.configure(".",
        background=BG,
        foreground=TEXT_PRIMARY,
        font=FONT_NORMAL,
        borderwidth=0,
        relief="flat",
        focusthickness=0,
    )
    style.map(".", background=[("disabled", BG)])

    # ── Frame ─────────────────────────────────────────────
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=BG_CARD, relief="flat")

    # ── LabelFrame ────────────────────────────────────────
    style.configure("TLabelframe",
        background=BG_CARD,
        bordercolor=BORDER,
        relief="solid",
        borderwidth=1,
        padding=12,
    )
    style.configure("TLabelframe.Label",
        background=BG_CARD,
        foreground=ACCENT,
        font=("Segoe UI", 9, "bold"),
    )
    style.map("TLabelframe", bordercolor=[("focus", BORDER_FOCUS)])

    # ── Label ─────────────────────────────────────────────
    style.configure("TLabel", background=BG, foreground=TEXT_PRIMARY)
    style.configure("Card.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY)
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=FONT_SMALL)
    style.configure("Card.Muted.TLabel", background=BG_CARD, foreground=TEXT_MUTED, font=FONT_SMALL)
    style.configure("Success.TLabel", background=BG_CARD, foreground=SUCCESS, font=FONT_SMALL)
    style.configure("Warning.TLabel", background=BG_CARD, foreground=WARNING, font=FONT_SMALL)
    style.configure("Error.TLabel", background=BG_CARD, foreground=ERROR, font=FONT_SMALL)
    style.configure("Info.TLabel", background=BG_CARD, foreground=INFO, font=FONT_SMALL)
    style.configure("Title.TLabel", background=BG, foreground=TEXT_PRIMARY, font=FONT_TITLE)
    style.configure("Subtitle.TLabel", background=BG, foreground=TEXT_SECONDARY, font=FONT_SUBTITLE)

    # ── Button – standard ─────────────────────────────────
    style.configure("TButton",
        background=BG_INPUT,
        foreground=TEXT_PRIMARY,
        bordercolor=BORDER,
        borderwidth=1,
        relief="flat",
        padding=(10, 5),
        font=FONT_NORMAL,
    )
    style.map("TButton",
        background=[("active", BORDER), ("pressed", ACCENT_DARK), ("disabled", BG_CARD)],
        foreground=[("disabled", TEXT_MUTED)],
        bordercolor=[("focus", ACCENT)],
    )

    # ── Button – primary (accent) ──────────────────────────
    style.configure("Primary.TButton",
        background=ACCENT,
        foreground="#ffffff",
        bordercolor=ACCENT,
        borderwidth=0,
        relief="flat",
        padding=(14, 7),
        font=FONT_BTN_PRIMARY,
    )
    style.map("Primary.TButton",
        background=[("active", ACCENT_DARK), ("pressed", "#4a3ab8"), ("disabled", BG_CARD)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    # ── Button – danger ───────────────────────────────────
    style.configure("Danger.TButton",
        background="#5c2626",
        foreground=ERROR,
        bordercolor="#7a3030",
        borderwidth=1,
        relief="flat",
        padding=(10, 5),
        font=FONT_NORMAL,
    )
    style.map("Danger.TButton",
        background=[("active", "#7a3030"), ("pressed", "#9a4040")],
    )

    # ── Entry ─────────────────────────────────────────────
    style.configure("TEntry",
        fieldbackground=BG_INPUT,
        foreground=TEXT_PRIMARY,
        bordercolor=BORDER,
        insertcolor=TEXT_PRIMARY,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        relief="flat",
        borderwidth=1,
        padding=(6, 4),
    )
    style.map("TEntry",
        bordercolor=[("focus", BORDER_FOCUS)],
        fieldbackground=[("disabled", BG_CARD)],
        foreground=[("disabled", TEXT_MUTED)],
    )

    # ── Combobox ──────────────────────────────────────────
    style.configure("TCombobox",
        fieldbackground=BG_INPUT,
        foreground=TEXT_PRIMARY,
        background=BG_INPUT,
        bordercolor=BORDER,
        arrowcolor=TEXT_SECONDARY,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        relief="flat",
    )
    style.map("TCombobox",
        bordercolor=[("focus", BORDER_FOCUS)],
        fieldbackground=[("readonly", BG_INPUT)],
        foreground=[("disabled", TEXT_MUTED)],
    )
    root.option_add("*TCombobox*Listbox.background", BG_INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    # ── Scrollbar ─────────────────────────────────────────
    style.configure("TScrollbar",
        background=BG_INPUT,
        troughcolor=BG_CARD,
        bordercolor=BORDER,
        arrowcolor=TEXT_MUTED,
        relief="flat",
        arrowsize=12,
    )
    style.map("TScrollbar",
        background=[("active", BORDER), ("pressed", ACCENT)],
    )

    # ── Progressbar ───────────────────────────────────────
    style.configure("TProgressbar",
        troughcolor=BG_INPUT,
        background=ACCENT,
        bordercolor=BORDER,
        thickness=8,
    )

    # ── Radiobutton ───────────────────────────────────────
    style.configure("TRadiobutton",
        background=BG_CARD,
        foreground=TEXT_PRIMARY,
        focusthickness=0,
        indicatorcolor=ACCENT,
    )
    style.map("TRadiobutton",
        background=[("active", BG_CARD)],
        foreground=[("active", TEXT_PRIMARY)],
        indicatorcolor=[("selected", ACCENT), ("!selected", BORDER)],
    )

    # ── Checkbutton ───────────────────────────────────────
    style.configure("TCheckbutton",
        background=BG_CARD,
        foreground=TEXT_PRIMARY,
        focusthickness=0,
    )
    style.map("TCheckbutton",
        background=[("active", BG_CARD)],
        indicatorcolor=[("selected", ACCENT), ("!selected", BORDER)],
    )

    # ── Separator ─────────────────────────────────────────
    style.configure("TSeparator", background=BORDER)

    # ── Notebook (tabs) ───────────────────────────────────
    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab",
        background=BG_CARD,
        foreground=TEXT_SECONDARY,
        padding=(12, 6),
        borderwidth=0,
    )
    style.map("TNotebook.Tab",
        background=[("selected", BG), ("active", BORDER)],
        foreground=[("selected", TEXT_PRIMARY)],
    )

    return style


def style_text_widget(widget: tk.Text):
    """Apply dark theme to a tk.Text widget (not covered by ttk.Style)."""
    widget.configure(
        bg=BG_INPUT,
        fg=TEXT_PRIMARY,
        insertbackground=TEXT_PRIMARY,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        relief="flat",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER_FOCUS,
        font=FONT_MONO,
    )


def style_listbox(widget: tk.Listbox):
    """Apply dark theme to a tk.Listbox widget."""
    widget.configure(
        bg=BG_INPUT,
        fg=TEXT_PRIMARY,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        activestyle="none",
        relief="flat",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER_FOCUS,
        font=FONT_MONO,
    )


def style_canvas(widget: tk.Canvas):
    """Apply dark background to a tk.Canvas (used for scrollable frames)."""
    widget.configure(bg=BG_CARD, highlightthickness=0)


# ── Notification bar ─────────────────────────────────────────────────────────

# Couleurs de fond par niveau
_NOTIF_BG = {
    "info":    "#1e3a5f",
    "success": "#14432a",
    "warning": "#4a2e00",
    "error":   "#4a1515",
}
_NOTIF_FG = {
    "info":    INFO,
    "success": SUCCESS,
    "warning": WARNING,
    "error":   ERROR,
}
_NOTIF_ICON = {
    "info":    "ℹ",
    "success": "✔",
    "warning": "⚠",
    "error":   "✖",
}


class NotificationBar(tk.Frame):
    """
    Barre de notification inline à placer en bas (ou haut) d'une fenêtre.
    Utilisation :
        bar = NotificationBar(parent)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        bar.show("Message d'erreur", level="error")
        bar.show("Succès !", level="success")   # s'efface après 5 s
        bar.show("Voulez-vous continuer ?", level="warning",
                 confirm=True, on_yes=ma_fonction, on_no=autre_fonction)
    """

    AUTO_HIDE_MS = 6000  # 6 secondes avant disparition automatique

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, height=0, **kwargs)
        self._after_id = None
        self._visible = False

        # Ligne de séparation
        self._sep = tk.Frame(self, bg=BORDER, height=1)
        self._sep.pack(fill=tk.X, side=tk.TOP)

        # Contenu
        self._inner = tk.Frame(self, bg=BG, padx=12, pady=6)
        self._inner.pack(fill=tk.X)

        self._icon_lbl = tk.Label(self._inner, text="", bg=BG,
                                  font=("Segoe UI", 11), width=2)
        self._icon_lbl.pack(side=tk.LEFT)

        self._msg_lbl = tk.Label(self._inner, text="", bg=BG,
                                 fg=TEXT_PRIMARY, font=FONT_NORMAL,
                                 anchor="w", justify="left", wraplength=700)
        self._msg_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 12))

        # Boutons de confirmation (masqués par défaut)
        self._btn_frame = tk.Frame(self._inner, bg=BG)
        self._btn_yes = tk.Button(self._btn_frame, text="Oui",
                                  bg=ACCENT, fg="#ffffff",
                                  activebackground=ACCENT_DARK,
                                  relief="flat", padx=14, pady=3,
                                  font=("Segoe UI", 9, "bold"),
                                  cursor="hand2", bd=0)
        self._btn_yes.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_no = tk.Button(self._btn_frame, text="Non",
                                 bg=BG_INPUT, fg=TEXT_PRIMARY,
                                 activebackground=BORDER,
                                 relief="flat", padx=14, pady=3,
                                 font=("Segoe UI", 9),
                                 cursor="hand2", bd=0)
        self._btn_no.pack(side=tk.LEFT)

        # Bouton fermer
        self._close_btn = tk.Button(self._inner, text="✕",
                                    bg=BG, fg=TEXT_MUTED,
                                    activebackground=BG,
                                    relief="flat", bd=0, padx=4,
                                    font=("Segoe UI", 9),
                                    cursor="hand2",
                                    command=self.hide)
        self._close_btn.pack(side=tk.RIGHT)

        # Masquer au départ (grid_remove préserve la config, évite le conflit pack/grid)
        self.grid(row=0, column=0, sticky="ew")
        self.grid_remove()

    def show(self, message: str, level: str = "info",
             confirm: bool = False,
             on_yes=None, on_no=None,
             auto_hide: bool = True):
        """
        Affiche la notification.
        - level    : "info" | "success" | "warning" | "error"
        - confirm  : True → affiche les boutons Oui / Non
        - on_yes   : callback si l'utilisateur clique Oui
        - on_no    : callback si l'utilisateur clique Non
        - auto_hide: False pour les confirmations (attend l'action)
        """
        # Annuler l'auto-masquage précédent
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

        bg  = _NOTIF_BG.get(level, BG_INPUT)
        fg  = _NOTIF_FG.get(level, TEXT_PRIMARY)
        icon = _NOTIF_ICON.get(level, "•")

        self.configure(bg=bg)
        self._sep.configure(bg=_NOTIF_FG.get(level, BORDER))
        self._inner.configure(bg=bg)
        self._icon_lbl.configure(text=icon, fg=fg, bg=bg)
        self._msg_lbl.configure(text=message, fg=fg, bg=bg)
        self._close_btn.configure(bg=bg, activebackground=bg)

        if confirm:
            self._btn_frame.configure(bg=bg)
            self._btn_yes.configure(bg=ACCENT)
            self._btn_no.configure(bg=BG_INPUT)
            # Reconfigurer les callbacks
            self._btn_yes.configure(command=lambda: self._on_confirm(on_yes))
            self._btn_no.configure(command=lambda: self._on_confirm(on_no))
            self._btn_frame.pack(side=tk.RIGHT, padx=(0, 8))
        else:
            self._btn_frame.pack_forget()

        # Afficher la barre (grid_restore, compatible avec le conteneur géré en grid)
        self.grid()
        self._visible = True

        if auto_hide and not confirm:
            self._after_id = self.after(self.AUTO_HIDE_MS, self.hide)

    def hide(self):
        """Masque la barre de notification."""
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.grid_remove()
        self._visible = False

    def _on_confirm(self, callback):
        self.hide()
        if callable(callback):
            callback()
