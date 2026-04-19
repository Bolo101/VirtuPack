#!/usr/bin/env python3
"""
P2V Converter GUI Module - Enhanced with Disk Mounting Support and QCOW2 Resize
Provides the graphical user interface for the Physical to Virtual converter
with support for mounting unmounted disks for output storage and resizing QCOW2 images
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
from pathlib import Path
from log_handler import (log_info, log_error, log_warning, generate_session_pdf,
generate_log_file_pdf, session_start, session_end,
log_application_exit, get_current_session_logs,
is_session_active)
from utils import (get_disk_list, format_bytes, get_disk_info, is_system_disk)
from vm import (check_output_space, check_qemu_tools, create_vm_from_disk, validate_vm_name)
from disk_mount_dialog import DiskMountDialog
from qcow2_resize_dialog import QCow2CloneResizerGUI
from image_format_converter import ImageFormatConverter
from delete_file import FileDeleteManager
from virt_launcher import VirtManagerLauncher
from ciphering import LUKSCiphering
from export import VirtualImageExporter
import theme


class P2VConverterGUI:
    """GUI class for the P2V Converter application"""

    def __init__(self, root):
        self.root = root
        self.root.title("Convertisseur Physique vers Virtuel (P2V)")
        self.root.geometry("600x500")
        self.root.attributes("-fullscreen", True)

        # Operation control variables
        self.operation_running = False
        self.stop_requested = False

        # VM configuration variables
        self.vm_name    = tk.StringVar(value="converted_vm")
        self.output_path = tk.StringVar(value="/tmp/p2v_output")

        # Store current disk list for reference
        self.current_disks = []

        # Apply dark theme
        self._style = theme.apply_theme(self.root)

        # Configure the main window
        self.setup_window()

        # Create the GUI elements
        self.create_widgets()

        # Set up window close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.exit_application)

        # Start logging session and log GUI initialization
        session_start()
        log_info("P2V Converter GUI initialized successfully")

        # Check for required tools
        self.check_prerequisites()

        # Start periodic log update
        self.update_log_from_session()

    # ─────────────────────────────────────────────────────────────────────────
    def setup_window(self):
        """Configure the main window properties with responsive design"""
        self.root.resizable(True, True)

        screen_width  = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        window_width  = int(screen_width  * 0.90)
        window_height = int(screen_height * 0.90)

        self.root.geometry(f"{window_width}x{window_height}+50+50")
        self.root.minsize(800, 600)

        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        try:
            self.root.iconname("P2V Converter")
        except (tk.TclError, AttributeError):
            pass

    def get_screen_layout_config(self):
        """Determine layout configuration based on screen dimensions"""
        screen_width  = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        if screen_width < 1024:
            tools_columns, font_size = 2, 8
        elif screen_width < 1400:
            tools_columns, font_size = 3, 9
        elif screen_width < 1600:
            tools_columns, font_size = 4, 9
        else:
            tools_columns, font_size = 5, 10

        if screen_height < 768:
            log_height = 4
        elif screen_height < 1080:
            log_height = 6
        else:
            log_height = 8

        return {
            "tools_columns": tools_columns,
            "font_size": font_size,
            "log_height": log_height,
            "space_height": 4,
        }

    def is_disk_unavailable_for_conversion(self, device_path):
        """Check if a disk is unavailable for conversion"""
        try:
            if is_system_disk(device_path):
                return True, "This is an active system disk currently in use"

            from utils import has_mounted_partitions
            if has_mounted_partitions(device_path):
                return True, "This disk has mounted partitions"

            try:
                with open("/proc/mounts", "r") as f:
                    mounts_content = f.read()
                device_name = device_path.replace("/dev/", "")
                for line in mounts_content.split("\n"):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            mounted_device = parts[0]
                            mount_point    = parts[1]
                            if mounted_device.startswith("/dev/") and device_name in mounted_device:
                                if mounted_device != device_path:
                                    return True, f"Partition {mounted_device} is mounted at {mount_point}"
            except (IOError, OSError) as e:
                log_warning(f"Could not read mount status: {e}")

            return False, "Available for conversion"

        except FileNotFoundError as e:
            log_error(f"File not found checking disk availability: {e}")
            return True, "Unable to verify disk status - file not found"
        except PermissionError as e:
            log_error(f"Permission denied checking disk availability: {e}")
            return True, "Unable to verify disk status - permission denied"
        except subprocess.CalledProcessError as e:
            log_error(f"Command failed checking disk availability: {e}")
            return True, "Unable to verify disk status - command failed"
        except (ValueError, IndexError) as e:
            log_error(f"Error parsing disk information: {e}")
            return True, "Unable to verify disk status - data error"
        except OSError as e:
            log_error(f"System error checking disk availability: {e}")
            return True, "Unable to verify disk status - system error"

    # ─────────────────────────────────────────────────────────────────────────
    def create_widgets(self):
        """Create all GUI widgets"""
        self.create_header_frame()
        self.create_main_frame()
        self.create_status_frame()

    # ── Header ────────────────────────────────────────────────────────────────
    def create_header_frame(self):
        """Create the header frame with title and action buttons"""
        C = theme

        header = tk.Frame(self.root, bg=C.BG_CARD, pady=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        # Left: branding
        brand = tk.Frame(header, bg=C.BG_CARD)
        brand.grid(row=0, column=0, sticky="ew", padx=(16, 10), pady=10)

        tk.Label(brand, text="Convertisseur P2V",
                 font=C.FONT_TITLE, bg=C.BG_CARD, fg=C.TEXT_PRIMARY
                 ).pack(anchor="w")
        tk.Label(brand, text="Conversion Physique vers Machine Virtuelle",
                 font=C.FONT_SMALL, bg=C.BG_CARD, fg=C.TEXT_SECONDARY
                 ).pack(anchor="w")

        # Right: buttons
        btn_bar = tk.Frame(header, bg=C.BG_CARD)
        btn_bar.grid(row=0, column=1, sticky="e", padx=(0, 16), pady=10)

        screen_width = self.root.winfo_screenwidth()
        btn_width = 12 if screen_width < 1024 else (15 if screen_width < 1400 else 18)

        self.session_pdf_btn = ttk.Button(btn_bar, text="Journal session",
                                          command=self.generate_session_pdf,
                                          width=btn_width)
        self.session_pdf_btn.pack(side="left", padx=(0, 4))

        self.file_pdf_btn = ttk.Button(btn_bar, text="Journal complet",
                                       command=self.generate_log_file_pdf,
                                       width=btn_width)
        self.file_pdf_btn.pack(side="left", padx=(0, 4))

        self.exit_btn = ttk.Button(btn_bar, text="Quitter",
                                   command=self.exit_application, width=10)
        self.exit_btn.pack(side="left", padx=(0, 4))

        self.poweroff_btn = ttk.Button(btn_bar, text="Éteindre",
                                       command=self.power_off_system,
                                       style="Danger.TButton", width=10)
        self.poweroff_btn.pack(side="left")

        # Bottom border line
        tk.Frame(self.root, bg=theme.BORDER, height=1).grid(row=0, column=0,
                                                              sticky="sew", pady=0)

    # ── Main content ──────────────────────────────────────────────────────────
    def create_main_frame(self):
        """Create the main content frame"""
        C = theme

        main_frame = ttk.Frame(self.root, style="TFrame", padding=(12, 10))
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.grid_rowconfigure(5, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        layout_config = self.get_screen_layout_config()

        # ── Source disk selection ─────────────────────────────────────────
        source_frame = ttk.LabelFrame(main_frame, text="Sélection du disque source",
                                       style="TLabelframe")
        source_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        source_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(source_frame, text="Disque physique :",
                  font=C.FONT_LABEL, style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w")

        self.source_var   = tk.StringVar()
        self.source_combo = ttk.Combobox(source_frame, textvariable=self.source_var,
                                          state="readonly", font=C.FONT_NORMAL)
        self.source_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.source_combo.bind("<<ComboboxSelected>>", self.on_source_selected)

        self.refresh_btn = ttk.Button(source_frame, text="Actualiser les disques",
                                       command=self.refresh_disks)
        self.refresh_btn.grid(row=0, column=2, padx=(10, 0))

        # ── VM Configuration ──────────────────────────────────────────────
        vm_config_frame = ttk.LabelFrame(main_frame, text="Configuration de la VM",
                                          style="TLabelframe")
        vm_config_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        vm_config_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(vm_config_frame, text="Nom de la VM :",
                  font=C.FONT_LABEL, style="Card.TLabel"
                  ).grid(row=0, column=0, sticky="w")
        vm_name_entry = ttk.Entry(vm_config_frame, textvariable=self.vm_name,
                                   font=C.FONT_NORMAL)
        vm_name_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        vm_name_entry.bind("<KeyRelease>", self.validate_vm_name_input)

        ttk.Label(vm_config_frame, text="Répertoire de sortie :",
                  font=C.FONT_LABEL, style="Card.TLabel"
                  ).grid(row=1, column=0, sticky="w", pady=(10, 0))

        output_frame = ttk.Frame(vm_config_frame, style="Card.TFrame")
        output_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10, 0))
        output_frame.grid_columnconfigure(0, weight=1)

        output_entry = ttk.Entry(output_frame, textvariable=self.output_path,
                                  font=C.FONT_NORMAL)
        output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        # Primary buttons: Browse / Mount / Delete
        primary_tools_frame = ttk.Frame(output_frame, style="Card.TFrame")
        primary_tools_frame.grid(row=0, column=1, sticky="ew")

        browse_btn = ttk.Button(primary_tools_frame, text="Parcourir",
                                 command=self.browse_output_dir)
        browse_btn.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        mount_btn = ttk.Button(primary_tools_frame, text="Monter le disque",
                                command=self.mount_disk_dialog)
        mount_btn.grid(row=0, column=1, padx=(0, 3), sticky="ew")

        delete_files_btn = ttk.Button(primary_tools_frame, text="Supprimer des fichiers",
                                       command=self.open_delete_files_manager)
        delete_files_btn.grid(row=0, column=2, sticky="ew")

        # Utility tools row
        tools_lbl = ttk.Label(vm_config_frame, text="Outils utilitaires :",
                               font=("Segoe UI", 9, "bold"), style="Card.Muted.TLabel")
        tools_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 8))

        tools_columns = layout_config["tools_columns"]
        tools = [
            ("Redimensionner QCOW2",     self.open_qcow2_resizer),
            ("Convertisseur de format", self.open_format_converter),
            ("Chiffrement LUKS",  self.open_luks_ciphering),
            ("Virt-Manager",     self.open_virt_manager),
            ("Exporter l'image",     self.open_image_exporter),
        ]

        current_row, current_col = 3, 0
        for tool_name, tool_command in tools:
            if current_col >= tools_columns:
                current_row += 1
                current_col  = 0

            cell = ttk.Frame(vm_config_frame, style="Card.TFrame")
            cell.grid(row=current_row, column=current_col,
                       sticky="ew", padx=(10, 5), pady=(0, 5))
            cell.grid_columnconfigure(0, weight=1)

            ttk.Button(cell, text=tool_name, command=tool_command
                       ).pack(fill="x", expand=True)

            current_col += 1

        if current_col > 0:
            for col in range(tools_columns):
                vm_config_frame.grid_columnconfigure(col, weight=1)

        ttk.Label(vm_config_frame,
                  text="Redimensionner QCOW2 · Convertir formats · Chiffrer/déchiffrer · Gérer VMs · Exporter images",
                  style="Card.Muted.TLabel", wraplength=400
                  ).grid(row=current_row + 1, column=0, columnspan=2,
                          sticky="w", pady=(5, 0))

        # ── Storage space info ────────────────────────────────────────────
        space_frame = ttk.LabelFrame(main_frame, text="Informations sur l'espace disque",
                                      style="TLabelframe")
        space_frame.grid(row=6, column=0, sticky="ew", pady=(0, 10))

        self.space_info_text = tk.Text(
            space_frame,
            height=layout_config["space_height"],
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        theme.style_text_widget(self.space_info_text)
        space_scrollbar = ttk.Scrollbar(space_frame, orient="vertical",
                                         command=self.space_info_text.yview)
        self.space_info_text.configure(yscrollcommand=space_scrollbar.set)

        self.space_info_text.grid(row=0, column=0, sticky="nsew")
        space_scrollbar.grid(row=0, column=1, sticky="ns")
        space_frame.grid_rowconfigure(0, weight=1)
        space_frame.grid_columnconfigure(0, weight=1)

        # ── Control buttons ───────────────────────────────────────────────
        control_frame = ttk.Frame(main_frame, style="TFrame")
        control_frame.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        control_frame.grid_columnconfigure(1, weight=1)

        self.check_space_btn = ttk.Button(control_frame, text="Vérifier l'espace",
                                           command=self.check_space_requirements)
        self.check_space_btn.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.convert_btn = ttk.Button(control_frame, text="Démarrer la conversion P2V",
                                       command=self.start_conversion,
                                       style="Primary.TButton")
        self.convert_btn.grid(row=0, column=1, padx=(0, 8), sticky="w")

        self.stop_btn = ttk.Button(control_frame, text="Arrêter l'opération",
                                    command=self.stop_operation,
                                    style="Danger.TButton",
                                    state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=1, padx=(0, 8), sticky="e")

        self.clear_log_btn = ttk.Button(control_frame, text="Effacer l'affichage",
                                         command=self.clear_log_display)
        self.clear_log_btn.grid(row=0, column=2)

        # ── Operation Log ─────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(main_frame, text="Journal des opérations",
                                    style="TLabelframe", padding=(4, 4))
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        text_frame = ttk.Frame(log_frame, style="TFrame")
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        self.log_text = tk.Text(text_frame, wrap=tk.WORD, state=tk.DISABLED,
                                 font=(theme.FONT_MONO[0], layout_config["font_size"]))
        theme.style_text_widget(self.log_text)

        scrollbar_v = ttk.Scrollbar(text_frame, orient="vertical",
                                     command=self.log_text.yview)
        scrollbar_h = ttk.Scrollbar(text_frame, orient="horizontal",
                                     command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=scrollbar_v.set,
                                 xscrollcommand=scrollbar_h.set)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar_v.grid(row=0, column=1, sticky="ns")
        scrollbar_h.grid(row=1, column=0, sticky="ew")

        # Log level tags
        self.log_text.tag_configure("INFO",    foreground=theme.INFO)
        self.log_text.tag_configure("WARNING", foreground=theme.WARNING)
        self.log_text.tag_configure("ERROR",   foreground=theme.ERROR)
        self.log_text.tag_configure("SUCCESS", foreground=theme.SUCCESS)

        self.last_log_count = 0

    # ── Status bar ────────────────────────────────────────────────────────────
    def create_status_frame(self):
        """Create the status bar at the bottom"""
        C = theme

        status_frame = tk.Frame(self.root, bg=C.BG_CARD)
        status_frame.grid(row=2, column=0, sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)

        # Top border
        tk.Frame(status_frame, bg=C.BORDER, height=1).pack(fill="x")

        inner = tk.Frame(status_frame, bg=C.BG_CARD, padx=14, pady=6)
        inner.pack(fill="x")
        inner.columnconfigure(1, weight=1)

        screen_width = self.root.winfo_screenwidth()
        bar_length   = 150 if screen_width < 1024 else 300

        # Progress label
        tk.Label(inner, text="Progression :", bg=C.BG_CARD,
                 fg=C.TEXT_SECONDARY, font=C.FONT_SMALL
                 ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(inner, variable=self.progress_var,
                                             maximum=100, length=bar_length)
        self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self.progress_label = tk.Label(inner, text="0%", width=5,
                                        bg=C.BG_CARD, fg=C.TEXT_SECONDARY,
                                        font=C.FONT_SMALL)
        self.progress_label.grid(row=0, column=2, sticky="w", padx=(0, 20))

        tk.Label(inner, text="Statut :", bg=C.BG_CARD,
                 fg=C.TEXT_SECONDARY, font=C.FONT_SMALL
                 ).grid(row=0, column=3, sticky="w", padx=(0, 6))

        self.status_var   = tk.StringVar(value="Prêt")
        self.status_label = tk.Label(inner, textvariable=self.status_var,
                                      bg=C.BG_CARD, fg=C.TEXT_PRIMARY,
                                      font=("Segoe UI", 9, "bold"))
        self.status_label.grid(row=0, column=4, sticky="w")

        wrap_len = 300 if screen_width < 1024 else 500
        self.operation_details = tk.Label(inner, text="",
                                           bg=C.BG_CARD, fg=C.TEXT_MUTED,
                                           font=C.FONT_SMALL, wraplength=wrap_len,
                                           anchor="w")
        self.operation_details.grid(row=1, column=0, columnspan=5,
                                     sticky="w", pady=(4, 0))

        # Bootstrap disk list
        self.root.after(100, self.refresh_disks)

    # =========================================================================
    # All business logic below is UNCHANGED from the original file
    # =========================================================================

    def open_image_exporter(self):
        """Open the Virtual Image Exporter dialog"""
        try:
            log_info("Opening Virtual Image Exporter dialog")
            exporter = VirtualImageExporter(self.root)
            log_info("Virtual Image Exporter dialog opened successfully")
        except ImportError as e:
            log_error(f"Virtual Image Exporter not available: {e}")
            messagebox.showerror("Feature Not Available",
                                 "Virtual Image Exporter feature is not available.\n\n"
                                 "Please ensure export.py is in the same directory.\n\n"
                                 f"Missing dependency: {e}")
        except tk.TclError as e:
            log_error(f"Window creation error: {e}")
            messagebox.showerror("Window Error", f"Failed to create exporter window:\n\n{e}")
        except (AttributeError, TypeError) as e:
            log_error(f"Internal error initializing exporter: {e}")
            messagebox.showerror("Internal Error", f"Failed to initialize exporter:\n\n{e}")
        except OSError as e:
            log_error(f"System error opening exporter: {e}")
            messagebox.showerror("System Error", f"Failed to open exporter:\n\n{e}")
        except ValueError as e:
            log_error(f"Invalid value for exporter: {e}")
            messagebox.showerror("Value Error", f"Failed to initialize exporter:\n\n{e}")
        except MemoryError:
            log_error("Insufficient memory to open Virtual Image Exporter")
            messagebox.showerror("Memory Error", "Failed to open exporter: insufficient memory")
        except FileNotFoundError as e:
            log_error(f"Required file not found: {e}")
            messagebox.showerror("File Not Found", f"Failed to open exporter:\n\n{e}")
        except PermissionError as e:
            log_error(f"Permission denied: {e}")
            messagebox.showerror("Permission Error", f"Failed to open exporter:\n\n{e}")

    def open_qcow2_resizer(self):
        """Open the QCOW2 resizer dialog as a modal window"""
        try:
            log_info("Opening QCOW2 Clone Resizer dialog")
            resizer_app = QCow2CloneResizerGUI(self.root)
            log_info("QCOW2 Clone Resizer dialog opened")
        except ImportError as e:
            log_error(f"QCOW2 Clone Resizer not available: {e}")
            messagebox.showerror("Feature Not Available",
                                 "QCOW2 Clone Resizer feature is not available.\n\n"
                                 "Please ensure qcow2_resize_dialog.py is in the same directory.")
        except AttributeError as e:
            log_error(f"Error initializing QCOW2 Clone Resizer: {e}")
            messagebox.showerror("Initialization Error", f"Failed to initialize QCOW2 Clone Resizer:\n\n{e}")
        except tk.TclError as e:
            log_error(f"Window creation error: {e}")
            messagebox.showerror("Window Error", f"Failed to create QCOW2 Clone Resizer window:\n\n{e}")
        except (TypeError, ValueError, MemoryError, OSError) as e:
            log_error(f"Error opening QCOW2 Clone Resizer: {e}")
            messagebox.showerror("Error", f"Failed to open QCOW2 Clone Resizer:\n\n{e}")

    def open_luks_ciphering(self):
        """Open the LUKS Encryption dialog as a modal window"""
        try:
            log_info("Opening LUKS Encryption dialog")
            ciphering_app = LUKSCiphering(self.root)
            log_info("LUKS Encryption dialog opened")
        except ImportError as e:
            log_error(f"LUKS Ciphering not available: {e}")
            messagebox.showerror("Feature Not Available",
                                 "LUKS Encryption feature is not available.\n\n"
                                 "Please ensure ciphering.py is in the same directory.\n\n"
                                 f"Missing dependency: {e}")
        except (AttributeError, tk.TclError, TypeError, ValueError, MemoryError,
                OSError, FileNotFoundError, PermissionError) as e:
            log_error(f"Error opening LUKS Ciphering: {e}")
            messagebox.showerror("Error", f"Failed to open LUKS Encryption:\n\n{e}")

    def open_delete_files_manager(self):
        """Open the Delete Files Manager for interactive file deletion"""
        try:
            log_info("Opening Delete Files Manager")
            file_manager = FileDeleteManager(self.root)
            stats = file_manager.delete_files_interactive()
            if stats["removed"] > 0 or stats["failed"] > 0:
                summary_msg = (f"File Deletion Summary: {stats['removed']} deleted, "
                               f"{stats['failed']} failed")
                log_info(summary_msg)
                self.operation_details.config(
                    text=summary_msg,
                    fg=theme.SUCCESS if stats["failed"] == 0 else theme.WARNING,
                )
        except (ImportError, AttributeError, tk.TclError, TypeError, ValueError,
                MemoryError, OSError, PermissionError, FileNotFoundError) as e:
            log_error(f"Error opening Delete Files Manager: {e}")
            messagebox.showerror("Error", f"Failed to open Delete Files Manager:\n\n{e}")

    def open_format_converter(self):
        """Open the Format Converter dialog as a modal window"""
        try:
            log_info("Opening Format Converter dialog")
            converter_app = ImageFormatConverter(self.root)
            log_info("Format Converter dialog opened")
        except (ImportError, AttributeError, tk.TclError, TypeError, ValueError,
                MemoryError, OSError, FileNotFoundError, PermissionError) as e:
            log_error(f"Error opening Format Converter: {e}")
            messagebox.showerror("Error", f"Failed to open Format Converter:\n\n{e}")

    def mount_disk_dialog(self):
        """Show dialog to select and mount a disk for output storage"""
        try:
            dialog = DiskMountDialog(self.root)
            self.root.wait_window(dialog.dialog)
            if dialog.result:
                self.output_path.set(dialog.result)
                log_info(f"Selected mounted disk path: {dialog.result}")
                if self.source_var.get():
                    self.root.after(100, self.check_space_requirements)
        except (PermissionError, OSError, ImportError, subprocess.CalledProcessError,
                ValueError, AttributeError, TypeError, tk.TclError) as e:
            log_error(f"Error in disk mount dialog: {e}")
            messagebox.showerror("Error", str(e))

    def open_virt_manager(self):
        """Open virt-manager with proper permissions for VM management"""
        try:
            log_info("Checking virt-manager availability")
            missing_tools, available = VirtManagerLauncher.check_virt_manager()

            if not available:
                error_msg = "Required virtualization tools are missing:\n\n"
                error_msg += "\n".join(f"• {tool}" for tool in missing_tools)
                error_msg += "\n\nPlease install the missing packages"
                log_error(f"Virt-manager check failed: {', '.join(missing_tools)}")
                messagebox.showerror("Missing Virtualization Tools", error_msg)
                return

            log_info("Virt-manager is available, launching...")

            confirm_msg = (
                "Lancer Virt-Manager\n\n"
                "Cela ouvrira virt-manager pour la gestion des machines virtuelles.\n\n"
                "Vous pouvez :\n"
                "• Créer de nouvelles VMs\n"
                "• Importer/gérer des images VM existantes\n"
                "• Configurer le matériel de la VM\n"
                "• Installer des systèmes d'exploitation invités\n\n"
                "Continuer ?"
            )
            if not messagebox.askyesno("Lancer Virt-Manager", confirm_msg):
                log_info("User cancelled virt-manager launch")
                return

            log_info("User confirmed virt-manager launch")
            self.status_var.set("Lancement de virt-manager...")
            self.root.update_idletasks()

            try:
                VirtManagerLauncher.launch_virt_manager(log_callback=log_info)
                log_info("Virt-manager launched successfully")
                self.status_var.set("Virt-manager est en cours d'exécution")
                self.operation_details.config(text="Virt-manager ouvert en arrière-plan",
                                               fg=theme.SUCCESS)
                messagebox.showinfo("Virt-Manager lancé",
                                    "Virt-manager est maintenant en cours d'exécution.\n\n"
                                    "Vous pouvez importer ou créer des machines virtuelles à partir de vos images disque.\n"
                                    "Fermez cette fenêtre et virt-manager une fois terminé.")
            except (FileNotFoundError, PermissionError, OSError,
                    subprocess.CalledProcessError, subprocess.TimeoutExpired,
                    subprocess.SubprocessError, ImportError, AttributeError, TypeError) as e:
                log_error(f"Error launching virt-manager: {e}")
                messagebox.showerror("Launch Error", str(e))

        except (tk.TclError, KeyError, ValueError) as e:
            log_error(f"GUI/config error: {e}")
            messagebox.showerror("Error", str(e))
        finally:
            self.status_var.set("Prêt")

    def launch_virt_manager_with_image(self, image_path):
        """Launch virt-manager with a specific VM image"""
        try:
            if not os.path.exists(image_path):
                log_error(f"Image file not found: {image_path}")
                messagebox.showerror("File Not Found", f"Image file not found: {image_path}")
                return

            log_info(f"Launching virt-manager with image: {image_path}")
            self.status_var.set("Préparation de l'image VM...")
            self.root.update_idletasks()

            try:
                VirtManagerLauncher.launch_virt_manager_with_image(
                    image_path, log_callback=log_info
                )
                log_info(f"Virt-manager launched with image: {image_path}")
                self.status_var.set("Virt-manager est en cours d'exécution")
                self.operation_details.config(
                    text=f"Virt-manager ouvert avec : {Path(image_path).name}",
                    fg=theme.SUCCESS,
                )
                messagebox.showinfo(
                    "Virt-Manager lancé",
                    f"Virt-manager is now running with your VM image.\n\n"
                    f"File: {Path(image_path).name}\n"
                    f"Size: {VirtManagerLauncher.format_size(os.path.getsize(image_path))}",
                )
            except (FileNotFoundError, PermissionError, OSError,
                    subprocess.SubprocessError) as e:
                log_error(f"Error launching virt-manager with image: {e}")
                messagebox.showerror("Error", str(e))

        except tk.TclError as e:
            log_error(f"GUI error: {e}")
            messagebox.showerror("GUI Error", str(e))
        finally:
            self.status_var.set("Prêt")

    # ── Misc / Business logic (unchanged) ─────────────────────────────────────

    def check_prerequisites(self):
        tools_available, message = check_qemu_tools()
        if not tools_available:
            log_error(f"Prerequisites check failed: {message}")
            messagebox.showerror("Prérequis manquants",
                                 f"Outils requis manquants :\n\n{message}\n\n"
                                 "Veuillez installer les paquets requis :\n"
                                 "• qemu-utils (for qemu-img)\n"
                                 "• coreutils (for dd)")
        else:
            log_info("All prerequisites are available")

    def power_off_system(self):
        """Power off the system after confirmation."""
        try:
            if self.operation_running:
                messagebox.showwarning("Opération en cours",
                                       "Cannot power off while an operation is running.\n\n"
                                       "Please stop the current operation first.")
                return

            result = messagebox.askyesno(
                "Confirmation d'extinction",
                "Êtes-vous sûr de vouloir éteindre le système ?\n\n"
                "Cela va :\n"
                "• Fermer toutes les applications\n"
                "• Enregistrer les journaux de session\n"
                "• Éteindre le système\n\n"
                "Continuer avec l'extinction ?",
            )
            if not result:
                log_info("Power off cancelled by user")
                return

            log_info("System power off requested by user")

            try:
                if is_session_active():
                    log_info("Ending session before system power off")
                    session_end()
            except (AttributeError, IOError, OSError, KeyError, ValueError) as e:
                log_warning(f"Error ending session before power off: {e}")

            self.status_var.set("Arrêt du système en cours...")
            self.root.update_idletasks()

            for cmd in (["systemctl", "poweroff"], ["shutdown", "-h", "now"], ["poweroff"]):
                try:
                    subprocess.run(cmd, check=True, timeout=5)
                    return
                except (subprocess.CalledProcessError, FileNotFoundError,
                        subprocess.TimeoutExpired):
                    continue

            log_error("All power off methods failed")
            messagebox.showerror("Échec de l'extinction",
                                 "Impossible d'éteindre le système.\n\n"
                                 "Méthodes essayées :\n"
                                 "• systemctl poweroff\n"
                                 "• shutdown -h now\n"
                                 "• poweroff\n\n"
                                 "Veuillez exécuter avec sudo ou utiliser le bouton d'alimentation du système.")

        except PermissionError as e:
            log_error(f"Permission denied: {e}")
            messagebox.showerror("Permission Error",
                                 f"Permission denied:\n\n{e}\n\nPower off requires root privileges.")
        except (OSError, subprocess.SubprocessError, tk.TclError,
                AttributeError, TypeError) as e:
            log_error(f"Error during power off: {e}")
            messagebox.showerror("Error", str(e))

    def update_log_from_session(self):
        """Update log display from session logs"""
        try:
            if is_session_active():
                session_logs = get_current_session_logs()
                if len(session_logs) > self.last_log_count:
                    new_logs = session_logs[self.last_log_count:]
                    self.log_text.config(state=tk.NORMAL)
                    for log_entry in new_logs:
                        if "] " in log_entry and ": " in log_entry:
                            try:
                                parts     = log_entry.split("] ", 1)
                                timestamp = parts[0] + "]"
                                rest      = parts[1]
                                level_parts = rest.split(": ", 1)
                                level   = level_parts[0]
                                message = level_parts[1] if len(level_parts) > 1 else rest
                                self.log_text.insert(tk.END, f"{timestamp} ", "INFO")
                                self.log_text.insert(tk.END, f"{level}: {message}\n", level.upper())
                            except (IndexError, ValueError, AttributeError):
                                self.log_text.insert(tk.END, f"{log_entry}\n", "INFO")
                        else:
                            self.log_text.insert(tk.END, f"{log_entry}\n", "INFO")
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
                    self.last_log_count = len(session_logs)
        except (AttributeError, KeyError, TypeError, IOError, OSError):
            pass
        self.root.after(1000, self.update_log_from_session)

    def clear_log_display(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        log_info("Log display cleared (session logs preserved)")
        self.last_log_count = 0

    def refresh_disks(self):
        try:
            log_info("Refreshing disk list")
            self.current_disks = get_disk_list()

            if self.current_disks:
                disk_options    = []
                unavailable_count = 0

                for disk in self.current_disks:
                    disk_info = f"{disk['device']} ({disk['size']}) - {disk['model']}"
                    if disk["label"] and disk["label"] != "No Label":
                        disk_info += f" [{disk['label']}]"

                    is_unavailable, reason = self.is_disk_unavailable_for_conversion(disk["device"])
                    if is_unavailable:
                        unavailable_count += 1
                        if "active system disk" in reason.lower():
                            disk_info = f"SYSTÈME : {disk_info} [ACTIF]"
                        elif "mounted" in reason.lower():
                            disk_info = f"MONTÉ : {disk_info} [EN COURS D'UTILISATION]"
                        else:
                            disk_info = f"OCCUPÉ : {disk_info} [INDISPONIBLE]"

                    disk_options.append(disk_info)

                self.source_combo["values"] = disk_options
                if self.source_var.get() not in disk_options:
                    self.source_var.set("")

                log_info(f"Found {len(self.current_disks)} disk(s)")
                available_count = len(self.current_disks) - unavailable_count
                if unavailable_count > 0:
                    self.status_var.set(
                        f"Trouvé {len(self.current_disks)} disque(s) "
                        f"({available_count} disponible(s), {unavailable_count} indisponible(s))"
                    )
                else:
                    self.status_var.set(f"Trouvé {len(self.current_disks)} disque(s) (tous disponibles)")
            else:
                log_warning("Aucun disque trouvé")
                self.status_var.set("Aucun disque trouvé")
                self.source_combo["values"] = []

        except (OSError, subprocess.CalledProcessError, FileNotFoundError,
                ValueError, KeyError, PermissionError, AttributeError) as e:
            log_error(f"Error refreshing disks: {e}")
            messagebox.showerror("Error", str(e))
            self.status_var.set("Erreur lors de l'actualisation des disques")

    def get_selected_disk_info(self):
        selected = self.source_var.get()
        if not selected:
            return None
        device_path = (selected.split(" ")[1]
                       if selected.startswith("SYSTEM:") else selected.split(" ")[0])
        for disk in self.current_disks:
            if disk["device"] == device_path:
                return disk
        return None

    def on_source_selected(self, event=None):
        selected = self.source_var.get()
        if not selected:
            return

        device_path = (selected.split(" ")[1]
                       if selected.startswith("SYSTEM:") else selected.split(" ")[0])

        is_unavailable, reason = self.is_disk_unavailable_for_conversion(device_path)
        if is_unavailable:
            warning_message = f"Impossible de sélectionner le disque\n\nDisque sélectionné : {device_path}\nRaison : {reason}\n\n"
            if "active system disk" in reason.lower():
                warning_message += ("La conversion d'un disque système actif est dangereuse.\n\n"
                                    "Recommandations :\n"
                                    "• Sélectionnez un autre disque inactif\n"
                                    "• Démarrez sur un support live USB/CD pour convertir ce disque en toute sécurité")
            elif "mounted" in reason.lower():
                warning_message += ("La conversion d'un disque avec des partitions montées peut provoquer une corruption.\n\n"
                                    "Recommandations :\n"
                                    "• Démontez toutes les partitions de ce disque d'abord\n"
                                    "• Utilisez la commande 'umount' pour démonter en toute sécurité")
            else:
                warning_message += "Veuillez sélectionner un autre disque qui n'est pas en cours d'utilisation."

            messagebox.showerror("Disque indisponible pour la conversion", warning_message)
            self.source_var.set("")
            log_warning(f"User attempted to select unavailable disk: {device_path} - {reason}")
            self.status_var.set("Sélection du disque refusée")
            self.operation_details.config(text=f"Impossible de sélectionner le disque : {reason}",
                                           fg=theme.ERROR)

            self.space_info_text.config(state=tk.NORMAL)
            self.space_info_text.delete(1.0, tk.END)
            self.space_info_text.insert(
                tk.END,
                "Veuillez sélectionner un disque non monté et non utilisé pour la conversion P2V.\n\n"
                "Disques compatibles pour la conversion :\n"
                "• Disques de stockage secondaires non montés\n"
                "• Disques externes non montés\n"
                "• Disques de systèmes démarrés depuis un support live",
            )
            self.space_info_text.config(state=tk.DISABLED)
            return

        log_info(f"Selected source disk: {device_path}")
        disk_name = device_path.split("/")[-1]
        self.vm_name.set(f"{disk_name}_vm")
        self.operation_details.config(text="", fg=theme.TEXT_MUTED)

        disk_info = self.get_selected_disk_info()
        if disk_info and self.output_path.get():
            self.root.after(100, self.check_space_requirements)

    def validate_vm_name_input(self, event=None):
        name = self.vm_name.get()
        is_valid, message = validate_vm_name(name)
        if not is_valid and name:
            self.operation_details.config(text=f"Attention : {message}", fg=theme.WARNING)
        else:
            self.operation_details.config(text="", fg=theme.TEXT_MUTED)

    def browse_output_dir(self):
        selected_dir = filedialog.askdirectory(
            title="Select Output Directory for VM Files",
            initialdir=self.output_path.get(),
        )
        if selected_dir:
            self.output_path.set(selected_dir)
            log_info(f"Output directory selected: {selected_dir}")
            if self.source_var.get():
                self.root.after(100, self.check_space_requirements)

    def check_space_requirements(self):
        try:
            source     = self.source_var.get()
            output_dir = self.output_path.get()

            if not source:
                messagebox.showwarning("Avertissement", "Veuillez d'abord sélectionner un disque source")
                return
            if not output_dir:
                messagebox.showwarning("Avertissement", "Veuillez spécifier un répertoire de sortie")
                return

            device_path = (source.split(" ")[1]
                           if source.startswith(("SYSTEM:", "MOUNTED:", "BUSY:"))
                           else source.split(" ")[0])

            log_info(f"Checking space requirements for {device_path}")
            has_space, space_message = check_output_space(output_dir, device_path)
            disk_info = get_disk_info(device_path)

            self.space_info_text.config(state=tk.NORMAL)
            self.space_info_text.delete(1.0, tk.END)

            info_text  = f"Disque source : {device_path}\n"
            info_text += f"Modèle : {disk_info.get('model', 'Inconnu')}\n"
            if disk_info.get("label") and disk_info["label"] != "Unknown":
                info_text += f"Label: {disk_info['label']}\n"
            info_text += f"Répertoire de sortie : {output_dir}\n\n"
            info_text += space_message

            if is_system_disk(device_path):
                info_text += "\n\nWarning: This is an active system disk!"

            self.space_info_text.insert(tk.END, info_text)
            self.space_info_text.config(state=tk.DISABLED)

            if has_space:
                log_info("Space check passed")
                self.operation_details.config(text="Espace disponible suffisant",
                                               fg=theme.SUCCESS)
            else:
                log_error("Space check failed - insufficient space")
                self.operation_details.config(text="Espace insuffisant", fg=theme.ERROR)
                messagebox.showwarning("Espace insuffisant",
                                       f"Espace disponible insuffisant !\n\n{space_message}")

        except (OSError, IOError, ValueError, TypeError,
                subprocess.CalledProcessError, FileNotFoundError) as e:
            log_error(f"Error checking space requirements: {e}")
            messagebox.showerror("Error", str(e))
            self.operation_details.config(text="Vérification de l'espace échouée", fg=theme.ERROR)

    def start_conversion(self):
        source     = self.source_var.get()
        vm_name    = self.vm_name.get().strip()
        output_dir = self.output_path.get().strip()

        if not source:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner un disque source")
            return
        if not vm_name:
            messagebox.showwarning("Avertissement", "Veuillez saisir un nom de VM")
            return
        if not output_dir:
            messagebox.showwarning("Avertissement", "Veuillez spécifier un répertoire de sortie")
            return

        is_valid, validation_message = validate_vm_name(vm_name)
        if not is_valid:
            messagebox.showerror("Nom de VM invalide", validation_message)
            return

        device_path = (source.split(" ")[1]
                       if source.startswith(("SYSTEM:", "MOUNTED:", "BUSY:"))
                       else source.split(" ")[0])

        is_unavailable, reason = self.is_disk_unavailable_for_conversion(device_path)
        if is_unavailable:
            messagebox.showerror(
                "Disque indisponible",
                f"Conversion bloquée\n\n"
                f"Le disque sélectionné ({device_path}) n'est pas disponible pour la conversion.\n\n"
                f"Raison : {reason}\n\n"
                f"Veuillez sélectionner un autre disque ou résoudre le problème avant de convertir.",
            )
            self.refresh_disks()
            return

        try:
            has_space, space_message = check_output_space(output_dir, device_path)
            if not has_space:
                if not messagebox.askyesno("Avertissement : espace insuffisant",
                                           f"Avertissement d'espace\n\n{space_message}\n\n"
                                           f"Continuer quand même ? La conversion risque d'échouer."):
                    return
        except (OSError, IOError, ValueError, TypeError, KeyError,
                subprocess.CalledProcessError, FileNotFoundError) as e:
            log_warning(f"Error checking space before conversion: {e}")

        try:
            disk_info = get_disk_info(device_path)
            confirmation_text = (
                f"Confirmation de la conversion P2V\n\n"
                f"Disque source : {device_path}\n"
                f"Modèle : {disk_info.get('model', 'Inconnu')}\n"
                f"Taille : {disk_info.get('size_human', 'Inconnue')}\n"
            )
            if disk_info.get("label") and disk_info["label"] != "Unknown":
                confirmation_text += f"Label: {disk_info['label']}\n"
            confirmation_text += (
                f"Nom VM : {vm_name}\n"
                f"Répertoire de sortie : {output_dir}\n\n"
                f"Cela créera une machine virtuelle qcow2 compressée.\n"
                f"Le processus peut prendre un temps considérable.\n\n"
                f"Continuer la conversion ?"
            )
        except (OSError, IOError, ValueError, KeyError, AttributeError):
            confirmation_text = (
                f"Confirmation de la conversion P2V\n\n"
                f"Disque source : {device_path}\n"
                f"Nom VM : {vm_name}\n"
                f"Répertoire de sortie : {output_dir}\n\n"
                f"Continuer la conversion ?"
            )

        if not messagebox.askyesno("Confirmer la conversion P2V", confirmation_text):
            return

        self.operation_running = True
        self.stop_requested    = False

        conversion_thread = threading.Thread(
            target=self._conversion_worker,
            args=(device_path, output_dir, vm_name),
        )
        conversion_thread.daemon = True
        conversion_thread.start()

        self.convert_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.refresh_btn.config(state=tk.DISABLED)
        self.check_space_btn.config(state=tk.DISABLED)
        self.source_combo.config(state=tk.DISABLED)
        self.status_var.set("Conversion P2V en cours...")

    def _conversion_worker(self, source_device, output_dir, vm_name):
        try:
            log_info(f"Starting P2V conversion: {source_device} -> {vm_name}.qcow2")

            def progress_callback(percent, status):
                self.root.after(0, lambda: self._update_progress(percent, status))

            def stop_check():
                return self.stop_requested

            output_file = create_vm_from_disk(source_device, output_dir, vm_name,
                                               progress_callback, stop_check)

            if not self.stop_requested:
                log_info("P2V conversion completed successfully")
                final_size = os.path.getsize(output_file)
                log_info(f"VM created: {output_file} ({format_bytes(final_size)})")
                completion_text = (
                    f"Conversion P2V effectuée avec succès !\n\n"
                    f"Fichier VM : {output_file}\n"
                    f"Taille : {format_bytes(final_size)}\n\n"
                    f"Vous pouvez maintenant utiliser ce fichier qcow2 avec :\n"
                    f"• Virtualisation QEMU/KVM\n"
                    f"• VirtualBox (après conversion)\n"
                    f"• Autres plateformes de virtualisation supportant qcow2\n\n"
                    f"Pour démarrer la VM avec QEMU :\n"
                    f'qemu-system-x86_64 -hda "{output_file}" -m 2048\n\n'
                    f"Utilisez le bouton 'Redimensionner QCOW2' pour optimiser la taille si nécessaire."
                )
                self.root.after(0, lambda: messagebox.showinfo("Conversion terminée",
                                                                completion_text))

        except FileNotFoundError as e:
            log_error(f"Required command or file not found: {e}")
            self.root.after(0, lambda: messagebox.showerror("Command Error",
                                                             f"P2V conversion failed:\n\n{e}"))
        except subprocess.CalledProcessError as e:
            log_error(f"Command execution failed: {e}")
            self.root.after(0, lambda: messagebox.showerror("Command Error",
                                                             f"P2V conversion failed:\n\n{e}"))
        except subprocess.TimeoutExpired as e:
            log_error(f"Command timed out: {e}")
            self.root.after(0, lambda: messagebox.showerror("Timeout Error",
                                                             f"P2V conversion failed:\n\n{e}"))
        except PermissionError as e:
            log_error(f"Permission denied: {e}")
            self.root.after(0, lambda: messagebox.showerror("Permission Error",
                                                             f"P2V conversion failed:\n\n{e}"))
        except (OSError, IOError, ValueError, TypeError, AttributeError,
                KeyError, IndexError, MemoryError, RuntimeError, UnicodeError) as e:
            log_error(f"Error during conversion: {e}")
            self.root.after(0, lambda: messagebox.showerror("Error",
                                                             f"P2V conversion failed:\n\n{e}"))
        except KeyboardInterrupt:
            log_warning("P2V conversion cancelled by user")
            self.root.after(0, lambda: messagebox.showinfo("Annulée",
                                                            "Conversion P2V annulée par l'utilisateur"))
        finally:
            self.root.after(0, self._reset_ui_after_operation)

    def _update_progress(self, percent, status):
        percent = max(0, min(100, percent))
        self.progress_var.set(percent)
        self.progress_label.config(text=f"{percent:.1f}%")
        self.operation_details.config(text=status, fg=theme.INFO)
        self.root.update_idletasks()

    def _reset_ui_after_operation(self):
        self.operation_running = False
        self.convert_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.refresh_btn.config(state=tk.NORMAL)
        self.check_space_btn.config(state=tk.NORMAL)
        self.source_combo.config(state="readonly")
        self.progress_var.set(0)
        self.progress_label.config(text="0%")
        self.status_var.set("Prêt")
        self.operation_details.config(text="", fg=theme.TEXT_MUTED)

    def stop_operation(self):
        if self.operation_running:
            self.stop_requested = True
            log_warning("Stop requested by user")
            self.status_var.set("Arrêt...")
            self.operation_details.config(text="Arrêt en cours, veuillez patienter...",
                                           fg=theme.WARNING)

    def exit_application(self):
        if self.operation_running:
            result = messagebox.askyesno("Confirmation de fermeture",
                                         "Une opération est en cours.\n\n"
                                         "Êtes-vous sûr de vouloir quitter ?\n"
                                         "Cela arrêtera l'opération en cours.")
            if result:
                self.stop_requested = True
                log_warning("Application exit requested during operation")
                self.root.after(1000, self._force_exit)
            return

        result = messagebox.askyesno("Confirmation de fermeture",
                                     "Êtes-vous sûr de vouloir quitter le convertisseur P2V ?")
        if result:
            self._perform_exit("GUI Exit button")

    def _force_exit(self):
        self._perform_exit("Forced exit during operation")

    def _perform_exit(self, reason):
        try:
            log_application_exit(reason)
            if is_session_active():
                session_end()
        except (AttributeError, IOError, OSError, KeyError, ValueError):
            print("Warning: Error during session cleanup")
        finally:
            self.root.quit()
            self.root.destroy()

    # ── External-storage helpers (detect / mount / unmount / export) ──────────

    def _get_external_disks(self) -> list:
        import subprocess as _sp
        import json as _json

        result = []
        try:
            raw  = _sp.run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MODEL,MOUNTPOINT"],
                           stdout=_sp.PIPE, stderr=_sp.PIPE).stdout.decode()
            data = _json.loads(raw)
        except Exception as e:
            log_error(f"lsblk JSON failed: {e}")
            return result

        for dev in data.get("blockdevices", []):
            dev_name = dev.get("name", "")
            dev_type = dev.get("type", "")
            if dev_type not in ("disk",):
                continue
            if dev_name.startswith("loop"):
                continue
            if is_system_disk(f"/dev/{dev_name}"):
                continue

            partitions = []
            mount_map  = {}
            children = dev.get("children") or []
            if children:
                for child in children:
                    p_name = child.get("name", "")
                    if child.get("type") == "part":
                        partitions.append(p_name)
                        mount_map[p_name] = child.get("mountpoint") or None
            else:
                partitions.append(dev_name)
                mount_map[dev_name] = dev.get("mountpoint") or None

            result.append({
                "device":       dev_name,
                "path":         f"/dev/{dev_name}",
                "size":         dev.get("size", "?"),
                "model":        (dev.get("model") or "").strip(),
                "partitions":   partitions,
                "mount_points": mount_map,
            })

        return result

    def _mount_partition(self, partition: str):
        import tempfile as _tf

        mount_dir = _tf.mkdtemp(prefix="p2v_export_")
        try:
            r = subprocess.run(["mount", f"/dev/{partition}", mount_dir],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if r.returncode != 0:
                err = r.stderr.decode().strip()
                log_error(f"mount /dev/{partition} -> {mount_dir} failed: {err}")
                try:
                    os.rmdir(mount_dir)
                except OSError:
                    pass
                return None
            log_info(f"Mounted /dev/{partition} at {mount_dir}")
            return mount_dir
        except FileNotFoundError:
            log_error("mount command not found")
            return None
        except Exception as e:
            log_error(f"Unexpected error mounting /dev/{partition}: {e}")
            return None

    def _unmount_partition(self, mount_dir: str) -> None:
        try:
            r = subprocess.run(["umount", mount_dir],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if r.returncode != 0:
                log_error(f"umount {mount_dir} failed: {r.stderr.decode().strip()}")
            else:
                log_info(f"Unmounted {mount_dir}")
        except Exception as e:
            log_error(f"Error during umount {mount_dir}: {e}")
        finally:
            try:
                os.rmdir(mount_dir)
            except OSError:
                pass

    def _show_disk_picker(self, external_disks: list):
        C = theme
        result = {"partition": None, "already_mounted": False, "mount_point": None}

        dlg = tk.Toplevel(self.root)
        dlg.title("Sélectionner le support externe")
        dlg.configure(bg=C.BG)
        dlg.grab_set()
        dlg.resizable(False, False)
        theme.apply_theme(dlg)

        ttk.Label(dlg, text="Choisissez le support externe pour l'export PDF",
                  font=C.FONT_LABEL, padding=(10, 10)
                  ).pack(fill=tk.X)

        ttk.Label(dlg,
                  text="Seuls les disques hors système sont listés.\n"
                       "Le support sera monté automatiquement si nécessaire.",
                  style="Muted.TLabel", padding=(10, 0, 10, 6)
                  ).pack(fill=tk.X)

        frame = ttk.Frame(dlg, padding=(10, 0, 10, 6))
        frame.pack(fill=tk.BOTH, expand=True)

        lb = tk.Listbox(frame, width=70, height=12, selectmode=tk.SINGLE, activestyle="dotbox")
        theme.style_listbox(lb)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        entries = []
        for disk in external_disks:
            model_str = f" [{disk['model']}]" if disk["model"] else ""
            lb.insert(tk.END, f"── {disk['path']}  {disk['size']}{model_str}")
            lb.itemconfig(tk.END, foreground=C.ACCENT, background=C.BG_CARD)
            entries.append(None)
            for part in disk["partitions"]:
                mp     = disk["mount_points"].get(part)
                status = f"monté sur {mp}" if mp else "non monté"
                lb.insert(tk.END, f"     /dev/{part:<14}  {status}")
                entries.append((part, mp is not None, mp))

        btn_frame = ttk.Frame(dlg, padding=(10, 6))
        btn_frame.pack(fill=tk.X)

        def on_select():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning("Aucune sélection",
                                       "Veuillez sélectionner une partition.", parent=dlg)
                return
            entry = entries[sel[0]]
            if entry is None:
                messagebox.showwarning("Sélection invalide",
                                       "Veuillez sélectionner une partition,\n"
                                       "pas un en-tête de disque.", parent=dlg)
                return
            result.update({"partition": entry[0], "already_mounted": entry[1],
                           "mount_point": entry[2]})
            dlg.destroy()

        ttk.Button(btn_frame, text="Sélectionner", command=on_select,
                   style="Primary.TButton").pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Annuler", command=dlg.destroy).pack(side=tk.LEFT, padx=4)

        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width()  - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        dlg.geometry(f"+{x}+{y}")
        self.root.wait_window(dlg)

        return result["partition"], result["already_mounted"], result["mount_point"]

    def _request_external_export_path(self, default_filename: str):
        external_disks = self._get_external_disks()
        if not external_disks:
            messagebox.showerror("Aucun support externe détecté",
                                 "Aucun disque externe n'a été détecté.\n\n"
                                 "Branchez une clé USB, un disque dur externe ou tout autre "
                                 "support amovible, puis réessayez.")
            return None

        partition, already_mounted, existing_mp = self._show_disk_picker(external_disks)
        if not partition:
            return None

        self._pending_unmount_dir = None
        if already_mounted and existing_mp:
            mount_point = existing_mp
        else:
            self.status_var.set(f"Montage de /dev/{partition}…")
            self.root.update_idletasks()
            mount_point = self._mount_partition(partition)
            if not mount_point:
                messagebox.showerror("Erreur de montage",
                                     f"Impossible de monter /dev/{partition}.\n\n"
                                     "Vérifiez que le support est correctement branché et "
                                     "que le système de fichiers est supporté (ext4, NTFS, FAT32…).")
                self.status_var.set("Prêt")
                return None
            self._pending_unmount_dir = mount_point

        chosen_path = filedialog.asksaveasfilename(
            title="Exporter le PDF — support externe",
            initialdir=mount_point,
            initialfile=default_filename,
            defaultextension=".pdf",
            filetypes=[("Fichiers PDF", "*.pdf"), ("Tous les fichiers", "*.*")],
        )

        if not chosen_path:
            if self._pending_unmount_dir:
                self.status_var.set(f"Démontage de /dev/{partition}…")
                self.root.update_idletasks()
                self._unmount_partition(self._pending_unmount_dir)
                self._pending_unmount_dir = None
            self.status_var.set("Prêt")
            return None

        mp_norm   = mount_point.rstrip("/") + "/"
        path_norm = os.path.abspath(chosen_path).rstrip("/") + "/"
        if not path_norm.startswith(mp_norm):
            messagebox.showwarning("Destination invalide",
                                   "Le chemin choisi n'est pas sur le support externe monté.\n"
                                   f"Veuillez choisir un emplacement sous : {mount_point}")
            if self._pending_unmount_dir:
                self._unmount_partition(self._pending_unmount_dir)
                self._pending_unmount_dir = None
            return None

        return chosen_path

    def _finalize_export(self) -> None:
        if getattr(self, "_pending_unmount_dir", None):
            self.status_var.set("Démontage du support externe…")
            self.root.update_idletasks()
            self._unmount_partition(self._pending_unmount_dir)
            self._pending_unmount_dir = None
            self.status_var.set("Support externe démonté.")
            log_info("Support externe démonté avec succès après export.")

    # ── PDF generation ────────────────────────────────────────────────────────

    def generate_session_pdf(self):
        from datetime import datetime as _dt
        default_name = f"p2v_session_{_dt.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        export_path  = self._request_external_export_path(default_name)
        if not export_path:
            log_info("Export PDF session annulé par l'utilisateur.")
            self.status_var.set("Prêt")
            return

        try:
            log_info("Génération du PDF de session…")
            self.session_pdf_btn.config(state=tk.DISABLED)
            self.status_var.set("Génération du PDF…")
            pdf_path = generate_session_pdf(output_path=export_path)
            self._finalize_export()
            messagebox.showinfo("PDF Exporté",
                                f"PDF de session exporté avec succès !\n\nEnregistré : {pdf_path}")
            log_info(f"PDF de session exporté : {pdf_path}")
        except (ValueError, PermissionError, OSError, IOError,
                ImportError, AttributeError, TypeError) as e:
            log_error(f"Error generating session PDF: {e}")
            messagebox.showerror("Erreur PDF", f"Impossible de générer le PDF de session :\n\n{e}")
        finally:
            self.session_pdf_btn.config(state=tk.NORMAL)
            self.status_var.set("Prêt")

    def generate_log_file_pdf(self):
        from datetime import datetime as _dt
        default_name = f"p2v_complete_log_{_dt.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        export_path  = self._request_external_export_path(default_name)
        if not export_path:
            log_info("Export PDF journal complet annulé par l'utilisateur.")
            self.status_var.set("Prêt")
            return

        try:
            log_info("Génération du PDF journal complet…")
            self.file_pdf_btn.config(state=tk.DISABLED)
            self.status_var.set("Génération du PDF…")
            pdf_path = generate_log_file_pdf(output_path=export_path)
            self._finalize_export()
            messagebox.showinfo("PDF Exporté",
                                f"PDF journal complet exporté avec succès !\n\nEnregistré : {pdf_path}")
            log_info(f"PDF journal complet exporté : {pdf_path}")
        except (FileNotFoundError, PermissionError, OSError, IOError,
                UnicodeDecodeError, ImportError, AttributeError, TypeError,
                KeyError, ValueError) as e:
            log_error(f"Error generating log file PDF: {e}")
            messagebox.showerror("Erreur PDF", f"Échec de génération du PDF :\n\n{e}")
        finally:
            self.file_pdf_btn.config(state=tk.NORMAL)
            self.status_var.set("Prêt")