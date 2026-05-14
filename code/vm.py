import subprocess
import os
import json
import re
from log_handler import log_error, log_info
from utils import (
    format_bytes, 
    get_disk_info, 
    get_directory_space,
    get_disk_usage_info
)


def check_qemu_tools() -> tuple[bool, str]:
    """Vérifier si les outils QEMU requis sont disponibles"""
    tools = ['qemu-img', 'dd']
    missing = []
    
    for tool in tools:
        try:
            subprocess.run([tool, '--version'], capture_output=True, check=True)
        except FileNotFoundError:
            missing.append(tool)
        except subprocess.CalledProcessError as e:
            missing.append(f"{tool} (erreur : {e})")
    
    if missing:
        return False, f"Outils requis manquants : {', '.join(missing)}"
    return True, "Tous les outils requis sont disponibles"



def verify_vm_image(qcow2_path: str) -> dict:
    """
    Vérifier une image VM qcow2 et récupérer ses informations
    Retourne un dictionnaire avec les résultats de vérification et les informations sur l'image
    """
    try:
        # Utiliser qemu-img info pour obtenir les détails de l'image
        result = subprocess.run(['qemu-img', 'info', '--output=json', qcow2_path], 
                               capture_output=True, text=True, check=True)
        
        info_data = json.loads(result.stdout)
        
        return {
            'success': True,
            'virtual_size': info_data.get('virtual-size', 0),
            'actual_size': info_data.get('actual-size', 0),
            'format': info_data.get('format', 'unknown'),
            'compressed': info_data.get('compressed', False)
        }
    except subprocess.CalledProcessError as e:
        log_error(f"Échec de qemu-img info : {e}")
    except FileNotFoundError as e:
        log_error(f"qemu-img introuvable : {e}")
    except json.JSONDecodeError as e:
        log_error(f"Échec de l'analyse de la sortie de qemu-img : {e}")
    except KeyError as e:
        log_error(f"Champ requis manquant dans la sortie de qemu-img : {e}")
        
    # Repli sur la taille du fichier si qemu-img info échoue
    try:
        actual_size = os.path.getsize(qcow2_path)
        return {
            'success': False,
            'virtual_size': 0,
            'actual_size': actual_size,
            'format': 'qcow2',
            'compressed': True
        }
    except OSError as e:
        log_error(f"Échec de la récupération de la taille du fichier : {e}")
        return {
            'success': False,
            'virtual_size': 0,
            'actual_size': 0,
            'format': 'unknown',
            'compressed': False
        }


def check_output_space(output_path: str, source_disk: str) -> tuple[bool, str]:
    """
    Vérification améliorée de l'espace qui tient compte de l'utilisation réelle du disque
    Args:
        output_path: Chemin vers le répertoire de sortie
        source_disk: Chemin vers le disque source ou taille du disque en octets (pour compatibilité ascendante)
    Returns:
        tuple: (espace_suffisant, message)
    """
    try:
        # S'assurer que le répertoire existe
        os.makedirs(output_path, exist_ok=True)
        
        # Obtenir l'espace disponible dans le répertoire de sortie
        space_info = get_directory_space(output_path)
        
        # Gérer à la fois les chemins de disque et les tailles pour la compatibilité ascendante
        if isinstance(source_disk, str) and source_disk.startswith('/dev/'):
            # C'est un chemin de disque - récupérer les infos disque et l'utilisation
            disk_info = get_disk_info(source_disk)
            disk_size = disk_info['size_bytes']
            usage_info = get_disk_usage_info(source_disk)
            
            if usage_info['used'] > 0:
                # Utiliser l'utilisation réelle du système de fichiers + 30 % de surcharge pour les variations de métadonnées/compression
                estimated_size = int(usage_info['used'] * 1.3)
                estimation_method = "utilisation du système de fichiers + 30 % de surcharge"
            else:
                # Repli sur une estimation prudente (50 % de la taille du disque)
                estimated_size = int(disk_size * 0.5)
                estimation_method = "50 % de la taille totale du disque (estimation prudente)"
            
            message = (
                f"Taille du disque source : {format_bytes(disk_size)}\n"
                f"Espace de sortie disponible : {format_bytes(space_info['free'])}\n"
                f"Taille estimée de la VM : {format_bytes(estimated_size)} ({estimation_method})\n"
            )
            
            if usage_info['used'] > 0:
                message += f"Utilisation du système de fichiers : {format_bytes(usage_info['used'])} ({usage_info['usage_percent']:.1f}%)\n"
        
        else:
            # Compatibilité ascendante : source_disk est en fait la taille du disque en octets
            try:
                disk_size = int(source_disk) if isinstance(source_disk, (int, str)) else source_disk
            except ValueError as e:
                raise ValueError(f"Valeur de taille de disque invalide : {e}")
                
            estimated_size = int(disk_size * 0.5)  # Taux de compression de 50 %
            estimation_method = "taux de compression de 50 % (estimation prudente)"
            
            message = (
                f"Taille du disque source : {format_bytes(disk_size)}\n"
                f"Espace de sortie disponible : {format_bytes(space_info['free'])}\n"
                f"Taille estimée de la VM : {format_bytes(estimated_size)} ({estimation_method})\n"
            )
        
        # Ajouter une marge de sécurité supplémentaire de 10 %
        required_space = int(estimated_size * 1.1)
        has_space = space_info['free'] >= required_space
        
        message += f"Espace requis (avec marge de 10 %) : {format_bytes(required_space)}\n"
        message += f"État : {'Espace suffisant' if has_space else 'Espace insuffisant'}"
        
        return has_space, message
        
    except OSError as e:
        return False, f"Erreur lors de la vérification de l'espace : {e}"
    except ValueError as e:
        return False, f"Valeur d'entrée invalide : {e}"
    except TypeError as e:
        return False, f"Erreur de type dans les calculs : {e}"



