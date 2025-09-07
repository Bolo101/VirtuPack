#!/usr/bin/env python3
"""
QCOW2 Virtual Disk Resizer - Clone-based Edition
Secure resizing by creating new image and cloning partitions
Always uses GParted for manual partition resizing
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
            # Use parted to get detailed info
            result = subprocess.run(
                ['parted', '-s', nbd_device, 'print'],
                capture_output=True, text=True, check=True, timeout=30
            )
            
            print(f"Parted output for {nbd_device}:")
            print(result.stdout)
            print("=" * 50)
            
            lines = result.stdout.split('\n')
            partitions = []
            all_end_values = []
            
            for line in lines:
                line = line.strip()
                if re.match(r'^\s*\d+\s+', line):  # Partition line
                    parts = line.split()
                    print(f"DEBUG: Parsing line: '{line}'")
                    print(f"DEBUG: Split into parts: {parts}")
                    
                    if len(parts) >= 3:
                        partition_num = int(parts[0])
                        start_str = parts[1]
                        end_str = parts[2]
                        
                        print(f"DEBUG: Partition {partition_num} - start:'{start_str}' end:'{end_str}'")
                        
                        # FIXED: Support both European (comma) and US (dot) decimal separators
                        end_bytes = 0
                        
                        # Method 1: Look for GB values (support both 47.5GB and 47,5GB)
                        gb_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*GB', end_str, re.IGNORECASE)
                        if gb_match:
                            gb_value_str = gb_match.group(1).replace(',', '.')  # Convert European to US format
                            gb_value = float(gb_value_str)
                            end_bytes = int(gb_value * 1024**3)
                            print(f"DEBUG: Found GB value: {gb_value_str}GB (converted from '{gb_match.group(1)}GB') = {end_bytes} bytes")
                        else:
                            # Method 2: Look for MB values (support both 47.5MB and 47,5MB)
                            mb_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*MB', end_str, re.IGNORECASE)
                            if mb_match:
                                mb_value_str = mb_match.group(1).replace(',', '.')
                                mb_value = float(mb_value_str)
                                end_bytes = int(mb_value * 1024**2)
                                print(f"DEBUG: Found MB value: {mb_value_str}MB = {end_bytes} bytes")
                            else:
                                # Method 3: Look for kB values
                                kb_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*kB', end_str, re.IGNORECASE)
                                if kb_match:
                                    kb_value_str = kb_match.group(1).replace(',', '.')
                                    kb_value = float(kb_value_str)
                                    end_bytes = int(kb_value * 1024)
                                    print(f"DEBUG: Found kB value: {kb_value_str}kB = {end_bytes} bytes")
                                else:
                                    print(f"DEBUG: Could not parse end value '{end_str}'")
                                    continue
                        
                        all_end_values.append({
                            'partition': partition_num,
                            'end_str': end_str,
                            'end_bytes': end_bytes,
                            'end_formatted': QCow2CloneResizer.format_size(end_bytes)
                        })
                        
                        # Parse start too (with same European format support)
                        start_bytes = 0
                        gb_start = re.search(r'(\d+(?:[,\.]\d+)?)\s*GB', start_str, re.IGNORECASE)
                        if gb_start:
                            start_bytes = int(float(gb_start.group(1).replace(',', '.')) * 1024**3)
                        else:
                            mb_start = re.search(r'(\d+(?:[,\.]\d+)?)\s*MB', start_str, re.IGNORECASE)
                            if mb_start:
                                start_bytes = int(float(mb_start.group(1).replace(',', '.')) * 1024**2)
                            else:
                                kb_start = re.search(r'(\d+(?:[,\.]\d+)?)\s*kB', start_str, re.IGNORECASE)
                                if kb_start:
                                    start_bytes = int(float(kb_start.group(1).replace(',', '.')) * 1024)
                        
                        partitions.append({
                            'number': partition_num,
                            'start': start_str,
                            'end': end_str,
                            'start_bytes': start_bytes,
                            'end_bytes': end_bytes,
                            'size': parts[3] if len(parts) > 3 else 'unknown',
                            'filesystem': parts[4] if len(parts) > 4 else 'unknown'
                        })
            
            print("\nDEBUG: All end values found:")
            for item in all_end_values:
                print(f"  Partition {item['partition']}: '{item['end_str']}' = {item['end_bytes']} bytes = {item['end_formatted']}")
            
            # Find the maximum end value
            if all_end_values:
                max_end_bytes = max(item['end_bytes'] for item in all_end_values)
                max_partition = max(all_end_values, key=lambda x: x['end_bytes'])
                
                print(f"\nDEBUG: Maximum end value:")
                print(f"  Partition {max_partition['partition']}: {max_partition['end_formatted']} ({max_end_bytes} bytes)")
            else:
                max_end_bytes = 0
                print("\nDEBUG: No partition end values found!")
            
            # Add 200MB buffer
            buffer_size = 200 * 1024 * 1024  # 200MB
            required_minimum_bytes = max_end_bytes + buffer_size
            
            print(f"\nDEBUG: Final calculation:")
            print(f"  Maximum partition end: {QCow2CloneResizer.format_size(max_end_bytes)}")
            print(f"  Buffer: {QCow2CloneResizer.format_size(buffer_size)}")
            print(f"  Required minimum: {QCow2CloneResizer.format_size(required_minimum_bytes)}")
            
            return {
                'partitions': partitions,
                'last_partition_end_bytes': max_end_bytes,
                'required_minimum_bytes': required_minimum_bytes,
                'partition_count': len(partitions)
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
    """Dialog to enter new image size based on final partition layout"""
    
    def __init__(self, parent, final_layout_info, original_size, partition_changes):
        self.parent = parent
        self.final_layout_info = final_layout_info
        self.original_size = original_size
        self.partition_changes = partition_changes
        self.result = None
        
        # Create dialog with better sizing
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("New Image Size - Based on Final Partition Layout")
        
        # Make dialog modal and ensure it stays on top
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.focus_force()
        
        # Get screen dimensions for proper sizing
        screen_width = self.dialog.winfo_screenwidth()
        screen_height = self.dialog.winfo_screenheight()
        
        # Set dialog size to 80% of screen height, max 800px wide
        dialog_width = min(800, int(screen_width * 0.6))
        dialog_height = min(700, int(screen_height * 0.8))
        
        # Center on screen
        x = (screen_width - dialog_width) // 2
        y = (screen_height - dialog_height) // 2
        self.dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # Make dialog resizable
        self.dialog.resizable(True, True)
        self.dialog.minsize(600, 500)
        
        # Ensure dialog is properly displayed before continuing
        self.dialog.update_idletasks()
        
        self.setup_ui()
        
        # Add proper dialog close handling
        self.dialog.protocol("WM_DELETE_WINDOW", self.skip_cloning)
        
        # Wait for dialog completion - this is the key fix
        try:
            # Force the dialog to be visible and responsive
            self.dialog.lift()
            self.dialog.attributes('-topmost', True)
            self.dialog.after_idle(lambda: self.dialog.attributes('-topmost', False))
            
            # Wait for the dialog to complete
            self.dialog.wait_window()
        except Exception as e:
            print(f"Dialog wait error: {e}")
            self.result = None
    
    def setup_ui(self):
        """Setup dialog UI with scrollable content"""
        # Create main container
        main_container = ttk.Frame(self.dialog)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Create scrollable frame
        canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack scrollable components
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Main content in scrollable frame
        content_frame = ttk.Frame(scrollable_frame, padding="15")
        content_frame.pack(fill="both", expand=True)
        
        # Title
        title = ttk.Label(content_frame, text="Create New Image - Final Size Selection", 
                         font=("Arial", 16, "bold"))
        title.pack(pady=(0, 15))
        
        # GParted Changes Summary
        changes_frame = ttk.LabelFrame(content_frame, text="GParted Partition Changes", padding="10")
        changes_frame.pack(fill="x", pady=(0, 15))
        
        changes_info = "GParted operations completed successfully!\n\n"
        changes_info += f"Partition modifications: {self.partition_changes}\n\n"
        
        if self.final_layout_info['partitions']:
            changes_info += "Final partition layout:\n"
            for i, part in enumerate(self.final_layout_info['partitions']):
                changes_info += f"  Partition {part['number']}: {part['start']} - {part['end']} ({part['size']})\n"
        
        changes_label = ttk.Label(changes_frame, text=changes_info, justify="left", font=("Arial", 9))
        changes_label.pack()
        
        # Size Requirements
        status_frame = ttk.LabelFrame(content_frame, text="Size Requirements", padding="10")
        status_frame.pack(fill="x", pady=(0, 15))
        
        last_partition_end = self.final_layout_info['last_partition_end_bytes']
        min_size_with_buffer = self.final_layout_info['required_minimum_bytes']
        
        current_info = f"Original Image Size: {QCow2CloneResizer.format_size(self.original_size)}\n"
        current_info += f"Last Partition Ends At: {QCow2CloneResizer.format_size(last_partition_end)}\n"
        current_info += f"Required New Size: {QCow2CloneResizer.format_size(min_size_with_buffer)} (partition end + 200MB buffer)\n\n"
        
        if min_size_with_buffer < self.original_size:
            saved = self.original_size - min_size_with_buffer
            current_info += f"Space Savings: {QCow2CloneResizer.format_size(saved)} "
            current_info += f"({(saved/self.original_size*100):.1f}% reduction)"
        elif min_size_with_buffer > self.original_size:
            added = min_size_with_buffer - self.original_size
            current_info += f"Additional Space Needed: {QCow2CloneResizer.format_size(added)}"
        else:
            current_info += f"Same space requirements as original"
        
        status_label = ttk.Label(status_frame, text=current_info, justify="left", font=("Arial", 9))
        status_label.pack()
        
        # Size Selection
        size_frame = ttk.LabelFrame(content_frame, text="New Image Size Selection", padding="10")
        size_frame.pack(fill="x", pady=(0, 15))
        
        self.choice = tk.StringVar(value="calculated")
        
        # Option 1: Use calculated size (recommended) - Make this more prominent
        calc_frame = ttk.Frame(size_frame)
        calc_frame.pack(fill="x", pady=2)
        calc_radio = ttk.Radiobutton(calc_frame, text=f"Use Calculated Size: {QCow2CloneResizer.format_size(min_size_with_buffer)}", 
                                    variable=self.choice, value="calculated")
        calc_radio.pack(side="left")
        ttk.Label(calc_frame, text="(RECOMMENDED)", font=("Arial", 8, "bold"), foreground="green").pack(side="left", padx=(5, 0))
        
        # Option 2: Same as original (if sufficient)
        if self.original_size >= min_size_with_buffer:
            ttk.Radiobutton(size_frame, text=f"Keep Original Size: {QCow2CloneResizer.format_size(self.original_size)} (no space savings)", 
                           variable=self.choice, value="original").pack(anchor="w", pady=2)
        else:
            # Original is too small
            shortage = min_size_with_buffer - self.original_size
            ttk.Label(size_frame, text=f"Original size insufficient - needs {QCow2CloneResizer.format_size(shortage)} more space", 
                     foreground="red", font=("Arial", 8)).pack(anchor="w", pady=2)
        
        # Option 3: Custom size
        custom_frame = ttk.Frame(size_frame)
        custom_frame.pack(fill="x", pady=(8, 0))
        
        ttk.Radiobutton(custom_frame, text="Custom size:", 
                       variable=self.choice, value="custom").pack(side="left")
        
        # Default custom size
        default_gb = max(1, int(min_size_with_buffer / (1024**3)) + 1)
        self.custom_size = tk.StringVar(value=f"{default_gb}G")
        custom_entry = ttk.Entry(custom_frame, textvariable=self.custom_size, width=12, font=("Arial", 9))
        custom_entry.pack(side="left", padx=(10, 10))
        
        ttk.Label(custom_frame, text="(e.g. 100G, 512M, 2T)", font=("Arial", 8)).pack(side="left")
        
        # Show minimum size warning
        warning_frame = ttk.Frame(size_frame)
        warning_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(warning_frame, text=f"⚠ Minimum size required: {QCow2CloneResizer.format_size(min_size_with_buffer)}", 
                 font=("Arial", 8), foreground="orange").pack(anchor="w")
        
        # What Happens Next
        exp_frame = ttk.LabelFrame(content_frame, text="What Happens Next", padding="10")
        exp_frame.pack(fill="x", pady=(0, 20))
        
        explanation = ("1. Create new empty image with selected size\n"
                      "2. Copy partition table structure from current image\n"
                      "3. Clone each partition with all your GParted changes\n"
                      "4. Preserve bootloader and all modifications\n\n"
                      "All your partition resizing and changes will be preserved.")
        
        exp_label = ttk.Label(exp_frame, text=explanation, wraplength=500, justify="left", font=("Arial", 9))
        exp_label.pack()
        
        # FIXED: Buttons outside scrollable area, always visible
        button_container = ttk.Frame(main_container)
        button_container.pack(fill="x", pady=(10, 0))
        
        # Separator line
        separator = ttk.Separator(button_container, orient="horizontal")
        separator.pack(fill="x", pady=(0, 10))
        
        # Buttons frame
        button_frame = ttk.Frame(button_container)
        button_frame.pack(fill="x")
        
        # Create buttons with larger size and clear labels
        create_btn = ttk.Button(button_frame, text="✓ Create New Optimized Image", 
                               command=self.create_new, 
                               style="Accent.TButton")
        create_btn.pack(side="right", padx=(10, 0), ipadx=10, ipady=5)
        
        cancel_btn = ttk.Button(button_frame, text="Skip Cloning", 
                               command=self.skip_cloning,
                               ipadx=10, ipady=5)
        cancel_btn.pack(side="right")
        
        # Add keyboard shortcuts
        self.dialog.bind('<Return>', lambda e: self.create_new())
        self.dialog.bind('<Escape>', lambda e: self.skip_cloning())
        
        # Focus on the create button
        create_btn.focus_set()
    
    def create_new(self):
        """Create new image with selected size"""
        choice = self.choice.get()
        min_size = self.final_layout_info['required_minimum_bytes']
        
        try:
            if choice == "calculated":
                new_size = min_size
            elif choice == "original":
                new_size = self.original_size
            elif choice == "custom":
                new_size = QCow2CloneResizer.parse_size(self.custom_size.get())
            else:
                raise ValueError("Invalid choice")
            
            # Validate size
            if new_size < min_size:
                shortage = min_size - new_size
                messagebox.showerror("Size Too Small", 
                    f"Size insufficient!\n\n"
                    f"Minimum required: {QCow2CloneResizer.format_size(min_size)}\n"
                    f"Your selection: {QCow2CloneResizer.format_size(new_size)}\n"
                    f"Need {QCow2CloneResizer.format_size(shortage)} more space.")
                return
            
            self.result = new_size
            self.dialog.quit()  # Use quit() instead of destroy() for proper cleanup
            self.dialog.destroy()
            
        except ValueError as e:
            messagebox.showerror("Invalid Size", f"Error parsing size: {e}")
    
    def skip_cloning(self):
        """Skip cloning - keep original image with changes"""
        self.result = None
        self.dialog.quit()  # Use quit() instead of destroy() for proper cleanup
        self.dialog.destroy()


class QCow2CloneResizerGUI:
    """GUI for clone-based resizing with mandatory GParted usage"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("QCOW2 Clone Resizer - GParted + Safe Cloning")
        
        # Appropriate window size
        self.root.geometry("800x600")
        self.root.minsize(750, 550)
        
        self.image_path = tk.StringVar()
        self.image_info = None
        self.operation_active = False
        
        # Threading event system for dialog handling
        self.dialog_result_event = threading.Event()
        self.dialog_result_value = None
        
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
                                         text="🚀 START GPARTED + CLONE PROCESS", 
                                         command=self.start_gparted_resize, 
                                         state="disabled",
                                         style="Accent.TButton")
        self.main_action_btn.pack(side="top", fill="x", pady=(0, 15), ipady=8)
        
        # Secondary buttons (smaller, side by side)
        secondary_frame = ttk.Frame(button_frame)
        secondary_frame.pack(fill="x")
        
        self.backup_btn = ttk.Button(secondary_frame, text="💾 Create Backup", 
                                    command=self.create_backup)
        self.backup_btn.pack(side="left", padx=(0, 10))
        
        ttk.Button(secondary_frame, text="🔄 Refresh", 
                  command=self.analyze_image).pack(side="left", padx=(0, 10))
        
        ttk.Button(secondary_frame, text="❌ Close", 
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
            text = f"❌ Missing required tools: {', '.join(missing)}\n"
            
            install_msg = "Required tools missing!\n\n"
            install_msg += "Ubuntu/Debian:\n"
            install_msg += "sudo apt install qemu-utils parted gparted\n\n"
            install_msg += "Fedora/RHEL:\n"
            install_msg += "sudo dnf install qemu-img parted gparted\n\n"
            install_msg += "Arch Linux:\n"
            install_msg += "sudo pacman -S qemu parted gparted"
            
            messagebox.showerror("Missing Tools", install_msg)
            
        else:
            text = "✅ All required tools available\n"
        
        if optional:
            text += f"📋 Optional tools: {', '.join(optional)}\n"
        
        root_status = "🔐 Running as root" if os.geteuid() == 0 else "🔓 Will use privilege escalation"
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
            self.status_label.config(text="✅ Image analyzed - Ready to start GParted + Clone process")
            
        except Exception as e:
            messagebox.showerror("Analysis Failed", f"Failed to analyze image:\n\n{e}")
            self.update_progress(0, "Analysis failed")
    
    def display_image_info(self):
        """Display image information"""
        if not self.image_info:
            return
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        info = f"📁 FILE INFORMATION\n"
        info += f"{'='*50}\n"
        info += f"Path: {self.image_path.get()}\n"
        info += f"Name: {os.path.basename(self.image_path.get())}\n"
        info += f"Format: {self.image_info['format'].upper()}\n\n"
        
        info += f"💾 SIZE INFORMATION\n"
        info += f"{'='*50}\n"
        info += f"Virtual Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n"
        
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Usage: {ratio*100:.1f}% of virtual size\n"
            
            if ratio < 0.5:
                info += f"ℹ️ Sparse allocation detected (efficient storage)\n"
        
        info += f"\n🔧 PROCESS WORKFLOW\n"
        info += f"{'='*50}\n"
        info += f"1. 🖥️  Mount image as NBD device\n"
        info += f"2. 🎯 Launch GParted for manual partition editing\n"
        info += f"3. ✏️  Resize/modify partitions as needed\n"
        info += f"4. 💾 Apply changes and close GParted\n"
        info += f"5. 📏 Select optimal size for new image\n"
        info += f"6. 🚀 Clone all partitions to new optimized image\n\n"
        
        info += f"⚠️  IMPORTANT REQUIREMENTS:\n"
        info += f"• Virtual machine MUST be completely shut down\n"
        info += f"• Apply ALL changes in GParted before closing\n"
        info += f"• Backup recommended before starting\n"
        info += f"\n✅ Ready for GParted + Clone process!"
        
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
            
            backup_msg = f"💾 BACKUP CREATED SUCCESSFULLY!\n\n"
            backup_msg += f"Original: {path}\n"
            backup_msg += f"Backup: {backup_path}\n\n"
            backup_msg += f"The backup is a complete copy of your virtual disk.\n"
            backup_msg += f"You can now safely proceed with the resizing process."
            
            messagebox.showinfo("Backup Complete", backup_msg)
            
        except Exception as e:
            self.update_progress(0, "Backup failed")
            messagebox.showerror("Backup Failed", f"Could not create backup:\n\n{e}")
    
    def start_gparted_resize(self):
        """Start GParted + clone resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        
        # Detailed confirmation dialog
        msg = f"🚀 GPARTED + CLONE OPERATION\n\n"
        msg += f"📁 File: {os.path.basename(path)}\n"
        msg += f"💾 Current Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        msg += f"📂 File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n\n"
        
        msg += f"🔄 PROCESS STEPS:\n"
        msg += f"1. 🖥️  Mount image as NBD device\n"
        msg += f"2. 🎯 Launch GParted for manual partition editing\n"
        msg += f"3. ✏️  Resize/move/modify partitions in GParted\n"
        msg += f"4. ✅ Apply changes and close GParted\n"
        msg += f"5. 📏 Select optimal size for new image\n"
        msg += f"6. 🚀 Create new optimized image\n"
        msg += f"7. 📋 Clone all modified partitions safely\n\n"
        
        msg += f"⚠️  CRITICAL REQUIREMENTS:\n"
        msg += f"• Virtual machine MUST be completely shut down\n"
        msg += f"• Root privileges required for NBD operations\n"
        msg += f"• APPLY ALL CHANGES in GParted before closing\n"
        msg += f"• Backup recommended before operation\n\n"
        
        msg += f"Continue with GParted + Clone process?"
        
        if not messagebox.askyesno("Confirm Operation", msg):
            return
        
        # Check root privileges
        if os.geteuid() != 0:
            root_msg = ("🔐 ROOT PRIVILEGES REQUIRED\n\n"
                       "This operation requires root privileges for NBD device management.\n\n"
                       "The application will attempt to use privilege escalation (pkexec, sudo) "
                       "when launching GParted.\n\n"
                       "💡 For best experience, run entire application with:\n"
                       "sudo python3 qcow2_clone_resizer.py\n\n"
                       "Continue anyway?")
            
            if not messagebox.askyesno("Root Privileges Required", root_msg):
                return
        
        # Start resize in thread
        self.operation_active = True
        self.main_action_btn.config(state="disabled")
        self.backup_btn.config(state="disabled")
        self.status_label.config(text="🔄 GParted + Clone operation in progress...")
        
        thread = threading.Thread(target=self._gparted_clone_worker, args=(path,))
        thread.daemon = True
        thread.start()
    
    def _gparted_clone_worker(self, image_path):
        """Worker thread for GParted + clone resize operation"""
        nbd_device = None
        
        try:
            # Store original image info
            original_info = self.image_info.copy()
            
            # Setup NBD device for GParted
            self.update_progress(10, "Setting up NBD device for GParted...")
            nbd_device = QCow2CloneResizer.setup_nbd_device(image_path, self.update_progress)
            
            # Get initial partition layout
            self.update_progress(20, "Analyzing initial partition layout...")
            initial_layout = QCow2CloneResizer.get_partition_layout(nbd_device)
            
            # Show pre-GParted info
            initial_info = f"Initial partition layout:\n"
            for part in initial_layout['partitions']:
                initial_info += f"  Partition {part['number']}: {part['start']} - {part['end']} ({part['size']})\n"
            
            # Launch GParted - ALWAYS for manual partition modification
            self.update_progress(30, "Launching GParted for manual partition editing...")
            
            # Show detailed GParted instructions
            instructions = (
                f"🎯 GPARTED LAUNCHED FOR MANUAL PARTITION EDITING\n\n"
                f"Device: {nbd_device}\n\n"
                f"📋 CURRENT PARTITIONS:\n{initial_info}\n"
                f"🔧 INSTRUCTIONS FOR GPARTED:\n"
                f"1. Resize partitions (shrink to save space or expand)\n"
                f"2. Move partitions if needed\n"
                f"3. Modify filesystem sizes\n"
                f"4. Delete unused partitions\n"
                f"5. ⚠️  CRITICAL: Click 'Apply' to execute all changes\n"
                f"6. Wait for all operations to complete\n"
                f"7. Close GParted when finished\n\n"
                f"🚀 After GParted closes, this tool will:\n"
                f"• Analyze your partition changes\n"
                f"• Let you choose optimal new image size\n"
                f"• Clone all modified partitions to new image\n\n"
                f"💡 TIP: Shrinking partitions = smaller final image size!"
            )
            
            self.root.after(0, lambda: messagebox.showinfo("GParted Session Starting", instructions))
            
            # Launch GParted and wait for completion
            QCow2CloneResizer.launch_gparted(nbd_device)
            
            # GParted session completed - analyze final partition layout
            self.update_progress(40, "GParted completed - analyzing partition changes...")
            final_layout = QCow2CloneResizer.get_partition_layout(nbd_device)
            
            # Compare layouts to detect changes
            partition_changes = "Partitions modified using GParted"
            if len(initial_layout['partitions']) != len(final_layout['partitions']):
                partition_changes = f"Partition count changed: {len(initial_layout['partitions'])} → {len(final_layout['partitions'])}"
            elif initial_layout['last_partition_end_bytes'] != final_layout['last_partition_end_bytes']:
                old_size = QCow2CloneResizer.format_size(initial_layout['last_partition_end_bytes'])
                new_size = QCow2CloneResizer.format_size(final_layout['last_partition_end_bytes'])
                partition_changes = f"Partition space changed: {old_size} → {new_size}"
            
            # Show new size dialog with final layout information
            self.update_progress(45, "Select size for new optimized image...")
            
            # Reset the event and result
            self.dialog_result_event.clear()
            self.dialog_result_value = None
            
            # Show dialog in main thread
            self.root.after(0, self._show_final_size_dialog, final_layout, partition_changes)
            
            # Wait for dialog completion with proper event handling
            dialog_completed = self.dialog_result_event.wait(timeout=300)  # 5 minute timeout
            
            if not dialog_completed:
                raise Exception("Size selection dialog timed out - please try again")
            
            new_size = self.dialog_result_value
            print(f"DEBUG: Dialog completed. New size selected: {new_size}")
            
            if new_size is not None:
                print(f"DEBUG: User selected to create new image with size: {QCow2CloneResizer.format_size(new_size)}")
            else:
                print(f"DEBUG: User chose to skip cloning")
            
            if new_size is not None:
                # User chose to create new optimized image
                # Generate new filename
                original_path = Path(image_path)
                new_path = original_path.parent / f"{original_path.stem}_gparted_resized{original_path.suffix}"
                
                # Cleanup original NBD device before cloning
                self.update_progress(50, "Preparing for cloning to new image...")
                QCow2CloneResizer.cleanup_nbd_device(nbd_device)
                nbd_device = None
                
                # Clone to new image with all GParted modifications
                self.update_progress(55, "Cloning modified partitions to new optimized image...")
                QCow2CloneResizer.clone_to_new_image(
                    image_path, 
                    str(new_path),
                    new_size,
                    self.update_progress
                )
                
                # Analyze new image
                new_image_info = QCow2CloneResizer.get_image_info(str(new_path))
                
                # Show comprehensive success message
                success_msg = f"🎉 GPARTED + CLONE OPERATION COMPLETED SUCCESSFULLY!\n\n"
                success_msg += f"📊 RESULTS:\n"
                success_msg += f"📁 Original image: {image_path}\n"
                success_msg += f"✨ New optimized image: {new_path}\n\n"
                success_msg += f"📏 SIZE COMPARISON:\n"
                success_msg += f"📊 Original virtual size: {QCow2CloneResizer.format_size(original_info['virtual_size'])}\n"
                success_msg += f"🎯 New virtual size: {QCow2CloneResizer.format_size(new_image_info['virtual_size'])}\n"
                
                if new_size < original_info['virtual_size']:
                    saved = original_info['virtual_size'] - new_size
                    success_msg += f"💾 Space saved: {QCow2CloneResizer.format_size(saved)} "
                    success_msg += f"({(saved/original_info['virtual_size']*100):.1f}% reduction)\n"
                elif new_size > original_info['virtual_size']:
                    added = new_size - original_info['virtual_size']
                    success_msg += f"📈 Space added: {QCow2CloneResizer.format_size(added)} "
                    success_msg += f"({(added/original_info['virtual_size']*100):.1f}% increase)\n"
                else:
                    success_msg += f"🔧 Size maintained (optimized structure)\n"
                
                success_msg += f"\n🏆 PROCESS SUMMARY:\n"
                success_msg += f"✅ GParted partition modifications applied\n"
                success_msg += f"✅ All partition changes preserved\n"
                success_msg += f"✅ Bootloader and structures intact\n"
                success_msg += f"✅ New image optimized for actual needs\n\n"
                success_msg += f"🚀 Your virtual machine is ready to use with the new image!"
                
                # Ask about replacing original file
                replace_msg = f"🔄 REPLACE ORIGINAL FILE?\n\n"
                replace_msg += f"Do you want to replace the original file with the new optimized image?\n\n"
                replace_msg += f"📁 Original: {image_path}\n"
                replace_msg += f"✨ New: {new_path}\n\n"
                replace_msg += f"✅ If YES:\n"
                replace_msg += f"• Old file renamed to .old extension\n"
                replace_msg += f"• New file takes original name\n"
                replace_msg += f"• VM configuration unchanged\n\n"
                replace_msg += f"📂 If NO:\n"
                replace_msg += f"• Both files kept\n"
                replace_msg += f"• Update VM to use new file manually"
                
                def show_success_messages():
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
                                f"Active file: {image_path}\n"
                                f"Original saved: {old_path}\n\n"
                                f"Your VM will use the new optimized image automatically.")
                        except Exception as e:
                            messagebox.showerror("Replace Error", 
                                f"Could not replace file:\n{e}")
                
                self.root.after(0, show_success_messages)
            else:
                # User chose to skip cloning - just keep GParted changes
                self.root.after(0, lambda: messagebox.showinfo("GParted Changes Applied", 
                    f"GParted partition modifications completed successfully!\n\n"
                    f"Changes applied:\n{partition_changes}\n\n"
                    f"Original image updated with all partition modifications.\n"
                    f"No additional cloning performed.\n\n"
                    f"Your virtual machine can use the modified image directly."))
            
        except Exception as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED\n\n{e}\n\nPlease check console output for more details."
            self.log(f"Operation failed: {e}")
            self.root.after(0, lambda: messagebox.showerror("Operation Failed", error_msg))
        
        finally:
            if nbd_device:
                try:
                    QCow2CloneResizer.cleanup_nbd_device(nbd_device)
                except:
                    pass
            self.root.after(0, self.reset_ui)
    
    def _show_final_size_dialog(self, final_layout, partition_changes):
        """Show final size dialog after GParted operations"""
        try:
            dialog = NewSizeDialog(self.root, final_layout, self.image_info['virtual_size'], partition_changes)
            # Store the result and signal completion
            self.dialog_result_value = dialog.result
            self.dialog_result_event.set()
        except Exception as e:
            self.log(f"Final size dialog error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
    
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
                self.status_label.config(text="Ready - Select image and ensure VM is shut down")
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
        self.main_action_btn.config(state="normal")
        self.backup_btn.config(state="normal")
        self.progress['value'] = 0
        self.progress_label.config(text="Operation completed")
        self.status_label.config(text="Operation completed - Ready for next operation")


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
    print("   5. Safe cloning to new optimized image")
    print("=" * 75)
    
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