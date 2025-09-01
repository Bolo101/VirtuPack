#!/usr/bin/env python3
"""
QCOW2 Virtual Disk Resizer - Clean Implementation
Handles resizing of QCOW2 virtual machine disk images
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

class QCow2Resizer:
    """Core QCOW2 resize functionality"""
    
    @staticmethod
    def check_tools():
        """Check if required tools are available"""
        tools = {
            'qemu-img': 'qemu-utils',
            'qemu-nbd': 'qemu-utils',
        }
        
        missing = []
        for tool, package in tools.items():
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
    def resize_image(image_path, new_size_bytes, progress_callback=None):
        """Resize QCOW2 image to new size"""
        try:
            if progress_callback:
                progress_callback(10, "Starting resize...")
            
            # Execute resize
            result = subprocess.run(
                ['qemu-img', 'resize', image_path, str(new_size_bytes)],
                capture_output=True, text=True, check=True, timeout=600
            )
            
            if progress_callback:
                progress_callback(90, "Verifying resize...")
            
            # Verify resize
            new_info = QCow2Resizer.get_image_info(image_path)
            actual_size = new_info['virtual_size']
            
            if abs(actual_size - new_size_bytes) > 1024 * 1024:  # 1MB tolerance
                raise Exception(f"Resize verification failed: expected {new_size_bytes}, got {actual_size}")
            
            if progress_callback:
                progress_callback(100, "Resize completed")
            
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


class QCow2ResizerGUI:
    """GUI for QCOW2 resizing"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("QCOW2 Resizer")
        self.root.geometry("700x600")
        
        # Only set fullscreen if this is the main window (not a Toplevel)
        if isinstance(root, tk.Tk):
            self.root.attributes('-fullscreen', True)
        
        self.image_path = tk.StringVar()
        self.image_info = None
        self.operation_active = False
        self.stop_flag = False
        
        self.setup_ui()
        self.check_prerequisites()
        
        # Set up proper close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    

    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno("Operation in Progress", 
                                    "An operation is currently running.\n\n"
                                    "Are you sure you want to close?\n"
                                    "This will stop the current operation.",
                                    parent=self.root)
            if not result:
                return
            
            # Stop the operation
            self.stop_flag = True
        
        # Destroy the window
        self.root.destroy()

    def setup_ui(self):
        """Setup user interface"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title = ttk.Label(main_frame, text="QCOW2 Virtual Disk Resizer", 
                        font=("Arial", 14, "bold"))
        title.pack(pady=(0, 20))
        
        # Prerequisites
        self.prereq_frame = ttk.LabelFrame(main_frame, text="Prerequisites", padding="10")
        self.prereq_frame.pack(fill="x", pady=(0, 10))
        
        self.prereq_label = ttk.Label(self.prereq_frame, text="Checking...")
        self.prereq_label.pack()
        
        # File selection
        file_frame = ttk.LabelFrame(main_frame, text="Image File", padding="10")
        file_frame.pack(fill="x", pady=(0, 10))
        
        path_frame = ttk.Frame(file_frame)
        path_frame.pack(fill="x")
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.image_path, width=50)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        ttk.Button(path_frame, text="Browse", command=self.browse_file).pack(side="right", padx=(0, 5))
        ttk.Button(path_frame, text="Analyze", command=self.analyze_image).pack(side="right")
        
        # Image info
        info_frame = ttk.LabelFrame(main_frame, text="Image Information", padding="10")
        info_frame.pack(fill="x", pady=(0, 10))
        
        self.info_text = tk.Text(info_frame, height=6, state="disabled", wrap="word")
        self.info_text.pack(fill="x")
        
        # Resize controls
        resize_frame = ttk.LabelFrame(main_frame, text="Resize Configuration", padding="10")
        resize_frame.pack(fill="x", pady=(0, 10))
        
        # New size input
        size_frame = ttk.Frame(resize_frame)
        size_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(size_frame, text="New Size:").pack(side="left")
        
        self.new_size = tk.StringVar(value="20G")
        size_entry = ttk.Entry(size_frame, textvariable=self.new_size, width=15)
        size_entry.pack(side="right")
        
        ttk.Label(size_frame, text="(e.g., 20G, 512M, 1.5T)").pack(side="right", padx=(0, 10))
        
        # Target size display
        self.target_label = ttk.Label(resize_frame, text="", font=("Arial", 9, "bold"))
        self.target_label.pack(pady=(5, 0))
        
        # Warnings
        self.warning_label = ttk.Label(resize_frame, text="", foreground="red", wraplength=600)
        self.warning_label.pack(pady=(5, 0))
        
        # Bind size input changes
        self.new_size.trace('w', self.update_target_info)
        
        # Progress
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill="x", pady=(0, 10))
        
        self.progress = ttk.Progressbar(progress_frame, length=400)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.progress_label = ttk.Label(progress_frame, text="Ready")
        self.progress_label.pack(side="right")
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        
        self.resize_btn = ttk.Button(button_frame, text="Resize Image", command=self.start_resize)
        self.resize_btn.pack(side="left", padx=(0, 10))
        
        self.stop_btn = ttk.Button(button_frame, text="Stop", command=self.stop_operation, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 10))
        
        ttk.Button(button_frame, text="Close", command=self.close_window).pack(side="right")
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        missing = QCow2Resizer.check_tools()
        
        if missing:
            text = f"Missing: {', '.join(missing)}"
            self.prereq_label.config(text=text, foreground="red")
            self.resize_btn.config(state="disabled")
            
            messagebox.showerror("Missing Tools", 
                f"Required tools missing: {', '.join(missing)}\n\n"
                "Install with:\n"
                "Ubuntu/Debian: sudo apt install qemu-utils\n"
                "RHEL/CentOS: sudo yum install qemu-img\n"
                "Fedora: sudo dnf install qemu-img")
        else:
            self.prereq_label.config(text="All tools available", foreground="green")
    
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
            self.update_target_info()
            
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
        info += f"Actual Size: {QCow2Resizer.format_size(self.image_info['actual_size'])}\n"
        
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Space Usage: {ratio*100:.1f}%\n"
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    def update_target_info(self, *args):
        """Update target size information and warnings"""
        if not self.image_info:
            return
        
        try:
            new_size_str = self.new_size.get().strip()
            if not new_size_str:
                return
            
            new_size_bytes = QCow2Resizer.parse_size(new_size_str)
            current_size = self.image_info['virtual_size']
            
            # Update target display
            self.target_label.config(
                text=f"Target: {QCow2Resizer.format_size(new_size_bytes)}"
            )
            
            # Generate warnings
            warnings = []
            
            if new_size_bytes == current_size:
                warnings.append("No change - target equals current size")
            elif new_size_bytes < current_size:
                # Shrinking
                reduction = current_size - new_size_bytes
                warnings.append(f"SHRINKING by {QCow2Resizer.format_size(reduction)}")
                warnings.append("WARNING: Must shrink filesystem FIRST!")
                warnings.append("BACKUP required before shrinking!")
            else:
                # Expanding
                increase = new_size_bytes - current_size
                warnings.append(f"Expanding by {QCow2Resizer.format_size(increase)}")
                warnings.append("Safe operation - can extend partitions after")
            
            # Check disk space
            try:
                free_space = shutil.disk_usage(os.path.dirname(self.image_path.get())).free
                if new_size_bytes > current_size:
                    needed = new_size_bytes - current_size
                    if needed > free_space:
                        warnings.append(f"Insufficient space (need {QCow2Resizer.format_size(needed)})")
            except:
                pass
            
            self.warning_label.config(text="\n".join(warnings))
            
        except ValueError as e:
            self.target_label.config(text="Invalid size format")
            self.warning_label.config(text=str(e))
    
    def start_resize(self):
        """Start resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        new_size_str = self.new_size.get()
        
        try:
            new_size_bytes = QCow2Resizer.parse_size(new_size_str)
            current_size = self.image_info['virtual_size']
            
            # Confirmation
            operation = "expand" if new_size_bytes > current_size else "shrink"
            
            msg = f"Resize QCOW2 Image\n\n"
            msg += f"File: {os.path.basename(path)}\n"
            msg += f"Current: {QCow2Resizer.format_size(current_size)}\n"
            msg += f"Target: {QCow2Resizer.format_size(new_size_bytes)}\n"
            msg += f"Operation: {operation.upper()}\n\n"
            
            if operation == "shrink":
                msg += "WARNING: Shrinking can cause data loss!\n"
                msg += "Ensure filesystem is already shrunk!\n\n"
            
            msg += "Continue?"
            
            if not messagebox.askyesno("Confirm Resize", msg):
                return
            
            # Start resize in thread
            self.operation_active = True
            self.stop_flag = False
            self.resize_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            
            thread = threading.Thread(
                target=self._resize_worker,
                args=(path, new_size_bytes, operation)
            )
            thread.daemon = True
            thread.start()
            
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid size: {e}")
    
    def _resize_worker(self, image_path, new_size_bytes, operation):
        """Worker thread for resize operation"""
        backup_path = None
        
        try:
            # Create backup for shrink operations
            if operation == "shrink":
                self.update_progress(5, "Creating backup...")
                backup_path = QCow2Resizer.create_backup(image_path)
                self.log(f"Backup created: {backup_path}")
            
            if self.stop_flag:
                raise KeyboardInterrupt("Cancelled")
            
            # Perform resize
            self.update_progress(20, f"Resizing image...")
            new_info = QCow2Resizer.resize_image(image_path, new_size_bytes, self.update_progress)
            
            if self.stop_flag:
                raise KeyboardInterrupt("Cancelled")
            
            # Success
            self.log(f"Resize completed successfully!")
            self.log(f"New size: {QCow2Resizer.format_size(new_info['virtual_size'])}")
            
            # Update image info
            self.image_info = new_info
            self.root.after(0, self.display_image_info)
            
            # Remove backup on successful shrink
            if backup_path and os.path.exists(backup_path):
                os.remove(backup_path)
                self.log("Backup removed (operation successful)")
            
            # Show completion message
            self.root.after(0, lambda: messagebox.showinfo("Success", 
                f"Resize completed!\n\n"
                f"New size: {QCow2Resizer.format_size(new_info['virtual_size'])}\n\n"
                f"{'Use partition tools to extend partitions' if operation == 'expand' else 'Verify VM boots correctly'}"))
            
        except KeyboardInterrupt:
            self.log("Operation cancelled by user")
        except Exception as e:
            self.log(f"Error: {e}")
            
            # Restore backup on shrink failure
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.move(backup_path, image_path)
                    self.log("Image restored from backup")
                except Exception as restore_err:
                    self.log(f"CRITICAL: Could not restore backup: {restore_err}")
            
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        
        finally:
            self.root.after(0, self.reset_ui)
    
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
        
        try:
            new_size_bytes = QCow2Resizer.parse_size(self.new_size.get())
            current_size = self.image_info['virtual_size']
            
            if new_size_bytes <= 0:
                messagebox.showerror("Error", "Size must be positive")
                return False
            
            if abs(new_size_bytes - current_size) < 1024 * 1024:  # Less than 1MB
                messagebox.showwarning("Warning", "Size change too small (minimum 1MB)")
                return False
            
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid size format: {e}")
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
    
    def stop_operation(self):
        """Stop current operation"""
        self.stop_flag = True
        self.log("Stop requested")
    
    def reset_ui(self):
        """Reset UI after operation"""
        self.operation_active = False
        self.stop_flag = False
        self.resize_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress['value'] = 0
        self.progress_label.config(text="Ready")


