import subprocess
import sys
import re
import time
import os
import shutil
from log_handler import log_error, log_info
from pathlib import Path


def run_command(command_list: list[str], raise_on_error: bool = True) -> str:
    try:
        result = subprocess.run(command_list, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.decode('utf-8').strip()
    except FileNotFoundError:
        log_error(f"Erreur : commande introuvable : {' '.join(command_list)}")
        if raise_on_error:
            sys.exit(2)
        else:
            raise
    except subprocess.CalledProcessError:
        log_error(f"Erreur : échec de l'exécution de la commande : {' '.join(command_list)}")
        if raise_on_error:
            sys.exit(1)
        else:
            raise
    except KeyboardInterrupt:
        log_error("Opération interrompue par l'utilisateur (Ctrl+C)")
        print("\nOpération interrompue par l'utilisateur (Ctrl+C)")
        sys.exit(130)  # Code de sortie standard pour SIGINT



def run_command_with_progress(command_list: list[str], progress_callback=None, stop_flag=None) -> str:
    """Exécuter une commande avec suivi de progression et prise en charge de l'annulation"""
    try:
        # Démarrer le processus
        process = subprocess.Popen(command_list, stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE, text=True)
        
        # Surveiller la progression
        while process.poll() is None:
            if stop_flag and stop_flag():
                # L'utilisateur a demandé l'annulation
                process.terminate()
                process.wait()
                raise KeyboardInterrupt("Opération annulée par l'utilisateur")
            
            # Mettre à jour la progression si une fonction de rappel est fournie
            if progress_callback:
                progress_callback()
            
            time.sleep(1)
        
        # Attendre la fin et récupérer la sortie
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command_list, stdout, stderr)
        
        return stdout.strip()
        
    except FileNotFoundError:
        log_error(f"Erreur : commande introuvable : {' '.join(command_list)}")
        raise
    except subprocess.CalledProcessError as e:
        log_error(f"Erreur : échec de l'exécution de la commande : {' '.join(command_list)}")
        if e.stderr:
            log_error(f"Sortie d'erreur : {e.stderr}")
        raise
    except KeyboardInterrupt:
        log_error("Opération interrompue par l'utilisateur")
        raise


