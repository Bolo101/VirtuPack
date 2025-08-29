#!/usr/bin/env python3
"""
Disk Mount Dialog Module
Provides dialog for selecting and mounting unmounted partitions
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
from log_handler import log_info, log_error, log_warning
from utils import get_disk_list, is_system_disk, get_directory_space, format_bytes


class DiskMountDialog:
    """Dialog for selecting and mounting unmounted partitions"""
    
    def __init__(self, parent):
        self.parent = parent
        self.result = None
        self.selected_partition = None
        self.mount_point = None
        
        # Create dialog window
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Select Partition for Output Storage")
        self.dialog.geometry("600x500")
        self.dialog.attributes("-fullscreen", True)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        
        # Set up dialog close protocol
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        
        self.create_widgets()
        self.refresh_unmounted_partitions()
    
    def create_widgets(self):
        """Create dialog widgets"""
        main_frame = ttk.Frame(self.dialog, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title and description
        title_label = ttk.Label(main_frame, text="Select Partition for VM Storage", 
                               font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        desc_label = ttk.Label(main_frame, 
                              text="Select an unmounted partition to mount and use for storing the converted VM. "
                                   "Only partitions with existing filesystems are shown.",
                              wraplength=600)
        desc_label.pack(pady=(0, 15))
        
        # Partition selection frame
        partition_frame = ttk.LabelFrame(main_frame, text="Available Unmounted Partitions", padding="10")
        partition_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Partition listbox with scrollbar
        list_frame = ttk.Frame(partition_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.partition_listbox = tk.Listbox(list_frame, font=("Consolas", 10), selectmode=tk.SINGLE)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.partition_listbox.yview)
        self.partition_listbox.configure(yscrollcommand=scrollbar.set)
        
        self.partition_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.partition_listbox.bind("<<ListboxSelect>>", self.on_partition_selected)
        # Add double-click binding for quick selection
        self.partition_listbox.bind("<Double-Button-1>", self.on_double_click)
        
        # Refresh button
        refresh_btn = ttk.Button(partition_frame, text="Refresh List", command=self.refresh_unmounted_partitions)
        refresh_btn.pack(pady=(10, 0))
        
        # Mount point configuration
        mount_frame = ttk.LabelFrame(main_frame, text="Mount Configuration", padding="10")
        mount_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(mount_frame, text="Mount Point:").pack(anchor=tk.W)
        self.mount_point_var = tk.StringVar(value="/mnt/vm_storage")
        mount_entry = ttk.Entry(mount_frame, textvariable=self.mount_point_var, width=60)
        mount_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Partition information display
        info_frame = ttk.LabelFrame(main_frame, text="Selected Partition Information", padding="10")
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.info_text = tk.Text(info_frame, height=5, wrap=tk.WORD, state=tk.DISABLED,
                                font=("Consolas", 9), bg="#f8f8f8")
        self.info_text.pack(fill=tk.X)
        
        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        # Cancel button
        cancel_btn = ttk.Button(button_frame, text="Close", command=self.cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Mount & Select button (initially disabled)
        self.mount_btn = ttk.Button(button_frame, text="Mount & Select", 
                                   command=self.mount_and_select, state=tk.DISABLED)
        self.mount_btn.pack(side=tk.RIGHT)
        
        # Browse for existing directory button
        browse_btn = ttk.Button(button_frame, text="Browse Existing...", 
                               command=self.browse_existing_directory)
        browse_btn.pack(side=tk.LEFT)
        
        # Store partition data for reference
        self.partition_data = []
    
    def on_double_click(self, event=None):
        """Handle double-click on partition list - quick mount"""
        if self.mount_btn['state'] == tk.NORMAL:
            self.mount_and_select()
    
    def browse_existing_directory(self):
        """Browse for existing directory instead of mounting a partition"""
        selected_dir = filedialog.askdirectory(
            parent=self.dialog,
            title="Select Existing Directory for VM Storage",
            initialdir="/mnt"
        )
        
        if selected_dir:
            self.result = selected_dir
            self.dialog.destroy()
    
    def get_unmounted_partitions(self):
        """Get list of unmounted partitions suitable for mounting"""
        try:
            # Get all disks
            all_disks = get_disk_list()
            unmounted_partitions = []
            
            # Get currently mounted devices
            mounted_devices = set()
            try:
                with open('/proc/mounts', 'r') as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 1 and parts[0].startswith('/dev/'):
                            # Extract device name
                            device = parts[0]
                            mounted_devices.add(device)
            except (IOError, OSError):
                log_warning("Could not read /proc/mounts")
            
            # For each disk, get its partitions and check which ones are unmounted
            for disk in all_disks:
                device_path = disk['device']
                
                # Skip if it's a system/active disk
                if disk.get('is_active', False) or is_system_disk(device_path):
                    continue
                
                try:
                    # Get partitions for this disk using lsblk
                    result = subprocess.run(['lsblk', '-n', '-o', 'NAME,FSTYPE,SIZE,LABEL', device_path], 
                                          capture_output=True, text=True, check=True)
                    
                    lines = result.stdout.strip().split('\n')
                    
                    for line in lines[1:]:  # Skip the first line (the disk itself)
                        if line.strip():
                            parts = line.strip().split(None, 3)  # Split into max 4 parts to preserve labels with spaces
                            if len(parts) >= 2:
                                partition_name = parts[0]
                                fstype = parts[1] if len(parts) > 1 and parts[1] != '' else None
                                size = parts[2] if len(parts) > 2 else 'Unknown'
                                label = parts[3] if len(parts) > 3 and parts[3] != '' else "No Label"
                                
                                # Remove any tree characters from lsblk output
                                partition_name = partition_name.lstrip('├─└│ ─')
                                partition_path = f"/dev/{partition_name}"
                                
                                # Check if this partition is mounted
                                if partition_path not in mounted_devices:
                                    # Check if it has a mountable filesystem
                                    mountable_fs = ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'ntfs', 'fat32', 'vfat', 'exfat']
                                    
                                    if fstype and fstype.lower() in mountable_fs:
                                        partition_info = {
                                            'device': partition_path,
                                            'size': size,
                                            'model': disk['model'],
                                            'label': label,
                                            'has_filesystem': fstype,
                                            'parent_disk': device_path,
                                            'parent_disk_label': disk.get('label', 'No Label'),
                                            'size_bytes': 0,  # Could calculate if needed
                                            'is_active': False
                                        }
                                        unmounted_partitions.append(partition_info)
                
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    log_warning(f"Could not get partition info for {device_path}: {str(e)}")
                    continue
            
            return unmounted_partitions
        
        except Exception as e:
            log_error(f"Error getting unmounted partitions: {str(e)}")
            return []
    
    def refresh_unmounted_partitions(self):
        """Refresh the list of unmounted partitions"""
        try:
            log_info("Refreshing unmounted partition list")
            
            self.partition_data = self.get_unmounted_partitions()
            self.partition_listbox.delete(0, tk.END)
            
            if self.partition_data:
                for partition in self.partition_data:
                    fs_info = f" [{partition['has_filesystem']}]" if partition['has_filesystem'] else " [No FS]"
                    display_text = f"{partition['device']} ({partition['size']}){fs_info}"
                    
                    if partition['label'] and partition['label'] not in ["No Label", "Unknown", ""]:
                        display_text += f" - {partition['label']}"
                    
                    # Add parent disk info for clarity
                    parent_disk = partition['parent_disk'].replace('/dev/', '')
                    display_text += f" (on {parent_disk})"
                    
                    self.partition_listbox.insert(tk.END, display_text)
                
                log_info(f"Found {len(self.partition_data)} unmounted partition(s)")
            else:
                self.partition_listbox.insert(tk.END, "No unmounted partitions with filesystems available")
                log_warning("No unmounted partitions found")
                
        except Exception as e:
            log_error(f"Error refreshing unmounted partitions: {str(e)}")
            self.partition_listbox.delete(0, tk.END)
            self.partition_listbox.insert(tk.END, "Error loading partition list")
    
    def on_partition_selected(self, event=None):
        """Handle partition selection"""
        selection = self.partition_listbox.curselection()
        if not selection or not self.partition_data:
            self.mount_btn.config(state=tk.DISABLED)
            self.selected_partition = None
            self.update_info_display("No partition selected")
            return
        
        index = selection[0]
        if index >= len(self.partition_data):
            return
        
        # Check if this is an error message or actual partition
        selected_text = self.partition_listbox.get(index)
        if selected_text in ["No unmounted partitions with filesystems available", "Error loading partition list"]:
            self.mount_btn.config(state=tk.DISABLED)
            self.selected_partition = None
            return
        
        self.selected_partition = self.partition_data[index]
        
        # Update info display
        info = f"Partition: {self.selected_partition['device']}\n"
        info += f"Size: {self.selected_partition['size']}\n"
        info += f"Filesystem: {self.selected_partition['has_filesystem']}\n"
        
        if self.selected_partition['label'] not in ["No Label", "Unknown", ""]:
            info += f"Label: {self.selected_partition['label']}\n"
        
        info += f"Parent Disk: {self.selected_partition['parent_disk']}\n"
        info += f"Disk Model: {self.selected_partition['model']}\n"
        info += f"Status: Ready to mount"
        
        self.mount_btn.config(state=tk.NORMAL)
        self.update_info_display(info)
    
    def update_info_display(self, text):
        """Update the information display"""
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(1.0, text)
        self.info_text.config(state=tk.DISABLED)
    
    def mount_and_select(self):
        """Mount the selected partition and return the mount point"""
        if not self.selected_partition:
            messagebox.showwarning("Warning", "Please select a partition first", parent=self.dialog)
            return
        
        device_path = self.selected_partition['device']  # This is now a partition like /dev/sdb1
        mount_point = self.mount_point_var.get().strip()
        
        if not mount_point:
            messagebox.showwarning("Warning", "Please specify a mount point", parent=self.dialog)
            return
        
        # Validate mount point
        if not mount_point.startswith('/'):
            messagebox.showwarning("Warning", "Mount point must be an absolute path (start with /)", 
                                 parent=self.dialog)
            return
        
        # Confirm mounting
        confirmation_text = f"Mount {device_path} to {mount_point}?\n\n"
        confirmation_text += f"Partition: {device_path}\n"
        confirmation_text += f"Parent Disk: {self.selected_partition['parent_disk']}\n"
        confirmation_text += f"Size: {self.selected_partition['size']}\n"
        confirmation_text += f"Filesystem: {self.selected_partition['has_filesystem']}\n"
        
        if self.selected_partition['label'] not in ["No Label", "Unknown", ""]:
            confirmation_text += f"Label: {self.selected_partition['label']}\n"
        
        confirmation_text += f"Mount point: {mount_point}\n\n"
        confirmation_text += f"This will create the mount point directory if it doesn't exist."
        
        if not messagebox.askyesno("Confirm Mount", confirmation_text, parent=self.dialog):
            return
        
        # Disable button during mounting
        self.mount_btn.config(state=tk.DISABLED, text="Mounting...")
        self.dialog.update()
        
        try:
            # Create mount point if it doesn't exist
            os.makedirs(mount_point, exist_ok=True)
            
            # Attempt to mount
            log_info(f"Mounting {device_path} to {mount_point}")
            
            # Try different mount commands based on filesystem
            fs_type = self.selected_partition['has_filesystem']
            mount_cmd = ['sudo', 'mount']
            
            if fs_type and fs_type.lower() == 'ntfs':
                mount_cmd.extend(['-t', 'ntfs-3g'])
            elif fs_type:
                mount_cmd.extend(['-t', fs_type])
            
            mount_cmd.extend([device_path, mount_point])
            
            result = subprocess.run(mount_cmd, capture_output=True, text=True, check=True, timeout=30)
            
            # Verify mount was successful
            if os.path.ismount(mount_point):
                log_info(f"Successfully mounted {device_path} to {mount_point}")
                
                # Check available space
                try:
                    space_info = get_directory_space(mount_point)
                    space_msg = f"Available space: {format_bytes(space_info['free'])}"
                    
                    success_text = f"Partition mounted successfully!\n\n"
                    success_text += f"Partition: {device_path}\n"
                    success_text += f"Mount point: {mount_point}\n"
                    success_text += f"Filesystem: {fs_type}\n"
                    success_text += f"{space_msg}\n\n"
                    success_text += f"You can now use this location for VM storage."
                    
                    messagebox.showinfo("Mount Successful", success_text, parent=self.dialog)
                except Exception:
                    messagebox.showinfo("Mount Successful", 
                                      f"Partition mounted successfully!\n\n"
                                      f"Partition: {device_path}\n"
                                      f"Mount point: {mount_point}",
                                      parent=self.dialog)
                
                self.mount_point = mount_point
                self.result = mount_point
                self.dialog.destroy()
                
            else:
                raise Exception("Mount command succeeded but mount point is not mounted")
        
        except subprocess.TimeoutExpired:
            error_msg = "Mount operation timed out. The partition may not be ready or may require manual intervention."
            log_error(error_msg)
            messagebox.showerror("Mount Failed", error_msg, parent=self.dialog)
        
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to mount partition: {e.stderr.strip() if e.stderr else str(e)}"
            log_error(error_msg)
            messagebox.showerror("Mount Failed", error_msg, parent=self.dialog)
        
        except PermissionError:
            error_msg = "Permission denied. You may need to run the application with sudo or check partition permissions."
            messagebox.showerror("Mount Failed", error_msg, parent=self.dialog)
        
        except Exception as e:
            error_msg = f"Unexpected error mounting partition: {str(e)}"
            log_error(error_msg)
            messagebox.showerror("Mount Failed", error_msg, parent=self.dialog)
        
        finally:
            # Re-enable button
            self.mount_btn.config(state=tk.NORMAL, text="Mount & Select")
    
    def cancel(self):
        """Cancel the dialog"""
        self.result = None
        self.dialog.destroy()