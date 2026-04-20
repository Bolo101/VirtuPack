#!/usr/bin/env python3
"""
VM Image Export Module
Provides GUI for exporting virtual machine disk images using rsync with progress tracking
Based on LUKS Encryption module design pattern
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import re
from pathlib import Path
from log_handler import log_info, log_error, log_warning
import theme


class VirtualImageExporter:
    """GUI for exporting virtual disk images using rsync"""
    
    def __init__(self, parent):
        self.parent = parent
        
        self.root = tk.Toplevel(parent)
        self.root.title("Export d'images virtuelles")
        self.root.attributes("-fullscreen", True)
        self.root.transient(parent)
        
        self.source_path = tk.StringVar()
        self.dest_path = tk.StringVar()
        self.operation_active = False
        
        log_info("Dialogue Export d'images ouvert")
        
        self.setup_ui()
        self.check_prerequisites()
        
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    
    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno(
                "Opération en cours",
                "Un export est actuellement en cours. Arrêter et fermer ?"
            )
            if not result:
                return
            
            log_warning("Export interrompu par l'utilisateur")
        
        log_info("Dialogue Export d'images fermé")
        self.root.destroy()
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        rsync_available = self._check_command('rsync')
        
        if not rsync_available:
            text = "Outil requis manquant : rsync\n\n"
            text += "Installation de rsync :\n"
            text += "Ubuntu/Debian : sudo apt install rsync\n"
            text += "Fedora/RHEL : sudo dnf install rsync\n"
            text += "Arch Linux : sudo pacman -S rsync\n"
            
            self.prereq_label.config(text=text, foreground="red")
            
            log_error("rsync introuvable — requis pour l'export d'images")
            
            messagebox.showerror(
                "Outil requis manquant",
                "rsync est nécessaire pour l'export d'images.\n\n"
                "Veuillez installer le paquet rsync."
            )
        else:
            text = "✓ rsync disponible — Prêt pour l'export d'images"
            self.prereq_label.config(text=text, foreground="green")
            log_info("rsync disponible — prérequis satisfaits")
    
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
    
    def browse_source_file(self):
        """Browse for source image file"""
        file_path = filedialog.askopenfilename(
            title="Sélectionner un fichier image virtuel",
            filetypes=[
                ("Images virtuelles", "*.qcow2 *.img *.iso *.vdi *.vmdk"),
                ("Images QCOW2", "*.qcow2"),
                ("Images RAW", "*.img"),
                ("Images ISO", "*.iso"),
                ("Images VDI", "*.vdi"),
                ("Images VMDK", "*.vmdk"),
                ("Tous les fichiers", "*.*")
            ]
        )
        if file_path:
            self.source_path.set(file_path)
            self.analyze_source()
    
    def browse_destination_dir(self):
        """Browse for destination directory"""
        directory = filedialog.askdirectory(
            title="Sélectionner un répertoire de destination"
        )
        if directory:
            self.dest_path.set(directory)
            self.analyze_destination()
    
    def browse_home_dest(self):
        """Navigate to home directory"""
        try:
            home_dir = str(Path.home())
            self.dest_path.set(home_dir)
            self.analyze_destination()
            log_info(f"Selected home directory as destination: {home_dir}")
        except RuntimeError as e:
            log_error(f"Could not determine home directory: {e}")
            messagebox.showerror("Erreur", f"Impossible d'accéder au dossier personnel :\n{e}")
    
    def analyze_source(self):
        """Analyze selected source image"""
        path = self.source_path.get().strip()
        if not path:
            messagebox.showwarning("Aucun fichier sélectionné", "Veuillez d'abord sélectionner un fichier image source")
            log_warning("Analyse source tentée sans fichier sélectionné")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("Fichier introuvable", "Le fichier sélectionné n'existe pas")
            log_error(f"Source file not found: {path}")
            return
        
        try:
            self.update_progress(1, "Analyse du fichier source...")
            
            file_size = os.path.getsize(path)
            file_name = os.path.basename(path)
            
            log_info(f"Analyzing source: {file_name} - Size: {self._format_size(file_size)}")
            
            self.display_source_info(path, file_size)
            self.update_progress(0, "Analyse terminée — Prêt")
            self.status_label.config(text="Source analysée — Sélectionnez la destination")
            
            log_info(f"Source analysis completed successfully for {file_name}")
            
        except FileNotFoundError:
            messagebox.showerror("Fichier introuvable", f"Fichier source introuvable : {path}")
            log_error(f"FileNotFoundError during source analysis: {path}")
            self.update_progress(0, "Échec de l'analyse")
        except PermissionError:
            messagebox.showerror("Permission refusée", f"Permission refusée : {path}")
            log_error(f"PermissionError during source analysis: {path}")
            self.update_progress(0, "Échec de l'analyse")
        except OSError as e:
            messagebox.showerror("Erreur système", f"Erreur système : {e}")
            log_error(f"OSError during source analysis: {e}")
            self.update_progress(0, "Échec de l'analyse")
    
    def analyze_destination(self):
        """Analyze destination directory"""
        path = self.dest_path.get().strip()
        if not path:
            messagebox.showwarning("Aucun répertoire sélectionné", "Veuillez d'abord sélectionner un répertoire de destination")
            log_warning("Analyse destination tentée sans répertoire sélectionné")
            return
        
        if not os.path.isdir(path):
            messagebox.showerror("Répertoire introuvable", "Le répertoire sélectionné n'existe pas")
            log_error(f"Destination directory not found: {path}")
            return
        
        try:
            self.update_progress(1, "Analyse de la destination...")
            
            stat = os.statvfs(path)
            available_space = stat.f_bavail * stat.f_frsize
            
            self.display_destination_info(path, available_space)
            
            # Check if source is selected and compare sizes
            if self.source_path.get():
                source_size = os.path.getsize(self.source_path.get())
                if source_size > available_space:
                    messagebox.showwarning(
                        "Espace insuffisant",
                        f"Taille source : {self._format_size(source_size)}\n"
                        f"Espace disponible : {self._format_size(available_space)}"
                    )
                    log_warning(f"Insufficient space for export: need {source_size}, have {available_space}")
            
            self.update_progress(0, "Analyse terminée — Prêt")
            self.status_label.config(text="Destination prête — Prêt à exporter")
            
            log_info(f"Destination analysis completed - Available: {self._format_size(available_space)}")
            
        except OSError as e:
            messagebox.showerror("Erreur système", f"Erreur système : {e}")
            log_error(f"OSError during destination analysis: {e}")
            self.update_progress(0, "Échec de l'analyse")
    
    def display_source_info(self, path, file_size):
        """Display source image information"""
        self.source_info_text.config(state="normal")
        self.source_info_text.delete(1.0, "end")
        
        info = f"File: {os.path.basename(path)}\nSize: {self._format_size(file_size)} ({file_size:,} bytes)\nPath: {path}"
        
        self.source_info_text.insert(1.0, info)
        self.source_info_text.config(state="disabled")
    
    def display_destination_info(self, path, available_space):
        """Display destination directory information"""
        self.dest_info_text.config(state="normal")
        self.dest_info_text.delete(1.0, "end")
        
        info = f"Directory: {path}\nAvailable Space: {self._format_size(available_space)} ({available_space:,} bytes)"
        
        self.dest_info_text.insert(1.0, info)
        self.dest_info_text.config(state="disabled")
    
    def validate_inputs(self):
        """Validate user inputs"""
        source_path = self.source_path.get().strip()
        dest_path = self.dest_path.get().strip()
        
        if not source_path:
            messagebox.showwarning("Aucune source", "Veuillez sélectionner un fichier image source")
            log_warning("Validation failed: no source file selected")
            return False
        
        if not os.path.isfile(source_path):
            messagebox.showerror("Source invalide", f"Fichier source introuvable : {source_path}")
            log_error(f"Validation failed: source file not found - {source_path}")
            return False
        
        if not dest_path:
            messagebox.showwarning("Aucune destination", "Veuillez sélectionner un répertoire de destination")
            log_warning("Validation failed: no destination directory selected")
            return False
        
        if not os.path.isdir(dest_path):
            messagebox.showerror("Destination invalide", f"Répertoire de destination introuvable : {dest_path}")
            log_error(f"Validation failed: destination directory not found - {dest_path}")
            return False
        
        # Check available space
        try:
            source_size = os.path.getsize(source_path)
            stat = os.statvfs(dest_path)
            available = stat.f_bavail * stat.f_frsize
            
            if source_size > available:
                messagebox.showerror(
                    "Espace insuffisant",
                    f"Espace insuffisant dans la destination.\n\n"
                    f"Requis : {self._format_size(source_size)}\n"
                    f"Disponible : {self._format_size(available)}"
                )
                log_error(f"Validation failed: insufficient space - need {source_size}, have {available}")
                return False
        except (OSError, ValueError) as e:
            log_warning(f"Could not check space: {e}")
        
        log_info("Toutes les entrées sont valides")
        return True
    
    def start_export(self):
        """Start the export operation"""
        if not self.validate_inputs():
            return
        
        source_file = self.source_path.get()
        dest_dir = self.dest_path.get()
        file_name = os.path.basename(source_file)
        dest_file = os.path.join(dest_dir, file_name)
        
        # Check if destination file exists
        if os.path.exists(dest_file):
            result = messagebox.askyesno(
                "Fichier existant",
                f"Le fichier de destination existe déjà :\n{dest_file}\n\nÉcraser ?"
            )
            if not result:
                log_warning(f"Export annulé — fichier de destination déjà existant : {dest_file}")
                return
        
        # Confirmation dialog
        source_size = os.path.getsize(source_file)
        msg = f"CONFIRMATION D'EXPORT D'IMAGE\n\n"
        msg += f"Source : {file_name} ({self._format_size(source_size)})\n"
        msg += f"Destination : {dest_dir}\n\n"
        msg += f"⚠ L'opération peut prendre plusieurs minutes\n"
        msg += f"⚠ Le fichier de destination sera créé ou écrasé\n"
        msg += f"⚠ Le fichier source ne sera PAS modifié\n\n"
        msg += f"Continuer ?"
        
        if not messagebox.askyesno("Confirmer l'export", msg):
            log_warning("User cancelled export operation")
            return
        
        log_info(f"Starting export operation")
        log_info(f"Source file: {source_file}")
        log_info(f"Destination: {dest_file}")
        log_info(f"Source size: {self._format_size(source_size)}")
        
        self.operation_active = True
        self.export_btn.config(state="disabled")
        self.status_label.config(text="Export en cours...")
        
        thread = threading.Thread(
            target=self._export_worker,
            args=(source_file, dest_dir)
        )
        thread.daemon = True
        thread.start()
    
    def _export_worker(self, source_file, dest_dir):
        """Worker thread for export operation"""
        try:
            self._export_image_rsync(source_file, dest_dir)
            
            dest_file = os.path.join(dest_dir, os.path.basename(source_file))
            dest_size = os.path.getsize(dest_file)
            
            msg = f"EXPORT TERMINÉ !\n\n"
            msg += f"Source : {os.path.basename(source_file)}\n"
            msg += f"Destination : {dest_file}\n"
            msg += f"Taille : {self._format_size(dest_size)}\n\n"
            msg += f"✓ Image exportée avec succès\n"
            msg += f"✓ Fichier source intact\n"
            msg += f"✓ Prêt à l'emploi\n"
            
            log_info(f"Export completed successfully")
            log_info(f"Output file size: {self._format_size(dest_size)}")
            
            self.root.after(0, lambda: messagebox.showinfo("Export terminé", msg))
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Export échoué : {e}"
            log_error(f"CalledProcessError during export: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Export échoué", error_msg))
        except OSError as e:
            error_msg = f"Erreur système : {e}"
            log_error(f"OSError during export: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Erreur système", error_msg))
        except FileNotFoundError as e:
            error_msg = f"Commande rsync introuvable. Veuillez installer rsync."
            log_error(f"FileNotFoundError during export: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Erreur de commande", error_msg))
        finally:
            self.root.after(0, self.reset_ui)
    
    def _export_image_rsync(self, source_file, dest_dir):
        """Export image using rsync with progress tracking"""
        self.update_progress(1, "Démarrage de l'export rsync...")
        
        source_size = os.path.getsize(source_file)
        file_name = os.path.basename(source_file)
        
        log_info(f"Starting rsync export: {source_file} -> {dest_dir}")
        log_info(f"File size: {self._format_size(source_size)}")
        
        try:
            # Build rsync command
            cmd = ['rsync', '-av', '--progress', source_file, dest_dir]
            
            log_info(f"Executing: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            bytes_transferred = 0
            last_progress_percent = -1
            
            # Parse rsync output for progress
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                
                # Look for progress lines like: "12345 56%  1.23MB/s  0:00:10"
                if '%' in line and '/' in line:
                    try:
                        # Extract percentage from rsync output
                        match = re.search(r'(\d+)%', line)
                        if match:
                            percent = int(match.group(1))
                            
                            # Extract speed
                            speed_match = re.search(r'([\d.]+\w+/s)', line)
                            speed = speed_match.group(1) if speed_match else "calculating..."
                            
                            # Extract time remaining
                            time_match = re.search(r'(\d+:\d+:\d+)', line)
                            time_left = time_match.group(1) if time_match else "calculating..."
                            
                            status = f"Export : {percent}% | Vitesse : {speed} | Temps restant : {time_left}"
                            
                            if percent != last_progress_percent:
                                last_progress_percent = percent
                                self.update_progress(percent, status)
                                log_info(f"Progress: {status}")
                    except (ValueError, AttributeError) as e:
                        log_warning(f"Could not parse rsync output: {line}")
                
                # Log other output
                elif line and not line.startswith('sending'):
                    log_info(f"rsync : {line}")
            
            returncode = process.wait()
            
            if returncode == 0:
                self.update_progress(100, "Export terminé avec succès")
                log_info(f"Export completed successfully")
            else:
                error_msg = f"rsync failed with return code {returncode}"
                log_error(error_msg)
                raise subprocess.CalledProcessError(returncode, 'rsync', error_msg)
        
        except FileNotFoundError:
            error_msg = "Commande rsync introuvable. Installez-la : sudo apt install rsync"
            log_error(error_msg)
            self.update_progress(0, error_msg)
            raise FileNotFoundError(error_msg)
        except subprocess.TimeoutExpired:
            error_msg = "Délai de la commande rsync dépassé"
            log_error(error_msg)
            self.update_progress(0, error_msg)
            raise subprocess.TimeoutExpired('rsync', 300, error_msg)
        except OSError as e:
            error_msg = f"Erreur système pendant l'export : {e}"
            log_error(error_msg)
            self.update_progress(0, error_msg)
            raise OSError(error_msg)
    
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
            text="Prêt — Sélectionnez une image source et un répertoire de destination",
            font=C.FONT_NORMAL, style="Card.TLabel"
        )
        self.status_label.pack(anchor="center", pady=(0, 4))

        ttk.Separator(bottom_frame, orient="horizontal").pack(fill="x", pady=(0, 8))

        button_frame = ttk.Frame(bottom_frame, style="TFrame")
        button_frame.pack(fill="x", pady=(0, 6))

        self.export_btn = ttk.Button(
            button_frame,
            text="DÉMARRER L'EXPORT",
            command=self.start_export,
            state="normal",
            style="Primary.TButton"
        )
        self.export_btn.pack(fill="x", pady=(0, 8), ipady=6)

        secondary_frame = ttk.Frame(button_frame, style="TFrame")
        secondary_frame.pack(fill="x")

        ttk.Button(secondary_frame, text="Rafraîchir",
                   command=self.analyze_source, width=12).pack(side="left")
        ttk.Button(secondary_frame, text="Effacer",
                   command=self.clear_fields, width=14).pack(side="left", padx=(6, 0))
        ttk.Button(secondary_frame, text="Fermer",
                   command=self.close_window, width=12).pack(side="right")

        # ── En-tête ───────────────────────────────────────────────────────
        header_frame = ttk.Frame(main_frame, style="TFrame")
        header_frame.pack(fill="x", pady=(0, 18))

        ttk.Label(header_frame, text="Export d'images virtuelles",
                  style="Title.TLabel").pack(anchor="center")
        ttk.Label(header_frame,
                  text="Exporter des images de disques virtuels avec rsync et suivi de progression",
                  style="Subtitle.TLabel").pack(anchor="center", pady=(2, 0))

        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=(0, 16))

        # ── Fichier image source ──────────────────────────────────────────
        source_frame = ttk.LabelFrame(main_frame, text="Fichier image source",
                                      style="TLabelframe")
        source_frame.pack(fill="x", pady=(0, 12))

        path_frame = ttk.Frame(source_frame, style="Card.TFrame")
        path_frame.pack(fill="x", pady=(0, 6))

        self.source_entry = ttk.Entry(path_frame, textvariable=self.source_path,
                                      font=C.FONT_NORMAL, style="TEntry")
        self.source_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Button(path_frame, text="Parcourir",
                   command=self.browse_source_file).pack(side="right", padx=(0, 5))
        ttk.Button(path_frame, text="Analyser",
                   command=self.analyze_source).pack(side="right")

        # ── Informations source ───────────────────────────────────────────
        source_info_frame = ttk.LabelFrame(main_frame, text="Informations source",
                                           style="TLabelframe")
        source_info_frame.pack(fill="x", pady=(0, 12))

        self.source_info_text = tk.Text(source_info_frame, height=3,
                                        state="disabled", wrap="word")
        theme.style_text_widget(self.source_info_text)
        src_scrollbar = ttk.Scrollbar(source_info_frame, orient="vertical",
                                      command=self.source_info_text.yview)
        self.source_info_text.configure(yscrollcommand=src_scrollbar.set)
        self.source_info_text.pack(side="left", fill="both", expand=True)
        src_scrollbar.pack(side="right", fill="y")

        # ── Répertoire de destination ─────────────────────────────────────
        dest_frame = ttk.LabelFrame(main_frame, text="Répertoire de destination",
                                    style="TLabelframe")
        dest_frame.pack(fill="x", pady=(0, 12))

        dest_path_frame = ttk.Frame(dest_frame, style="Card.TFrame")
        dest_path_frame.pack(fill="x", pady=(0, 6))

        self.dest_entry = ttk.Entry(dest_path_frame, textvariable=self.dest_path,
                                    font=C.FONT_NORMAL, style="TEntry")
        self.dest_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Button(dest_path_frame, text="Parcourir",
                   command=self.browse_destination_dir).pack(side="right", padx=(0, 5))
        ttk.Button(dest_path_frame, text="Dossier personnel",
                   command=self.browse_home_dest).pack(side="right", padx=(0, 5))
        ttk.Button(dest_path_frame, text="Analyser",
                   command=self.analyze_destination).pack(side="right")

        # ── Informations destination ──────────────────────────────────────
        dest_info_frame = ttk.LabelFrame(main_frame, text="Informations destination",
                                         style="TLabelframe")
        dest_info_frame.pack(fill="x", pady=(0, 12))

        self.dest_info_text = tk.Text(dest_info_frame, height=3,
                                      state="disabled", wrap="word")
        theme.style_text_widget(self.dest_info_text)
        dst_scrollbar = ttk.Scrollbar(dest_info_frame, orient="vertical",
                                      command=self.dest_info_text.yview)
        self.dest_info_text.configure(yscrollcommand=dst_scrollbar.set)
        self.dest_info_text.pack(side="left", fill="both", expand=True)
        dst_scrollbar.pack(side="right", fill="y")

        # ── État du système ───────────────────────────────────────────────
        self.prereq_frame = ttk.LabelFrame(main_frame, text="État du système",
                                           style="TLabelframe")
        self.prereq_frame.pack(fill="x", pady=(0, 12))

        self.prereq_label = ttk.Label(self.prereq_frame,
                                      text="Vérification des outils requis...",
                                      font=C.FONT_NORMAL, style="Card.TLabel")
        self.prereq_label.pack(anchor="w")

        # ── Progression ───────────────────────────────────────────────────
        progress_frame = ttk.LabelFrame(main_frame, text="Progression de l'export",
                                        style="TLabelframe")
        progress_frame.pack(fill="x", pady=(0, 12))

        self.progress = ttk.Progressbar(progress_frame, mode='determinate',
                                        maximum=100, length=400)
        self.progress.pack(fill="x", pady=(0, 8))

        self.progress_label = ttk.Label(progress_frame, text="Prêt à démarrer",
                                        font=("Segoe UI", 10, "bold"),
                                        style="Card.TLabel")
        self.progress_label.pack(anchor="center")
    
    def clear_fields(self):
        """Clear all fields"""
        self.source_path.set("")
        self.dest_path.set("")
        self.source_info_text.config(state="normal")
        self.source_info_text.delete(1.0, tk.END)
        self.source_info_text.config(state="disabled")
        self.dest_info_text.config(state="normal")
        self.dest_info_text.delete(1.0, tk.END)
        self.dest_info_text.config(state="disabled")
        self.progress.config(value=0)
        self.progress_label.config(text="Prêt à démarrer")
        self.status_label.config(text="Prêt — Sélectionnez une image source et un répertoire de destination")
        log_info("Champs export effacés")
    
    def update_progress(self, percentage, status):
        """Update progress bar with percentage value"""
        def update():
            self.progress.config(value=min(percentage, 100))
            self.progress_label.config(text=f"{status} - {percentage}%")
        
        self.root.after(0, update)
    
    def reset_ui(self):
        """Reset UI after operation"""
        self.operation_active = False
        self.export_btn.config(state="normal")
        self.status_label.config(text="Export terminé — Prêt pour un nouvel export")
        log_info("Interface réinitialisée après l'export")
    
    @staticmethod
    def _format_size(bytes_size):
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"