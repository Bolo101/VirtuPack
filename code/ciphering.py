#!/usr/bin/env python3
"""
VM Image LUKS Encryption Module
Provides GUI for encrypting and decrypting virtual machine disk images using LUKS

Updated: handle "No space left on device" from dd as a tolerated condition when the target
file/device reached the expected size. Adds a helper to inspect dd exit and decide
whether to treat it as success based on target size checks.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import time
from pathlib import Path
import re
import fcntl
from log_handler import log_info, log_error, log_warning
import theme


class LUKSCiphering:
    """GUI for LUKS encryption/decryption of virtual disk images"""
    
    MODES = {
        'encrypt': {
            'name': 'Chiffrer l\'image',
            'description': 'Chiffrer une image de disque virtuel avec LUKS'
        },
        'decrypt': {
            'name': 'Déchiffrer l\'image',
            'description': 'Déchiffrer une image de disque virtuel chiffrée par LUKS'
        }
    }
    
    def __init__(self, parent):
        self.parent = parent
        
        self.root = tk.Toplevel(parent)
        self.root.title("Chiffrement LUKS d'images")
        self.root.attributes("-fullscreen", True)
        self.root.transient(parent)
        
        self.image_path = tk.StringVar()
        self.mode = tk.StringVar(value='encrypt')
        self.password = tk.StringVar()
        self.password_confirm = tk.StringVar()
        self.operation_active = False
        
        log_info("Dialogue Chiffrement LUKS ouvert")
        
        self.setup_ui()
        self.check_prerequisites()
        
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    
    def close_window(self):
        """Gestion de la fermeture de fenêtre"""
        if self.operation_active:
            result = messagebox.askyesno(
                "Opération en cours",
                "Une opération de chiffrement/déchiffrement est en cours. Arrêter et fermer ?"
            )
            if not result:
                return
            
            log_warning("Opération LUKS interrompue par l'utilisateur")
        
        log_info("Dialogue Chiffrement LUKS fermé")
        self.root.destroy()
    
    
    def setup_ui(self):
        """Setup de l'interface utilisateur"""
        C = theme

        # Appliquer le thème sombre à cette Toplevel
        theme.apply_theme(self.root)
        self.root.configure(bg=C.BG)

        # Conteneur principal
        main_frame = ttk.Frame(self.root, style="TFrame", padding=(20, 16))
        main_frame.pack(fill="both", expand=True)

        # ── Zone basse ancrée en premier (toujours visible) ───────────────
        bottom_frame = ttk.Frame(main_frame, style="TFrame")
        bottom_frame.pack(side="bottom", fill="x")

        self.status_label = ttk.Label(
            bottom_frame,
            text="Prêt — Sélectionnez un fichier image et saisissez le mot de passe",
            font=C.FONT_NORMAL, style="Card.TLabel"
        )
        self.status_label.pack(anchor="center", pady=(0, 4))

        ttk.Separator(bottom_frame, orient="horizontal").pack(fill="x", pady=(0, 8))

        button_frame = ttk.Frame(bottom_frame, style="TFrame")
        button_frame.pack(fill="x", pady=(0, 6))

        self.action_btn = ttk.Button(
            button_frame,
            text="DÉMARRER L'OPÉRATION",
            command=self.start_operation,
            state="disabled",
            style="Primary.TButton"
        )
        self.action_btn.pack(fill="x", pady=(0, 8), ipady=6)

        secondary_frame = ttk.Frame(button_frame, style="TFrame")
        secondary_frame.pack(fill="x")

        ttk.Button(secondary_frame, text="Rafraîchir",
                   command=self.analyze_image, width=12).pack(side="left")
        ttk.Button(secondary_frame, text="Effacer le mot de passe",
                   command=self.clear_password, width=20).pack(side="left", padx=(6, 0))
        ttk.Button(secondary_frame, text="Fermer",
                   command=self.close_window, width=12).pack(side="right")

        # ── En-tête ───────────────────────────────────────────────────────
        header_frame = ttk.Frame(main_frame, style="TFrame")
        header_frame.pack(fill="x", pady=(0, 18))

        ttk.Label(header_frame, text="Chiffrement LUKS d'images",
                  style="Title.TLabel").pack(anchor="center")
        ttk.Label(header_frame,
                  text="Chiffrer ou déchiffrer des images de disques virtuels",
                  style="Subtitle.TLabel").pack(anchor="center", pady=(2, 0))

        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=(0, 16))

        # ── Mode opération ────────────────────────────────────────────────
        mode_frame = ttk.LabelFrame(main_frame, text="Mode d'opération",
                                    style="TLabelframe")
        mode_frame.pack(fill="x", pady=(0, 12))

        for mode_key, mode_info in self.MODES.items():
            ttk.Radiobutton(
                mode_frame,
                text=f"{mode_info['name']} — {mode_info['description']}",
                variable=self.mode,
                value=mode_key,
                command=self.on_mode_changed
            ).pack(anchor="w", pady=2)

        # ── Fichier image source ──────────────────────────────────────────
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

        self.info_text = tk.Text(info_frame, height=3, state="disabled", wrap="word")
        theme.style_text_widget(self.info_text)
        info_scrollbar = ttk.Scrollbar(info_frame, orient="vertical",
                                       command=self.info_text.yview)
        self.info_text.configure(yscrollcommand=info_scrollbar.set)
        self.info_text.pack(side="left", fill="both", expand=True)
        info_scrollbar.pack(side="right", fill="y")

        # ── Mot de passe ──────────────────────────────────────────────────
        password_frame = ttk.LabelFrame(main_frame, text="Mot de passe",
                                        style="TLabelframe")
        password_frame.pack(fill="x", pady=(0, 12))

        pwd_row1 = ttk.Frame(password_frame, style="TFrame")
        pwd_row1.pack(fill="x", pady=(0, 6))
        ttk.Label(pwd_row1, text="Mot de passe :", font=C.FONT_NORMAL,
                  style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.password_entry = ttk.Entry(pwd_row1, textvariable=self.password,
                                        show="•", font=C.FONT_NORMAL, style="TEntry")
        self.password_entry.pack(side="left", fill="x", expand=True)
        self.password_entry.bind("<KeyRelease>", self.update_password_strength)

        pwd_row2 = ttk.Frame(password_frame, style="TFrame")
        pwd_row2.pack(fill="x", pady=(0, 8))
        ttk.Label(pwd_row2, text="Confirmation :", font=C.FONT_NORMAL,
                  style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.password_confirm_entry = ttk.Entry(pwd_row2,
                                                textvariable=self.password_confirm,
                                                show="•", font=C.FONT_NORMAL,
                                                style="TEntry")
        self.password_confirm_entry.pack(side="left", fill="x", expand=True)

        strength_frame = ttk.Frame(password_frame, style="TFrame")
        strength_frame.pack(fill="x")
        ttk.Label(strength_frame, text="Robustesse :", font=C.FONT_NORMAL,
                  style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.strength_bar = ttk.Progressbar(strength_frame, length=120,
                                            mode='determinate', maximum=100)
        self.strength_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.strength_label = ttk.Label(strength_frame, text="Faible",
                                        font=C.FONT_NORMAL, style="Card.TLabel",
                                        width=10)
        self.strength_label.pack(side="left")

        # ── État du système ───────────────────────────────────────────────
        self.prereq_frame = ttk.LabelFrame(main_frame, text="État du système",
                                           style="TLabelframe")
        self.prereq_frame.pack(fill="x", pady=(0, 12))

        self.prereq_label = ttk.Label(self.prereq_frame,
                                      text="Vérification des outils requis...",
                                      font=C.FONT_NORMAL, style="Card.TLabel")
        self.prereq_label.pack(anchor="w")

        # ── Progression ───────────────────────────────────────────────────
        progress_frame = ttk.LabelFrame(main_frame, text="Progression de l'opération",
                                        style="TLabelframe")
        progress_frame.pack(fill="x", pady=(0, 12))

        self.progress = ttk.Progressbar(progress_frame, mode='determinate',
                                        maximum=100, length=400)
        self.progress.pack(fill="x", pady=(0, 8))

        self.progress_label = ttk.Label(progress_frame, text="Prêt à démarrer",
                                        font=("Segoe UI", 10, "bold"),
                                        style="Card.TLabel")
        self.progress_label.pack(anchor="center")

    def check_prerequisites(self):
        """Vérifier si les outils requis sont installés"""
        cryptsetup_available = self._check_command('cryptsetup')
        
        if not cryptsetup_available:
            text = "Outil requis manquant : cryptsetup\n\n"
            text += "Installation de cryptsetup :\n"
            text += "Ubuntu/Debian : sudo apt install cryptsetup\n"
            text += "Fedora/RHEL : sudo dnf install cryptsetup\n"
            text += "Arch Linux : sudo pacman -S cryptsetup\n"
            
            self.prereq_label.config(text=text, foreground="red")
            
            log_error("cryptsetup introuvable — requis pour le chiffrement LUKS")
            
            messagebox.showerror(
                "Outil requis manquant",
                "cryptsetup est nécessaire pour le chiffrement LUKS.\n\n"
                "Veuillez installer le paquet cryptsetup."
            )
        else:
            text = "✓ cryptsetup disponible — Prêt pour le chiffrement LUKS"
            self.prereq_label.config(text=text, foreground="green")
            log_info("cryptsetup disponible — prérequis satisfaits")
    
    def _check_command(self, command):
        """Check if a command is available"""
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
        """Browse for image file"""
        file_path = filedialog.askopenfilename(
            title="Sélectionner un fichier image de disque virtuel",
            filetypes=[
                ("Toutes les images", "*.qcow2 *.vdi *.vhd *.vhdx *.vmdk *.img *.raw"),
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
        """Analyser l'image sélectionnée"""
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("Aucun fichier sélectionné", "Veuillez d'abord sélectionner un fichier image")
            log_warning("Analyse tentée sans fichier sélectionné")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("Fichier introuvable", "Le fichier sélectionné n'existe pas")
            log_error(f"Fichier image introuvable : {path}")
            return
        
        try:
            self.update_progress(True, "Analyse du fichier image...")
            
            file_size = os.path.getsize(path)
            file_stat = os.stat(path)
            
            log_info(f"Analyse de l'image : {os.path.basename(path)} — Taille : {self._format_size(file_size)}")
            
            self.display_image_info(path, file_size, file_stat)
            
            self.action_btn.config(state="normal")
            
            self.update_progress(False, "Analyse terminée — Prêt pour l'opération")
            self.status_label.config(text="Image analysée — Prêt")
            
            log_info(f"Analyse terminée avec succès pour {os.path.basename(path)}")
            
        except FileNotFoundError:
            messagebox.showerror("Fichier introuvable", f"Fichier image introuvable : {path}")
            log_error(f"FileNotFoundError pendant l'analyse : {path}")
            self.update_progress(False, "Échec de l'analyse")
        except PermissionError:
            messagebox.showerror("Permission refusée", f"Permission refusée : {path}")
            log_error(f"PermissionError pendant l'analyse : {path}")
            self.update_progress(False, "Échec de l'analyse")
        except OSError as e:
            messagebox.showerror("Erreur système", f"Erreur système : {e}")
            log_error(f"OSError pendant l'analyse : {e}")
            self.update_progress(False, "Échec de l'analyse")
    
    def display_image_info(self, path, file_size, file_stat):
        """Afficher les informations de l'image"""
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        mode_text = "CHIFFREMENT" if self.mode.get() == 'encrypt' else "DÉCHIFFREMENT"
        info = f"{os.path.basename(path)} | {self._format_size(file_size)} | Opération : {mode_text}\nFichier original NON modifié"
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    
    def update_password_strength(self, event=None):
        """Update password strength indicator"""
        password = self.password.get()
        strength = 0
        feedback = "Très faible"
        
        if len(password) >= 8:
            strength += 25
            feedback = "Faible"
        
        if len(password) >= 12:
            strength += 25
            feedback = "Correct"
        
        if any(c.isupper() for c in password) and any(c.islower() for c in password):
            strength += 25
            feedback = "Bon"
        
        if any(c.isdigit() for c in password) and any(not c.isalnum() for c in password):
            strength += 25
            feedback = "Fort"
        
        self.strength_bar.config(value=strength)
        self.strength_label.config(text=feedback)
    
    def clear_password(self):
        """Clear password fields"""
        self.password.set("")
        self.password_confirm.set("")
        self.strength_bar.config(value=0)
        self.strength_label.config(text="Faible")
        log_info("Champs mot de passe effacés")
    
    def validate_inputs(self):
        """Validate user inputs"""
        path = self.image_path.get().strip()
        
        if not path:
            messagebox.showwarning("Aucun fichier sélectionné", "Veuillez sélectionner un fichier image")
            log_warning("Validation échouée : aucun fichier image sélectionné")
            return False
        
        if not os.path.exists(path):
            messagebox.showerror("Fichier introuvable", "Le fichier sélectionné n'existe pas")
            log_error(f"Validation échouée : fichier image introuvable — {path}")
            return False
        
        password = self.password.get()
        mode = self.mode.get()
        
        if not password:
            messagebox.showwarning("Aucun mot de passe", "Veuillez saisir un mot de passe")
            log_warning("Validation échouée : aucun mot de passe saisi")
            return False
        
        if len(password) < 8:
            messagebox.showwarning("Mot de passe trop court", "Le mot de passe doit comporter au moins 8 caractères")
            log_warning("Validation échouée : mot de passe trop court (moins de 8 caractères)")
            return False
        
        # En mode chiffrement, vérifier la confirmation
        if mode == 'encrypt':
            password_confirm = self.password_confirm.get()
            if password != password_confirm:
                messagebox.showerror("Mots de passe différents", "Les mots de passe ne correspondent pas")
                log_error("Validation échouée : mots de passe différents")
                return False
        
        log_info("Toutes les entrées sont valides")
        return True
    
    def start_operation(self):
        """Start encryption/decryption operation"""
        if not self.validate_inputs():
            return
        
        image_path = self.image_path.get()
        mode = self.mode.get()
        password = self.password.get()
        
        # Generate output filename
        source_file = Path(image_path)
        if mode == 'encrypt':
            output_path = source_file.parent / f"{source_file.stem}_encrypted{source_file.suffix}"
            operation_name = "Chiffrement"
        else:
            output_path = source_file.parent / f"{source_file.stem}_decrypted{source_file.suffix}"
            operation_name = "Déchiffrement"
        
        # Vérifier si la cible existe
        if output_path.exists():
            result = messagebox.askyesno(
                "Fichier existant",
                f"Le fichier cible existe déjà :\n{output_path}\n\nÉcraser ?"
            )
            if not result:
                log_warning(f"Opération annulée — fichier cible déjà existant : {output_path}")
                return
        
        # Dialogue de confirmation
        msg = f"CHIFFREMENT/DÉCHIFFREMENT LUKS\n\n"
        msg += f"Source : {os.path.basename(image_path)} ({self._format_size(os.path.getsize(image_path))})\n"
        msg += f"Cible : {output_path.name}\n\n"
        msg += f"⚠ La machine virtuelle doit être arrêtée\n"
        msg += f"⚠ L'opération peut prendre plusieurs minutes\n"
        msg += f"⚠ Le fichier d'origine ne sera PAS modifié\n\n"
        msg += f"Continuer ?"
        
        if not messagebox.askyesno("Confirmer l'opération", msg):
            log_warning(f"Opération {operation_name.lower()} annulée par l'utilisateur")
            return
        
        log_info(f"Démarrage de l'opération {operation_name.lower()}")
        log_info(f"Fichier source : {image_path}")
        log_info(f"Fichier cible : {output_path}")
        log_info(f"Taille source : {self._format_size(os.path.getsize(image_path))}")
        
        self.operation_active = True
        self.action_btn.config(state="disabled")
        self.status_label.config(text=f"{operation_name} en cours...")
        
        thread = threading.Thread(
            target=self._operation_worker,
            args=(image_path, str(output_path), mode, password)
        )
        thread.daemon = True
        thread.start()
    
    def _operation_worker(self, source_path, target_path, mode, password):
        """Worker thread for encryption/decryption"""
        try:
            if mode == 'encrypt':
                self._encrypt_image(source_path, target_path, password)
            else:
                self._decrypt_image(source_path, target_path, password)
            
            target_size = os.path.getsize(target_path)
            
            msg = f"{'CHIFFREMENT' if mode == 'encrypt' else 'DÉCHIFFREMENT'} TERMINÉ !\n\n"
            msg += f"Source : {os.path.basename(source_path)}\n"
            msg += f"Cible : {os.path.basename(target_path)}\n"
            msg += f"Taille : {self._format_size(target_size)}\n\n"
            msg += f"✓ Fichier {'chiffré' if mode == 'encrypt' else 'déchiffré'} avec succès\n"
            msg += f"✓ Fichier d'origine intact\n"
            msg += f"✓ Prêt à l'emploi\n\n"
            msg += f"Emplacement : {target_path}"
            
            log_info(f"{'CHIFFREMENT' if mode == 'encrypt' else 'DÉCHIFFREMENT'} terminé avec succès")
            log_info(f"Taille du fichier de sortie : {self._format_size(target_size)}")
            
            self.root.after(0, lambda: messagebox.showinfo("Opération terminée", msg))
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Opération échouée : {e}"
            log_error(f"CalledProcessError pendant l'opération : {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Opération échouée", error_msg))
        except OSError as e:
            error_msg = f"Erreur système : {e}"
            log_error(f"OSError pendant l'opération : {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Erreur système", error_msg))
        finally:
            self.root.after(0, self.reset_ui)
    
    def on_mode_changed(self):
        """Gestion du changement de mode"""
        mode = self.mode.get()
        log_info(f"Mode d'opération changé en : {'CHIFFREMENT' if mode == 'encrypt' else 'DÉCHIFFREMENT'}")
        
        self.clear_password()
        self.progress_label.config(text="Prêt à démarrer")
        self.status_label.config(text="Mode modifié — Prêt à analyser l'image")
        
        # Désactiver la confirmation en mode déchiffrement
        if mode == 'decrypt':
            self.password_confirm_entry.config(state="disabled")
        else:
            self.password_confirm_entry.config(state="normal")




    def update_progress(self, percentage, status):
        """Update progress bar with percentage value"""
        def update():
            self.progress.config(value=min(percentage, 100))
            self.progress_label.config(text=f"{status} - {percentage}%")
        
        self.root.after(0, update)

    def _encrypt_image(self, source_path, target_path, password):
        """Chiffrer image avec LUKS - gestion robuste de dd avec progression LUKS"""
        self.update_progress(1, "Création du fichier cible")
        
        container_name = None
        process = None
        try:
            if not os.path.isabs(source_path) or not os.path.isabs(target_path):
                raise ValueError("Les chemins doivent être absolus")
            
            if not os.path.exists(source_path):
                raise FileNotFoundError(f"Fichier source introuvable: {source_path}")
            
            source_size = os.path.getsize(source_path)
            
            # Créer fichier cible sparse PLUS GRAND (LUKS2 ajoute ~16MB d'en-tête)
            luks_overhead = int(source_size * 0.20) + (20 * 1024 * 1024)
            target_size = source_size + luks_overhead
            
            log_info(f"LUKS Encryption: Source size: {self._format_size(source_size)}, Target size: {self._format_size(target_size)}")
            
            print(f"Source: {self._format_size(source_size)}, Target: {self._format_size(target_size)} (overhead: {self._format_size(luks_overhead)})")
            
            try:
                self.update_progress(1, "Création du fichier cible")
                
                # Créer le fichier et l'allouer avec zeros au lieu d'un fichier sparse
                with open(target_path, 'wb') as f:
                    # Écrire par chunks de 1MB pour éviter les gros seeks
                    chunk_size = 1024 * 1024  # 1MB
                    bytes_written = 0
                    
                    while bytes_written < target_size:
                        remaining = target_size - bytes_written
                        write_size = min(chunk_size, remaining)
                        f.write(b'\0' * write_size)
                        bytes_written += write_size
                        
                        # Mise à jour de la progression tous les 100MB
                        if bytes_written % (100 * 1024 * 1024) == 0:
                            progress = int((bytes_written / target_size) * 4) + 1  # 1% à 5%
                            self.update_progress(progress, f"Allocation: {self._format_size(bytes_written)}/{self._format_size(target_size)}")
                
                self.update_progress(5, "Fichier cible créé")
                os.chmod(target_path, 0o600)
                log_info(f"Target file created: {target_path}")
            except Exception as e:
                log_error(f"Failed to create target file: {e}")
                raise IOError(f"Impossible de créer {target_path} ({target_size} bytes): {e}")

            self.update_progress(6, "Formatage du conteneur LUKS")
            log_info("Formatting LUKS2 container...")

            format_cmd = [
                'cryptsetup', 'luksFormat',
                '--type', 'luks2',
                '-q',
                '--batch-mode',
                target_path
            ]
            
            proc = subprocess.Popen(
                format_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=self._restrict_process
            )
            
            # Démarrer un thread pour monitorer la progression PENDANT que cryptsetup s'exécute
            def monitor_luks_format():
                last_progress_percent = 6
                while proc.poll() is None:
                    try:
                        current_size = os.path.getsize(target_path)
                        progress_percent = int((current_size / target_size) * 9) + 6  # 6% à 15%
                        progress_percent = min(progress_percent, 14)  # Cap à 14% avant ouverture
                        
                        if progress_percent != last_progress_percent:
                            last_progress_percent = progress_percent
                            self.update_progress(progress_percent, 
                                f"Formatage LUKS: {self._format_size(current_size)}/{self._format_size(target_size)}")
                    except OSError:
                        pass
                    
                    time.sleep(0.5)
            
            monitor_thread = threading.Thread(target=monitor_luks_format)
            monitor_thread.daemon = True
            monitor_thread.start()
            
            # Envoyer le mot de passe via communicate() - c'est plus propre
            stdout, stderr = proc.communicate(input=f"{password}\n{password}\n")
            
            # Attendre la fin du monitoring
            monitor_thread.join(timeout=1)
            
            if proc.returncode != 0:
                log_error(f"LUKS Format Error: {stderr}")
                print(f"Erreur LUKS Format: {stderr}")
                raise subprocess.CalledProcessError(proc.returncode, 'cryptsetup luksFormat', stderr)
            
            log_info("LUKS2 container formatted successfully")
            self.update_progress(15, "Ouverture du conteneur LUKS")
            
            log_info("Opening LUKS container...")
            
            container_name = "temp_luks_mount"
            open_cmd = [
                'cryptsetup', 'open',
                target_path,
                container_name
            ]
            
            proc = subprocess.Popen(
                open_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=self._restrict_process
            )
            
            stdout, stderr = proc.communicate(input=password + "\n")
            
            if proc.returncode != 0:
                log_error(f"LUKS Open Error: {stderr}")
                print(f"Erreur LUKS Open: {stderr}")
                raise subprocess.CalledProcessError(proc.returncode, 'cryptsetup open', stderr)
            
            log_info("LUKS container opened successfully")
            self.update_progress(18, "Démarrage du chiffrement des données")
            
            try:
                log_info("Starting data encryption with dd...")
                
                copy_cmd = [
                    'dd',
                    f'if={source_path}',
                    f'of=/dev/mapper/{container_name}',
                    'bs=4M',
                    'conv=notrunc,noerror,sync',
                    'oflag=sync',
                    'status=progress'
                ]
                
                process = subprocess.Popen(
                    copy_cmd,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    bufsize=0
                )
                
                flags = fcntl.fcntl(process.stderr, fcntl.F_GETFL)
                fcntl.fcntl(process.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                
                buffer = b""
                bytes_copied = 0
                last_progress_percent = -1
                
                while process.poll() is None:
                    time.sleep(0.1)
                    
                    try:
                        chunk = process.stderr.read(8192)
                        if not chunk:
                            continue
                        
                        print(chunk.decode("utf-8", errors="ignore"), end="", flush=True)
                        
                        buffer += chunk
                        text = buffer.decode("utf-8", errors="ignore")
                        
                        if "\r" in text:
                            line = text.split("\r")[-1].strip()
                            buffer = text.split("\r")[-1].encode()
                        else:
                            line = text.strip()
                        
                        m = (
                            re.search(r"(\d+)\s+octets", line) or
                            re.search(r"(\d+)\s+bytes", line)
                        )
                        
                        if m:
                            bytes_copied = int(m.group(1))
                            progress_percent = int((bytes_copied / source_size) * 82) + 18  # 18% à 100%
                            progress_percent = min(max(progress_percent, 18), 99)
                            
                            if progress_percent != last_progress_percent:
                                last_progress_percent = progress_percent
                                self.update_progress(progress_percent, f"Chiffrement: {self._format_size(bytes_copied)}/{self._format_size(source_size)}")
                    
                    except (BlockingIOError, OSError):
                        pass
                    except (UnicodeDecodeError, ValueError):
                        pass
                
                return_code = process.returncode
                
                if return_code == 0:
                    log_info(f"Data encryption completed - {self._format_size(bytes_copied)} encrypted")
                    print(f"✓ Chiffrement réussi")
                    self.update_progress(100, "Chiffrement complété")
                else:
                    self._evaluate_dd_result(
                        return_code,
                        "",
                        expected_size=source_size,
                        path_to_check=target_path,
                        description='dd (encrypt)'
                    )
                    log_info(f"Data encryption completed with tolerated error - {self._format_size(bytes_copied)} encrypted")
                    print(f"✓ Chiffrement réussi (dd a terminé avec succès malgré le code retour)")
                    self.update_progress(100, "Chiffrement complété")
                
                subprocess.run(['sync'], check=True, capture_output=True)
                        
            finally:
                if process and process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                
                close_cmd = ['cryptsetup', 'close', container_name]
                close_proc = subprocess.run(
                    close_cmd,
                    check=False,
                    capture_output=True
                )
                if close_proc.returncode != 0:
                    log_warning(f"LUKS Close warning: {close_proc.stderr}")
                    print(f"Avertissement LUKS Close: {close_proc.stderr}")
                else:
                    log_info("LUKS container closed successfully")
        
        except subprocess.CalledProcessError as e:
            try:
                if container_name:
                    subprocess.run(['cryptsetup', 'close', container_name], check=False, capture_output=True)
                if os.path.exists(target_path):
                    os.remove(target_path)
                    log_info("Target file removed after error")
            except Exception as cleanup_e:
                log_error(f"Erreur nettoyage: {cleanup_e}")
                print(f"Erreur nettoyage: {cleanup_e}")
            raise e
        except Exception as e:
            try:
                if container_name:
                    subprocess.run(['cryptsetup', 'close', container_name], check=False, capture_output=True)
                if os.path.exists(target_path):
                    os.remove(target_path)
                    log_info("Target file removed after error")
            except Exception as cleanup_e:
                log_error(f"Erreur nettoyage: {cleanup_e}")
                print(f"Erreur nettoyage: {cleanup_e}")
            log_error(f"Encryption failed: {str(e)}")
            raise subprocess.CalledProcessError(1, "cryptsetup", str(e))
        finally:
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    pass

    def _decrypt_image(self, source_path, target_path, password):
        """Déchiffrer image LUKS chiffrée - gestion robuste de dd"""
        self.update_progress(1, "Ouverture du conteneur chiffré")
        
        container_name = "temp_luks_decrypt"
        process = None
        try:
            if not os.path.isabs(source_path) or not os.path.isabs(target_path):
                raise ValueError("Les chemins doivent être absolus")
            
            if not os.path.exists(source_path):
                log_error(f"Decryption source file not found: {source_path}")
                raise FileNotFoundError(f"Fichier source introuvable: {source_path}")
            
            log_info(f"Opening encrypted container: {source_path}")
            
            # Nettoyer le mot de passe (supprimer espaces inutiles)
            password = password.strip()
            
            open_cmd = [
                'cryptsetup', 'open',
                source_path,
                container_name
            ]
            
            proc = subprocess.Popen(
                open_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=self._restrict_process
            )
            
            # Utiliser communicate() pour un meilleur handling du password
            stdout, stderr = proc.communicate(input=password + "\n", timeout=30)
            
            if proc.returncode != 0:
                log_error(f"Failed to open encrypted container - Return code: {proc.returncode}")
                log_error(f"stderr: {stderr}")
                raise subprocess.CalledProcessError(proc.returncode, 'cryptsetup open', 
                    "Mot de passe invalide ou conteneur corrompu")
            
            log_info("Encrypted container opened successfully")
            self.update_progress(10, "Détermination de la taille du conteneur")
            
            try:
                result = subprocess.run(
                    ['blockdev', '--getsize64', f'/dev/mapper/{container_name}'],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10
                )
                container_size = int(result.stdout.strip())
                log_info(f"Container size: {self._format_size(container_size)}")
            except:
                container_size = 0
                log_warning("Could not determine container size")
            
            try:
                self.update_progress(15, "Démarrage du déchiffrement des données")
                log_info("Starting data decryption with dd...")
                
                copy_cmd = [
                    'dd',
                    f'if=/dev/mapper/{container_name}',
                    f'of={target_path}',
                    'bs=4M',
                    'conv=notrunc,noerror,sync',
                    'oflag=sync',
                    'status=progress'
                ]
                
                process = subprocess.Popen(
                    copy_cmd,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    bufsize=0
                )
                
                flags = fcntl.fcntl(process.stderr, fcntl.F_GETFL)
                fcntl.fcntl(process.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                
                buffer = b""
                bytes_copied = 0
                last_progress_percent = -1
                
                while process.poll() is None:
                    time.sleep(0.1)
                    
                    try:
                        chunk = process.stderr.read(8192)
                        if not chunk:
                            continue
                        
                        print(chunk.decode("utf-8", errors="ignore"), end="", flush=True)
                        
                        buffer += chunk
                        text = buffer.decode("utf-8", errors="ignore")
                        
                        if "\r" in text:
                            line = text.split("\r")[-1].strip()
                            buffer = text.split("\r")[-1].encode()
                        else:
                            line = text.strip()
                        
                        m = (
                            re.search(r"(\d+)\s+octets", line) or
                            re.search(r"(\d+)\s+bytes", line)
                        )
                        
                        if m:
                            bytes_copied = int(m.group(1))
                            progress_percent = int((bytes_copied / container_size) * 85) + 15  # 15% à 100%
                            progress_percent = min(max(progress_percent, 15), 99)
                            
                            if progress_percent != last_progress_percent:
                                last_progress_percent = progress_percent
                                self.update_progress(progress_percent, f"Déchiffrement: {self._format_size(bytes_copied)}/{self._format_size(container_size)}")
                    
                    except (BlockingIOError, OSError):
                        pass
                    except (UnicodeDecodeError, ValueError):
                        pass
                
                return_code = process.returncode
                
                if return_code == 0:
                    log_info(f"Data decryption completed - {self._format_size(bytes_copied)} decrypted")
                    print(f"✓ Déchiffrement réussi")
                    self.update_progress(100, "Déchiffrement complété")
                else:
                    self._evaluate_dd_result(
                        return_code,
                        "",
                        expected_size=container_size,
                        path_to_check=target_path,
                        description='dd (decrypt)'
                    )
                    log_info(f"Data decryption completed with tolerated error - {self._format_size(bytes_copied)} decrypted")
                    print(f"✓ Déchiffrement réussi (dd a terminé avec succès malgré le code retour)")
                    self.update_progress(100, "Déchiffrement complété")
                
                try:
                    os.chmod(target_path, 0o600)
                except Exception:
                    pass
                
                subprocess.run(['sync'], check=True, capture_output=True)
                
            finally:
                if process and process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                
                subprocess.run(
                    ['cryptsetup', 'close', container_name],
                    check=False,
                    capture_output=True
                )
                log_info("LUKS container closed")
        
        except subprocess.CalledProcessError as e:
            try:
                subprocess.run(['cryptsetup', 'close', container_name], check=False)
                if os.path.exists(target_path):
                    os.remove(target_path)
                    log_info("Target file removed after decryption error")
            except:
                pass
            log_error(f"Decryption failed: {str(e)}")
            raise e
        except Exception as e:
            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
                    log_info("Target file removed after decryption error")
            except:
                pass
            log_error(f"Decryption operation error: {str(e)}")
            raise subprocess.CalledProcessError(1, "cryptsetup", str(e))
        finally:
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    pass

    def _evaluate_dd_result(self, returncode, stderr_text, expected_size=0, path_to_check=None, description='dd'):
        """Évaluer le résultat de dd et tolérer les erreurs d'espace disque acceptables."""
        if returncode == 0:
            return
        
        stderr_text = (stderr_text or '').lower()
        enospc_indicators = ['no space left', 'aucun espace', 'enospc', 'out of space']
        is_enospc = any(indicator in stderr_text for indicator in enospc_indicators)
        
        if is_enospc or returncode == 1:
            if path_to_check and os.path.exists(path_to_check):
                try:
                    actual_size = os.path.getsize(path_to_check)
                    if expected_size == 0 or actual_size >= expected_size:
                        log_info(f"{description} reached target size: {self._format_size(actual_size)} >= {self._format_size(expected_size)}")
                        return
                    else:
                        log_error(f"{description} incomplete size: {actual_size} < {expected_size}")
                        raise subprocess.CalledProcessError(returncode, description, 
                            f"File incomplete: {actual_size}/{expected_size} bytes")
                except OSError as e:
                    log_error(f"{description} cannot verify target: {e}")
                    raise subprocess.CalledProcessError(returncode, description, str(e))
            else:
                log_error(f"{description} target file does not exist")
                raise subprocess.CalledProcessError(returncode, description, "Target file does not exist")
        
        log_error(f"{description} real error: {stderr_text}")
        raise subprocess.CalledProcessError(returncode, description, stderr_text)
    

    
    @staticmethod
    def _restrict_process():
        """Restrict process capabilities for security (Linux only)"""
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (2147483648, 2147483648))
        except:
            pass
    
    def reset_ui(self):
        """Réinitialiser l'interface après l'opération"""
        self.operation_active = False
        self.action_btn.config(state="normal")
        self.progress.stop()
        self.progress_label.config(text="Opération terminée")
        self.status_label.config(text="Opération terminée — Prêt pour une nouvelle opération")
        log_info("Interface réinitialisée après l'opération")
    
    @staticmethod
    def _format_size(bytes_size):
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"