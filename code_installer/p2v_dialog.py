#!/usr/bin/env python3
"""
VirtualPack GUI Module - Enhanced with Disk Mounting Support and QCOW2 Resize
Provides the graphical user interface for the Physical to Virtual converter
with support for mounting unmounted disks for output storage and resizing QCOW2 images
"""

import tkinter as tk
from tkinter import ttk, filedialog
import theme
import os
import subprocess
import threading
from log_handler import (log_info, log_error, log_warning,
                         session_start, session_end,
                         log_application_exit, get_current_session_logs,
                         is_session_active)
from admin_interface import open_admin_panel
from utils import (get_disk_list, format_bytes,get_disk_info, is_system_disk)
from vm import (check_output_space, check_qemu_tools, create_vm_from_disk, validate_vm_name)
from stats_manager import get_conversion_count, record_conversion
from disk_mount_dialog import DiskMountDialog
from qcow2_resize_dialog import QCow2CloneResizerGUI
from image_format_converter import ImageFormatConverter
from delete_file import FileDeleteManager
from virt_launcher import VirtManagerLauncher
from ciphering import LUKSCiphering
from export import VirtualImageExporter

class P2VConverterGUI:
    """GUI class for the VirtualPack Converter application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("VirtualPack)")
        self.root.geometry("600x500")
        self.root.attributes("-fullscreen", True)
        
        # Operation control variables
        self.operation_running = False
        self.stop_requested = False
        
        # VM configuration variables
        self.vm_name = tk.StringVar(value="converted_vm")
        self.output_path = tk.StringVar(value="/tmp/virtualpack_output")
        
        # Conversion counter
        self._counter_var = tk.StringVar(value=str(get_conversion_count()))
        
        # Store current disk list for reference
        self.current_disks = []
        
        # Configure the main window
        self.setup_window()
        
        # Create the GUI elements
        self.create_widgets()
        
        # Set up window close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.exit_application)
        
        # Start logging session and log GUI initialization
        session_start()
        log_info("VirtualPack GUI initialisée avec succès")
        
        # Check for required tools
        self.check_prerequisites()
        
        # Start periodic log update
        self.update_log_from_session()
    
    def setup_window(self):
        """Configure the main window properties with responsive design"""
        theme.apply_theme(self.root)
        self.root.resizable(True, True)
        
        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Use 90% of screen with minimum dimensions
        window_width = int(screen_width * 0.90)
        window_height = int(screen_height * 0.90)
        
        # Set geometry based on screen size
        self.root.geometry(f"{window_width}x{window_height}+50+50")
        self.root.minsize(800, 600)
        
        # Configure grid weights for responsive design
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Set window icon (if available)
        try:
            self.root.iconname("VirtualPack")
        except (tk.TclError, AttributeError):
            pass

    def get_screen_layout_config(self):
        """Determine layout configuration based on screen dimensions"""
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Determine number of tool columns based on width
        if screen_width < 1024:
            tools_columns = 2
            font_size = 8
        elif screen_width < 1400:
            tools_columns = 3
            font_size = 9
        elif screen_width < 1600:
            tools_columns = 4
            font_size = 9
        else:
            tools_columns = 5
            font_size = 10
        
        # Determine log frame height based on screen height
        if screen_height < 768:
            log_height = 4
        elif screen_height < 1080:
            log_height = 6
        else:
            log_height = 8
        
        return {
            'tools_columns': tools_columns,
            'font_size': font_size,
            'log_height': log_height,
            'space_height': 4
        }

    def is_disk_unavailable_for_conversion(self, device_path):
        """
        Check if a disk is unavailable for conversion
        """
        try:
            if is_system_disk(device_path):
                return True, "Ce disque est le disque système actif actuellement utilisé"
            
            from utils import has_mounted_partitions
            if has_mounted_partitions(device_path):
                return True, "Ce disque a des partitions montées"
            
            try:
                with open('/proc/mounts', 'r') as f:
                    mounts_content = f.read()
                    
                device_name = device_path.replace('/dev/', '')
                
                for line in mounts_content.split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            mounted_device = parts[0]
                            mount_point = parts[1]
                            
                            if mounted_device.startswith('/dev/') and device_name in mounted_device:
                                if mounted_device != device_path:
                                    return True, f"La partition {mounted_device} est montée sur {mount_point}"
            
            except IOError as e:
                log_warning(f"Could not read mount status from /proc/mounts: {str(e)}")
            except OSError as e:
                log_warning(f"System error checking mount status: {str(e)}")
            
            return False, "Disponible pour la conversion"
                
        except FileNotFoundError as e:
            log_error(f"Required file or command not found checking disk availability: {str(e)}")
            return True, "Impossible de vérifier l'état du disque — fichier introuvable"
        except PermissionError as e:
            log_error(f"Permission denied checking disk availability: {str(e)}")
            return True, "Impossible de vérifier l'état du disque — permission refusée"
        except subprocess.CalledProcessError as e:
            log_error(f"Command failed checking disk availability: {str(e)}")
            return True, "Impossible de vérifier l'état du disque — commande échouée"
        except (ValueError, IndexError) as e:
            log_error(f"Error parsing disk information: {str(e)}")
            return True, "Impossible de vérifier l'état du disque — erreur de données"
        except OSError as e:
            log_error(f"System error checking disk availability: {str(e)}")
            return True, "Impossible de vérifier l'état du disque — erreur système"
    
    def create_widgets(self):
        """Create all GUI widgets - Updated version with Format Converter integration"""
        self.create_header_frame()
        self.create_main_frame()
        self.create_status_frame()
        # NotificationBar est isolée dans un Frame intermédiaire pour éviter
        # tout conflit pack/grid directement dans la fenêtre racine (.)
        _notif_container = ttk.Frame(self.root)
        _notif_container.grid(row=3, column=0, sticky="ew")
        _notif_container.grid_columnconfigure(0, weight=1)
        self.notif_bar = theme.NotificationBar(_notif_container)
    
    def create_header_frame(self):
        """Create the header frame with title and PDF generation buttons"""
        header_frame = ttk.Frame(self.root, padding="10")
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)
        
        # Title label with icon-like symbol
        title_frame = ttk.Frame(header_frame)
        title_frame.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        title_frame.grid_columnconfigure(0, weight=1)
        
        title_label = ttk.Label(title_frame, text="VirtualPack", 
                            font=("Arial", 14, "bold"), wraplength=200)
        title_label.grid(row=0, column=0, sticky="w")
        
        subtitle_label = ttk.Label(title_frame, text="Convertisseur de machine physique en machine virtuelle", 
                                font=("Arial", 8), foreground="gray", wraplength=200)
        subtitle_label.grid(row=1, column=0, sticky="w")

        # Conversion counter
        counter_frame = ttk.Frame(title_frame)
        counter_frame.grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(counter_frame, text="Machines virtualisées :",
                  font=("Arial", 8)).pack(side=tk.LEFT)
        ttk.Label(counter_frame, textvariable=self._counter_var,
                  font=("Arial", 10, "bold"), foreground="#1a6e1a").pack(side=tk.LEFT, padx=(4, 0))
        
        # Button frame for PDF generation buttons - responsive layout
        button_frame = ttk.Frame(header_frame)
        button_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        # Administration button – PDF export, log management, shutdown, etc.
        self.admin_btn = ttk.Button(button_frame,
                                    text="⚙  Administration",
                                    command=lambda: open_admin_panel(self.root),
                                    width=20)
        self.admin_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        # Add separator
        separator = ttk.Separator(self.root, orient='horizontal')
        separator.grid(row=0, column=0, sticky="ew", pady=(0, 5), columnspan=1)
    
    def create_main_frame(self):
        """Create the main content frame with responsive layout"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        main_frame.grid_rowconfigure(5, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        
        # Get layout configuration
        layout_config = self.get_screen_layout_config()
        
        # Source disk selection frame
        source_frame = ttk.LabelFrame(main_frame, text="Sélection du disque source", padding="10")
        source_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        source_frame.grid_columnconfigure(1, weight=1)
        
        ttk.Label(source_frame, text="Disque physique :", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(source_frame, textvariable=self.source_var, 
                                        state="readonly", font=("Arial", 9))
        self.source_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.source_combo.bind("<<ComboboxSelected>>", self.on_source_selected)
        
        # Refresh button
        self.refresh_btn = ttk.Button(source_frame, text="Actualiser les disques", 
                                    command=self.refresh_disks)
        self.refresh_btn.grid(row=0, column=2, padx=(10, 0))
        
        # VM configuration frame
        vm_config_frame = ttk.LabelFrame(main_frame, text="Configuration de la VM", padding="10")
        vm_config_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        vm_config_frame.grid_columnconfigure(1, weight=1)
        
        # VM Name
        ttk.Label(vm_config_frame, text="Nom de la VM :", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w")
        vm_name_entry = ttk.Entry(vm_config_frame, textvariable=self.vm_name, font=("Arial", 9))
        vm_name_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        vm_name_entry.bind("<KeyRelease>", self.validate_vm_name_input)
        
        # Output Directory
        ttk.Label(vm_config_frame, text="Répertoire de sortie :", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(10, 0))
        
        output_frame = ttk.Frame(vm_config_frame)
        output_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10, 0))
        output_frame.grid_columnconfigure(0, weight=1)
        
        output_entry = ttk.Entry(output_frame, textvariable=self.output_path, font=("Arial", 9))
        output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        # Primary action buttons row (Browse, Mount, Delete Files)
        primary_tools_frame = ttk.Frame(output_frame)
        primary_tools_frame.grid(row=0, column=1, sticky="ew")
        
        browse_btn = ttk.Button(primary_tools_frame, text="Parcourir", command=self.browse_output_dir)
        browse_btn.grid(row=0, column=0, padx=(0, 2), sticky="ew")
        
        mount_btn = ttk.Button(primary_tools_frame, text="Monter un disque", command=self.mount_disk_dialog)
        mount_btn.grid(row=0, column=1, padx=(0, 2), sticky="ew")
        
        delete_files_btn = ttk.Button(primary_tools_frame, text="Supprimer des fichiers", 
                                    command=self.open_delete_files_manager)
        delete_files_btn.grid(row=0, column=2, sticky="ew")
        
        # Secondary tools label
        secondary_tools_label = ttk.Label(vm_config_frame, text="Outils utilitaires :", font=("Arial", 9, "bold"))
        secondary_tools_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 8))
        
        # Dynamic tools layout based on screen width
        tools_columns = layout_config['tools_columns']
        tools = [
            ("Redimensionner QCOW2", self.open_qcow2_resizer),
            ("Convertisseur de format", self.open_format_converter),
            ("Chiffrement LUKS", self.open_luks_ciphering),
            ("Virt-Manager", self.open_virt_manager),
            ("Exporter l'image", self.open_image_exporter),
        ]
        
        current_row = 3
        current_col = 0
        
        for tool_name, tool_command in tools:
            if current_col == 0 and current_col > 0:  # New row needed
                current_row += 1
                current_col = 0
            
            if current_col >= tools_columns:
                current_row += 1
                current_col = 0
            
            tools_frame = ttk.Frame(vm_config_frame)
            tools_frame.grid(row=current_row, column=current_col, sticky="ew", padx=(10, 5), pady=(0, 5))
            tools_frame.grid_columnconfigure(0, weight=1)

            # Utiliser grid() de manière cohérente avec grid_columnconfigure — pas pack()
            btn = ttk.Button(tools_frame, text=tool_name, command=tool_command)
            btn.grid(row=0, column=0, sticky="ew")
            
            current_col += 1
        
        # Adjust final row spanning
        if current_col > 0:
            for col in range(tools_columns):
                vm_config_frame.grid_columnconfigure(col, weight=1)
        
        # Tools description - updated
        tools_info_label = ttk.Label(vm_config_frame, 
                                    text="Redimensionner QCOW2 • Convertir formats • Chiffrer/déchiffrer • Gérer les VMs • Exporter des images",
                                    font=("Arial", 7), foreground="gray", wraplength=400)
        tools_info_label.grid(row=current_row+1, column=0, columnspan=2, sticky="w", pady=(5, 0))
        
        # Space information frame
        space_frame = ttk.LabelFrame(main_frame, text="Informations sur l'espace de stockage", padding="10")
        space_frame.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        
        self.space_info_text = tk.Text(space_frame, height=layout_config['space_height'], wrap=tk.WORD, state=tk.DISABLED, 
                                    font=("Consolas", 9), bg="#f8f8f8")
        space_scrollbar = ttk.Scrollbar(space_frame, orient="vertical", command=self.space_info_text.yview)
        self.space_info_text.configure(yscrollcommand=space_scrollbar.set)
        
        self.space_info_text.grid(row=0, column=0, sticky="nsew")
        space_scrollbar.grid(row=0, column=1, sticky="ns")
        
        space_frame.grid_rowconfigure(0, weight=1)
        space_frame.grid_columnconfigure(0, weight=1)
        
        # Control buttons frame - responsive
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        control_frame.grid_columnconfigure(1, weight=1)
        
        self.check_space_btn = ttk.Button(control_frame, text="Vérifier l'espace", 
                                        command=self.check_space_requirements)
        self.check_space_btn.grid(row=0, column=0, padx=(0, 10), sticky="w")
        
        self.convert_btn = ttk.Button(control_frame, text="Démarrer la conversion VirtualPack",
                                    style="Primary.TButton", 
                                    command=self.start_conversion)
        self.convert_btn.grid(row=0, column=1, padx=(0, 10), sticky="w")
        
        self.stop_btn = ttk.Button(control_frame, text="Arrêter l'opération",
                                  style="Danger.TButton", 
                                command=self.stop_operation, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=1, padx=(0, 10), sticky="e")
        
        self.clear_log_btn = ttk.Button(control_frame, text="Effacer l'affichage", 
                                    command=self.clear_log_display)
        self.clear_log_btn.grid(row=0, column=2)
        
        # Progress and log area
        log_frame = ttk.LabelFrame(main_frame, text="Journal des opérations", padding="5")
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        # Create text widget with scrollbar
        text_frame = ttk.Frame(log_frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)
        
        self.log_text = tk.Text(text_frame, wrap=tk.WORD, state=tk.DISABLED, 
                            font=("Consolas", layout_config['font_size']), bg="#f8f8f8", fg="#333333")
        scrollbar_v = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        scrollbar_h = ttk.Scrollbar(text_frame, orient="horizontal", command=self.log_text.xview)
        
        self.log_text.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
        
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar_v.grid(row=0, column=1, sticky="ns")
        scrollbar_h.grid(row=1, column=0, sticky="ew")
        
        # Configure text tags for different log levels
        self.log_text.tag_configure("INFO", foreground="#0066cc")
        self.log_text.tag_configure("WARNING", foreground="#ff6600")
        self.log_text.tag_configure("ERROR", foreground="#cc0000")
        self.log_text.tag_configure("SUCCESS", foreground="#009900")
        
        # Track last displayed log count
        self.last_log_count = 0

    def _notify(self, message: str, level: str = "info",
                confirm: bool = False, on_yes=None, on_no=None):
        """Notification inline sans pop-up."""
        try:
            self.notif_bar.show(message, level=level, confirm=confirm,
                                on_yes=on_yes, on_no=on_no,
                                auto_hide=not confirm)
        except AttributeError:
            print(f"[{level.upper()}] {message}")

    def open_image_exporter(self):
        """Open the Virtual Image Exporter dialog"""
        try:
            log_info("Opening Virtual Image Exporter dialog")
            
            # Create and show the exporter dialog
            exporter = VirtualImageExporter(self.root)
            
            log_info("Virtual Image Exporter dialog opened successfully")
            
        except ImportError as e:
            error_msg = f"Exporteur d'images virtuelles non disponible : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except tk.TclError as e:
            error_msg = f"Erreur de création de fenêtre : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir la fenêtre de l'exporteur d'images :\n\n{error_msg}", level="error")
        except (AttributeError, TypeError) as e:
            error_msg = f"Erreur interne lors de l'initialisation de l'exporteur : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser l'exporteur d'images :\n\n{error_msg}", level="error")
        except OSError as e:
            error_msg = f"Erreur système à l'ouverture de l'exporteur : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir l'exporteur d'images :\n\n{error_msg}", level="error")
        except ValueError as e:
            error_msg = f"Valeur invalide pour l'exporteur : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser l'exporteur d'images :\n\n{error_msg}", level="error")
        except MemoryError as e:
            error_msg = "Mémoire insuffisante pour ouvrir l'Exporteur d'images virtuelles"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir l'exporteur d'images :\n\n{error_msg}", level="error")
        except FileNotFoundError as e:
            error_msg = f"Fichier requis introuvable : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir l'exporteur d'images :\n\n{error_msg}", level="error")
        except PermissionError as e:
            error_msg = f"Permission refusée : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir l'exporteur d'images :\n\n{error_msg}", level="error")
    
    def open_qcow2_resizer(self):
        """Open the QCOW2 resizer dialog as a modal window"""
        try:
            log_info("Opening QCOW2 Clone Resizer dialog")
            
            # Import and create the resizer directly - it creates its own Toplevel
            resizer_app = QCow2CloneResizerGUI(self.root)
            
            # The resizer creates its own window, so just wait for it
            log_info("QCOW2 Clone Resizer dialog opened")
            
        except ImportError as e:
            error_msg = f"Redimensionneur QCOW2 non disponible : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except AttributeError as e:
            error_msg = f"Erreur d'initialisation du Redimensionneur QCOW2 : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le redimensionneur QCOW2 :\n\n{error_msg}", level="error")
        except tk.TclError as e:
            error_msg = f"Erreur de création de fenêtre : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir la fenêtre de le redimensionneur QCOW2 :\n\n{error_msg}", level="error")
        except TypeError as e:
            error_msg = f"Erreur de type lors de l'initialisation du Redimensionneur QCOW2 : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le redimensionneur QCOW2 :\n\n{error_msg}", level="error")
        except ValueError as e:
            error_msg = f"Valeur invalide pour le Redimensionneur QCOW2 : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le redimensionneur QCOW2 :\n\n{error_msg}", level="error")
        except MemoryError as e:
            error_msg = "Mémoire insuffisante pour ouvrir le Redimensionneur QCOW2"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le redimensionneur QCOW2 :\n\n{error_msg}", level="error")
        except OSError as e:
            error_msg = f"Erreur système à l'ouverture du Redimensionneur QCOW2 : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le redimensionneur QCOW2 :\n\n{error_msg}", level="error")
            
    def open_luks_ciphering(self):
        """Open the LUKS Encryption dialog as a modal window"""
        try:
            log_info("Opening LUKS Encryption dialog")
            
            # Create the ciphering directly - it creates its own Toplevel window
            ciphering_app = LUKSCiphering(self.root)
            
            log_info("LUKS Encryption dialog opened")
            
        except ImportError as e:
            error_msg = f"Chiffrement LUKS non disponible : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except AttributeError as e:
            error_msg = f"Erreur d'initialisation du Chiffrement LUKS : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le chiffrement LUKS :\n\n{error_msg}", level="error")
        except tk.TclError as e:
            error_msg = f"Erreur de création de fenêtre : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir la fenêtre de le chiffrement LUKS :\n\n{error_msg}", level="error")
        except TypeError as e:
            error_msg = f"Erreur de type lors de l'initialisation du Chiffrement LUKS : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le chiffrement LUKS :\n\n{error_msg}", level="error")
        except ValueError as e:
            error_msg = f"Valeur invalide pour le Chiffrement LUKS : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le chiffrement LUKS :\n\n{error_msg}", level="error")
        except MemoryError as e:
            error_msg = "Mémoire insuffisante pour ouvrir le Chiffrement LUKS"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le chiffrement LUKS :\n\n{error_msg}", level="error")
        except OSError as e:
            error_msg = f"Erreur système à l'ouverture du Chiffrement LUKS : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le chiffrement LUKS :\n\n{error_msg}", level="error")
        except FileNotFoundError as e:
            error_msg = f"Fichier requis introuvable : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le chiffrement LUKS :\n\n{error_msg}", level="error")
        except PermissionError as e:
            error_msg = f"Permission refusée : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le chiffrement LUKS :\n\n{error_msg}", level="error")

    def open_delete_files_manager(self):
            """Open the Delete Files Manager for interactive file deletion"""
            try:
                
                log_info("Opening Delete Files Manager")
                
                # Create the file deletion manager
                file_manager = FileDeleteManager(self.root)
                
                # Start interactive file deletion process
                # (user selects files, then confirms deletion)
                stats = file_manager.delete_files_interactive()
                
                # Show summary in log
                if stats['removed'] > 0 or stats['failed'] > 0:
                    summary_msg = f"Suppression de fichiers : {stats['removed']} supprimé(s), {stats['failed']} échoué(s)"
                    log_info(summary_msg)
                    self.operation_details.config(text=summary_msg, foreground="green" if stats['failed'] == 0 else "orange")
                
            except ImportError as e:
                error_msg = f"Gestionnaire de suppression non disponible : {str(e)}"
                log_error(error_msg)
                self._notify("Notification", level="info")
            except AttributeError as e:
                error_msg = f"Erreur d'initialisation du Gestionnaire de suppression : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'initialiser le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except tk.TclError as e:
                error_msg = f"Erreur de création de fenêtre : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'ouvrir la fenêtre de le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except TypeError as e:
                error_msg = f"Erreur de type lors de l'initialisation du Gestionnaire de suppression : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'initialiser le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except ValueError as e:
                error_msg = f"Valeur invalide pour le Gestionnaire de suppression : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'initialiser le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except MemoryError as e:
                error_msg = "Mémoire insuffisante pour ouvrir le Gestionnaire de suppression"
                log_error(error_msg)
                self._notify(f"Impossible d'ouvrir le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except OSError as e:
                error_msg = f"Erreur système à l'ouverture du Gestionnaire de suppression : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'ouvrir le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except PermissionError as e:
                error_msg = f"Permission refusée : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'ouvrir le gestionnaire de suppression :\n\n{error_msg}", level="error")
            except FileNotFoundError as e:
                error_msg = f"Fichier requis introuvable : {str(e)}"
                log_error(error_msg)
                self._notify(f"Impossible d'ouvrir le gestionnaire de suppression :\n\n{error_msg}", level="error")

    def open_format_converter(self):
        """Open the Format Converter dialog as a modal window"""
        try:
            log_info("Opening Format Converter dialog")
            
            # Create the converter directly - it creates its own Toplevel window
            converter_app = ImageFormatConverter(self.root)
            
            log_info("Format Converter dialog opened")
            
        except ImportError as e:
            error_msg = f"Convertisseur de format non disponible : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except AttributeError as e:
            error_msg = f"Erreur d'initialisation du Convertisseur de format : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le convertisseur de format :\n\n{error_msg}", level="error")
        except tk.TclError as e:
            error_msg = f"Erreur de création de fenêtre : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir la fenêtre de le convertisseur de format :\n\n{error_msg}", level="error")
        except TypeError as e:
            error_msg = f"Erreur de type lors de l'initialisation du Convertisseur de format : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le convertisseur de format :\n\n{error_msg}", level="error")
        except ValueError as e:
            error_msg = f"Valeur invalide pour le Convertisseur de format : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'initialiser le convertisseur de format :\n\n{error_msg}", level="error")
        except MemoryError as e:
            error_msg = "Mémoire insuffisante pour ouvrir le Convertisseur de format"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le convertisseur de format :\n\n{error_msg}", level="error")
        except OSError as e:
            error_msg = f"Erreur système à l'ouverture du Convertisseur de format : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le convertisseur de format :\n\n{error_msg}", level="error")
        except FileNotFoundError as e:
            error_msg = f"Fichier requis introuvable : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le convertisseur de format :\n\n{error_msg}", level="error")
        except PermissionError as e:
            error_msg = f"Permission refusée : {str(e)}"
            log_error(error_msg)
            self._notify(f"Impossible d'ouvrir le convertisseur de format :\n\n{error_msg}", level="error")

    def mount_disk_dialog(self):
        """Show dialog to select and mount a disk for output storage"""
        try:
            dialog = DiskMountDialog(self.root)
            self.root.wait_window(dialog.dialog)
            
            if dialog.result:
                # Update output path with the mounted disk
                self.output_path.set(dialog.result)
                log_info(f"Selected mounted disk path: {dialog.result}")
                
                # Auto-check space if source disk is selected
                if self.source_var.get():
                    self.root.after(100, self.check_space_requirements)
                    
        except PermissionError as e:
            error_msg = f"Permission refusée pour la boîte de montage de disque : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except OSError as e:
            error_msg = f"Erreur système dans la boîte de montage de disque : {str(e)}"
            log_error(error_msg) 
            self._notify("Notification", level="info")
        except ImportError as e:
            error_msg = f"Module requis manquant pour le montage de disque : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except subprocess.CalledProcessError as e:
            error_msg = f"Commande échouée dans la boîte de montage de disque : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info") 
        except ValueError as e:
            error_msg = f"Valeur invalide dans la boîte de montage de disque : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except (AttributeError, TypeError) as e:
            error_msg = f"Erreur interne dans la boîte de montage de disque : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        except tk.TclError as e:
            error_msg = f"Erreur de fenêtre de dialogue : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
    
    def open_virt_manager(self):
        """Open virt-manager with proper permissions for VM management"""
        try:
            log_info("Checking virt-manager availability")
            
            # Check if virt-manager is available
            missing_tools, available = VirtManagerLauncher.check_virt_manager()
            
            if not available:
                error_msg = "Outils de virtualisation manquants : " + ", ".join(missing_tools)
                log_error(f"Virt-manager check failed: {', '.join(missing_tools)}")
                self._notify(error_msg, level="error")
                return
            
            log_info("Virt-manager is available, launching...")
            
            # Disable button during launch
            self.status_var.set("Lancement de virt-manager...")
            self.root.update_idletasks()
            
            # Launch virt-manager
            try:
                VirtManagerLauncher.launch_virt_manager(log_callback=log_info)
                
                log_info("Virt-manager launched successfully")
                self.status_var.set("Virt-manager est en cours d'exécution")
                self.operation_details.config(text="Virt-manager ouvert en arrière-plan",
                                            foreground="green")
                self._notify("Virt-manager lancé avec succès", level="success")
            
            except FileNotFoundError as e:
                error_msg = f"virt-manager introuvable : {str(e)}"
                log_error(error_msg)
                self._notify(error_msg, level="error")
            
            except PermissionError as e:
                error_msg = f"Permission refusée : {str(e)}"
                log_error(error_msg)
                self._notify(error_msg, level="error")
            
            except OSError as e:
                error_msg = f"Erreur système au lancement : {str(e)}"
                log_error(error_msg)
                self._notify(error_msg, level="error")
            
            except subprocess.CalledProcessError as e:
                error_msg = f"virt-manager a échoué (code {e.returncode})"
                log_error(error_msg)
                self._notify(error_msg, level="error")
            
            except subprocess.SubprocessError as e:
                error_msg = f"Erreur subprocess : {str(e)}"
                log_error(error_msg)
                self._notify(error_msg, level="error")
            
            except (AttributeError, TypeError) as e:
                error_msg = f"Erreur interne : {str(e)}"
                log_error(error_msg)
                self._notify(error_msg, level="error")
        
        except tk.TclError as e:
            error_msg = f"Erreur GUI : {str(e)}"
            log_error(error_msg)
            self._notify(error_msg, level="error")
        
        except (KeyError, ValueError) as e:
            error_msg = f"Erreur de configuration : {str(e)}"
            log_error(error_msg)
            self._notify(error_msg, level="error")
        
        finally:
            self.status_var.set("Prêt")
    
    def launch_virt_manager_with_image(self, image_path):
        """
        Launch virt-manager with a specific VM image
        
        Args:
            image_path: Path to the VM image file
        """
        try:
            if not os.path.exists(image_path):
                error_msg = f"Fichier image introuvable : {image_path}"
                log_error(error_msg)
                self._notify("Notification", level="info")
                return
            
            log_info(f"Launching virt-manager with image: {image_path}")
            
            # Disable button during launch
            self.status_var.set("Préparation de l'image VM...")
            self.root.update_idletasks()
            
            # Launch with image
            try:
                VirtManagerLauncher.launch_virt_manager_with_image(
                    image_path, 
                    log_callback=log_info
                )
                
                log_info(f"Virt-manager launched with image: {image_path}")
                self.status_var.set("Virt-manager est en cours d'exécution")
                self.operation_details.config(
                    text=f"Virt-manager ouvert avec : {Path(image_path).name}", 
                    foreground="green"
                )
                
                self._notify(
                    f"Virt-manager lancé avec {Path(image_path).name} "
                    f"({VirtManagerLauncher.format_size(os.path.getsize(image_path))})",
                    level="success"
                )
            
            except FileNotFoundError as e:
                error_msg = f"Erreur : {str(e)}"
                log_error(error_msg)
                self._notify("Notification", level="info")
            
            except PermissionError as e:
                error_msg = (
                    f"Permission error: {str(e)}\n\n"
                    "Impossible d'accéder au fichier image VM.\n\n"
                    "Vérifiez les permissions et la propriété du fichier."
                )
                log_error(error_msg)
                self._notify("Notification", level="info")
            
            except OSError as e:
                error_msg = f"Erreur système : {str(e)}"
                log_error(error_msg)
                self._notify("Notification", level="info")
            
            except subprocess.SubprocessError as e:
                error_msg = f"Erreur de sous-processus : {str(e)}"
                log_error(error_msg)
                self._notify("Notification", level="info")
        
        except tk.TclError as e:
            error_msg = f"Erreur d'interface graphique : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
        
        finally:
            self.status_var.set("Prêt")

    def create_status_frame(self):
        """Create the status frame at the bottom with responsive layout"""
        status_frame = ttk.Frame(self.root, padding="10")
        status_frame.grid(row=2, column=0, sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)
        
        # Get screen width to determine layout
        screen_width = self.root.winfo_screenwidth()
        
        if screen_width < 1024:
            # Compact layout for small screens
            progress_label = ttk.Label(status_frame, text="Progression :")
            progress_label.grid(row=0, column=0, sticky="w", padx=(0, 5))
            
            self.progress_var = tk.DoubleVar()
            self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, 
                                            maximum=100, length=150)
            self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(0, 5))
            
            self.progress_label = ttk.Label(status_frame, text="0%", width=4)
            self.progress_label.grid(row=0, column=2, sticky="w", padx=(0, 10))
            
            status_info_label = ttk.Label(status_frame, text="Statut :")
            status_info_label.grid(row=0, column=3, sticky="w", padx=(0, 5))
            
            self.status_var = tk.StringVar(value="Prêt")
            self.status_label = ttk.Label(status_frame, textvariable=self.status_var, 
                                        font=("Arial", 8, "bold"))
            self.status_label.grid(row=0, column=4, sticky="w")
            
            # Details on next row
            self.operation_details = ttk.Label(status_frame, text="", 
                                            font=("Arial", 7), foreground="gray", wraplength=300)
            self.operation_details.grid(row=1, column=0, columnspan=5, sticky="w", pady=(5, 0))
        else:
            # Full layout for larger screens
            progress_label = ttk.Label(status_frame, text="Progression :")
            progress_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
            
            self.progress_var = tk.DoubleVar()
            self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, 
                                            maximum=100, length=300)
            self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(0, 10))
            
            self.progress_label = ttk.Label(status_frame, text="0%")
            self.progress_label.grid(row=0, column=2, sticky="w", padx=(0, 20))
            
            status_info_label = ttk.Label(status_frame, text="Statut :")
            status_info_label.grid(row=0, column=3, sticky="w", padx=(0, 10))
            
            self.status_var = tk.StringVar(value="Prêt")
            self.status_label = ttk.Label(status_frame, textvariable=self.status_var, 
                                        font=("Arial", 9, "bold"))
            self.status_label.grid(row=0, column=4, sticky="w")
            
            self.operation_details = ttk.Label(status_frame, text="", 
                                            font=("Arial", 8), foreground="gray")
            self.operation_details.grid(row=1, column=0, columnspan=5, sticky="w", pady=(5, 0))
        
        # Initialize with disk refresh
        self.root.after(100, self.refresh_disks)
    
    def check_prerequisites(self):
        """Check if required tools are available"""
        tools_available, message = check_qemu_tools()
        if not tools_available:
            log_error(f"Prerequisites check failed: {message}")
            self._notify(
                f"Prérequis manquants : {message} — Installez : qemu-utils, coreutils",
                level="error"
            )
        else:
            log_info("All prerequisites are available")

    def update_log_from_session(self):
        """Update log display from session logs"""
        try:
            if is_session_active():
                session_logs = get_current_session_logs()
                
                # Only update if there are new logs
                if len(session_logs) > self.last_log_count:
                    new_logs = session_logs[self.last_log_count:]
                    
                    self.log_text.config(state=tk.NORMAL)
                    
                    for log_entry in new_logs:
                        # Parse log entry to extract level and message
                        # Format: [TIMESTAMP] LEVEL: MESSAGE
                        if "] " in log_entry and ": " in log_entry:
                            try:
                                # Extract timestamp, level, and message
                                parts = log_entry.split("] ", 1)
                                timestamp = parts[0] + "]"
                                rest = parts[1]
                                
                                level_parts = rest.split(": ", 1)
                                level = level_parts[0]
                                message = level_parts[1] if len(level_parts) > 1 else rest
                                
                                # Insert with appropriate formatting
                                self.log_text.insert(tk.END, f"{timestamp} ", "INFO")
                                self.log_text.insert(tk.END, f"{level}: {message}\n", level.upper())
                                
                            except (IndexError, ValueError, AttributeError):
                                # Fallback: display as-is
                                self.log_text.insert(tk.END, f"{log_entry}\n", "INFO")
                        else:
                            # Display as-is if format doesn't match expected pattern
                            self.log_text.insert(tk.END, f"{log_entry}\n", "INFO")
                    
                    # Auto-scroll to bottom
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
                    
                    # Update counter
                    self.last_log_count = len(session_logs)
        except (AttributeError, KeyError, TypeError, IOError, OSError):
            # Don't let log update errors crash the GUI
            pass
        
        # Schedule next update
        self.root.after(1000, self.update_log_from_session)
    
    def clear_log_display(self):
        """Clear the log display (but not the actual session logs)"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        log_info("Log display cleared (session logs preserved)")
        # Reset counter so logs will reappear on next update
        self.last_log_count = 0
    
    def refresh_disks(self):
        """Refresh the list of available disks"""
        try:
            log_info("Refreshing disk list")
            self.current_disks = get_disk_list()
            
            if self.current_disks:
                disk_options = []
                unavailable_count = 0
                
                for disk in self.current_disks:
                    disk_info = f"{disk['device']} ({disk['size']}) - {disk['model']}"
                    
                    if disk['label'] and disk['label'] != "No Label":
                        disk_info += f" [{disk['label']}]"
                    
                    is_unavailable, reason = self.is_disk_unavailable_for_conversion(disk['device'])
                    
                    if is_unavailable:
                        unavailable_count += 1
                        if "active system disk" in reason.lower():
                            disk_info = f"SYSTÈME : {disk_info} [ACTIF]"
                        elif "mounted" in reason.lower():
                            disk_info = f"MONTÉ : {disk_info} [EN COURS D'UTILISATION]"
                        else:
                            disk_info = f"OCCUPÉ : {disk_info} [INDISPONIBLE]"
                    
                    disk_options.append(disk_info)
                
                self.source_combo['values'] = disk_options
                
                if self.source_var.get() not in disk_options:
                    self.source_var.set("")
                
                log_info(f"Found {len(self.current_disks)} disk(s)")
                
                available_count = len(self.current_disks) - unavailable_count
                if unavailable_count > 0:
                    self.status_var.set(f"{len(self.current_disks)} disque(s) trouvé(s) ({available_count} disponible(s), {unavailable_count} indisponible(s))")
                else:
                    self.status_var.set(f"{len(self.current_disks)} disque(s) trouvé(s) (tous disponibles)")
                
            else:
                log_warning("No disks found")
                self.status_var.set("Aucun disque trouvé")
                self.source_combo['values'] = []
                
        except OSError as e:
            error_msg = f"Erreur système lors de l'actualisation des disques : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.status_var.set("Erreur lors de l'actualisation des disques")
        except subprocess.CalledProcessError as e:
            error_msg = f"Erreur d'exécution de la commande : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.status_var.set("Erreur lors de l'actualisation des disques")
        except FileNotFoundError as e:
            error_msg = f"Commande requise introuvable : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.status_var.set("Erreur lors de l'actualisation des disques")
        except (ValueError, KeyError) as e:
            error_msg = f"Erreur d'analyse des données : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.status_var.set("Erreur lors de l'actualisation des disques")
        except PermissionError as e:
            error_msg = f"Permission refusée pour accéder aux informations du disque : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.status_var.set("Erreur lors de l'actualisation des disques")
        except AttributeError as e:
            error_msg = f"Structure de données invalide retournée : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.status_var.set("Erreur lors de l'actualisation des disques")
    
    def get_selected_disk_info(self):
        """Get disk info for currently selected disk"""
        selected = self.source_var.get()
        if not selected:
            return None
        
        # Extract device path from display string
        device_path = selected.split(' ')[1] if selected.startswith('SYSTEM:') else selected.split(' ')[0]
        
        # Find matching disk in current_disks
        for disk in self.current_disks:
            if disk['device'] == device_path:
                return disk
        
        return None
    
    def on_source_selected(self, event=None):
        """Handle source disk selection with enhanced validation"""
        selected = self.source_var.get()
        if selected:
            # Extract device path
            device_path = selected.split(' ')[1] if selected.startswith('SYSTEM:') else selected.split(' ')[0]
            
            # Check if this disk is unavailable for conversion
            is_unavailable, reason = self.is_disk_unavailable_for_conversion(device_path)
            
            if is_unavailable:
                # Show detailed warning dialog
                warning_title = "Disque indisponible pour la conversion"
                warning_message = f"Impossible de sélectionner ce disque pour la conversion\n\n"
                warning_message += f"Disque sélectionné : {device_path}\n"
                warning_message += f"Raison : {reason}\n\n"
                
                if "active system disk" in reason.lower():
                    warning_message += f"Convertir un disque système actif est dangereux et peut :\n"
                    warning_message += f"• Provoquer une instabilité système ou des plantages\n"
                    warning_message += f"• Entraîner une conversion incomplète ou corrompue\n"
                    warning_message += f"• Interférer avec les processus système en cours\n\n"
                    warning_message += f"Recommandations :\n"
                    warning_message += f"• Sélectionnez un disque différent et inactif pour la conversion\n"
                    warning_message += f"• Démarrez depuis un support live (USB/CD) pour convertir ce disque en toute sécurité"
                
                elif "mounted" in reason.lower():
                    warning_message += f"Convertir un disque avec des partitions montées peut :\n"
                    warning_message += f"• Provoquer une corruption ou perte de données\n"
                    warning_message += f"• Entraîner une conversion incomplète\n"
                    warning_message += f"• Interférer avec les opérations de fichiers en cours\n\n"
                    warning_message += f"Recommandations :\n"
                    warning_message += f"• Démontez d'abord toutes les partitions de ce disque\n"
                    warning_message += f"• Sélectionnez un disque différent qui n'est pas monté\n"
                    warning_message += f"• Utilisez la commande 'umount' pour démonter les partitions en toute sécurité"
                
                else:
                    warning_message += f"Veuillez sélectionner un disque différent qui n'est pas utilisé."
                
                self._notify("Notification", level="info")
                
                # Clear the selection
                self.source_var.set("")
                log_warning(f"User attempted to select unavailable disk: {device_path} - {reason}")
                self.status_var.set("Sélection du disque refusée")
                self.operation_details.config(text=f"Impossible de sélectionner le disque : {reason}", foreground="red")
                
                # Clear space info
                self.space_info_text.config(state=tk.NORMAL)
                self.space_info_text.delete(1.0, tk.END)
                self.space_info_text.insert(tk.END, 
                    "Veuillez sélectionner un disque non monté et non utilisé activement pour la conversion VirtualPack.\n\n"
                    "Disques sûrs pour la conversion :\n"
                    "• Disques de stockage secondaires non montés\n"
                    "• Disques externes démontés\n"
                    "• Disques de systèmes démarrés via un support live")
                self.space_info_text.config(state=tk.DISABLED)
                return
            
            log_info(f"Selected source disk: {device_path}")
            
            # Auto-update VM name based on disk
            disk_name = device_path.split('/')[-1]  # e.g., sda from /dev/sda
            self.vm_name.set(f"{disk_name}_vm")
            
            # Clear any previous error messages
            self.operation_details.config(text="", foreground="gray")
            
            # Update space info if we have detailed disk information
            disk_info = self.get_selected_disk_info()
            if disk_info and self.output_path.get():
                self.root.after(100, self.check_space_requirements)
    
    def validate_vm_name_input(self, event=None):
        """Validate VM name as user types"""
        name = self.vm_name.get()
        is_valid, message = validate_vm_name(name)
        
        if not is_valid and name:  # Only show error if there's content
            self.operation_details.config(text=f"Avertissement : {message}", foreground="red")
        else:
            self.operation_details.config(text="", foreground="gray")
    
    def browse_output_dir(self):
        """Browse for output directory"""
        selected_dir = filedialog.askdirectory(
            title="Sélectionner le répertoire de sortie pour les fichiers VM",
            initialdir=self.output_path.get()
        )
        
        if selected_dir:
            self.output_path.set(selected_dir)
            log_info(f"Output directory selected: {selected_dir}")
            
            # Auto-check space if disk is selected
            if self.source_var.get():
                self.root.after(100, self.check_space_requirements)
    
    def check_space_requirements(self):
        """Check space requirements and display information"""
        try:
            source = self.source_var.get()
            output_dir = self.output_path.get()
            
            if not source:
                self._notify("Veuillez d'abord sélectionner un disque source", level="warning")
                return
            
            if not output_dir:
                self._notify("Veuillez spécifier un répertoire de sortie", level="warning")
                return
            
            # Extract device path
            device_path = source.split(' ')[1] if source.startswith(('SYSTEM:', 'MOUNTED:', 'BUSY:')) else source.split(' ')[0]
            
            log_info(f"Checking space requirements for {device_path}")
            
            # Use the consolidated check_output_space function
            has_space, space_message = check_output_space(output_dir, device_path)
            
            # Get disk info for additional display information
            disk_info = get_disk_info(device_path)
            
            # Update space info display with enhanced information
            self.space_info_text.config(state=tk.NORMAL)
            self.space_info_text.delete(1.0, tk.END)
            
            info_text = f"Disque source : {device_path}\n"
            info_text += f"Modèle : {disk_info.get('model', 'Inconnu')}\n"
            if disk_info.get('label') and disk_info['label'] != "Unknown":
                info_text += f"Étiquette : {disk_info['label']}\n"
            info_text += f"Répertoire de sortie : {output_dir}\n\n"
            info_text += space_message
            
            # Add system disk warning if applicable
            if is_system_disk(device_path):
                info_text += "\n\nAvertissement : Ce disque est le disque système actif !"
            
            self.space_info_text.insert(tk.END, info_text)
            self.space_info_text.config(state=tk.DISABLED)
            
            if has_space:
                log_info("Space check passed - sufficient space available")
                self.operation_details.config(text="Espace suffisant disponible", foreground="green")
            else:
                log_error("Space check failed - insufficient space")
                self.operation_details.config(text="Espace insuffisant", foreground="red")
                self._notify("Espace insuffisant !\n\n{space_message}", level="warning")
            
        except (OSError, IOError) as e:
            error_msg = f"Erreur système lors de la vérification de l'espace requis : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.operation_details.config(text="Vérification de l'espace échouée", foreground="red")
        except (ValueError, TypeError) as e:
            error_msg = f"Erreur de données lors de la vérification de l'espace requis : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.operation_details.config(text="Vérification de l'espace échouée", foreground="red")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = f"Erreur de commande lors de la vérification de l'espace requis : {str(e)}"
            log_error(error_msg)
            self._notify("Notification", level="info")
            self.operation_details.config(text="Vérification de l'espace échouée", foreground="red")
    
    def start_conversion(self):
        """Start the VirtualPack conversion operation with enhanced validation"""
        source = self.source_var.get()
        vm_name = self.vm_name.get().strip()
        output_dir = self.output_path.get().strip()
        
        # Validation
        if not source:
            self._notify("Veuillez sélectionner un disque source", level="warning")
            return
        
        if not vm_name:
            self._notify("Veuillez saisir un nom de VM", level="warning")
            return
        
        if not output_dir:
            self._notify("Veuillez spécifier un répertoire de sortie", level="warning")
            return
        
        # Validate VM name
        is_valid, validation_message = validate_vm_name(vm_name)
        if not is_valid:
            self._notify("Notification", level="info")
            return
        
        # Extract device path
        device_path = source.split(' ')[1] if source.startswith(('SYSTEM:', 'MOUNTED:', 'BUSY:')) else source.split(' ')[0]
        
        # Final safety check - re-validate disk availability right before conversion
        is_unavailable, reason = self.is_disk_unavailable_for_conversion(device_path)
        if is_unavailable:
            self._notify(
                f"Disque {device_path} indisponible pour la conversion — {reason}",
                level="error"
            )
            # Refresh disk list to update status
            self.refresh_disks()
            return
        
        # Space check before starting
        try:
            has_space, space_message = check_output_space(output_dir, device_path)
            if not has_space:
                if not self._notify("Notification", level="info"):
                    return
        except (OSError, IOError) as e:
            log_warning(f"System error checking space before conversion: {str(e)}")
        except (ValueError, TypeError, KeyError) as e:
            log_warning(f"Data error checking space before conversion: {str(e)}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log_warning(f"Command error checking space before conversion: {str(e)}")
        
        # Final confirmation with enhanced information
        try:
            disk_info = get_disk_info(device_path)
            confirmation_text = f"Confirmation de conversion VirtualPack\n\n"
            confirmation_text += f"Disque source : {device_path}\n"
            confirmation_text += f"Modèle : {disk_info.get('model', 'Inconnu')}\n"
            confirmation_text += f"Taille : {disk_info.get('size_human', 'Inconnue')}\n"
            if disk_info.get('label') and disk_info['label'] != "Unknown":
                confirmation_text += f"Étiquette : {disk_info['label']}\n"
            confirmation_text += f"Nom de la VM : {vm_name}\n"
            confirmation_text += f"Répertoire de sortie : {output_dir}\n\n"
            confirmation_text += f"Cela créera une machine virtuelle qcow2 compressée.\n"
            confirmation_text += f"Le processus peut prendre un temps significatif.\n\n"
            confirmation_text += f"Continuer la conversion ?"
        except (OSError, IOError, ValueError, KeyError, AttributeError):
            confirmation_text = f"Confirmation de conversion VirtualPack\n\n"
            confirmation_text += f"Disque source : {device_path}\n"
            confirmation_text += f"Nom de la VM : {vm_name}\n"
            confirmation_text += f"Répertoire de sortie : {output_dir}\n\n"
            confirmation_text += f"Continuer la conversion ?"
        
        # Confirmation inline
            self._pending_confirm = True  # set by _notify confirm flow
            self._notify(confirmation_text, level="warning", confirm=True,
                on_yes=lambda: self._run_after_confirm(), on_no=None)
            return
        
        # Start conversion in a separate thread
        self.operation_running = True
        self.stop_requested = False
        
        conversion_thread = threading.Thread(target=self._conversion_worker, 
                                            args=(device_path, output_dir, vm_name))
        conversion_thread.daemon = True
        conversion_thread.start()
        
        # Update UI
        self.convert_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.refresh_btn.config(state=tk.DISABLED)
        self.check_space_btn.config(state=tk.DISABLED)
        self.source_combo.config(state=tk.DISABLED)
        self.status_var.set("Conversion VirtualPack en cours...")

    
    def _conversion_worker(self, source_device, output_dir, vm_name):
        """Worker thread for VirtualPack conversion operation"""
        try:
            log_info(f"Starting VirtualPack conversion: {source_device} -> {vm_name}.qcow2")
            
            def progress_callback(percent, status):
                self.root.after(0, lambda: self._update_progress(percent, status))
            
            def stop_check():
                return self.stop_requested
            
            # Perform the conversion using the improved function
            output_file = create_vm_from_disk(source_device, output_dir, vm_name, 
                                            progress_callback, stop_check)
            
            if not self.stop_requested:
                log_info("VirtualPack conversion completed successfully")
                
                # Get final file size
                final_size = os.path.getsize(output_file)
                log_info(f"VM created: {output_file} ({format_bytes(final_size)})")

                # Record in persistent counter
                try:
                    new_count = record_conversion(
                        source_disk=source_device,
                        vm_name=vm_name,
                        output_path=output_file,
                        actual_size=final_size,
                    )
                    self.root.after(0, lambda c=new_count: self._counter_var.set(str(c)))
                    log_info(f"Total machines virtualized: {new_count}")
                except Exception as e:
                    log_error(f"Could not record conversion stats: {e}")
                
                # Show completion dialog with enhanced information
                completion_text = f"Conversion VirtualPack terminée avec succès !\n\n"
                completion_text += f"Fichier VM : {output_file}\n"
                completion_text += f"Taille : {format_bytes(final_size)}\n\n"
                completion_text += f"Vous pouvez désormais utiliser ce fichier qcow2 avec :\n"
                completion_text += f"• La virtualisation QEMU/KVM\n"
                completion_text += f"• VirtualBox (avec conversion)\n"
                completion_text += f"• D'autres plateformes de virtualisation supportant qcow2\n\n"
                completion_text += f"Pour démarrer la VM avec QEMU :\n"
                completion_text += f"qemu-system-x86_64 -hda \"{output_file}\" -m 2048\n\n"
                completion_text += f"Utilisez le bouton 'Redimensionner QCOW2...' pour optimiser la taille du disque si nécessaire."
                
                self.root.after(0, lambda msg=completion_text: self._notify(msg, level="success"))
        
        except FileNotFoundError as e:
            error_msg = f"Commande ou fichier requis introuvable : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except subprocess.CalledProcessError as e:
            error_msg = f"Échec de l'exécution de la commande : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        except subprocess.TimeoutExpired as e:
            error_msg = f"Délai de la commande dépassé : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except PermissionError as e:
            error_msg = f"Permission refusée pour accéder au disque ou au répertoire de sortie : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except OSError as e:
            error_msg = f"Erreur système pendant l'opération disque : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        except IOError as e:
            error_msg = f"Erreur d'E/S pendant la conversion : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except ValueError as e:
            error_msg = f"Valeur ou paramètre invalide : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except TypeError as e:
            error_msg = f"Erreur de type dans le processus de conversion : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except AttributeError as e:
            error_msg = f"Erreur d'attribut d'objet pendant la conversion : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        except KeyError as e:
            error_msg = f"Clé de configuration manquante : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        except IndexError as e:
            error_msg = f"Erreur d'index pendant le traitement des données : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
                
        except KeyboardInterrupt:
            log_warning("VirtualPack conversion cancelled by user")
            self.root.after(0, lambda: self._notify("Conversion VirtualPack annulée par l'utilisateur", level="success"))
                
        except MemoryError:
            error_msg = "Mémoire insuffisante pour effectuer la conversion"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        except RuntimeError as e:
            error_msg = f"Erreur d'exécution pendant la conversion : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        except UnicodeError as e:
            error_msg = f"Erreur d'encodage de texte : {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: self._notify(f"Échec de la conversion VirtualPack :\n\n{error_msg}", level="error"))
        
        finally:
            # Reset UI in main thread
            self.root.after(0, self._reset_ui_after_operation)

    def _update_progress(self, percent, status):
        """Update progress bar and status from worker thread"""
        # Ensure percent is within valid range
        percent = max(0, min(100, percent))
        
        self.progress_var.set(percent)
        self.progress_label.config(text=f"{percent:.1f}%")
        self.operation_details.config(text=status, foreground="blue")
        
        # Force GUI update
        self.root.update_idletasks()
    
    def _reset_ui_after_operation(self):
        """Reset UI after operation completes"""
        self.operation_running = False
        self.convert_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.refresh_btn.config(state=tk.NORMAL)
        self.check_space_btn.config(state=tk.NORMAL)
        self.source_combo.config(state="readonly")  # Re-enable combobox
        self.progress_var.set(0)
        self.progress_label.config(text="0%")
        self.status_var.set("Prêt")
        self.operation_details.config(text="", foreground="gray")
    
    def stop_operation(self):
        """Stop the current operation"""
        if self.operation_running:
            self.stop_requested = True
            log_warning("Stop requested by user")
            self.status_var.set("Arrêt en cours...")
            self.operation_details.config(text="Arrêt de l'opération, veuillez patienter...", foreground="orange")
    
    def exit_application(self):
        """Exit the application with confirmation"""
        if self.operation_running:
            result = self._notify("Notification", level="info")
            if result:
                self.stop_requested = True
                log_warning("Application exit requested during operation")
                # Give a moment for the operation to stop
                self.root.after(1000, self._force_exit)
            return
        
        # Normal exit confirmation
        result = self._notify("Notification", level="info")
        if result:
            self._perform_exit("GUI Exit button")
    
    def _force_exit(self):
        """Force exit after stopping operation"""
        self._perform_exit("Forced exit during operation")
    
    def _perform_exit(self, reason):
        """Perform the actual exit with proper session cleanup"""
        try:
            log_application_exit(reason)
            # Only end session if it's still active
            if is_session_active():
                session_end()
        except (AttributeError, IOError, OSError, KeyError, ValueError):
            # Don't let logging errors prevent exit
            print(f"Warning: Error during session cleanup")
        finally:
            self.root.quit()
            self.root.destroy()
    
    # (External-storage helpers and PDF/log export methods have been moved
    #  to admin_interface.py and are accessible via the Administration panel.)

    def _get_external_disks(self) -> list:  # kept for internal use by other tools
        """
        Return a list of dicts describing block devices that are NOT the
        active system disk and NOT a virtual/loop device.

        Each dict has:
            device       – base device name, e.g. 'sdb'
            path         – full path, e.g. '/dev/sdb'
            size         – human-readable size from lsblk
            model        – model string (may be empty)
            partitions   – list of partition names, e.g. ['sdb1', 'sdb2']
            mount_points – dict {partition_name: mount_point or None}
        """
        import subprocess as _sp
        import json as _json

        result = []

        try:
            raw = _sp.run(
                ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MODEL,MOUNTPOINT"],
                stdout=_sp.PIPE, stderr=_sp.PIPE
            ).stdout.decode()
            data = _json.loads(raw)
        except Exception as e:
            log_error(f"lsblk JSON failed: {e}")
            return result

        for dev in data.get("blockdevices", []):
            dev_name = dev.get("name", "")
            dev_type = dev.get("type", "")

            # Only plain disks
            if dev_type not in ("disk",):
                continue
            # Skip loop devices
            if dev_name.startswith("loop"):
                continue
            # Skip system disk (uses is_system_disk from utils)
            if is_system_disk(f"/dev/{dev_name}"):
                continue

            partitions = []
            mount_map  = {}

            children = dev.get("children") or []
            if children:
                for child in children:
                    p_name = child.get("name", "")
                    p_type = child.get("type", "")
                    if p_type == "part":
                        partitions.append(p_name)
                        mount_map[p_name] = child.get("mountpoint") or None
            else:
                # Disk with no partition table – treat disk itself as target
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

    def _mount_partition(self, partition: str) -> str | None:
        """
        Mount /dev/<partition> to a unique temp directory.
        Returns the mount point on success, None on failure.
        """
        import tempfile as _tf

        mount_dir = _tf.mkdtemp(prefix="virtualpack_export_")
        try:
            r = subprocess.run(
                ["mount", f"/dev/{partition}", mount_dir],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
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
        """Unmount and remove the temporary mount directory."""
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