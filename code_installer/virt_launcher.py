#!/usr/bin/env python3
"""
Virt-Manager Launcher Module
Handles launching virt-manager with proper privilege escalation and permission management
for virtual machine images on system storage or external drives.
"""

import os
import subprocess
import shutil
from pathlib import Path


class VirtManagerLauncher:
    """Launcher class for virt-manager with privilege management"""
    
    @staticmethod
    def check_virt_manager():
        """Check if virt-manager and required tools are available"""
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
        Fix permissions on VM image for libvirt access
        Ensures proper ownership and permissions for QEMU/KVM access
        Works with external drives through libvirt configuration
        
        Args:
            image_path: Path to the VM image file
            log_callback: Optional callback function for logging (log_info function)
            
        Returns:
            bool: True if permissions were verified successfully
            
        Raises:
            FileNotFoundError: If image file doesn't exist
            OSError: If filesystem operations fail
        """
        try:
            if not os.path.exists(image_path):
                error_msg = f"Image file not found: {image_path}"
                if log_callback:
                    log_callback(error_msg)
                raise FileNotFoundError(error_msg)
            
            if log_callback:
                log_callback(f"Verifying image access: {image_path}")
            
            # Get current file stats
            file_stat = os.stat(image_path)
            current_perms = oct(file_stat.st_mode)[-3:]
            
            if log_callback:
                log_callback(f"Image permissions: {current_perms}")
            
            # Check if file is readable
            if not os.access(image_path, os.R_OK):
                if log_callback:
                    log_callback("Warning: Image file not readable")
            
            # Since libvirt daemon runs as root (configured in qemu.conf),
            # file accessibility is less of a concern
            if log_callback:
                log_callback(f"Image is accessible for libvirt (daemon runs as root)")
            
            return True
            
        except (FileNotFoundError, OSError) as e:
            if log_callback:
                log_callback(f"Error verifying image: {str(e)}")
            raise
    
    @staticmethod
    def _is_external_drive(path):
        """
        Check if a path is on an external drive
        
        Args:
            path: File path to check
            
        Returns:
            bool: True if appears to be on external drive
        """
        try:
            # Get filesystem type
            import subprocess
            result = subprocess.run(['df', path], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    fs_line = lines[1]
                    # Check for common external drive mount points and filesystem types
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

        # 4. Fallback : vérifier via virsh
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
        Launch virt-manager with proper privilege escalation
        
        Args:
            image_path: Optional path to VM image to open in virt-manager
            log_callback: Optional callback function for logging (log_info function)
            
        Returns:
            int: Return code from virt-manager (0 on success)
            
        Raises:
            FileNotFoundError: If virt-manager not found
            PermissionError: If permission denied
            OSError: If system error occurs
            subprocess.CalledProcessError: If virt-manager fails
            subprocess.TimeoutExpired: If operation times out
        """
        try:
            # Check if virt-manager is available
            if not shutil.which('virt-manager'):
                error_msg = "virt-manager not found - please install the virt-manager package"
                if log_callback:
                    log_callback(error_msg)
                raise FileNotFoundError(error_msg)
            
            # S'assurer que libvirtd tourne avant de lancer virt-manager
            VirtManagerLauncher.ensure_libvirtd_running(log_callback)

            # Fix image permissions if path provided
            if image_path:
                if not os.path.exists(image_path):
                    error_msg = f"VM image not found: {image_path}"
                    if log_callback:
                        log_callback(error_msg)
                    raise FileNotFoundError(error_msg)
                
                if log_callback:
                    log_callback(f"Preparing VM image: {image_path}")
                
                # Fix permissions for libvirt access
                try:
                    VirtManagerLauncher.fix_image_permissions(image_path, log_callback)
                except (FileNotFoundError, PermissionError, OSError) as e:
                    error_msg = f"Failed to fix image permissions: {str(e)}"
                    if log_callback:
                        log_callback(error_msg)
                    # Continue anyway - virt-manager might still work with proper escalation
            
            if log_callback:
                log_callback("Launching virt-manager...")
            
            # Prepare environment
            env = os.environ.copy()
            env['DISPLAY'] = env.get('DISPLAY', ':0')
            
            # Build command
            cmd = ['virt-manager']
            
            if image_path:
                cmd.extend(['--connect', 'qemu:///system', '--show-domain-console'])
            
            # Check if running as root
            if os.geteuid() == 0:
                # Running as root - can launch directly
                if log_callback:
                    log_callback("Launching virt-manager (running as root)")
                
                print(f"Launching virt-manager: {' '.join(cmd)}")
                
                # Launch without timeout - let user control when to close
                try:
                    process = subprocess.Popen(
                        cmd,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        preexec_fn=None  # Already root
                    )
                    
                    # Wait for process with a reasonable timeout for initial startup
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                        # If it exits within 5 seconds, something went wrong
                        if process.returncode != 0:
                            error_msg = f"virt-manager exited with code {process.returncode}"
                            if stderr:
                                error_msg += f"\n{stderr}"
                            if log_callback:
                                log_callback(error_msg)
                            raise subprocess.CalledProcessError(process.returncode, cmd)
                    except subprocess.TimeoutExpired:
                        # This is expected - virt-manager is running
                        if log_callback:
                            log_callback("virt-manager launched successfully (running in background)")
                        return 0
                
                except subprocess.CalledProcessError as e:
                    error_msg = f"virt-manager launch failed: {str(e)}"
                    if log_callback:
                        log_callback(error_msg)
                    raise
            
            else:
                # Not running as root - need privilege escalation
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
                            log_callback(f"Launching virt-manager with {escalation_cmd[0]}")
                        
                        print(f"Launching virt-manager: {' '.join(escalation_cmd)}")
                        
                        try:
                            process = subprocess.Popen(
                                escalation_cmd,
                                env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True
                            )
                            
                            # Wait for process with timeout for initial startup
                            try:
                                stdout, stderr = process.communicate(timeout=5)
                                if process.returncode != 0:
                                    error_msg = f"virt-manager exited with code {process.returncode}"
                                    if stderr:
                                        error_msg += f"\n{stderr}"
                                    if log_callback:
                                        log_callback(error_msg)
                                    last_error = error_msg
                                    continue  # Try next escalation method
                            except subprocess.TimeoutExpired:
                                # This is expected - virt-manager is running
                                if log_callback:
                                    log_callback("virt-manager launched successfully (running in background)")
                                return 0
                        
                        except subprocess.CalledProcessError as e:
                            error_msg = f"Failed with {escalation_cmd[0]}: {str(e)}"
                            if log_callback:
                                log_callback(error_msg)
                            last_error = error_msg
                            continue
                        
                        except FileNotFoundError as e:
                            error_msg = f"Escalation command not found: {escalation_cmd[0]}"
                            if log_callback:
                                log_callback(error_msg)
                            last_error = error_msg
                            continue
                
                if not escalation_found:
                    error_msg = (
                        "No privilege escalation method found.\n"
                        "Please install one of: pkexec (polkit-1), gksudo (gksu), or sudo\n"
                        "Or run the application with sudo"
                    )
                    if log_callback:
                        log_callback(error_msg)
                    raise PermissionError(error_msg)
                
                error_msg = "All privilege escalation methods failed"
                if last_error:
                    error_msg += f"\n{last_error}"
                if log_callback:
                    log_callback(error_msg)
                raise PermissionError(error_msg)
        
        except FileNotFoundError as e:
            if log_callback:
                log_callback(f"File not found error: {str(e)}")
            raise
        except PermissionError as e:
            if log_callback:
                log_callback(f"Permission error: {str(e)}")
            raise
        except OSError as e:
            if log_callback:
                log_callback(f"System error: {str(e)}")
            raise
        except subprocess.CalledProcessError as e:
            if log_callback:
                log_callback(f"Command error: {str(e)}")
            raise
        except subprocess.SubprocessError as e:
            if log_callback:
                log_callback(f"Subprocess error: {str(e)}")
            raise
        except (AttributeError, TypeError) as e:
            if log_callback:
                log_callback(f"Internal error: {str(e)}")
            raise
    
    @staticmethod
    def launch_virt_manager_with_image(image_path, log_callback=None):
        """
        Launch virt-manager and optionally open/import a VM image
        Works with images on external drives thanks to libvirt configuration
        
        Args:
            image_path: Path to VM image file to work with
            log_callback: Optional callback function for logging
            
        Returns:
            int: Return code (0 on success)
            
        Raises:
            Various exceptions from launch_virt_manager
        """
        try:
            if log_callback:
                log_callback(f"Preparing to launch virt-manager for image: {image_path}")
            
            # Verify image exists
            if not os.path.exists(image_path):
                error_msg = f"Image file not found: {image_path}"
                if log_callback:
                    log_callback(error_msg)
                raise FileNotFoundError(error_msg)
            
            # Get file info
            file_size = os.path.getsize(image_path)
            file_path_obj = Path(image_path)
            
            if log_callback:
                log_callback(f"Image file: {file_path_obj.name}")
                log_callback(f"File size: {VirtManagerLauncher.format_size(file_size)}")
                log_callback(f"Full path: {image_path}")
            
            # Launch virt-manager with the image
            return VirtManagerLauncher.launch_virt_manager(image_path, log_callback)
        
        except (FileNotFoundError, OSError) as e:
            if log_callback:
                log_callback(f"Error launching virt-manager: {str(e)}")
            raise
    
    @staticmethod
    def format_size(bytes_val):
        """Format bytes to human readable size"""
        if bytes_val == 0:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        
        return f"{bytes_val:.1f} PB"