def format_bytes(bytes_count: int) -> str:
    """Convertir des octets dans un format lisible par un humain"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} PB"


def get_directory_space(path: str) -> dict:
    """
    Obtenir les informations d'espace disponible pour un répertoire
    Retourne un dictionnaire avec 'total', 'used', 'free' en octets
    """
    try:
        stat = shutil.disk_usage(path)
        return {
            'total': stat.total,
            'used': stat.total - stat.free,
            'free': stat.free
        }
    except OSError as e:
        log_error(f"Erreur lors de la récupération de l'espace disque pour {path} : {str(e)}")
        return {'total': 0, 'used': 0, 'free': 0}


def get_disk_label(device: str) -> str:
    """
    Obtenir l'étiquette d'un périphérique disque avec lsblk.
    Retourne l'étiquette ou "Aucun libellé" si elle n'existe pas.
    """
    try:
        # Utiliser lsblk pour obtenir les informations d'étiquette pour toutes les partitions du périphérique
        output = run_command(["lsblk", "-o", "LABEL", "-n", f"/dev/{device}"], raise_on_error=False)
        if output and output.strip():
            # Obtenir la première étiquette non vide (en cas de partitions multiples)
            labels = [line.strip() for line in output.split('\n') if line.strip()]
            if labels:
                return labels[0]
        return "Aucun libellé"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Inconnu"



def get_mounted_devices() -> set:
    """
    Obtenir l'ensemble des chemins de périphériques actuellement montés et de leurs disques de base
    Retourne à la fois les chemins des partitions et ceux des disques de base
    """
    mounted_devices = set()
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 1 and parts[0].startswith('/dev/'):
                    device = parts[0]
                    mounted_devices.add(device)
                    # Ajouter aussi le nom du disque de base pour la vérification des partitions
                    base_device = get_base_device_from_partition(device)
                    if base_device != device:
                        mounted_devices.add(base_device)
    except (IOError, OSError) as e:
        log_error(f"Impossible de lire /proc/mounts : {str(e)}")
    
    return mounted_devices


def get_base_device_from_partition(device_path: str) -> str:
    """
    Obtenir le périphérique de base à partir d'un chemin de partition
    Exemples : 
        '/dev/sda1' -> '/dev/sda'
        '/dev/nvme0n1p1' -> '/dev/nvme0n1'
        '/dev/sda' -> '/dev/sda' (inchangé)
    """
    try:
        # Gérer les périphériques nvme (ex. : /dev/nvme0n1p1 -> /dev/nvme0n1)
        if 'nvme' in device_path and 'p' in device_path:
            match = re.match(r'(/dev/nvme\d+n\d+)', device_path)
            if match:
                return match.group(1)
        
        # Gérer les périphériques classiques (ex. : /dev/sda1 -> /dev/sda)
        match = re.match(r'(/dev/[a-zA-Z]+)', device_path)
        if match:
            return match.group(1)
        
        # Si aucun motif ne correspond, retourner l'original
        return device_path
        
    except re.error as e:
        log_error(f"Motif regex invalide lors du traitement du chemin de périphérique '{device_path}' : {str(e)}")
        return device_path
    except TypeError as e:
        log_error(f"Type de chemin de périphérique invalide fourni '{type(device_path)}' : {str(e)}")
        return device_path
    except ValueError as e:
        log_error(f"Format de chemin de périphérique invalide '{device_path}' : {str(e)}")
        return device_path


def has_mounted_partitions(device_path: str) -> bool:
    """
    Vérifier si un disque a des partitions montées
    Args:
        device_path: Chemin vers le périphérique (ex. : /dev/sda)
    Returns:
        bool: True si au moins une partition est montée, sinon False
    """
    try:
        mounted_devices = get_mounted_devices()
        
        # Vérifier si le périphérique lui-même est monté
        if device_path in mounted_devices:
            return True
        
        # Obtenir toutes les partitions de ce périphérique
        try:
            result = subprocess.run(['lsblk', '-n', '-o', 'NAME', device_path], 
                                  capture_output=True, text=True, check=True)
            
            lines = result.stdout.strip().split('\n')
            device_name = device_path.replace('/dev/', '')
            
            for line in lines:
                if line.strip():
                    partition_name = line.strip()
                    # Supprimer les caractères d'arborescence de la sortie de lsblk
                    partition_name = partition_name.lstrip('â"œâ"€â""â"‚ â"€')
                    partition_path = f"/dev/{partition_name}"
                    
                    # Ignorer la ligne du périphérique principal
                    if partition_name == device_name:
                        continue
                        
                    # Vérifier si cette partition est montée
                    if partition_path in mounted_devices:
                        return True
        
        except subprocess.CalledProcessError as e:
            log_error(f"Erreur lors de l'exécution de lsblk pour {device_path} : {e.stderr}")
            return False
        except FileNotFoundError as e:
            log_error(f"Commande lsblk introuvable : {str(e)}")
            return False
        
        return False
        
    except OSError as e:
        log_error(f"Erreur système lors de la vérification des partitions montées pour {device_path} : {str(e)}")
        return False
    except ValueError as e:
        log_error(f"Format de chemin de périphérique invalide lors de la vérification des montages : {str(e)}")
        return False
    except TypeError as e:
        log_error(f"Type invalide pour le paramètre device_path : {str(e)}")
        return False


def check_filesystem(device_path: str) -> str:
    """Vérifier si le périphérique possède un système de fichiers montable et retourner son type"""
    try:
        # Vérifier le système de fichiers avec lsblk
        result = subprocess.run(['lsblk', '-n', '-o', 'FSTYPE', device_path], 
                              capture_output=True, text=True, check=True)
        
        filesystems = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
        
        # Systèmes de fichiers montables courants
        mountable_fs = ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'ntfs', 'fat32', 'vfat', 'exfat']
        
        for fs in filesystems:
            if fs.lower() in mountable_fs:
                return fs
        
        return None
    
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def mount_disk(device_path: str, mount_point: str, filesystem_type: str = None) -> bool:
    """
    Monter un disque sur un point de montage spécifié
    
    Args:
        device_path: Chemin vers le périphérique (ex. : /dev/sdb1)
        mount_point: Répertoire de montage
        filesystem_type: Type de système de fichiers facultatif
    
    Returns:
        bool: True si le montage a réussi, sinon False
    """
    try:
        # Créer le point de montage s'il n'existe pas
        os.makedirs(mount_point, exist_ok=True)
        
        # Construire la commande de montage
        mount_cmd = ['sudo', 'mount']
        
        if filesystem_type:
            if filesystem_type.lower() == 'ntfs':
                mount_cmd.extend(['-t', 'ntfs-3g'])
            else:
                mount_cmd.extend(['-t', filesystem_type])
        
        mount_cmd.extend([device_path, mount_point])
        
        # Exécuter la commande de montage
        result = subprocess.run(mount_cmd, capture_output=True, text=True, check=True)
        
        # Vérifier que le montage a réussi
        if os.path.ismount(mount_point):
            log_info(f"Montage réussi de {device_path} sur {mount_point}")
            return True
        else:
            log_error(f"La commande de montage a réussi mais {mount_point} n'est pas monté")
            return False
    
    except subprocess.CalledProcessError as e:
        error_msg = f"Échec du montage de {device_path} : {e.stderr if e.stderr else str(e)}"
        log_error(error_msg)
        return False
    
    except PermissionError as e:
        log_error(f"Permission refusée lors du montage de {device_path} : {str(e)}")
        return False
    
    except Exception as e:
        log_error(f"Erreur inattendue lors du montage de {device_path} : {str(e)}")
        return False


def unmount_disk(mount_point: str) -> bool:
    """
    Démonter un disque à partir du point de montage spécifié
    
    Args:
        mount_point: Répertoire à démonter
    
    Returns:
        bool: True si le démontage a réussi, sinon False
    """
    try:
        # Exécuter la commande de démontage
        result = subprocess.run(['sudo', 'umount', mount_point], 
                              capture_output=True, text=True, check=True)
        
        # Vérifier que le démontage a réussi
        if not os.path.ismount(mount_point):
            log_info(f"Démontage réussi de {mount_point}")
            return True
        else:
            log_error(f"La commande de démontage a réussi mais {mount_point} est toujours monté")
            return False
    
    except subprocess.CalledProcessError as e:
        error_msg = f"Échec du démontage de {mount_point} : {e.stderr if e.stderr else str(e)}"
        log_error(error_msg)
        return False
    
    except Exception as e:
        log_error(f"Erreur inattendue lors du démontage de {mount_point} : {str(e)}")
        return False


def get_unmounted_disks() -> list[dict]:
    """
    Obtenir la liste des disques non montés pouvant être montés
    Retourne une liste de dictionnaires de disques avec un champ supplémentaire 'has_filesystem'
    """
    try:
        # Obtenir tous les disques
        all_disks = get_disk_list()
        unmounted_disks = []
        
        # Filtrer les disques montés et les disques système
        for disk in all_disks:
            device_path = disk['device']
            
            # Ignorer si c'est un disque système/actif ou un disque monté
            if disk.get('is_active', False) or disk.get('is_mounted', False) or is_system_disk(device_path):
                continue
            
            # Vérifier si le disque possède un système de fichiers que l'on peut monter
            has_filesystem = check_filesystem(device_path)
            disk['has_filesystem'] = has_filesystem
            unmounted_disks.append(disk)
        
        return unmounted_disks
    
    except Exception as e:
        log_error(f"Erreur lors de la récupération des disques non montés : {str(e)}")
        return []


def get_disk_usage_info(device: str) -> dict:
    """
    Obtenir les informations d'utilisation du disque pour une meilleure estimation de l'espace
    Retourne un dictionnaire avec les informations d'utilisation du système de fichiers
    """
    try:
        # Essayer d'obtenir les informations d'utilisation du système de fichiers
        result = subprocess.run(['df', device], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 6:
                total = int(parts[1]) * 1024  # Convertir de Ko en octets
                used = int(parts[2]) * 1024
                available = int(parts[3]) * 1024
                
                return {
                    'total': total,
                    'used': used,
                    'available': available,
                    'usage_percent': (used / total * 100) if total > 0 else 0
                }
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, IndexError):
        # Si nous ne pouvons pas obtenir les infos du système de fichiers, essayer d'estimer à partir des partitions
        try:
            # Obtenir toutes les partitions de ce périphérique et essayer d'additionner leur utilisation
            result = subprocess.run(['lsblk', '-n', '-o', 'NAME', device], capture_output=True, text=True, check=True)
            partitions = []
            for line in result.stdout.strip().split('\n'):
                partition = line.strip()
                if partition and partition != device.replace('/dev/', ''):
                    partitions.append(f"/dev/{partition}")
            
            total_used = 0
            for partition in partitions:
                try:
                    df_result = subprocess.run(['df', partition], capture_output=True, text=True, check=True)
                    df_lines = df_result.stdout.strip().split('\n')
                    if len(df_lines) > 1:
                        df_parts = df_lines[1].split()
                        if len(df_parts) >= 3:
                            total_used += int(df_parts[2]) * 1024  # Convertir de Ko en octets
                except subprocess.CalledProcessError:
                    continue
            
            if total_used > 0:
                disk_info = get_disk_info(device)
                total_size = disk_info['size_bytes']
                return {
                    'total': total_size,
                    'used': total_used,
                    'available': total_size - total_used,
                    'usage_percent': (total_used / total_size * 100) if total_size > 0 else 0
                }
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    
    return {
        'total': 0,
        'used': 0, 
        'available': 0,
        'usage_percent': 0
    }


def get_disk_info(device: str) -> dict:
    """Obtenir des informations détaillées sur un disque"""
    try:
        # Obtenir la taille avec blockdev
        result = subprocess.run(['blockdev', '--getsize64', device], 
                              capture_output=True, text=True, check=True)
        size_bytes = int(result.stdout.strip())
        
        # Obtenir les informations de modèle avec lsblk
        result = subprocess.run(['lsblk', '-d', '-n', '-o', 'MODEL', device], 
                              capture_output=True, text=True, check=True)
        model = result.stdout.strip() or "Inconnu"
        
        # Obtenir l'étiquette
        device_name = device.replace('/dev/', '')
        label = get_disk_label(device_name)
        
        return {
            'device': device,
            'size_bytes': size_bytes,
            'size_human': format_bytes(size_bytes),
            'model': model,
            'label': label
        }
        
    except subprocess.CalledProcessError as e:
        log_error(f"Échec de l'exécution de la commande pour {device} : {e.stderr}")
    except FileNotFoundError as e:
        log_error(f"Commande requise introuvable : {str(e)}")
    except ValueError as e:
        log_error(f"Valeur invalide reçue lors du traitement des informations du disque {device} : {str(e)}")
    except OSError as e:
        log_error(f"Erreur système lors de l'accès au disque {device} : {str(e)}")
    except TypeError as e:
        log_error(f"Type invalide fourni pour les paramètres d'information du disque : {str(e)}")
    
    # Retourner des valeurs par défaut si une erreur s'est produite
    return {
        'device': device,
        'size_bytes': 0,
        'size_human': "Inconnu",
        'model': "Inconnu",
        'label': "Inconnu"
    }

def get_active_disk():
    """
    Détecter le périphérique actif supportant le système de fichiers racine.
    Retourne toujours une liste de noms de disques de base (ex. : ['nvme0n1', 'sda']) ou None pour conserver la cohérence.
    Utilise la logique LVM si le périphérique racine est un volume logique (/dev/mapper/),
    sinon utilise la logique normale de détection de disque, y compris la détection d'un média live boot.
    Tous les noms de périphériques retournés sont résolus vers leurs noms de disques de base.
    """
    try:
        # Initialiser l'ensemble des périphériques pour collecter tous les périphériques actifs
        devices = set()
        live_boot_found = False
        
        # Step 1: Check /proc/mounts for all mounted devices
        with open('/proc/mounts', 'r') as f:
            mounts_content = f.read()
            
            # Look for root filesystem mount
            root_device = None
            for line in mounts_content.split('\n'):
                if line.strip() and ' / ' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        root_device = parts[0]
                        break

        # Step 2: Handle special live boot cases where root is not a real device
        if not root_device or root_device in ['rootfs', 'overlay', 'aufs', '/dev/root']:
            
            # In live boot, look for the actual boot media in /proc/mounts
            with open('/proc/mounts', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 6:
                        device = parts[0]
                        mount_point = parts[1]
                        
                        # Look for common live boot mount points
                        if any(keyword in mount_point for keyword in ['/run/live', '/lib/live', '/live/', '/cdrom']):
                            match = re.search(r'/dev/([a-zA-Z]+\d*[a-zA-Z]*\d*)', device)
                            if match:
                                device_name = match.group(1)
                                base_device = get_base_disk(device_name)
                                devices.add(base_device)
                                live_boot_found = True
                        
                        # Also check for USB/removable media patterns
                        elif device.startswith('/dev/') and any(keyword in device for keyword in ['sd', 'nvme', 'mmc']):
                            # Check if this looks like a removable device by checking mount point
                            if '/media' in mount_point or '/mnt' in mount_point or '/run' in mount_point:
                                match = re.search(r'/dev/([a-zA-Z]+\d*[a-zA-Z]*\d*)', device)
                                if match:
                                    device_name = match.group(1)
                                    base_device = get_base_disk(device_name)
                                    devices.add(base_device)
            
            # If we still haven't found anything, fall back to df command analysis
            if not devices:
                # Use df command instead of viewing /proc/mounts
                try:
                    output = run_command(["df", "-h"])
                    lines = output.strip().split('\n')
                    
                    for line in lines[1:]:  # Skip header
                        parts = line.split()
                        if len(parts) >= 6:
                            device = parts[0]
                            mount_point = parts[5]
                            
                            # Look for any mounted storage devices
                            if device.startswith('/dev/') and any(keyword in device for keyword in ['sd', 'nvme', 'mmc']):
                                match = re.search(r'/dev/([a-zA-Z]+\d*[a-zA-Z]*\d*)', device)
                                if match:
                                    device_name = match.group(1)
                                    base_device = get_base_disk(device_name)
                                    devices.add(base_device)
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    log_error(f"Erreur lors de l'exécution de la commande df : {str(e)}")
        
        else:
            # Step 3: Handle normal root device (installed system)
            # Check if this is LVM/device mapper
            if '/dev/mapper/' in root_device or '/dev/dm-' in root_device:
                # LVM resolution - map to physical drives
                active_physical_drives = get_physical_drives_for_logical_volumes([root_device])
                
                # Add physical drives to devices set, resolving to base names
                for drive in active_physical_drives:
                    base_device = get_base_disk(drive)
                    devices.add(base_device)
                    
            else:
                # Regular disk - extract device name with improved regex for NVMe
                match = re.search(r'/dev/([a-zA-Z]+\d*[a-zA-Z]*\d*)', root_device)
                if match:
                    device_name = match.group(1)
                    base_device = get_base_disk(device_name)
                    devices.add(base_device)
            
            # Also check for live boot media even in normal systems
            try:
                output = run_command(["df", "-h"])
                lines = output.strip().split('\n')
                
                for line in lines[1:]:  # Skip header line
                    parts = line.split()
                    if len(parts) >= 6:
                        device = parts[0]
                        mount_point = parts[5]
                        
                        # Check for live boot mount points
                        if "/run/live" in mount_point or "/lib/live" in mount_point:
                            match = re.search(r'/dev/([a-zA-Z]+\d*[a-zA-Z]*\d*)', device)
                            if match:
                                device_name = match.group(1)
                                base_device = get_base_disk(device_name)
                                devices.add(base_device)
                                live_boot_found = True
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                log_info(f"Impossible de vérifier les périphériques live boot : {str(e)}")


        # Step 4: Return logic
        if devices:
            device_list = list(devices)
            return device_list
        else:
            log_error("Aucun périphérique actif trouvé")
            return None

    except FileNotFoundError as e:
        log_error(f"Fichier requis introuvable : {str(e)}")
        return None
    except PermissionError as e:
        log_error(f"Permission refusée lors de l'accès aux fichiers système : {str(e)}")
        return None
    except OSError as e:
        log_error(f"Erreur système lors de l'accès aux informations système : {str(e)}")
        return None
    except subprocess.CalledProcessError as e:
        log_error(f"Erreur lors de l'exécution de la commande : {str(e)}")
        return None
    except (IndexError, ValueError) as e:
        log_error(f"Erreur lors de l'analyse de la sortie de commande : {str(e)}")
        return None
    except re.error as e:
        log_error(f"Erreur de motif regex : {str(e)}")
        return None
    except KeyboardInterrupt:
        log_error("Opération interrompue par l'utilisateur")
        return None
    except UnicodeDecodeError as e:
        log_error(f"Erreur lors du décodage du contenu du fichier : {str(e)}")
        return None
    except MemoryError:
        log_error("Mémoire insuffisante pour traiter les informations des périphériques")
        return None


def get_physical_drives_for_logical_volumes(active_devices: list) -> set:
    """
    Mapper les volumes logiques (LVM, etc.) à leurs disques physiques sous-jacents.
    
    Args:
        active_devices: Liste des chemins des périphériques actifs (ex. : ['/dev/mapper/rocket--vg-root'])
    
    Returns:
        Ensemble des noms des disques physiques (ex. : {'nvme0n1', 'sda'})
    """
    if not active_devices:
        return set()
    
    physical_drives = set()
    
    try:
        try:
            output = run_command([
                "lsblk", 
                "-d",  # Afficher uniquement les périphériques, pas les partitions
                "-n",  # Sans en-têtes
                "-o", "NAME"  # Uniquement les noms des périphériques
            ], raise_on_error=False)
            
            physical_device_names = []
            for line in output.strip().split('\n'):
                if line.strip():
                    physical_device_names.append(line.strip())
        
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log_error(f"Impossible d'obtenir la liste des périphériques physiques : {str(e)}")
            return set()
        
        for physical_device in physical_device_names:
            try:
                # Utiliser lsblk pour obtenir l'arborescence complète du périphérique pour ce disque physique
                # -o NAME affiche les noms des périphériques, -l affiche au format liste, -n supprime les en-têtes
                output = run_command([
                    "lsblk", 
                    f"/dev/{physical_device}", 
                    "-o", "NAME", 
                    "-l", 
                    "-n"
                ], raise_on_error=False)
                
                # Analyser la sortie pour obtenir tous les périphériques de l'arborescence
                device_tree = []
                for line in output.strip().split('\n'):
                    if line.strip():
                        device_name = line.strip()
                        # Ajouter avec et sans le préfixe /dev/ pour la comparaison
                        device_tree.append(f"/dev/{device_name}")
                        device_tree.append(device_name)
                
                # Vérifier si un périphérique actif est dans l'arborescence de ce disque physique
                for active_device in active_devices:
                    # Gérer différents formats de noms de périphériques
                    active_variants = [
                        active_device,
                        active_device.replace('/dev/', ''),
                        active_device.replace('/dev/mapper/', '')
                    ]
                    
                    # Vérifier si une variante du périphérique actif est dans l'arborescence
                    for variant in active_variants:
                        if variant in device_tree:
                            physical_drives.add(physical_device)
                            log_info(f"Périphérique actif '{active_device}' trouvé sur le disque physique '{physical_device}'")
                            break
                    
                    if physical_device in physical_drives:
                        break
                        
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                # Ignorer ce périphérique physique si lsblk échoue
                log_error(f"Impossible d'interroger l'arborescence du périphérique pour {physical_device} : {str(e)}")
                continue
                
    except (AttributeError, TypeError) as e:
        log_error(f"Erreur lors du traitement des structures de données des périphériques : {str(e)}")
    except MemoryError:
        log_error("Mémoire insuffisante pour traiter la correspondance des volumes logiques")
    except OSError as e:
        log_error(f"Erreur système pendant la correspondance des volumes logiques : {str(e)}")
    
    return physical_drives


def get_disk_list() -> list[dict]:
    """
    Obtenir la liste des disques disponibles sous forme de données structurées.
    Retourne une liste de dictionnaires contenant les informations sur les disques.
    Chaque dictionnaire contient : 'device', 'size', 'model', 'size_bytes', 'label', 'is_active' et 'is_mounted'.
    """
    try:
        # Utiliser une spécification de colonnes plus explicite avec l'option -o et -n pour ignorer l'en-tête
        output = run_command(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,MODEL", "-n", "-b"])
        
        if not output:
            # Repli sur une commande plus simple si la première n'a retourné aucun résultat
            output = run_command(["lsblk", "-d", "-o", "NAME,SIZE", "-n", "-b"])
            if not output:
                log_info("Aucun disque détecté. Assurez-vous que le programme est exécuté avec les permissions appropriées.")
                return []
        
        # Obtenir les disques actifs pour les marquer - mais gérer le cas où cela échoue
        try:
            active_disks = get_active_disk() or []
            active_disk_names = set()
            for active_device in active_disks:
                if isinstance(active_device, str):
                    # Supprimer le préfixe /dev/ s'il est présent
                    base_name = active_device.replace('/dev/', '')
                    active_disk_names.add(base_name)
        except Exception as e:
            # Si la récupération des disques actifs échoue, continuer sans en marquer comme actifs
            log_error(f"Impossible de déterminer les disques actifs : {str(e)}")
            active_disk_names = set()
        
        # Analyser la sortie de la commande lsblk
        disks = []
        for line in output.strip().split('\n'):
            if not line.strip():
                continue
                
            # Découper la ligne tout en conservant le nom du modèle qui peut contenir des espaces
            parts = line.strip().split(maxsplit=3)
            device = parts[0]
            
            # S'assurer que nous avons au moins NAME et SIZE
            if len(parts) >= 2:
                try:
                    size_bytes = int(parts[1])
                    size_human = format_bytes(size_bytes)
                except (ValueError, IndexError):
                    size_bytes = 0
                    size_human = "Inconnu"
                
                # MODEL peut être absent, définir à "Inconnu" dans ce cas
                model = parts[3] if len(parts) > 3 else "Inconnu"
                
                # Obtenir l'étiquette du disque
                label = get_disk_label(device)
                
                # Vérifier si ce disque est actif (disque système)
                is_active = device in active_disk_names
                
                # Vérifier si ce disque a des partitions montées
                device_path = f"/dev/{device}"
                is_mounted = has_mounted_partitions(device_path)
                
                disks.append({
                    "device": device_path,
                    "size": size_human,
                    "size_bytes": size_bytes,
                    "model": model,
                    "label": label,
                    "is_active": is_active,
                    "is_mounted": is_mounted
                })
        return disks
    except FileNotFoundError as e:
        log_error(f"Erreur : commande introuvable : {str(e)}")
        return []
    except subprocess.CalledProcessError as e:
        log_error(f"Erreur lors de l'exécution de la commande : {str(e)}")
        return []
    except (IndexError, ValueError) as e:
        log_error(f"Erreur lors de l'analyse des informations disque : {str(e)}")
        return []
    except KeyboardInterrupt:
        log_error("Liste des disques interrompue par l'utilisateur")
        return []


def get_base_disk(device_name: str) -> str:
    """
    Extraire le nom du disque de base à partir d'un nom de périphérique.
    Exemples : 
        'nvme0n1p1' -> 'nvme0n1'
        'sda1' -> 'sda'
        'nvme0n1' -> 'nvme0n1'
    """
    try:
        # Gérer les périphériques nvme (ex. : nvme0n1p1 -> nvme0n1)
        if 'nvme' in device_name:
            match = re.match(r'(nvme\d+n\d+)', device_name)
            if match:
                return match.group(1)
        
        # Gérer les périphériques classiques (ex. : sda1 -> sda)
        match = re.match(r'([a-zA-Z/]+[a-zA-Z])', device_name)
        if match:
            return match.group(1)
        
        # Si aucun motif ne correspond, retourner l'original
        return device_name
        
    except re.error as e:
        log_error(f"Motif regex invalide lors du traitement du nom de périphérique '{device_name}' : {str(e)}")
    except TypeError as e:
        log_error(f"Type invalide pour le paramètre device_name : {str(e)}")
    except ValueError as e:
        log_error(f"Format de nom de périphérique invalide '{device_name}' : {str(e)}")
    
    return device_name


def is_system_disk(device_path: str) -> bool:
    """
    Vérifier si le chemin de périphérique donné correspond à un disque système (actif/monté).
    Args:
        device_path: Chemin complet du périphérique (ex. : '/dev/sda')
    Returns:
        bool: True si c'est un disque système, sinon False
    """
    try:
        # Extraire le nom du périphérique sans le préfixe /dev/
        device_name = device_path.replace('/dev/', '')
        
        # Obtenir la liste des disques actifs
        active_disks = get_active_disk()
        if active_disks:
            return device_name in active_disks
        
        return False
        
    except TypeError as e:
        log_error(f"Type invalide pour le chemin de périphérique '{type(device_path)}' : {str(e)}")
    except ValueError as e:
        log_error(f"Format de chemin de périphérique invalide '{device_path}' : {str(e)}")
    except OSError as e:
        log_error(f"Erreur système lors de la vérification de l'état disque système pour {device_path} : {str(e)}")
    
    return False