def validate_vm_name(name: str) -> tuple[bool, str]:
    """Valider le nom de la VM pour la compatibilité avec le système de fichiers"""
    if not name:
        return False, "Le nom de la VM ne peut pas être vide"
    
    # Vérifier les caractères invalides
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        if char in name:
            return False, f"Le nom de la VM contient un caractère invalide : {char}"
    
    # Vérifier la longueur
    if len(name) > 100:
        return False, "Le nom de la VM est trop long (100 caractères maximum)"
    
    # Vérifier les noms réservés
    reserved = ['con', 'prn', 'aux', 'nul', 'com1', 'com2', 'com3', 'com4', 
               'com5', 'com6', 'com7', 'com8', 'com9', 'lpt1', 'lpt2', 'lpt3', 
               'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9']
    if name.lower() in reserved:
        return False, f"Le nom de VM '{name}' est réservé"
    
    return True, "Nom valide"



def parse_qemu_progress(line: str) -> float:
    """
    Analyser la sortie de progression de qemu-img et retourner le pourcentage
    qemu-img -p produit des lignes comme : (45.67/100%)\r
    """
    try:
        # Nettoyer la ligne de tous les caractères de contrôle et espaces
        clean_line = line.replace('\r', '').replace('\n', '').strip()
        
        # Rechercher un motif comme (XX.XX/100%) ou (XX/100%)
        match = re.search(r'\((\d+(?:\.\d+)?)/100%\)', clean_line)
        if match:
            return float(match.group(1))
        
        # Motif alternatif : (XX.XX%)
        match = re.search(r'\((\d+(?:\.\d+)?)%\)', clean_line)
        if match:
            return float(match.group(1))
            
        # Rechercher un pourcentage isolé : XX.XX%
        match = re.search(r'(\d+(?:\.\d+)?)%', clean_line)
        if match:
            return float(match.group(1))
            
    except ValueError as e:
        log_error(f"Échec de l'analyse de la valeur de progression : {e}")
    except AttributeError as e:
        log_error(f"Échec de la correspondance du motif de progression : {e}")
    
    return None


