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


class VirtualImageExporter:
    """GUI for exporting virtual disk images using rsync"""
    
    def __init__(self, parent):
        self.parent = parent
        
        self.root = tk.Toplevel(parent)
        self.root.title("Virtual Image Export")
        self.root.geometry("950x900")
        self.root.minsize(850, 700)
        self.root.transient(parent)
        
        self.source_path = tk.StringVar()
        self.dest_path = tk.StringVar()
        self.operation_active = False
        
        log_info("Virtual Image Export dialog opened")
        
        self.setup_ui()
        self.check_prerequisites()
        
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    
    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno(
                "Operation in Progress",
                "An export operation is currently running. Stop and close?"
            )
            if not result:
                return
            
            log_warning("Export operation interrupted by user")
        
        log_info("Virtual Image Export dialog closed")
        self.root.destroy()
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        rsync_available = self._check_command('rsync')
        
        if not rsync_available:
            text = "Missing required tool: rsync\n\n"
            text += "Install rsync:\n"
            text += "Ubuntu/Debian: sudo apt install rsync\n"
            text += "Fedora/RHEL: sudo dnf install rsync\n"
            text += "Arch Linux: sudo pacman -S rsync\n"
            
            self.prereq_label.config(text=text, foreground="red")
            
            log_error("rsync not found - required for image export")
            
            messagebox.showerror(
                "Missing Required Tool",
                "rsync is required for image export.\n\n"
                "Please install the rsync package."
            )
        else:
            text = "✓ rsync available - Ready for image export"
            self.prereq_label.config(text=text, foreground="green")
            log_info("rsync available - prerequisites met")
    
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
            title="Select Virtual Image File",
            filetypes=[
                ("Virtual Images", "*.qcow2 *.img *.iso *.vdi *.vmdk"),
                ("QCOW2 Images", "*.qcow2"),
                ("Raw Images", "*.img"),
                ("ISO Images", "*.iso"),
                ("VDI Images", "*.vdi"),
                ("VMDK Images", "*.vmdk"),
                ("All Files", "*.*")
            ]
        )
        if file_path:
            self.source_path.set(file_path)
            self.analyze_source()
    
    def browse_destination_dir(self):
        """Browse for destination directory"""
        directory = filedialog.askdirectory(
            title="Select Destination Directory"
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
            messagebox.showerror("Error", f"Could not access home directory:\n{e}")
    
    def analyze_source(self):
        """Analyze selected source image"""
        path = self.source_path.get().strip()
        if not path:
            messagebox.showwarning("No File Selected", "Please select a source image file first")
            log_warning("Source analysis attempted but no file selected")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", "The selected file does not exist")
            log_error(f"Source file not found: {path}")
            return
        
        try:
            self.update_progress(1, "Analyzing source file...")
            
            file_size = os.path.getsize(path)
            file_name = os.path.basename(path)
            
            log_info(f"Analyzing source: {file_name} - Size: {self._format_size(file_size)}")
            
            self.display_source_info(path, file_size)
            self.update_progress(0, "Analysis complete - Ready")
            self.status_label.config(text="Source analyzed - Select destination")
            
            log_info(f"Source analysis completed successfully for {file_name}")
            
        except FileNotFoundError:
            messagebox.showerror("File Not Found", f"Source file not found: {path}")
            log_error(f"FileNotFoundError during source analysis: {path}")
            self.update_progress(0, "Analysis failed")
        except PermissionError:
            messagebox.showerror("Permission Denied", f"Permission denied: {path}")
            log_error(f"PermissionError during source analysis: {path}")
            self.update_progress(0, "Analysis failed")
        except OSError as e:
            messagebox.showerror("System Error", f"System error: {e}")
            log_error(f"OSError during source analysis: {e}")
            self.update_progress(0, "Analysis failed")
    
    def analyze_destination(self):
        """Analyze destination directory"""
        path = self.dest_path.get().strip()
        if not path:
            messagebox.showwarning("No Directory Selected", "Please select a destination directory first")
            log_warning("Destination analysis attempted but no directory selected")
            return
        
        if not os.path.isdir(path):
            messagebox.showerror("Directory Not Found", "The selected directory does not exist")
            log_error(f"Destination directory not found: {path}")
            return
        
        try:
            self.update_progress(1, "Analyzing destination...")
            
            stat = os.statvfs(path)
            available_space = stat.f_bavail * stat.f_frsize
            
            self.display_destination_info(path, available_space)
            
            # Check if source is selected and compare sizes
            if self.source_path.get():
                source_size = os.path.getsize(self.source_path.get())
                if source_size > available_space:
                    messagebox.showwarning(
                        "Insufficient Space",
                        f"Source size: {self._format_size(source_size)}\n"
                        f"Available space: {self._format_size(available_space)}"
                    )
                    log_warning(f"Insufficient space for export: need {source_size}, have {available_space}")
            
            self.update_progress(0, "Analysis complete - Ready")
            self.status_label.config(text="Destination ready - Ready to export")
            
            log_info(f"Destination analysis completed - Available: {self._format_size(available_space)}")
            
        except OSError as e:
            messagebox.showerror("System Error", f"System error: {e}")
            log_error(f"OSError during destination analysis: {e}")
            self.update_progress(0, "Analysis failed")
    
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
            messagebox.showwarning("No Source", "Please select a source image file")
            log_warning("Validation failed: no source file selected")
            return False
        
        if not os.path.isfile(source_path):
            messagebox.showerror("Invalid Source", f"Source file not found: {source_path}")
            log_error(f"Validation failed: source file not found - {source_path}")
            return False
        
        if not dest_path:
            messagebox.showwarning("No Destination", "Please select a destination directory")
            log_warning("Validation failed: no destination directory selected")
            return False
        
        if not os.path.isdir(dest_path):
            messagebox.showerror("Invalid Destination", f"Destination directory not found: {dest_path}")
            log_error(f"Validation failed: destination directory not found - {dest_path}")
            return False
        
        # Check available space
        try:
            source_size = os.path.getsize(source_path)
            stat = os.statvfs(dest_path)
            available = stat.f_bavail * stat.f_frsize
            
            if source_size > available:
                messagebox.showerror(
                    "Insufficient Space",
                    f"Not enough space in destination.\n\n"
                    f"Required: {self._format_size(source_size)}\n"
                    f"Available: {self._format_size(available)}"
                )
                log_error(f"Validation failed: insufficient space - need {source_size}, have {available}")
                return False
        except (OSError, ValueError) as e:
            log_warning(f"Could not check space: {e}")
        
        log_info("All inputs validated successfully")
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
                "File Exists",
                f"Destination file already exists:\n{dest_file}\n\nOverwrite?"
            )
            if not result:
                log_warning(f"Export cancelled - destination file already exists: {dest_file}")
                return
        
        # Confirmation dialog
        source_size = os.path.getsize(source_file)
        msg = f"IMAGE EXPORT CONFIRMATION\n\n"
        msg += f"Source: {file_name} ({self._format_size(source_size)})\n"
        msg += f"Destination: {dest_dir}\n\n"
        msg += f"⚠ Operation may take several minutes\n"
        msg += f"⚠ Destination file will be created/overwritten\n"
        msg += f"⚠ Source file will NOT be modified\n\n"
        msg += f"Continue?"
        
        if not messagebox.askyesno("Confirm Export", msg):
            log_warning("User cancelled export operation")
            return
        
        log_info(f"Starting export operation")
        log_info(f"Source file: {source_file}")
        log_info(f"Destination: {dest_file}")
        log_info(f"Source size: {self._format_size(source_size)}")
        
        self.operation_active = True
        self.export_btn.config(state="disabled")
        self.status_label.config(text="Export in progress...")
        
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
            
            msg = f"EXPORT COMPLETED!\n\n"
            msg += f"Source: {os.path.basename(source_file)}\n"
            msg += f"Destination: {dest_file}\n"
            msg += f"Size: {self._format_size(dest_size)}\n\n"
            msg += f"✓ Image successfully exported\n"
            msg += f"✓ Source file untouched\n"
            msg += f"✓ Ready for use\n"
            
            log_info(f"Export completed successfully")
            log_info(f"Output file size: {self._format_size(dest_size)}")
            
            self.root.after(0, lambda: messagebox.showinfo("Export Complete", msg))
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Export failed: {e}"
            log_error(f"CalledProcessError during export: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Export Failed", error_msg))
        except OSError as e:
            error_msg = f"System error: {e}"
            log_error(f"OSError during export: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("System Error", error_msg))
        except FileNotFoundError as e:
            error_msg = f"rsync command not found. Please install rsync."
            log_error(f"FileNotFoundError during export: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Command Error", error_msg))
        finally:
            self.root.after(0, self.reset_ui)
    
    def _export_image_rsync(self, source_file, dest_dir):
        """Export image using rsync with progress tracking"""
        self.update_progress(1, "Starting rsync export...")
        
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
                            
                            status = f"Exporting: {percent}% | Speed: {speed} | Time remaining: {time_left}"
                            
                            if percent != last_progress_percent:
                                last_progress_percent = percent
                                self.update_progress(percent, status)
                                log_info(f"Progress: {status}")
                    except (ValueError, AttributeError) as e:
                        log_warning(f"Could not parse rsync output: {line}")
                
                # Log other output
                elif line and not line.startswith('sending'):
                    log_info(f"rsync: {line}")
            
            returncode = process.wait()
            
            if returncode == 0:
                self.update_progress(100, "Export completed successfully")
                log_info(f"Export completed successfully")
            else:
                error_msg = f"rsync failed with return code {returncode}"
                log_error(error_msg)
                raise subprocess.CalledProcessError(returncode, 'rsync', error_msg)
        
        except FileNotFoundError:
            error_msg = "rsync command not found. Please install rsync: sudo apt install rsync"
            log_error(error_msg)
            self.update_progress(0, error_msg)
            raise FileNotFoundError(error_msg)
        except subprocess.TimeoutExpired:
            error_msg = "rsync command timed out"
            log_error(error_msg)
            self.update_progress(0, error_msg)
            raise subprocess.TimeoutExpired('rsync', 300, error_msg)
        except OSError as e:
            error_msg = f"System error during export: {e}"
            log_error(error_msg)
            self.update_progress(0, error_msg)
            raise OSError(error_msg)
    
    def setup_ui(self):
        """Setup user interface"""
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
            text="Virtual Image Export",
            font=("Arial", 14, "bold")
        )
        title.pack(anchor="w")
        
        subtitle = ttk.Label(
            header_frame,
            text="Export virtual machine disk images using rsync with progress tracking",
            font=("Arial", 9)
        )
        subtitle.pack(anchor="w")
        
        # Source file selection section
        source_frame = ttk.LabelFrame(main_frame, text="Source Image File", padding="8")
        source_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        source_frame.columnconfigure(0, weight=1)
        
        path_frame = ttk.Frame(source_frame)
        path_frame.grid(row=0, column=0, sticky="ew")
        path_frame.columnconfigure(0, weight=1)
        
        self.source_entry = ttk.Entry(
            path_frame,
            textvariable=self.source_path,
            font=("Arial", 9)
        )
        self.source_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        
        button_frame = ttk.Frame(path_frame)
        button_frame.grid(row=0, column=1)
        
        ttk.Button(
            button_frame,
            text="Browse",
            command=self.browse_source_file,
            width=10
        ).pack(side="left", padx=(0, 3))
        
        ttk.Button(
            button_frame,
            text="Analyze",
            command=self.analyze_source,
            width=10
        ).pack(side="left")
        
        # Source information display
        source_info_frame = ttk.LabelFrame(main_frame, text="Source Info", padding="8")
        source_info_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        source_info_frame.columnconfigure(0, weight=1)
        
        self.source_info_text = tk.Text(
            source_info_frame,
            height=3,
            state="disabled",
            wrap="word",
            font=("Consolas", 8),
            bg="white"
        )
        self.source_info_text.pack(fill="both", expand=True)
        
        # Destination directory selection section
        dest_frame = ttk.LabelFrame(main_frame, text="Destination Directory", padding="8")
        dest_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        dest_frame.columnconfigure(0, weight=1)
        
        dest_path_frame = ttk.Frame(dest_frame)
        dest_path_frame.grid(row=0, column=0, sticky="ew")
        dest_path_frame.columnconfigure(0, weight=1)
        
        self.dest_entry = ttk.Entry(
            dest_path_frame,
            textvariable=self.dest_path,
            font=("Arial", 9)
        )
        self.dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        
        dest_button_frame = ttk.Frame(dest_path_frame)
        dest_button_frame.grid(row=0, column=1)
        
        ttk.Button(
            dest_button_frame,
            text="Browse",
            command=self.browse_destination_dir,
            width=10
        ).pack(side="left", padx=(0, 3))
        
        ttk.Button(
            dest_button_frame,
            text="Home",
            command=self.browse_home_dest,
            width=10
        ).pack(side="left", padx=(0, 3))
        
        ttk.Button(
            dest_button_frame,
            text="Analyze",
            command=self.analyze_destination,
            width=10
        ).pack(side="left")
        
        # Destination information display
        dest_info_frame = ttk.LabelFrame(main_frame, text="Destination Info", padding="8")
        dest_info_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        dest_info_frame.columnconfigure(0, weight=1)
        
        self.dest_info_text = tk.Text(
            dest_info_frame,
            height=3,
            state="disabled",
            wrap="word",
            font=("Consolas", 8),
            bg="white"
        )
        self.dest_info_text.pack(fill="both", expand=True)
        
        # System requirements check
        self.prereq_frame = ttk.LabelFrame(main_frame, text="System Status", padding="8")
        self.prereq_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        
        self.prereq_label = ttk.Label(
            self.prereq_frame,
            text="Checking required tools...",
            font=("Arial", 8)
        )
        self.prereq_label.pack()
        
        # Progress section
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
        self.export_btn = ttk.Button(
            button_container,
            text="START EXPORT",
            command=self.start_export,
            state="normal"
        )
        self.export_btn.grid(row=0, column=0, sticky="ew", pady=(0, 6), ipady=5)
        
        # Secondary buttons
        secondary_frame = ttk.Frame(button_container)
        secondary_frame.grid(row=1, column=0, sticky="ew")
        secondary_frame.columnconfigure(1, weight=1)
        
        ttk.Button(
            secondary_frame,
            text="Refresh",
            command=self.analyze_source,
            width=12
        ).grid(row=0, column=0, padx=(0, 6))
        
        ttk.Button(
            secondary_frame,
            text="Clear",
            command=self.clear_fields,
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
            text="Ready - Select source image and destination directory",
            font=("Arial", 8)
        )
        self.status_label.pack()
    
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
        self.progress_label.config(text="Ready to start")
        self.status_label.config(text="Ready - Select source image and destination directory")
        log_info("Export fields cleared")
    
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
        self.status_label.config(text="Export completed - Ready for next operation")
        log_info("UI reset after export operation")
    
    @staticmethod
    def _format_size(bytes_size):
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"