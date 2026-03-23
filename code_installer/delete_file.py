import tkinter as tk
from tkinter import ttk, messagebox
import os
import time
import threading
from pathlib import Path
from log_handler import log_info, log_error, log_warning


class FileDeleteManager:
    """Manager for file deletion with GUI interface"""
    
    def __init__(self, parent_window):
        """
        Initialize FileDeleteManager
        
        Args:
            parent_window: Parent Tkinter window for modal dialogs
        """
        self.parent_window = parent_window
        self.selected_files = []
        self.operation_active = False
        self.cancel_requested = False
        
        log_info("FileDeleteManager initialized")
    
    def show_file_selection_dialog(self, initial_directory="/home"):
        """
        Show file browser dialog for selecting files to delete
        
        Args:
            initial_directory: Starting directory for file browser
            
        Returns:
            list: List of Path objects selected by user, or empty list if cancelled
        """
        try:
            log_info(f"Opening file selection dialog starting from: {initial_directory}")
            
            # Create file selection window
            selection_window = tk.Toplevel(self.parent_window)
            selection_window.title("Delete Files - Select files to remove")
            selection_window.geometry("900x600") 
            selection_window.resizable(False, False)
            
            # Make window modal
            selection_window.transient(self.parent_window)
            selection_window.grab_set()
            selection_window.lift()
            selection_window.focus_force()
            
            selected_files = []
            
            # Main frame
            main_frame = ttk.Frame(selection_window, padding="15")
            main_frame.pack(fill="both", expand=True) 

            # Title
            title_label = ttk.Label(main_frame, 
                                text="FILE DELETION - Select files to permanently delete",
                                font=("Arial", 12, "bold"))
            title_label.pack(fill="x", pady=(0, 10))
            
            # Description
            desc_label = ttk.Label(main_frame,
                                text="Navigate the file system and select files to delete.\n"
                                    "Selected files will be permanently removed after confirmation.",
                                font=("Arial", 10),
                                wraplength=850, 
                                justify="left")
            desc_label.pack(fill="x", pady=(0, 15))
            
            # Directory navigation frame
            nav_frame = ttk.LabelFrame(main_frame, text="Directory Navigation", padding="10")
            nav_frame.pack(fill="x", pady=(0, 10))
            
            current_dir_var = tk.StringVar(value=initial_directory)
            
            ttk.Label(nav_frame, text="Current Directory:").pack(side="left", padx=(0, 5))
            dir_entry = ttk.Entry(nav_frame, textvariable=current_dir_var, font=("Arial", 9))
            dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 5)) 
            
            def browse_directory():
                """Open directory browser"""
                try:
                    from tkinter import filedialog
                    directory = filedialog.askdirectory(
                        title="Select Directory",
                        initialdir=current_dir_var.get()
                    )
                    if directory:
                        current_dir_var.set(directory)
                        refresh_file_list()
                        log_info(f"User navigated to directory: {directory}")
                except FileNotFoundError as e:
                    log_error(f"Directory not found: {e}")
                    messagebox.showerror("Browse Error", f"Directory not found:\n{e}")
                except PermissionError as e:
                    log_error(f"Permission denied accessing directory: {e}")
                    messagebox.showerror("Browse Error", f"Permission denied:\n{e}")
                except tk.TclError as e:
                    log_error(f"Tkinter error in browse dialog: {e}")
                    messagebox.showerror("Browse Error", f"Dialog error:\n{e}")
            
            ttk.Button(nav_frame, text="Browse", command=browse_directory).pack(side="left", padx=(0, 5))
            
            def go_to_home():
                """Navigate to home directory"""
                try:
                    home_dir = str(Path.home())
                    current_dir_var.set(home_dir)
                    refresh_file_list()
                    log_info(f"User navigated to home directory: {home_dir}")
                except RuntimeError as e:
                    log_error(f"Could not determine home directory: {e}")
                    messagebox.showerror("Home Directory Error", f"Could not access home directory:\n{e}")
            
            ttk.Button(nav_frame, text="Home", command=go_to_home).pack(side="left")
            
            # File browser frame
            browser_frame = ttk.LabelFrame(main_frame, text="Files in Directory", padding="10")
            browser_frame.pack(fill="both", expand=True, pady=(0, 15)) 
            
            browser_frame.grid_rowconfigure(0, weight=1) 
            browser_frame.grid_columnconfigure(0, weight=1) 

            # Scrollbars
            scrollbar_v = ttk.Scrollbar(browser_frame, orient="vertical")
            scrollbar_h = ttk.Scrollbar(browser_frame, orient="horizontal")
            
            # File listbox
            file_listbox = tk.Listbox(browser_frame, 
                                    yscrollcommand=scrollbar_v.set,
                                    xscrollcommand=scrollbar_h.set,
                                    height=15, 
                                    font=("Consolas", 9),
                                    selectmode=tk.EXTENDED)
            file_listbox.grid(row=0, column=0, sticky="nsew") 
            scrollbar_v.config(command=file_listbox.yview)
            scrollbar_v.grid(row=0, column=1, sticky="ns") 
            scrollbar_h.config(command=file_listbox.xview)
            scrollbar_h.grid(row=1, column=0, sticky="ew") 
            
            file_info_list = [] 
            
            def refresh_file_list():
                """Recharge la liste des fichiers du répertoire courant"""
                try:
                    current_dir = current_dir_var.get()
                    
                    if not os.path.isdir(current_dir):
                        messagebox.showwarning("Invalid Directory", 
                                            f"Directory does not exist:\n{current_dir}")
                        return
                    
                    file_listbox.delete(0, tk.END)
                    file_info_list.clear()
                    
                    try:
                        entries = os.listdir(current_dir)
                    except PermissionError as e:
                        messagebox.showwarning("Permission Denied", 
                                            f"Permission denied accessing:\n{current_dir}")
                        log_warning(f"Permission denied listing directory: {current_dir}")
                        return
                    except OSError as e:
                        messagebox.showerror("Error", f"Error reading directory:\n{e}")
                        log_error(f"Error reading directory {current_dir}: {e}")
                        return
                    
                    entries.sort()
                    
                    for entry in entries:
                        try:
                            entry_path = os.path.join(current_dir, entry)
                            
                            if os.path.isdir(entry_path):
                                display_text = f"[DIR] {entry}"
                            else:
                                try:
                                    size = os.path.getsize(entry_path)
                                    size_str = self._format_size_compact(size)
                                    display_text = f"{entry} ({size_str})"
                                except OSError as e:
                                    log_warning(f"Could not get size for {entry_path}: {e}")
                                    display_text = f"{entry}"
                            
                            file_listbox.insert(tk.END, display_text)
                            file_info_list.append((entry_path, display_text))
                            
                        except (OSError, PermissionError) as e:
                            log_warning(f"Could not process entry {entry}: {e}")
                            continue
                    
                    log_info(f"File list refreshed for directory: {current_dir}")
                    update_selection_info()
                    
                except ValueError as e:
                    log_error(f"Invalid value in file list refresh: {e}")
                    messagebox.showerror("Refresh Error", f"Invalid value:\n{e}")
                except IOError as e:
                    log_error(f"I/O error refreshing file list: {e}")
                    messagebox.showerror("Refresh Error", f"I/O error:\n{e}")
            
            def update_selection_info():
                """Met à jour l'étiquette d'information de sélection"""
                try:
                    selected_indices = file_listbox.curselection()
                    total_size = 0
                    file_count = len(selected_indices)
                    
                    for idx in selected_indices:
                        if idx < len(file_info_list):
                            file_path = file_info_list[idx][0]
                            try:
                                if os.path.isfile(file_path):
                                    total_size += os.path.getsize(file_path)
                            except OSError as e:
                                log_warning(f"Could not get size for {file_path}: {e}")
                    
                    size_str = self._format_size_compact(total_size) if total_size > 0 else "0B"
                    selection_label.config(text=f"Selected: {file_count} item(s), Total size: {size_str}")
                    
                except IndexError as e:
                    log_warning(f"Index error updating selection info: {e}")
                except tk.TclError as e:
                    log_warning(f"Tkinter error updating selection info: {e}")
            
            # Selection info label
            selection_label = ttk.Label(main_frame, text="Selected: 0 item(s), Total size: 0B", 
                                    font=("Arial", 9), foreground="blue")
            selection_label.pack(fill="x", pady=(0, 10))
            
            # Bind selection changes
            file_listbox.bind("<<ListboxSelect>>", lambda e: update_selection_info())
            
            # Bouton Delete en noir sur fond rouge
            all_buttons_frame = ttk.Frame(main_frame)
            all_buttons_frame.pack(fill="x", pady=(0, 10))
            
            def on_delete():
                """Confirme la suppression"""
                selected_indices = file_listbox.curselection()
                if not selected_indices:
                    messagebox.showwarning("No Selection", "Please select files to delete")
                    return
                
                selected_files.clear()
                for idx in selected_indices:
                    if idx < len(file_info_list):
                        selected_files.append(Path(file_info_list[idx][0]))
                
                log_info(f"User confirmed deletion of {len(selected_files)} file(s)")
                selection_window.destroy()
            
            def on_cancel():
                """Annule l'opération"""
                selected_files.clear()
                log_info("User cancelled file selection")
                selection_window.destroy()
            
            def select_all():
                """Sélectionne tous les fichiers"""
                file_listbox.select_set(0, tk.END)
                update_selection_info()
                log_info("User selected all files")
            
            def deselect_all():
                """Désélectionne tous les fichiers"""
                file_listbox.selection_clear(0, tk.END)
                update_selection_info()
                log_info("User deselected all files")
            
            left_buttons_frame = ttk.Frame(all_buttons_frame)
            left_buttons_frame.pack(side="left", fill="x", expand=True)
            
            right_buttons_frame = ttk.Frame(all_buttons_frame)
            right_buttons_frame.pack(side="right")

            ttk.Button(left_buttons_frame, text="Select All", command=select_all).pack(side="left", padx=(0, 5))
            ttk.Button(left_buttons_frame, text="Deselect All", command=deselect_all).pack(side="left", padx=(0, 15))
            ttk.Button(left_buttons_frame, text="Refresh", command=refresh_file_list).pack(side="left")

            # Bouton Delete en noir sur fond rouge
            delete_btn = tk.Button(right_buttons_frame, text="Delete Selected Files", 
                                command=on_delete, bg="red", fg="black", 
                                font=("Arial", 9, "bold"), padx=10, pady=5)
            delete_btn.pack(side="left", padx=(0, 10))
            
            ttk.Button(right_buttons_frame, text="Cancel", 
                    command=on_cancel).pack(side="left")
            
            # Warning label
            warning_label = ttk.Label(main_frame,
                                    text="⚠ WARNING: Selected files will be permanently deleted and cannot be recovered!",
                                    font=("Arial", 9),
                                    foreground="red")
            warning_label.pack(fill="x", pady=(0, 10))
            
            # Centrer la fenêtre
            selection_window.update_idletasks()
            x = self.parent_window.winfo_x() + (self.parent_window.winfo_width() - selection_window.winfo_width()) // 2
            y = self.parent_window.winfo_y() + (self.parent_window.winfo_height() - selection_window.winfo_height()) // 2
            selection_window.geometry(f"+{x}+{y}")
            
            # Charger le répertoire initial
            refresh_file_list()
            
            # Attendre que la fenêtre se ferme
            self.parent_window.wait_window(selection_window)
            
            return selected_files
            
        except tk.TclError as e:
            log_error(f"Tkinter error in file selection dialog: {e}")
            messagebox.showerror("Dialog Error", f"Error creating file selection dialog:\n{e}")
            return []
        except ValueError as e:
            log_error(f"Value error in file selection dialog: {e}")
            messagebox.showerror("Dialog Error", f"Invalid value in dialog:\n{e}")
            return []
        except IOError as e:
            log_error(f"I/O error in file selection dialog: {e}")
            messagebox.showerror("Dialog Error", f"I/O error:\n{e}")
            return []
    
    def delete_files_with_confirmation(self, files_to_delete):
        """
        Delete selected files with confirmation dialog
        """
        if not files_to_delete:
            log_warning("No files provided for deletion")
            return {'removed': 0, 'failed': 0}
        
        try:
            total_size = 0
            for file_path in files_to_delete:
                try:
                    if os.path.isfile(file_path):
                        total_size += os.path.getsize(file_path)
                except OSError as e:
                    log_warning(f"Could not get size for {file_path}: {e}")
            
            confirm_msg = f"PERMANENT DELETION CONFIRMATION\n\n"
            confirm_msg += f"Files to DELETE ({len(files_to_delete)}):\n"
            confirm_msg += f"{'='*50}\n\n"
            
            for i, file_path in enumerate(files_to_delete[:10]):
                try:
                    if os.path.isfile(file_path):
                        size = os.path.getsize(file_path)
                        size_str = self._format_size_compact(size)
                        confirm_msg += f"• {file_path.name} ({size_str})\n"
                    else:
                        confirm_msg += f"• {file_path.name} [DIRECTORY]\n"
                except OSError as e:
                    log_warning(f"Could not get info for {file_path}: {e}")
                    confirm_msg += f"• {file_path.name}\n"
            
            if len(files_to_delete) > 10:
                confirm_msg += f"\n... and {len(files_to_delete) - 10} more file(s)\n"
            
            confirm_msg += f"\n{'='*50}\n"
            confirm_msg += f"Total size: {self._format_size_compact(total_size)}\n\n"
            confirm_msg += f"⚠ WARNING: This action CANNOT be undone!\n"
            confirm_msg += f"Files will be permanently deleted.\n\n"
            confirm_msg += f"Are you absolutely sure?"
            
            result = messagebox.askyesno("CONFIRM PERMANENT DELETION", confirm_msg, default='no')
            
            if not result:
                log_info("User cancelled file deletion")
                return {'removed': 0, 'failed': 0}
            
            log_info(f"User confirmed deletion of {len(files_to_delete)} file(s), total size: {self._format_size_compact(total_size)}")
            
            stats = {'removed': 0, 'failed': 0}
            
            def delete_worker():
                try:
                    for i, file_path in enumerate(files_to_delete):
                        try:
                            if os.path.isfile(file_path) or os.path.isdir(file_path):
                                max_retries = 3
                                deleted = False
                                
                                for attempt in range(max_retries):
                                    try:
                                        if os.path.isfile(file_path):
                                            os.remove(file_path)
                                        else:
                                            import shutil
                                            shutil.rmtree(file_path)
                                        
                                        stats['removed'] += 1
                                        log_info(f"Deleted: {file_path}")
                                        deleted = True
                                        break
                                        
                                    except PermissionError as e:
                                        if attempt < max_retries - 1:
                                            time.sleep(1)
                                        else:
                                            raise
                                    except OSError as e:
                                        if attempt < max_retries - 1:
                                            time.sleep(1)
                                        else:
                                            raise
                                
                                if not deleted:
                                    stats['failed'] += 1
                                    log_error(f"Failed to delete: {file_path}")
                            else:
                                stats['failed'] += 1
                                log_warning(f"File/directory not found: {file_path}")
                                
                        except PermissionError as e:
                            stats['failed'] += 1
                            log_error(f"Permission denied deleting {file_path}: {e}")
                        except OSError as e:
                            stats['failed'] += 1
                            log_error(f"OS error deleting {file_path}: {e}")
                        except ValueError as e:
                            stats['failed'] += 1
                            log_error(f"Value error deleting {file_path}: {e}")
                except PermissionError as e:
                    log_error(f"Permission error in deletion worker thread: {e}")
                except OSError as e:
                    log_error(f"OS error in deletion worker thread: {e}")
                except RuntimeError as e:
                    log_error(f"Runtime error in deletion worker thread: {e}")
            
            delete_thread = threading.Thread(target=delete_worker, daemon=True)
            delete_thread.start()
            delete_thread.join(timeout=300)  # Wait up to 5 minutes
            
            result_msg = f"FILE DELETION RESULTS\n\n"
            result_msg += f"✓ Successfully deleted: {stats['removed']} file(s)\n"
            result_msg += f"✗ Failed to delete: {stats['failed']} file(s)\n"
            
            if stats['removed'] > 0:
                result_msg += f"\nFreed disk space: {self._format_size_compact(total_size)}\n"
                messagebox.showinfo("Deletion Complete", result_msg)
                log_info(f"Deletion complete - removed: {stats['removed']}, failed: {stats['failed']}")
            else:
                messagebox.showwarning("Deletion Failed", result_msg)
                log_warning(f"Deletion failed - no files removed")
            
            return stats
            
        except OSError as e:
            log_error(f"OS error in delete_files_with_confirmation: {e}")
            messagebox.showerror("Deletion Error", f"OS error during file deletion:\n{e}")
            return {'removed': 0, 'failed': 0}
        except ValueError as e:
            log_error(f"Value error in delete_files_with_confirmation: {e}")
            messagebox.showerror("Deletion Error", f"Invalid value during file deletion:\n{e}")
            return {'removed': 0, 'failed': 0}
        except TypeError as e:
            log_error(f"Type error in delete_files_with_confirmation: {e}")
            messagebox.showerror("Deletion Error", f"Type error during file deletion:\n{e}")
            return {'removed': 0, 'failed': 0}

    
    def delete_files_interactive(self):
        """
        Interactive file deletion: Select files then delete them
        """
        try:
            log_info("Starting interactive file deletion process")
            
            selected_files = self.show_file_selection_dialog()
            
            if not selected_files:
                log_info("No files selected for deletion")
                return {'removed': 0, 'failed': 0}
            
            stats = self.delete_files_with_confirmation(selected_files)
            
            return stats
            
        except ValueError as e:
            log_error(f"Value error in delete_files_interactive: {e}")
            messagebox.showerror("Error", f"Invalid value during file deletion process:\n{e}")
            return {'removed': 0, 'failed': 0}
        except IOError as e:
            log_error(f"I/O error in delete_files_interactive: {e}")
            messagebox.showerror("Error", f"I/O error during file deletion process:\n{e}")
            return {'removed': 0, 'failed': 0}
        except RuntimeError as e:
            log_error(f"Runtime error in delete_files_interactive: {e}")
            messagebox.showerror("Error", f"Runtime error during file deletion process:\n{e}")
            return {'removed': 0, 'failed': 0}
    
    @staticmethod
    def _format_size_compact(size_bytes):
        """
        Format bytes to compact size string
        """
        try:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size_bytes < 1024.0:
                    if unit == 'B':
                        return f"{int(size_bytes)}{unit}"
                    return f"{size_bytes:.1f}{unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f}PB"
        except (TypeError, ValueError):
            return "unknown"