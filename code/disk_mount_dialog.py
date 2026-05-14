#!/usr/bin/env python3
"""
Module de dialogue de montage de disque
Fournit une boîte de dialogue pour sélectionner et monter des partitions non montées
"""


import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
from log_handler import log_info, log_error, log_warning
from utils import get_disk_list, is_system_disk, get_directory_space, format_bytes



class DiskMountDialog:
    """Boîte de dialogue pour sélectionner et monter des partitions non montées"""
    
    def __init__(self, parent):
        self.parent = parent
        self.result = None
        self.selected_partition = None
        self.mount_point = None
        
        # Create dialog window
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Sélectionner une partition pour le stockage de sortie")
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
        """Créer les widgets de la boîte de dialogue"""
        main_frame = ttk.Frame(self.dialog, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title and description
        title_label = ttk.Label(main_frame, text="Sélectionner une partition pour le stockage de la VM", 
                               font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        desc_label = ttk.Label(main_frame, 
                              text="Sélectionnez une partition non montée à monter et à utiliser pour stocker la VM convertie. "
                                   "Seules les partitions disposant déjà d’un système de fichiers sont affichées.",
                              wraplength=600)
        desc_label.pack(pady=(0, 15))
        
        # Partition selection frame
        partition_frame = ttk.LabelFrame(main_frame, text="Partitions non montées disponibles", padding="10")
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
        refresh_btn = ttk.Button(partition_frame, text="Actualiser la liste", command=self.refresh_unmounted_partitions)
        refresh_btn.pack(pady=(10, 0))
        
        # Mount point configuration
        mount_frame = ttk.LabelFrame(main_frame, text="Configuration du montage", padding="10")
        mount_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(mount_frame, text="Point de montage :").pack(anchor=tk.W)
        self.mount_point_var = tk.StringVar(value="/mnt/vm_storage")
        mount_entry = ttk.Entry(mount_frame, textvariable=self.mount_point_var, width=60)
        mount_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Partition information display
        info_frame = ttk.LabelFrame(main_frame, text="Informations sur la partition sélectionnée", padding="10")
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.info_text = tk.Text(info_frame, height=5, wrap=tk.WORD, state=tk.DISABLED,
                                font=("Consolas", 9), bg="#f8f8f8")
        self.info_text.pack(fill=tk.X)
        
        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        # Cancel button
        cancel_btn = ttk.Button(button_frame, text="Fermer", command=self.cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Mount & Select button (initially disabled)
        self.mount_btn = ttk.Button(button_frame, text="Sélectionner et monter", 
                                   command=self.mount_and_select, state=tk.DISABLED)
        self.mount_btn.pack(side=tk.RIGHT)
        
        # Browse for existing directory button
        browse_btn = ttk.Button(button_frame, text="Parcourir un dossier existant...", 
                               command=self.browse_existing_directory)
        browse_btn.pack(side=tk.LEFT)
        
        # Store partition data for reference
        self.partition_data = []
    
    def on_double_click(self, event=None):
        """Gérer le double-clic sur la liste des partitions - montage rapide"""
        if self.mount_btn['state'] == tk.NORMAL:
            self.mount_and_select()
    
    def browse_existing_directory(self):
        """Parcourir un dossier existant au lieu de monter une partition"""
        selected_dir = filedialog.askdirectory(
            parent=self.dialog,
            title="Sélectionner un dossier existant pour le stockage de la VM",
            initialdir="/mnt"
        )
        
        if selected_dir:
            self.result = selected_dir
            self.dialog.destroy()
    
    def get_unmounted_partitions(self):
        """Obtenir la liste des partitions non montées pouvant être montées"""
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
                log_warning("Impossible de lire /proc/mounts")
            
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
                                size = parts[2] if len(parts) > 2 else 'Inconnu'
                                label = parts[3] if len(parts) > 3 and parts[3] != '' else "Aucun libellé"
                                
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
                                            'parent_disk_label': disk.get('label', 'Aucun libellé'),
                                            'size_bytes': 0,  # Could calculate if needed
                                            'is_active': False
                                        }
                                        unmounted_partitions.append(partition_info)
                
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    log_warning(f"Impossible d'obtenir les informations de partition pour {device_path} : {str(e)}")
                    continue
            
            return unmounted_partitions
        
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            log_error(f"Erreur lors du traitement des données disque : {str(e)}")
            return []
        except (ImportError, NameError) as e:
            log_error(f"Erreur lors de l'import des modules ou fonctions requis : {str(e)}")
            return []
        except (RuntimeError, SystemError) as e:
            log_error(f"Erreur système lors de la récupération des partitions non montées : {str(e)}")
            return []
    
    def refresh_unmounted_partitions(self):
        """Actualiser la liste des partitions non montées"""
        try:
            log_info("Actualisation de la liste des partitions non montées")
            
            self.partition_data = self.get_unmounted_partitions()
            self.partition_listbox.delete(0, tk.END)
            
            if self.partition_data:
                for partition in self.partition_data:
                    fs_info = f" [{partition['has_filesystem']}]" if partition['has_filesystem'] else " [Aucun FS]"
                    display_text = f"{partition['device']} ({partition['size']}){fs_info}"
                    
                    if partition['label'] and partition['label'] not in ["Aucun libellé", "Inconnu", ""]:
                        display_text += f" - {partition['label']}"
                    
                    # Add parent disk info for clarity
                    parent_disk = partition['parent_disk'].replace('/dev/', '')
                    display_text += f" (sur {parent_disk})"
                    
                    self.partition_listbox.insert(tk.END, display_text)
                
                log_info(f"{len(self.partition_data)} partition(s) non montée(s) trouvée(s)")
            else:
                self.partition_listbox.insert(tk.END, "Aucune partition non montée avec système de fichiers disponible")
                log_warning("Aucune partition non montée trouvée")
                
        except (tk.TclError, AttributeError) as e:
            log_error(f"Erreur d'interface lors de l'actualisation de la liste des partitions : {str(e)}")
            self.partition_listbox.delete(0, tk.END)
            self.partition_listbox.insert(tk.END, "Erreur lors du chargement de la liste des partitions")
        except (KeyError, TypeError, ValueError) as e:
            log_error(f"Erreur de traitement des données lors de l'actualisation des partitions : {str(e)}")
            self.partition_listbox.delete(0, tk.END)
            self.partition_listbox.insert(tk.END, "Erreur lors du chargement de la liste des partitions")
    
    def on_partition_selected(self, event=None):
        """Gérer la sélection de partition"""
        selection = self.partition_listbox.curselection()
        if not selection or not self.partition_data:
            self.mount_btn.config(state=tk.DISABLED)
            self.selected_partition = None
            self.update_info_display("Aucune partition sélectionnée")
            return
        
        index = selection[0]
        if index >= len(self.partition_data):
            return
        
        # Check if this is an error message or actual partition
        selected_text = self.partition_listbox.get(index)
        if selected_text in ["Aucune partition non montée avec système de fichiers disponible", "Erreur lors du chargement de la liste des partitions"]:
            self.mount_btn.config(state=tk.DISABLED)
            self.selected_partition = None
            return
        
        self.selected_partition = self.partition_data[index]
        
        # Update info display
        info = f"Partition : {self.selected_partition['device']}\n"
        info += f"Taille : {self.selected_partition['size']}\n"
        info += f"Système de fichiers : {self.selected_partition['has_filesystem']}\n"
        
        if self.selected_partition['label'] not in ["Aucun libellé", "Inconnu", ""]:
            info += f"Libellé : {self.selected_partition['label']}\n"
        
        info += f"Disque parent : {self.selected_partition['parent_disk']}\n"
        info += f"Modèle du disque : {self.selected_partition['model']}\n"
        info += f"État : prêt à monter"
        
        self.mount_btn.config(state=tk.NORMAL)
        self.update_info_display(info)
    
    def update_info_display(self, text):
        """Mettre à jour l'affichage des informations"""
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(1.0, text)
        self.info_text.config(state=tk.DISABLED)
    
    def mount_and_select(self):
        """Monter la partition sélectionnée et renvoyer le point de montage"""
        if not self.selected_partition:
            messagebox.showwarning("Avertissement", "Veuillez d'abord sélectionner une partition", parent=self.dialog)
            return
        
        device_path = self.selected_partition['device']  # This is now a partition like /dev/sdb1
        mount_point = self.mount_point_var.get().strip()
        
        if not mount_point:
            messagebox.showwarning("Avertissement", "Veuillez indiquer un point de montage", parent=self.dialog)
            return
        
        # Validate mount point
        if not mount_point.startswith('/'):
            messagebox.showwarning("Avertissement", "Le point de montage doit être un chemin absolu (commençant par /)", 
                                parent=self.dialog)
            return
        
        # Confirm mounting
        confirmation_text = f"Monter {device_path} sur {mount_point} ?\n\n"
        confirmation_text += f"Partition : {device_path}\n"
        confirmation_text += f"Disque parent : {self.selected_partition['parent_disk']}\n"
        confirmation_text += f"Taille : {self.selected_partition['size']}\n"
        confirmation_text += f"Système de fichiers : {self.selected_partition['has_filesystem']}\n"
        
        if self.selected_partition['label'] not in ["Aucun libellé", "Inconnu", ""]:
            confirmation_text += f"Libellé : {self.selected_partition['label']}\n"
        
        confirmation_text += f"Point de montage : {mount_point}\n\n"
        confirmation_text += f"Le dossier du point de montage sera créé s'il n'existe pas."
        
        if not messagebox.askyesno("Confirmer le montage", confirmation_text, parent=self.dialog):
            return
        
        # Disable button during mounting
        try:
            if self.mount_btn.winfo_exists():
                self.mount_btn.config(state=tk.DISABLED, text="Montage...")
                self.dialog.update()
        except tk.TclError:
            pass  # Widget already destroyed
        
        try:
            # Create mount point if it doesn't exist
            os.makedirs(mount_point, exist_ok=True)
            
            # Attempt to mount
            log_info(f"Montage de {device_path} sur {mount_point}")
            
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
                log_info(f"{device_path} monté avec succès sur {mount_point}")
                
                # Check available space
                try:
                    space_info = get_directory_space(mount_point)
                    space_msg = f"Espace disponible : {format_bytes(space_info['free'])}"
                    
                    success_text = f"Partition montée avec succès !\n\n"
                    success_text += f"Partition : {device_path}\n"
                    success_text += f"Point de montage : {mount_point}\n"
                    success_text += f"Système de fichiers : {fs_type}\n"
                    success_text += f"{space_msg}\n\n"
                    success_text += f"Vous pouvez maintenant utiliser cet emplacement pour le stockage de la VM."
                    
                    # Check if dialog still exists before showing message
                    if self.dialog.winfo_exists():
                        messagebox.showinfo("Montage réussi", success_text, parent=self.dialog)
                except (OSError, IOError, AttributeError, KeyError) as e:
                    if self.dialog.winfo_exists():
                        messagebox.showinfo("Montage réussi", 
                                        f"Partition montée avec succès !\n\n"
                                        f"Partition : {device_path}\n"
                                        f"Point de montage : {mount_point}",
                                        parent=self.dialog)
                
                self.mount_point = mount_point
                self.result = mount_point
                
                # Destroy dialog only if it still exists
                if self.dialog.winfo_exists():
                    self.dialog.destroy()
                
            else:
                raise RuntimeError("La commande de montage a réussi mais le point de montage n'est pas monté")
        
        except subprocess.TimeoutExpired:
            error_msg = "Le montage a expiré. La partition n'est peut-être pas prête ou peut nécessiter une intervention manuelle."
            log_error(error_msg)
            if self.dialog.winfo_exists():
                messagebox.showerror("Échec du montage", error_msg, parent=self.dialog)
        
        except subprocess.CalledProcessError as e:
            error_msg = f"Impossible de monter la partition : {e.stderr.strip() if e.stderr else str(e)}"
            log_error(error_msg)
            if self.dialog.winfo_exists():
                messagebox.showerror("Échec du montage", error_msg, parent=self.dialog)
        
        except PermissionError:
            error_msg = "Permission refusée. Vous devrez peut-être exécuter l'application avec sudo ou vérifier les permissions de la partition."
            if self.dialog.winfo_exists():
                messagebox.showerror("Échec du montage", error_msg, parent=self.dialog)
        
        except (FileNotFoundError, NotADirectoryError) as e:
            error_msg = f"Erreur du système de fichiers : {str(e)}"
            log_error(error_msg)
            if self.dialog.winfo_exists():
                messagebox.showerror("Échec du montage", error_msg, parent=self.dialog)
        
        except OSError as e:
            error_msg = f"Erreur système pendant l'opération de montage : {str(e)}"
            log_error(error_msg)
            if self.dialog.winfo_exists():
                messagebox.showerror("Échec du montage", error_msg, parent=self.dialog)
        
        except (RuntimeError, SystemError, ValueError) as e:
            error_msg = f"Erreur inattendue lors du montage de la partition : {str(e)}"
            log_error(error_msg)
            if self.dialog.winfo_exists():
                messagebox.showerror("Échec du montage", error_msg, parent=self.dialog)
        
        except tk.TclError as e:
            # Dialog was destroyed while we were working
            log_warning(f"Boîte de dialogue détruite pendant l'opération de montage : {e}")
            # Still set the result in case caller needs it
            self.mount_point = mount_point
            self.result = mount_point
        
        finally:
            # Re-enable button only if it still exists
            try:
                if hasattr(self, 'mount_btn') and self.mount_btn.winfo_exists():
                    self.mount_btn.config(state=tk.NORMAL, text="Sélectionner et monter")
            except (tk.TclError, AttributeError):
                pass
    
    def cancel(self):
        """Annuler la boîte de dialogue"""
        self.result = None
        self.dialog.destroy()