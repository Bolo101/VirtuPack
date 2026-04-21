import tkinter as tk
from tkinter import ttk, messagebox
from QCow2CloneResizer import QCow2CloneResizer
import theme


class NewSizeDialog:
    """Dialog to enter new image size based on final partition layout"""

    def __init__(self, parent, final_layout_info, original_size, partition_changes):
        self.parent = parent
        self.final_layout_info = final_layout_info
        self.original_size = original_size
        self.partition_changes = partition_changes
        self.result = None

        try:
            self.dialog = tk.Toplevel(parent)
            self.dialog.title("Nouvelle taille d'image — Disposition finale des partitions")

            self.dialog.transient(parent)
            self.dialog.grab_set()
            self.dialog.focus_force()

            # Apply dark theme
            self._style = theme.apply_theme(self.dialog)

            screen_width  = self.dialog.winfo_screenwidth()
            screen_height = self.dialog.winfo_screenheight()

            dialog_width  = min(800, int(screen_width  * 0.6))
            dialog_height = min(720, int(screen_height * 0.8))

            x = (screen_width  - dialog_width)  // 2
            y = (screen_height - dialog_height) // 2
            self.dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
            self.dialog.resizable(True, True)
            self.dialog.minsize(600, 520)
            self.dialog.update_idletasks()

            self.setup_ui()

            self.dialog.protocol("WM_DELETE_WINDOW", self.skip_cloning)

            try:
                self.dialog.lift()
                self.dialog.attributes("-topmost", True)
                self.dialog.after_idle(lambda: self.dialog.attributes("-topmost", False))
                self.dialog.wait_window()
            except tk.TclError as e:
                print(f"Dialog wait TCL error: {e}")
                self.result = None
            except AttributeError as e:
                print(f"Dialog attribute error during wait: {e}")
                self.result = None

        except (tk.TclError, TypeError, AttributeError) as e:
            print(f"Error during dialog initialization: {e}")
            self.result = None

    # ─────────────────────────────────────────────────────────
    def setup_ui(self):
        """Setup dialog UI with scrollable content"""
        try:
            C = theme  # alias

            # ── Root background ───────────────────────────
            self.dialog.configure(bg=C.BG)

            # ── Outer container ───────────────────────────
            main_container = ttk.Frame(self.dialog, style="TFrame")
            main_container.pack(fill="both", expand=True, padx=14, pady=14)

            # ── Scrollable area ───────────────────────────
            canvas = tk.Canvas(main_container)
            theme.style_canvas(canvas)
            scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas, style="TFrame")

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set, bg=C.BG, highlightthickness=0)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            def _on_mousewheel(event):
                try:
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except (AttributeError, ZeroDivisionError, TypeError):
                    pass

            canvas.bind_all("<MouseWheel>", _on_mousewheel)

            content = ttk.Frame(scrollable_frame, style="TFrame", padding=(8, 8, 8, 8))
            content.pack(fill="both", expand=True)

            # ── Header ────────────────────────────────────
            header = ttk.Frame(content, style="TFrame")
            header.pack(fill="x", pady=(0, 18))

            ttk.Label(header,
                      text="Créer une nouvelle image",
                      style="Title.TLabel"
                      ).pack(anchor="w")
            ttk.Label(header,
                      text="Sélectionnez la taille finale de l'image QCOW2 optimisée",
                      style="Subtitle.TLabel"
                      ).pack(anchor="w", pady=(2, 0))

            # ── Divider ───────────────────────────────────
            ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(0, 18))

            # ── GParted Changes card ──────────────────────
            chg = ttk.LabelFrame(content, text="Modifications des partitions GParted", style="TLabelframe")
            chg.pack(fill="x", pady=(0, 12))

            chg_text = "Opérations GParted effectuées avec succès.\n\n"
            chg_text += f"Modifications des partitions : {self.partition_changes}\n"
            if self.final_layout_info.get("partitions"):
                chg_text += "\nDisposition finale des partitions :\n"
                for p in self.final_layout_info["partitions"]:
                    chg_text += (
                        f"  Partition {p['number']} :  "
                        f"{p['start']} → {p['end']}  ({p['size']})\n"
                    )

            lbl_chg = ttk.Label(chg, text=chg_text, justify="left",
                                 font=C.FONT_NORMAL, style="Card.TLabel")
            lbl_chg.pack(anchor="w")

            # ── Size Requirements card ────────────────────
            req = ttk.LabelFrame(content, text="Exigences de taille", style="TLabelframe")
            req.pack(fill="x", pady=(0, 12))

            last_end    = self.final_layout_info["last_partition_end_bytes"]
            min_size    = self.final_layout_info["required_minimum_bytes"]

            grid = ttk.Frame(req, style="Card.TFrame")
            grid.pack(fill="x")

            rows = [
                ("Taille originale de l'image",
                 QCow2CloneResizer.format_size(self.original_size), "Card.TLabel"),
                ("Fin de la dernière partition",
                 QCow2CloneResizer.format_size(last_end), "Card.TLabel"),
                ("Nouvelle taille requise (+ tampon 200 Mo)",
                 QCow2CloneResizer.format_size(min_size), "Card.TLabel"),
            ]
            for r, (lbl, val, sty) in enumerate(rows):
                ttk.Label(grid, text=lbl, style="Card.Muted.TLabel").grid(
                    row=r, column=0, sticky="w", pady=2)
                ttk.Label(grid, text=val, style=sty, font=C.FONT_NORMAL).grid(
                    row=r, column=1, sticky="w", padx=(20, 0), pady=2)

            # Savings / extra space
            delta_frame = ttk.Frame(req, style="Card.TFrame")
            delta_frame.pack(fill="x", pady=(8, 0))
            if min_size < self.original_size:
                saved = self.original_size - min_size
                ttk.Label(delta_frame,
                          text=f"Espace économisé : {QCow2CloneResizer.format_size(saved)} "
                               f"({saved / self.original_size * 100:.1f}% de réduction)",
                          style="Success.TLabel"
                          ).pack(anchor="w")
            elif min_size > self.original_size:
                extra = min_size - self.original_size
                ttk.Label(delta_frame,
                          text=f"Espace supplémentaire requis : {QCow2CloneResizer.format_size(extra)}",
                          style="Warning.TLabel"
                          ).pack(anchor="w")
            else:
                ttk.Label(delta_frame,
                          text="Même espace requis que l'original",
                          style="Info.TLabel"
                          ).pack(anchor="w")

            # ── Size selection card ───────────────────────
            sel = ttk.LabelFrame(content, text="Sélection de la nouvelle taille", style="TLabelframe")
            sel.pack(fill="x", pady=(0, 12))

            self.choice = tk.StringVar(value="calculated")

            # Option 1 – calculated (recommended)
            row1 = ttk.Frame(sel, style="Card.TFrame")
            row1.pack(fill="x", pady=4)
            ttk.Radiobutton(
                row1,
                text=f"Utiliser la taille calculée : {QCow2CloneResizer.format_size(min_size)}",
                variable=self.choice,
                value="calculated",
                style="TRadiobutton",
            ).pack(side="left")
            ttk.Label(row1, text="RECOMMANDÉ", style="Success.TLabel",
                      font=("Segoe UI", 8, "bold")).pack(side="left", padx=(10, 0))

            # Option 2 – original size (if sufficient)
            if self.original_size >= min_size:
                ttk.Radiobutton(
                    sel,
                    text=(f"Conserver la taille originale : "
                          f"{QCow2CloneResizer.format_size(self.original_size)} "
                          f"(aucune économie d'espace)"),
                    variable=self.choice,
                    value="original",
                    style="TRadiobutton",
                ).pack(anchor="w", pady=4)
            else:
                shortage = min_size - self.original_size
                ttk.Label(sel,
                          text=(f"Taille originale insuffisante — "
                                f"nécessite {QCow2CloneResizer.format_size(shortage)} supplémentaires"),
                          style="Error.TLabel"
                          ).pack(anchor="w", pady=4)

            # Option 3 – custom
            row3 = ttk.Frame(sel, style="Card.TFrame")
            row3.pack(fill="x", pady=4)
            ttk.Radiobutton(row3, text="Taille personnalisée :", variable=self.choice,
                             value="custom", style="TRadiobutton").pack(side="left")

            default_gb = max(1, int(min_size / (1024 ** 3)) + 1)
            self.custom_size = tk.StringVar(value=f"{default_gb}G")
            entry = ttk.Entry(row3, textvariable=self.custom_size, width=12,
                               font=C.FONT_NORMAL, style="TEntry")
            entry.pack(side="left", padx=(12, 8))
            ttk.Label(row3, text="ex. 100G · 512M · 2T",
                       style="Card.Muted.TLabel").pack(side="left")

            # Minimum warning
            warn = ttk.Frame(sel, style="Card.TFrame")
            warn.pack(fill="x", pady=(8, 0))
            ttk.Label(warn,
                      text=f"⚠  Minimum requis : {QCow2CloneResizer.format_size(min_size)}",
                      style="Warning.TLabel"
                      ).pack(anchor="w")

            # ── What happens next card ────────────────────
            nxt = ttk.LabelFrame(content, text="Prochaines étapes", style="TLabelframe")
            nxt.pack(fill="x", pady=(0, 20))

            steps = [
                "1.  Créer une nouvelle image vide avec la taille sélectionnée (preallocation=metadata)",
                "2.  Copier la structure de la table de partitions de l'image source",
                "3.  Cloner chaque partition avec toutes les modifications GParted",
                "4.  Préserver le chargeur de démarrage et toutes les modifications",
            ]
            for step in steps:
                ttk.Label(nxt, text=step, style="Card.TLabel",
                           font=C.FONT_NORMAL).pack(anchor="w", pady=1)

            ttk.Label(nxt, text="\nToutes les modifications de partitionnement seront conservées.",
                       style="Info.TLabel").pack(anchor="w", pady=(4, 0))

            # ── Fixed button bar ───────────────────────────
            bar = ttk.Frame(main_container, style="TFrame")
            bar.pack(fill="x", pady=(12, 0))

            ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 10))

            btn_row = ttk.Frame(bar, style="TFrame")
            btn_row.pack(fill="x")

            skip_btn = ttk.Button(btn_row, text="Ignorer le clonage",
                                   command=self.skip_cloning, style="TButton")
            skip_btn.pack(side="right", padx=(8, 0))

            create_btn = ttk.Button(btn_row, text="Créer la nouvelle image optimisée",
                                     command=self.create_new, style="Primary.TButton")
            create_btn.pack(side="right")

            self.dialog.bind("<Return>",  lambda e: self.create_new())
            self.dialog.bind("<Escape>",  lambda e: self.skip_cloning())
            create_btn.focus_set()

        except (tk.TclError, KeyError, TypeError, AttributeError, ValueError) as e:
            print(f"Error during UI setup: {e}")
            self._create_fallback_ui()

    # ─────────────────────────────────────────────────────────
    def _create_fallback_ui(self):
        """Minimal fallback UI"""
        try:
            frame = ttk.Frame(self.dialog, padding="20")
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="Erreur de dialogue — Interface de secours",
                       font=theme.FONT_LABEL, foreground=theme.ERROR).pack(pady=(0, 20))
            ttk.Label(frame, text="Utiliser la taille minimale calculée ?",
                       font=theme.FONT_NORMAL).pack(pady=(0, 20))
            bf = ttk.Frame(frame)
            bf.pack(fill="x")
            ttk.Button(bf, text="Oui — Créer la nouvelle image",
                        command=self._fallback_create, style="Primary.TButton").pack(side="right", padx=(10, 0))
            ttk.Button(bf, text="Non — Ignorer le clonage",
                        command=self.skip_cloning).pack(side="right")
        except (tk.TclError, AttributeError, TypeError) as e:
            print(f"Error in fallback UI: {e}")
            self.result = None

    def _fallback_create(self):
        try:
            self.result = self.final_layout_info["required_minimum_bytes"]
            self.dialog.destroy()
        except (KeyError, tk.TclError, AttributeError) as e:
            print(f"Error in fallback create: {e}")
            self.result = None
            self.skip_cloning()

    # ─────────────────────────────────────────────────────────
    def create_new(self):
        try:
            choice   = self.choice.get()
            min_size = self.final_layout_info["required_minimum_bytes"]

            if choice == "calculated":
                new_size = min_size
            elif choice == "original":
                new_size = self.original_size
            elif choice == "custom":
                new_size = QCow2CloneResizer.parse_size(self.custom_size.get())
            else:
                raise ValueError("Invalid choice")

            if new_size < min_size:
                shortage = min_size - new_size
                messagebox.showerror(
                    "Taille insuffisante",
                    f"Taille insuffisante !\n\n"
                    f"Minimum requis : {QCow2CloneResizer.format_size(min_size)}\n"
                    f"Votre sélection : {QCow2CloneResizer.format_size(new_size)}\n"
                    f"Il manque {QCow2CloneResizer.format_size(shortage)}.",
                    parent=self.dialog,
                )
                return

            self.result = new_size
            print(f"NewSizeDialog: User selected size {new_size} bytes")
            self.dialog.destroy()

        except KeyError as e:
            messagebox.showerror("Erreur de données", f"Donnée de configuration manquante : {e}", parent=self.dialog)
        except ValueError as e:
            messagebox.showerror("Taille invalide", f"Erreur d'analyse de la taille : {e}", parent=self.dialog)
        except tk.TclError as e:
            print(f"Tkinter error during create: {e}")
            try:
                self.result = self.final_layout_info["required_minimum_bytes"]
                self.dialog.destroy()
            except (KeyError, tk.TclError):
                self.result = None
        except AttributeError as e:
            messagebox.showerror("Erreur", f"Attribut de configuration manquant : {e}", parent=self.dialog)

    def skip_cloning(self):
        try:
            self.result = None
            print("NewSizeDialog: User skipped cloning")
            self.dialog.destroy()
        except (tk.TclError, AttributeError) as e:
            print(f"Error destroying dialog on skip: {e}")
            self.result = None
