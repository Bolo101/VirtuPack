import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from QCow2CloneResizer import QCow2CloneResizer

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
        
        # CRITICAL: Use wait_window instead of custom event handling
        # This is safe when called from root.after(0, ...) in the worker thread
        try:
            self.dialog.lift()
            self.dialog.attributes('-topmost', True)
            self.dialog.after_idle(lambda: self.dialog.attributes('-topmost', False))
            
            # Wait for the dialog to complete
            self.dialog.wait_window()
        except tk.TclError as e:
            print(f"Dialog wait TCL error: {e}")
            self.result = None
        except Exception as e:
            print(f"Dialog wait error: {e}")
            self.result = None

    def setup_ui(self):
        """Setup dialog UI with scrollable content"""
        try:
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
                try:
                    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                except:
                    pass
            
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
            
            # Option 1: Use calculated size (recommended)
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
            ttk.Label(warning_frame, text=f"WARNING: Minimum size required: {QCow2CloneResizer.format_size(min_size_with_buffer)}", 
                    font=("Arial", 8), foreground="orange").pack(anchor="w")
            
            # What Happens Next
            exp_frame = ttk.LabelFrame(content_frame, text="What Happens Next", padding="10")
            exp_frame.pack(fill="x", pady=(0, 20))
            
            explanation = ("1. Create new empty image with selected size (using preallocation=metadata)\n"
                        "2. Copy partition table structure from current image\n"
                        "3. Clone each partition with all your GParted changes\n"
                        "4. Preserve bootloader and all modifications\n\n"
                        "All your partition resizing and changes will be preserved.")
            
            exp_label = ttk.Label(exp_frame, text=explanation, wraplength=500, justify="left", font=("Arial", 9))
            exp_label.pack()
            
            # Buttons outside scrollable area, always visible
            button_container = ttk.Frame(main_container)
            button_container.pack(fill="x", pady=(10, 0))
            
            # Separator line
            separator = ttk.Separator(button_container, orient="horizontal")
            separator.pack(fill="x", pady=(0, 10))
            
            # Buttons frame
            button_frame = ttk.Frame(button_container)
            button_frame.pack(fill="x")
            
            create_btn = ttk.Button(button_frame, text="Create New Optimized Image", 
                                command=self.create_new)
            create_btn.pack(side="right", padx=(10, 0), pady=5)
            
            cancel_btn = ttk.Button(button_frame, text="Skip Cloning", 
                                command=self.skip_cloning)
            cancel_btn.pack(side="right", pady=5)
            
            # Add keyboard shortcuts
            self.dialog.bind('<Return>', lambda e: self.create_new())
            self.dialog.bind('<Escape>', lambda e: self.skip_cloning())
            
            # Focus on the create button
            create_btn.focus_set()
            
        except Exception as e:
            print(f"UI setup error: {e}")
            self._create_fallback_ui()
    
    def _create_fallback_ui(self):
        """Create minimal fallback UI if main UI setup fails"""
        try:
            fallback_frame = ttk.Frame(self.dialog, padding="20")
            fallback_frame.pack(fill="both", expand=True)
            
            ttk.Label(fallback_frame, text="Dialog Error - Using Fallback Interface", 
                     font=("Arial", 12, "bold"), foreground="red").pack(pady=(0, 20))
            
            ttk.Label(fallback_frame, text="Use calculated minimum size?", 
                     font=("Arial", 10)).pack(pady=(0, 20))
            
            button_frame = ttk.Frame(fallback_frame)
            button_frame.pack(fill="x")
            
            ttk.Button(button_frame, text="Yes - Create New Image", 
                      command=self._fallback_create).pack(side="right", padx=(10, 0))
            ttk.Button(button_frame, text="No - Skip Cloning", 
                      command=self.skip_cloning).pack(side="right")
            
        except Exception as e:
            print(f"Fallback UI creation failed: {e}")
            self.result = None
    
    def _fallback_create(self):
        """Fallback create method using minimum size"""
        try:
            self.result = self.final_layout_info['required_minimum_bytes']
            # CRITICAL: Just destroy, don't call quit()
            self.dialog.destroy()
        except Exception as e:
            print(f"Fallback create error: {e}")
            self.result = None
            self.skip_cloning()
    
    def create_new(self):
        """Create new image with selected size"""
        try:
            choice = self.choice.get()
            min_size = self.final_layout_info['required_minimum_bytes']
            
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
            
            # Store result and close dialog
            self.result = new_size
            print(f"NewSizeDialog: User selected size {new_size} bytes")
            
            # CRITICAL: Just destroy, don't call quit()
            # quit() can cause the mainloop to exit completely
            self.dialog.destroy()
            
        except ValueError as e:
            messagebox.showerror("Invalid Size", f"Error parsing size: {e}")
        except Exception as e:
            print(f"Create new error: {e}")
            # Try to set result anyway
            try:
                self.result = self.final_layout_info['required_minimum_bytes']
                self.dialog.destroy()
            except:
                self.result = None
    
    def skip_cloning(self):
        """Skip cloning - keep original image with changes"""
        try:
            self.result = None
            print("NewSizeDialog: User skipped cloning")
            # CRITICAL: Just destroy, don't call quit()
            self.dialog.destroy()
        except Exception as e:
            print(f"Skip cloning error: {e}")
            self.result = None