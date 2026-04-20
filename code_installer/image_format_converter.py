#!/usr/bin/env python3
"""
Convertisseur de formats d'images de disque virtuel
Interface basée sur la disposition compacte de la fenêtre de chiffrement LUKS
Logique et fonctionnalités reprises de image_format_converter
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import json
import time
from pathlib import Path
from QCow2CloneResizer import QCow2CloneResizer
import theme


class ImageFormatConverter:
    """Interface graphique pour convertir des images de disque virtuel entre formats"""

    FORMATS = {
        'qcow2': {
            'name': 'QCOW2',
            'description': 'QEMU Copy-On-Write v2 (KVM/QEMU)',
            'extension': '.qcow2',
            'supports_compression': True
        },
        'vdi': {
            'name': 'VDI',
            'description': 'Image de disque VirtualBox',
            'extension': '.vdi',
            'supports_compression': False
        },
        'vhdx': {
            'name': 'VHDX',
            'description': 'Disque dur virtuel Hyper-V v2',
            'extension': '.vhdx',
            'supports_compression': False
        },
        'vmdk': {
            'name': 'VMDK',
            'description': 'Disque de machine virtuelle VMware',
            'extension': '.vmdk',
            'supports_compression': False
        },
        'vpc': {
            'name': 'VHD',
            'description': 'Disque dur virtuel (Hyper-V / VirtualBox)',
            'extension': '.vhd',
            'supports_compression': False
        },
        'raw': {
            'name': 'RAW',
            'description': 'Image disque brute (format dd)',
            'extension': '.img',
            'supports_compression': False
        }
    }

    def __init__(self, parent):
        self.parent = parent

        self.root = tk.Toplevel(parent)
        self.root.title("Convertisseur de formats d'images de disque virtuel")
        self.root.attributes("-fullscreen", True)
        self.root.transient(parent)

        self.image_path = tk.StringVar()
        self.image_info = None
        self.detected_format = None
        self.operation_active = False

        self.target_format = tk.StringVar(value='qcow2')
        self.compress_option = tk.BooleanVar(value=False)

        self.dialog_result_event = threading.Event()
        self.dialog_result_value = None

        self.setup_ui()
        self.check_prerequisites()

        self.root.protocol("WM_DELETE_WINDOW", self.close_window)

    def close_window(self):
        if self.operation_active:
            result = messagebox.askyesno(
                "Opération en cours",
                "Une conversion est actuellement en cours. Voulez-vous l'arrêter et fermer ?"
            )
            if not result:
                return
        self.root.destroy()

    def _show_message_and_wait(self, title, message):
        self.dialog_result_event.clear()
        self.dialog_result_value = None

        def show_dialog():
            messagebox.showinfo(title, message)
            self.dialog_result_event.set()

        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()

    def _show_error_and_wait(self, title, message):
        self.dialog_result_event.clear()
        self.dialog_result_value = None

        def show_dialog():
            messagebox.showerror(title, message)
            self.dialog_result_event.set()

        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()

    def setup_ui(self):
        C = theme

        # Appliquer le thème sombre à cette Toplevel
        theme.apply_theme(self.root)
        self.root.configure(bg=C.BG)

        # Conteneur principal
        main_frame = ttk.Frame(self.root, style="TFrame", padding=(20, 16))
        main_frame.pack(fill="both", expand=True)

        # ── En-tête ───────────────────────────────────────────────────────
        header_frame = ttk.Frame(main_frame, style="TFrame")
        header_frame.pack(fill="x", pady=(0, 18))

        ttk.Label(header_frame, text="Convertisseur de formats d'images",
                  style="Title.TLabel").pack(anchor="center")
        ttk.Label(header_frame,
                  text="Convertir entre les formats QCOW2, VHD, VHDX, VMDK, VDI et RAW",
                  style="Subtitle.TLabel").pack(anchor="center", pady=(2, 0))

        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=(0, 16))

        # ── Sélection du fichier ──────────────────────────────────────────
        file_frame = ttk.LabelFrame(main_frame, text="Fichier image source",
                                    style="TLabelframe")
        file_frame.pack(fill="x", pady=(0, 12))

        path_frame = ttk.Frame(file_frame, style="Card.TFrame")
        path_frame.pack(fill="x", pady=(0, 6))

        self.path_entry = ttk.Entry(path_frame, textvariable=self.image_path,
                                    font=C.FONT_NORMAL, style="TEntry")
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Button(path_frame, text="Parcourir",
                   command=self.browse_file).pack(side="right", padx=(0, 5))
        ttk.Button(path_frame, text="Analyser",
                   command=self.analyze_image).pack(side="right")

        # ── Informations sur l'image ──────────────────────────────────────
        info_frame = ttk.LabelFrame(main_frame, text="Informations sur l'image",
                                    style="TLabelframe")
        info_frame.pack(fill="x", pady=(0, 12))

        self.info_text = tk.Text(info_frame, height=5, state="disabled", wrap="word")
        theme.style_text_widget(self.info_text)
        info_scrollbar = ttk.Scrollbar(info_frame, orient="vertical",
                                       command=self.info_text.yview)
        self.info_text.configure(yscrollcommand=info_scrollbar.set)
        self.info_text.pack(side="left", fill="both", expand=True)
        info_scrollbar.pack(side="right", fill="y")

        # ── Format cible ──────────────────────────────────────────────────
        format_frame = ttk.LabelFrame(main_frame, text="Format cible",
                                      style="TLabelframe")
        format_frame.pack(fill="x", pady=(0, 12))

        self.format_radios = {}
        formats_list = list(self.FORMATS.items())
        mid_point = (len(formats_list) + 1) // 2

        cols_frame = ttk.Frame(format_frame, style="TFrame")
        cols_frame.pack(fill="x")

        left_col = ttk.Frame(cols_frame, style="TFrame")
        left_col.pack(side="left", anchor="nw", padx=(0, 20))
        right_col = ttk.Frame(cols_frame, style="TFrame")
        right_col.pack(side="left", anchor="nw")

        for idx, (fmt_key, fmt_info) in enumerate(formats_list):
            parent_col = left_col if idx < mid_point else right_col
            radio = ttk.Radiobutton(
                parent_col,
                text=f"{fmt_info['name']} — {fmt_info['description']}",
                variable=self.target_format,
                value=fmt_key,
                command=self.on_format_changed
            )
            radio.pack(anchor="w", pady=2)
            self.format_radios[fmt_key] = radio

        self.compress_check = ttk.Checkbutton(
            format_frame,
            text="Activer la compression (QCOW2 uniquement)",
            variable=self.compress_option,
            state="disabled"
        )
        self.compress_check.pack(anchor="w", pady=(8, 0))

        # ── État du système ───────────────────────────────────────────────
        self.prereq_frame = ttk.LabelFrame(main_frame, text="État du système",
                                           style="TLabelframe")
        self.prereq_frame.pack(fill="x", pady=(0, 12))

        self.prereq_label = ttk.Label(self.prereq_frame,
                                      text="Vérification des outils requis...",
                                      font=C.FONT_NORMAL, style="Card.TLabel")
        self.prereq_label.pack(anchor="w")

        # ── Progression ───────────────────────────────────────────────────
        progress_frame = ttk.LabelFrame(main_frame, text="Progression de la conversion",
                                        style="TLabelframe")
        progress_frame.pack(fill="x", pady=(0, 16))

        self.progress = ttk.Progressbar(progress_frame, mode='indeterminate', length=400)
        self.progress.pack(fill="x", pady=(0, 8))

        self.progress_label = ttk.Label(progress_frame, text="Prêt à convertir",
                                        font=("Segoe UI", 10, "bold"),
                                        style="Card.TLabel")
        self.progress_label.pack(anchor="center")

        # ── Boutons d'action ──────────────────────────────────────────────
        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(fill="x", pady=(0, 10))

        self.convert_btn = ttk.Button(
            button_frame,
            text="LANCER LA CONVERSION",
            command=self.start_conversion,
            state="disabled",
            style="Primary.TButton"
        )
        self.convert_btn.pack(fill="x", pady=(0, 8), ipady=6)

        secondary_frame = ttk.Frame(button_frame, style="TFrame")
        secondary_frame.pack(fill="x")

        ttk.Button(secondary_frame, text="Rafraîchir",
                   command=self.analyze_image, width=12).pack(side="left")
        ttk.Button(secondary_frame, text="Fermer",
                   command=self.close_window, width=12).pack(side="right")

        # ── Barre de statut ───────────────────────────────────────────────
        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=(10, 4))

        self.status_label = ttk.Label(
            main_frame,
            text="Prêt — Sélectionnez un fichier image source pour commencer",
            font=C.FONT_NORMAL, style="Card.TLabel"
        )
        self.status_label.pack(anchor="center")

    def check_prerequisites(self):
        qemu_img_available = self._check_command('qemu-img')

        text = ""
        if not qemu_img_available:
            text = "Outil requis manquant : qemu-img\n\n"
            text += "Installation de qemu-img :\n"
            text += "Ubuntu/Debian : sudo apt install qemu-utils\n"
            text += "Fedora/RHEL : sudo dnf install qemu-img\n"
            text += "Arch Linux : sudo pacman -S qemu\n"
            self.prereq_label.config(text=text, foreground="red")
            messagebox.showerror(
                "Outil requis manquant",
                "qemu-img est nécessaire pour la conversion des formats d'image.\n\n"
                "Veuillez installer le paquet qemu-utils."
            )
        else:
            text = "✓ qemu-img disponible - Tous les formats sont pris en charge"
            vboxmanage = self._check_command('VBoxManage')
            if vboxmanage:
                text += "\n✓ VBoxManage disponible - prise en charge VDI améliorée"
            self.prereq_label.config(text=text, foreground="green")

    def _check_command(self, command):
        try:
            subprocess.run(
                [command, '--version'],
                capture_output=True,
                timeout=5,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Sélectionner un fichier image de disque virtuel",
            filetypes=[
                ("Tous les formats pris en charge", "*.qcow2 *.vdi *.vhd *.vhdx *.vmdk *.img *.raw"),
                ("Fichiers QCOW2", "*.qcow2"),
                ("Fichiers VDI", "*.vdi"),
                ("Fichiers VHD", "*.vhd"),
                ("Fichiers VHDX", "*.vhdx"),
                ("Fichiers VMDK", "*.vmdk"),
                ("Images RAW", "*.img *.raw"),
                ("Tous les fichiers", "*.*")
            ]
        )
        if file_path:
            self.image_path.set(file_path)
            self.analyze_image()

    def analyze_image(self):
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("Aucun fichier sélectionné", "Veuillez d'abord sélectionner un fichier image.")
            return

        if not os.path.exists(path):
            messagebox.showerror("Fichier introuvable", "Le fichier sélectionné n'existe pas.")
            return

        try:
            self.update_progress(True, "Analyse du fichier image...")
            self.image_info = QCow2CloneResizer.get_image_info(path)
            self.detected_format = self.image_info['format']
            self.display_image_info()
            self.convert_btn.config(state="normal")
            self.update_progress(False, "Analyse terminée - prêt pour la conversion")
            self.status_label.config(text=f"Image analysée - Format détecté : {self.detected_format.upper()}")
        except FileNotFoundError:
            messagebox.showerror("Fichier introuvable", f"Fichier image introuvable : {path}")
            self.update_progress(False, "Échec de l'analyse - fichier introuvable")
        except PermissionError:
            messagebox.showerror("Permission refusée", f"Permission refusée pour accéder au fichier image : {path}")
            self.update_progress(False, "Échec de l'analyse - permission refusée")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Commande échouée", f"L'analyse avec qemu-img a échoué :\n\n{e}")
            self.update_progress(False, "Échec de l'analyse - erreur de commande")
        except json.JSONDecodeError:
            messagebox.showerror("Erreur d'analyse", "Impossible d'analyser les résultats de l'image.")
            self.update_progress(False, "Échec de l'analyse - erreur de format")
        except OSError as e:
            messagebox.showerror("Erreur système", f"Erreur système pendant l'analyse de l'image :\n\n{e}")
            self.update_progress(False, "Échec de l'analyse - erreur système")

    def display_image_info(self):
        if not self.image_info:
            return

        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")

        info = f"INFORMATIONS SUR L'IMAGE SOURCE\n"
        info += f"{'=' * 50}\n"
        info += f"Chemin : {self.image_path.get()}\n"
        info += f"Nom : {os.path.basename(self.image_path.get())}\n"
        info += f"Format détecté : {self.image_info['format'].upper()}\n\n"
        info += f"INFORMATIONS SUR LA TAILLE\n"
        info += f"{'=' * 50}\n"
        info += f"Taille virtuelle : {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"Taille du fichier : {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n"

        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Utilisation : {ratio * 100:.1f}% de la taille virtuelle\n"

        info += f"\nNOTES DE CONVERSION :\n"
        info += f"{'=' * 50}\n"
        info += f"• Sélectionnez un format cible ci-dessus\n"
        info += f"• La conversion conserve la taille virtuelle du disque\n"
        info += f"• La taille réelle du fichier peut varier selon le format\n"
        info += f"• Le fichier d'origine ne sera pas modifié\n"
        info += f"• Assurez-vous que la machine virtuelle est arrêtée avant conversion\n"

        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")

    def on_format_changed(self):
        selected = self.target_format.get()
        if self.FORMATS[selected]['supports_compression']:
            self.compress_check.config(state="normal")
        else:
            self.compress_check.config(state="disabled")
            self.compress_option.set(False)

    def validate_inputs(self):
        path = self.image_path.get().strip()

        if not path:
            messagebox.showwarning("Aucun fichier sélectionné", "Veuillez sélectionner un fichier image.")
            return False

        if not os.path.exists(path):
            messagebox.showerror("Fichier introuvable", "Le fichier sélectionné n'existe pas.")
            return False

        if not self.image_info:
            messagebox.showwarning("Image non analysée", "Veuillez d'abord analyser l'image en cliquant sur « Analyser ».")
            return False

        target_format = self.target_format.get()
        if not target_format or target_format not in self.FORMATS:
            messagebox.showwarning("Aucun format sélectionné", "Veuillez sélectionner un format cible.")
            return False

        return True

    def start_conversion(self):
        if not self.validate_inputs():
            return

        source_path = self.image_path.get()
        target_format = self.target_format.get()
        source_format = self.detected_format

        if source_format == target_format:
            result = messagebox.askyesno(
                "Même format détecté",
                f"Le format source et le format cible sont tous les deux {source_format.upper()}.\n\n"
                f"Une copie de l'image sera créée.\n\n"
                f"Continuer ?"
            )
            if not result:
                return

        source_file = Path(source_path)
        target_extension = self.FORMATS[target_format]['extension']
        target_path = source_file.parent / f"{source_file.stem}_converted{target_extension}"

        if target_path.exists():
            result = messagebox.askyesno(
                "Fichier existant",
                f"Le fichier cible existe déjà :\n{target_path}\n\n"
                f"Voulez-vous l'écraser ?"
            )
            if not result:
                return

        msg = f"CONVERSION DU FORMAT D'IMAGE\n\n"
        msg += f"Source :\n"
        msg += f" Fichier : {os.path.basename(source_path)}\n"
        msg += f" Format : {source_format.upper()}\n"
        msg += f" Taille : {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n\n"
        msg += f"Cible :\n"
        msg += f" Fichier : {target_path.name}\n"
        msg += f" Format : {target_format.upper()}\n"
        msg += f" Description : {self.FORMATS[target_format]['description']}\n"
        if self.compress_option.get():
            msg += f" Compression : activée\n"
        msg += f"\nIMPORTANT :\n"
        msg += f"• La machine virtuelle doit être complètement arrêtée\n"
        msg += f"• Le temps de conversion dépend de la taille de l'image\n"
        msg += f"• Le fichier d'origine ne sera pas modifié\n"
        msg += f"• Le fichier cible sera créé : {target_path.name}\n\n"
        msg += f"Continuer la conversion ?"

        if not messagebox.askyesno("Confirmer la conversion", msg):
            return

        self.operation_active = True
        self.convert_btn.config(state="disabled")
        self.status_label.config(text="Conversion en cours...")

        thread = threading.Thread(
            target=self._conversion_worker,
            args=(source_path, str(target_path), target_format)
        )
        thread.daemon = True
        thread.start()

    def _conversion_worker(self, source_path, target_path, target_format):
        try:
            self.update_progress(True, f"Conversion vers {target_format.upper()}...")
            cmd = ['qemu-img', 'convert', '-O', target_format, '-p']
            if self.compress_option.get() and self.FORMATS[target_format]['supports_compression']:
                cmd.extend(['-c'])
            cmd.extend([source_path, target_path])

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )

            for line in process.stdout:
                line = line.strip()
                if line and ('%' in line or '/' in line):
                    self.update_progress(True, f"Conversion : {line}")

            process.wait()

            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd, "Conversion failed")

            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Le fichier cible n'a pas été créé : {target_path}")

            target_size = os.path.getsize(target_path)
            if target_size < 1024:
                raise ValueError(f"Le fichier cible est trop petit : {target_size} octets")

            target_info = QCow2CloneResizer.get_image_info(target_path)
            self._show_conversion_complete(source_path, target_path, target_info, target_size)

        except FileNotFoundError as e:
            self._show_error_and_wait("Fichier introuvable", f"Échec de la conversion - fichier introuvable :\n\n{e}")
        except PermissionError as e:
            self._show_error_and_wait(
                "Permission refusée",
                f"Échec de la conversion - permission refusée :\n\n{e}\n\nVérifiez les permissions des fichiers et l'espace disque disponible."
            )
        except subprocess.CalledProcessError as e:
            self._show_error_and_wait(
                "Conversion échouée",
                f"La conversion avec qemu-img a échoué :\n\n{e}\n\nVérifiez que l'image source n'est pas corrompue."
            )
        except ValueError as e:
            self._show_error_and_wait("Valeur invalide", f"Échec de la conversion - valeur invalide :\n\n{e}")
        except OSError as e:
            self._show_error_and_wait(
                "Erreur système",
                f"Échec de la conversion - erreur système :\n\n{e}\n\nVérifiez l'espace disque et les ressources système."
            )
        except Exception as e:
            self._show_error_and_wait("Erreur inattendue", f"Échec de la conversion avec une erreur inattendue :\n\n{e}")
        finally:
            self.root.after(0, self.reset_ui)

    def _show_conversion_complete(self, source_path, target_path, target_info, target_size):
        try:
            source_size = self.image_info['actual_size']
            source_format = self.image_info['format']
            target_format = target_info['format']

            msg = f"CONVERSION RÉUSSIE !\n\n"
            msg += f"IMAGE SOURCE :\n"
            msg += f"{'=' * 50}\n"
            msg += f"Fichier : {os.path.basename(source_path)}\n"
            msg += f"Format : {source_format.upper()}\n"
            msg += f"Taille : {QCow2CloneResizer.format_size(source_size)}\n\n"
            msg += f"IMAGE CIBLE :\n"
            msg += f"{'=' * 50}\n"
            msg += f"Fichier : {os.path.basename(target_path)}\n"
            msg += f"Format : {target_format.upper()}\n"
            msg += f"Taille virtuelle : {QCow2CloneResizer.format_size(target_info['virtual_size'])}\n"
            msg += f"Taille du fichier : {QCow2CloneResizer.format_size(target_size)}\n\n"

            if target_size < source_size:
                saved = source_size - target_size
                ratio = saved / source_size * 100
                msg += f"✓ Espace économisé : {QCow2CloneResizer.format_size(saved)} ({ratio:.1f}% de moins)\n"
            elif target_size > source_size:
                added = target_size - source_size
                ratio = added / source_size * 100
                msg += f"⚠ Fichier plus volumineux : {QCow2CloneResizer.format_size(added)} ({ratio:.1f}% de plus)\n"
            else:
                msg += f"✓ Taille du fichier inchangée\n"

            msg += f"\n✓ Taille virtuelle du disque conservée\n"
            msg += f"✓ Fichier d'origine intact\n"
            msg += f"✓ Prêt à être utilisé dans la machine virtuelle\n\n"
            msg += f"Emplacement : {target_path}"
            self._show_message_and_wait("Conversion terminée", msg)
        except KeyError:
            self._show_message_and_wait(
                "Conversion terminée",
                f"La conversion de l'image est terminée avec succès !\n\nFichier cible : {target_path}"
            )

    def update_progress(self, active, status):
        def update():
            if active:
                self.progress.start(10)
            else:
                self.progress.stop()
            self.progress_label.config(text=status)
            if not active:
                self.status_label.config(text="Prêt - Sélectionnez une image pour commencer")
            else:
                self.status_label.config(text=f"Opération en cours : {status}")
        self.root.after(0, update)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def reset_ui(self):
        self.operation_active = False
        self.convert_btn.config(state="normal")
        self.progress.stop()
        self.progress_label.config(text="Opération terminée")
        self.status_label.config(text="Opération terminée - Prêt pour une nouvelle conversion")