def create_vm_from_disk(source_disk: str, output_path: str, vm_name: str, 
                       progress_callback=None, stop_flag=None) -> str:
    """
    Convertir un disque physique en VM qcow2 avec allocation clairsemée (seules les données utilisées)
    Args:
        source_disk: Chemin du disque source (par ex., /dev/sda)
        output_path: Répertoire où enregistrer les fichiers VM
        vm_name: Nom des fichiers de la VM
        progress_callback: Fonction à appeler pour les mises à jour de progression
        stop_flag: Fonction qui retourne True si l'opération doit être arrêtée
    Returns:
        str: Chemin du fichier qcow2 créé
    """
    try:
        # Créer le répertoire de sortie
        os.makedirs(output_path, exist_ok=True)
        
        # Générer les chemins de fichiers
        qcow2_path = os.path.join(output_path, f"{vm_name}.qcow2")
        temp_qcow2_path = os.path.join(output_path, f"{vm_name}_temp.qcow2")
        
        log_info(f"Démarrage de la conversion P2V : {source_disk} -> {qcow2_path}")
        
        # Obtenir la taille du disque d'origine
        disk_info = get_disk_info(source_disk)
        original_size = disk_info['size_bytes']
        
        log_info(f"Taille du disque d'origine : {format_bytes(original_size)}")
        
        # Étape 1 : convertir directement le disque physique en qcow2 avec allocation clairsemée
        log_info("Étape 1 : conversion du disque avec allocation clairsemée...")
        if progress_callback:
            progress_callback(0, "Initialisation de la conversion...")
        
        # Convertir directement le disque physique en qcow2 avec allocation clairsemée et compression
        qemu_convert_cmd = [
            'qemu-img', 'convert',
            '-f', 'raw',                    # Format d'entrée
            '-O', 'qcow2',                  # Format de sortie  
            '-c',                           # Compression
            '-S', '4k',                     # Ignorer les secteurs vides (blocs de 4k)
            '-p',                           # Afficher la progression
            source_disk,                    # Périphérique d'entrée
            temp_qcow2_path                # Sortie temporaire
        ]
        
        log_info(f"Exécution de la commande : {' '.join(qemu_convert_cmd)}")
        
        # Exécuter qemu-img convert avec un suivi de progression amélioré
        process = subprocess.Popen(qemu_convert_cmd, 
                                 stderr=subprocess.STDOUT,  # Rediriger stderr vers stdout
                                 stdout=subprocess.PIPE, 
                                 text=True, 
                                 bufsize=1,  # Tampon par ligne
                                 universal_newlines=True)
        
        last_progress = 0
        
        # Lire la sortie ligne par ligne en temps réel
        while True:
            if stop_flag and stop_flag():
                process.terminate()
                process.wait()
                # Nettoyer les fichiers
                if os.path.exists(temp_qcow2_path):
                    os.remove(temp_qcow2_path)
                raise KeyboardInterrupt("Opération annulée par l'utilisateur")
            
            # Lire une ligne depuis stdout
            output_line = process.stdout.readline()
            
            if output_line == '' and process.poll() is not None:
                break
                
            if output_line:
                # Essayer d'analyser la progression depuis la ligne
                parsed_progress = parse_qemu_progress(output_line)
                
                if parsed_progress is not None and parsed_progress > last_progress:
                    last_progress = parsed_progress
                    if progress_callback:
                        progress_callback(parsed_progress, 
                                       f"Conversion des données du disque... {parsed_progress:.1f}%")
                    
                    # Journaliser les étapes de progression significatives
                    if parsed_progress % 10 < 1:  # Tous les ~10 %
                        log_info(f"Progression de la conversion : {parsed_progress:.1f}%")
        
        # Attendre la fin du processus
        return_code = process.poll()
        
        if return_code != 0:
            # Nettoyer en cas d'échec
            if os.path.exists(temp_qcow2_path):
                os.remove(temp_qcow2_path)
            
            # Récupérer toute sortie restante
            remaining_output = process.stdout.read() if process.stdout else ""
            error_msg = f"qemu-img convert a échoué avec le code de retour {return_code}"
            if remaining_output:
                # Filtrer les lignes de progression du message d'erreur
                error_lines = []
                for line in remaining_output.split('\n'):
                    if line.strip() and not re.search(r'\d+(?:\.\d+)?%', line):
                        error_lines.append(line)
                if error_lines:
                    error_msg += f"\nSortie d'erreur : {chr(10).join(error_lines)}"
            
            raise subprocess.CalledProcessError(return_code, qemu_convert_cmd, 
                                             "", remaining_output)
        
        log_info("Conversion clairsemée du disque terminée")
        
        # Étape 2 : déplacer le fichier temporaire vers son emplacement final
        log_info("Étape 2 : finalisation de l'image VM...")
        if progress_callback:
            progress_callback(95, "Finalisation de l'image VM...")
        
        # Déplacer le fichier converti vers l'emplacement final
        os.rename(temp_qcow2_path, qcow2_path)
        
        # Étape 3 : vérifier et récupérer les informations finales
        if not os.path.exists(qcow2_path):
            raise FileNotFoundError("Le fichier qcow2 n'a pas été créé correctement")
        
        # Obtenir les informations détaillées de l'image
        if progress_callback:
            progress_callback(98, "Vérification de l'image VM...")
        
        verification_info = verify_vm_image(qcow2_path)
        
        if verification_info['success']:
            actual_size = verification_info['actual_size']
            virtual_size = verification_info['virtual_size']
            
            log_info("Conversion P2V terminée avec succès")
            log_info(f"Fichier de sortie : {qcow2_path}")
            log_info(f"Taille du disque virtuel : {format_bytes(virtual_size)}")
            log_info(f"Taille réelle du fichier : {format_bytes(actual_size)}")
            
            if virtual_size > 0:
                space_saved = virtual_size - actual_size
                savings_percent = (space_saved / virtual_size * 100)
                log_info(f"Espace économisé : {format_bytes(space_saved)} ({savings_percent:.1f}%)")
        else:
            log_info(f"Conversion P2V terminée - fichier créé : {qcow2_path}")
            actual_size = os.path.getsize(qcow2_path)
            log_info(f"Taille finale du fichier : {format_bytes(actual_size)}")
        
        if progress_callback:
            progress_callback(100, "Conversion terminée avec succès !")
        
        return qcow2_path
        
    except KeyboardInterrupt:
        log_error("Conversion P2V annulée par l'utilisateur")
        raise
    except FileNotFoundError as e:
        log_error(f"Fichier ou outil requis introuvable : {e}")
        raise
    except PermissionError as e:
        log_error(f"Permission refusée lors de l'accès au disque ou aux fichiers : {e}")
        raise
    except subprocess.CalledProcessError as e:
        log_error(f"Échec de l'exécution de la commande : {e}")
        raise
    except OSError as e:
        log_error(f"Erreur système pendant la conversion : {e}")
        raise
    except ValueError as e:
        log_error(f"Valeur invalide rencontrée : {e}")
        raise
    except RuntimeError as e:
        log_error(f"Erreur d'exécution pendant la conversion : {e}")
        raise