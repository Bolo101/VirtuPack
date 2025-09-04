#!/usr/bin/env python3
"""
QCOW2 Virtual Disk Resizer - Simplified GParted-Only Implementation
Handles resizing of QCOW2 virtual machine disk images using GParted for partition operations
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

class QCow2Resizer:
    """Core QCOW2 resize functionality with GParted-only approach"""
    
    @staticmethod
    def check_tools():
        """Check if required tools are available"""
        essential_tools = {
            'qemu-img': 'qemu-utils',
            'qemu-nbd': 'qemu-utils',
            'parted': 'parted',
            'gparted': 'gparted',
        }
        
        missing = []
        for tool, package in essential_tools.items():
            if not shutil.which(tool):
                missing.append(f"{tool} ({package})")
        
        return missing
    
    @staticmethod
    def parse_size(size_str):
        """Parse size string like '20G', '512M' to bytes"""
        if isinstance(size_str, (int, float)):
            return int(size_str)
        
        size_str = str(size_str).strip().upper()
        
        # Match pattern like "20G", "512M", "1.5T"
        match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT]?)B?$', size_str)
        if not match:
            raise ValueError(f"Invalid size format: {size_str}")
        
        number = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {'': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        return int(number * multipliers[unit])
    
    @staticmethod
    def format_size(bytes_val):
        """Format bytes to human readable"""
        if bytes_val == 0:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
    
    @staticmethod
    def get_image_info(image_path):
        """Get QCOW2 image information"""
        try:
            result = subprocess.run(
                ['qemu-img', 'info', '--output=json', image_path],
                capture_output=True, text=True, check=True, timeout=30
            )
            data = json.loads(result.stdout)
            
            return {
                'virtual_size': data.get('virtual-size', 0),
                'actual_size': data.get('actual-size', 0),
                'format': data.get('format', 'unknown'),
                'compressed': data.get('compressed', False)
            }
        except Exception as e:
            raise Exception(f"Failed to analyze image: {e}")
    
    @staticmethod
    def setup_nbd_device(image_path, progress_callback=None):
        """Setup NBD device for partition operations"""
        try:
            if progress_callback:
                progress_callback(5, "Setting up NBD device...")
            
            # Load nbd module
            subprocess.run(['modprobe', 'nbd'], check=False)
            
            # Find available NBD device
            nbd_device = None
            for i in range(16):  # Check nbd0 to nbd15
                device = f"/dev/nbd{i}"
                if os.path.exists(device):
                    # Check if device is free
                    try:
                        result = subprocess.run(
                            ['lsblk', device],
                            capture_output=True, text=True, timeout=5
                        )
                        # If lsblk shows no entries, device is free
                        if device not in result.stdout or len(result.stdout.strip().split('\n')) <= 1:
                            nbd_device = device
                            break
                    except:
                        nbd_device = device
                        break
            
            if not nbd_device:
                raise Exception("No available NBD device found")
            
            # Connect image to NBD device
            subprocess.run(
                ['qemu-nbd', '--connect', nbd_device, image_path],
                check=True, timeout=30
            )
            
            # Wait for device to be ready
            max_attempts = 10
            for attempt in range(max_attempts):
                time.sleep(1)
                subprocess.run(['partprobe', nbd_device], check=False)
                time.sleep(1)
                
                # Check if device is accessible
                try:
                    result = subprocess.run(['lsblk', nbd_device], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        break
                except:
                    pass
                
                if attempt == max_attempts - 1:
                    print(f"Warning: NBD device setup may be incomplete after {max_attempts} attempts")
            
            return nbd_device
            
        except Exception as e:
            raise Exception(f"Failed to setup NBD device: {e}")
    
    @staticmethod
    def cleanup_nbd_device(nbd_device):
        """Cleanup NBD device"""
        try:
            subprocess.run(['qemu-nbd', '--disconnect', nbd_device], 
                         check=False, timeout=10)
        except:
            pass
    
    @staticmethod
    def get_partition_layout(nbd_device):
        """Get partition layout information after GParted operations"""
        try:
            result = subprocess.run(
                ['parted', '-s', nbd_device, 'print'],
                capture_output=True, text=True, check=True, timeout=30
            )
            
            lines = result.stdout.split('\n')
            partitions = []
            disk_size_bytes = 0
            
            # Parse disk size from parted output
            for line in lines:
                if line.strip().startswith('Disk'):
                    # Extract disk size (e.g., "Disk /dev/nbd0: 21.5GB")
                    match = re.search(r':\s*(\d+(?:\.\d+)?)(GB|MB|TB)', line)
                    if match:
                        size_val = float(match.group(1))
                        unit = match.group(2)
                        multiplier = {'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                        disk_size_bytes = int(size_val * multiplier[unit])
            
            # Find last partition end
            last_partition_end_bytes = 0
            
            for line in lines:
                line = line.strip()
                if re.match(r'^\s*\d+\s+', line):  # Partition line
                    parts = line.split()
                    if len(parts) >= 3:
                        partition_num = int(parts[0])
                        start = parts[1]
                        end = parts[2]
                        
                        # Parse end position
                        match = re.match(r'(\d+(?:\.\d+)?)(GB|MB|TB)', end)
                        if match:
                            end_val = float(match.group(1))
                            unit = match.group(2)
                            multiplier = {'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                            end_bytes = int(end_val * multiplier[unit])
                            last_partition_end_bytes = max(last_partition_end_bytes, end_bytes)
                        
                        partitions.append({
                            'number': partition_num,
                            'start': start,
                            'end': end,
                            'size': parts[3] if len(parts) > 3 else 'unknown'
                        })
            
            # Calculate unallocated space
            unallocated_bytes = max(0, disk_size_bytes - last_partition_end_bytes)
            
            return {
                'partitions': partitions,
                'disk_size_bytes': disk_size_bytes,
                'last_partition_end_bytes': last_partition_end_bytes,
                'unallocated_bytes': unallocated_bytes
            }
            
        except Exception as e:
            raise Exception(f"Failed to analyze partition layout: {e}")
    
    @staticmethod
    def launch_gparted(nbd_device):
        """Launch GParted GUI for partition operations"""
        try:
            if not shutil.which('gparted'):
                raise Exception("GParted not available - install gparted package")
            
            print(f"Launching GParted for device: {nbd_device}")
            
            # Launch GParted with proper environment
            env = os.environ.copy()
            env['DISPLAY'] = env.get('DISPLAY', ':0')
            
            # Use privilege escalation if needed
            if os.geteuid() != 0:
                escalation_commands = [
                    ['pkexec', 'gparted', nbd_device],
                    ['gksudo', 'gparted', nbd_device],
                    ['sudo', 'gparted', nbd_device]
                ]
                
                for cmd in escalation_commands:
                    if shutil.which(cmd[0]):
                        try:
                            print(f"Using {cmd[0]} for privilege escalation")
                            subprocess.run(cmd, env=env, timeout=3600)
                            return True
                        except subprocess.TimeoutExpired:
                            raise Exception("GParted operation timed out (1 hour limit)")
                        except Exception as e:
                            print(f"Failed with {cmd[0]}: {e}")
                            continue
                
                print("Warning: No privilege escalation found, trying direct launch")
            
            # Direct launch
            subprocess.run(['gparted', nbd_device], env=env, timeout=3600)
            return True
            
        except subprocess.TimeoutExpired:
            raise Exception("GParted operation timed out (1 hour limit)")
        except Exception as e:
            raise Exception(f"Could not launch GParted: {e}")
    
    @staticmethod
    def resize_image(image_path, new_size_bytes, progress_callback=None):
        """Resize QCOW2 image to new size"""
        try:
            if progress_callback:
                progress_callback(85, "Resizing virtual disk...")
            
            # Execute resize
            result = subprocess.run(
                ['qemu-img', 'resize', image_path, str(new_size_bytes)],
                capture_output=True, text=True, check=True, timeout=600
            )
            
            if progress_callback:
                progress_callback(95, "Verifying resize...")
            
            # Verify resize
            new_info = QCow2Resizer.get_image_info(image_path)
            actual_size = new_info['virtual_size']
            
            if abs(actual_size - new_size_bytes) > 1024 * 1024:  # 1MB tolerance
                raise Exception(f"Resize verification failed: expected {new_size_bytes}, got {actual_size}")
            
            if progress_callback:
                progress_callback(100, "Completed")
            
            return new_info
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"qemu-img resize failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise Exception("Resize operation timed out")
    
    @staticmethod
    def create_backup(image_path):
        """Create backup of image"""
        backup_path = f"{image_path}.backup.{int(time.time())}"
        shutil.copy2(image_path, backup_path)
        return backup_path


class OptimalSizeDialog:
    """Dialog to help user choose optimal virtual disk size"""
    
    def __init__(self, parent, layout_info, current_virtual_size):
        self.parent = parent
        self.layout_info = layout_info
        self.current_virtual_size = current_virtual_size
        self.result = None
        
        # Create dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Optimize Virtual Disk Size")
        self.dialog.geometry("600x450")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center on parent
        self.dialog.geometry("+%d+%d" % (
            parent.winfo_rootx() + 50,
            parent.winfo_rooty() + 50
        ))
        
        self.setup_ui()
        
        # Wait for dialog completion
        self.dialog.wait_window()
    
    def setup_ui(self):
        """Setup dialog UI"""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title = ttk.Label(main_frame, text="Optimize Virtual Disk Size", 
                         font=("Arial", 12, "bold"))
        title.pack(pady=(0, 15))
        
        # Current status
        status_frame = ttk.LabelFrame(main_frame, text="Current Status", padding="10")
        status_frame.pack(fill="x", pady=(0, 15))
        
        current_info = f"Current Virtual Size: {QCow2Resizer.format_size(self.current_virtual_size)}\n"
        current_info += f"Used Space (last partition end): {QCow2Resizer.format_size(self.layout_info['last_partition_end_bytes'])}\n"
        current_info += f"Unallocated Space: {QCow2Resizer.format_size(self.layout_info['unallocated_bytes'])}"
        
        status_label = ttk.Label(status_frame, text=current_info, justify="left")
        status_label.pack()
        
        # Recommendations
        rec_frame = ttk.LabelFrame(main_frame, text="Optimization Options", padding="10")
        rec_frame.pack(fill="x", pady=(0, 15))
        
        self.choice = tk.StringVar(value="optimal")
        
        # Option 1: Optimal size (minimal waste)
        optimal_size = self.layout_info['last_partition_end_bytes'] + (100 * 1024 * 1024)  # +100MB buffer
        ttk.Radiobutton(rec_frame, text=f"Optimal: {QCow2Resizer.format_size(optimal_size)} (minimal waste)", 
                       variable=self.choice, value="optimal").pack(anchor="w", pady=2)
        
        # Option 2: Remove half unallocated
        if self.layout_info['unallocated_bytes'] > 200 * 1024 * 1024:  # More than 200MB unallocated
            half_removed = self.current_virtual_size - (self.layout_info['unallocated_bytes'] // 2)
            ttk.Radiobutton(rec_frame, text=f"Conservative: {QCow2Resizer.format_size(half_removed)} (remove half unallocated)", 
                           variable=self.choice, value="conservative").pack(anchor="w", pady=2)
        
        # Option 3: Keep current size
        ttk.Radiobutton(rec_frame, text=f"No change: {QCow2Resizer.format_size(self.current_virtual_size)} (keep current)", 
                       variable=self.choice, value="none").pack(anchor="w", pady=2)
        
        # Option 4: Custom size
        custom_frame = ttk.Frame(rec_frame)
        custom_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Radiobutton(custom_frame, text="Custom size:", 
                       variable=self.choice, value="custom").pack(side="left")
        
        self.custom_size = tk.StringVar(value="20G")
        custom_entry = ttk.Entry(custom_frame, textvariable=self.custom_size, width=10)
        custom_entry.pack(side="left", padx=(5, 5))
        
        ttk.Label(custom_frame, text="(e.g., 20G, 512M)").pack(side="left")
        
        # Warning
        if self.layout_info['unallocated_bytes'] > 1024 * 1024 * 1024:  # > 1GB waste
            warning_text = f"⚠️ Currently wasting {QCow2Resizer.format_size(self.layout_info['unallocated_bytes'])} of space"
            warning_label = ttk.Label(rec_frame, text=warning_text, foreground="orange")
            warning_label.pack(pady=(10, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(15, 0))
        
        ttk.Button(button_frame, text="Apply", command=self.apply).pack(side="right", padx=(5, 0))
        ttk.Button(button_frame, text="Skip Resize", command=self.skip).pack(side="right")
        
        # Explanation
        exp_frame = ttk.LabelFrame(main_frame, text="What This Does", padding="10")
        exp_frame.pack(fill="x", pady=(15, 0))
        
        explanation = ("After you modified partitions in GParted, this tool can shrink the virtual disk "
                      "to remove wasted unallocated space. This makes the VM image smaller and more efficient.\n\n"
                      "• Optimal: Shrinks to just fit your partitions plus small buffer\n"
                      "• Conservative: Removes only half the wasted space\n"
                      "• No change: Keeps current virtual disk size\n"
                      "• Custom: You specify the exact size")
        
        exp_label = ttk.Label(exp_frame, text=explanation, wraplength=550, justify="left")
        exp_label.pack()
    
    def apply(self):
        """Apply selected option"""
        choice = self.choice.get()
        
        try:
            if choice == "optimal":
                # Minimal size with 100MB buffer
                new_size = self.layout_info['last_partition_end_bytes'] + (100 * 1024 * 1024)
            elif choice == "conservative":
                # Remove half unallocated
                new_size = self.current_virtual_size - (self.layout_info['unallocated_bytes'] // 2)
            elif choice == "none":
                # No change
                self.result = None
                self.dialog.destroy()
                return
            elif choice == "custom":
                # Parse custom size
                new_size = QCow2Resizer.parse_size(self.custom_size.get())
            else:
                raise ValueError("Invalid choice")
            
            # Validate size
            min_size = self.layout_info['last_partition_end_bytes']
            if new_size < min_size:
                messagebox.showerror("Invalid Size", 
                    f"Size too small. Minimum required: {QCow2Resizer.format_size(min_size)}")
                return
            
            # Check if change is meaningful
            if abs(new_size - self.current_virtual_size) < 10 * 1024 * 1024:  # Less than 10MB
                messagebox.showwarning("Small Change", 
                    "Size change is less than 10MB. No resize needed.")
                self.result = None
                self.dialog.destroy()
                return
            
            self.result = new_size
            self.dialog.destroy()
            
        except ValueError as e:
            messagebox.showerror("Invalid Size", f"Error parsing size: {e}")
    
    def skip(self):
        """Skip resize"""
        self.result = None
        self.dialog.destroy()


class QCow2ResizerGUI:
    """Simplified GUI for QCOW2 resizing with GParted-only approach"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("QCOW2 Resizer - GParted Edition")
        self.root.geometry("650x550")
        
        self.image_path = tk.StringVar()
        self.image_info = None
        self.operation_active = False
        
        self.setup_ui()
        self.check_prerequisites()
        
        # Set up proper close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    
    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno("Operation in Progress", 
                                    "An operation is currently running. Stop and close?")
            if not result:
                return
        
        self.root.destroy()

    def setup_ui(self):
        """Setup user interface"""
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title = ttk.Label(main_frame, text="QCOW2 Resizer - Simplified", 
                        font=("Arial", 14, "bold"))
        title.pack(pady=(0, 20))
        
        # Description
        desc_text = ("This tool helps you resize QCOW2 virtual disk images using GParted.\n"
                    "1. Select your QCOW2 file\n"
                    "2. Click 'Resize with GParted' to launch the partition editor\n"
                    "3. Modify partitions as needed in GParted\n"
                    "4. Close GParted - tool will optimize the virtual disk size automatically")
        
        desc_label = ttk.Label(main_frame, text=desc_text, wraplength=600, justify="left")
        desc_label.pack(pady=(0, 20))
        
        # Prerequisites
        self.prereq_frame = ttk.LabelFrame(main_frame, text="Prerequisites", padding="10")
        self.prereq_frame.pack(fill="x", pady=(0, 15))
        
        self.prereq_label = ttk.Label(self.prereq_frame, text="Checking...")
        self.prereq_label.pack()
        
        # File selection
        file_frame = ttk.LabelFrame(main_frame, text="QCOW2 Image File", padding="10")
        file_frame.pack(fill="x", pady=(0, 15))
        
        path_frame = ttk.Frame(file_frame)
        path_frame.pack(fill="x")
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.image_path, width=50)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        ttk.Button(path_frame, text="Browse", command=self.browse_file).pack(side="right", padx=(0, 5))
        ttk.Button(path_frame, text="Analyze", command=self.analyze_image).pack(side="right")
        
        # Image info
        info_frame = ttk.LabelFrame(main_frame, text="Image Information", padding="10")
        info_frame.pack(fill="x", pady=(0, 15))
        
        self.info_text = tk.Text(info_frame, height=6, state="disabled", wrap="word")
        self.info_text.pack(fill="x")
        
        # Warnings
        warning_frame = ttk.LabelFrame(main_frame, text="Important Notes", padding="10")
        warning_frame.pack(fill="x", pady=(0, 15))
        
        warning_text = ("⚠️ REQUIREMENTS:\n"
                       "• Root privileges required\n"
                       "• Virtual machine must be completely shut down\n"
                       "• Backup recommended before shrinking operations\n\n"
                       "✓ SUPPORTS: All partition types and filesystems\n"
                       "✓ SAFE: Manual control over all operations")
        
        warning_label = ttk.Label(warning_frame, text=warning_text, justify="left")
        warning_label.pack()
        
        # Progress
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill="x", pady=(0, 15))
        
        self.progress = ttk.Progressbar(progress_frame, length=400)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.progress_label = ttk.Label(progress_frame, text="Ready")
        self.progress_label.pack(side="right")
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        
        self.resize_btn = ttk.Button(button_frame, text="Resize with GParted", 
                                   command=self.start_gparted_resize, state="disabled")
        self.resize_btn.pack(side="left", padx=(0, 10))
        
        ttk.Button(button_frame, text="Create Backup", command=self.create_backup).pack(side="left", padx=(0, 10))
        ttk.Button(button_frame, text="Close", command=self.close_window).pack(side="right")
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        missing = QCow2Resizer.check_tools()
        
        if missing:
            text = f"Missing required tools: {', '.join(missing)}"
            self.prereq_label.config(text=text, foreground="red")
            
            install_msg = "Required tools missing!\n\n"
            install_msg += "Ubuntu/Debian:\n"
            install_msg += "sudo apt install qemu-utils parted gparted\n\n"
            install_msg += "Fedora/RHEL:\n"
            install_msg += "sudo dnf install qemu-img parted gparted\n\n"
            install_msg += "Arch Linux:\n"
            install_msg += "sudo pacman -S qemu parted gparted"
            
            messagebox.showerror("Missing Tools", install_msg)
        else:
            self.prereq_label.config(text="All required tools available ✓", foreground="green")
    
    def browse_file(self):
        """Browse for QCOW2 file"""
        file_path = filedialog.askopenfilename(
            title="Select QCOW2 Image",
            filetypes=[("QCOW2 files", "*.qcow2"), ("All files", "*.*")]
        )
        if file_path:
            self.image_path.set(file_path)
            self.analyze_image()
    
    def analyze_image(self):
        """Analyze selected image"""
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("Warning", "Please select an image file")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("Error", "File does not exist")
            return
        
        try:
            self.image_info = QCow2Resizer.get_image_info(path)
            self.display_image_info()
            self.resize_btn.config(state="normal")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to analyze image: {e}")
    
    def display_image_info(self):
        """Display image information"""
        if not self.image_info:
            return
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        info = f"File: {os.path.basename(self.image_path.get())}\n"
        info += f"Format: {self.image_info['format']}\n"
        info += f"Virtual Size: {QCow2Resizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"Actual File Size: {QCow2Resizer.format_size(self.image_info['actual_size'])}\n"
        
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Disk Usage: {ratio*100:.1f}%\n"
        
        info += f"\nReady for GParted resize operation."
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    def create_backup(self):
        """Create backup of current image"""
        path = self.image_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("Warning", "Select a valid image file first")
            return
        
        try:
            backup_path = QCow2Resizer.create_backup(path)
            messagebox.showinfo("Backup Created", f"Backup saved as:\n{backup_path}")
        except Exception as e:
            messagebox.showerror("Backup Failed", f"Could not create backup: {e}")
    
    def start_gparted_resize(self):
        """Start GParted resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        
        # Confirmation
        msg = f"GParted Resize Operation\n\n"
        msg += f"File: {os.path.basename(path)}\n"
        msg += f"Current Size: {QCow2Resizer.format_size(self.image_info['virtual_size'])}\n\n"
        msg += "Process:\n"
        msg += "1. Tool will mount the image and launch GParted\n"
        msg += "2. Modify partitions as needed in GParted\n"
        msg += "3. Close GParted when finished\n"
        msg += "4. Tool will analyze changes and optimize virtual disk size\n\n"
        msg += "⚠️ Ensure VM is completely shut down!\n"
        msg += "⚠️ Root privileges required!\n\n"
        msg += "Continue?"
        
        if not messagebox.askyesno("Confirm GParted Resize", msg):
            return
        
        # Check root privileges
        if os.geteuid() != 0:
            messagebox.showerror("Permission Error", 
                "Root privileges required for this operation.\n"
                "Please run this application with sudo.")
            return
        
        # Start resize in thread
        self.operation_active = True
        self.resize_btn.config(state="disabled")
        
        thread = threading.Thread(target=self._gparted_resize_worker, args=(path,))
        thread.daemon = True
        thread.start()
    
    def _gparted_resize_worker(self, image_path):
        """Worker thread for GParted resize operation"""
        nbd_device = None
        
        try:
            # Setup NBD device
            self.update_progress(10, "Setting up device...")
            nbd_device = QCow2Resizer.setup_nbd_device(image_path, self.update_progress)
            
            # Get initial layout
            self.update_progress(20, "Analyzing current layout...")
            initial_layout = QCow2Resizer.get_partition_layout(nbd_device)
            
            # Launch GParted
            self.update_progress(30, "Launching GParted...")
            
            # Show GParted instructions
            instructions = (
                f"GParted is about to open for device: {nbd_device}\n\n"
                f"Instructions:\n"
                f"1. Resize, move, or modify partitions as needed\n"
                f"2. Apply all changes in GParted\n"
                f"3. Close GParted when finished\n"
                f"4. This tool will continue automatically\n\n"
                f"Current virtual disk: {QCow2Resizer.format_size(self.image_info['virtual_size'])}\n"
                f"Tip: You can shrink partitions to reduce the virtual disk size"
            )
            
            self.root.after(0, lambda: messagebox.showinfo("GParted Instructions", instructions))
            
            # Launch GParted and wait
            QCow2Resizer.launch_gparted(nbd_device)
            
            # Analyze new layout
            self.update_progress(60, "Analyzing partition changes...")
            new_layout = QCow2Resizer.get_partition_layout(nbd_device)
            
            # Cleanup NBD device before image operations
            QCow2Resizer.cleanup_nbd_device(nbd_device)
            nbd_device = None
            
            # Show optimization dialog
            self.update_progress(70, "Calculating optimal size...")
            
            def show_optimization_dialog():
                dialog = OptimalSizeDialog(self.root, new_layout, self.image_info['virtual_size'])
                return dialog.result
            
            optimal_size = self.root.after(0, show_optimization_dialog)
            
            # Wait for dialog result (this is a bit tricky with threading)
            # We need to use a different approach
            self.optimization_result = None
            self.root.after(0, self._show_optimization_dialog, new_layout)
            
            # Wait for result
            while self.optimization_result is None:
                time.sleep(0.1)
            
            optimal_size = self.optimization_result
            
            if optimal_size is not None:
                # Resize virtual disk
                self.update_progress(80, "Resizing virtual disk...")
                new_info = QCow2Resizer.resize_image(image_path, optimal_size, self.update_progress)
                
                # Update display
                self.image_info = new_info
                self.root.after(0, self.display_image_info)
                
                # Show success message
                success_msg = f"Resize completed successfully!\n\n"
                success_msg += f"New virtual size: {QCow2Resizer.format_size(new_info['virtual_size'])}\n"
                
                if optimal_size < self.image_info['virtual_size']:
                    saved = self.image_info['virtual_size'] - optimal_size
                    success_msg += f"Space saved: {QCow2Resizer.format_size(saved)}\n"
                
                success_msg += f"\nPartition changes applied successfully."
                
                self.root.after(0, lambda: messagebox.showinfo("Success", success_msg))
            else:
                # No resize requested
                self.root.after(0, lambda: messagebox.showinfo("Complete", 
                    "GParted operations completed.\nVirtual disk size unchanged."))
            
        except Exception as e:
            error_msg = f"Operation failed: {e}"
            self.log(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        finally:
            if nbd_device:
                QCow2Resizer.cleanup_nbd_device(nbd_device)
            self.root.after(0, self.reset_ui)
    
    def _show_optimization_dialog(self, layout_info):
        """Show optimization dialog in main thread"""
        dialog = OptimalSizeDialog(self.root, layout_info, self.image_info['virtual_size'])
        self.optimization_result = dialog.result
    
    def validate_inputs(self):
        """Validate user inputs"""
        path = self.image_path.get().strip()
        
        if not path:
            messagebox.showwarning("Warning", "Select an image file")
            return False
        
        if not os.path.exists(path):
            messagebox.showerror("Error", "File does not exist")
            return False
        
        if not self.image_info:
            messagebox.showwarning("Warning", "Analyze the image first")
            return False
        
        return True
    
    def update_progress(self, percent, status):
        """Update progress bar and status"""
        def update():
            self.progress['value'] = percent
            self.progress_label.config(text=status)
        
        self.root.after(0, update)
    
    def log(self, message):
        """Log message to console"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    def reset_ui(self):
        """Reset UI after operation"""
        self.operation_active = False
        self.resize_btn.config(state="normal")
        self.progress['value'] = 0
        self.progress_label.config(text="Ready")


def main():
    """Main entry point"""
    # Check tools
    missing = QCow2Resizer.check_tools()
    if missing:
        print(f"Error: Missing required tools: {', '.join(missing)}")
        print("\nInstall required packages:")
        print("Ubuntu/Debian: sudo apt install qemu-utils parted gparted")
        print("Fedora/RHEL: sudo dnf install qemu-img parted gparted") 
        print("Arch Linux: sudo pacman -S qemu parted gparted")
        sys.exit(1)
    
    # Check if running as root
    if os.geteuid() != 0:
        print("Warning: Not running as root. Some operations will require privilege escalation.")
        print("For best experience, run with: sudo python3 qcow2_resize_dialog.py")
        print()
    
    # Launch GUI
    root = tk.Tk()
    app = QCow2ResizerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()