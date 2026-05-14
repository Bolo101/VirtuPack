import tkinter as tk
from tkinter import ttk, messagebox
import os
import time
import threading
from pathlib import Path
from log_handler import log_info, log_error, log_warning


class FileDeleteManager:
    """Gestionnaire de suppression de fichiers avec interface graphique"""
    
    def __init__(self, parent_window):
        """
        Initialise FileDeleteManager
        
        Args:
            parent_window: Fenêtre Tkinter parente pour les boîtes de dialogue modales
        """
        self.parent_window = parent_window
        self.selected_files = []
        self.operation_active = False
        self.cancel_requested = False
        
        log_info("FileDeleteManager initialisé")
    
    def show_file_selection_dialog(self, initial_directory="/home"):
        """
        Affiche une boîte de dialogue de navigation pour sélectionner les fichiers à supprimer
        
        Args:
            initial_directory: Répertoire de départ pour le navigateur de fichiers
            
        Returns:
            list: Liste d'objets Path sélectionnés par l'utilisateur, ou liste vide si annulé
        """
        try:
            log_info(f"Ouverture de la boîte de sélection de fichiers à partir de : {initial_directory}")
            
            # Create file selection window
            selection_window = tk.Toplevel(self.parent_window)
            selection_window.title("Supprimer des fichiers - Sélectionner les fichiers à supprimer")
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
                                text="SUPPRESSION DE FICHIERS - Sélectionnez les fichiers à supprimer définitivement",
                                font=("Arial", 12, "bold"))
            title_label.pack(fill="x", pady=(0, 10))
            
            # Description
            desc_label = ttk.Label(main_frame,
                                text="Parcourez le système de fichiers et sélectionnez les fichiers à supprimer.\n"
                                    "Les fichiers sélectionnés seront supprimés définitivement après confirmation.",
                                font=("Arial", 10),
                                wraplength=850, 
                                justify="left")
            desc_label.pack(fill="x", pady=(0, 15))
            
            # Directory navigation frame
            nav_frame = ttk.LabelFrame(main_frame, text="Navigation dans les répertoires", padding="10")
            nav_frame.pack(fill="x", pady=(0, 10))
            
            current_dir_var = tk.StringVar(value=initial_directory)
            
            ttk.Label(nav_frame, text="Répertoire actuel :").pack(side="left", padx=(0, 5))
            dir_entry = ttk.Entry(nav_frame, textvariable=current_dir_var, font=("Arial", 9))
            dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 5)) 
            
            def browse_directory():
                """Open directory browser"""
                try:
                    from tkinter import filedialog
                    directory = filedialog.askdirectory(
                        title="Sélectionner un répertoire",
                        initialdir=current_dir_var.get()
                    )
                    if directory:
                        current_dir_var.set(directory)
                        refresh_file_list()
                        log_info(f"L'utilisateur a navigué vers le répertoire : {directory}")
                except FileNotFoundError as e:
                    log_error(f"Répertoire introuvable : {e}")
                    messagebox.showerror("Erreur de navigation", f"Répertoire introuvable :\n{e}")
                except PermissionError as e:
                    log_error(f"Permission refusée pour accéder au répertoire : {e}")
                    messagebox.showerror("Erreur de navigation", f"Permission refusée :\n{e}")
                except tk.TclError as e:
                    log_error(f"Erreur Tkinter dans la boîte de navigation : {e}")
                    messagebox.showerror("Erreur de navigation", f"Erreur de dialogue :\n{e}")
            
            ttk.Button(nav_frame, text="Parcourir", command=browse_directory).pack(side="left", padx=(0, 5))
            
            def go_to_home():
                """Navigate to home directory"""
                try:
                    home_dir = str(Path.home())
                    current_dir_var.set(home_dir)
                    refresh_file_list()
                    log_info(f"L'utilisateur a navigué vers le répertoire personnel : {home_dir}")
                except RuntimeError as e:
                    log_error(f"Impossible de déterminer le répertoire personnel : {e}")
                    messagebox.showerror("Erreur du répertoire personnel", f"Impossible d'accéder au répertoire personnel :\n{e}")
            
            ttk.Button(nav_frame, text="Accueil", command=go_to_home).pack(side="left")
            
            # File browser frame
            browser_frame = ttk.LabelFrame(main_frame, text="Fichiers du répertoire", padding="10")
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
                        messagebox.showwarning("Répertoire invalide", 
                                            f"Le répertoire n'existe pas :\n{current_dir}")
                        return
                    
                    file_listbox.delete(0, tk.END)
                    file_info_list.clear()
                    
                    try:
                        entries = os.listdir(current_dir)
                    except PermissionError as e:
                        messagebox.showwarning("Permission refusée", 
                                            f"Permission refusée pour accéder à :\n{current_dir}")
                        log_warning(f"Permission refusée pour lister le répertoire : {current_dir}")
                        return
                    except OSError as e:
                        messagebox.showerror("Erreur", f"Erreur lors de la lecture du répertoire :\n{e}")
                        log_error(f"Erreur lors de la lecture du répertoire {current_dir} : {e}")
                        return
                    
                    entries.sort()
                    
                    for entry in entries:
                        try:
                            entry_path = os.path.join(current_dir, entry)
                            
                            if os.path.isdir(entry_path):
                                display_text = f"[DOSSIER] {entry}"
                            else:
                                try:
                                    size = os.path.getsize(entry_path)
                                    size_str = self._format_size_compact(size)
                                    display_text = f"{entry} ({size_str})"
                                except OSError as e:
                                    log_warning(f"Impossible d'obtenir la taille pour {entry_path} : {e}")
                                    display_text = f"{entry}"
                            
                            file_listbox.insert(tk.END, display_text)
                            file_info_list.append((entry_path, display_text))
                            
                        except (OSError, PermissionError) as e:
                            log_warning(f"Impossible de traiter l'entrée {entry} : {e}")
                            continue
                    
                    log_info(f"Liste des fichiers actualisée pour le répertoire : {current_dir}")
                    update_selection_info()
                    
                except ValueError as e:
                    log_error(f"Valeur invalide lors de l'actualisation de la liste des fichiers : {e}")
                    messagebox.showerror("Erreur d'actualisation", f"Valeur invalide :\n{e}")
                except IOError as e:
                    log_error(f"Erreur d'E/S lors de l'actualisation de la liste des fichiers : {e}")
                    messagebox.showerror("Erreur d'actualisation", f"Erreur d'E/S :\n{e}")
            
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
                                log_warning(f"Impossible d'obtenir la taille pour {file_path} : {e}")
                    
                    size_str = self._format_size_compact(total_size) if total_size > 0 else "0B"
                    selection_label.config(text=f"Sélection : {file_count} élément(s), taille totale : {size_str}")
                    
                except IndexError as e:
                    log_warning(f"Erreur d'index lors de la mise à jour des informations de sélection : {e}")
                except tk.TclError as e:
                    log_warning(f"Erreur Tkinter lors de la mise à jour des informations de sélection : {e}")
            
            # Selection info label
            selection_label = ttk.Label(main_frame, text="Sélection : 0 élément(s), taille totale : 0B", 
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
                    messagebox.showwarning("Aucune sélection", "Veuillez sélectionner des fichiers à supprimer")
                    return
                
                selected_files.clear()
                for idx in selected_indices:
                    if idx < len(file_info_list):
                        selected_files.append(Path(file_info_list[idx][0]))
                
                log_info(f"L'utilisateur a confirmé la suppression de {len(selected_files)} fichier(s)")
                selection_window.destroy()
            
            def on_cancel():
                """Annule l'opération"""
                selected_files.clear()
                log_info("L'utilisateur a annulé la sélection de fichiers")
                selection_window.destroy()
            
            def select_all():
                """Sélectionne tous les fichiers"""
                file_listbox.select_set(0, tk.END)
                update_selection_info()
                log_info("L'utilisateur a sélectionné tous les fichiers")
            
            def deselect_all():
                """Désélectionne tous les fichiers"""
                file_listbox.selection_clear(0, tk.END)
                update_selection_info()
                log_info("L'utilisateur a désélectionné tous les fichiers")
            
            left_buttons_frame = ttk.Frame(all_buttons_frame)
            left_buttons_frame.pack(side="left", fill="x", expand=True)
            
            right_buttons_frame = ttk.Frame(all_buttons_frame)
            right_buttons_frame.pack(side="right")


            ttk.Button(left_buttons_frame, text="Tout sélectionner", command=select_all).pack(side="left", padx=(0, 5))
            ttk.Button(left_buttons_frame, text="Tout désélectionner", command=deselect_all).pack(side="left", padx=(0, 15))
            ttk.Button(left_buttons_frame, text="Actualiser", command=refresh_file_list).pack(side="left")


            # Bouton Delete en noir sur fond rouge
            delete_btn = tk.Button(right_buttons_frame, text="Supprimer les fichiers sélectionnés", 
                                command=on_delete, bg="red", fg="black", 
                                font=("Arial", 9, "bold"), padx=10, pady=5)
            delete_btn.pack(side="left", padx=(0, 10))
            
            ttk.Button(right_buttons_frame, text="Annuler", 
                    command=on_cancel).pack(side="left")
            
            # Warning label
            warning_label = ttk.Label(main_frame,
                                    text="⚠ AVERTISSEMENT : Les fichiers sélectionnés seront supprimés définitivement et ne pourront pas être récupérés !",
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
            log_error(f"Erreur Tkinter dans la boîte de dialogue de sélection de fichiers : {e}")
            messagebox.showerror("Erreur de dialogue", f"Erreur lors de la création de la boîte de dialogue de sélection de fichiers :\n{e}")
            return []
        except ValueError as e:
            log_error(f"Erreur de valeur dans la boîte de dialogue de sélection de fichiers : {e}")
            messagebox.showerror("Erreur de dialogue", f"Valeur invalide dans la boîte de dialogue :\n{e}")
            return []
        except IOError as e:
            log_error(f"Erreur d'E/S dans la boîte de dialogue de sélection de fichiers : {e}")
            messagebox.showerror("Erreur de dialogue", f"Erreur d'E/S :\n{e}")
            return []
    
    def delete_files_with_confirmation(self, files_to_delete):
        """
        Supprime les fichiers sélectionnés avec une boîte de dialogue de confirmation
        """
        if not files_to_delete:
            log_warning("Aucun fichier fourni pour la suppression")
            return {'removed': 0, 'failed': 0}
        
        try:
            total_size = 0
            for file_path in files_to_delete:
                try:
                    if os.path.isfile(file_path):
                        total_size += os.path.getsize(file_path)
                except OSError as e:
                    log_warning(f"Impossible d'obtenir la taille pour {file_path} : {e}")
            
            confirm_msg = f"CONFIRMATION DE SUPPRESSION DÉFINITIVE\n\n"
            confirm_msg += f"Fichiers à SUPPRIMER ({len(files_to_delete)}) :\n"
            confirm_msg += f"{'='*50}\n\n"
            
            for i, file_path in enumerate(files_to_delete[:10]):
                try:
                    if os.path.isfile(file_path):
                        size = os.path.getsize(file_path)
                        size_str = self._format_size_compact(size)
                        confirm_msg += f"• {file_path.name} ({size_str})\n"
                    else:
                        confirm_msg += f"• {file_path.name} [DOSSIER]\n"
                except OSError as e:
                    log_warning(f"Impossible d'obtenir les informations pour {file_path} : {e}")
                    confirm_msg += f"• {file_path.name}\n"
            
            if len(files_to_delete) > 10:
                confirm_msg += f"\n... et {len(files_to_delete) - 10} fichier(s) supplémentaire(s)\n"
            
            confirm_msg += f"\n{'='*50}\n"
            confirm_msg += f"Taille totale : {self._format_size_compact(total_size)}\n\n"
            confirm_msg += f"⚠ AVERTISSEMENT : Cette action est IRRÉVERSIBLE !\n"
            confirm_msg += f"Les fichiers seront supprimés définitivement.\n\n"
            confirm_msg += f"Êtes-vous absolument sûr ?"
            
            result = messagebox.askyesno("CONFIRMER LA SUPPRESSION DÉFINITIVE", confirm_msg, default='no')
            
            if not result:
                log_info("L'utilisateur a annulé la suppression des fichiers")
                return {'removed': 0, 'failed': 0}
            
            log_info(f"L'utilisateur a confirmé la suppression de {len(files_to_delete)} fichier(s), taille totale : {self._format_size_compact(total_size)}")
            
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
                                        log_info(f"Supprimé : {file_path}")
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
                                    log_error(f"Échec de suppression : {file_path}")
                            else:
                                stats['failed'] += 1
                                log_warning(f"Fichier/répertoire introuvable : {file_path}")
                                
                        except PermissionError as e:
                            stats['failed'] += 1
                            log_error(f"Permission refusée lors de la suppression de {file_path} : {e}")
                        except OSError as e:
                            stats['failed'] += 1
                            log_error(f"Erreur système lors de la suppression de {file_path} : {e}")
                        except ValueError as e:
                            stats['failed'] += 1
                            log_error(f"Erreur de valeur lors de la suppression de {file_path} : {e}")
                except PermissionError as e:
                    log_error(f"Erreur de permission dans le thread de suppression : {e}")
                except OSError as e:
                    log_error(f"Erreur système dans le thread de suppression : {e}")
                except RuntimeError as e:
                    log_error(f"Erreur d'exécution dans le thread de suppression : {e}")
            
            delete_thread = threading.Thread(target=delete_worker, daemon=True)
            delete_thread.start()
            delete_thread.join(timeout=300)  # Wait up to 5 minutes
            
            result_msg = f"RÉSULTATS DE LA SUPPRESSION DE FICHIERS\n\n"
            result_msg += f"✓ Supprimé(s) avec succès : {stats['removed']} fichier(s)\n"
            result_msg += f"✗ Échec(s) de suppression : {stats['failed']} fichier(s)\n"
            
            if stats['removed'] > 0:
                result_msg += f"\nEspace disque libéré : {self._format_size_compact(total_size)}\n"
                messagebox.showinfo("Suppression terminée", result_msg)
                log_info(f"Suppression terminée - supprimés : {stats['removed']}, échecs : {stats['failed']}")
            else:
                messagebox.showwarning("Échec de la suppression", result_msg)
                log_warning("Échec de la suppression - aucun fichier supprimé")
            
            return stats
            
        except OSError as e:
            log_error(f"Erreur système dans delete_files_with_confirmation : {e}")
            messagebox.showerror("Erreur de suppression", f"Erreur système pendant la suppression des fichiers :\n{e}")
            return {'removed': 0, 'failed': 0}
        except ValueError as e:
            log_error(f"Erreur de valeur dans delete_files_with_confirmation : {e}")
            messagebox.showerror("Erreur de suppression", f"Valeur invalide pendant la suppression des fichiers :\n{e}")
            return {'removed': 0, 'failed': 0}
        except TypeError as e:
            log_error(f"Erreur de type dans delete_files_with_confirmation : {e}")
            messagebox.showerror("Erreur de suppression", f"Erreur de type pendant la suppression des fichiers :\n{e}")
            return {'removed': 0, 'failed': 0}

    
    def delete_files_interactive(self):
        """
        Suppression interactive de fichiers : sélectionner les fichiers puis les supprimer
        """
        try:
            log_info("Démarrage du processus interactif de suppression de fichiers")
            
            selected_files = self.show_file_selection_dialog()
            
            if not selected_files:
                log_info("Aucun fichier sélectionné pour la suppression")
                return {'removed': 0, 'failed': 0}
            
            stats = self.delete_files_with_confirmation(selected_files)
            
            return stats
            
        except ValueError as e:
            log_error(f"Erreur de valeur dans delete_files_interactive : {e}")
            messagebox.showerror("Erreur", f"Valeur invalide pendant le processus de suppression de fichiers :\n{e}")
            return {'removed': 0, 'failed': 0}
        except IOError as e:
            log_error(f"Erreur d'E/S dans delete_files_interactive : {e}")
            messagebox.showerror("Erreur", f"Erreur d'E/S pendant le processus de suppression de fichiers :\n{e}")
            return {'removed': 0, 'failed': 0}
        except RuntimeError as e:
            log_error(f"Erreur d'exécution dans delete_files_interactive : {e}")
            messagebox.showerror("Erreur", f"Erreur d'exécution pendant le processus de suppression de fichiers :\n{e}")
            return {'removed': 0, 'failed': 0}
    
    @staticmethod
    def _format_size_compact(size_bytes):
        """
        Formate des octets en chaîne de taille compacte
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
            return "inconnu"