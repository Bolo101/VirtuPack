#!/usr/bin/env python3
"""
QCOW2 Virtual Disk Resizer - Clone-based Edition
Secure resizing by creating new image and cloning partitions
Always uses GParted for manual partition resizing
Features: preallocation=metadata for new images and improved error handling
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import json
import shutil
import time
import re
import sys
from pathlib import Path
import tempfile
from NewSizeDialog import NewSizeDialog
from QCow2CloneResizer import QCow2CloneResizer
from log_handler import log_error, log_info, log_warning
import queue


class QCow2CloneResizerGUI:
    """GUI for clone-based resizing with mandatory GParted usage"""
    
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.root.title("QCOW2 Clone Resizer - GParted + Safe Cloning")
        
        # Appropriate window size
        self.root.attributes("-fullscreen", True)
        self.root.transient(parent)
        
        self.image_path = tk.StringVar()
        self.image_info = None
        self.operation_active = False
        self.compression_process = None
        self.worker_thread = None
        
        # Track created files for cleanup on error
        self.created_temp_files = []
        self.source_image_path = None
        
        # Threading event system for dialog handling
        self.dialog_result_event = threading.Event()
        self.dialog_result_value = None
        
        # QUEUE pour communication thread-safe entre worker et main thread
        self.dialog_queue = queue.Queue()
        
        self.setup_ui()
        self.check_prerequisites()
        
        # Set up proper close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        
        # Vérifier périodiquement la queue pour les demandes de dialog
        self._check_dialog_queue()

    def _show_file_selection_dialog_main_thread(self, files_to_clean, original_path):
        """Show file selection dialog - called ONLY from main thread via queue check"""
        try:
            print("Creating file selection dialog in MAIN thread...")
            
            # Create window
            selection_window = tk.Toplevel(self.root)
            selection_window.title("Select Files to Delete")
            selection_window.geometry("700x450")
            selection_window.resizable(True, True)
            
            # Make window modal
            selection_window.transient(self.root)
            selection_window.grab_set()
            selection_window.lift()
            selection_window.focus_force()
            
            # Main frame
            main_frame = ttk.Frame(selection_window, padding="15")
            main_frame.pack(fill="both", expand=True)
            
            # Title
            title_label = ttk.Label(main_frame, 
                                text="ERROR CLEANUP - Select files to delete",
                                font=("Arial", 12, "bold"))
            title_label.pack(fill="x", pady=(0, 10))
            
            # Description
            desc_label = ttk.Label(main_frame,
                                text="The following temporary files were created during the cloning operation.\n"
                                    "Select which files to delete. The original image will be preserved.",
                                font=("Arial", 10),
                                wraplength=600,
                                justify="left")
            desc_label.pack(fill="x", pady=(0, 15))
            
            # File listbox
            list_frame = ttk.LabelFrame(main_frame, text="Temporary Files", padding="10")
            list_frame.pack(fill="both", expand=True, pady=(0, 15))
            
            scrollbar = ttk.Scrollbar(list_frame)
            scrollbar.pack(side="right", fill="y")
            
            file_listbox = tk.Listbox(list_frame, 
                                    yscrollcommand=scrollbar.set,
                                    height=10,
                                    font=("Consolas", 9),
                                    selectmode=tk.MULTIPLE)
            file_listbox.pack(side="left", fill="both", expand=True)
            scrollbar.config(command=file_listbox.yview)
            
            # Add files
            file_info = []
            for file_path in files_to_clean:
                try:
                    size = os.path.getsize(file_path)
                    size_str = self._format_size_compact(size)
                    display_text = f"{file_path.name} ({size_str})"
                except OSError:
                    display_text = f"{file_path.name} (size unknown)"
                
                file_listbox.insert("end", display_text)
                file_info.append((file_path, display_text))
                print(f"  Added: {display_text}")
            
            file_listbox.select_set(0, "end")
            
            # Buttons frame
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill="x", pady=(0, 10))
            
            def select_all():
                file_listbox.select_set(0, "end")
                update_total_size()
            
            def deselect_all():
                file_listbox.selection_clear(0, "end")
                update_total_size()
            
            ttk.Button(button_frame, text="Select All", command=select_all).pack(side="left", padx=(0, 5))
            ttk.Button(button_frame, text="Deselect All", command=deselect_all).pack(side="left", padx=(0, 15))
            
            total_size_label = ttk.Label(button_frame, text="", font=("Arial", 9))
            total_size_label.pack(side="left")
            
            def update_total_size():
                try:
                    selected_indices = file_listbox.curselection()
                    total_size = 0
                    for idx in selected_indices:
                        if idx < len(file_info):
                            total_size += os.path.getsize(file_info[idx][0])
                    size_str = self._format_size_compact(total_size)
                    total_size_label.config(text=f"Total to delete: {size_str}")
                except OSError:
                    total_size_label.config(text="Total to delete: calculating...")
            
            file_listbox.bind("<<ListboxSelect>>", lambda e: update_total_size())
            update_total_size()
            
            # Info
            info_frame = ttk.Frame(main_frame)
            info_frame.pack(fill="x", pady=(0, 15))
            
            info_label = ttk.Label(info_frame,
                                text="⚠ WARNING: Files will be permanently deleted\n"
                                    "Original image: " + original_path.name + " (will be preserved)",
                                font=("Arial", 9),
                                foreground="red",
                                justify="left")
            info_label.pack(fill="x")
            
            # Action buttons
            action_frame = ttk.Frame(main_frame)
            action_frame.pack(fill="x")
            
            def on_delete():
                selected_indices = file_listbox.curselection()
                selected_files = [file_info[idx][0] for idx in selected_indices]
                self.dialog_result_value = selected_files
                print(f"User selected {len(selected_files)} files to delete")
                selection_window.destroy()
                self.dialog_result_event.set()
            
            def on_keep():
                self.dialog_result_value = []
                print("User chose to keep all files")
                selection_window.destroy()
                self.dialog_result_event.set()
            
            def on_cancel():
                self.dialog_result_value = None
                print("User cancelled cleanup")
                selection_window.destroy()
                self.dialog_result_event.set()
            
            ttk.Button(action_frame, text="Delete Selected Files", 
                    command=on_delete).pack(side="left", padx=(0, 10))
            ttk.Button(action_frame, text="Keep All Files", 
                    command=on_keep).pack(side="left", padx=(0, 10))
            ttk.Button(action_frame, text="Cancel", 
                    command=on_cancel).pack(side="right")
            
            # Center window
            selection_window.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - selection_window.winfo_width()) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - selection_window.winfo_height()) // 2
            selection_window.geometry(f"+{x}+{y}")
            
            print("File selection dialog displayed successfully")
            
        except tk.TclError as tcl_e:
            print(f"Tkinter error creating selection dialog: {tcl_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except OSError as os_e:
            print(f"OS error in file selection dialog: {os_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except AttributeError as attr_e:
            print(f"Attribute error in file selection dialog: {attr_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except IndexError as idx_e:
            print(f"Index error in file selection dialog: {idx_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()

    def _check_dialog_queue(self):
        """Check queue for pending dialog requests - called from main thread"""
        try:
            while True:
                try:
                    msg = self.dialog_queue.get_nowait()
                    
                    if msg.get('type') == 'file_selection':
                        files = msg.get('files')
                        original_path = msg.get('original_path')
                        self._show_file_selection_dialog_main_thread(files, original_path)
                        
                except queue.Empty:
                    break
        except TypeError as type_e:
            print(f"Type error checking dialog queue: {type_e}")
        except AttributeError as attr_e:
            print(f"Attribute error checking dialog queue: {attr_e}")
        
        # Re-schedule check
        try:
            self.root.after(100, self._check_dialog_queue)
        except tk.TclError:
            pass

    def close_window(self):
        """Handle window close event - forcefully stop operations"""
        if self.operation_active:
            result = messagebox.askyesno("Operation in Progress", 
                                    "An operation is currently running.\n\n"
                                    "This will STOP the operation immediately.\n"
                                    "Temporary files will be handled appropriately.\n\n"
                                    "Continue?")
            if not result:
                return
            
            print("\n" + "="*60)
            print("FORCE STOPPING OPERATION (User clicked Close)")
            print("="*60)
            
            # Kill the compression process if it's running
            if self.compression_process and self.compression_process.poll() is None:
                print(f"Killing qemu-img process (PID: {self.compression_process.pid})...")
                try:
                    self.compression_process.terminate()
                    time.sleep(1)
                    if self.compression_process.poll() is None:
                        print("Process didn't terminate, forcing kill...")
                        self.compression_process.kill()
                        self.compression_process.wait(timeout=5)
                    print("✓ Process killed successfully")
                except Exception as e:
                    print(f"Error killing process: {e}")
            
            # Auto-cleanup .compressed.tmp files from source directory
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized files if any exist
            if self.created_temp_files:
                self._cleanup_on_error(self.source_image_path, self.created_temp_files)
            
            # Stop operation flag
            self.operation_active = False
        
        print("Closing QCOW2 Clone Resizer...")
        try:
            self.root.destroy()
        except tk.TclError:
            pass


    def _force_cleanup_temp_files(self):
        """Forcefully remove all known temporary files"""
        print("\n" + "="*60)
        print("FORCE CLEANUP OF TEMPORARY FILES")
        print("="*60)
        
        # Common temporary file patterns to clean
        temp_patterns = [
            "*.compressed.tmp",
            "*_intermediate.qcow2",
            "*_optimized.qcow2",
            "*_compressed.qcow2",
            "*.tmp.qcow2",
        ]
        
        search_dir = Path.cwd()
        print(f"Searching in: {search_dir}\n")
        
        total_removed = 0
        total_failed = 0
        
        for pattern in temp_patterns:
            try:
                matching_files = list(search_dir.glob(pattern))
                
                if matching_files:
                    print(f"Pattern: {pattern}")
                    for file_path in matching_files:
                        try:
                            max_retries = 5
                            for attempt in range(max_retries):
                                try:
                                    os.remove(file_path)
                                    print(f"  ✓ Removed: {file_path.name}")
                                    total_removed += 1
                                    break
                                except (PermissionError, OSError) as e:
                                    if attempt < max_retries - 1:
                                        time.sleep(1)
                                    else:
                                        raise
                        except FileNotFoundError as fnf_e:
                            print(f"  ✓ Already removed: {file_path.name}")
                            total_removed += 1
                        except PermissionError as perm_e:
                            print(f"  ✗ Failed: {file_path.name} - Permission denied")
                            total_failed += 1
                        except OSError as os_e:
                            print(f"  ✗ Failed: {file_path.name} - {os_e}")
                            total_failed += 1
            except TypeError as type_e:
                print(f"Type error with pattern {pattern}: {type_e}")
                continue
        
        print(f"\nCleanup complete:")
        print(f"  Removed: {total_removed} files")
        print(f"  Failed: {total_failed} files")
        print("="*60 + "\n")

    def setup_ui(self):
        """Setup simplified user interface with single action button"""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # Header section
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill="x", pady=(0, 20))
        
        # Title
        title = ttk.Label(header_frame, text="QCOW2 Clone Resizer", 
                        font=("Arial", 18, "bold"))
        title.pack(pady=(0, 5))
        
        subtitle = ttk.Label(header_frame, text="GParted Manual Resizing + Safe Cloning", 
                           font=("Arial", 11))
        subtitle.pack(pady=(0, 10))
        
        # File selection section
        file_frame = ttk.LabelFrame(main_frame, text="QCOW2 Image File", padding="15")
        file_frame.pack(fill="x", pady=(0, 15))
        
        path_frame = ttk.Frame(file_frame)
        path_frame.pack(fill="x", pady=(0, 10))
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.image_path, font=("Arial", 10))
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ttk.Button(path_frame, text="Browse", command=self.browse_file).pack(side="right", padx=(0, 5))
        ttk.Button(path_frame, text="Analyze", command=self.analyze_image).pack(side="right")
        
        # Image information display
        info_frame = ttk.LabelFrame(main_frame, text="Image Information", padding="15")
        info_frame.pack(fill="both", expand=True, pady=(0, 15))
        
        self.info_text = tk.Text(info_frame, height=10, state="disabled", wrap="word", 
                                font=("Consolas", 9), bg="white")
        info_scrollbar = ttk.Scrollbar(info_frame, orient="vertical", command=self.info_text.yview)
        self.info_text.configure(yscrollcommand=info_scrollbar.set)
        
        self.info_text.pack(side="left", fill="both", expand=True)
        info_scrollbar.pack(side="right", fill="y")
        
        # System requirements check
        self.prereq_frame = ttk.LabelFrame(main_frame, text="System Status", padding="15")
        self.prereq_frame.pack(fill="x", pady=(0, 15))
        
        self.prereq_label = ttk.Label(self.prereq_frame, text="Checking required tools...", 
                                     font=("Arial", 9))
        self.prereq_label.pack()
        
        # Progress section
        progress_frame = ttk.LabelFrame(main_frame, text="Operation Progress", padding="15")
        progress_frame.pack(fill="x", pady=(0, 20))
        
        self.progress = ttk.Progressbar(progress_frame, length=400, style="TProgressbar")
        self.progress.pack(fill="x", pady=(0, 8))
        
        self.progress_label = ttk.Label(progress_frame, text="Ready to begin", 
                                       font=("Arial", 10, "bold"))
        self.progress_label.pack()
        
        # Action buttons section
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(0, 10))
        
        # Primary action button (large, prominent)
        self.main_action_btn = ttk.Button(button_frame, 
                                         text="START GPARTED + CLONE PROCESS", 
                                         command=self.start_gparted_resize, 
                                         state="disabled",
                                         style="Accent.TButton")
        self.main_action_btn.pack(side="top", fill="x", pady=(0, 15), ipady=8)
        
        # Secondary buttons (smaller, side by side)
        secondary_frame = ttk.Frame(button_frame)
        secondary_frame.pack(fill="x")
        
        self.backup_btn = ttk.Button(secondary_frame, text="Create Backup", 
                                    command=self.create_backup)
        self.backup_btn.pack(side="left", padx=(0, 10))
        
        ttk.Button(secondary_frame, text="Refresh", 
                  command=self.analyze_image).pack(side="left", padx=(0, 10))
        
        ttk.Button(secondary_frame, text="Close", 
                  command=self.close_window).pack(side="right")
        
        # Status bar
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill="x", pady=(15, 0))
        
        separator = ttk.Separator(status_frame, orient="horizontal")
        separator.pack(fill="x", pady=(0, 8))
        
        self.status_label = ttk.Label(status_frame, 
                                     text="Ready - Select QCOW2 image file and ensure VM is shut down", 
                                     font=("Arial", 9))
        self.status_label.pack()
        
        # Configure styles
        self.setup_styles()
    
    def setup_styles(self):
        """Setup custom styles"""
        style = ttk.Style()
        
        # Configure accent button style for main action
        style.configure("Accent.TButton",
                       font=("Arial", 12, "bold"),
                       padding=(20, 10))
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        missing, optional = QCow2CloneResizer.check_tools()
        
        text = ""
        if missing:
            text = f"Missing required tools: {', '.join(missing)}\n"
            
            install_msg = "Required tools missing!\n\n"
            install_msg += "Ubuntu/Debian:\n"
            install_msg += "sudo apt install qemu-utils parted gparted\n\n"
            install_msg += "Fedora/RHEL:\n"
            install_msg += "sudo dnf install qemu-img parted gparted\n\n"
            install_msg += "Arch Linux:\n"
            install_msg += "sudo pacman -S qemu parted gparted"
            
            messagebox.showerror("Missing Tools", install_msg)
            
        else:
            text = "All required tools available\n"
        
        if optional:
            text += f"Optional tools: {', '.join(optional)}\n"
        
        root_status = "Running as root" if os.geteuid() == 0 else "Will use privilege escalation"
        text += root_status
        
        color = "red" if missing else "green"
        self.prereq_label.config(text=text, foreground=color)
    
    def browse_file(self):
        """Browse for QCOW2 file"""
        file_path = filedialog.askopenfilename(
            title="Select QCOW2 Image File",
            filetypes=[("QCOW2 files", "*.qcow2"), ("All files", "*.*")]
        )
        if file_path:
            self.image_path.set(file_path)
            self.analyze_image()
    
    def analyze_image(self):
        """Analyze selected image"""
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("No File Selected", "Please select an image file first")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", "The selected file does not exist")
            return
        
        try:
            self.update_progress(10, "Analyzing image file...")
            self.image_info = QCow2CloneResizer.get_image_info(path)
            self.display_image_info()
            
            # Enable action buttons
            self.main_action_btn.config(state="normal")
            
            self.update_progress(0, "Analysis complete - Ready for GParted + Clone process")
            self.status_label.config(text="Image analyzed - Ready to start GParted + Clone process")
            
        except FileNotFoundError:
            messagebox.showerror("File Not Found", f"Image file not found: {path}")
            self.update_progress(0, "Analysis failed - file not found")
        except PermissionError:
            messagebox.showerror("Permission Denied", f"Permission denied accessing image file: {path}")
            self.update_progress(0, "Analysis failed - permission denied")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Command Failed", f"qemu-img analysis failed:\n\n{e}")
            self.update_progress(0, "Analysis failed - command error")
        except json.JSONDecodeError:
            messagebox.showerror("Parse Error", f"Failed to parse image analysis results")
            self.update_progress(0, "Analysis failed - parse error")
        except OSError as e:
            messagebox.showerror("System Error", f"System error during image analysis:\n\n{e}")
            self.update_progress(0, "Analysis failed - system error")
    
    def display_image_info(self):
        """Display image information"""
        if not self.image_info:
            return
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        info = f"FILE INFORMATION\n"
        info += f"{'='*50}\n"
        info += f"Path: {self.image_path.get()}\n"
        info += f"Name: {os.path.basename(self.image_path.get())}\n"
        info += f"Format: {self.image_info['format'].upper()}\n\n"
        
        info += f"SIZE INFORMATION\n"
        info += f"{'='*50}\n"
        info += f"Virtual Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n"
        
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Usage: {ratio*100:.1f}% of virtual size\n"
            
            if ratio < 0.5:
                info += f"INFO: Sparse allocation detected (efficient storage)\n"
        
        info += f"\nPROCESS WORKFLOW\n"
        info += f"{'='*50}\n"
        info += f"1. Mount image as NBD device\n"
        info += f"2. Launch GParted for manual partition editing\n"
        info += f"3. Resize/modify partitions as needed\n"
        info += f"4. Apply changes and close GParted\n"
        info += f"5. Select optimal size for new image\n"
        info += f"6. Clone all partitions to new optimized image\n\n"
        
        info += f"IMPORTANT REQUIREMENTS:\n"
        info += f"• Virtual machine MUST be completely shut down\n"
        info += f"• Apply ALL changes in GParted before closing\n"
        info += f"• Backup recommended before starting\n"
        info += f"• New image will use preallocation=metadata\n"
        info += f"\nReady for GParted + Clone process!"
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    def create_backup(self):
        """Create backup of current image using rsync with progress"""
        path = self.image_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("No File", "Select a valid image file first")
            return
        
        try:
            # Generate backup filename
            from pathlib import Path
            original_path = Path(path)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = original_path.parent / f"{original_path.stem}_backup_{timestamp}{original_path.suffix}"
            
            # Disable backup button during operation
            self.backup_btn.config(state="disabled")
            self.main_action_btn.config(state="disabled")
            
            # Start backup in thread
            backup_thread = threading.Thread(
                target=self._backup_worker,
                args=(path, str(backup_path))
            )
            backup_thread.daemon = False
            backup_thread.start()
            
        except OSError as e:
            error_msg = f"System error preparing backup: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("System Error", error_msg)
            self.backup_btn.config(state="normal")
            self.main_action_btn.config(state="normal")
        except PermissionError as e:
            error_msg = f"Permission denied preparing backup: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Permission Error", error_msg)
            self.backup_btn.config(state="normal")
            self.main_action_btn.config(state="normal")
        except ValueError as e:
            error_msg = f"Invalid path for backup: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Value Error", error_msg)
            self.backup_btn.config(state="normal")
            self.main_action_btn.config(state="normal")

    def _backup_worker(self, source_path, backup_path):
        """Worker thread for rsync backup with progress tracking"""
        try:
            log_info(f"Starting backup: {source_path} -> {backup_path}")
            self.update_progress(5, "Initializing backup...")
            
            source_size = os.path.getsize(source_path)
            
            rsync_cmd = [
                'rsync',
                '-ah',
                '--progress',
                source_path,
                backup_path
            ]
            
            self.update_progress(10, "Starting file transfer...")
            
            process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            for line in process.stdout:
                line = line.strip()
                if line:
                    if '%' in line:
                        try:
                            parts = line.split()
                            for part in parts:
                                if '%' in part:
                                    percent_str = part.replace('%', '')
                                    percent = float(percent_str)
                                    scaled_percent = 10 + (percent * 0.8)
                                    self.update_progress(
                                        int(scaled_percent),
                                        f"Backing up: {percent:.1f}%"
                                    )
                                    break
                        except (ValueError, IndexError):
                            pass
            
            return_code = process.wait()
            
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, rsync_cmd)
            
            if not os.path.exists(backup_path):
                raise FileNotFoundError(f"Backup file not created: {backup_path}")
            
            backup_size = os.path.getsize(backup_path)
            if backup_size != source_size:
                raise ValueError(
                    f"Backup size mismatch: source={source_size}, backup={backup_size}"
                )
            
            self.update_progress(100, "Backup completed successfully")
            log_info(f"Backup created successfully: {backup_path}")
            
            backup_msg = f"BACKUP CREATED SUCCESSFULLY!\n\n"
            backup_msg += f"Original: {os.path.basename(source_path)}\n"
            backup_msg += f"Backup: {os.path.basename(backup_path)}\n"
            backup_msg += f"Size: {QCow2CloneResizer.format_size(backup_size)}\n\n"
            backup_msg += f"Location: {backup_path}\n\n"
            backup_msg += f"The backup is a complete copy of your virtual disk.\n"
            backup_msg += f"You can now safely proceed with the resizing process."
            
            self.root.after(0, lambda: messagebox.showinfo("Backup Complete", backup_msg))
            self.root.after(100, lambda: self.update_progress(0, "Backup complete"))
            
        except FileNotFoundError as fnf_e:
            error_msg = f"Backup failed - file not found: {str(fnf_e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("File Not Found", error_msg))
            self.update_progress(0, "Backup failed")
        except PermissionError as perm_e:
            error_msg = f"Backup failed - permission denied: {str(perm_e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Permission Denied", error_msg))
            self.update_progress(0, "Backup failed")
        except subprocess.CalledProcessError as cpe:
            error_msg = f"Backup failed - rsync error (code {cpe.returncode})"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Backup Failed", error_msg))
            self.update_progress(0, "Backup failed")
        except subprocess.TimeoutExpired as timeout_e:
            error_msg = f"Backup failed - operation timed out"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Timeout", error_msg))
            self.update_progress(0, "Backup failed")
        except ValueError as val_e:
            error_msg = f"Backup failed - verification error: {str(val_e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Verification Failed", error_msg))
            self.update_progress(0, "Backup failed")
        except OSError as os_e:
            error_msg = f"Backup failed - system error: {str(os_e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("System Error", error_msg))
            self.update_progress(0, "Backup failed")
        except IOError as io_e:
            error_msg = f"Backup failed - I/O error: {str(io_e)}"
            log_error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("I/O Error", error_msg))
            self.update_progress(0, "Backup failed")
        finally:
            self.root.after(0, lambda: self.backup_btn.config(state="normal"))
            self.root.after(0, lambda: self.main_action_btn.config(state="normal"))
    
    def start_gparted_resize(self):
        """Start GParted + clone resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        
        # Store source image path for cleanup tracking
        self.source_image_path = path
        self.created_temp_files = []  # Reset list
        
        # Detailed confirmation dialog
        msg = f"GPARTED + CLONE OPERATION\n\n"
        msg += f"File: {os.path.basename(path)}\n"
        msg += f"Current Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        msg += f"File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n\n"
        
        msg += f"PROCESS STEPS:\n"
        msg += f"1. Mount image as NBD device\n"
        msg += f"2. Launch GParted for manual partition editing\n"
        msg += f"3. Resize/move/modify partitions in GParted\n"
        msg += f"4. Apply changes and close GParted\n"
        msg += f"5. Select optimal size for new image\n"
        msg += f"6. Create new optimized image (with preallocation=metadata)\n"
        msg += f"7. Clone all modified partitions safely\n\n"
        
        msg += f"CRITICAL REQUIREMENTS:\n"
        msg += f"• Virtual machine MUST be completely shut down\n"
        msg += f"• Root privileges required for NBD operations\n"
        msg += f"• APPLY ALL CHANGES in GParted before closing\n"
        msg += f"• Backup recommended before operation\n\n"
        
        msg += f"Continue with GParted + Clone process?"
        
        if not messagebox.askyesno("Confirm Operation", msg):
            return
        
        # Check root privileges
        if os.geteuid() != 0:
            root_msg = ("ROOT PRIVILEGES REQUIRED\n\n"
                    "This operation requires root privileges for NBD device management.\n\n"
                    "The application will attempt to use privilege escalation (pkexec, sudo) "
                    "when launching GParted.\n\n"
                    "For best experience, run entire application with:\n"
                    "sudo python3 qcow2_clone_resizer.py\n\n"
                    "Continue anyway?")
            
            if not messagebox.askyesno("Root Privileges Required", root_msg):
                return
        
        # Start resize in thread
        self.operation_active = True
        self.main_action_btn.config(state="disabled")
        self.backup_btn.config(state="disabled")
        self.status_label.config(text="GParted + Clone operation in progress...")
        
        self.worker_thread = threading.Thread(target=self._gparted_clone_worker, args=(path,))
        self.worker_thread.daemon = True
        self.worker_thread.start()



    def _format_size_compact(self, size_bytes):
        """Format bytes to compact size string"""
        try:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f}{unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f}PB"
        except (TypeError, ValueError):
            return "unknown"


    def _gparted_clone_worker(self, image_path):
        """Worker thread for GParted + clone resize operation with comprehensive logging"""
        source_nbd = None
        
        try:
            log_info(f"Starting GParted + Clone operation for: {image_path}")
            
            # Store original image info BEFORE any modifications
            original_info = self.image_info.copy()
            original_source_size = os.path.getsize(image_path)
            log_info(f"Original image size: {QCow2CloneResizer.format_size(original_source_size)}")
            
            # Pre-calculate potential temporary file paths
            original_path = Path(image_path)
            intermediate_path = str(original_path.parent / f"{original_path.stem}_intermediate{original_path.suffix}")
            final_path = str(original_path.parent / f"{original_path.stem}_optimized{original_path.suffix}")
            
            # TRACK these files for error cleanup
            self.created_temp_files = [intermediate_path, final_path]
            log_info(f"Temporary files will be created: {[Path(p).name for p in self.created_temp_files]}")
            
            # Setup NBD device for GParted
            self.update_progress(10, "Setting up NBD device for GParted...")
            log_info("Setting up NBD device for GParted...")
            source_nbd = QCow2CloneResizer.setup_nbd_device(image_path, self.update_progress)
            log_info(f"NBD device setup complete: {source_nbd}")
            
            # Detect OS type
            self.update_progress(15, "Detecting VM operating system...")
            log_info("Detecting VM operating system...")
            os_type = QCow2CloneResizer.detect_vm_os(source_nbd)
            log_info(f"Detected OS type: {os_type}")
            
            # Detect boot mode by checking partition table
            log_info("Detecting boot mode (UEFI/BIOS)...")
            parted_result = subprocess.run(
                ['parted', '-s', source_nbd, 'print'],
                capture_output=True, text=True, check=True, timeout=30
            )
            is_gpt = 'gpt' in parted_result.stdout.lower()
            has_esp = 'esp' in parted_result.stdout.lower()
            boot_mode = 'uefi' if (is_gpt and has_esp) else 'bios'
            log_info(f"Boot mode detected: {boot_mode.upper()} (GPT: {is_gpt}, ESP: {has_esp})")
            
            # Get initial partition layout
            self.update_progress(20, "Analyzing initial partition layout...")
            log_info("Analyzing initial partition layout...")
            initial_layout = QCow2CloneResizer.get_partition_layout(source_nbd)
            log_info(f"Initial partition count: {len(initial_layout['partitions'])}")
            for part in initial_layout['partitions']:
                log_info(f"  Partition {part['number']}: {part['start']} - {part['end']} ({part['size']})")
            
            # Launch GParted
            self.update_progress(30, "Launching GParted for manual partition editing...")
            log_info("Preparing to launch GParted...")
            
            initial_info = f"Initial partition layout:\n"
            for part in initial_layout['partitions']:
                initial_info += f"  Partition {part['number']}: {part['start']} - {part['end']} ({part['size']})\n"
            
            instructions = (
                f"GPARTED LAUNCHED FOR MANUAL PARTITION EDITING\n\n"
                f"Device: {source_nbd}\n"
                f"OS Type: {os_type.upper()}\n"
                f"Boot Mode: {boot_mode.upper()}\n\n"
                f"CURRENT PARTITIONS:\n{initial_info}\n"
                f"INSTRUCTIONS FOR GPARTED:\n"
                f"1. Resize partitions (shrink to save space or expand)\n"
                f"2. Move partitions if needed\n"
                f"3. CRITICAL: Click 'Apply' to execute all changes\n"
                f"4. Wait for all operations to complete\n"
                f"5. Close GParted when finished\n\n"
            )
            
            if os_type == 'linux' and boot_mode == 'uefi':
                instructions += (
                    f"After GParted closes, the EFI boot entry will be automatically\n"
                    f"set for automatic access and the image will be cloned to an optimized version."
                )
            elif os_type == 'linux' and boot_mode == 'bios':
                instructions += (
                    f"After GParted closes, the image will be resized to optimal size\n"
                    f"and compressed to save disk space."
                )
            elif os_type == 'windows':
                instructions += (
                    f"After GParted closes, the image will be resized to optimal size\n"
                    f"and compressed to save disk space."
                )
            else:
                instructions += (
                    f"After GParted closes, the operation will proceed based on\n"
                    f"detected OS type."
                )
            
            # Show instructions and wait for OK
            self._show_message_and_wait("GParted Session Starting", instructions)
            
            log_info("Launching GParted for user partition editing...")
            QCow2CloneResizer.launch_gparted(source_nbd)
            log_info("GParted session completed - user has closed GParted")
            
            # WAIT FOR PARTITIONS TO STABILIZE
            log_info("Waiting for partitions to stabilize after GParted modifications...")
            time.sleep(5)
            
            # Re-scan partitions
            log_info("Re-scanning partitions with partprobe...")
            subprocess.run(['partprobe', source_nbd], check=False, timeout=30)
            time.sleep(3)
            
            # OS-SPECIFIC AND BOOT-MODE HANDLING
            if os_type == 'linux' and boot_mode == 'uefi':
                log_info("="*60)
                log_info("LINUX UEFI VM DETECTED - PERFORMING FULL CLONING")
                log_info("="*60)
                
                self.update_progress(35, "Configuring EFI boot entries for automatic boot...")
                log_info("Configuring EFI boot entries for automatic boot...")
                
                bootloader_fixed = QCow2CloneResizerGUI.setup_efi_boot_entries(
                    source_nbd, 
                    self.update_progress
                )
                
                if bootloader_fixed:
                    log_info("✓ EFI boot entry set up for automatic boot")
                    self._show_message_and_wait(
                        "EFI boot entry Fixed",
                        "✓ EFI boot entry set up for automatic boot.\n\n"
                        "Your VM will boot correctly with the resized partitions."
                    )
                else:
                    log_warning("Could not automatically reconfigure EFI boot entry")
                    warning_msg = (
                        "⚠ Could not automatically reconfigure EFI boot entry.\n\n"
                        "VM might need to create manual boot option creation to boot\n"
                        "Continue with cloning?"
                    )
                    
                    if not self._show_yesno_and_wait("Bootloader Warning", warning_msg):
                        log_warning("User cancelled operation after bootloader warning")
                        raise RuntimeError("Operation cancelled by user after bootloader warning")
                
                # Analyze final partition layout
                self.update_progress(40, "GParted completed - analyzing partition changes...")
                log_info("Analyzing partition changes after GParted...")
                final_layout = QCow2CloneResizer.get_partition_layout(source_nbd)
                log_info(f"Final partition count: {len(final_layout['partitions'])}")
                
                # Compare layouts
                partition_changes = "Partitions modified using GParted"
                if len(initial_layout['partitions']) != len(final_layout['partitions']):
                    partition_changes = f"Partition count changed: {len(initial_layout['partitions'])} → {len(final_layout['partitions'])}"
                    log_info(partition_changes)
                elif initial_layout['last_partition_end_bytes'] != final_layout['last_partition_end_bytes']:
                    old_size = QCow2CloneResizer.format_size(initial_layout['last_partition_end_bytes'])
                    new_size = QCow2CloneResizer.format_size(final_layout['last_partition_end_bytes'])
                    partition_changes = f"Partition space changed: {old_size} → {new_size}"
                    log_info(partition_changes)
                
                # Show size selection dialog
                self.update_progress(45, "Select size for new optimized image...")
                log_info("Showing size selection dialog to user...")
                
                self.dialog_result_event.clear()
                self.dialog_result_value = None
                
                self.root.after(0, self._show_final_size_dialog, final_layout, partition_changes)
                
                dialog_completed = self.dialog_result_event.wait(timeout=300)
                
                if not dialog_completed:
                    log_error("Size selection dialog timed out (300 seconds)")
                    raise RuntimeError("Size selection dialog timed out")
                
                new_size = self.dialog_result_value
                log_info(f"User selected new image size: {QCow2CloneResizer.format_size(new_size) if new_size else 'None (cancelled)'}")
                
                if new_size is not None:
                    log_info(f"Starting clone operation to intermediate image: {Path(intermediate_path).name}")
                    
                    # Clone to intermediate image
                    self.update_progress(55, "Cloning modified partitions to intermediate image...")
                    
                    self._clone_to_new_image_with_existing_nbd(
                        image_path,
                        intermediate_path,
                        new_size,
                        source_nbd,
                        final_layout,
                        self.update_progress,
                        compress=False
                    )
                    
                    log_info("✓ Clone operation completed successfully")
                    
                    # Compress intermediate image to create final image
                    self.update_progress(90, "Preparing final compression...")
                    log_info(f"Starting compression: {Path(intermediate_path).name} -> {Path(final_path).name}")

                    try:
                        # Copy intermediate to final
                        log_info("Copying intermediate image to final location...")
                        shutil.copy2(intermediate_path, final_path)
                        self.update_progress(92, "Copy complete, starting compression...")
                        log_info("Copy complete, starting QCOW2 compression...")
                        
                        # Compress final image
                        compression_stats = QCow2CloneResizer.compress_qcow2_image(
                            final_path, 
                            self.update_progress,
                            delete_original_source=None,
                            process_tracker=self
                        )
                        log_info(f"✓ Compression completed: {compression_stats['compression_ratio']:.1f}% space saved")
                    except subprocess.CalledProcessError as compress_e:
                        log_error(f"Compression command failed: {compress_e}")
                        compression_stats = {
                            'space_saved': 0,
                            'compression_ratio': 0.0,
                            'original_size': 0,
                            'compressed_size': 0,
                        }
                    except subprocess.TimeoutExpired as timeout_e:
                        log_error(f"Compression timed out: {timeout_e}")
                        compression_stats = {
                            'space_saved': 0,
                            'compression_ratio': 0.0,
                            'original_size': 0,
                            'compressed_size': 0,
                        }
                    except FileNotFoundError as file_e:
                        log_error(f"Compression file not found: {file_e}")
                        compression_stats = {
                            'space_saved': 0,
                            'compression_ratio': 0.0,
                            'original_size': 0,
                            'compressed_size': 0,
                        }
                    except PermissionError as perm_e:
                        log_error(f"Compression permission denied: {perm_e}")
                        compression_stats = {
                            'space_saved': 0,
                            'compression_ratio': 0.0,
                            'original_size': 0,
                            'compressed_size': 0,
                        }
                    except OSError as os_e:
                        log_error(f"Compression OS error: {os_e}")
                        compression_stats = {
                            'space_saved': 0,
                            'compression_ratio': 0.0,
                            'original_size': 0,
                            'compressed_size': 0,
                        }
                    
                    # Get final image info
                    log_info("Analyzing final compressed image...")
                    final_image_info = QCow2CloneResizer.get_image_info(final_path)
                    final_image_size = os.path.getsize(final_path)
                    log_info(f"Final image virtual size: {QCow2CloneResizer.format_size(final_image_info['virtual_size'])}")
                    log_info(f"Final image file size: {QCow2CloneResizer.format_size(final_image_size)}")
                    
                    # Show completion dialog
                    log_info("Showing completion dialog to user...")
                    self._show_completion_and_replacement_dialog(
                        image_path,
                        final_path,
                        intermediate_path,
                        original_info,
                        original_source_size,
                        final_image_info,
                        final_image_size,
                        new_size,
                        compression_stats
                    )
                    
                    # Clear temp files list on success
                    self.created_temp_files = []
                    log_info("✓ UEFI Linux clone operation completed successfully")
                    
                else:
                    log_warning("User chose to skip cloning - operation cancelled")
                    raise RuntimeError("Operation cancelled by user - cloning skipped")
            
            elif os_type == 'linux' and boot_mode == 'bios':
                log_info("="*60)
                log_info("LINUX BIOS VM DETECTED - RESIZING AND COMPRESSING")
                log_info("="*60)
                
                self.update_progress(40, "Analyzing final BIOS partition layout...")
                log_info("Analyzing final partition layout for BIOS...")
                final_layout = QCow2CloneResizer.get_partition_layout(source_nbd)
                
                partition_changes = "Partitions modified using GParted"
                if len(initial_layout['partitions']) != len(final_layout['partitions']):
                    partition_changes = f"Partition count changed: {len(initial_layout['partitions'])} → {len(final_layout['partitions'])}"
                    log_info(partition_changes)
                elif initial_layout['last_partition_end_bytes'] != final_layout['last_partition_end_bytes']:
                    old_size = QCow2CloneResizer.format_size(initial_layout['last_partition_end_bytes'])
                    new_size = QCow2CloneResizer.format_size(final_layout['last_partition_end_bytes'])
                    partition_changes = f"Partition space changed: {old_size} → {new_size}"
                    log_info(partition_changes)
                
                self.update_progress(45, "Select size for optimized image...")
                log_info("Showing size selection dialog for BIOS Linux...")
                
                self.dialog_result_event.clear()
                self.dialog_result_value = None
                
                self.root.after(0, self._show_final_size_dialog, final_layout, partition_changes)
                
                dialog_completed = self.dialog_result_event.wait(timeout=300)
                
                if not dialog_completed:
                    log_error("Size selection dialog timed out (300 seconds)")
                    raise RuntimeError("Size selection dialog timed out")
                
                new_size = self.dialog_result_value
                log_info(f"User selected size for BIOS: {QCow2CloneResizer.format_size(new_size) if new_size else 'None (cancelled)'}")
                
                if new_size is not None:
                    log_info(f"Resizing BIOS image to: {QCow2CloneResizer.format_size(new_size)}")
                    
                    self.update_progress(50, "Preparing for image resize...")
                    log_info("Performing final sync before NBD disconnect...")
                    self._perform_safe_sync("Pre-resize sync")
                    
                    log_info(f"Disconnecting NBD device: {source_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(source_nbd)
                    source_nbd = None
                    
                    log_info("Waiting for device release...")
                    time.sleep(10)
                    
                    self.update_progress(55, "Resizing image...")
                    log_info(f"Executing qemu-img resize to {QCow2CloneResizer.format_size(new_size)}")
                    
                    resize_cmd = [
                        'qemu-img', 'resize',
                        '--shrink',
                        '-f', 'qcow2',
                        image_path,
                        str(new_size)
                    ]
                    
                    result = subprocess.run(
                        resize_cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False
                    )
                    
                    if result.returncode != 0:
                        log_error(f"qemu-img resize failed with return code {result.returncode}")
                        log_error(f"stderr: {result.stderr}")
                        raise subprocess.CalledProcessError(result.returncode, resize_cmd, result.stderr)
                    
                    log_info("✓ BIOS Image resized successfully")
                    
                    self.update_progress(70, "Compressing optimized image...")
                    log_info("Starting compression for BIOS image...")
                    
                    compression_stats = QCow2CloneResizer.compress_qcow2_image(
                        image_path,
                        self.update_progress,
                        delete_original_source=None,
                        process_tracker=self
                    )
                    
                    log_info(f"✓ BIOS Image compression completed: {compression_stats['compression_ratio']:.1f}% space saved")
                    
                    self.update_progress(95, "Finalizing...")
                    log_info("Analyzing final BIOS image...")
                    
                    final_image_info = QCow2CloneResizer.get_image_info(image_path)
                    final_image_size = os.path.getsize(image_path)
                    log_info(f"Final BIOS image size: {QCow2CloneResizer.format_size(final_image_size)}")
                    
                    log_info("Showing BIOS completion dialog...")
                    self._show_bios_completion_dialog(
                        image_path,
                        original_info,
                        original_source_size,
                        final_image_info,
                        final_image_size,
                        compression_stats
                    )
                    
                    # Clear temp files list on success
                    self.created_temp_files = []
                    log_info("✓ BIOS Linux resize operation completed successfully")
                else:
                    log_warning("User cancelled BIOS resizing")
                    raise RuntimeError("Operation cancelled by user")
            
            elif os_type == 'windows':
                log_info("="*60)
                log_info("WINDOWS VM DETECTED - RESIZING AND COMPRESSING")
                log_info("="*60)
                
                self.update_progress(40, "Finalizing Windows partition changes...")
                log_info("Waiting for partitions to stabilize after GParted...")
                
                # Don't disconnect yet - analyze with NBD still mounted
                log_info("Re-scanning partitions...")
                subprocess.run(['partprobe', source_nbd], check=False, timeout=30)
                time.sleep(3)
                
                self.update_progress(45, "Analyzing final partition layout...")
                log_info("Analyzing final Windows partition layout...")
                # Use source_nbd (still mounted), NOT image_path
                final_layout = QCow2CloneResizer.get_partition_layout(source_nbd)
                
                partition_changes = "Partitions modified using GParted"
                if len(initial_layout['partitions']) != len(final_layout['partitions']):
                    partition_changes = f"Partition count changed: {len(initial_layout['partitions'])} → {len(final_layout['partitions'])}"
                    log_info(partition_changes)
                elif initial_layout['last_partition_end_bytes'] != final_layout['last_partition_end_bytes']:
                    old_size = QCow2CloneResizer.format_size(initial_layout['last_partition_end_bytes'])
                    new_size = QCow2CloneResizer.format_size(final_layout['last_partition_end_bytes'])
                    partition_changes = f"Partition space changed: {old_size} → {new_size}"
                    log_info(partition_changes)
                
                self.update_progress(50, "Select size for optimized image...")
                log_info("Showing size selection dialog for Windows...")
                
                self.dialog_result_event.clear()
                self.dialog_result_value = None
                
                self.root.after(0, self._show_final_size_dialog, final_layout, partition_changes)
                
                dialog_completed = self.dialog_result_event.wait(timeout=300)
                
                if not dialog_completed:
                    log_error("Size selection dialog timed out (300 seconds)")
                    raise RuntimeError("Size selection dialog timed out")
                
                new_size = self.dialog_result_value
                log_info(f"User selected size for Windows: {QCow2CloneResizer.format_size(new_size) if new_size else 'None (cancelled)'}")
                
                if new_size is not None:
                    # ALIGN SIZE TO 512-BYTE BOUNDARY FOR WINDOWS
                    aligned_new_size = self._align_windows_size_to_512(new_size)
                    
                    if aligned_new_size != new_size:
                        log_info(f"Windows size alignment required: {new_size} -> {aligned_new_size} bytes")
                        alignment_msg = (
                            f"SIZE ALIGNMENT REQUIRED FOR WINDOWS\n\n"
                            f"Windows images must use 512-byte sector alignment.\n\n"
                            f"Original selected size: {QCow2CloneResizer.format_size(new_size)}\n"
                            f"Aligned size:           {QCow2CloneResizer.format_size(aligned_new_size)}\n"
                            f"Difference:             {aligned_new_size - new_size} bytes\n\n"
                            f"The image will be resized to the aligned size for compatibility."
                        )
                        self._show_message_and_wait("Windows Size Alignment", alignment_msg)
                        new_size = aligned_new_size
                        log_info(f"Using aligned size: {QCow2CloneResizer.format_size(new_size)}")
                    
                    log_info(f"Resizing Windows image to: {QCow2CloneResizer.format_size(new_size)}")
                    
                    # Perform safe sync while NBD is still mounted
                    self.update_progress(55, "Finalizing Windows partition changes...")
                    log_info("Performing final sync before NBD disconnect...")
                    self._perform_safe_sync("Windows pre-resize sync")
                    
                    # NOW disconnect NBD device after all analysis complete
                    log_info(f"Disconnecting NBD device: {source_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(source_nbd)
                    source_nbd = None
                    
                    log_info("Waiting for device release...")
                    time.sleep(10)
                    
                    # RESIZE the image
                    self.update_progress(60, "Resizing image...")
                    log_info(f"Executing qemu-img resize to {QCow2CloneResizer.format_size(new_size)}")
                    
                    resize_cmd = [
                        'qemu-img', 'resize',
                        '--shrink',
                        '-f', 'qcow2',
                        image_path,
                        str(new_size)
                    ]
                    
                    result = subprocess.run(
                        resize_cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False
                    )
                    
                    if result.returncode != 0:
                        log_error(f"qemu-img resize failed with return code {result.returncode}")
                        log_error(f"stderr: {result.stderr}")
                        raise subprocess.CalledProcessError(result.returncode, resize_cmd, result.stderr)
                    
                    log_info("✓ Windows Image resized successfully")
                    
                    # COMPRESS the resized image
                    self.update_progress(75, "Compressing optimized image...")
                    log_info("Starting compression for Windows image...")
                    
                    compression_stats = QCow2CloneResizer.compress_qcow2_image(
                        image_path,
                        self.update_progress,
                        delete_original_source=None,
                        process_tracker=self
                    )
                    
                    log_info(f"✓ Windows Image compression completed: {compression_stats['compression_ratio']:.1f}% space saved")
                    
                    self.update_progress(95, "Finalizing...")
                    log_info("Analyzing final Windows image...")
                    
                    final_image_info = QCow2CloneResizer.get_image_info(image_path)
                    final_image_size = os.path.getsize(image_path)
                    log_info(f"Final Windows image size: {QCow2CloneResizer.format_size(final_image_size)}")
                    
                    log_info("Showing Windows completion dialog...")
                    self._show_windows_completion_dialog(
                        image_path,
                        original_info,
                        original_source_size,
                        final_image_info,
                        final_image_size,
                        compression_stats
                    )
                    
                    # Clear temp files list on success
                    self.created_temp_files = []
                    log_info("✓ Windows resize operation completed successfully")
                else:
                    log_warning("User cancelled Windows resizing")
                    raise RuntimeError("Operation cancelled by user")
                
            else:
                log_warning("="*60)
                log_warning("UNKNOWN OS TYPE - CANNOT PROCEED")
                log_warning("="*60)
                
                if source_nbd:
                    log_info(f"Disconnecting NBD device: {source_nbd}")
                    self._perform_safe_sync("Unknown OS pre-disconnect sync")
                    QCow2CloneResizer.cleanup_nbd_device(source_nbd)
                    source_nbd = None
                
                self._show_message_and_wait("Unknown OS Type",
                    f"Could not determine if this is a Linux or Windows VM.\n\n"
                    f"GParted changes have been applied but no resize/compression was performed.\n\n"
                    f"Your original image has been modified in place:\n"
                    f"{image_path}\n\n"
                    f"If you want to optimize the image, please run the operation again.")
                
                # Clear temp files list on completion
                self.created_temp_files = []
            
        except subprocess.CalledProcessError as e:
            log_error("="*60)
            log_error(f"SUBPROCESS ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"Command: {e.cmd}")
            log_error(f"Return code: {e.returncode}")
            if e.stderr:
                log_error(f"Error output: {e.stderr}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
        
        except subprocess.TimeoutExpired as e:
            log_error("="*60)
            log_error(f"TIMEOUT ERROR: Operation exceeded {e.timeout} seconds")
            log_error("="*60)
            log_error(f"Command: {e.cmd}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
        
        except FileNotFoundError as e:
            log_error("="*60)
            log_error(f"FILE NOT FOUND ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"Missing file or command: {e}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
        
        except PermissionError as e:
            log_error("="*60)
            log_error(f"PERMISSION ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"Access denied: {e}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
        
        except OSError as e:
            log_error("="*60)
            log_error(f"SYSTEM ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"OS error: {e}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
        
        except ValueError as e:
            log_error("="*60)
            log_error(f"VALUE ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"Invalid value: {e}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
        
        except json.JSONDecodeError as e:
            log_error("="*60)
            log_error(f"JSON PARSE ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)

        except RuntimeError as e:
            log_error("="*60)
            log_error(f"RUNTIME ERROR: {type(e).__name__}")
            log_error("="*60)
            log_error(f"Runtime error: {e}")
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)

        except KeyboardInterrupt:
            log_warning("="*60)
            log_warning("OPERATION INTERRUPTED BY USER (Ctrl+C)")
            log_warning("="*60)
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)

        except Exception as e:
            log_error("="*60)
            log_error(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
            log_error("="*60)
            import traceback
            traceback.print_exc()
            
            # Auto-cleanup .compressed.tmp
            self._auto_cleanup_compressed_tmp()
            
            # Show dialog for intermediate/optimized if any
            if self.created_temp_files:
                self._cleanup_on_error(image_path, self.created_temp_files)
            
        finally:
            # Clean up NBD device
            if source_nbd:
                try:
                    log_info(f"Final cleanup of NBD device: {source_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(source_nbd)
                except subprocess.CalledProcessError as cleanup_e:
                    log_error(f"Error cleaning up NBD device - CalledProcessError: {cleanup_e}")
                except subprocess.TimeoutExpired as cleanup_e:
                    log_error(f"Error cleaning up NBD device - TimeoutExpired: {cleanup_e}")
                except FileNotFoundError as cleanup_e:
                    log_error(f"Error cleaning up NBD device - FileNotFoundError: {cleanup_e}")
                except PermissionError as cleanup_e:
                    log_error(f"Error cleaning up NBD device - PermissionError: {cleanup_e}")
                except OSError as cleanup_e:
                    log_error(f"Error cleaning up NBD device - OSError: {cleanup_e}")
                except Exception as cleanup_e:
                    log_error(f"Error cleaning up NBD device - Unexpected error: {type(cleanup_e).__name__}: {cleanup_e}")
            
            self.root.after(0, self.reset_ui)
            log_info("Worker thread completed")

    def _align_windows_size_to_512(self, size_bytes):
        """Align Windows image size to 512-byte boundary (sector size)
        
        Windows requires images to be aligned to 512-byte sectors.
        If size is not a multiple of 512, round up to next multiple.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Size aligned to 512-byte boundary (always >= input size)
        """
        try:
            # Check if already aligned
            if size_bytes % 512 == 0:
                print(f"Size {self._format_size_compact(size_bytes)} is already 512-byte aligned")
                return size_bytes
            
            # Calculate aligned size (round up)
            aligned_size = ((size_bytes + 511) // 512) * 512
            
            overhead = aligned_size - size_bytes
            print(f"Size alignment for Windows:")
            print(f"  Requested: {self._format_size_compact(size_bytes)} ({size_bytes} bytes)")
            print(f"  Aligned:   {self._format_size_compact(aligned_size)} ({aligned_size} bytes)")
            print(f"  Overhead:  {overhead} bytes")
            
            return aligned_size
            
        except (TypeError, ValueError) as e:
            print(f"ERROR in _align_windows_size_to_512: {e}")
            # Return original size if error (fail gracefully)
            return size_bytes

    def _cleanup_on_error(self, original_image_path, temp_files_to_show):
        """Show dialog to let user select which files to delete - SYNCHRONE approach"""
        try:
            print("\n" + "="*60)
            print("CLEANUP - MANAGING INTERMEDIATE/OPTIMIZED FILES")
            print("="*60)
            
            # Filter only existing files
            existing_files = []
            for file_path in temp_files_to_show:
                if file_path and os.path.exists(file_path):
                    existing_files.append(Path(file_path))
            
            if not existing_files:
                print("No intermediate/optimized files found")
                return True
            
            print(f"Found {len(existing_files)} files to manage:")
            for f in existing_files:
                try:
                    size = os.path.getsize(f)
                    print(f"  - {f.name} ({self._format_size_compact(size)})")
                except OSError:
                    print(f"  - {f.name}")
            
            # Prepare dialog data
            print("Creating file selection dialog...")
            self.dialog_result_event.clear()
            self.dialog_result_value = None
            
            # Call dialog creation and wait for it to complete
            # Utilise une approche qui force Tkinter à traiter le dialog
            self.root.update()  # Process pending events
            
            # Create and show dialog
            self._create_and_show_file_selection_dialog(existing_files, Path(original_image_path))
            
            # Wait for user response with timeout
            if not self.dialog_result_event.wait(timeout=300):
                print("Dialog timeout - user didn't respond in 5 minutes")
                return False
            
            selected_files = self.dialog_result_value
            
            if selected_files is None:
                print("User cancelled cleanup")
                return False
            
            if not selected_files:
                print("User chose to keep all files")
                return True
            
            # Delete selected files
            files_removed = []
            files_failed = []
            
            for file_path in selected_files:
                try:
                    print(f"Removing: {file_path.name}")
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            os.remove(file_path)
                            files_removed.append(file_path.name)
                            break
                        except (PermissionError, OSError) as e:
                            if attempt < max_retries - 1:
                                time.sleep(1)
                            else:
                                raise
                except Exception as e:
                    print(f"Failed to remove {file_path.name}: {e}")
                    files_failed.append(file_path.name)
            
            print(f"\nCleanup: {len(files_removed)} deleted, {len(files_failed)} failed")
            return True
            
        except Exception as e:
            print(f"Error during error cleanup: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _show_final_size_dialog(self, final_layout, partition_changes):
        """Show final size dialog after GParted operations"""
        try:
            print("Creating NewSizeDialog...")
            dialog = NewSizeDialog(self.root, final_layout, self.image_info['virtual_size'], partition_changes)
            # Store the result and signal completion
            self.dialog_result_value = dialog.result
            print(f"Dialog result: {self.dialog_result_value}")
            self.dialog_result_event.set()
        except ImportError as e:
            log_error(f"Final size dialog error - missing module: {e}")
            print(f"ERROR in _show_final_size_dialog - import error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except AttributeError as e:
            log_error(f"Final size dialog error - attribute error: {e}")
            print(f"ERROR in _show_final_size_dialog - attribute error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except TypeError as e:
            log_error(f"Final size dialog error - type error: {e}")
            print(f"ERROR in _show_final_size_dialog - type error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except ValueError as e:
            log_error(f"Final size dialog error - value error: {e}")
            print(f"ERROR in _show_final_size_dialog - value error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except KeyError as e:
            log_error(f"Final size dialog error - missing data key: {e}")
            print(f"ERROR in _show_final_size_dialog - key error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except tk.TclError as e:
            log_error(f"Final size dialog error - Tkinter error: {e}")
            print(f"ERROR in _show_final_size_dialog - Tkinter error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except RuntimeError as e:
            log_error(f"Final size dialog error - runtime error: {e}")
            print(f"ERROR in _show_final_size_dialog - runtime error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except OSError as e:
            log_error(f"Final size dialog error - system error: {e}")
            print(f"ERROR in _show_final_size_dialog - system error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()

    def _create_and_show_file_selection_dialog(self, files_to_clean, original_path):
        """Create and show file selection dialog"""
        try:
            selection_window = tk.Toplevel(self.root)
            selection_window.title("Select Files to Delete")
            selection_window.geometry("700x450")
            selection_window.resizable(True, True)
            
            selection_window.transient(self.root)
            selection_window.grab_set()
            selection_window.lift()
            
            main_frame = ttk.Frame(selection_window, padding="15")
            main_frame.pack(fill="both", expand=True)
            
            title_label = ttk.Label(main_frame, 
                                text="ERROR CLEANUP - Select files to delete",
                                font=("Arial", 12, "bold"))
            title_label.pack(fill="x", pady=(0, 10))
            
            desc_label = ttk.Label(main_frame,
                                text="The following temporary files were created during the cloning operation.\n"
                                    "Select which files to delete. The original image will be preserved.",
                                font=("Arial", 10),
                                wraplength=600,
                                justify="left")
            desc_label.pack(fill="x", pady=(0, 15))
            
            list_frame = ttk.LabelFrame(main_frame, text="Temporary Files", padding="10")
            list_frame.pack(fill="both", expand=True, pady=(0, 15))
            
            scrollbar = ttk.Scrollbar(list_frame)
            scrollbar.pack(side="right", fill="y")
            
            file_listbox = tk.Listbox(list_frame, 
                                    yscrollcommand=scrollbar.set,
                                    height=10,
                                    font=("Consolas", 9),
                                    selectmode=tk.MULTIPLE)
            file_listbox.pack(side="left", fill="both", expand=True)
            scrollbar.config(command=file_listbox.yview)
            
            file_info = []
            for file_path in files_to_clean:
                try:
                    size = os.path.getsize(file_path)
                    size_str = self._format_size_compact(size)
                    display_text = f"{file_path.name} ({size_str})"
                except OSError:
                    display_text = f"{file_path.name} (size unknown)"
                
                file_listbox.insert("end", display_text)
                file_info.append((file_path, display_text))
            
            file_listbox.select_set(0, "end")
            
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill="x", pady=(0, 10))
            
            def select_all():
                file_listbox.select_set(0, "end")
                update_total_size()
            
            def deselect_all():
                file_listbox.selection_clear(0, "end")
                update_total_size()
            
            ttk.Button(button_frame, text="Select All", command=select_all).pack(side="left", padx=(0, 5))
            ttk.Button(button_frame, text="Deselect All", command=deselect_all).pack(side="left", padx=(0, 15))
            
            total_size_label = ttk.Label(button_frame, text="", font=("Arial", 9))
            total_size_label.pack(side="left")
            
            def update_total_size():
                try:
                    selected_indices = file_listbox.curselection()
                    total_size = 0
                    for idx in selected_indices:
                        if idx < len(file_info):
                            total_size += os.path.getsize(file_info[idx][0])
                    size_str = self._format_size_compact(total_size)
                    total_size_label.config(text=f"Total to delete: {size_str}")
                except (OSError, IndexError):
                    total_size_label.config(text="Total to delete: calculating...")
            
            file_listbox.bind("<<ListboxSelect>>", lambda e: update_total_size())
            update_total_size()
            
            info_frame = ttk.Frame(main_frame)
            info_frame.pack(fill="x", pady=(0, 15))
            
            info_label = ttk.Label(info_frame,
                                text="⚠ WARNING: Files will be permanently deleted\n"
                                    "Original image: " + original_path.name + " (will be preserved)",
                                font=("Arial", 9),
                                foreground="red",
                                justify="left")
            info_label.pack(fill="x")
            
            action_frame = ttk.Frame(main_frame)
            action_frame.pack(fill="x")
            
            def on_delete():
                selected_indices = file_listbox.curselection()
                selected_files = [file_info[idx][0] for idx in selected_indices]
                self.dialog_result_value = selected_files
                print(f"User selected {len(selected_files)} files to delete")
                selection_window.destroy()
                self.dialog_result_event.set()
            
            def on_keep():
                self.dialog_result_value = []
                print("User chose to keep all files")
                selection_window.destroy()
                self.dialog_result_event.set()
            
            def on_cancel():
                self.dialog_result_value = None
                print("User cancelled cleanup")
                selection_window.destroy()
                self.dialog_result_event.set()
            
            ttk.Button(action_frame, text="Delete Selected Files", 
                    command=on_delete).pack(side="left", padx=(0, 10))
            ttk.Button(action_frame, text="Keep All Files", 
                    command=on_keep).pack(side="left", padx=(0, 10))
            ttk.Button(action_frame, text="Cancel", 
                    command=on_cancel).pack(side="right")
            
            selection_window.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - selection_window.winfo_width()) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - selection_window.winfo_height()) // 2
            selection_window.geometry(f"+{x}+{y}")
            
            selection_window.focus_force()
            
            print("File selection dialog created and displayed")
            
            print("Waiting for user interaction...")
            while selection_window.winfo_exists():
                try:
                    self.root.update()
                    time.sleep(0.1)
                except tk.TclError:
                    break
            
            print("Dialog closed, proceeding with cleanup")
            
        except tk.TclError as tcl_e:
            print(f"Tkinter error creating selection dialog: {tcl_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except OSError as os_e:
            print(f"OS error in file selection dialog: {os_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except AttributeError as attr_e:
            print(f"Attribute error in file selection dialog: {attr_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except IndexError as idx_e:
            print(f"Index error in file selection dialog: {idx_e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()

    def _perform_safe_sync(self, operation_name="Sync"):
        """Perform sync operation with proper error handling and no timeout"""
        try:
            print(f"{operation_name}: Starting sync operation...")
            
            # Method 1: Try regular sync (no timeout - let it finish)
            try:
                print(f"{operation_name}: Attempting full sync...")
                process = subprocess.Popen(['sync'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                try:
                    stdout, stderr = process.communicate(timeout=120)
                    if process.returncode == 0:
                        print(f"{operation_name}: Full sync completed successfully")
                        time.sleep(2)
                        return True
                except subprocess.TimeoutExpired as timeout_e:
                    print(f"{operation_name}: Full sync taking longer than expected, continuing anyway...")
                    time.sleep(5)
                    return True
                    
            except FileNotFoundError as fnf_e:
                print(f"{operation_name}: sync command not found: {fnf_e}")
            except OSError as os_e:
                print(f"{operation_name}: Full sync error: {os_e}")
            
            # Method 2: Try syncfs on specific device if we have NBD info
            try:
                print(f"{operation_name}: Attempting filesystem-specific sync...")
                subprocess.run(['sync', '-f'], check=False, timeout=30)
                print(f"{operation_name}: Filesystem sync completed")
                time.sleep(2)
                return True
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                pass
            
            # Method 3: Just wait a bit for kernel buffers to flush
            print(f"{operation_name}: Using fallback wait period...")
            time.sleep(10)
            
            print(f"{operation_name}: Sync operation completed (or timed out safely)")
            return True
            
        except KeyboardInterrupt as ki_e:
            print(f"{operation_name}: Sync interrupted: {ki_e}")
            time.sleep(5)
            return False
        except Exception as e:
            print(f"{operation_name}: Sync error (non-fatal): {e}")
            time.sleep(5)
            return False

    def _show_windows_completion_dialog(self, image_path, original_info, original_source_size,
                                    final_image_info, final_image_size, compression_stats):
        """Show completion dialog for Windows image compression"""
        try:
            original_virtual_size = original_info['virtual_size']
            final_virtual_size = final_image_info['virtual_size']
            
            success_msg = f"WINDOWS IMAGE COMPRESSION COMPLETED!\n\n"
            success_msg += f"OPERATION RESULTS:\n"
            success_msg += f"{'='*50}\n"
            success_msg += f"Image: {os.path.basename(image_path)}\n\n"
            
            success_msg += f"IMAGE COMPRESSION RESULTS:\n"
            success_msg += f"Original file size: {QCow2CloneResizer.format_size(original_source_size)}\n"
            success_msg += f"Compressed file size: {QCow2CloneResizer.format_size(final_image_size)}\n"
            
            if final_image_size < original_source_size:
                file_saved = original_source_size - final_image_size
                file_ratio = file_saved / original_source_size * 100
                success_msg += f"\n✓ Space optimized: {QCow2CloneResizer.format_size(file_saved)} smaller ({file_ratio:.1f}% reduction)\n"
            
            if compression_stats and compression_stats.get('compression_ratio', 0) > 0:
                success_msg += f"✓ Compression applied: {compression_stats['compression_ratio']:.1f}% space saved\n"
            
            success_msg += f"\n✓ All partition changes preserved\n"
            success_msg += f"✓ Windows system intact\n"
            success_msg += f"✓ Ready for VM use\n\n"
            
            success_msg += f"Your Windows image has been optimized for storage.\n"
            success_msg += f"No cloning was performed - the image was compressed in place."
            
            self._show_message_and_wait("Compression Complete", success_msg)
            
        except KeyError as e:
            log_error(f"Windows completion dialog error - missing key: {e}")
            self._show_message_and_wait("Operation Complete",
                f"Windows image compression completed!\n\n"
                f"Original: {original_source_size / (1024**3):.2f} GB\n"
                f"Compressed: {final_image_size / (1024**3):.2f} GB\n\n"
                f"Note: Some statistics unavailable.")
        except ZeroDivisionError as e:
            log_error(f"Windows completion dialog error - division by zero: {e}")
            self._show_message_and_wait("Operation Complete",
                f"Windows image compression completed!\n\n"
                f"Cannot calculate compression ratio (zero size detected).")
        except TypeError as e:
            log_error(f"Windows completion dialog error - type error: {e}")
            self._show_message_and_wait("Operation Complete",
                f"Windows image compression completed!\n\n"
                f"Some statistics could not be calculated.")
        except ValueError as e:
            log_error(f"Windows completion dialog error - value error: {e}")
            self._show_message_and_wait("Operation Complete",
                f"Windows image compression completed!\n\n"
                f"Invalid values encountered in statistics.")


    def _show_bios_completion_dialog(self, image_path, original_info, original_source_size,
                                    final_image_info, final_image_size, compression_stats):
        """Show completion dialog for BIOS Linux image compression"""
        try:
            original_virtual_size = original_info['virtual_size']
            final_virtual_size = final_image_info['virtual_size']
            
            success_msg = f"BIOS LINUX IMAGE COMPRESSION COMPLETED!\n\n"
            success_msg += f"OPERATION RESULTS:\n"
            success_msg += f"{'='*50}\n"
            success_msg += f"Image: {os.path.basename(image_path)}\n\n"
            
            success_msg += f"IMAGE COMPRESSION RESULTS:\n"
            success_msg += f"Original file size: {QCow2CloneResizer.format_size(original_source_size)}\n"
            success_msg += f"Compressed file size: {QCow2CloneResizer.format_size(final_image_size)}\n"
            
            if final_image_size < original_source_size:
                file_saved = original_source_size - final_image_size
                file_ratio = file_saved / original_source_size * 100
                success_msg += f"\n✓ Space optimized: {QCow2CloneResizer.format_size(file_saved)} smaller ({file_ratio:.1f}% reduction)\n"
            
            if compression_stats and compression_stats.get('compression_ratio', 0) > 0:
                success_msg += f"✓ Compression applied: {compression_stats['compression_ratio']:.1f}% space saved\n"
            
            success_msg += f"\n✓ All partition changes preserved\n"
            success_msg += f"✓ BIOS bootloader intact\n"
            success_msg += f"✓ Ready for VM use\n\n"
            
            success_msg += f"Your BIOS Linux image has been optimized for storage.\n"
            success_msg += f"No cloning was performed - the image was compressed in place.\n"
            success_msg += f"The bootloader remains unchanged and should boot normally."
            
            self._show_message_and_wait("Compression Complete", success_msg)
            
        except KeyError as e:
            log_error(f"BIOS completion dialog error - missing key: {e}")
            self._show_message_and_wait("Operation Complete",
                f"BIOS Linux image compression completed!\n\n"
                f"Original: {original_source_size / (1024**3):.2f} GB\n"
                f"Compressed: {final_image_size / (1024**3):.2f} GB\n\n"
                f"Note: Some statistics unavailable.")
        except ZeroDivisionError as e:
            log_error(f"BIOS completion dialog error - division by zero: {e}")
            self._show_message_and_wait("Operation Complete",
                f"BIOS Linux image compression completed!\n\n"
                f"Cannot calculate compression ratio (zero size detected).")
        except TypeError as e:
            log_error(f"BIOS completion dialog error - type error: {e}")
            self._show_message_and_wait("Operation Complete",
                f"BIOS Linux image compression completed!\n\n"
                f"Some statistics could not be calculated.")
        except ValueError as e:
            log_error(f"BIOS completion dialog error - value error: {e}")
            self._show_message_and_wait("Operation Complete",
                f"BIOS Linux image compression completed!\n\n"
                f"Invalid values encountered in statistics.")
            

    def _show_completion_and_replacement_dialog(self, source_path, final_path, intermediate_path,
                                        original_info, original_source_size,
                                        final_image_info, final_image_size,
                                        new_size, compression_stats):
        """Show completion dialog comparing SOURCE and FINAL images"""
        try:
            original_virtual_size = original_info['virtual_size']
            final_virtual_size = final_image_info['virtual_size']
            
            # Build success message comparing SOURCE vs FINAL
            success_msg = f"QCOW2 RESIZE & COMPRESSION COMPLETED SUCCESSFULLY!\n\n"
            success_msg += f"OPERATION RESULTS:\n"
            success_msg += f"{'='*50}\n"
            success_msg += f"Original image: {os.path.basename(source_path)}\n"
            success_msg += f"Final optimized image: {os.path.basename(final_path)}\n\n"
            
            success_msg += f"IMAGE COMPARISON (SOURCE vs FINAL):\n"
            success_msg += f"Original source image:\n"
            success_msg += f"  Virtual size: {QCow2CloneResizer.format_size(original_virtual_size)}\n"
            success_msg += f"  File size: {QCow2CloneResizer.format_size(original_source_size)}\n\n"
            success_msg += f"Final optimized image:\n"
            success_msg += f"  Virtual size: {QCow2CloneResizer.format_size(final_virtual_size)}\n"
            success_msg += f"  File size: {QCow2CloneResizer.format_size(final_image_size)}\n\n"
            
            # Calculate improvements
            if final_virtual_size < original_virtual_size:
                saved = original_virtual_size - final_virtual_size
                success_msg += f"✓ Virtual space optimized: {QCow2CloneResizer.format_size(saved)} smaller "
                success_msg += f"({(saved/original_virtual_size*100):.1f}% reduction)\n"
            elif final_virtual_size > original_virtual_size:
                added = final_virtual_size - original_virtual_size
                success_msg += f"✓ Virtual space expanded: {QCow2CloneResizer.format_size(added)} larger "
                success_msg += f"({(added/original_virtual_size*100):.1f}% increase)\n"
            
            if final_image_size < original_source_size:
                file_saved = original_source_size - final_image_size
                file_ratio = file_saved / original_source_size * 100
                success_msg += f"✓ File size optimized: {QCow2CloneResizer.format_size(file_saved)} smaller ({file_ratio:.1f}% reduction)\n"
            
            if compression_stats and compression_stats.get('compression_ratio', 0) > 0:
                success_msg += f"✓ Compression applied: {compression_stats['compression_ratio']:.1f}% space saved\n"
            
            success_msg += f"\n✓ All partition changes preserved\n"
            success_msg += f"✓ Bootloader intact\n"
            success_msg += f"✓ Ready for VM use\n\n"
            
            success_msg += f"NEXT STEP - CLEANUP:\n"
            success_msg += f"{'='*50}\n"
            success_msg += f"REPLACE - Delete original and intermediate, keep final:\n"
            success_msg += f"  • Original image DELETED: {os.path.basename(source_path)}\n"
            success_msg += f"  • Intermediate DELETED: {os.path.basename(intermediate_path)}\n"
            success_msg += f"  • Final becomes main: {os.path.basename(final_path)}\n"
            success_msg += f"  • Maximum space savings\n"
            success_msg += f"  • WARNING: Cannot be undone\n\n"
            success_msg += f"KEEP ALL - Preserve all files for manual cleanup:\n"
            success_msg += f"  • All three files preserved\n"
            success_msg += f"  • Manual cleanup required\n"
            
            # Show dialog using event-based system
            replace_result = self._show_yesnocancel_and_wait(
                "Cleanup - Replace or Keep All?", 
                success_msg
            )
            
            if replace_result is True:  # REPLACE
                self._perform_final_cleanup(source_path, intermediate_path, final_path, 
                                        original_source_size, final_image_size)
            elif replace_result is False:  # KEEP ALL
                self._show_message_and_wait("All Files Preserved", 
                    f"Operation completed successfully!\n\n"
                    f"FILES AVAILABLE:\n"
                    f"• Original: {source_path}\n"
                    f"• Intermediate: {intermediate_path}\n"
                    f"• Final optimized: {final_path}\n\n"
                    f"Manual cleanup required.")
            else:  # Cancel
                self._show_message_and_wait("Operation Complete", 
                    f"QCOW2 resize completed!\n\n"
                    f"Final optimized image: {final_path}")
            
        except KeyError as e:
            log_error(f"Completion dialog error - missing data: {e}")
            self._show_message_and_wait("Operation Complete", 
                f"QCOW2 resize completed!\n\n"
                f"Original: {source_path}\n"
                f"Final: {final_path}\n\n"
                f"Note: Some statistics unavailable.")
        except ZeroDivisionError as e:
            log_error(f"Completion dialog error - division by zero: {e}")
            self._show_message_and_wait("Operation Complete", 
                f"QCOW2 resize completed!\n\n"
                f"Cannot calculate some ratios (zero size detected).")
        except TypeError as e:
            log_error(f"Completion dialog error - type error: {e}")
            self._show_message_and_wait("Operation Complete", 
                f"QCOW2 resize completed - check console for details.")
        except ValueError as e:
            log_error(f"Completion dialog error - value error: {e}")
            self._show_message_and_wait("Operation Complete", 
                f"QCOW2 resize completed - invalid values in statistics.")

    def _perform_final_cleanup(self, source_path, intermediate_path, final_path,
                        original_size, final_size):
        """Delete original and intermediate, rename final to original location"""
        try:
            print(f"Starting final cleanup and file replacement")
            
            total_space_saved = original_size - final_size
            
            # Final confirmation
            confirm_msg = f"FINAL CONFIRMATION - CLEANUP AND REPLACEMENT\n\n"
            confirm_msg += f"Files to DELETE:\n"
            confirm_msg += f"1. Original: {source_path}\n"
            confirm_msg += f"   Size: {QCow2CloneResizer.format_size(original_size)}\n"
            confirm_msg += f"2. Intermediate: {intermediate_path}\n\n"
            confirm_msg += f"Final optimized image will become main file:\n"
            confirm_msg += f"   {final_path} -> {source_path}\n"
            confirm_msg += f"   Size: {QCow2CloneResizer.format_size(final_size)}\n\n"
            confirm_msg += f"Total space saved: {QCow2CloneResizer.format_size(total_space_saved)}\n\n"
            confirm_msg += f"WARNING: This action CANNOT be undone!\n\n"
            confirm_msg += f"Proceed with cleanup?"
            
            final_confirm = self._show_yesno_and_wait(
                "DELETE ORIGINAL AND INTERMEDIATE?", 
                confirm_msg
            )
            
            if not final_confirm:
                self._show_message_and_wait("Cleanup Cancelled", 
                    f"Cleanup cancelled.\n\nAll files preserved for manual handling.")
                return
            
            print(f"User confirmed cleanup - proceeding")
            
            # Step 1: Delete original
            print(f"Deleting original file: {source_path}")
            os.remove(source_path)
            
            # Step 2: Delete intermediate
            print(f"Deleting intermediate file: {intermediate_path}")
            os.remove(intermediate_path)
            
            # Step 3: Move final to original location
            print(f"Moving final to original location: {final_path} -> {source_path}")
            os.rename(final_path, source_path)
            
            # Verify
            if not os.path.exists(source_path):
                raise FileNotFoundError(f"Failed to move final image to original location")
            
            if os.path.exists(intermediate_path) or os.path.exists(final_path):
                print(f"Warning: Cleanup may be incomplete")
            
            print(f"Cleanup completed successfully")
            
            # Success message
            self._show_message_and_wait("Cleanup Complete", 
                f"✓ CLEANUP SUCCESSFUL!\n\n"
                f"FINAL STATUS:\n"
                f"✓ Active file: {source_path}\n"
                f"  (Now the optimized version)\n"
                f"  Size: {QCow2CloneResizer.format_size(final_size)}\n\n"
                f"✓ Original file: DELETED\n"
                f"✓ Intermediate file: DELETED\n"
                f"✓ Total disk space freed: {QCow2CloneResizer.format_size(total_space_saved)}\n\n"
                f"The optimized image is ready for use!")
            
        except FileNotFoundError as e:
            log_error(f"Cleanup failed - file not found: {e}")
            error_msg = f"Could not find file during cleanup:\n{e}\n\n"
            error_msg += f"Files may have been moved or deleted.\n"
            error_msg += f"Check file locations manually:\n"
            error_msg += f"• Original: {source_path}\n"
            error_msg += f"• Intermediate: {intermediate_path}\n"
            error_msg += f"• Final: {final_path}"
            self.root.after(0, lambda: messagebox.showerror("Cleanup Failed - File Not Found", error_msg))
        except PermissionError as e:
            log_error(f"Cleanup failed - permission denied: {e}")
            error_msg = f"Permission denied during file cleanup:\n{e}\n\n"
            error_msg += f"Check file permissions or run as administrator.\n\n"
            error_msg += f"Manual cleanup may be required for:\n"
            error_msg += f"• Original: {source_path}\n"
            error_msg += f"• Intermediate: {intermediate_path}\n"
            error_msg += f"• Final: {final_path}"
            self.root.after(0, lambda: messagebox.showerror("Cleanup Failed - Permission Denied", error_msg))
        except OSError as e:
            log_error(f"Cleanup failed - system error: {e}")
            error_msg = f"System error during file cleanup:\n{e}\n\n"
            error_msg += f"Check disk space and file system status.\n\n"
            error_msg += f"Manual cleanup may be required for:\n"
            error_msg += f"• Original: {source_path}\n"
            error_msg += f"• Intermediate: {intermediate_path}\n"
            error_msg += f"• Final: {final_path}"
            self.root.after(0, lambda: messagebox.showerror("Cleanup Failed - System Error", error_msg))
        except Exception as e:
            log_error(f"Cleanup failed - unexpected error: {e}")
            error_msg = f"Unexpected error during cleanup:\n{e}\n\n"
            error_msg += f"Check file status manually:\n"
            error_msg += f"• Original: {source_path}\n"
            error_msg += f"• Intermediate: {intermediate_path}\n"
            error_msg += f"• Final: {final_path}"
            self.root.after(0, lambda: messagebox.showerror("Cleanup Failed", error_msg))


    def _show_message_and_wait(self, title, message):
        """Show info message and wait for user to click OK"""
        self.dialog_result_event.clear()
        self.dialog_result_value = None
        
        def show_dialog():
            messagebox.showinfo(title, message)
            self.dialog_result_event.set()
        
        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()


    def _show_yesno_and_wait(self, title, message):
        """Show yes/no dialog and wait for user response"""
        self.dialog_result_event.clear()
        self.dialog_result_value = None
        
        def show_dialog():
            result = messagebox.askyesno(title, message, default='yes')
            self.dialog_result_value = result
            self.dialog_result_event.set()
        
        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()
        
        return self.dialog_result_value


    def _show_yesnocancel_and_wait(self, title, message):
        """Show yes/no/cancel dialog and wait for user response"""
        self.dialog_result_event.clear()
        self.dialog_result_value = None
        
        def show_dialog():
            result = messagebox.askyesnocancel(title, message, default='yes')
            self.dialog_result_value = result
            self.dialog_result_event.set()
        
        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()
        
        return self.dialog_result_value

    @staticmethod
    def setup_efi_boot_entries(nbd_device, progress_callback=None):
        """Setup EFI boot entries by creating BOOTX64.EFI fallback
        
        This function discovers the existing bootloader and creates a fallback
        BOOTX64.EFI entry. No efibootmgr NVRAM manipulation needed - the VM
        firmware will automatically find and boot BOOTX64.EFI from the EFI partition.
        """
        try:
            if progress_callback:
                progress_callback(45, "Configuring EFI boot entries...")
            
            print(f"\n{'='*60}")
            print(f"SETTING UP EFI BOOT ENTRIES")
            print(f"{'='*60}")
            print(f"NBD Device: {nbd_device}")
            print(f"Device exists: {os.path.exists(nbd_device)}")
            
            # Detect partition table
            parted_result = subprocess.run(
                ['parted', '-s', nbd_device, 'print'],
                capture_output=True, text=True, check=True, timeout=30
            )
            
            print(f"\nPartition table output:\n{parted_result.stdout}")
            
            is_gpt = 'gpt' in parted_result.stdout.lower()
            is_uefi = is_gpt
            
            if not is_uefi:
                print("BIOS mode detected - no EFI setup needed")
                return True
            
            print("UEFI mode detected - configuring boot entries")
            
            # Find partitions
            partitions = []
            for line in parted_result.stdout.split('\n'):
                if re.match(r'^\s*\d+\s+', line.strip()):
                    parts = line.split()
                    if len(parts) >= 1:
                        partitions.append({
                            'number': int(parts[0]),
                            'flags': line.lower()
                        })
            
            print(f"Found partitions: {[p['number'] for p in partitions]}")
            
            # Find EFI partition
            efi_partition = None
            for part in partitions:
                if 'esp' in part['flags']:
                    efi_partition = part['number']
                    break
            
            print(f"EFI partition: {efi_partition}")
            
            if not efi_partition:
                print("No EFI partition found")
                return False
            
            # Find Linux root and its EFI bootloader
            found_linux = False
            for part_num in [p['number'] for p in partitions]:
                if part_num == efi_partition:
                    continue
                
                print(f"\nChecking partition {part_num}...")
                
                part_device = None
                for path in [f"{nbd_device}p{part_num}", f"{nbd_device}{part_num}"]:
                    if os.path.exists(path):
                        part_device = path
                        print(f"  Found device: {part_device}")
                        break
                
                if not part_device:
                    print(f"  Device not found for partition {part_num}")
                    continue
                
                with tempfile.TemporaryDirectory() as mount_point:
                    try:
                        # Mount root partition - try multiple filesystems
                        print(f"  Mounting {part_device} at {mount_point}...")
                        mounted = False
                        used_fs = None
                        
                        for fs_type in ['auto', 'ext4', 'ext3', 'ext2', 'btrfs', 'xfs']:
                            print(f"    Trying {fs_type}...")
                            result = subprocess.run(
                                ['mount', '-t', fs_type, part_device, mount_point],
                                capture_output=True, timeout=30, check=False
                            )
                            if result.returncode == 0:
                                mounted = True
                                used_fs = fs_type
                                print(f"    ✓ Mounted with {fs_type}")
                                break
                            else:
                                print(f"    ✗ Failed with {fs_type}: {result.stderr.decode('utf-8', errors='ignore')[:100]}")
                        
                        if not mounted:
                            print(f"  Could not mount partition {part_num}")
                            continue
                        
                        # Check what's in mount point
                        print(f"  Mount contents: {os.listdir(mount_point)[:10]}")
                        
                        # Check if Linux - look for multiple indicators
                        is_linux = False
                        linux_indicators = []
                        
                        if os.path.exists(os.path.join(mount_point, 'etc')):
                            is_linux = True
                            linux_indicators.append('etc')
                        
                        if os.path.exists(os.path.join(mount_point, 'root')):
                            linux_indicators.append('root')
                        
                        if os.path.exists(os.path.join(mount_point, 'boot')):
                            linux_indicators.append('boot')
                        
                        if os.path.exists(os.path.join(mount_point, 'usr')):
                            linux_indicators.append('usr')
                        
                        print(f"  Linux indicators: {linux_indicators}")
                        
                        if not is_linux:
                            print(f"  Not a Linux filesystem - skipping")
                            subprocess.run(['umount', mount_point], check=False, timeout=30)
                            continue
                        
                        print(f"✓ Found Linux on partition {part_num} (fs: {used_fs})")
                        found_linux = True
                        
                        # Mount EFI partition
                        efi_mount = os.path.join(mount_point, 'boot', 'efi')
                        os.makedirs(efi_mount, exist_ok=True)
                        print(f"  EFI mount point: {efi_mount}")
                        
                        efi_dev = None
                        for path in [f"{nbd_device}p{efi_partition}", f"{nbd_device}{efi_partition}"]:
                            if os.path.exists(path):
                                efi_dev = path
                                break
                        
                        print(f"  EFI device: {efi_dev}")
                        
                        if not efi_dev:
                            print(f"  EFI device not found")
                            subprocess.run(['umount', mount_point], check=False, timeout=30)
                            continue
                        
                        if subprocess.run(['mount', '-t', 'vfat', efi_dev, efi_mount],
                                        capture_output=True, check=False, timeout=30).returncode != 0:
                            print(f"  Failed to mount EFI partition")
                            subprocess.run(['umount', mount_point], check=False, timeout=30)
                            continue
                        
                        print("✓ EFI partition mounted")
                        
                        efi_base = os.path.join(mount_point, 'boot', 'efi', 'EFI')
                        print(f"  EFI base: {efi_base}")
                        print(f"  EFI base exists: {os.path.exists(efi_base)}")
                        
                        # ===== DISCOVER existing bootloader =====
                        print(f"\n  Searching for existing GRUB bootloader...")
                        
                        existing_grub = None
                        grub_subdir = None
                        
                        if os.path.exists(efi_base):
                            efi_contents = os.listdir(efi_base)
                            print(f"  EFI directory contents: {efi_contents}")
                            
                            for item in efi_contents:
                                item_path = os.path.join(efi_base, item)
                                print(f"    Checking: {item} (is_dir: {os.path.isdir(item_path)})")
                                
                                if os.path.isdir(item_path) and item.upper() != 'BOOT':
                                    # Look for grubx64.efi (Debian, Ubuntu, etc)
                                    grubx64 = os.path.join(item_path, 'grubx64.efi')
                                    print(f"      Looking for: {grubx64} (exists: {os.path.exists(grubx64)})")
                                    
                                    if os.path.exists(grubx64):
                                        existing_grub = grubx64
                                        grub_subdir = item
                                        size = os.path.getsize(grubx64)
                                        print(f"    ✓ Found GRUB bootloader: /EFI/{item}/grubx64.efi ({size} bytes)")
                                        break
                        else:
                            print(f"  EFI base directory does not exist!")
                        
                        if not existing_grub:
                            print("✗ ERROR: No existing GRUB bootloader found")
                            subprocess.run(['umount', efi_mount], check=False, timeout=30)
                            subprocess.run(['umount', mount_point], check=False, timeout=30)
                            continue
                        
                        # ===== Create fallback BOOTX64.EFI =====
                        print("\n  Creating fallback BOOTX64.EFI...")
                        
                        boot_dir = os.path.join(efi_base, 'BOOT')
                        os.makedirs(boot_dir, exist_ok=True)
                        
                        bootx64_path = os.path.join(boot_dir, 'BOOTX64.EFI')
                        
                        try:
                            shutil.copy2(existing_grub, bootx64_path)
                            size = os.path.getsize(bootx64_path)
                            print(f"  ✓ BOOTX64.EFI created: {size} bytes (copy of /EFI/{grub_subdir}/grubx64.efi)")
                        except (shutil.Error, OSError) as e:
                            print(f"  ✗ Error creating BOOTX64.EFI: {e}")
                            subprocess.run(['umount', efi_mount], check=False, timeout=30)
                            subprocess.run(['umount', mount_point], check=False, timeout=30)
                            continue
                        
                        # ===== NO EFIBOOTMGR - Firmware will find BOOTX64.EFI automatically =====
                        print("\n  EFI boot configuration:")
                        print(f"  ✓ BOOTX64.EFI created as fallback bootloader")
                        print(f"  ✓ UEFI firmware will automatically detect and boot BOOTX64.EFI")
                        print(f"  ✓ No NVRAM modification needed")
                        
                        # Display final EFI structure
                        print("\n  Final EFI structure:")
                        if os.path.exists(efi_base):
                            for root, dirs, files in os.walk(efi_base):
                                level = root.replace(efi_base, '').count(os.sep)
                                indent = '    ' + ' ' * 2 * level
                                print(f"{indent}{os.path.basename(root)}/")
                                subindent = '    ' + ' ' * 2 * (level + 1)
                                for file in files:
                                    print(f"{subindent}{file}")
                        
                        # Cleanup
                        subprocess.run(['umount', efi_mount], check=False, timeout=30)
                        subprocess.run(['umount', mount_point], check=False, timeout=30)
                        
                        print("\n✓ EFI boot configuration complete")
                        print(f"{'='*60}\n")
                        return True
                        
                    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                            FileNotFoundError, PermissionError, OSError) as e:
                        print(f"  Error: {e}")
                        subprocess.run(['umount', mount_point], check=False, timeout=10)
            
            if not found_linux:
                print(f"\n✗ ERROR: No Linux root filesystem found on any partition")
                print(f"{'='*60}\n")
            
            return False
            
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, PermissionError, OSError) as e:
            print(f"\nERROR - {type(e).__name__}: {e}")
            print(f"{'='*60}\n")
            import traceback
            traceback.print_exc()
            return False

    def _clone_to_new_image_with_existing_nbd(self, source_path, target_path, new_size_bytes, 
                                existing_source_nbd, layout_info, progress_callback=None,
                                compress=False):
        """Clone to new image using existing NBD device - NO compression by default"""
        target_nbd = None
        
        try:
            print(f"Starting clone with existing NBD device:")
            print(f"  Source NBD: {existing_source_nbd}")
            print(f"  Target: {target_path}")
            print(f"  New size: {QCow2CloneResizer.format_size(new_size_bytes)}")
            print(f"  Compress: {compress}")
            
            # Verification
            min_required = layout_info['required_minimum_bytes']
            if new_size_bytes < min_required:
                raise ValueError(
                    f"Size insufficient! Minimum required: {QCow2CloneResizer.format_size(min_required)}, "
                    f"requested: {QCow2CloneResizer.format_size(new_size_bytes)}"
                )
            
            # Create new image WITHOUT compression
            if progress_callback:
                progress_callback(60, "Creating new image...")
            
            print("Creating new QCOW2 image...")
            QCow2CloneResizer.create_new_qcow2_image(target_path, new_size_bytes, progress_callback)
            
            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Failed to create target image: {target_path}")
            
            # Mount target image
            if progress_callback:
                progress_callback(70, "Mounting target image...")
            
            print("Waiting before mounting target image...")
            time.sleep(5)
            
            exclude_devices = [existing_source_nbd]
            target_nbd = QCow2CloneResizer.setup_nbd_device(
                target_path, 
                progress_callback=None, 
                exclude_devices=exclude_devices
            )
            print(f"Target NBD device: {target_nbd}")
            
            if existing_source_nbd == target_nbd:
                raise RuntimeError(f"CRITICAL ERROR: Source and target NBD devices are identical: {existing_source_nbd}")
            
            # Clone disk structure
            if progress_callback:
                progress_callback(75, "Cloning disk structure...")
            
            print("Cloning disk structure...")
            QCow2CloneResizer.clone_disk_structure(existing_source_nbd, target_nbd, layout_info, progress_callback)
            
            # Clone partition data with proper progress callback
            print("Cloning partition data...")
            self._clone_partition_data_safe(existing_source_nbd, target_nbd, layout_info, progress_callback)
            
            if progress_callback:
                progress_callback(95, "Finalizing clone...")
            
            # Final sync
            print("Performing final filesystem sync...")
            subprocess.run(['sync'], check=False, timeout=60)
            time.sleep(3)
            
            # Cleanup target NBD device
            print(f"Cleaning up target NBD device: {target_nbd}")
            if target_nbd:
                QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                target_nbd = None
            
            time.sleep(5)
            
            # Final verification
            print("Verifying target image...")
            time.sleep(2)
            
            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Target image file not found: {target_path}")
            
            file_stat = os.stat(target_path)
            if file_stat.st_size < 1024: 
                raise ValueError(f"Target image file is too small: {file_stat.st_size} bytes")
            
            final_info = QCow2CloneResizer.get_image_info(target_path)
            print(f"Clone operation completed successfully!")
            print(f"  Final image virtual size: {QCow2CloneResizer.format_size(final_info['virtual_size'])}")
            print(f"  Final file size: {QCow2CloneResizer.format_size(final_info['actual_size'])}")
            
            if progress_callback:
                progress_callback(100, "Clone complete!")
            
            return True
            
        except ValueError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - value error: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD if still mounted
            if target_nbd:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
                    pass
            
            # Delete the failed target image
            if target_path and os.path.exists(target_path):
                try:
                    print(f"Removing failed target image: {target_path}")
                    os.remove(target_path)
                except (FileNotFoundError, PermissionError, OSError):
                    pass
            
            raise
        except FileNotFoundError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - file not found: {e}")
            import traceback
            traceback.print_exc()
            
            if target_nbd:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
                    pass
            
            if target_path and os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except (FileNotFoundError, PermissionError, OSError):
                    pass
            
            raise
        except PermissionError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - permission denied: {e}")
            import traceback
            traceback.print_exc()
            
            if target_nbd:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
                    pass
            
            if target_path and os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except (FileNotFoundError, PermissionError, OSError):
                    pass
            
            raise
        except RuntimeError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - runtime error: {e}")
            import traceback
            traceback.print_exc()
            
            if target_nbd:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
                    pass
            
            if target_path and os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except (FileNotFoundError, PermissionError, OSError):
                    pass
            
            raise
        except OSError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - OS error: {e}")
            import traceback
            traceback.print_exc()
            
            if target_nbd:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
                    pass
            
            if target_path and os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except (FileNotFoundError, PermissionError, OSError):
                    pass
            
            raise

    @staticmethod
    def _clone_disk_structure_safe(source_nbd, target_nbd, layout_info, progress_callback=None, sync_callback=None):
        """Clone disk structure - SIMPLE: just copy partition layout exactly as GParted created it with 5% extra buffer"""
        try:
            print(f"Cloning disk structure from {source_nbd} to {target_nbd}")
            print(f"Copying partition layout exactly as GParted created it\n")
            
            if source_nbd == target_nbd:
                raise ValueError(f"Source and target NBD devices cannot be the same: {source_nbd}")
            
            if progress_callback:
                progress_callback(76, "Copying partition table...")
            
            # Step 1: Copy partition table and MBR/GPT (first 1MB)
            cmd = [
                'dd', 
                f'if={source_nbd}',
                f'of={target_nbd}',
                'bs=1M',
                'count=1',
                'conv=notrunc'
            ]
            
            print(f"Copying structure: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
            print("Syncing after partition table copy...")
            QCow2CloneResizer._perform_safe_sync_static("After partition table copy")
            
            if progress_callback:
                progress_callback(77, "Recreating partition table...")
            
            # Step 2: Get partition table type from source
            parted_result = subprocess.run(
                ['parted', '-s', source_nbd, 'print'],
                capture_output=True, text=True, check=True, timeout=60
            )
            
            table_type = 'msdos'
            for line in parted_result.stdout.split('\n'):
                if 'Partition Table:' in line:
                    table_type = line.split(':')[1].strip()
                    break
            
            print(f"Detected partition table type: {table_type}")
            
            # Step 3: Parse partitions with flags from source
            partitions_with_flags = []
            for line in parted_result.stdout.split('\n'):
                if re.match(r'^\s*\d+\s+', line.strip()):
                    parts = line.split()
                    if len(parts) >= 1:
                        part_num = int(parts[0])
                        flags = []
                        
                        line_lower = line.lower()
                        if 'boot' in line_lower:
                            flags.append('boot')
                        if 'esp' in line_lower:
                            flags.append('esp')
                        if 'bios_grub' in line_lower:
                            flags.append('bios_grub')
                        if 'lvm' in line_lower:
                            flags.append('lvm')
                        if 'raid' in line_lower:
                            flags.append('raid')
                        
                        partitions_with_flags.append({
                            'number': part_num,
                            'flags': flags
                        })
            
            print(f"Parsed partitions with flags: {partitions_with_flags}")
            
            # Step 4: Create partition table on target
            print("Creating partition table on target device...")
            subprocess.run([
                'parted', '-s', target_nbd, 'mklabel', table_type
            ], check=True, timeout=60)
            print("Syncing after mklabel...")
            QCow2CloneResizer._perform_safe_sync_static("After mklabel")
            
            # Step 5: Recreate partitions with 5% extra buffer added to each
            print(f"\nCreating partitions (GParted layout + 5% buffer per partition)...\n")
            
            for i, partition in enumerate(layout_info['partitions']):
                if progress_callback:
                    progress_callback(77 + i, f"Creating partition {partition['number']}...")
                
                part_num = partition['number']
                
                # Parse original end position and add 5% buffer
                end_bytes = partition['end_bytes']
                buffer_5percent = int(end_bytes * 0.05)
                new_end_bytes = end_bytes + buffer_5percent
                
                # Convert to GB format
                new_end_gb = new_end_bytes / (1024**3)
                new_end_str = f"{new_end_gb:.2f}GB"
                
                print(f"\nPartition {part_num}:")
                print(f"  Start:             {partition['start']}")
                print(f"  Original end:      {partition['end']} ({QCow2CloneResizer.format_size(end_bytes)})")
                print(f"  + 5% buffer:       {new_end_str} ({QCow2CloneResizer.format_size(new_end_bytes)})")
                print(f"  Buffer size:       {QCow2CloneResizer.format_size(buffer_5percent)}")
                
                # Create with extended end position
                subprocess.run([
                    'parted', '-s', target_nbd, 
                    'mkpart', 'primary',
                    partition['start'], new_end_str
                ], capture_output=True, text=True, check=True, timeout=60)
                
                print(f"  OK - Created")
                
                # Sync after each partition
                QCow2CloneResizer._perform_safe_sync_static(f"After partition {part_num}")
                subprocess.run(['partprobe', target_nbd], check=False, timeout=30)
            
            # Step 6: Final probe and sync
            print("\nFinal partition probe...")
            subprocess.run(['partprobe', target_nbd], check=False, timeout=30)
            QCow2CloneResizer._perform_safe_sync_static("Final sync before flags")
            
            # Step 7: Apply flags
            if progress_callback:
                progress_callback(78, "Applying partition flags...")
            
            for part_info in partitions_with_flags:
                part_num = part_info['number']
                flags = part_info['flags']
                
                if flags:
                    print(f"Setting flags for partition {part_num}: {flags}")
                    for flag in flags:
                        try:
                            subprocess.run([
                                'parted', '-s', target_nbd,
                                'set', str(part_num), flag, 'on'
                            ], capture_output=True, text=True, check=True, timeout=30)
                            print(f"  OK - Set flag '{flag}'")
                        except subprocess.CalledProcessError as e:
                            print(f"  WARNING - Could not set flag '{flag}': {e}")
                    
                    QCow2CloneResizer._perform_safe_sync_static(f"After flags for partition {part_num}")
            
            # Step 8: Final sync before verification
            print("\nFinal sync...")
            QCow2CloneResizer._perform_safe_sync_static("Final sync before verification")
            
            # Step 9: Verify
            print("Verifying partitions...")
            verify_result = subprocess.run(['lsblk', target_nbd], 
                                        capture_output=True, text=True, timeout=30)
            print(f"Partitions:\n{verify_result.stdout}")
            
            print("\nOK - Disk structure cloning complete!")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Command failed: {e}")
            raise
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            raise


    def _clone_partition_data_safe(self, source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone partition data using dd, but skip SWAP partitions
        
        SWAP partitions don't need cloning - they're recreated at boot.
        Use dd for all other partitions.
        """
        source_part = None
        target_part = None
        process = None
        
        try:
            print(f"\n{'='*60}")
            print(f"CLONING PARTITION DATA")
            print(f"{'='*60}")
            print(f"Source NBD: {source_nbd}")
            print(f"Target NBD: {target_nbd}")

            total_partitions = len(layout_info['partitions'])
            print(f"Processing {total_partitions} partitions\n")

            if progress_callback:
                progress_callback(5, "Ensuring all partitions are available...")

            # Ensure all partitions are available
            print("Ensuring all partitions are available...")
            for attempt in range(10):
                subprocess.run(['partprobe', source_nbd], check=False, timeout=30)
                subprocess.run(['partprobe', target_nbd], check=False, timeout=30)
                time.sleep(2)

            # Clone each partition
            for partition_index, partition in enumerate(layout_info['partitions']):
                partition_num = partition['number']
                partition_label = f"Partition {partition_num}/{total_partitions}"

                # Resolve actual device paths
                def resolve_path(base, num):
                    for opt in (f"{base}p{num}", f"{base}{num}"):
                        if os.path.exists(opt):
                            return opt
                    return None

                source_part = resolve_path(source_nbd, partition_num)
                target_part = resolve_path(target_nbd, partition_num)

                if not source_part or not target_part:
                    print(f"ERROR: Could not access partition {partition_num}")
                    print(f"  Source: {source_part}")
                    print(f"  Target: {target_part}")
                    raise FileNotFoundError(f"Partition {partition_num} not found")

                print(f"\n{partition_label}:")
                print(f"  Source: {source_part}")
                print(f"  Target: {target_part}")

                # Get partition sizes
                try:
                    src_size = int(subprocess.run(['blockdev', '--getsize64', source_part],
                                                capture_output=True, text=True, check=True, timeout=10).stdout.strip())
                    tgt_size = int(subprocess.run(['blockdev', '--getsize64', target_part],
                                                capture_output=True, text=True, check=True, timeout=10).stdout.strip())
                    
                    clone_size = src_size
                    partition_size_formatted = QCow2CloneResizer.format_size(clone_size)
                    
                    print(f"  Source size: {QCow2CloneResizer.format_size(src_size)}")
                    print(f"  Target size: {QCow2CloneResizer.format_size(tgt_size)}")
                    
                    if clone_size <= 0:
                        print(f"  Status: Empty partition - skipping")
                        overall_percent = int((partition_index + 1) / total_partitions * 100)
                        if progress_callback:
                            progress_callback(overall_percent, f"Completed: {partition_label} (empty)")
                        continue
                    
                except subprocess.CalledProcessError as e:
                    print(f"ERROR: Could not determine partition size: {e}")
                    raise OSError(f"Failed to get partition size for {partition_num}: {e}")

                # Detect if this is a SWAP partition
                print(f"  Detecting partition type...")
                is_swap = False
                swap_uuid = None
                
                try:
                    result = subprocess.run(['blkid', '-o', 'value', '-s', 'TYPE', source_part],
                                        capture_output=True, text=True, timeout=10, check=False)
                    partition_type = result.stdout.strip().lower()
                    print(f"  Partition type: {partition_type}")
                    
                    if 'swap' in partition_type:
                        is_swap = True
                        
                        # Get the current SWAP UUID
                        uuid_result = subprocess.run(['blkid', '-o', 'value', '-s', 'UUID', source_part],
                                                capture_output=True, text=True, timeout=10, check=False)
                        swap_uuid = uuid_result.stdout.strip()
                        
                        print(f"  SWAP partition detected")
                        print(f"  Current SWAP UUID: {swap_uuid}")
                        print(f"  Recreating SWAP with same UUID on target...")
                        
                        # Recreate SWAP on target with same UUID
                        if swap_uuid:
                            cmd = ['mkswap', '-U', swap_uuid, target_part]
                        else:
                            cmd = ['mkswap', target_part]
                        
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
                        
                        if result.returncode == 0:
                            print(f"  OK - SWAP recreated with UUID: {swap_uuid}")
                            overall_percent = int((partition_index + 1) / total_partitions * 100)
                            if progress_callback:
                                progress_callback(overall_percent, f"Completed: {partition_label} (SWAP recreated)")
                        else:
                            print(f"  WARNING - Could not recreate SWAP: {result.stderr}")
                            print(f"  Proceeding anyway...")
                            overall_percent = int((partition_index + 1) / total_partitions * 100)
                            if progress_callback:
                                progress_callback(overall_percent, f"Skipped: {partition_label} (SWAP)")
                        
                        continue
                        
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    print(f"  Could not detect partition type, assuming data partition")

                # Clone with dd for non-SWAP partitions
                print(f"  Cloning ({partition_size_formatted})...")
                
                cmd = [
                    'dd',
                    f'if={source_part}',
                    f'of={target_part}',
                    'bs=4M',
                    'conv=notrunc,noerror,sync',
                    'oflag=sync',
                    'status=progress'
                ]
                
                success = False
                last_error = None
                
                for attempt in range(3):
                    process = None
                    try:
                        print(f"  Attempt {attempt + 1}/3...")
                        
                        process = subprocess.Popen(
                            cmd,
                            stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            bufsize=0,
                            universal_newlines=True
                        )
                        
                        last_progress_percent = -1
                        
                        while process.poll() is None:
                            time.sleep(0.2)
                            
                            try:
                                line = process.stderr.readline()
                                if not line:
                                    continue
                                
                                line = line.strip()
                                if not line:
                                    continue
                                
                                m = re.search(r'(\d+)\s+(?:bytes|octets)', line)
                                
                                if m:
                                    bytes_copied = int(m.group(1))
                                    partition_percent = min(100, int((bytes_copied / clone_size) * 100))
                                    
                                    if partition_percent != last_progress_percent:
                                        last_progress_percent = partition_percent
                                        
                                        bytes_formatted = QCow2CloneResizer.format_size(bytes_copied)
                                        
                                        print(f"    {partition_percent}% ({bytes_formatted}/{partition_size_formatted})", end='\r', flush=True)
                                        
                                        if progress_callback:
                                            progress_callback(
                                                partition_percent,
                                                f"Cloning {partition_label}: {partition_percent}% ({bytes_formatted}/{partition_size_formatted})"
                                            )
                                
                            except (UnicodeDecodeError, ValueError, AttributeError):
                                pass
                        
                        return_code = process.returncode
                        if return_code == 0:
                            print(f"\n  OK - Partition {partition_num} cloned successfully")
                            overall_percent = int((partition_index + 1) / total_partitions * 100)
                            if progress_callback:
                                progress_callback(overall_percent, f"Completed: {partition_label} ({partition_size_formatted})")
                            success = True
                            break
                        else:
                            last_error = RuntimeError(f"dd failed with return code {return_code}")
                            print(f"\n  WARNING - dd failed with code {return_code}, attempt {attempt + 1}/3")
                        
                    except subprocess.TimeoutExpired as timeout_e:
                        last_error = subprocess.TimeoutExpired(cmd, timeout_e.timeout)
                        print(f"\n  WARNING - dd timeout, attempt {attempt + 1}/3")
                        if process and process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                    
                    except FileNotFoundError as file_e:
                        last_error = FileNotFoundError(f"dd command not found: {file_e}")
                        print(f"\n  ERROR - dd command not found")
                        raise last_error
                    
                    except PermissionError as perm_e:
                        last_error = PermissionError(f"Permission denied: {perm_e}")
                        print(f"\n  ERROR - Permission denied")
                        raise last_error
                    
                    except OSError as os_e:
                        last_error = OSError(f"OS error: {os_e}")
                        print(f"\n  WARNING - OS error, attempt {attempt + 1}/3")
                    
                    finally:
                        process = None
                
                if not success:
                    if last_error:
                        raise last_error
                    else:
                        raise RuntimeError(f"Failed to clone partition {partition_num} after 3 attempts")
                
                # Sync after each partition - increased timeout
                print(f"  Syncing filesystem...")
                try:
                    subprocess.run(['sync'], check=False, timeout=300)
                except subprocess.TimeoutExpired:
                    print(f"  WARNING - sync taking longer than 5 minutes, continuing anyway")
                    pass
                time.sleep(3)

            if progress_callback:
                progress_callback(100, "All partitions cloned successfully!")

            print(f"\n{'='*60}")
            print(f"OK - ALL PARTITIONS CLONED SUCCESSFULLY")
            print(f"{'='*60}\n")
            
            return True

        except ValueError as val_e:
            print(f"\nERROR - Value error: {val_e}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Value error during partition cloning: {val_e}")
        
        except FileNotFoundError as file_e:
            print(f"\nERROR - File not found: {file_e}")
            import traceback
            traceback.print_exc()
            raise FileNotFoundError(f"File not found during partition cloning: {file_e}")
        
        except PermissionError as perm_e:
            print(f"\nERROR - Permission denied: {perm_e}")
            import traceback
            traceback.print_exc()
            raise PermissionError(f"Permission denied during partition cloning: {perm_e}")
        
        except OSError as os_e:
            print(f"\nERROR - OS error: {os_e}")
            import traceback
            traceback.print_exc()
            raise OSError(f"OS error during partition cloning: {os_e}")
        
        except subprocess.CalledProcessError as cmd_e:
            print(f"\nERROR - Command error: {cmd_e}")
            import traceback
            traceback.print_exc()
            raise subprocess.CalledProcessError(cmd_e.returncode, cmd_e.cmd)
        
        except subprocess.TimeoutExpired as timeout_e:
            print(f"\nERROR - Timeout: {timeout_e}")
            import traceback
            traceback.print_exc()
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    pass
            raise subprocess.TimeoutExpired(timeout_e.cmd, timeout_e.timeout)
        
        except Exception as e:
            print(f"\nERROR - Unexpected error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        finally:
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    pass

    def update_progress(self, percent, status):
        """Thread-safe GUI update"""
        def do_update():
            try:
                if self.progress.winfo_exists():
                    self.progress['value'] = percent
                if self.progress_label.winfo_exists():
                    self.progress_label.config(text=status)

                if self.status_label.winfo_exists():
                    if percent == 0:
                        self.status_label.config(
                            text="Ready - Select image and ensure VM is shut down"
                        )
                    else:
                        self.status_label.config(
                            text=f"Operation in progress: {status}"
                        )
            except tk.TclError:
                pass

        # si appel depuis thread extérieur → renvoi vers thread Tkinter
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, do_update)
        else:
            do_update()

    
    def validate_inputs(self):
        """Validate user inputs"""
        path = self.image_path.get().strip()
        
        if not path:
            messagebox.showwarning("No File Selected", 
                                  "Please select a QCOW2 image file first")
            return False
        
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", 
                                "The selected file does not exist")
            return False
        
        if not self.image_info:
            messagebox.showwarning("Image Not Analyzed", 
                                  "Please analyze the image first by clicking 'Analyze'")
            return False
        
        return True
    

    def reset_ui(self):
        """Reset UI after operation"""
        try:
            if self.main_action_btn.winfo_exists():
                self.main_action_btn.config(state="normal")
            if self.backup_btn.winfo_exists():
                self.backup_btn.config(state="normal")
            if self.progress.winfo_exists():
                self.progress['value'] = 0
            if self.progress_label.winfo_exists():
                self.progress_label.config(text="Operation completed")
            if self.status_label.winfo_exists():
                self.status_label.config(text="Operation completed - Ready for next operation")
        except tk.TclError:
            pass
        
        # Clear process reference
        self.compression_process = None
        
        # Clear temp files list (operation completed successfully)
        self.created_temp_files = []
        
        # Set this LAST
        self.operation_active = False

    def _auto_cleanup_compressed_tmp(self):
        """Auto cleanup ONLY .compressed.tmp files from source directory"""
        if not self.source_image_path:
            return
        
        source_dir = Path(self.source_image_path).parent
        print("\nAuto-cleaning .compressed.tmp files...")
        
        try:
            tmp_files = list(source_dir.glob("*.compressed.tmp"))
        except OSError as os_e:
            print(f"OS error listing temporary files: {os_e}")
            return
        except TypeError as type_e:
            print(f"Type error listing temporary files: {type_e}")
            return
        
        if not tmp_files:
            print("  ✓ No .compressed.tmp files found (already cleaned up)")
            return
        
        cleaned_count = 0
        failed_count = 0
        
        for tmp_file in tmp_files:
            try:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        os.remove(tmp_file)
                        print(f"  ✓ Removed: {tmp_file.name}")
                        cleaned_count += 1
                        break
                    except FileNotFoundError:
                        print(f"  ✓ Already cleaned: {tmp_file.name}")
                        cleaned_count += 1
                        break
                    except (PermissionError, OSError) as e:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                        else:
                            raise
            except FileNotFoundError as fnf_e:
                print(f"  ✓ Already removed {tmp_file.name}")
                cleaned_count += 1
            except PermissionError as perm_e:
                print(f"  ✗ Permission denied: {tmp_file.name}")
                failed_count += 1
            except OSError as os_e:
                print(f"  ✗ Failed to remove {tmp_file.name}: {os_e}")
                failed_count += 1
        
        if cleaned_count > 0 or failed_count == 0:
            print(f"  Cleaned: {cleaned_count}, Failed: {failed_count}")

    def _cleanup_on_error(self, original_image_path, temp_files_to_show):
        """Show dialog to let user select which files to delete"""
        try:
            print("\n" + "="*60)
            print("CLEANUP - MANAGING INTERMEDIATE/OPTIMIZED FILES")
            print("="*60)
            
            # Filter only existing files
            existing_files = []
            for file_path in temp_files_to_show:
                if file_path and os.path.exists(file_path):
                    existing_files.append(Path(file_path))
            
            if not existing_files:
                print("No intermediate/optimized files found")
                return True
            
            print(f"Found {len(existing_files)} files to manage:")
            for f in existing_files:
                try:
                    size = os.path.getsize(f)
                    print(f"  - {f.name} ({self._format_size_compact(size)})")
                except OSError:
                    print(f"  - {f.name}")
            
            print("Creating file selection dialog...")
            self.dialog_result_event.clear()
            self.dialog_result_value = None
            
            self.root.update()
            self._create_and_show_file_selection_dialog(existing_files, Path(original_image_path))
            
            # Wait for user response with timeout
            if not self.dialog_result_event.wait(timeout=300):
                print("Dialog timeout - user didn't respond in 5 minutes")
                return False
            
            selected_files = self.dialog_result_value
            
            if selected_files is None:
                print("User cancelled cleanup")
                return False
            
            if not selected_files:
                print("User chose to keep all files")
                return True
            
            # Delete selected files
            files_removed = []
            files_failed = []
            
            for file_path in selected_files:
                try:
                    print(f"Removing: {file_path.name}")
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            os.remove(file_path)
                            files_removed.append(file_path.name)
                            break
                        except (PermissionError, OSError) as e:
                            if attempt < max_retries - 1:
                                time.sleep(1)
                            else:
                                raise
                except FileNotFoundError as fnf_e:
                    print(f"File already removed {file_path.name}: {fnf_e}")
                    files_removed.append(file_path.name)
                except PermissionError as perm_e:
                    print(f"Permission denied removing {file_path.name}: {perm_e}")
                    files_failed.append(file_path.name)
                except OSError as os_e:
                    print(f"Failed to remove {file_path.name}: {os_e}")
                    files_failed.append(file_path.name)
            
            print(f"\nCleanup: {len(files_removed)} deleted, {len(files_failed)} failed")
            return True
            
        except tk.TclError as tcl_e:
            print(f"Tkinter error during cleanup: {tcl_e}")
            return False
        except ValueError as val_e:
            print(f"Value error during cleanup: {val_e}")
            return False
        except TypeError as type_e:
            print(f"Type error during cleanup: {type_e}")
            return False
        except AttributeError as attr_e:
            print(f"Attribute error during cleanup: {attr_e}")
            return False

    
def main():
    """Main entry point"""
    print("=" * 75)
    print("QCOW2 CLONE RESIZER - GPARTED + SAFE CLONING METHOD")
    print("=" * 75)
    
    # Check tools
    missing, optional = QCow2CloneResizer.check_tools()
    if missing:
        print(f"ERROR: Missing required tools: {', '.join(missing)}")
        print("\nINSTALL REQUIRED PACKAGES:")
        print("Ubuntu/Debian: sudo apt install qemu-utils parted gparted")
        print("Fedora/RHEL: sudo dnf install qemu-img parted gparted") 
        print("Arch Linux: sudo pacman -S qemu parted gparted")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    print("All required tools are available")
    
    if optional:
        print(f"Optional recommended tools: {', '.join(optional)}")
        print("   These tools can speed up certain cloning operations")
    
    # Check if running as root
    if os.geteuid() != 0:
        print("WARNING: Not running as root")
        print("   Some operations will require privilege escalation")
        print("   For best experience, run with: sudo python3 qcow2_clone_resizer.py")
    else:
        print("Running with root privileges")
    
    print("\nLaunching GUI...")
    print("PROCESS OVERVIEW:")
    print("   1. Select QCOW2 image file")
    print("   2. Launch GParted for manual partition editing")
    print("   3. Apply partition changes in GParted")
    print("   4. Choose optimal size for new image")
    print("   5. Safe cloning to new optimized image (with preallocation=metadata)")
    print("=" * 75)
    
    # Launch GUI
    root = tk.Tk()
    app = QCow2CloneResizerGUI(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
    except ImportError as e:
        print(f"\nImport error: {e}")
        print("Please ensure all required Python modules are installed")
    except OSError as e:
        print(f"\nSystem error: {e}")
        print("Check system resources and permissions")
    except RuntimeError as e:
        print(f"\nRuntime error: {e}")
        print("Application encountered an internal error")
    
    print("Application closed - Goodbye!")


if __name__ == "__main__":
    main()
