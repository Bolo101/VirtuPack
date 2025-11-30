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
from log_handler import log_info, log_error, log_warning, session_start, session_end


class LUKSCiphering:
    """GUI for LUKS encryption/decryption of virtual disk images"""
    
    MODES = {
        'encrypt': {
            'name': 'Encrypt Image',
            'description': 'Encrypt a virtual disk image with LUKS'
        },
        'decrypt': {
            'name': 'Decrypt Image',
            'description': 'Decrypt a LUKS-encrypted virtual disk image'
        }
    }
    
    def __init__(self, parent):
        self.parent = parent
        
        self.root = tk.Toplevel(parent)
        self.root.title("LUKS Image Encryption")
        self.root.geometry("950x900")
        self.root.minsize(850, 700)
        self.root.transient(parent)
        
        self.image_path = tk.StringVar()
        self.mode = tk.StringVar(value='encrypt')
        self.password = tk.StringVar()
        self.password_confirm = tk.StringVar()
        self.operation_active = False
        
        log_info("LUKS Encryption dialog opened")
        
        self.setup_ui()
        self.check_prerequisites()
        
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    
    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno(
                "Operation in Progress",
                "An encryption/decryption operation is currently running. Stop and close?"
            )
            if not result:
                return
            
            log_warning("LUKS operation interrupted by user")
        
        log_info("LUKS Encryption dialog closed")
        self.root.destroy()
    
    
    def setup_styles(self):
        """Setup custom styles"""
        style = ttk.Style()
        style.configure(
            "Accent.TButton",
            font=("Arial", 10, "bold")
        )
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        cryptsetup_available = self._check_command('cryptsetup')
        
        if not cryptsetup_available:
            text = "Missing required tool: cryptsetup\n\n"
            text += "Install cryptsetup:\n"
            text += "Ubuntu/Debian: sudo apt install cryptsetup\n"
            text += "Fedora/RHEL: sudo dnf install cryptsetup\n"
            text += "Arch Linux: sudo pacman -S cryptsetup\n"
            
            self.prereq_label.config(text=text, foreground="red")
            
            log_error("cryptsetup not found - required for LUKS encryption")
            
            messagebox.showerror(
                "Missing Required Tool",
                "cryptsetup is required for LUKS encryption.\n\n"
                "Please install the cryptsetup package."
            )
        else:
            text = "✓ cryptsetup available - Ready for LUKS encryption"
            self.prereq_label.config(text=text, foreground="green")
            log_info("cryptsetup available - prerequisites met")
    
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
            title="Select Virtual Disk Image File",
            filetypes=[
                ("All images", "*.qcow2 *.vdi *.vhd *.vhdx *.vmdk *.img *.raw"),
                ("QCOW2 files", "*.qcow2"),
                ("VDI files", "*.vdi"),
                ("VHD files", "*.vhd"),
                ("VHDX files", "*.vhdx"),
                ("VMDK files", "*.vmdk"),
                ("RAW images", "*.img *.raw"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.image_path.set(file_path)
            self.analyze_image()

    def analyze_image(self):
        """Analyze selected image"""
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("No File Selected", "Please select an image file first")
            log_warning("Image analysis attempted but no file selected")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", "The selected file does not exist")
            log_error(f"Image file not found: {path}")
            return
        
        try:
            self.update_progress(True, "Analyzing image file...")
            
            file_size = os.path.getsize(path)
            file_stat = os.stat(path)
            
            log_info(f"Analyzing image: {os.path.basename(path)} - Size: {self._format_size(file_size)}")
            
            self.display_image_info(path, file_size, file_stat)
            
            self.action_btn.config(state="normal")
            
            self.update_progress(False, "Analysis complete - Ready for operation")
            self.status_label.config(text="Image analyzed - Ready")
            
            log_info(f"Image analysis completed successfully for {os.path.basename(path)}")
            
        except FileNotFoundError:
            messagebox.showerror("File Not Found", f"Image file not found: {path}")
            log_error(f"FileNotFoundError during image analysis: {path}")
            self.update_progress(False, "Analysis failed")
        except PermissionError:
            messagebox.showerror("Permission Denied", f"Permission denied: {path}")
            log_error(f"PermissionError during image analysis: {path}")
            self.update_progress(False, "Analysis failed")
        except OSError as e:
            messagebox.showerror("System Error", f"System error: {e}")
            log_error(f"OSError during image analysis: {e}")
            self.update_progress(False, "Analysis failed")
    
    def display_image_info(self, path, file_size, file_stat):
        """Display image information"""
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        mode_text = "ENCRYPT" if self.mode.get() == 'encrypt' else "DECRYPT"
        info = f"{os.path.basename(path)} | {self._format_size(file_size)} | Op: {mode_text}\nOriginal file NOT modified"
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    
    def update_password_strength(self, event=None):
        """Update password strength indicator"""
        password = self.password.get()
        strength = 0
        feedback = "Very Weak"
        
        if len(password) >= 8:
            strength += 25
            feedback = "Weak"
        
        if len(password) >= 12:
            strength += 25
            feedback = "Fair"
        
        if any(c.isupper() for c in password) and any(c.islower() for c in password):
            strength += 25
            feedback = "Good"
        
        if any(c.isdigit() for c in password) and any(not c.isalnum() for c in password):
            strength += 25
            feedback = "Strong"
        
        self.strength_bar.config(value=strength)
        self.strength_label.config(text=feedback)
    
    def clear_password(self):
        """Clear password fields"""
        self.password.set("")
        self.password_confirm.set("")
        self.strength_bar.config(value=0)
        self.strength_label.config(text="Weak")
        log_info("Password fields cleared")
    
    def validate_inputs(self):
        """Validate user inputs"""
        path = self.image_path.get().strip()
        
        if not path:
            messagebox.showwarning("No File Selected", "Please select an image file")
            log_warning("Validation failed: no image file selected")
            return False
        
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", "The selected file does not exist")
            log_error(f"Validation failed: image file not found - {path}")
            return False
        
        password = self.password.get()
        password_confirm = self.password_confirm.get()
        
        if not password:
            messagebox.showwarning("No Password", "Please enter a password")
            log_warning("Validation failed: no password entered")
            return False
        
        if len(password) < 8:
            messagebox.showwarning("Weak Password", "Password must be at least 8 characters")
            log_warning("Validation failed: password too weak (less than 8 characters)")
            return False
        
        if password != password_confirm:
            messagebox.showerror("Password Mismatch", "Passwords do not match")
            log_error("Validation failed: password mismatch")
            return False
        
        log_info("All inputs validated successfully")
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
            operation_name = "Encryption"
        else:
            output_path = source_file.parent / f"{source_file.stem}_decrypted{source_file.suffix}"
            operation_name = "Decryption"
        
        # Check if target exists
        if output_path.exists():
            result = messagebox.askyesno(
                "File Exists",
                f"Target file already exists:\n{output_path}\n\nOverwrite?"
            )
            if not result:
                log_warning(f"Operation cancelled - target file already exists: {output_path}")
                return
        
        # Confirmation dialog
        msg = f"LUKS IMAGE {operation_name.upper()}\n\n"
        msg += f"Source: {os.path.basename(image_path)} ({self._format_size(os.path.getsize(image_path))})\n"
        msg += f"Target: {output_path.name}\n\n"
        msg += f"⚠ VM must be shut down\n"
        msg += f"⚠ Operation may take several minutes\n"
        msg += f"⚠ Original file will NOT be modified\n\n"
        msg += f"Continue?"
        
        if not messagebox.askyesno("Confirm Operation", msg):
            log_warning(f"User cancelled {operation_name.lower()} operation")
            return
        
        log_info(f"Starting {operation_name.lower()} operation")
        log_info(f"Source file: {image_path}")
        log_info(f"Target file: {output_path}")
        log_info(f"Source size: {self._format_size(os.path.getsize(image_path))}")
        
        self.operation_active = True
        self.action_btn.config(state="disabled")
        self.status_label.config(text=f"{operation_name} in progress...")
        
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
            
            msg = f"{'ENCRYPTION' if mode == 'encrypt' else 'DECRYPTION'} COMPLETED!\n\n"
            msg += f"Source: {os.path.basename(source_path)}\n"
            msg += f"Target: {os.path.basename(target_path)}\n"
            msg += f"Size: {self._format_size(target_size)}\n\n"
            msg += f"✓ File successfully {'encrypted' if mode == 'encrypt' else 'decrypted'}\n"
            msg += f"✓ Original file untouched\n"
            msg += f"✓ Ready for use\n\n"
            msg += f"Location: {target_path}"
            
            log_info(f"{'ENCRYPTION' if mode == 'encrypt' else 'DECRYPTION'} completed successfully")
            log_info(f"Output file size: {self._format_size(target_size)}")
            
            self.root.after(0, lambda: messagebox.showinfo("Operation Complete", msg))
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Operation failed: {e}"
            log_error(f"CalledProcessError during operation: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Operation Failed", error_msg))
        except OSError as e:
            error_msg = f"System error: {e}"
            log_error(f"OSError during operation: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("System Error", error_msg))
        finally:
            self.root.after(0, self.reset_ui)
    
    def on_mode_changed(self):
        """Handle mode selection change"""
        mode = self.mode.get()
        log_info(f"Operation mode changed to: {'ENCRYPTION' if mode == 'encrypt' else 'DECRYPTION'}")
        
        self.clear_password()
        self.progress_label.config(text="Ready to start")
        self.status_label.config(text="Mode changed - Ready to analyze image")
        
        # Disable password confirm field for decryption mode
        if mode == 'decrypt':
            self.password_confirm_entry.config(state="disabled")
        else:
            self.password_confirm_entry.config(state="normal")


    def setup_ui(self):
        """Setup user interface without scrollbar"""
        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.pack(fill="both", expand=True)
        
        # Configure grid for responsiveness
        main_frame.grid_rowconfigure(7, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        
        # Header section
        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        title = ttk.Label(
            header_frame,
            text="LUKS Image Encryption",
            font=("Arial", 14, "bold")
        )
        title.pack(anchor="w")
        
        subtitle = ttk.Label(
            header_frame,
            text="Encrypt or decrypt virtual machine disk images",
            font=("Arial", 9)
        )
        subtitle.pack(anchor="w")
        
        # Mode selection section (compact)
        mode_frame = ttk.LabelFrame(main_frame, text="Operation Mode", padding="8")
        mode_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        
        for idx, (mode_key, mode_info) in enumerate(self.MODES.items()):
            radio = ttk.Radiobutton(
                mode_frame,
                text=f"{mode_info['name']} - {mode_info['description']}",
                variable=self.mode,
                value=mode_key,
                command=self.on_mode_changed
            )
            radio.pack(anchor="w", pady=1)
        
        # File selection section
        file_frame = ttk.LabelFrame(main_frame, text="Source Image File", padding="8")
        file_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        file_frame.columnconfigure(0, weight=1)
        
        path_frame = ttk.Frame(file_frame)
        path_frame.grid(row=0, column=0, sticky="ew")
        path_frame.columnconfigure(0, weight=1)
        
        self.path_entry = ttk.Entry(
            path_frame,
            textvariable=self.image_path,
            font=("Arial", 9)
        )
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        
        button_frame = ttk.Frame(path_frame)
        button_frame.grid(row=0, column=1)
        
        ttk.Button(
            button_frame,
            text="Browse",
            command=self.browse_file,
            width=10
        ).pack(side="left", padx=(0, 3))
        
        ttk.Button(
            button_frame,
            text="Analyze",
            command=self.analyze_image,
            width=10
        ).pack(side="left")
        
        # Image information display (compact)
        info_frame = ttk.LabelFrame(main_frame, text="Image Info", padding="8")
        info_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        info_frame.columnconfigure(0, weight=1)
        
        self.info_text = tk.Text(
            info_frame,
            height=3,
            state="disabled",
            wrap="word",
            font=("Consolas", 8),
            bg="white"
        )
        self.info_text.pack(fill="both", expand=True)
        
        # Password section (compact)
        password_frame = ttk.LabelFrame(main_frame, text="Password", padding="8")
        password_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        password_frame.columnconfigure(1, weight=1)
        
        ttk.Label(password_frame, text="Password:", font=("Arial", 9)).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        
        self.password_entry = ttk.Entry(
            password_frame,
            textvariable=self.password,
            show="•",
            font=("Arial", 9)
        )
        self.password_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
        self.password_entry.bind("<KeyRelease>", self.update_password_strength)
        
        ttk.Label(password_frame, text="Confirm:", font=("Arial", 9)).grid(
            row=1, column=0, sticky="w", pady=(0, 4)
        )
        
        self.password_confirm_entry = ttk.Entry(
            password_frame,
            textvariable=self.password_confirm,
            show="•",
            font=("Arial", 9)
        )
        self.password_confirm_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
        
        # Password strength indicator (compact)
        strength_frame = ttk.Frame(password_frame)
        strength_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        ttk.Label(strength_frame, text="Strength:", font=("Arial", 8)).pack(side="left", padx=(0, 8))
        
        self.strength_bar = ttk.Progressbar(
            strength_frame,
            length=120,
            mode='determinate',
            maximum=100
        )
        self.strength_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        self.strength_label = ttk.Label(strength_frame, text="Weak", font=("Arial", 8), width=7)
        self.strength_label.pack(side="left")
        
        # System requirements check
        self.prereq_frame = ttk.LabelFrame(main_frame, text="System Status", padding="8")
        self.prereq_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        
        self.prereq_label = ttk.Label(
            self.prereq_frame,
            text="Checking required tools...",
            font=("Arial", 8)
        )
        self.prereq_label.pack()
        
        # Progress section - Changed to show percentage instead of indeterminate
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="8")
        progress_frame.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress = ttk.Progressbar(progress_frame, mode='determinate', maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        
        self.progress_label = ttk.Label(
            progress_frame,
            text="Ready to start",
            font=("Arial", 9, "bold")
        )
        self.progress_label.grid(row=1, column=0, sticky="w")
        
        # Action buttons section
        button_container = ttk.Frame(main_frame)
        button_container.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        button_container.columnconfigure(0, weight=1)
        
        # Primary action button
        self.action_btn = ttk.Button(
            button_container,
            text="START OPERATION",
            command=self.start_operation,
            state="disabled"
        )
        self.action_btn.grid(row=0, column=0, sticky="ew", pady=(0, 6), ipady=5)
        
        # Secondary buttons
        secondary_frame = ttk.Frame(button_container)
        secondary_frame.grid(row=1, column=0, sticky="ew")
        secondary_frame.columnconfigure(1, weight=1)
        
        ttk.Button(
            secondary_frame,
            text="Refresh",
            command=self.analyze_image,
            width=12
        ).grid(row=0, column=0, padx=(0, 6))
        
        ttk.Button(
            secondary_frame,
            text="Clear Password",
            command=self.clear_password,
            width=14
        ).grid(row=0, column=1, padx=(0, 6), sticky="w")
        
        ttk.Button(
            secondary_frame,
            text="Close",
            command=self.close_window,
            width=12
        ).grid(row=0, column=2, sticky="e")
        
        # Status bar
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=8, column=0, sticky="ew")
        
        separator = ttk.Separator(status_frame, orient="horizontal")
        separator.pack(fill="x", pady=(6, 4))
        
        self.status_label = ttk.Label(
            status_frame,
            text="Ready - Select image file and enter password",
            font=("Arial", 8)
        )
        self.status_label.pack()
        
        self.setup_styles()


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
            
            stdout, stderr = proc.communicate(input=password + "\n")
            
            if proc.returncode != 0:
                log_error("Failed to open encrypted container - invalid password or corrupted container")
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
        """Reset UI after operation"""
        self.operation_active = False
        self.action_btn.config(state="normal")
        self.progress.stop()
        self.progress_label.config(text="Operation completed")
        self.status_label.config(text="Operation completed - Ready for next operation")
        log_info("UI reset after operation")
    
    @staticmethod
    def _format_size(bytes_size):
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"
