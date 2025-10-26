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
from log_handler import (log_info, log_error, log_warning, generate_session_pdf,
generate_log_file_pdf, session_start, session_end,
log_application_exit, get_current_session_logs,
is_session_active)
from utils import (get_disk_list, get_directory_space, format_bytes, get_active_disk,
get_disk_info, is_system_disk)
from vm import (check_output_space, check_qemu_tools, create_vm_from_disk, validate_vm_name)
from disk_mount_dialog import DiskMountDialog
from qcow2_resize_dialog import QCow2CloneResizerGUI
from image_format_converter import ImageFormatConverter

class P2VConverterGUI:
    """GUI class for the P2V Converter application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Physical to Virtual (P2V) Converter")
        self.root.geometry("600x500")
        self.root.attributes("-fullscreen", True)
        
        # Operation control variables
        self.operation_running = False
        self.stop_requested = False
        
        # VM configuration variables
        self.vm_name = tk.StringVar(value="converted_vm")
        self.output_path = tk.StringVar(value="/tmp/p2v_output")
        
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
        log_info("P2V Converter GUI initialized successfully")
        
        # Check for required tools
        self.check_prerequisites()
        
        # Start periodic log update
        self.update_log_from_session()
    
    def setup_window(self):
        """Configure the main window properties"""
        self.root.resizable(True, True)
        self.root.minsize(800, 600)
        
        # Configure grid weights for responsive design
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Set window icon (if available)
        try:
            self.root.iconname("P2V Converter")
        except (tk.TclError, AttributeError):
            pass

    def is_disk_unavailable_for_conversion(self, device_path):
        """
        Check if a disk is unavailable for conversion
        """
        try:
            if is_system_disk(device_path):
                return True, "This is an active system disk currently in use"
            
            from utils import has_mounted_partitions
            if has_mounted_partitions(device_path):
                return True, "This disk has mounted partitions"
            
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
                                    return True, f"Partition {mounted_device} is mounted at {mount_point}"
            
            except IOError as e:
                log_warning(f"Could not read mount status from /proc/mounts: {str(e)}")
            except OSError as e:
                log_warning(f"System error checking mount status: {str(e)}")
            
            return False, "Available for conversion"
                
        except FileNotFoundError as e:
            log_error(f"Required file or command not found checking disk availability: {str(e)}")
            return True, "Unable to verify disk status - file not found"
        except PermissionError as e:
            log_error(f"Permission denied checking disk availability: {str(e)}")
            return True, "Unable to verify disk status - permission denied"
        except subprocess.CalledProcessError as e:
            log_error(f"Command failed checking disk availability: {str(e)}")
            return True, "Unable to verify disk status - command failed"
        except (ValueError, IndexError) as e:
            log_error(f"Error parsing disk information: {str(e)}")
            return True, "Unable to verify disk status - data error"
        except OSError as e:
            log_error(f"System error checking disk availability: {str(e)}")
            return True, "Unable to verify disk status - system error"
    
    def create_widgets(self):
        """Create all GUI widgets - Updated version with Format Converter integration"""
        self.create_header_frame()
        self.create_main_frame()
        self.create_status_frame()  
    
    def create_header_frame(self):
        """Create the header frame with title and PDF generation buttons"""
        header_frame = ttk.Frame(self.root, padding="10")
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)  # Make middle column expand
        
        # Title label with icon-like symbol
        title_frame = ttk.Frame(header_frame)
        title_frame.grid(row=0, column=0, sticky="w")
        
        title_label = ttk.Label(title_frame, text="P2V Converter", 
                               font=("Arial", 18, "bold"))
        title_label.grid(row=0, column=0, sticky="w")
        
        subtitle_label = ttk.Label(title_frame, text="Physical to Virtual Machine Converter", 
                                  font=("Arial", 9), foreground="gray")
        subtitle_label.grid(row=1, column=0, sticky="w")
        
        # Button frame for PDF generation buttons
        button_frame = ttk.Frame(header_frame)
        button_frame.grid(row=0, column=2, sticky="e")
        
        # Print session log button
        self.session_pdf_btn = ttk.Button(button_frame, 
                                         text="Print Session Log",
                                         command=self.generate_session_pdf,
                                         width=20)
        self.session_pdf_btn.grid(row=0, column=0, padx=(0, 5))
        
        # Print complete log file button
        self.file_pdf_btn = ttk.Button(button_frame, 
                                      text="Print Complete Log",
                                      command=self.generate_log_file_pdf,
                                      width=20)
        self.file_pdf_btn.grid(row=0, column=1, padx=(0, 5))
        
        # Exit button
        self.exit_btn = ttk.Button(button_frame, 
                                  text="Exit",
                                  command=self.exit_application,
                                  width=12)
        self.exit_btn.grid(row=0, column=2)
        
        # Add separator
        separator = ttk.Separator(self.root, orient='horizontal')
        separator.grid(row=0, column=0, sticky="ew", pady=(0, 5), columnspan=1)
    
    def create_main_frame(self):
        """Create the main content frame - Updated with Format Converter button"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        main_frame.grid_rowconfigure(4, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        
        # Source disk selection frame
        source_frame = ttk.LabelFrame(main_frame, text="Source Disk Selection", padding="10")
        source_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        source_frame.grid_columnconfigure(1, weight=1)
        
        ttk.Label(source_frame, text="Physical Disk:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(source_frame, textvariable=self.source_var, 
                                        state="readonly", font=("Arial", 9))
        self.source_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.source_combo.bind("<<ComboboxSelected>>", self.on_source_selected)
        
        # Refresh button
        self.refresh_btn = ttk.Button(source_frame, text="Refresh Disks", 
                                    command=self.refresh_disks)
        self.refresh_btn.grid(row=0, column=2, padx=(10, 0))
        
        # VM configuration frame
        vm_config_frame = ttk.LabelFrame(main_frame, text="VM Configuration", padding="10")
        vm_config_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        vm_config_frame.grid_columnconfigure(1, weight=1)
        
        # VM Name
        ttk.Label(vm_config_frame, text="VM Name:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w")
        vm_name_entry = ttk.Entry(vm_config_frame, textvariable=self.vm_name, font=("Arial", 9))
        vm_name_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        vm_name_entry.bind("<KeyRelease>", self.validate_vm_name_input)
        
        # Output Directory
        ttk.Label(vm_config_frame, text="Output Directory:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(10, 0))
        
        output_frame = ttk.Frame(vm_config_frame)
        output_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10, 0))
        output_frame.grid_columnconfigure(0, weight=1)
        
        output_entry = ttk.Entry(output_frame, textvariable=self.output_path, font=("Arial", 9))
        output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        # Enhanced browse button with dropdown - Updated with Format Converter button
        browse_frame = ttk.Frame(output_frame)
        browse_frame.grid(row=0, column=1)
        
        browse_btn = ttk.Button(browse_frame, text="Browse", command=self.browse_output_dir)
        browse_btn.grid(row=0, column=0, padx=(0, 2))
        
        mount_btn = ttk.Button(browse_frame, text="Mount Disk", command=self.mount_disk_dialog)
        mount_btn.grid(row=0, column=1, padx=(0, 2))
        
        # QCOW2 Clone Resize button
        resize_btn = ttk.Button(browse_frame, text="QCOW2 Resize", command=self.open_qcow2_resizer,
                            width=12)
        resize_btn.grid(row=0, column=2, padx=(0, 2))

        # NEW: Format Converter button
        convert_btn = ttk.Button(browse_frame, text="Format Converter", 
                                command=self.open_format_converter, 
                                width=14)
        convert_btn.grid(row=0, column=3, padx=(0, 0))

        # Add tooltip/description for the tools buttons
        tools_info_frame = ttk.Frame(vm_config_frame)
        tools_info_frame.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(5, 0))
        
        tools_info_label = ttk.Label(tools_info_frame, 
                                    text="QCOW2 Tools: Resize virtual disks | Format Converter: Convert between disk image formats",
                                    font=("Arial", 8), foreground="gray")
        tools_info_label.grid(row=0, column=0, sticky="w")
        
        # Space information frame
        space_frame = ttk.LabelFrame(main_frame, text="Storage Space Information", padding="10")
        space_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        
        self.space_info_text = tk.Text(space_frame, height=6, wrap=tk.WORD, state=tk.DISABLED, 
                                    font=("Consolas", 9), bg="#f8f8f8")
        space_scrollbar = ttk.Scrollbar(space_frame, orient="vertical", command=self.space_info_text.yview)
        self.space_info_text.configure(yscrollcommand=space_scrollbar.set)
        
        self.space_info_text.grid(row=0, column=0, sticky="nsew")
        space_scrollbar.grid(row=0, column=1, sticky="ns")
        
        space_frame.grid_rowconfigure(0, weight=1)
        space_frame.grid_columnconfigure(0, weight=1)
        
        # Control buttons frame
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        
        self.check_space_btn = ttk.Button(control_frame, text="Check Space Requirements", 
                                        command=self.check_space_requirements)
        self.check_space_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.convert_btn = ttk.Button(control_frame, text="Start P2V Conversion", 
                                    command=self.start_conversion)
        self.convert_btn.grid(row=0, column=1, padx=(0, 10))
        
        self.stop_btn = ttk.Button(control_frame, text="Stop Operation", 
                                command=self.stop_operation, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=2, padx=(0, 10))
        
        self.clear_log_btn = ttk.Button(control_frame, text="Clear Display", 
                                    command=self.clear_log_display)
        self.clear_log_btn.grid(row=0, column=3)
        
        # Progress and log area
        log_frame = ttk.LabelFrame(main_frame, text="Operation Log", padding="5")
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        # Create text widget with scrollbar
        text_frame = ttk.Frame(log_frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)
        
        self.log_text = tk.Text(text_frame, wrap=tk.WORD, state=tk.DISABLED, 
                            font=("Consolas", 9), bg="#f8f8f8", fg="#333333")
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
    
    def open_qcow2_resizer(self):
        """Open the QCOW2 resizer dialog as a modal window"""
        try:
            log_info("Opening QCOW2 Clone Resizer dialog")
            
            # Import and create the resizer directly - it creates its own Toplevel
            resizer_app = QCow2CloneResizerGUI(self.root)
            
            # The resizer creates its own window, so just wait for it
            log_info("QCOW2 Clone Resizer dialog opened")
            
        except ImportError as e:
            error_msg = f"QCOW2 Clone Resizer not available: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Feature Not Available", 
                            "QCOW2 Clone Resizer feature is not available.\n\n"
                            "Please ensure qcow2_resize_dialog.py is in the same directory.\n\n"
                            "Missing dependency: qcow2_resize_dialog module")
        except AttributeError as e:
            error_msg = f"Error initializing QCOW2 Clone Resizer: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Initialization Error", 
                            f"Failed to initialize QCOW2 Clone Resizer:\n\n{error_msg}")
        except tk.TclError as e:
            error_msg = f"Window creation error: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Window Error", 
                            f"Failed to create QCOW2 Clone Resizer window:\n\n{error_msg}")
        except TypeError as e:
            error_msg = f"Type error initializing QCOW2 Clone Resizer: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Type Error", 
                            f"Failed to initialize QCOW2 Clone Resizer:\n\n{error_msg}")
        except ValueError as e:
            error_msg = f"Invalid value for QCOW2 Clone Resizer: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Value Error", 
                            f"Failed to initialize QCOW2 Clone Resizer:\n\n{error_msg}")
        except MemoryError as e:
            error_msg = "Insufficient memory to open QCOW2 Clone Resizer"
            log_error(error_msg)
            messagebox.showerror("Memory Error", 
                            f"Failed to open QCOW2 Clone Resizer:\n\n{error_msg}")
        except OSError as e:
            error_msg = f"System error opening QCOW2 Clone Resizer: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", 
                            f"Failed to open QCOW2 Clone Resizer:\n\n{error_msg}")

    def open_format_converter(self):
        """Open the Format Converter dialog as a modal window"""
        try:
            log_info("Opening Format Converter dialog")
            
            # Import the converter module
            from image_format_converter import ImageFormatConverter
            
            # Create the converter directly - it creates its own Toplevel window
            converter_app = ImageFormatConverter(self.root)
            
            log_info("Format Converter dialog opened")
            
        except ImportError as e:
            error_msg = f"Format Converter not available: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Feature Not Available", 
                            "Format Converter feature is not available.\n\n"
                            "Please ensure image_format_converter.py is in the same directory.\n\n"
                            f"Missing dependency: {str(e)}")
        except AttributeError as e:
            error_msg = f"Error initializing Format Converter: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Initialization Error", 
                            f"Failed to initialize Format Converter:\n\n{error_msg}")
        except tk.TclError as e:
            error_msg = f"Window creation error: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Window Error", 
                            f"Failed to create Format Converter window:\n\n{error_msg}")
        except TypeError as e:
            error_msg = f"Type error initializing Format Converter: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Type Error", 
                            f"Failed to initialize Format Converter:\n\n{error_msg}")
        except ValueError as e:
            error_msg = f"Invalid value for Format Converter: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Value Error", 
                            f"Failed to initialize Format Converter:\n\n{error_msg}")
        except MemoryError as e:
            error_msg = "Insufficient memory to open Format Converter"
            log_error(error_msg)
            messagebox.showerror("Memory Error", 
                            f"Failed to open Format Converter:\n\n{error_msg}")
        except OSError as e:
            error_msg = f"System error opening Format Converter: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", 
                            f"Failed to open Format Converter:\n\n{error_msg}")
        except FileNotFoundError as e:
            error_msg = f"Required file not found: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("File Not Found", 
                            f"Failed to open Format Converter:\n\n{error_msg}")
        except PermissionError as e:
            error_msg = f"Permission denied: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Permission Error", 
                            f"Failed to open Format Converter:\n\n{error_msg}")

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
            error_msg = f"Permission denied accessing disk mount dialog: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Permission Error", error_msg)
        except OSError as e:
            error_msg = f"System error in disk mount dialog: {str(e)}"
            log_error(error_msg) 
            messagebox.showerror("System Error", error_msg)
        except ImportError as e:
            error_msg = f"Missing required module for disk mounting: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Import Error", error_msg)
        except subprocess.CalledProcessError as e:
            error_msg = f"Command failed in disk mount dialog: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Command Error", error_msg) 
        except ValueError as e:
            error_msg = f"Invalid value in disk mount dialog: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Value Error", error_msg)
        except (AttributeError, TypeError) as e:
            error_msg = f"Internal error in disk mount dialog: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Internal Error", error_msg)
        except tk.TclError as e:
            error_msg = f"Dialog window error: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Dialog Error", error_msg)
    
    def create_status_frame(self):
        """Create the status frame at the bottom"""
        status_frame = ttk.Frame(self.root, padding="10")
        status_frame.grid(row=2, column=0, sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)
        
        # Progress bar with label
        progress_label = ttk.Label(status_frame, text="Progress:")
        progress_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, 
                                           maximum=100, length=300)
        self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        
        # Progress percentage label
        self.progress_label = ttk.Label(status_frame, text="0%")
        self.progress_label.grid(row=0, column=2, sticky="w", padx=(0, 20))
        
        # Status label
        status_info_label = ttk.Label(status_frame, text="Status:")
        status_info_label.grid(row=0, column=3, sticky="w", padx=(0, 10))
        
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, 
                                     font=("Arial", 9, "bold"))
        self.status_label.grid(row=0, column=4, sticky="w")
        
        # Current operation details
        self.operation_details = ttk.Label(status_frame, text="", 
                                          font=("Arial", 8), foreground="gray")
        self.operation_details.grid(row=1, column=0, columnspan=5, sticky="w", pady=(5, 0))
        
        # Initialize with disk refresh
        self.root.after(100, self.refresh_disks)  # Delayed initialization
    
    def check_prerequisites(self):
        """Check if required tools are available"""
        tools_available, message = check_qemu_tools()
        if not tools_available:
            log_error(f"Prerequisites check failed: {message}")
            messagebox.showerror("Missing Prerequisites", 
                               f"Required tools are missing:\n\n{message}\n\n"
                               f"Please install the required packages:\n"
                               f"• qemu-utils (for qemu-img)\n"
                               f"• coreutils (for dd)")
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
                            disk_info = f"SYSTEM: {disk_info} [ACTIVE]"
                        elif "mounted" in reason.lower():
                            disk_info = f"MOUNTED: {disk_info} [IN USE]"
                        else:
                            disk_info = f"BUSY: {disk_info} [UNAVAILABLE]"
                    
                    disk_options.append(disk_info)
                
                self.source_combo['values'] = disk_options
                
                if self.source_var.get() not in disk_options:
                    self.source_var.set("")
                
                log_info(f"Found {len(self.current_disks)} disk(s)")
                
                available_count = len(self.current_disks) - unavailable_count
                if unavailable_count > 0:
                    self.status_var.set(f"Found {len(self.current_disks)} disk(s) ({available_count} available, {unavailable_count} unavailable)")
                else:
                    self.status_var.set(f"Found {len(self.current_disks)} disk(s) (all available)")
                
            else:
                log_warning("No disks found")
                self.status_var.set("No disks found")
                self.source_combo['values'] = []
                
        except OSError as e:
            error_msg = f"System error refreshing disks: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except subprocess.CalledProcessError as e:
            error_msg = f"Command execution error: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Command Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except FileNotFoundError as e:
            error_msg = f"Required command not found: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Command Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except (ValueError, KeyError) as e:
            error_msg = f"Data parsing error: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Data Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except PermissionError as e:
            error_msg = f"Permission denied accessing disk information: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Permission Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except AttributeError as e:
            error_msg = f"Invalid data structure returned: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Data Error", error_msg)
            self.status_var.set("Error refreshing disks")
    
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
                warning_title = "Disk Unavailable for Conversion"
                warning_message = f"Cannot Select Disk for Conversion\n\n"
                warning_message += f"Selected disk: {device_path}\n"
                warning_message += f"Reason: {reason}\n\n"
                
                if "active system disk" in reason.lower():
                    warning_message += f"Converting an active system disk is dangerous and may:\n"
                    warning_message += f"• Cause system instability or crashes\n"
                    warning_message += f"• Result in incomplete or corrupted conversion\n"
                    warning_message += f"• Interfere with running system processes\n\n"
                    warning_message += f"Recommendations:\n"
                    warning_message += f"• Select a different, inactive disk for conversion\n"
                    warning_message += f"• Boot from a live USB/CD to convert this disk safely"
                
                elif "mounted" in reason.lower():
                    warning_message += f"Converting a disk with mounted partitions may:\n"
                    warning_message += f"• Cause data corruption or loss\n"
                    warning_message += f"• Result in incomplete conversion\n"
                    warning_message += f"• Interfere with active file operations\n\n"
                    warning_message += f"Recommendations:\n"
                    warning_message += f"• Unmount all partitions on this disk first\n"
                    warning_message += f"• Select a different disk that is not mounted\n"
                    warning_message += f"• Use 'umount' command to safely unmount partitions"
                
                else:
                    warning_message += f"Please select a different disk that is not in use."
                
                messagebox.showerror(warning_title, warning_message)
                
                # Clear the selection
                self.source_var.set("")
                log_warning(f"User attempted to select unavailable disk: {device_path} - {reason}")
                self.status_var.set("Disk selection denied")
                self.operation_details.config(text=f"Cannot select disk: {reason}", foreground="red")
                
                # Clear space info
                self.space_info_text.config(state=tk.NORMAL)
                self.space_info_text.delete(1.0, tk.END)
                self.space_info_text.insert(tk.END, 
                    "Please select a disk that is not mounted or in active use for P2V conversion.\n\n"
                    "Safe disks for conversion:\n"
                    "• Secondary storage drives not currently mounted\n"
                    "• External drives that are unmounted\n"
                    "• Drives from systems booted via live media")
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
            self.operation_details.config(text=f"Warning: {message}", foreground="red")
        else:
            self.operation_details.config(text="", foreground="gray")
    
    def browse_output_dir(self):
        """Browse for output directory"""
        selected_dir = filedialog.askdirectory(
            title="Select Output Directory for VM Files",
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
                messagebox.showwarning("Warning", "Please select a source disk first")
                return
            
            if not output_dir:
                messagebox.showwarning("Warning", "Please specify an output directory")
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
            
            info_text = f"Source Disk: {device_path}\n"
            info_text += f"Model: {disk_info.get('model', 'Unknown')}\n"
            if disk_info.get('label') and disk_info['label'] != "Unknown":
                info_text += f"Label: {disk_info['label']}\n"
            info_text += f"Output Directory: {output_dir}\n\n"
            info_text += space_message
            
            # Add system disk warning if applicable
            if is_system_disk(device_path):
                info_text += "\n\nWarning: This is an active system disk!"
            
            self.space_info_text.insert(tk.END, info_text)
            self.space_info_text.config(state=tk.DISABLED)
            
            if has_space:
                log_info("Space check passed - sufficient space available")
                self.operation_details.config(text="Sufficient space available", foreground="green")
            else:
                log_error("Space check failed - insufficient space")
                self.operation_details.config(text="Insufficient space", foreground="red")
                messagebox.showwarning("Insufficient Space", 
                                     f"Not enough space available!\n\n{space_message}")
            
        except (OSError, IOError) as e:
            error_msg = f"System error checking space requirements: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", error_msg)
            self.operation_details.config(text="Space check failed", foreground="red")
        except (ValueError, TypeError) as e:
            error_msg = f"Data error checking space requirements: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Data Error", error_msg)
            self.operation_details.config(text="Space check failed", foreground="red")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = f"Command error checking space requirements: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Command Error", error_msg)
            self.operation_details.config(text="Space check failed", foreground="red")
    
    def start_conversion(self):
        """Start the P2V conversion operation with enhanced validation"""
        source = self.source_var.get()
        vm_name = self.vm_name.get().strip()
        output_dir = self.output_path.get().strip()
        
        # Validation
        if not source:
            messagebox.showwarning("Warning", "Please select a source disk")
            return
        
        if not vm_name:
            messagebox.showwarning("Warning", "Please enter a VM name")
            return
        
        if not output_dir:
            messagebox.showwarning("Warning", "Please specify an output directory")
            return
        
        # Validate VM name
        is_valid, validation_message = validate_vm_name(vm_name)
        if not is_valid:
            messagebox.showerror("Invalid VM Name", validation_message)
            return
        
        # Extract device path
        device_path = source.split(' ')[1] if source.startswith(('SYSTEM:', 'MOUNTED:', 'BUSY:')) else source.split(' ')[0]
        
        # Final safety check - re-validate disk availability right before conversion
        is_unavailable, reason = self.is_disk_unavailable_for_conversion(device_path)
        if is_unavailable:
            messagebox.showerror("Disk Unavailable", 
                            f"Conversion Blocked\n\n"
                            f"The selected disk ({device_path}) is not available for conversion.\n\n"
                            f"Reason: {reason}\n\n"
                            f"Please select a different disk or resolve the issue before converting.")
            # Refresh disk list to update status
            self.refresh_disks()
            return
        
        # Space check before starting
        try:
            has_space, space_message = check_output_space(output_dir, device_path)
            if not has_space:
                if not messagebox.askyesno("Insufficient Space Warning",
                                        f"Space Warning\n\n{space_message}\n\n"
                                        f"Continue anyway? The conversion may fail."):
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
            confirmation_text = f"P2V Conversion Confirmation\n\n"
            confirmation_text += f"Source Disk: {device_path}\n"
            confirmation_text += f"Model: {disk_info.get('model', 'Unknown')}\n"
            confirmation_text += f"Size: {disk_info.get('size_human', 'Unknown')}\n"
            if disk_info.get('label') and disk_info['label'] != "Unknown":
                confirmation_text += f"Label: {disk_info['label']}\n"
            confirmation_text += f"VM Name: {vm_name}\n"
            confirmation_text += f"Output Directory: {output_dir}\n\n"
            confirmation_text += f"This will create a compressed qcow2 virtual machine.\n"
            confirmation_text += f"The process may take a significant amount of time.\n\n"
            confirmation_text += f"Continue with the conversion?"
        except (OSError, IOError, ValueError, KeyError, AttributeError):
            confirmation_text = f"P2V Conversion Confirmation\n\n"
            confirmation_text += f"Source Disk: {device_path}\n"
            confirmation_text += f"VM Name: {vm_name}\n"
            confirmation_text += f"Output Directory: {output_dir}\n\n"
            confirmation_text += f"Continue with the conversion?"
        
        if not messagebox.askyesno("Confirm P2V Conversion", confirmation_text):
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
        self.status_var.set("P2V conversion in progress...")

    
    def _conversion_worker(self, source_device, output_dir, vm_name):
        """Worker thread for P2V conversion operation"""
        try:
            log_info(f"Starting P2V conversion: {source_device} -> {vm_name}.qcow2")
            
            def progress_callback(percent, status):
                self.root.after(0, lambda: self._update_progress(percent, status))
            
            def stop_check():
                return self.stop_requested
            
            # Perform the conversion using the improved function
            output_file = create_vm_from_disk(source_device, output_dir, vm_name, 
                                            progress_callback, stop_check)
            
            if not self.stop_requested:
                log_info("P2V conversion completed successfully")
                
                # Get final file size
                final_size = os.path.getsize(output_file)
                log_info(f"VM created: {output_file} ({format_bytes(final_size)})")
                
                # Show completion dialog with enhanced information
                completion_text = f"P2V conversion completed successfully!\n\n"
                completion_text += f"VM File: {output_file}\n"
                completion_text += f"Size: {format_bytes(final_size)}\n\n"
                completion_text += f"You can now use this qcow2 file with:\n"
                completion_text += f"• QEMU/KVM virtualization\n"
                completion_text += f"• VirtualBox (with conversion)\n"
                completion_text += f"• Other virtualization platforms supporting qcow2\n\n"
                completion_text += f"To boot the VM with QEMU:\n"
                completion_text += f"qemu-system-x86_64 -hda \"{output_file}\" -m 2048\n\n"
                completion_text += f"Use 'Resize QCOW2...' button to optimize disk size if needed."
                
                self.root.after(0, lambda: messagebox.showinfo("Conversion Complete", completion_text))
        
        except FileNotFoundError as e:
            error_msg = f"Required command or file not found: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Command Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except subprocess.CalledProcessError as e:
            error_msg = f"Command execution failed: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Command Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except PermissionError as e:
            error_msg = f"Permission denied accessing disk or output directory: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Permission Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except OSError as e:
            error_msg = f"System error during disk operation: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("System Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except ValueError as e:
            error_msg = f"Invalid value or parameter: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Value Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except TypeError as e:
            error_msg = f"Type error in conversion process: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Type Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except AttributeError as e:
            error_msg = f"Object attribute error during conversion: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Attribute Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except KeyboardInterrupt:
            log_warning("P2V conversion cancelled by user")
            self.root.after(0, lambda: messagebox.showinfo("Cancelled", 
                "P2V conversion was cancelled by user"))
                
        except MemoryError as e:
            error_msg = "Insufficient memory to perform conversion"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Memory Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
                
        except Exception as e:
            error_msg = f"Unexpected error during conversion: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Unexpected Error", 
                f"P2V conversion failed:\n\n{error_msg}"))
        
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
        self.status_var.set("Ready")
        self.operation_details.config(text="", foreground="gray")
    
    def stop_operation(self):
        """Stop the current operation"""
        if self.operation_running:
            self.stop_requested = True
            log_warning("Stop requested by user")
            self.status_var.set("Stopping...")
            self.operation_details.config(text="Stopping operation, please wait...", foreground="orange")
    
    def exit_application(self):
        """Exit the application with confirmation"""
        if self.operation_running:
            result = messagebox.askyesno("Exit Confirmation", 
                                       "An operation is currently running.\n\n"
                                       "Are you sure you want to exit?\n"
                                       "This will stop the current operation.")
            if result:
                self.stop_requested = True
                log_warning("Application exit requested during operation")
                # Give a moment for the operation to stop
                self.root.after(1000, self._force_exit)
            return
        
        # Normal exit confirmation
        result = messagebox.askyesno("Exit Confirmation", 
                                   "Are you sure you want to exit the P2V Converter?")
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
    
    def generate_session_pdf(self):
        """Generate PDF from current session logs"""
        try:
            log_info("Generating session log PDF...")
            
            # Disable button during generation
            self.session_pdf_btn.config(state=tk.DISABLED)
            self.status_var.set("Generating PDF...")
            
            # Generate PDF using the log_handler function
            pdf_path = generate_session_pdf()
            
            # Show success message with option to open location
            result = messagebox.askyesnocancel("PDF Generated", 
                                            f"Session log PDF generated successfully!\n\n"
                                            f"Location: {pdf_path}\n\n"
                                            f"Would you like to open the containing folder?")
            
            if result:  # Yes - open folder
                try:
                    import platform
                    folder_path = os.path.dirname(pdf_path)
                    
                    if platform.system() == "Linux":
                        subprocess.run(["xdg-open", folder_path])
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.run(["open", folder_path])
                    elif platform.system() == "Windows":
                        subprocess.run(["explorer", folder_path])
                except FileNotFoundError as e:
                    log_warning(f"Folder not found: {str(e)}")
                    messagebox.showerror("Error", f"Could not find folder: {str(e)}")
                except subprocess.CalledProcessError as e:
                    log_warning(f"Failed to open folder: {str(e)}")
                    messagebox.showerror("Error", f"Failed to open folder: {str(e)}")
                except OSError as e:
                    log_warning(f"System error opening folder: {str(e)}")
                    messagebox.showerror("Error", f"System error opening folder: {str(e)}")
            
            log_info(f"Session PDF generated: {pdf_path}")
            
        except ValueError as e:
            log_warning(f"Cannot generate session PDF: {str(e)}")
            messagebox.showerror("PDF Generation Error", f"Cannot generate session PDF:\n\n{str(e)}")
        except PermissionError as e:
            log_error(f"Permission denied: {str(e)}")
            messagebox.showerror("Permission Error", f"Permission denied generating PDF:\n\n{str(e)}")
        except OSError as e:
            log_error(f"System error generating PDF: {str(e)}")
            messagebox.showerror("System Error", f"System error generating PDF:\n\n{str(e)}")
        except ImportError as e:
            log_error(f"Missing required module: {str(e)}")
            messagebox.showerror("Module Error", f"Missing required module:\n\n{str(e)}")
        except (AttributeError, TypeError) as e:
            log_error(f"Internal error generating PDF: {str(e)}")
            messagebox.showerror("Internal Error", f"Internal error generating PDF:\n\n{str(e)}")
        finally:
            # Re-enable button and reset status
            self.session_pdf_btn.config(state=tk.NORMAL)
            self.status_var.set("Ready")
        
    def generate_log_file_pdf(self):
        """Generate PDF from complete log file"""
        try:
            log_info("Generating complete log file PDF...")
            
            # Disable button during generation
            self.file_pdf_btn.config(state=tk.DISABLED)
            self.status_var.set("Generating PDF...")
            
            # Generate PDF using the log_handler function
            pdf_path = generate_log_file_pdf()
            
            # Show success message with option to open location
            result = messagebox.askyesnocancel("PDF Generated", 
                                             f"Complete log file PDF generated successfully!\n\n"
                                             f"Location: {pdf_path}\n\n"
                                             f"Would you like to open the containing folder?")
            
            if result:  # Yes - open folder
                try:
                    import subprocess
                    import platform
                    folder_path = os.path.dirname(pdf_path)
                    
                    if platform.system() == "Linux":
                        subprocess.run(["xdg-open", folder_path])
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.run(["open", folder_path])
                    elif platform.system() == "Windows":
                        subprocess.run(["explorer", folder_path])
                except (OSError, subprocess.CalledProcessError, FileNotFoundError) as e:
                    log_warning(f"Could not open folder: {str(e)}")
            
            log_info(f"Complete log PDF generated: {pdf_path}")
            
        except FileNotFoundError as e:
            log_warning(f"Cannot generate log file PDF: {str(e)}")
            messagebox.showwarning("Log File Not Found", 
                                 f"Cannot generate PDF:\n\n{str(e)}")
        except (PermissionError, OSError, IOError) as e:
            error_msg = f"Failed to generate log file PDF: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"Failed to generate PDF:\n\n{error_msg}")
        except UnicodeDecodeError as e:
            error_msg = f"Text encoding error in log file: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"Text encoding error:\n\n{error_msg}")
        except ImportError as e:
            error_msg = f"Missing required module for PDF generation: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"Missing dependency:\n\n{error_msg}")
        except (AttributeError, TypeError, KeyError, ValueError) as e:
            error_msg = f"Unexpected error generating log file PDF: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"Unexpected error:\n\n{error_msg}")
        
        finally:
            # Re-enable button and reset status
            self.file_pdf_btn.config(state=tk.NORMAL)
            self.status_var.set("Ready")


def main():
    """Main entry point for the GUI application"""
    root = tk.Tk()
    app = P2VConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()