#!/usr/bin/env python3
"""
P2V Converter GUI Module
Provides the graphical user interface for the Physical to Virtual converter
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import time
from log_handler import (log_info, log_error, log_warning, generate_session_pdf, 
                        generate_log_file_pdf, session_start, session_end, 
                        log_application_exit, get_current_session_logs, 
                        is_session_active)
from utils import (get_disk_list, get_directory_space, check_output_space, check_qemu_tools, 
                   create_vm_from_disk, validate_vm_name, format_bytes, get_active_disk,
                   get_disk_info, is_system_disk)

class P2VConverterGUI:
    """GUI class for the P2V Converter application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Physical to Virtual (P2V) Converter")
        self.root.geometry("1000x800")
        
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
    
    def create_widgets(self):
        """Create all GUI widgets"""
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
        
        title_label = ttk.Label(title_frame, text="🖥️ P2V Converter", 
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
                                         text="📄 Print Session Log",
                                         command=self.generate_session_pdf,
                                         width=20)
        self.session_pdf_btn.grid(row=0, column=0, padx=(0, 5))
        
        # Print complete log file button
        self.file_pdf_btn = ttk.Button(button_frame, 
                                      text="📋 Print Complete Log",
                                      command=self.generate_log_file_pdf,
                                      width=20)
        self.file_pdf_btn.grid(row=0, column=1, padx=(0, 5))
        
        # Exit button
        self.exit_btn = ttk.Button(button_frame, 
                                  text="❌ Exit",
                                  command=self.exit_application,
                                  width=12)
        self.exit_btn.grid(row=0, column=2)
        
        # Add separator
        separator = ttk.Separator(self.root, orient='horizontal')
        separator.grid(row=0, column=0, sticky="ew", pady=(0, 5), columnspan=1)
    
    def create_main_frame(self):
        """Create the main content frame"""
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
        self.refresh_btn = ttk.Button(source_frame, text="🔄 Refresh Disks", 
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
        
        browse_btn = ttk.Button(output_frame, text="Browse...", command=self.browse_output_dir)
        browse_btn.grid(row=0, column=1)
        
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
        
        self.check_space_btn = ttk.Button(control_frame, text="💾 Check Space Requirements", 
                                         command=self.check_space_requirements)
        self.check_space_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.convert_btn = ttk.Button(control_frame, text="▶️ Start P2V Conversion", 
                                     command=self.start_conversion)
        self.convert_btn.grid(row=0, column=1, padx=(0, 10))
        
        self.stop_btn = ttk.Button(control_frame, text="⏹️ Stop Operation", 
                                  command=self.stop_operation, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=2, padx=(0, 10))
        
        self.clear_log_btn = ttk.Button(control_frame, text="🗑️ Clear Display", 
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
                               f"❌ Required tools are missing:\n\n{message}\n\n"
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
            
            # Get list of disks using updated function
            self.current_disks = get_disk_list()
            
            if self.current_disks:
                # Format disk info for display with improved labeling
                disk_options = []
                for disk in self.current_disks:
                    # Create base display string
                    disk_info = f"{disk['device']} ({disk['size']}) - {disk['model']}"
                    
                    # Add label if available
                    if disk['label'] and disk['label'] != "No Label":
                        disk_info += f" [{disk['label']}]"
                    
                    # Mark system/active disks
                    if disk.get('is_active', False):
                        disk_info = f"🟡 {disk_info} [SYSTEM DISK]"
                    
                    disk_options.append(disk_info)
                
                # Update combobox
                self.source_combo['values'] = disk_options
                
                # Clear previous selection if it's no longer valid
                if self.source_var.get() not in disk_options:
                    self.source_var.set("")
                
                log_info(f"Found {len(self.current_disks)} disk(s)")
                
                # Count active disks for status
                active_count = sum(1 for disk in self.current_disks if disk.get('is_active', False))
                if active_count > 0:
                    self.status_var.set(f"Found {len(self.current_disks)} disk(s) ({active_count} active)")
                else:
                    self.status_var.set(f"Found {len(self.current_disks)} disk(s)")
                
            else:
                log_warning("No disks found")
                self.status_var.set("No disks found")
                self.source_combo['values'] = []
                
        except (OSError, IOError) as e:
            error_msg = f"System error refreshing disks: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = f"Command execution error refreshing disks: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Command Error", error_msg)
            self.status_var.set("Error refreshing disks")
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            error_msg = f"Data parsing error refreshing disks: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Data Error", error_msg)
            self.status_var.set("Error refreshing disks")
    
    def get_selected_disk_info(self):
        """Get disk info for currently selected disk"""
        selected = self.source_var.get()
        if not selected:
            return None
        
        # Extract device path from display string
        device_path = selected.split(' ')[0].replace('🟡 ', '')
        
        # Find matching disk in current_disks
        for disk in self.current_disks:
            if disk['device'] == device_path:
                return disk
        
        return None
    
    def on_source_selected(self, event=None):
        """Handle source disk selection"""
        selected = self.source_var.get()
        if selected:
            # Extract device path
            device_path = selected.split(' ')[0].replace('🟡 ', '')
            
            # Check if this is an active/system disk
            if is_system_disk(device_path) or "SYSTEM DISK" in selected:
                # Show warning and refuse selection
                messagebox.showerror("Active Disk Selection Denied", 
                                   f"🚫 Cannot Select Active System Disk\n\n"
                                   f"The selected disk ({device_path}) is currently active and in use by the system.\n\n"
                                   f"Converting an active system disk is not recommended as it may:\n"
                                   f"• Cause system instability\n"
                                   f"• Result in incomplete or corrupted conversion\n"
                                   f"• Interfere with running system processes\n\n"
                                   f"Please:\n"
                                   f"• Select a different, inactive disk for conversion\n"
                                   f"• Or boot from a live USB/CD to convert this disk safely")
                
                # Clear the selection
                self.source_var.set("")
                log_warning(f"User attempted to select active system disk: {device_path}")
                self.status_var.set("Active disk selection denied")
                self.operation_details.config(text="❌ Cannot select active system disk", foreground="red")
                
                # Clear space info
                self.space_info_text.config(state=tk.NORMAL)
                self.space_info_text.delete(1.0, tk.END)
                self.space_info_text.insert(tk.END, "Please select a non-active disk for P2V conversion.")
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
            self.operation_details.config(text=f"⚠️ {message}", foreground="red")
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
            device_path = source.split(' ')[0].replace('🟡 ', '')
            
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
                info_text += "\n\n⚠️ WARNING: This is an active system disk!"
            
            self.space_info_text.insert(tk.END, info_text)
            self.space_info_text.config(state=tk.DISABLED)
            
            if has_space:
                log_info("Space check passed - sufficient space available")
                self.operation_details.config(text="✅ Sufficient space available", foreground="green")
            else:
                log_error("Space check failed - insufficient space")
                self.operation_details.config(text="❌ Insufficient space", foreground="red")
                messagebox.showwarning("Insufficient Space", 
                                     f"⚠️ Not enough space available!\n\n{space_message}")
            
        except (OSError, IOError) as e:
            error_msg = f"System error checking space requirements: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", error_msg)
            self.operation_details.config(text="❌ Space check failed", foreground="red")
        except (ValueError, TypeError) as e:
            error_msg = f"Data error checking space requirements: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Data Error", error_msg)
            self.operation_details.config(text="❌ Space check failed", foreground="red")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = f"Command error checking space requirements: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Command Error", error_msg)
            self.operation_details.config(text="❌ Space check failed", foreground="red")
    
    def start_conversion(self):
        """Start the P2V conversion operation"""
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
        device_path = source.split(' ')[0].replace('🟡 ', '')
        
        # Double-check that this is not an active disk (safety check)
        if is_system_disk(device_path) or "SYSTEM DISK" in source:
            messagebox.showerror("Active Disk Detected", 
                               f"🚫 Conversion Blocked\n\n"
                               f"The selected disk ({device_path}) is an active system disk.\n\n"
                               f"This disk cannot be converted while it's in use.\n"
                               f"Please select a different disk or boot from a live system.")
            return
        
        # Space check before starting
        try:
            has_space, space_message = check_output_space(output_dir, device_path)
            if not has_space:
                if not messagebox.askyesno("Insufficient Space Warning",
                                         f"⚠️ Space Warning ⚠️\n\n{space_message}\n\n"
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
            confirmation_text = f"🖥️ P2V Conversion Confirmation\n\n"
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
            confirmation_text = f"🖥️ P2V Conversion Confirmation\n\n"
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
                completion_text = f"✅ P2V conversion completed successfully!\n\n"
                completion_text += f"VM File: {output_file}\n"
                completion_text += f"Size: {format_bytes(final_size)}\n\n"
                completion_text += f"You can now use this qcow2 file with:\n"
                completion_text += f"• QEMU/KVM virtualization\n"
                completion_text += f"• VirtualBox (with conversion)\n"
                completion_text += f"• Other virtualization platforms supporting qcow2\n\n"
                completion_text += f"To boot the VM with QEMU:\n"
                completion_text += f"qemu-system-x86_64 -hda \"{output_file}\" -m 2048"
                
                self.root.after(0, lambda: messagebox.showinfo("Conversion Complete", completion_text))
            
        except KeyboardInterrupt:
            log_warning("P2V conversion cancelled by user")
        except (OSError, IOError) as e:
            error_msg = f"System error during P2V conversion: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Conversion Failed", 
                f"❌ P2V conversion failed:\n\n{error_msg}"))
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = f"Command execution error during P2V conversion: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Conversion Failed", 
                f"❌ P2V conversion failed:\n\n{error_msg}"))
        except (ValueError, TypeError, AttributeError) as e:
            error_msg = f"Data processing error during P2V conversion: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Conversion Failed", 
                f"❌ P2V conversion failed:\n\n{error_msg}"))
        except PermissionError as e:
            error_msg = f"Permission denied during P2V conversion: {str(e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Conversion Failed", 
                f"❌ P2V conversion failed:\n\n{error_msg}"))
        
        finally:
            # Reset UI in main thread
            self.root.after(0, self._reset_ui_after_operation)
    
    def _update_progress(self, percent, status):
        """Update progress bar and status from worker thread"""
        self.progress_var.set(percent)
        self.progress_label.config(text=f"{percent:.1f}%")
        self.operation_details.config(text=status, foreground="blue")
    
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
                                       "⚠️ An operation is currently running.\n\n"
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
                                             f"📄 Session log PDF generated successfully!\n\n"
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
            
            log_info(f"Session PDF generated: {pdf_path}")
            
        except ValueError as e:
            # Handle case where no session logs are available
            log_warning(f"Cannot generate session PDF: {str(e)}")
            messagebox.showwarning("No Session Data", 
                                 f"⚠️ Cannot generate session PDF:\n\n{str(e)}")
        except (PermissionError, OSError, IOError) as e:
            error_msg = f"Failed to generate session PDF: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Failed to generate PDF:\n\n{error_msg}")
        except ImportError as e:
            error_msg = f"Missing required module for PDF generation: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Missing dependency:\n\n{error_msg}")
        except (AttributeError, TypeError, KeyError) as e:
            error_msg = f"Unexpected error generating session PDF: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Unexpected error:\n\n{error_msg}")
        
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
                                             f"📋 Complete log file PDF generated successfully!\n\n"
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
                                 f"⚠️ Cannot generate PDF:\n\n{str(e)}")
        except (PermissionError, OSError, IOError) as e:
            error_msg = f"Failed to generate log file PDF: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Failed to generate PDF:\n\n{error_msg}")
        except UnicodeDecodeError as e:
            error_msg = f"Text encoding error in log file: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Text encoding error:\n\n{error_msg}")
        except ImportError as e:
            error_msg = f"Missing required module for PDF generation: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Missing dependency:\n\n{error_msg}")
        except (AttributeError, TypeError, KeyError, ValueError) as e:
            error_msg = f"Unexpected error generating log file PDF: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("PDF Generation Error", 
                               f"❌ Unexpected error:\n\n{error_msg}")
        
        finally:
            # Re-enable button and reset status
            self.file_pdf_btn.config(state=tk.NORMAL)
            self.status_var.set("Ready")