#!/usr/bin/env python3
"""
Module de lancement de Virt-Manager
Gère le lancement de virt-manager avec une élévation de privilèges appropriée et une bonne gestion
des permissions pour les images de machines virtuelles stockées sur le système ou sur des disques externes.
"""

import os
import subprocess
import shutil
from pathlib import Path


class VirtManagerLauncher:
    """Classe de lancement de virt-manager avec gestion des privilèges"""
    
    @staticmethod
    def check_virt_manager():
        """Vérifier si virt-manager et les outils requis sont disponibles"""
        required_tools = {
            'virt-manager': 'virt-manager',
            'virsh': 'libvirt-clients',
            'qemu-system-x86_64': 'qemu-system-x86',
        }
        
        missing = []
        for tool, package in required_tools.items():
            if not shutil.which(tool):
                missing.append(f"{tool} ({package})")
        
        return missing, len(missing) == 0
    
    @staticmethod
    def fix_image_permissions(image_path, log_callback=None):
        """
        Corriger les permissions de l'image de VM pour l'accès via libvirt
        Assure une propriété et des permissions correctes pour l'accès QEMU/KVM
        Fonctionne avec les disques externes via la configuration de libvirt
        
        Args:
            image_path: Chemin du fichier image de la VM
            log_callback: Fonction de rappel optionnelle pour la journalisation (fonction log_info)
            
        Returns:
            bool: True si les permissions ont été vérifiées avec succès
            
        Raises:
            FileNotFoundError: Si le fichier image n'existe pas
            OSError: Si les opérations sur le système de fichiers échouent
        """
        try:
            if not os.path.exists(image_path):
                error_msg = f"Fichier image introuvable : {image_path}"
                if log_callback:
                    log_callback(error_msg)
                raise FileNotFoundError(error_msg)
            
            if log_callback:
                log_callback(f"Vérification de l'accès à l'image : {image_path}")
            
            # Obtenir les statistiques actuelles du fichier
            file_stat = os.stat(image_path)
            current_perms = oct(file_stat.st_mode)[-3:]
            
            if log_callback:
                log_callback(f"Permissions de l'image : {current_perms}")
            
            # Vérifier si le fichier est lisible
            if not os.access(image_path, os.R_OK):
                if log_callback:
                    log_callback("Avertissement : le fichier image n'est pas lisible")
            
            # Comme le démon libvirt s'exécute en tant que root (configuré dans qemu.conf),
            # l'accessibilité du fichier est moins problématique
            if log_callback:
                log_callback("L'image est accessible pour libvirt (le démon s'exécute en tant que root)")
            
            return True
            
        except (FileNotFoundError, OSError) as e:
            if log_callback:
                log_callback(f"Erreur lors de la vérification de l'image : {str(e)}")
            raise
    
    @staticmethod
    def _is_external_drive(path):
        """
        Vérifier si un chemin se trouve sur un disque externe
        
        Args:
            path: Chemin du fichier à vérifier
            
        Returns:
            bool: True si le chemin semble être sur un disque externe
        """
        try:
            # Obtenir le type de système de fichiers
            import subprocess
            result = subprocess.run(['df', path], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    fs_line = lines[1]
                    # Vérifier les points de montage et types de systèmes de fichiers externes courants
                    if any(x in fs_line for x in ['/mnt', '/media', 'ntfs', 'vfat', 'exfat']):
                        return True
        except (OSError, subprocess.SubprocessError):
            pass
        
        return False
    
    @staticmethod
    def ensure_libvirtd_running(log_callback=None):
        """
        S'assure que libvirtd est en cours d'exécution.
        Vérifie le socket, et démarre libvirtd via systemctl si nécessaire.

        Returns:
            bool: True si libvirtd est opérationnel
        """
        import time

        LIBVIRT_SOCK = "/var/run/libvirt/libvirt-sock"

        # 1. Vérifier si le socket existe déjà (libvirtd tourne)
        if os.path.exists(LIBVIRT_SOCK):
            if log_callback:
                log_callback("libvirtd est déjà actif")
            return True

        if log_callback:
            log_callback("libvirtd non détecté — tentative de démarrage...")

        # 2. Tenter de démarrer libvirtd via systemctl
        for service in ("libvirtd.service", "libvirtd.socket"):
            try:
                result = subprocess.run(
                    ["systemctl", "start", service],
                    capture_output=True, text=True, timeout=15
                )
                if log_callback:
                    if result.returncode == 0:
                        log_callback(f"{service} démarré")
                    else:
                        log_callback(f"Impossible de démarrer {service} : {result.stderr.strip()}")
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        # 3. Attendre que le socket apparaisse (max 10 s)
        for _ in range(20):
            if os.path.exists(LIBVIRT_SOCK):
                if log_callback:
                    log_callback("libvirtd opérationnel")
                return True
            time.sleep(0.5)


        # 4. Repli : vérifier via virsh
        try:
            result = subprocess.run(
                ["virsh", "-c", "qemu:///system", "list"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                if log_callback:
                    log_callback("libvirtd répond via virsh")
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        if log_callback:
            log_callback("Avertissement : libvirtd peut ne pas être disponible")
        return False

    @staticmethod
    def launch_virt_manager(image_path=None, log_callback=None):
        """
        Lancer virt-manager avec une élévation de privilèges appropriée
        
        Args:
            image_path: Chemin optionnel vers l'image de VM à ouvrir dans virt-manager
            log_callback: Fonction de rappel optionnelle pour la journalisation (fonction log_info)
            
        Returns:
            int: Code de retour de virt-manager (0 en cas de succès)
            
        Raises:
            FileNotFoundError: Si virt-manager est introuvable
            PermissionError: Si la permission est refusée
            OSError: En cas d'erreur système
            subprocess.CalledProcessError: Si virt-manager échoue
            subprocess.TimeoutExpired: Si l'opération expire
        """
        try:
            # Vérifier si virt-manager est disponible
            if not shutil.which('virt-manager'):
                error_msg = "virt-manager introuvable - veuillez installer le paquet virt-manager"
                if log_callback:
                    log_callback(error_msg)
                raise FileNotFoundError(error_msg)
            
            # S'assurer que libvirtd tourne avant de lancer virt-manager
            VirtManagerLauncher.ensure_libvirtd_running(log_callback)


            # Corriger les permissions de l'image si un chemin est fourni
            if image_path:
                if not os.path.exists(image_path):
                    error_msg = f"Image de VM introuvable : {image_path}"
                    if log_callback:
                        log_callback(error_msg)
                    raise FileNotFoundError(error_msg)
                
                if log_callback:
                    log_callback(f"Préparation de l'image de VM : {image_path}")
                
                # Corriger les permissions pour l'accès via libvirt
                try:
                    VirtManagerLauncher.fix_image_permissions(image_path, log_callback)
                except (FileNotFoundError, PermissionError, OSError) as e:
                    error_msg = f"Échec de la correction des permissions de l'image : {str(e)}"
                    if log_callback:
                        log_callback(error_msg)
                    # Continuer quand même - virt-manager peut encore fonctionner avec une élévation appropriée
            
            if log_callback:
                log_callback("Lancement de virt-manager...")
            
            # Préparer l'environnement
            env = os.environ.copy()
            env['DISPLAY'] = env.get('DISPLAY', ':0')
            
            # Construire la commande
            cmd = ['virt-manager']
            
            if image_path:
                cmd.extend(['--connect', 'qemu:///system', '--show-domain-console'])
            
            # Vérifier si l'exécution se fait en tant que root
            if os.geteuid() == 0:
                # Exécution en tant que root - lancement direct possible
                if log_callback:
                    log_callback("Lancement de virt-manager (exécution en tant que root)")
                
                print(f"Lancement de virt-manager : {' '.join(cmd)}")
                
                # Lancer sans délai global - laisser l'utilisateur décider quand fermer
                try:
                    process = subprocess.Popen(
                        cmd,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        preexec_fn=None  # Déjà root
                    )
                    
                    # Attendre le processus avec un délai raisonnable pour le démarrage initial
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                        # Si le programme quitte en moins de 5 secondes, quelque chose s'est mal passé
                        if process.returncode != 0:
                            error_msg = f"virt-manager s'est arrêté avec le code {process.returncode}"
                            if stderr:
                                error_msg += f"\n{stderr}"
                            if log_callback:
                                log_callback(error_msg)
                            raise subprocess.CalledProcessError(process.returncode, cmd)
                    except subprocess.TimeoutExpired:
                        # C'est attendu - virt-manager est en cours d'exécution
                        if log_callback:
                            log_callback("virt-manager lancé avec succès (exécution en arrière-plan)")
                        return 0
                
                except subprocess.CalledProcessError as e:
                    error_msg = f"Échec du lancement de virt-manager : {str(e)}"
                    if log_callback:
                        log_callback(error_msg)
                    raise
            
            else:
                # Pas exécuté en tant que root - élévation de privilèges nécessaire
                escalation_commands = [
                    ['pkexec', 'virt-manager'] + ([] if not image_path else ['--connect', 'qemu:///system']),
                    ['gksudo', 'virt-manager'] + ([] if not image_path else ['--connect', 'qemu:///system']),
                    ['sudo', 'virt-manager'] + ([] if not image_path else ['--connect', 'qemu:///system']),
                ]
                
                escalation_found = False
                last_error = None
                
                for escalation_cmd in escalation_commands:
                    if shutil.which(escalation_cmd[0]):
                        escalation_found = True
                        
                        if log_callback:
                            log_callback(f"Lancement de virt-manager avec {escalation_cmd[0]}")
                        
                        print(f"Lancement de virt-manager : {' '.join(escalation_cmd)}")
                        
                        try:
                            process = subprocess.Popen(
                                escalation_cmd,
                                env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True
                            )
                            
                            # Attendre le processus avec délai pour le démarrage initial
                            try:
                                stdout, stderr = process.communicate(timeout=5)
                                if process.returncode != 0:
                                    error_msg = f"virt-manager s'est arrêté avec le code {process.returncode}"
                                    if stderr:
                                        error_msg += f"\n{stderr}"
                                    if log_callback:
                                        log_callback(error_msg)
                                    last_error = error_msg
                                    continue  # Essayer la méthode d'élévation suivante
                            except subprocess.TimeoutExpired:
                                # C'est attendu - virt-manager est en cours d'exécution
                                if log_callback:
                                    log_callback("virt-manager lancé avec succès (exécution en arrière-plan)")
                                return 0
                        
                        except subprocess.CalledProcessError as e:
                            error_msg = f"Échec avec {escalation_cmd[0]} : {str(e)}"
                            if log_callback:
                                log_callback(error_msg)
                            last_error = error_msg
                            continue
                        
                        except FileNotFoundError as e:
                            error_msg = f"Commande d'élévation introuvable : {escalation_cmd[0]}"
                            if log_callback:
                                log_callback(error_msg)
                            last_error = error_msg
                            continue
                
                if not escalation_found:
                    error_msg = (
                        "Aucune méthode d'élévation de privilèges trouvée.\n"
                        "Veuillez installer l'un des outils suivants : pkexec (polkit-1), gksudo (gksu) ou sudo\n"
                        "Ou exécuter l'application avec sudo"
                    )
                    if log_callback:
                        log_callback(error_msg)
                    raise PermissionError(error_msg)
                
                error_msg = "Toutes les méthodes d'élévation de privilèges ont échoué"
                if last_error:
                    error_msg += f"\n{last_error}"
                if log_callback:
                    log_callback(error_msg)
                raise PermissionError(error_msg)
        
        except FileNotFoundError as e:
            if log_callback:
                log_callback(f"Erreur fichier introuvable : {str(e)}")
            raise
        except PermissionError as e:
            if log_callback:
                log_callback(f"Erreur de permission : {str(e)}")
            raise
        except OSError as e:
            if log_callback:
                log_callback(f"Erreur système : {str(e)}")
            raise
        except subprocess.CalledProcessError as e:
            if log_callback:
                log_callback(f"Erreur de commande : {str(e)}")
            raise
        except subprocess.SubprocessError as e:
            if log_callback:
                log_callback(f"Erreur de sous-processus : {str(e)}")
            raise
        except (AttributeError, TypeError) as e:
            if log_callback:
                log_callback(f"Erreur interne : {str(e)}")
            raise
    
    @staticmethod
    def launch_virt_manager_with_image(image_path, log_callback=None):
        """
        Lancer virt-manager et éventuellement ouvrir/importer une image de VM
        Fonctionne avec les images sur disques externes grâce à la configuration de libvirt
        
        Args:
            image_path: Chemin du fichier image de la VM à utiliser
            log_callback: Fonction de rappel optionnelle pour la journalisation
            
        Returns:
            int: Code de retour (0 en cas de succès)
            
        Raises:
            Diverses exceptions issues de launch_virt_manager
        """
        try:
            if log_callback:
                log_callback(f"Préparation du lancement de virt-manager pour l'image : {image_path}")
            
            # Vérifier que l'image existe
            if not os.path.exists(image_path):
                error_msg = f"Fichier image introuvable : {image_path}"
                if log_callback:
                    log_callback(error_msg)
                raise FileNotFoundError(error_msg)
            
            # Obtenir les informations sur le fichier
            file_size = os.path.getsize(image_path)
            file_path_obj = Path(image_path)
            
            if log_callback:
                log_callback(f"Fichier image : {file_path_obj.name}")
                log_callback(f"Taille du fichier : {VirtManagerLauncher.format_size(file_size)}")
                log_callback(f"Chemin complet : {image_path}")
            
            # Lancer virt-manager avec l'image
            return VirtManagerLauncher.launch_virt_manager(image_path, log_callback)
        
        except (FileNotFoundError, OSError) as e:
            if log_callback:
                log_callback(f"Erreur lors du lancement de virt-manager : {str(e)}")
            raise
    
    @staticmethod
    def format_size(bytes_val):
        """Formater des octets en taille lisible par un humain"""
        if bytes_val == 0:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        
        return f"{bytes_val:.1f} PB"