def resize_qcow2_cli(image_path, new_size, create_backup=True):
    """Command-line resize function"""
    try:
        # Validate inputs
        if not os.path.exists(image_path):
            raise Exception(f"Image file not found: {image_path}")
        
        # Get current info
        current_info = QCow2Resizer.get_image_info(image_path)
        new_size_bytes = QCow2Resizer.parse_size(new_size)
        
        current_size = current_info['virtual_size']
        operation = "expand" if new_size_bytes > current_size else "shrink"
        
        print(f"Image: {image_path}")
        print(f"Current size: {QCow2Resizer.format_size(current_size)}")
        print(f"Target size: {QCow2Resizer.format_size(new_size_bytes)}")
        print(f"Operation: {operation}")
        
        if new_size_bytes == current_size:
            print("No change needed - sizes are equal")
            return True
        
        # Create backup for shrink operations
        backup_path = None
        if operation == "shrink" and create_backup:
            print("Creating backup...")
            backup_path = QCow2Resizer.create_backup(image_path)
            print(f"Backup: {backup_path}")
        
        # Perform resize
        print("Resizing...")
        new_info = QCow2Resizer.resize_image(image_path, new_size_bytes)
        
        print(f"Success! New size: {QCow2Resizer.format_size(new_info['virtual_size'])}")
        
        # Clean up backup on success
        if backup_path and os.path.exists(backup_path):
            os.remove(backup_path)
            print("Backup removed")
        
        if operation == "expand":
            print("\nNext: Use partition tools to extend partitions")
        else:
            print("\nNext: Verify VM boots correctly")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        
        # Restore backup on failure
        if backup_path and os.path.exists(backup_path):
            try:
                shutil.move(backup_path, image_path)
                print("Image restored from backup")
            except Exception as restore_err:
                print(f"CRITICAL: Could not restore backup: {restore_err}")
                print(f"Manual restore: mv {backup_path} {image_path}")
        
        return False


