#!/usr/bin/env python3
"""
QCOW2 Image Resizer GUI Module
Provides GUI for resizing qcow2 virtual disk images using GParted and qemu-img
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import json
import tempfile
from log_handler import log_info, log_error, log_warning
from utils import format_bytes, run_command
from vm import verify_vm_image


class QCOW2ResizerGUI:
    """GUI class for resizing QCOW2 virtual disk images"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("QCOW2 Virtual Disk Resizer")
        self.root.geometry("700x600")
        
        # Operation control variables
        self.operation_running = False
        self.stop_requested = False
        
        # VM image variables
        self.image_path = tk.StringVar()
        self.vm_image_info = None
        self.mounted_path = None
        
        # Resize variables
        self.resize_operation = tk.StringVar(value="shrink")  # shrink or expand
        self.resize_amount_gb = tk.DoubleVar(value=1.0)
        self.target_size_gb = tk.DoubleVar()
        
        # Create the GUI elements
        self.create_widgets()
        
        # Set up window close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        
        log_info("QCOW2 Resizer GUI initialized")
    
    def create_widgets(self):
        """Create all GUI widgets"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.grid_rowconfigure(3, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Header
        header_label = ttk.Label(main_frame, text="QCOW2 Virtual Disk Resizer", 
                                font=("Arial", 16, "bold"))
        header_label.grid(row=0, column=0, pady=(0, 20))
        
        # Image selection frame
        self.create_image_selection_frame(main_frame)
        
        # Image information frame
        self.create_image_info_frame(main_frame)
        
        # Resize configuration frame
        self.create_resize_config_frame(main_frame)
        
        # Log frame
        self.create_log_frame(main_frame)
        
        # Control buttons
        self.create_control_buttons(main_frame)
        
        # Check prerequisites
        self.check_prerequisites()
    
    def create_image_selection_frame(self, parent):
        """Create the image selection frame"""
        selection_frame = ttk.LabelFrame(parent, text="Select QCOW2 Image", padding="10")
        selection_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        selection_frame.grid_columnconfigure(1, weight=1)
        
        ttk.Label(selection_frame, text="Image File:").grid(row=0, column=0, sticky="w")
        
        path_frame = ttk.Frame(selection_frame)
        path_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        path_frame.grid_columnconfigure(0, weight=1)
        
        path_entry = ttk.Entry(path_frame, textvariable=self.image_path, state="readonly")
        path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        browse_btn = ttk.Button(path_frame, text="Browse...", command=self.browse_image_file)
        browse_btn.grid(row=0, column=1)
        
        analyze_btn = ttk.Button(path_frame, text="Analyze Image", command=self.analyze_image)
        analyze_btn.grid(row=0, column=2, padx=(5, 0))
    
    def create_image_info_frame(self, parent):
        """Create the image information display frame"""
        info_frame = ttk.LabelFrame(parent, text="Image Information", padding="10")
        info_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        info_frame.grid_columnconfigure(0, weight=1)
        
        self.info_text = tk.Text(info_frame, height=8, wrap=tk.WORD, state=tk.DISABLED,
                                font=("Consolas", 9), bg="#f8f8f8")
        info_scrollbar = ttk.Scrollbar(info_frame, orient="vertical", command=self.info_text.yview)
        self.info_text.configure(yscrollcommand=info_scrollbar.set)
        
        self.info_text.grid(row=0, column=0, sticky="nsew")
        info_scrollbar.grid(row=0, column=1, sticky="ns")
        
        info_frame.grid_rowconfigure(0, weight=1)
    
    def create_resize_config_frame(self, parent):
        """Create the resize configuration frame"""
        resize_frame = ttk.LabelFrame(parent, text="Resize Configuration", padding="10")
        resize_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        resize_frame.grid_columnconfigure(1, weight=1)
        
        # Operation type
        ttk.Label(resize_frame, text="Operation:").grid(row=0, column=0, sticky="w")
        
        operation_frame = ttk.Frame(resize_frame)
        operation_frame.grid(row=0, column=1, sticky="w", padx=(10, 0))
        
        shrink_radio = ttk.Radiobutton(operation_frame, text="Shrink", 
                                      variable=self.resize_operation, value="shrink",
                                      command=self.on_operation_changed)
        shrink_radio.grid(row=0, column=0, padx=(0, 20))
        
        expand_radio = ttk.Radiobutton(operation_frame, text="Expand", 
                                      variable=self.resize_operation, value="expand",
                                      command=self.on_operation_changed)
        expand_radio.grid(row=0, column=1)
        
        # Size adjustment
        ttk.Label(resize_frame, text="Size Change:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        
        size_frame = ttk.Frame(resize_frame)
        size_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10, 0))
        size_frame.grid_columnconfigure(0, weight=1)
        
        size_spinbox = ttk.Spinbox(size_frame, from_=0.1, to=1000.0, increment=0.5, 
                                  textvariable=self.resize_amount_gb, width=10,
                                  command=self.update_target_size)
        size_spinbox.grid(row=0, column=0, sticky="w")
        size_spinbox.bind("<KeyRelease>", self.update_target_size)
        
        ttk.Label(size_frame, text="GB").grid(row=0, column=1, sticky="w", padx=(5, 0))
        
        # Target size display
        ttk.Label(resize_frame, text="Target Size:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.target_size_label = ttk.Label(resize_frame, text="N/A", font=("Arial", 9, "bold"))
        self.target_size_label.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(10, 0))
        
        # Warning label
        self.resize_warning = ttk.Label(resize_frame, text="", foreground="red", wraplength=400)
        self.resize_warning.grid(row=3, column=0, columnspan=2, pady=(10, 0))
    
    def create_log_frame(self, parent):
        """Create the operation log frame"""
        log_frame = ttk.LabelFrame(parent, text="Operation Log", padding="5")
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(0, 10))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED,
                               font=("Consolas", 9), bg="#f8f8f8")
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scrollbar.grid(row=0, column=1, sticky="ns")
    
    def create_control_buttons(self, parent):
        """Create control buttons"""
        button_frame = ttk.Frame(parent)
        button_frame.grid(row=5, column=0, sticky="ew")
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(button_frame, variable=self.progress_var, 
                                           maximum=100, length=200)
        self.progress_bar.grid(row=0, column=0, sticky="w", pady=(0, 10))
        
        self.progress_label = ttk.Label(button_frame, text="0%")
        self.progress_label.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 10))
        
        # Buttons
        controls_frame = ttk.Frame(button_frame)
        controls_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        
        self.resize_btn = ttk.Button(controls_frame, text="Start Resize Operation", 
                                    command=self.start_resize_operation)
        self.resize_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.stop_btn = ttk.Button(controls_frame, text="Stop Operation", 
                                  command=self.stop_operation, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=1, padx=(0, 10))
        
        self.close_btn = ttk.Button(controls_frame, text="Close", command=self.close_window)
        self.close_btn.grid(row=0, column=2)
    
    def check_prerequisites(self):
        """Check if required tools are available"""
        required_tools = ['qemu-img', 'gparted', 'qemu-nbd', 'modprobe']
        missing = []
        
        for tool in required_tools:
            try:
                subprocess.run([tool, '--version'], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                if tool == 'gparted':
                    # Check if gparted is available
                    try:
                        subprocess.run(['which', 'gparted'], capture_output=True, check=True)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        missing.append(tool)
                elif tool == 'qemu-nbd':
                    # Check for qemu-nbd
                    try:
                        subprocess.run(['which', 'qemu-nbd'], capture_output=True, check=True)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        missing.append(tool)
                else:
                    missing.append(tool)
        
        if missing:
            error_msg = f"Missing required tools: {', '.join(missing)}\n\n"
            error_msg += "Please install:\n"
            if 'gparted' in missing:
                error_msg += "• gparted (for partition management)\n"
            if 'qemu-img' in missing:
                error_msg += "• qemu-utils (for qemu-img)\n"
            if 'qemu-nbd' in missing:
                error_msg += "• qemu-utils (for qemu-nbd)\n"
            
            messagebox.showerror("Missing Prerequisites", error_msg)
            log_error(f"Prerequisites check failed: {', '.join(missing)}")
        else:
            log_info("All prerequisites available for QCOW2 resize operations")
    
    def browse_image_file(self):
        """Browse for QCOW2 image file"""
        file_path = filedialog.askopenfilename(
            title="Select QCOW2 Virtual Disk Image",
            filetypes=[
                ("QCOW2 Images", "*.qcow2"),
                ("All Files", "*.*")
            ],
            initialdir=os.path.expanduser("~")
        )
        
        if file_path:
            self.image_path.set(file_path)
            log_info(f"Selected QCOW2 image: {file_path}")
            # Auto-analyze the selected image
            self.analyze_image()
    
    def analyze_image(self):
        """Analyze the selected QCOW2 image"""
        image_path = self.image_path.get()
        
        if not image_path:
            messagebox.showwarning("Warning", "Please select a QCOW2 image file first")
            return
        
        if not os.path.exists(image_path):
            messagebox.showerror("Error", f"File does not exist: {image_path}")
            return
        
        try:
            self.log_message("Analyzing QCOW2 image...")
            
            # Get image information using verify_vm_image
            self.vm_image_info = verify_vm_image(image_path)
            
            if not self.vm_image_info['success']:
                # Try alternative method
                try:
                    result = subprocess.run(['qemu-img', 'info', '--output=json', image_path], 
                                          capture_output=True, text=True, check=True)
                    info_data = json.loads(result.stdout)
                    
                    self.vm_image_info = {
                        'success': True,
                        'virtual_size': info_data.get('virtual-size', 0),
                        'actual_size': info_data.get('actual-size', 0),
                        'format': info_data.get('format', 'unknown'),
                        'compressed': info_data.get('compressed', False)
                    }
                except Exception as e:
                    self.log_message(f"Error analyzing image: {str(e)}", "ERROR")
                    return
            
            # Get filesystem information by mounting the image
            filesystem_info = self.get_filesystem_info(image_path)
            
            # Display image information
            self.display_image_info(filesystem_info)
            
            # Update target size based on current size
            current_gb = self.vm_image_info['virtual_size'] / (1024**3)
            self.target_size_gb.set(current_gb)
            self.update_target_size()
            
            self.log_message("Image analysis completed")
            
        except Exception as e:
            error_msg = f"Failed to analyze image: {str(e)}"
            self.log_message(error_msg, "ERROR")
            messagebox.showerror("Analysis Error", error_msg)
    
    def get_filesystem_info(self, image_path):
        """Get filesystem information by mounting the qcow2 image"""
        try:
            # Load nbd module if not loaded
            try:
                subprocess.run(['sudo', 'modprobe', 'nbd'], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                pass  # Module might already be loaded
            
            # Find available nbd device
            nbd_device = None
            for i in range(16):  # Check nbd0 through nbd15
                device = f"/dev/nbd{i}"
                try:
                    # Check if device is not in use
                    result = subprocess.run(['sudo', 'qemu-nbd', '--list'], 
                                          capture_output=True, text=True)
                    if device not in result.stdout:
                        nbd_device = device
                        break
                except subprocess.CalledProcessError:
                    continue
            
            if not nbd_device:
                return {"error": "No available NBD devices"}
            
            try:
                # Connect qcow2 to nbd device
                subprocess.run(['sudo', 'qemu-nbd', '--connect', nbd_device, image_path], 
                             check=True, capture_output=True)
                
                # Wait for device to be ready
                import time
                time.sleep(2)
                
                # Get partition information
                result = subprocess.run(['sudo', 'fdisk', '-l', nbd_device], 
                                      capture_output=True, text=True)
                partition_info = result.stdout
                
                # Try to get filesystem info from first partition
                first_partition = f"{nbd_device}p1"
                filesystem_data = {}
                
                try:
                    # Get filesystem type
                    fs_result = subprocess.run(['sudo', 'blkid', '-o', 'value', '-s', 'TYPE', first_partition],
                                             capture_output=True, text=True)
                    filesystem_data['type'] = fs_result.stdout.strip() or "Unknown"
                    
                    # Get filesystem size info
                    df_result = subprocess.run(['sudo', 'df', '--block-size=1', first_partition],
                                             capture_output=True, text=True)
                    if df_result.returncode == 0:
                        lines = df_result.stdout.strip().split('\n')
                        if len(lines) > 1:
                            parts = lines[1].split()
                            if len(parts) >= 4:
                                filesystem_data['total'] = int(parts[1])
                                filesystem_data['used'] = int(parts[2])
                                filesystem_data['available'] = int(parts[3])
                
                except subprocess.CalledProcessError:
                    # Try mounting to get better info
                    mount_point = tempfile.mkdtemp()
                    try:
                        subprocess.run(['sudo', 'mount', '-o', 'ro', first_partition, mount_point],
                                     check=True, capture_output=True)
                        
                        df_result = subprocess.run(['df', '--block-size=1', mount_point],
                                                 capture_output=True, text=True, check=True)
                        lines = df_result.stdout.strip().split('\n')
                        if len(lines) > 1:
                            parts = lines[1].split()
                            if len(parts) >= 4:
                                filesystem_data['total'] = int(parts[1])
                                filesystem_data['used'] = int(parts[2])
                                filesystem_data['available'] = int(parts[3])
                        
                        subprocess.run(['sudo', 'umount', mount_point], check=True, capture_output=True)
                    except subprocess.CalledProcessError:
                        pass
                    finally:
                        try:
                            os.rmdir(mount_point)
                        except OSError:
                            pass
                
                return {
                    'partition_info': partition_info,
                    'filesystem': filesystem_data,
                    'nbd_device': nbd_device
                }
                
            finally:
                # Disconnect nbd device
                try:
                    subprocess.run(['sudo', 'qemu-nbd', '--disconnect', nbd_device], 
                                 capture_output=True)
                except subprocess.CalledProcessError:
                    pass
        
        except Exception as e:
            return {"error": str(e)}
    
    def display_image_info(self, filesystem_info):
        """Display comprehensive image information"""
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        
        if not self.vm_image_info:
            self.info_text.insert(tk.END, "No image information available")
            self.info_text.config(state=tk.DISABLED)
            return
        
        # Basic image information
        info_text = f"Image File: {self.image_path.get()}\n"
        info_text += f"Format: {self.vm_image_info.get('format', 'Unknown')}\n"
        info_text += f"Virtual Size: {format_bytes(self.vm_image_info.get('virtual_size', 0))}\n"
        info_text += f"Actual Size: {format_bytes(self.vm_image_info.get('actual_size', 0))}\n"
        info_text += f"Compressed: {'Yes' if self.vm_image_info.get('compressed', False) else 'No'}\n\n"
        
        # Filesystem information
        if filesystem_info and 'error' not in filesystem_info:
            fs_data = filesystem_info.get('filesystem', {})
            if fs_data:
                info_text += "Filesystem Information:\n"
                info_text += f"Type: {fs_data.get('type', 'Unknown')}\n"
                
                if 'total' in fs_data:
                    total_bytes = fs_data['total']
                    used_bytes = fs_data['used']
                    available_bytes = fs_data['available']
                    usage_percent = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0
                    
                    info_text += f"Filesystem Size: {format_bytes(total_bytes)}\n"
                    info_text += f"Used Space: {format_bytes(used_bytes)} ({usage_percent:.1f}%)\n"
                    info_text += f"Free Space: {format_bytes(available_bytes)}\n"
                    
                    # Calculate potential space savings
                    virtual_size = self.vm_image_info.get('virtual_size', 0)
                    potential_savings = virtual_size - total_bytes
                    if potential_savings > 0:
                        info_text += f"\nPotential Space Savings:\n"
                        info_text += f"Virtual disk can be reduced by up to {format_bytes(potential_savings)}\n"
                        info_text += f"Minimum safe size: {format_bytes(used_bytes * 1.2)}\n"  # 20% safety margin
            
            # Partition information
            if 'partition_info' in filesystem_info:
                info_text += f"\nPartition Layout:\n{filesystem_info['partition_info']}"
        
        elif filesystem_info and 'error' in filesystem_info:
            info_text += f"Filesystem Analysis Error: {filesystem_info['error']}\n"
            info_text += "Proceeding with virtual disk resize only (filesystem resize not available)\n"
        
        self.info_text.insert(tk.END, info_text)
        self.info_text.config(state=tk.DISABLED)
    
    def on_operation_changed(self):
        """Handle operation type change"""
        self.update_target_size()
        self.update_warnings()
    
    def update_target_size(self, event=None):
        """Update target size display"""
        if not self.vm_image_info:
            return
        
        try:
            current_gb = self.vm_image_info['virtual_size'] / (1024**3)
            change_gb = self.resize_amount_gb.get()
            
            if self.resize_operation.get() == "shrink":
                target_gb = current_gb - change_gb
            else:  # expand
                target_gb = current_gb + change_gb
            
            self.target_size_gb.set(target_gb)
            
            if target_gb > 0:
                self.target_size_label.config(text=f"{target_gb:.1f} GB ({format_bytes(int(target_gb * 1024**3))})")
            else:
                self.target_size_label.config(text="Invalid size")
            
            self.update_warnings()
            
        except (ValueError, AttributeError):
            self.target_size_label.config(text="N/A")
    
    def update_warnings(self):
        """Update warning messages based on current configuration"""
        if not self.vm_image_info:
            return
        
        warnings = []
        
        try:
            target_gb = self.target_size_gb.get()
            operation = self.resize_operation.get()
            
            if target_gb <= 0:
                warnings.append("Target size must be positive")
            
            if operation == "shrink":
                # Get filesystem used space if available
                # This is a simplified check - actual implementation should be more thorough
                current_gb = self.vm_image_info['virtual_size'] / (1024**3)
                min_safe_gb = current_gb * 0.3  # Conservative estimate
                
                if target_gb < min_safe_gb:
                    warnings.append(f"Warning: Target size may be too small (minimum recommended: {min_safe_gb:.1f} GB)")
                
                warnings.append("Shrinking requires filesystem to be resized first - data loss possible if not done carefully")
            
            elif operation == "expand":
                warnings.append("Expanding virtual disk size - filesystem must be expanded separately")
            
            self.resize_warning.config(text="\n".join(warnings))
            
        except (ValueError, AttributeError):
            self.resize_warning.config(text="Invalid configuration")
    
    def start_resize_operation(self):
        """Start the resize operation"""
        if not self.validate_resize_config():
            return
        
        image_path = self.image_path.get()
        operation = self.resize_operation.get()
        target_gb = self.target_size_gb.get()
        
        # Confirmation dialog
        confirm_text = f"QCOW2 Resize Confirmation\n\n"
        confirm_text += f"Image: {os.path.basename(image_path)}\n"
        confirm_text += f"Operation: {operation.title()}\n"
        confirm_text += f"Target Size: {target_gb:.1f} GB\n\n"
        
        if operation == "shrink":
            confirm_text += "WARNING: Shrinking operations can cause data loss!\n"
            confirm_text += "This operation will:\n"
            confirm_text += "1. Mount the virtual disk\n"
            confirm_text += "2. Launch GParted for partition resizing\n"
            confirm_text += "3. Resize the virtual disk file\n\n"
            confirm_text += "Make sure you have a backup before proceeding!\n\n"
        else:
            confirm_text += "This operation will:\n"
            confirm_text += "1. Resize the virtual disk file\n"
            confirm_text += "2. Launch GParted for partition expansion\n\n"
        
        confirm_text += "Continue?"
        
        if not messagebox.askyesno("Confirm Resize Operation", confirm_text):
            return
        
        # Start operation in thread
        self.operation_running = True
        self.stop_requested = False
        
        resize_thread = threading.Thread(target=self._resize_worker, 
                                        args=(image_path, operation, target_gb))
        resize_thread.daemon = True
        resize_thread.start()
        
        # Update UI
        self.resize_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
    
    def validate_resize_config(self):
        """Validate resize configuration"""
        image_path = self.image_path.get()
        
        if not image_path:
            messagebox.showwarning("Warning", "Please select a QCOW2 image file")
            return False
        
        if not os.path.exists(image_path):
            messagebox.showerror("Error", "Selected image file does not exist")
            return False
        
        if not self.vm_image_info:
            messagebox.showwarning("Warning", "Please analyze the image first")
            return False
        
        try:
            target_gb = self.target_size_gb.get()
            if target_gb <= 0:
                messagebox.showerror("Error", "Target size must be positive")
                return False
        except (ValueError, tk.TclError):
            messagebox.showerror("Error", "Invalid target size")
            return False
        
        return True
    
    def _resize_worker(self, image_path, operation, target_gb):
        """Worker thread for resize operation"""
        try:
            self.log_message(f"Starting {operation} operation on {os.path.basename(image_path)}")
            
            if operation == "shrink":
                self._perform_shrink(image_path, target_gb)
            else:
                self._perform_expand(image_path, target_gb)
            
            if not self.stop_requested:
                self.log_message("Resize operation completed successfully!", "SUCCESS")
                self.root.after(0, lambda: messagebox.showinfo("Operation Complete", 
                    "Resize operation completed successfully!\n\n"
                    "Please verify the resized image before using it."))
        
        except KeyboardInterrupt:
            self.log_message("Resize operation cancelled by user", "WARNING")
        except Exception as e:
            error_msg = f"Resize operation failed: {str(e)}"
            self.log_message(error_msg, "ERROR")
            self.root.after(0, lambda: messagebox.showerror("Operation Failed", error_msg))
        
        finally:
            self.root.after(0, self._reset_ui_after_operation)
    
    def _perform_shrink(self, image_path, target_gb):
        """Perform shrink operation"""
        target_bytes = int(target_gb * 1024**3)
        
        # Step 1: Create backup
        self._update_progress(10, "Creating backup...")
        backup_path = image_path + ".backup"
        subprocess.run(['cp', image_path, backup_path], check=True)
        self.log_message(f"Backup created: {backup_path}")
        
        try:
            # Step 2: Mount image and launch GParted for filesystem resize
            self._update_progress(20, "Mounting image for partition management...")
            nbd_device = self._mount_image_for_editing(image_path)
            
            self._update_progress(30, "Launching GParted for filesystem resize...")
            self.log_message("Launching GParted - please resize partitions FIRST, then close GParted")
            
            # Launch GParted with the mounted device
            gparted_process = subprocess.Popen(['sudo', 'gparted', nbd_device])
            
            # Wait for GParted to close
            while gparted_process.poll() is None:
                if self.stop_requested:
                    gparted_process.terminate()
                    raise KeyboardInterrupt("Operation cancelled")
                import time
                time.sleep(1)
            
            self.log_message("GParted closed - proceeding with virtual disk resize")
            
            # Step 3: Unmount and resize virtual disk
            self._update_progress(60, "Unmounting image...")
            self._unmount_image(nbd_device)
            
            self._update_progress(70, "Resizing virtual disk...")
            subprocess.run(['qemu-img', 'resize', image_path, f"{target_bytes}"], check=True)
            
            self._update_progress(90, "Verifying resized image...")
            # Verify the resize worked
            new_info = verify_vm_image(image_path)
            if new_info['success'] and new_info['virtual_size'] == target_bytes:
                self.log_message(f"Virtual disk resized to {format_bytes(target_bytes)}")
            else:
                raise Exception("Virtual disk resize verification failed")
            
            self._update_progress(100, "Shrink operation completed")
            
        except Exception as e:
            # Restore backup on failure
            if os.path.exists(backup_path):
                subprocess.run(['cp', backup_path, image_path], check=True)
                self.log_message("Backup restored due to error")
            raise e
        finally:
            # Clean up backup
            if os.path.exists(backup_path):
                os.remove(backup_path)
    
    def _perform_expand(self, image_path, target_gb):
        """Perform expand operation"""
        target_bytes = int(target_gb * 1024**3)
        
        # Step 1: Resize virtual disk first (safer for expansion)
        self._update_progress(20, "Expanding virtual disk...")
        subprocess.run(['qemu-img', 'resize', image_path, f"{target_bytes}"], check=True)
        self.log_message(f"Virtual disk expanded to {format_bytes(target_bytes)}")
        
        # Step 2: Mount and launch GParted for filesystem expansion
        self._update_progress(40, "Mounting image for partition management...")
        nbd_device = self._mount_image_for_editing(image_path)
        
        self._update_progress(60, "Launching GParted for filesystem expansion...")
        self.log_message("Launching GParted - please expand partitions to use new space, then close GParted")
        
        # Launch GParted
        gparted_process = subprocess.Popen(['sudo', 'gparted', nbd_device])
        
        # Wait for GParted to close
        while gparted_process.poll() is None:
            if self.stop_requested:
                gparted_process.terminate()
                raise KeyboardInterrupt("Operation cancelled")
            import time
            time.sleep(1)
        
        self.log_message("GParted closed - expansion completed")
        
        # Step 3: Unmount
        self._update_progress(90, "Unmounting image...")
        self._unmount_image(nbd_device)
        
        self._update_progress(100, "Expand operation completed")
    
    def _mount_image_for_editing(self, image_path):
        """Mount QCOW2 image using qemu-nbd for editing"""
        # Load nbd module
        try:
            subprocess.run(['sudo', 'modprobe', 'nbd', 'max_part=8'], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            self.log_message(f"Warning: Could not load nbd module: {e}", "WARNING")
        
        # Find available nbd device
        for i in range(16):
            nbd_device = f"/dev/nbd{i}"
            try:
                # Try to connect
                result = subprocess.run(['sudo', 'qemu-nbd', '--connect', nbd_device, image_path], 
                                      capture_output=True, check=True)
                
                # Wait for partitions to appear
                import time
                time.sleep(3)
                
                self.log_message(f"Image mounted on {nbd_device}")
                return nbd_device
                
            except subprocess.CalledProcessError:
                continue
        
        raise Exception("No available NBD devices for mounting")
    
    def _unmount_image(self, nbd_device):
        """Unmount QCOW2 image"""
        try:
            subprocess.run(['sudo', 'qemu-nbd', '--disconnect', nbd_device], 
                         check=True, capture_output=True)
            self.log_message(f"Image unmounted from {nbd_device}")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Warning: Error unmounting {nbd_device}: {e}", "WARNING")
    
    def _update_progress(self, percent, status):
        """Update progress from worker thread"""
        def update():
            self.progress_var.set(percent)
            self.progress_label.config(text=f"{percent:.1f}%")
        
        self.root.after(0, update)
        self.log_message(status)
    
    def stop_operation(self):
        """Stop the current operation"""
        if self.operation_running:
            self.stop_requested = True
            self.log_message("Stop requested by user", "WARNING")
    
    def _reset_ui_after_operation(self):
        """Reset UI after operation completes"""
        self.operation_running = False
        self.resize_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self.progress_label.config(text="0%")
    
    def log_message(self, message, level="INFO"):
        """Add message to log display"""
        def update_log():
            self.log_text.config(state=tk.NORMAL)
            
            # Format message with timestamp
            import datetime
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            formatted_message = f"[{timestamp}] {level}: {message}\n"
            
            self.log_text.insert(tk.END, formatted_message)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        
        self.root.after(0, update_log)
        
        # Also log to system logger if available
        if level == "ERROR":
            log_error(message)
        elif level == "WARNING":
            log_warning(message)
        else:
            log_info(message)
    
    def close_window(self):
        """Close the resizer window"""
        if self.operation_running:
            if messagebox.askyesno("Operation Running", 
                                 "An operation is currently running. Stop and close?"):
                self.stop_requested = True
                self.root.after(1000, self.root.destroy)
            return
        
        self.root.destroy()


def show_qcow2_resizer(parent=None):
    """Show the QCOW2 resizer dialog"""
    if parent:
        resizer_window = tk.Toplevel(parent)
    else:
        resizer_window = tk.Tk()
    
    app = QCOW2ResizerGUI(resizer_window)
    
    if parent:
        # Center on parent window
        resizer_window.transient(parent)
        resizer_window.grab_set()
        
        # Calculate position
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 300
        resizer_window.geometry(f"700x600+{x}+{y}")
    
    return app


if __name__ == "__main__":
    root = tk.Tk()
    app = QCOW2ResizerGUI(root)
    root.mainloop()