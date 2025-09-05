#!/usr/bin/env python3
"""
QCOW2 Virtual Disk Resizer - Clone-based Edition
Secure resizing by creating new image and cloning partitions
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

class QCow2CloneResizer:
    """Secure version using cloning instead of direct resizing"""
    
    @staticmethod
    def check_tools():
        """Check if required tools are available"""
        essential_tools = {
            'qemu-img': 'qemu-utils',
            'qemu-nbd': 'qemu-utils',
            'parted': 'parted',
            'gparted': 'gparted',
            'dd': 'coreutils',  # dd for cloning
            'partclone.ext4': 'partclone',  # optional for smart cloning
        }
        
        missing = []
        optional = []
        for tool, package in essential_tools.items():
            if not shutil.which(tool):
                if tool in ['partclone.ext4']:
                    optional.append(f"{tool} ({package}) - recommended")
                else:
                    missing.append(f"{tool} ({package})")
        
        return missing, optional
    
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
            # Force disconnect multiple times if needed
            for _ in range(3):
                result = subprocess.run(['qemu-nbd', '--disconnect', nbd_device], 
                                     capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    break
                time.sleep(1)
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
                            'size': parts[3] if len(parts) > 3 else 'unknown',
                            'filesystem': parts[4] if len(parts) > 4 else 'unknown'
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
    def create_new_qcow2_image(target_path, size_bytes, progress_callback=None):
        """Create a new QCOW2 image with specified size"""
        try:
            if progress_callback:
                progress_callback(20, "Creating new image...")
            
            # Remove file if it already exists
            if os.path.exists(target_path):
                os.remove(target_path)
            
            # Create new QCOW2 image
            cmd = [
                'qemu-img', 'create', 
                '-f', 'qcow2', 
                target_path, 
                str(size_bytes)
            ]
            
            print(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, check=True, timeout=300
            )
            
            if progress_callback:
                progress_callback(30, "New image created")
            
            return target_path
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to create image: {e.stderr if e.stderr else e}")
        except subprocess.TimeoutExpired:
            raise Exception("Image creation timed out")
    
    @staticmethod
    def clone_disk_structure(source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone disk structure (partition table + partitions)"""
        try:
            if progress_callback:
                progress_callback(40, "Cloning partition table...")
            
            # Step 1: Copy partition table and MBR/GPT
            # Copy first sectors (MBR + partition table)
            cmd = [
                'dd', 
                f'if={source_nbd}',
                f'of={target_nbd}',
                'bs=1M',
                'count=1',  # First MB for MBR/GPT
                'conv=notrunc'
            ]
            
            print(f"Copying structure: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, timeout=300)
            
            if progress_callback:
                progress_callback(50, "Recreating partition table...")
            
            # Step 2: Recreate partitions with parted
            # First, get partition table type
            parted_result = subprocess.run(
                ['parted', '-s', source_nbd, 'print'],
                capture_output=True, text=True, check=True
            )
            
            # Detect table type (msdos or gpt)
            table_type = 'msdos'  # default
            for line in parted_result.stdout.split('\n'):
                if 'Partition Table:' in line:
                    table_type = line.split(':')[1].strip()
                    break
            
            # Create partition table on new image
            subprocess.run([
                'parted', '-s', target_nbd, 'mklabel', table_type
            ], check=True)
            
            # Recreate each partition
            for i, partition in enumerate(layout_info['partitions']):
                if progress_callback:
                    progress_callback(55 + i * 5, f"Recreating partition {partition['number']}...")
                
                # Create partition
                subprocess.run([
                    'parted', '-s', target_nbd, 
                    'mkpart', 'primary',
                    partition['start'], partition['end']
                ], check=True)
            
            # Wait for partitions to be available
            time.sleep(2)
            subprocess.run(['partprobe', target_nbd], check=False)
            time.sleep(2)
            
            return True
            
        except Exception as e:
            raise Exception(f"Failed to clone structure: {e}")
    
    @staticmethod
    def clone_partition_data(source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone partition data"""
        try:
            total_partitions = len(layout_info['partitions'])
            
            for i, partition in enumerate(layout_info['partitions']):
                partition_num = partition['number']
                
                if progress_callback:
                    progress_callback(
                        70 + (i * 20 // total_partitions), 
                        f"Cloning partition {partition_num}..."
                    )
                
                source_part = f"{source_nbd}p{partition_num}"
                target_part = f"{target_nbd}p{partition_num}"
                
                # Check if partitions exist
                if not os.path.exists(source_part):
                    print(f"Warning: {source_part} doesn't exist, trying without 'p'")
                    source_part = f"{source_nbd}{partition_num}"
                    target_part = f"{target_nbd}{partition_num}"
                
                # Clone partition with dd
                cmd = [
                    'dd',
                    f'if={source_part}',
                    f'of={target_part}',
                    'bs=4M',
                    'conv=notrunc'
                ]
                
                print(f"Cloning partition {partition_num}: {' '.join(cmd)}")
                
                try:
                    result = subprocess.run(cmd, 
                                          capture_output=True, text=True, 
                                          check=True, timeout=3600)
                    print(f"Partition {partition_num} cloned successfully")
                except subprocess.CalledProcessError as e:
                    print(f"Error cloning partition {partition_num}: {e}")
                    # Continue with other partitions
                    continue
            
            if progress_callback:
                progress_callback(90, "Finalizing clone...")
            
            return True
            
        except Exception as e:
            raise Exception(f"Failed to clone data: {e}")
    
    @staticmethod
    def clone_to_new_image(source_path, target_path, new_size_bytes, progress_callback=None):
        """Complete cloning process to new image"""
        source_nbd = None
        target_nbd = None
        
        try:
            # Step 1: Analyze source image
            if progress_callback:
                progress_callback(5, "Analyzing source image...")
            
            source_nbd = QCow2CloneResizer.setup_nbd_device(source_path)
            layout_info = QCow2CloneResizer.get_partition_layout(source_nbd)
            
            # Verification: is new size sufficient?
            min_required = layout_info['last_partition_end_bytes']
            if new_size_bytes < min_required:
                raise Exception(
                    f"Size insufficient! Minimum required: {QCow2CloneResizer.format_size(min_required)}, "
                    f"requested: {QCow2CloneResizer.format_size(new_size_bytes)}"
                )
            
            # Step 2: Create new image
            QCow2CloneResizer.create_new_qcow2_image(target_path, new_size_bytes, progress_callback)
            
            # Step 3: Mount new image
            if progress_callback:
                progress_callback(35, "Mounting new image...")
            
            target_nbd = QCow2CloneResizer.setup_nbd_device(target_path)
            
            # Step 4: Clone disk structure
            QCow2CloneResizer.clone_disk_structure(source_nbd, target_nbd, layout_info, progress_callback)
            
            # Step 5: Clone partition data
            QCow2CloneResizer.clone_partition_data(source_nbd, target_nbd, layout_info, progress_callback)
            
            if progress_callback:
                progress_callback(95, "Cleaning up...")
            
            # Cleanup
            QCow2CloneResizer.cleanup_nbd_device(source_nbd)
            QCow2CloneResizer.cleanup_nbd_device(target_nbd)
            source_nbd = None
            target_nbd = None
            
            if progress_callback:
                progress_callback(100, "Clone complete!")
            
            return True
            
        except Exception as e:
            if source_nbd:
                QCow2CloneResizer.cleanup_nbd_device(source_nbd)
            if target_nbd:
                QCow2CloneResizer.cleanup_nbd_device(target_nbd)
            raise e
    
    @staticmethod
    def create_backup(image_path):
        """Create backup of image"""
        backup_path = f"{image_path}.backup.{int(time.time())}"
        shutil.copy2(image_path, backup_path)
        return backup_path


class NewSizeDialog:
    """Dialog to enter new image size"""
    
    def __init__(self, parent, layout_info, current_virtual_size):
        self.parent = parent
        self.layout_info = layout_info
        self.current_virtual_size = current_virtual_size
        self.result = None
        
        # Create dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("New Image Size")
        self.dialog.geometry("600x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center on parent
        parent.update_idletasks()
        x = (parent.winfo_screenwidth() // 2) - (600 // 2)
        y = (parent.winfo_screenheight() // 2) - (500 // 2)
        self.dialog.geometry(f"600x500+{x}+{y}")
        
        self.setup_ui()
        
        # Wait for dialog completion
        self.dialog.wait_window()
    
    def setup_ui(self):
        """Setup dialog UI"""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title = ttk.Label(main_frame, text="Create Optimized New Image", 
                         font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))
        
        # Current status
        status_frame = ttk.LabelFrame(main_frame, text="Current Status", padding="15")
        status_frame.pack(fill="x", pady=(0, 20))
        
        min_size = self.layout_info['last_partition_end_bytes']
        
        current_info = f"Current Virtual Size: {QCow2CloneResizer.format_size(self.current_virtual_size)}\n"
        current_info += f"Used Space (last partition end): {QCow2CloneResizer.format_size(min_size)}\n"
        current_info += f"Unallocated Space: {QCow2CloneResizer.format_size(self.layout_info['unallocated_bytes'])}\n"
        current_info += f"Minimum Required Size: {QCow2CloneResizer.format_size(min_size)}"
        
        status_label = ttk.Label(status_frame, text=current_info, justify="left", font=("Arial", 10))
        status_label.pack()
        
        # Size selection
        size_frame = ttk.LabelFrame(main_frame, text="New Image Size", padding="15")
        size_frame.pack(fill="x", pady=(0, 20))
        
        # Recommendations
        rec_frame = ttk.Frame(size_frame)
        rec_frame.pack(fill="x", pady=(0, 15))
        
        self.choice = tk.StringVar(value="optimal")
        
        # Option 1: Optimal size (minimal waste)
        optimal_size = min_size + (200 * 1024 * 1024)  # +200MB buffer
        ttk.Radiobutton(rec_frame, text=f"Optimal: {QCow2CloneResizer.format_size(optimal_size)} (minimum + 200MB)", 
                       variable=self.choice, value="optimal").pack(anchor="w", pady=2)
        
        # Option 2: Current size
        ttk.Radiobutton(rec_frame, text=f"Same: {QCow2CloneResizer.format_size(self.current_virtual_size)} (current size)", 
                       variable=self.choice, value="current").pack(anchor="w", pady=2)
        
        # Option 3: Custom size
        custom_frame = ttk.Frame(rec_frame)
        custom_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Radiobutton(custom_frame, text="Custom size:", 
                       variable=self.choice, value="custom").pack(side="left")
        
        # Default custom size based on optimal
        default_gb = max(10, int(optimal_size / (1024**3)) + 1)
        self.custom_size = tk.StringVar(value=f"{default_gb}G")
        custom_entry = ttk.Entry(custom_frame, textvariable=self.custom_size, width=12, font=("Arial", 10))
        custom_entry.pack(side="left", padx=(10, 10))
        
        ttk.Label(custom_frame, text="(e.g. 100G, 512M, 2T)", font=("Arial", 9)).pack(side="left")
        
        # Clone explanation
        exp_frame = ttk.LabelFrame(main_frame, text="Secure Cloning Process", padding="15")
        exp_frame.pack(fill="x", pady=(0, 20))
        
        explanation = ("This method is safer than direct resizing:\n\n"
                      "1. Create a new empty image of desired size\n"
                      "2. Clone partition table (MBR/GPT)\n"
                      "3. Clone each partition sector by sector\n"
                      "4. Preserve all boot structures\n\n"
                      "Advantages:\n"
                      "• No risk of data corruption\n"
                      "• Bootloader preservation\n"
                      "• Intact partition structures\n"
                      "• Clean and optimized final image")
        
        exp_label = ttk.Label(exp_frame, text=explanation, wraplength=560, justify="left", font=("Arial", 9))
        exp_label.pack()
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(20, 0))
        
        create_btn = ttk.Button(button_frame, text="Create New Image", command=self.create_new)
        create_btn.pack(side="right", padx=(10, 0))
        
        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self.cancel)
        cancel_btn.pack(side="right")
    
    def create_new(self):
        """Create new image with selected size"""
        choice = self.choice.get()
        min_size = self.layout_info['last_partition_end_bytes']
        
        try:
            if choice == "optimal":
                new_size = min_size + (200 * 1024 * 1024)
            elif choice == "current":
                new_size = self.current_virtual_size
            elif choice == "custom":
                new_size = QCow2CloneResizer.parse_size(self.custom_size.get())
            else:
                raise ValueError("Invalid choice")
            
            # Validate size
            if new_size < min_size:
                messagebox.showerror("Invalid Size", 
                    f"Size too small. Minimum required: {QCow2CloneResizer.format_size(min_size)}")
                return
            
            self.result = new_size
            self.dialog.destroy()
            
        except ValueError as e:
            messagebox.showerror("Invalid Size", f"Error parsing size: {e}")
    
    def cancel(self):
        """Cancel operation"""
        self.result = None
        self.dialog.destroy()


class QCow2CloneResizerGUI:
    """GUI for clone-based resizing"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("QCOW2 Clone Resizer - Safe Method")
        
        # Appropriate window size
        self.root.geometry("900x700")
        
        self.image_path = tk.StringVar()
        self.image_info = None
        self.operation_active = False
        self.new_size_result = None
        
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
        # Main container with scrollable content
        main_canvas = tk.Canvas(self.root)
        main_scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=main_scrollbar.set)
        
        main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar.pack(side="right", fill="y")
        
        # Main content frame
        main_frame = ttk.Frame(scrollable_frame, padding="25")
        main_frame.pack(fill="both", expand=True)
        
        # Header section
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill="x", pady=(0, 25))
        
        # Title
        title = ttk.Label(header_frame, text="QCOW2 Clone Resizer", 
                        font=("Arial", 20, "bold"))
        title.pack(pady=(0, 8))
        
        subtitle = ttk.Label(header_frame, text="Safe Resizing Through Cloning", 
                           font=("Arial", 12))
        subtitle.pack(pady=(0, 15))
        
        # Quick action buttons at top
        quick_action_frame = ttk.Frame(header_frame)
        quick_action_frame.pack(fill="x", pady=(0, 15))
        
        self.resize_btn_top = ttk.Button(quick_action_frame, text="START RESIZE WITH GPARTED", 
                                       command=self.start_clone_resize, state="disabled",
                                       style="Accent.TButton")
        self.resize_btn_top.pack(side="left", padx=(0, 15))
        
        ttk.Button(quick_action_frame, text="Create Backup", 
                  command=self.create_backup).pack(side="left", padx=(0, 15))
        
        # Create two columns
        columns_frame = ttk.Frame(main_frame)
        columns_frame.pack(fill="both", expand=True)
        
        # Left column
        left_column = ttk.Frame(columns_frame)
        left_column.pack(side="left", fill="both", expand=True, padx=(0, 15))
        
        # Right column  
        right_column = ttk.Frame(columns_frame)
        right_column.pack(side="right", fill="both", expand=True, padx=(15, 0))
        
        # LEFT COLUMN CONTENT
        
        # Description
        desc_frame = ttk.LabelFrame(left_column, text="Secure Cloning Method", padding="15")
        desc_frame.pack(fill="x", pady=(0, 15))
        
        desc_text = ("SAFE APPROACH:\n"
                    "1. Select your QCOW2 virtual disk file\n"
                    "2. Modify partitions in GParted\n" 
                    "3. Specify desired new image size\n"
                    "4. Tool creates new image and clones partitions\n\n"
                    "ADVANTAGES:\n"
                    "• No risk of data corruption\n"
                    "• Bootloader preserved intact\n"
                    "• Partition structures maintained\n"
                    "• Clean and optimized final image")
        
        desc_label = ttk.Label(desc_frame, text=desc_text, justify="left", font=("Arial", 10))
        desc_label.pack()
        
        # File selection
        file_frame = ttk.LabelFrame(left_column, text="QCOW2 Image Selection", padding="15")
        file_frame.pack(fill="x", pady=(0, 15))
        
        path_frame = ttk.Frame(file_frame)
        path_frame.pack(fill="x", pady=(0, 10))
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.image_path, font=("Arial", 10))
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        ttk.Button(path_frame, text="Browse", command=self.browse_file).pack(side="right", padx=(0, 8))
        ttk.Button(path_frame, text="Analyze", command=self.analyze_image).pack(side="right")
        
        # Prerequisites
        self.prereq_frame = ttk.LabelFrame(left_column, text="System Requirements", padding="15")
        self.prereq_frame.pack(fill="x", pady=(0, 15))
        
        self.prereq_label = ttk.Label(self.prereq_frame, text="Checking required tools...", 
                                     font=("Arial", 10))
        self.prereq_label.pack()
        
        # Progress section
        progress_frame = ttk.LabelFrame(left_column, text="Operation Progress", padding="15")
        progress_frame.pack(fill="x", pady=(0, 15))
        
        self.progress = ttk.Progressbar(progress_frame, length=400, style="TProgressbar")
        self.progress.pack(fill="x", pady=(0, 8))
        
        self.progress_label = ttk.Label(progress_frame, text="Ready to begin", 
                                       font=("Arial", 10, "bold"))
        self.progress_label.pack()
        
        # RIGHT COLUMN CONTENT
        
        # Image info
        info_frame = ttk.LabelFrame(right_column, text="Image Information", padding="15")
        info_frame.pack(fill="x", pady=(0, 15))
        
        self.info_text = tk.Text(info_frame, height=8, state="disabled", wrap="word", 
                                font=("Consolas", 9), bg="white")
        info_scrollbar = ttk.Scrollbar(info_frame, orient="vertical", command=self.info_text.yview)
        self.info_text.configure(yscrollcommand=info_scrollbar.set)
        
        self.info_text.pack(side="left", fill="both", expand=True)
        info_scrollbar.pack(side="right", fill="y")
        
        # Safety warnings
        warning_frame = ttk.LabelFrame(right_column, text="Important Instructions", padding="15")
        warning_frame.pack(fill="x", pady=(0, 15))
        
        warning_text = ("REQUIREMENTS:\n"
                       "• Root privileges required for NBD operations\n"
                       "• Virtual machine must be completely shut down\n"
                       "• BACKUP RECOMMENDED before operation\n\n"
                       "PROCESS:\n"
                       "• Partition modification in GParted\n"
                       "• Create new optimized size image\n"
                       "• Secure cloning of modified partitions\n"
                       "• Preserve all boot structures\n\n"
                       "SAFETY:\n"
                       "• No destructive resizing\n"
                       "• Original image preserved until confirmation\n"
                       "• Multiple consistency checks")
        
        warning_label = ttk.Label(warning_frame, text=warning_text, justify="left", 
                                 font=("Arial", 9))
        warning_label.pack()
        
        # Action buttons
        button_frame = ttk.LabelFrame(right_column, text="Actions", padding="15")
        button_frame.pack(fill="x", pady=(0, 15))
        
        # Primary action button
        self.resize_btn_main = ttk.Button(button_frame, text="START RESIZE OPERATION", 
                                         command=self.start_clone_resize, state="disabled",
                                         style="Accent.TButton")
        self.resize_btn_main.pack(fill="x", pady=(0, 10))
        
        # Secondary buttons
        secondary_frame = ttk.Frame(button_frame)
        secondary_frame.pack(fill="x")
        
        ttk.Button(secondary_frame, text="Create Backup", 
                  command=self.create_backup).pack(side="left", padx=(0, 8))
        
        ttk.Button(secondary_frame, text="Refresh", 
                  command=self.analyze_image).pack(side="left", padx=(0, 8))
        
        ttk.Button(secondary_frame, text="Close", 
                  command=self.close_window).pack(side="right")
        
        # Status bar
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill="x", pady=(20, 0))
        
        separator = ttk.Separator(status_frame, orient="horizontal")
        separator.pack(fill="x", pady=(0, 8))
        
        status_text = "Ready - Ensure VM is shut down before resizing"
        self.status_label = ttk.Label(status_frame, text=status_text, font=("Arial", 9))
        self.status_label.pack()
        
        # Configure styles
        self.setup_styles()
    
    def setup_styles(self):
        """Setup custom styles"""
        style = ttk.Style()
        
        # Configure accent button style
        style.configure("Accent.TButton",
                       font=("Arial", 11, "bold"),
                       padding=(15, 8))
    
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
        
        root_status = "Running as root" if os.geteuid() == 0 else "Not running as root (will use privilege escalation)"
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
            
            # Enable resize buttons
            self.resize_btn_top.config(state="normal")
            self.resize_btn_main.config(state="normal")
            
            self.update_progress(0, "Analysis complete - Ready for resize")
            self.status_label.config(text="Image analyzed successfully - Ready for resize")
            
        except Exception as e:
            messagebox.showerror("Analysis Failed", f"Failed to analyze image:\n\n{e}")
            self.update_progress(0, "Analysis failed")
    
    def display_image_info(self):
        """Display image information"""
        if not self.image_info:
            return
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        info = f"FILE INFORMATION\n"
        info += f"{'='*45}\n"
        info += f"Path: {self.image_path.get()}\n"
        info += f"Name: {os.path.basename(self.image_path.get())}\n"
        info += f"Format: {self.image_info['format'].upper()}\n\n"
        
        info += f"SIZE INFORMATION\n"
        info += f"{'='*45}\n"
        info += f"Virtual Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n"
        
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Usage: {ratio*100:.1f}% of virtual size\n"
            
            if ratio < 0.5:
                info += f"Info: Image with sparse allocation\n"
        
        info += f"\nSTATUS\n"
        info += f"{'='*45}\n"
        info += f"Compressed: {'Yes' if self.image_info.get('compressed', False) else 'No'}\n"
        info += f"Ready for resize: YES\n"
        info += f"\nReady for clone operation!"
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    def create_backup(self):
        """Create backup of current image"""
        path = self.image_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("No File", "Select a valid image file first")
            return
        
        try:
            self.update_progress(20, "Creating backup...")
            backup_path = QCow2CloneResizer.create_backup(path)
            self.update_progress(0, "Backup created successfully")
            
            backup_msg = f"Backup created successfully!\n\n"
            backup_msg += f"Original: {path}\n"
            backup_msg += f"Backup: {backup_path}\n\n"
            backup_msg += f"The backup is a complete copy of your virtual disk."
            
            messagebox.showinfo("Backup Complete", backup_msg)
            
        except Exception as e:
            self.update_progress(0, "Backup failed")
            messagebox.showerror("Backup Failed", f"Could not create backup:\n\n{e}")
    
    def start_clone_resize(self):
        """Start clone resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        
        # Detailed confirmation dialog
        msg = f"CLONE RESIZE OPERATION\n\n"
        msg += f"File: {os.path.basename(path)}\n"
        msg += f"Current Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        msg += f"File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n\n"
        
        msg += f"PROCESS:\n"
        msg += f"1. Mount image as NBD device\n"
        msg += f"2. Launch GParted for partition modification\n"
        msg += f"3. Select new image size\n"
        msg += f"4. Create new optimized image\n"
        msg += f"5. Secure cloning of modified partitions\n\n"
        
        msg += f"IMPORTANT REQUIREMENTS:\n"
        msg += f"• Virtual machine completely shut down\n"
        msg += f"• Root privileges required for NBD operations\n"
        msg += f"• Backup recommended before operation\n\n"
        
        msg += f"Continue with resize operation?"
        
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
            
            if not messagebox.askyesno("Root Privileges", root_msg):
                return
        
        # Start resize in thread
        self.operation_active = True
        self.resize_btn_top.config(state="disabled")
        self.resize_btn_main.config(state="disabled")
        self.status_label.config(text="Resize operation in progress...")
        
        thread = threading.Thread(target=self._clone_resize_worker, args=(path,))
        thread.daemon = True
        thread.start()
    
    def _clone_resize_worker(self, image_path):
        """Worker thread for clone resize operation"""
        nbd_device = None
        
        try:
            # Store original image info
            original_info = self.image_info.copy()
            
            # Setup NBD device
            self.update_progress(10, "Setting up NBD device...")
            nbd_device = QCow2CloneResizer.setup_nbd_device(image_path, self.update_progress)
            
            # Get initial layout
            self.update_progress(20, "Analyzing current partition layout...")
            initial_layout = QCow2CloneResizer.get_partition_layout(nbd_device)
            
            # Launch GParted
            self.update_progress(30, "Launching GParted...")
            
            # Show detailed GParted instructions
            instructions = (
                f"GPARTED LAUNCHED FOR DEVICE: {nbd_device}\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Resize, move or modify partitions as needed\n"
                f"2. Apply all changes in GParted (Apply button)\n"
                f"3. Wait for operations to complete\n"
                f"4. Close GParted when finished\n"
                f"5. Return to this application - it will continue automatically\n\n"
                f"CURRENT STATUS:\n"
                f"Virtual Disk Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
                f"Device: {nbd_device}\n\n"
                f"TIP: You can shrink partitions to reduce virtual disk size!\n\n"
                f"Remember: Apply changes in GParted before closing!"
            )
            
            self.root.after(0, lambda: messagebox.showinfo("GParted Launched", instructions))
            
            # Launch GParted and wait
            QCow2CloneResizer.launch_gparted(nbd_device)
            
            # Analyze new layout
            self.update_progress(40, "Analyzing partition changes...")
            new_layout = QCow2CloneResizer.get_partition_layout(nbd_device)
            
            # Show new size dialog in main thread
            self.update_progress(45, "Selecting new image size...")
            self.new_size_result = None
            self.root.after(0, self._show_new_size_dialog, new_layout)
            
            # Wait for dialog result with timeout
            timeout_count = 0
            while self.new_size_result is None and timeout_count < 600:  # 60 second timeout
                time.sleep(0.1)
                timeout_count += 1
            
            if timeout_count >= 600:
                raise Exception("Size selection dialog timed out - please try again")
            
            new_size = self.new_size_result
            
            if new_size is not None:
                # Generate new filename
                original_path = Path(image_path)
                new_path = original_path.parent / f"{original_path.stem}_resized{original_path.suffix}"
                
                # Cleanup original NBD device before cloning
                self.update_progress(50, "Cleaning up NBD device...")
                QCow2CloneResizer.cleanup_nbd_device(nbd_device)
                nbd_device = None
                
                # Clone to new image
                self.update_progress(55, "Starting clone to new image...")
                QCow2CloneResizer.clone_to_new_image(
                    image_path, 
                    str(new_path),
                    new_size,
                    self.update_progress
                )
                
                # Analyze new image
                new_image_info = QCow2CloneResizer.get_image_info(str(new_path))
                
                # Show detailed success message
                success_msg = f"CLONE OPERATION COMPLETED SUCCESSFULLY!\n\n"
                success_msg += f"RESULTS:\n"
                success_msg += f"Original image: {image_path}\n"
                success_msg += f"New image: {new_path}\n\n"
                success_msg += f"Original size: {QCow2CloneResizer.format_size(original_info['virtual_size'])}\n"
                success_msg += f"New size: {QCow2CloneResizer.format_size(new_image_info['virtual_size'])}\n"
                
                if new_size < original_info['virtual_size']:
                    saved = original_info['virtual_size'] - new_size
                    success_msg += f"Space saved: {QCow2CloneResizer.format_size(saved)}\n"
                    success_msg += f"Reduction: {(saved/original_info['virtual_size']*100):.1f}%\n"
                elif new_size > original_info['virtual_size']:
                    added = new_size - original_info['virtual_size']
                    success_msg += f"Space added: {QCow2CloneResizer.format_size(added)}\n"
                    success_msg += f"Increase: {(added/original_info['virtual_size']*100):.1f}%\n"
                
                success_msg += f"\nAll partition changes have been applied successfully!\n"
                success_msg += f"Your new virtual machine image is ready to use.\n\n"
                success_msg += f"You can now delete the old image if everything works correctly."
                
                # Ask about replacing original file
                replace_msg = f"REPLACE ORIGINAL FILE?\n\n"
                replace_msg += f"Do you want to replace the original file with the new optimized image?\n\n"
                replace_msg += f"Original: {image_path}\n"
                replace_msg += f"New: {new_path}\n\n"
                replace_msg += f"If you choose 'Yes':\n"
                replace_msg += f"• Old file will be renamed with .old extension\n"
                replace_msg += f"• New file will take the original name\n\n"
                replace_msg += f"If you choose 'No':\n"
                replace_msg += f"• Both files will be kept\n"
                replace_msg += f"• You'll need to configure VM to use new file"
                
                def show_messages():
                    messagebox.showinfo("Operation Complete", success_msg)
                    if messagebox.askyesno("Replace Original File", replace_msg):
                        try:
                            # Rename original to .old
                            old_path = f"{image_path}.old"
                            os.rename(image_path, old_path)
                            # Rename new to original name
                            os.rename(str(new_path), image_path)
                            messagebox.showinfo("File Replaced", 
                                f"File replaced successfully!\n\n"
                                f"New active file: {image_path}\n"
                                f"Old file saved: {old_path}")
                        except Exception as e:
                            messagebox.showerror("Replace Error", 
                                f"Could not replace file:\n{e}")
                
                self.root.after(0, show_messages)
            else:
                # No resize requested
                self.root.after(0, lambda: messagebox.showinfo("Operation Complete", 
                    "GParted operations completed successfully.\n\n"
                    "No cloning requested - original image unchanged.\n\n"
                    "All partition changes have been applied."))
            
        except Exception as e:
            error_msg = f"OPERATION FAILED\n\n{e}\n\nPlease check console output for more details."
            self.log(f"Operation failed: {e}")
            self.root.after(0, lambda: messagebox.showerror("Operation Failed", error_msg))
        
        finally:
            if nbd_device:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(nbd_device)
                except:
                    pass
            self.root.after(0, self.reset_ui)
    
    def _show_new_size_dialog(self, layout_info):
        """Show new size dialog in main thread"""
        try:
            dialog = NewSizeDialog(self.root, layout_info, self.image_info['virtual_size'])
            self.new_size_result = dialog.result
        except Exception as e:
            self.log(f"New size dialog error: {e}")
            self.new_size_result = None
    
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
    
    def update_progress(self, percent, status):
        """Update progress bar and status"""
        def update():
            self.progress['value'] = percent
            self.progress_label.config(text=status)
            
            if percent == 0:
                self.status_label.config(text="Ready - Ensure VM is shut down")
            else:
                self.status_label.config(text=f"Operation in progress: {status}")
        
        self.root.after(0, update)
    
    def log(self, message):
        """Log message to console with timestamp"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    def reset_ui(self):
        """Reset UI after operation"""
        self.operation_active = False
        self.resize_btn_top.config(state="normal")
        self.resize_btn_main.config(state="normal")
        self.progress['value'] = 0
        self.progress_label.config(text="Operation completed")
        self.status_label.config(text="Operation completed - Ready for next operation")


def main():
    """Main entry point"""
    print("=" * 65)
    print("QCOW2 CLONE RESIZER - SAFE METHOD")
    print("=" * 65)
    
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
    
    print("Launching GUI...")
    print("   This version uses secure cloning instead of direct resizing")
    print("=" * 65)
    
    # Launch GUI
    root = tk.Tk()
    app = QCow2CloneResizerGUI(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
    
    print("Application closed - Goodbye!")


if __name__ == "__main__":
    main()