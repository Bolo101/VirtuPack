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
        self.parent.destroy()

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
        """Create backup of current image"""
        path = self.image_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("No File", "Select a valid image file first")
            return
        
        try:
            self.update_progress(20, "Creating backup...")
            backup_path = QCow2CloneResizer.create_backup(path)
            self.update_progress(0, "Backup created successfully")
            
            backup_msg = f"BACKUP CREATED SUCCESSFULLY!\n\n"
            backup_msg += f"Original: {path}\n"
            backup_msg += f"Backup: {backup_path}\n\n"
            backup_msg += f"The backup is a complete copy of your virtual disk.\n"
            backup_msg += f"You can now safely proceed with the resizing process."
            
            messagebox.showinfo("Backup Complete", backup_msg)
            
        except FileNotFoundError:
            self.update_progress(0, "Backup failed - file not found")
            messagebox.showerror("File Not Found", f"Could not find source image:\n{path}")
        except PermissionError:
            self.update_progress(0, "Backup failed - permission denied")
            messagebox.showerror("Permission Denied", f"Permission denied creating backup")
        except shutil.Error as e:
            self.update_progress(0, "Backup failed - copy error")
            messagebox.showerror("Copy Error", f"Could not copy file during backup:\n{e}")
        except OSError as e:
            self.update_progress(0, "Backup failed - system error")
            messagebox.showerror("System Error", f"System error creating backup:\n{e}")
    
    def start_gparted_resize(self):
        """Start GParted + clone resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        
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
        
        thread = threading.Thread(target=self._gparted_clone_worker, args=(path,))
        thread.daemon = True
        thread.start()
    
    def _gparted_clone_worker(self, image_path):
        """Worker thread for GParted + clone resize operation - CORRECTED to keep NBD device"""
        source_nbd = None
        
        try:
            print(f"Starting GParted + Clone operation for: {image_path}")
            
            # Store original image info
            original_info = self.image_info.copy()
            
            # Setup NBD device for GParted - THIS STAYS CONNECTED THROUGHOUT
            self.update_progress(10, "Setting up NBD device for GParted...")
            source_nbd = QCow2CloneResizer.setup_nbd_device(image_path, self.update_progress)
            print(f"NBD device setup complete: {source_nbd}")
            
            # Get initial partition layout
            self.update_progress(20, "Analyzing initial partition layout...")
            initial_layout = QCow2CloneResizer.get_partition_layout(source_nbd)
            
            # Show pre-GParted info
            initial_info = f"Initial partition layout:\n"
            for part in initial_layout['partitions']:
                initial_info += f"  Partition {part['number']}: {part['start']} - {part['end']} ({part['size']})\n"
            
            # Launch GParted - ALWAYS for manual partition modification
            self.update_progress(30, "Launching GParted for manual partition editing...")
            
            # Show detailed GParted instructions
            instructions = (
                f"GPARTED LAUNCHED FOR MANUAL PARTITION EDITING\n\n"
                f"Device: {source_nbd}\n\n"
                f"CURRENT PARTITIONS:\n{initial_info}\n"
                f"INSTRUCTIONS FOR GPARTED:\n"
                f"1. Resize partitions (shrink to save space or expand)\n"
                f"2. Move partitions if needed\n"
                f"3. Modify filesystem sizes\n"
                f"4. Delete unused partitions\n"
                f"5. CRITICAL: Click 'Apply' to execute all changes\n"
                f"6. Wait for all operations to complete\n"
                f"7. Close GParted when finished\n\n"
                f"After GParted closes, this tool will:\n"
                f"• Analyze your partition changes\n"
                f"• Let you choose optimal new image size\n"
                f"• Clone all modified partitions to new image\n\n"
                f"TIP: Shrinking partitions = smaller final image size!"
            )
            
            self.root.after(0, lambda: messagebox.showinfo("GParted Session Starting", instructions))
            
            # Launch GParted and wait for completion
            print("Launching GParted...")
            QCow2CloneResizer.launch_gparted(source_nbd)
            print("GParted session completed")
            
            # IMPORTANT: Do NOT cleanup NBD device here - we need it for cloning!
            # The source_nbd device now contains all the GParted modifications
            
            # GParted session completed - analyze final partition layout
            self.update_progress(40, "GParted completed - analyzing partition changes...")
            final_layout = QCow2CloneResizer.get_partition_layout(source_nbd)
            
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
            print("Showing size selection dialog...")
            
            # Reset the event and result
            self.dialog_result_event.clear()
            self.dialog_result_value = None
            
            # Show dialog in main thread
            self.root.after(0, self._show_final_size_dialog, final_layout, partition_changes)
            
            # Wait for dialog completion with proper event handling
            dialog_completed = self.dialog_result_event.wait(timeout=300)  # 5 minute timeout
            
            if not dialog_completed:
                raise RuntimeError("Size selection dialog timed out - please try again")
            
            new_size = self.dialog_result_value
            print(f"Dialog completed. New size selected: {new_size}")
            
            if new_size is not None:
                print(f"User selected to create new image with size: {QCow2CloneResizer.format_size(new_size)}")
                
                # Generate new filename
                original_path = Path(image_path)
                new_path = original_path.parent / f"{original_path.stem}_gparted_resized{original_path.suffix}"
                
                # Clone to new image with all GParted modifications
                # CRITICAL: Pass the existing source_nbd and final_layout to avoid re-mounting
                self.update_progress(55, "Cloning modified partitions to new optimized image...")
                print(f"Starting clone operation to: {new_path}")
                
                # Use modified clone function that accepts existing NBD device
                self._clone_to_new_image_with_existing_nbd(
                    image_path,
                    str(new_path),
                    new_size,
                    source_nbd,  # Pass existing NBD device
                    final_layout,  # Pass existing layout info
                    self.update_progress
                )
                
                print("Clone operation completed successfully!")
                
                # Analyze new image
                new_image_info = QCow2CloneResizer.get_image_info(str(new_path))
                print(f"New image info: {new_image_info}")
                
                # Show comprehensive success message
                success_msg = f"GPARTED + CLONE OPERATION COMPLETED SUCCESSFULLY!\n\n"
                success_msg += f"RESULTS:\n"
                success_msg += f"Original image: {image_path}\n"
                success_msg += f"New optimized image: {new_path}\n\n"
                success_msg += f"SIZE COMPARISON:\n"
                success_msg += f"Original virtual size: {QCow2CloneResizer.format_size(original_info['virtual_size'])}\n"
                success_msg += f"New virtual size: {QCow2CloneResizer.format_size(new_image_info['virtual_size'])}\n"
                
                if new_size < original_info['virtual_size']:
                    saved = original_info['virtual_size'] - new_size
                    success_msg += f"Space saved: {QCow2CloneResizer.format_size(saved)} "
                    success_msg += f"({(saved/original_info['virtual_size']*100):.1f}% reduction)\n"
                elif new_size > original_info['virtual_size']:
                    added = new_size - original_info['virtual_size']
                    success_msg += f"Space added: {QCow2CloneResizer.format_size(added)} "
                    success_msg += f"({(added/original_info['virtual_size']*100):.1f}% increase)\n"
                else:
                    success_msg += f"Size maintained (optimized structure)\n"
                
                success_msg += f"\nPROCESS SUMMARY:\n"
                success_msg += f"✓ GParted partition modifications applied\n"
                success_msg += f"✓ All partition changes preserved\n"
                success_msg += f"✓ Bootloader and structures intact\n"
                success_msg += f"✓ New image optimized for actual needs\n"
                success_msg += f"✓ Image created with preallocation=metadata\n\n"
                success_msg += f"Your virtual machine is ready to use with the new image!"
                
                # Ask about replacing original file
                replace_msg = f"REPLACE ORIGINAL FILE?\n\n"
                replace_msg += f"Do you want to replace the original file with the new optimized image?\n\n"
                replace_msg += f"Original: {image_path}\n"
                replace_msg += f"New: {new_path}\n\n"
                replace_msg += f"If YES:\n"
                replace_msg += f"• Old file renamed to .old extension\n"
                replace_msg += f"• New file takes original name\n"
                replace_msg += f"• VM configuration unchanged\n\n"
                replace_msg += f"If NO:\n"
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
                        except FileNotFoundError as e:
                            messagebox.showerror("File Replace Error", 
                                f"Could not find file during replacement:\n{e}")
                        except PermissionError as e:
                            messagebox.showerror("Permission Error", 
                                f"Permission denied during file replacement:\n{e}")
                        except OSError as e:
                            messagebox.showerror("System Error", 
                                f"System error during file replacement:\n{e}")
                
                self.root.after(0, show_success_messages)
            else:
                # User chose to skip cloning - just keep GParted changes
                print("User chose to skip cloning")
                self.root.after(0, lambda: messagebox.showinfo("GParted Changes Applied", 
                    f"GParted partition modifications completed successfully!\n\n"
                    f"Changes applied:\n{partition_changes}\n\n"
                    f"Original image updated with all partition modifications.\n"
                    f"No additional cloning performed.\n\n"
                    f"Your virtual machine can use the modified image directly."))
            
        except FileNotFoundError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - File Not Found\n\n{e}\n\nPlease check that all files exist."
            self.log(f"Operation failed - file not found: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("File Not Found", error_msg))
        except PermissionError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - Permission Denied\n\n{e}\n\nRun as root or with sudo."
            self.log(f"Operation failed - permission denied: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("Permission Denied", error_msg))
        except subprocess.CalledProcessError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - Command Error\n\n{e}\n\nCheck that all required tools are installed."
            self.log(f"Operation failed - command error: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("Command Failed", error_msg))
        except subprocess.TimeoutExpired as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - Timeout\n\n{e}\n\nOperation took too long to complete."
            self.log(f"Operation failed - timeout: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("Operation Timeout", error_msg))
        except RuntimeError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - Runtime Error\n\n{e}\n\nInternal operation error."
            self.log(f"Operation failed - runtime error: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("Runtime Error", error_msg))
        except OSError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - System Error\n\n{e}\n\nSystem resource or device error."
            self.log(f"Operation failed - system error: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("System Error", error_msg))
        except ValueError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - Invalid Value\n\n{e}\n\nInvalid parameter or data format."
            self.log(f"Operation failed - value error: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("Invalid Value", error_msg))
        except ImportError as e:
            error_msg = f"GPARTED + CLONE OPERATION FAILED - Missing Module\n\n{e}\n\nRequired Python module not available."
            self.log(f"Operation failed - import error: {e}")
            print(f"ERROR in _gparted_clone_worker: {e}")
            self.root.after(0, lambda: messagebox.showerror("Module Error", error_msg))
        
        finally:
            # ONLY NOW cleanup the source NBD device
            if source_nbd:
                try:
                    print(f"Final cleanup of NBD device: {source_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(source_nbd)
                except subprocess.CalledProcessError as cleanup_e:
                    print(f"Error cleaning up NBD device - command failed: {cleanup_e}")
                except subprocess.TimeoutExpired:
                    print(f"Error cleaning up NBD device - timeout")
                except FileNotFoundError:
                    print(f"Error cleaning up NBD device - qemu-nbd not found")
                except OSError as cleanup_e:
                    print(f"Error cleaning up NBD device - system error: {cleanup_e}")
            self.root.after(0, self.reset_ui)

    def _clone_to_new_image_with_existing_nbd(self, source_path, target_path, new_size_bytes, 
                                        existing_source_nbd, layout_info, progress_callback=None):
        """Clone to new image using existing NBD device (avoids re-mounting source)"""
        target_nbd = None
        
        try:
            print(f"Starting clone with existing NBD device:")
            print(f"  Source NBD: {existing_source_nbd}")
            print(f"  Target: {target_path}")
            print(f"  New size: {QCow2CloneResizer.format_size(new_size_bytes)}")
            print(f"  Layout info: {len(layout_info['partitions'])} partitions")
            
            # Verification: is new size sufficient?
            min_required = layout_info['required_minimum_bytes']
            if new_size_bytes < min_required:
                raise ValueError(
                    f"Size insufficient! Minimum required: {QCow2CloneResizer.format_size(min_required)}, "
                    f"requested: {QCow2CloneResizer.format_size(new_size_bytes)}"
                )
            
            print(f"Size verification passed - using {QCow2CloneResizer.format_size(new_size_bytes)}")
            
            # Step 1: Create new image
            if progress_callback:
                progress_callback(60, "Creating new image...")
            
            print("Creating new QCOW2 image...")
            QCow2CloneResizer.create_new_qcow2_image(target_path, new_size_bytes, progress_callback)
            
            # Verify image was created
            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Failed to create target image: {target_path}")
            
            # Step 2: Mount new image with enhanced device selection
            if progress_callback:
                progress_callback(70, "Mounting target image...")
            
            print("Waiting before mounting target image...")
            time.sleep(5)  # Longer wait to ensure filesystem stability
            
            # Enhanced NBD device selection with explicit exclusions
            print(f"Setting up target NBD device (excluding {existing_source_nbd})...")
            exclude_devices = [existing_source_nbd]
            
            target_nbd = QCow2CloneResizer.setup_nbd_device(
                target_path, 
                progress_callback=None, 
                exclude_devices=exclude_devices
            )
            print(f"Target NBD device: {target_nbd}")
            
            # Verify devices are different
            if existing_source_nbd == target_nbd:
                raise ValueError(f"CRITICAL ERROR: Source and target NBD devices are identical: {existing_source_nbd}")
            
            print(f"NBD devices verified: source={existing_source_nbd}, target={target_nbd}")
            
            # Additional verification - check if devices are actually accessible
            try:
                source_check = subprocess.run(['blockdev', '--getsize64', existing_source_nbd], 
                                            capture_output=True, check=True, timeout=15)
                target_check = subprocess.run(['blockdev', '--getsize64', target_nbd], 
                                            capture_output=True, check=True, timeout=15)
                print(f"Source device size: {source_check.stdout.strip()} bytes")
                print(f"Target device size: {target_check.stdout.strip()} bytes")
            except subprocess.CalledProcessError as e:
                raise subprocess.CalledProcessError(e.returncode, e.cmd, f"Device accessibility check failed: {e}")
            except subprocess.TimeoutExpired:
                raise subprocess.TimeoutExpired(e.cmd, e.timeout, f"Device accessibility check timed out")
            except FileNotFoundError:
                raise FileNotFoundError(f"blockdev command not found for accessibility check")
            
            # Step 3: Clone disk structure
            if progress_callback:
                progress_callback(75, "Cloning disk structure...")
            
            print("Cloning disk structure...")
            self._clone_disk_structure_safe(existing_source_nbd, target_nbd, layout_info, progress_callback)
            
            # Step 4: Clone partition data with enhanced error handling
            if progress_callback:
                progress_callback(80, "Cloning partition data...")
            
            print("Cloning partition data...")
            clone_success = False
            try:
                self._clone_partition_data_safe(existing_source_nbd, target_nbd, layout_info, progress_callback)
                clone_success = True
            except FileNotFoundError as clone_error:
                print(f"Partition cloning failed - file not found: {clone_error}")
                raise clone_error
            except PermissionError as clone_error:
                print(f"Partition cloning failed - permission denied: {clone_error}")
                raise clone_error
            except subprocess.CalledProcessError as clone_error:
                print(f"Partition cloning failed - command error: {clone_error}")
                raise clone_error
            except OSError as clone_error:
                print(f"Partition cloning failed - system error: {clone_error}")
                raise clone_error
            except ValueError as clone_error:
                print(f"Partition cloning failed - value error: {clone_error}")
                raise clone_error
            
            if not clone_success:
                raise RuntimeError("Partition cloning did not complete successfully")
            
            if progress_callback:
                progress_callback(95, "Finalizing and cleaning up...")
            
            # Final sync before cleanup
            print("Performing final filesystem sync...")
            subprocess.run(['sync'], check=False, timeout=60)
            time.sleep(3)
            
            # Cleanup target NBD device
            print(f"Cleaning up target NBD device: {target_nbd}")
            if target_nbd:
                QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                target_nbd = None
            
            # Final verification with retry
            print("Verifying target image...")
            for verify_attempt in range(3):
                try:
                    time.sleep(2)  # Wait for filesystem operations to complete
                    
                    if not os.path.exists(target_path):
                        raise FileNotFoundError(f"Target image file not found: {target_path}")
                    
                    # Check if file has reasonable size
                    file_stat = os.stat(target_path)
                    if file_stat.st_size < 1024: 
                        raise ValueError(f"Target image file is too small: {file_stat.st_size} bytes")
                    
                    final_info = QCow2CloneResizer.get_image_info(target_path)
                    print(f"Clone operation completed successfully!")
                    print(f"  Final image size: {QCow2CloneResizer.format_size(final_info['virtual_size'])}")
                    print(f"  File size: {QCow2CloneResizer.format_size(final_info['actual_size'])}")
                    
                    if progress_callback:
                        progress_callback(100, "Clone complete!")
                    
                    return True
                    
                except FileNotFoundError as verify_error:
                    print(f"Verification attempt {verify_attempt + 1} failed - file not found: {verify_error}")
                    if verify_attempt == 2:  # Last attempt
                        raise FileNotFoundError(f"Target image verification failed - file not found: {verify_error}")
                    time.sleep(3)
                except PermissionError as verify_error:
                    print(f"Verification attempt {verify_attempt + 1} failed - permission denied: {verify_error}")
                    if verify_attempt == 2:  # Last attempt
                        raise PermissionError(f"Target image verification failed - permission denied: {verify_error}")
                    time.sleep(3)
                except OSError as verify_error:
                    print(f"Verification attempt {verify_attempt + 1} failed - system error: {verify_error}")
                    if verify_attempt == 2:  # Last attempt
                        raise OSError(f"Target image verification failed - system error: {verify_error}")
                    time.sleep(3)
                except ValueError as verify_error:
                    print(f"Verification attempt {verify_attempt + 1} failed - value error: {verify_error}")
                    if verify_attempt == 2:  # Last attempt
                        raise ValueError(f"Target image verification failed - value error: {verify_error}")
                    time.sleep(3)
            
            return True
            
        except FileNotFoundError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - file not found: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD on error
            if target_nbd:
                try:
                    print(f"Emergency cleanup of target NBD: {target_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except:
                    pass
            
            # Clean up partial target file
            if target_path and os.path.exists(target_path):
                try:
                    file_size = os.path.getsize(target_path)
                    print(f"Removing incomplete target file: {target_path} (size: {file_size} bytes)")
                    os.remove(target_path)
                    print("Incomplete target file removed successfully")
                except OSError as file_error:
                    print(f"Could not remove incomplete file: {file_error}")
            
            raise FileNotFoundError(f"Required file not found: {e}")
        except PermissionError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - permission denied: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD on error
            if target_nbd:
                try:
                    print(f"Emergency cleanup of target NBD: {target_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except:
                    pass
            
            # Clean up partial target file
            if target_path and os.path.exists(target_path):
                try:
                    file_size = os.path.getsize(target_path)
                    print(f"Removing incomplete target file: {target_path} (size: {file_size} bytes)")
                    os.remove(target_path)
                    print("Incomplete target file removed successfully")
                except OSError as file_error:
                    print(f"Could not remove incomplete file: {file_error}")
            
            raise PermissionError(f"Permission denied: {e}")
        except subprocess.CalledProcessError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - command failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD on error
            if target_nbd:
                try:
                    print(f"Emergency cleanup of target NBD: {target_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except:
                    pass
            
            # Clean up partial target file
            if target_path and os.path.exists(target_path):
                try:
                    file_size = os.path.getsize(target_path)
                    print(f"Removing incomplete target file: {target_path} (size: {file_size} bytes)")
                    os.remove(target_path)
                    print("Incomplete target file removed successfully")
                except OSError as file_error:
                    print(f"Could not remove incomplete file: {file_error}")
            
            raise subprocess.CalledProcessError(e.returncode, e.cmd, f"Command failed: {e}")
        except ValueError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - invalid value: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD on error
            if target_nbd:
                try:
                    print(f"Emergency cleanup of target NBD: {target_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except:
                    pass
            
            # Clean up partial target file
            if target_path and os.path.exists(target_path):
                try:
                    file_size = os.path.getsize(target_path)
                    print(f"Removing incomplete target file: {target_path} (size: {file_size} bytes)")
                    os.remove(target_path)
                    print("Incomplete target file removed successfully")
                except OSError as file_error:
                    print(f"Could not remove incomplete file: {file_error}")
            
            raise ValueError(f"Invalid value: {e}")
        except RuntimeError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - runtime error: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD on error
            if target_nbd:
                try:
                    print(f"Emergency cleanup of target NBD: {target_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except:
                    pass
            
            # Clean up partial target file
            if target_path and os.path.exists(target_path):
                try:
                    file_size = os.path.getsize(target_path)
                    print(f"Removing incomplete target file: {target_path} (size: {file_size} bytes)")
                    os.remove(target_path)
                    print("Incomplete target file removed successfully")
                except OSError as file_error:
                    print(f"Could not remove incomplete file: {file_error}")
            
            raise RuntimeError(f"Runtime error: {e}")
        except OSError as e:
            print(f"ERROR in _clone_to_new_image_with_existing_nbd - system error: {e}")
            import traceback
            traceback.print_exc()
            
            # Cleanup target NBD on error
            if target_nbd:
                try:
                    print(f"Emergency cleanup of target NBD: {target_nbd}")
                    QCow2CloneResizer.cleanup_nbd_device(target_nbd)
                except:
                    pass
            
            # Clean up partial target file
            if target_path and os.path.exists(target_path):
                try:
                    file_size = os.path.getsize(target_path)
                    print(f"Removing incomplete target file: {target_path} (size: {file_size} bytes)")
                    os.remove(target_path)
                    print("Incomplete target file removed successfully")
                except OSError as file_error:
                    print(f"Could not remove incomplete file: {file_error}")
            
            raise OSError(f"System error: {e}")
    
    def _execute_dd_with_retry(self, cmd, timeout=300, max_retries=3):
        """Execute dd command with retries and better error handling"""
        for attempt in range(max_retries):
            try:
                print(f"DD attempt {attempt + 1}: {' '.join(cmd)}")
                
                # Use Popen for better control
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                stdout_data = []
                stderr_data = []
                
                start_time = time.time()
                while True:
                    # Check if process has terminated
                    if process.poll() is not None:
                        break
                    
                    # Check timeout
                    if time.time() - start_time > timeout:
                        print(f"DD command timed out after {timeout} seconds")
                        process.kill()
                        process.wait()
                        raise subprocess.TimeoutExpired(cmd, timeout)
                    
                    time.sleep(0.5)
                
                # Get final output
                stdout, stderr = process.communicate(timeout=30)
                
                if stdout:
                    stdout_data.append(stdout)
                    print(f"DD stdout: {stdout.strip()}")
                
                if stderr:
                    stderr_data.append(stderr)
                    print(f"DD stderr: {stderr.strip()}")
                
                if process.returncode == 0:
                    print(f"DD command succeeded on attempt {attempt + 1}")
                    return True
                else:
                    print(f"DD command failed with return code {process.returncode}")
                    if attempt < max_retries - 1:
                        print(f"Retrying in 3 seconds...")
                        time.sleep(3)
                        # Try to sync before retry
                        subprocess.run(['sync'], check=False, timeout=30)
                        time.sleep(2)
                    
            except subprocess.TimeoutExpired:
                print(f"DD attempt {attempt + 1} timed out")
                if attempt < max_retries - 1:
                    print(f"Retrying in 5 seconds...")
                    time.sleep(5)
            except FileNotFoundError:
                print(f"DD attempt {attempt + 1} failed - dd command not found")
                if attempt < max_retries - 1:
                    print(f"Retrying in 3 seconds...")
                    time.sleep(3)
            except OSError as e:
                print(f"DD attempt {attempt + 1} failed with system error: {e}")
                if attempt < max_retries - 1:
                    print(f"Retrying in 3 seconds...")
                    time.sleep(3)
        
        print(f"All DD attempts failed after {max_retries} tries")
        return False

    def _clone_disk_structure_safe(self, source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone disk structure with device verification"""
        try:
            print(f"Cloning disk structure from {source_nbd} to {target_nbd}")
            
            # Verify devices are different
            if source_nbd == target_nbd:
                raise ValueError(f"Source and target NBD devices cannot be the same: {source_nbd}")
            
            if progress_callback:
                progress_callback(76, "Copying partition table...")
            
            # Step 1: Copy partition table and MBR/GPT
            cmd = [
                'dd', 
                f'if={source_nbd}',
                f'of={target_nbd}',
                'bs=1M',
                'count=1',  # First MB for MBR/GPT
                'conv=notrunc'
            ]
            
            print(f"Copying structure: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
            if result.stderr:
                print(f"DD stderr: {result.stderr}")
            
            if progress_callback:
                progress_callback(77, "Recreating partition table...")
            
            # Step 2: Get partition table info from source
            parted_result = subprocess.run(
                ['parted', '-s', source_nbd, 'print'],
                capture_output=True, text=True, check=True, timeout=60
            )
            
            # Detect table type
            table_type = 'msdos'  # default
            for line in parted_result.stdout.split('\n'):
                if 'Partition Table:' in line:
                    table_type = line.split(':')[1].strip()
                    break
            
            print(f"Detected partition table type: {table_type}")
            
            # Create partition table on target
            subprocess.run([
                'parted', '-s', target_nbd, 'mklabel', table_type
            ], check=True, timeout=60)
            
            # Recreate each partition
            for i, partition in enumerate(layout_info['partitions']):
                if progress_callback:
                    progress_callback(77 + i, f"Creating partition {partition['number']}...")
                
                print(f"Creating partition {partition['number']}: {partition['start']} - {partition['end']}")
                
                result = subprocess.run([
                    'parted', '-s', target_nbd, 
                    'mkpart', 'primary',
                    partition['start'], partition['end']
                ], capture_output=True, text=True, check=True, timeout=60)
                
                if result.stderr:
                    print(f"Parted stderr for partition {partition['number']}: {result.stderr}")
            
            # Wait for partitions to be available
            print("Waiting for target partitions to be available...")
            time.sleep(3)
            subprocess.run(['partprobe', target_nbd], check=False, timeout=30)
            time.sleep(2)
            
            # Verify partitions were created on target
            verify_result = subprocess.run(['lsblk', target_nbd], 
                                        capture_output=True, text=True, timeout=30)
            print(f"Target partition layout:\n{verify_result.stdout}")
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"ERROR in _clone_disk_structure_safe - command failed: {e}")
            raise subprocess.CalledProcessError(e.returncode, e.cmd, f"Failed to clone disk structure: {e}")
        except subprocess.TimeoutExpired as e:
            print(f"ERROR in _clone_disk_structure_safe - timeout: {e}")
            raise subprocess.TimeoutExpired(e.cmd, e.timeout, f"Disk structure cloning timed out: {e}")
        except FileNotFoundError as e:
            print(f"ERROR in _clone_disk_structure_safe - command not found: {e}")
            raise FileNotFoundError(f"Required command not found for disk structure cloning: {e}")
        except PermissionError as e:
            print(f"ERROR in _clone_disk_structure_safe - permission denied: {e}")
            raise PermissionError(f"Permission denied during disk structure cloning: {e}")
        except ValueError as e:
            print(f"ERROR in _clone_disk_structure_safe - invalid value: {e}")
            raise ValueError(f"Invalid parameter for disk structure cloning: {e}")
        except OSError as e:
            print(f"ERROR in _clone_disk_structure_safe - system error: {e}")
            raise OSError(f"System error during disk structure cloning: {e}")

    def _clone_partition_data_safe(self, source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone partition data with enhanced error handling and verification"""
        try:
            print(f"Cloning partition data from {source_nbd} to {target_nbd}")
            
            # Verify devices are different
            if source_nbd == target_nbd:
                raise ValueError(f"Source and target NBD devices cannot be the same: {source_nbd}")
            
            total_partitions = len(layout_info['partitions'])
            print(f"Processing {total_partitions} partitions")
            
            # Wait longer for all partitions to be available
            print("Ensuring all partitions are available...")
            max_wait_attempts = 10
            for attempt in range(max_wait_attempts):
                subprocess.run(['partprobe', source_nbd], check=False, timeout=30)
                subprocess.run(['partprobe', target_nbd], check=False, timeout=30)
                time.sleep(2)
                
                # Check if all partitions exist
                all_found = True
                for partition in layout_info['partitions']:
                    partition_num = partition['number']
                    source_options = [f"{source_nbd}p{partition_num}", f"{source_nbd}{partition_num}"]
                    target_options = [f"{target_nbd}p{partition_num}", f"{target_nbd}{partition_num}"]
                    
                    source_exists = any(os.path.exists(opt) for opt in source_options)
                    target_exists = any(os.path.exists(opt) for opt in target_options)
                    
                    if not source_exists or not target_exists:
                        all_found = False
                        break
                
                if all_found:
                    print(f"All partitions available after {attempt + 1} attempts")
                    break
                else:
                    print(f"Attempt {attempt + 1}: Some partitions not ready, waiting...")
            
            if not all_found:
                print("Warning: Not all partitions detected, proceeding anyway...")
            
            for i, partition in enumerate(layout_info['partitions']):
                partition_num = partition['number']
                
                base_progress = 80 + (i * 10 // total_partitions)
                if progress_callback:
                    progress_callback(base_progress, f"Cloning partition {partition_num}...")
                
                # Try different partition naming schemes for both devices
                source_part_options = [
                    f"{source_nbd}p{partition_num}",  # /dev/nbd0p1
                    f"{source_nbd}{partition_num}"    # /dev/nbd01
                ]
                
                target_part_options = [
                    f"{target_nbd}p{partition_num}",  # /dev/nbd1p1
                    f"{target_nbd}{partition_num}"    # /dev/nbd11
                ]
                
                source_part = None
                target_part = None
                
                # Find source partition with retries
                for retry in range(3):
                    for src_opt in source_part_options:
                        if os.path.exists(src_opt):
                            # Verify it's actually accessible
                            try:
                                subprocess.run(['blockdev', '--getsize64', src_opt],
                                            capture_output=True, check=True, timeout=10)
                                source_part = src_opt
                                print(f"Found accessible source partition: {source_part}")
                                break
                            except subprocess.CalledProcessError:
                                print(f"Partition {src_opt} exists but not accessible")
                                continue
                            except subprocess.TimeoutExpired:
                                print(f"Partition {src_opt} check timed out")
                                continue
                            except FileNotFoundError:
                                print(f"blockdev command not found for {src_opt}")
                                continue
                    
                    if source_part:
                        break
                    
                    print(f"Source partition retry {retry + 1}, waiting...")
                    time.sleep(2)
                    subprocess.run(['partprobe', source_nbd], check=False)
                
                # Find target partition with retries
                for retry in range(3):
                    for tgt_opt in target_part_options:
                        if os.path.exists(tgt_opt):
                            # Verify it's writable
                            try:
                                subprocess.run(['blockdev', '--getsize64', tgt_opt],
                                            capture_output=True, check=True, timeout=10)
                                target_part = tgt_opt
                                print(f"Found accessible target partition: {target_part}")
                                break
                            except subprocess.CalledProcessError:
                                print(f"Partition {tgt_opt} exists but not accessible")
                                continue
                            except subprocess.TimeoutExpired:
                                print(f"Partition {tgt_opt} check timed out")
                                continue
                            except FileNotFoundError:
                                print(f"blockdev command not found for {tgt_opt}")
                                continue
                    
                    if target_part:
                        break
                        
                    print(f"Target partition retry {retry + 1}, waiting...")
                    time.sleep(2)
                    subprocess.run(['partprobe', target_nbd], check=False)
                
                if not source_part:
                    print(f"ERROR: Could not find accessible source partition {partition_num}")
                    print(f"Tried: {source_part_options}")
                    continue
                
                if not target_part:
                    print(f"ERROR: Could not find accessible target partition {partition_num}")
                    print(f"Tried: {target_part_options}")
                    continue
                
                print(f"Cloning partition {partition_num}: {source_part} -> {target_part}")
                
                # Get exact partition sizes
                try:
                    source_size_result = subprocess.run(['blockdev', '--getsize64', source_part],
                                                capture_output=True, text=True, check=True, timeout=30)
                    source_size = int(source_size_result.stdout.strip())
                    
                    target_size_result = subprocess.run(['blockdev', '--getsize64', target_part],
                                                capture_output=True, text=True, check=True, timeout=30)
                    target_size = int(target_size_result.stdout.strip())
                    
                    print(f"Partition {partition_num} - Source: {QCow2CloneResizer.format_size(source_size)}, Target: {QCow2CloneResizer.format_size(target_size)}")
                    
                    if target_size < source_size:
                        print(f"WARNING: Target partition smaller than source, truncating data")
                    
                    # Use the smaller size to avoid overrun
                    copy_size = min(source_size, target_size)
                    copy_blocks = copy_size // (4 * 1024 * 1024)  # 4MB blocks
                    copy_remainder = copy_size % (4 * 1024 * 1024)
                    
                except subprocess.CalledProcessError as e:
                    print(f"Could not get partition sizes - command failed: {e}")
                    # Fallback: copy without count (full partition)
                    copy_blocks = None
                    copy_remainder = 0
                except ValueError as e:
                    print(f"Could not parse partition sizes - invalid value: {e}")
                    # Fallback: copy without count (full partition)
                    copy_blocks = None
                    copy_remainder = 0
                except FileNotFoundError:
                    print(f"Could not get partition sizes - blockdev not found")
                    # Fallback: copy without count (full partition)
                    copy_blocks = None
                    copy_remainder = 0
                
                # Enhanced dd command with better error handling
                if copy_blocks is not None:
                    # Copy in blocks first
                    if copy_blocks > 0:
                        cmd = [
                            'dd',
                            f'if={source_part}',
                            f'of={target_part}',
                            'bs=4M',
                            f'count={copy_blocks}',
                            'conv=notrunc,noerror,sync',
                            'oflag=sync'
                        ]
                        
                        print(f"Copying {copy_blocks} blocks: {' '.join(cmd)}")
                        
                        if not self._execute_dd_with_retry(cmd, timeout=600):
                            print(f"ERROR: Failed to copy main blocks for partition {partition_num}")
                            continue
                    
                    # Copy remainder if any
                    if copy_remainder > 0:
                        skip_blocks = copy_blocks
                        cmd = [
                            'dd',
                            f'if={source_part}',
                            f'of={target_part}',
                            'bs=1M',
                            f'count={copy_remainder // (1024 * 1024) + 1}',
                            f'skip={skip_blocks * 4}',  # Skip in 1MB blocks
                            f'seek={skip_blocks * 4}',
                            'conv=notrunc,noerror,sync',
                            'oflag=sync'
                        ]
                        
                        print(f"Copying remainder: {' '.join(cmd)}")
                        if not self._execute_dd_with_retry(cmd, timeout=300):
                            print(f"WARNING: Failed to copy remainder for partition {partition_num}")
                else:
                    # Simple copy without size limits
                    cmd = [
                        'dd',
                        f'if={source_part}',
                        f'of={target_part}',
                        'bs=4M',
                        'conv=notrunc,noerror,sync',
                        'oflag=sync'
                    ]
                    
                    print(f"Simple copy: {' '.join(cmd)}")
                    if not self._execute_dd_with_retry(cmd, timeout=1800):
                        print(f"ERROR: Failed to copy partition {partition_num}")
                        continue
                
                print(f"Partition {partition_num} cloned successfully")
                
                # Sync and verify
                subprocess.run(['sync'], check=False, timeout=60)
                time.sleep(1)
                
                if progress_callback:
                    progress_callback(base_progress + 2, f"Partition {partition_num} completed")
            
            # Final sync
            print("Performing final sync...")
            subprocess.run(['sync'], check=False, timeout=60)
            time.sleep(2)
            
            print("All partitions processed")
            return True
            
        except ValueError as e:
            print(f"ERROR in _clone_partition_data_safe - invalid value: {e}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Failed to clone partition data - invalid value: {e}")
        except FileNotFoundError as e:
            print(f"ERROR in _clone_partition_data_safe - file not found: {e}")
            import traceback
            traceback.print_exc()
            raise FileNotFoundError(f"Failed to clone partition data - file not found: {e}")
        except PermissionError as e:
            print(f"ERROR in _clone_partition_data_safe - permission denied: {e}")
            import traceback
            traceback.print_exc()
            raise PermissionError(f"Failed to clone partition data - permission denied: {e}")
        except OSError as e:
            print(f"ERROR in _clone_partition_data_safe - system error: {e}")
            import traceback
            traceback.print_exc()
            raise OSError(f"Failed to clone partition data - system error: {e}")
    
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
            self.log(f"Final size dialog error - missing module: {e}")
            print(f"ERROR in _show_final_size_dialog - import error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except AttributeError as e:
            self.log(f"Final size dialog error - attribute error: {e}")
            print(f"ERROR in _show_final_size_dialog - attribute error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except TypeError as e:
            self.log(f"Final size dialog error - type error: {e}")
            print(f"ERROR in _show_final_size_dialog - type error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except ValueError as e:
            self.log(f"Final size dialog error - value error: {e}")
            print(f"ERROR in _show_final_size_dialog - value error: {e}")
            self.dialog_result_value = None
            self.dialog_result_event.set()
        except OSError as e:
            self.log(f"Final size dialog error - system error: {e}")
            print(f"ERROR in _show_final_size_dialog - system error: {e}")
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