def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        # Command line mode
        import argparse
        
        parser = argparse.ArgumentParser(description="QCOW2 Virtual Disk Resizer")
        parser.add_argument("image", help="Path to QCOW2 image")
        parser.add_argument("--size", help="New size (e.g., 20G, 512M)")
        parser.add_argument("--info", action="store_true", help="Show image info only")
        parser.add_argument("--no-backup", action="store_true", help="Skip backup for shrink")
        parser.add_argument("--gui", action="store_true", help="Launch GUI")
        
        args = parser.parse_args()
        
        # Check tools
        missing = QCow2Resizer.check_tools()
        if missing:
            print(f"Error: Missing tools: {', '.join(missing)}")
            print("Install qemu-utils package")
            sys.exit(1)
        
        if args.info:
            # Show info only
            try:
                info = QCow2Resizer.get_image_info(args.image)
                print(f"Image: {args.image}")
                print(f"Format: {info['format']}")
                print(f"Virtual Size: {QCow2Resizer.format_size(info['virtual_size'])}")
                print(f"Actual Size: {QCow2Resizer.format_size(info['actual_size'])}")
                if info['virtual_size'] > 0:
                    ratio = info['actual_size'] / info['virtual_size']
                    print(f"Space Usage: {ratio*100:.1f}%")
            except Exception as e:
                print(f"Error: {e}")
                sys.exit(1)
        
        elif args.size:
            # Resize operation
            if not resize_qcow2_cli(args.image, args.size, not args.no_backup):
                sys.exit(1)
        
        elif args.gui:
            # Launch GUI
            root = tk.Tk()
            app = QCow2ResizerGUI(root)
            root.mainloop()
        
        else:
            parser.print_help()
    
    else:
        # Default to GUI
        root = tk.Tk()
        app = QCow2ResizerGUI(root)
        root.mainloop()


if __name__ == "__main__":
    main()