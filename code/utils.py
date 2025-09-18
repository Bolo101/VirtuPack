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
        log_error(f"Error: Command not found: {' '.join(command_list)}")
        if raise_on_error:
            sys.exit(2)
        else:
            raise
    except subprocess.CalledProcessError:
        log_error(f"Error: Command execution failed: {' '.join(command_list)}")
        if raise_on_error:
            sys.exit(1)
        else:
            raise
    except KeyboardInterrupt:
        log_error("Operation interrupted by user (Ctrl+C)")
        print("\nOperation interrupted by user (Ctrl+C)")
        sys.exit(130)  # Standard exit code for SIGINT


def run_command_with_progress(command_list: list[str], progress_callback=None, stop_flag=None) -> str:
    """Run command with progress monitoring and cancellation support"""
    try:
        # Start process
        process = subprocess.Popen(command_list, stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE, text=True)
        
        # Monitor progress
        while process.poll() is None:
            if stop_flag and stop_flag():
                # User requested cancellation
                process.terminate()
                process.wait()
                raise KeyboardInterrupt("Operation cancelled by user")
            
            # Update progress if callback provided
            if progress_callback:
                progress_callback()
            
            time.sleep(1)
        
        # Wait for completion and get output
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command_list, stdout, stderr)
        
        return stdout.strip()
        
    except FileNotFoundError:
        log_error(f"Error: Command not found: {' '.join(command_list)}")
        raise
    except subprocess.CalledProcessError as e:
        log_error(f"Error: Command execution failed: {' '.join(command_list)}")
        if e.stderr:
            log_error(f"Error output: {e.stderr}")
        raise
    except KeyboardInterrupt:
        log_error("Operation interrupted by user")
        raise


def format_bytes(bytes_count: int) -> str:
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} PB"


def get_directory_space(path: str) -> dict:
    """
    Get available space information for a directory
    Returns dict with 'total', 'used', 'free' in bytes
    """
    try:
        stat = shutil.disk_usage(path)
        return {
            'total': stat.total,
            'used': stat.total - stat.free,
            'free': stat.free
        }
    except OSError as e:
        log_error(f"Error getting disk space for {path}: {str(e)}")
        return {'total': 0, 'used': 0, 'free': 0}


def get_disk_label(device: str) -> str:
    """
    Get the label of a disk device using lsblk.
    Returns the label or "No Label" if none exists.
    """
    try:
        # Use lsblk to get label information for all partitions on the device
        output = run_command(["lsblk", "-o", "LABEL", "-n", f"/dev/{device}"], raise_on_error=False)
        if output and output.strip():
            # Get the first non-empty label (in case of multiple partitions)
            labels = [line.strip() for line in output.split('\n') if line.strip()]
            if labels:
                return labels[0]
        return "No Label"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Unknown"


def get_mounted_devices() -> set:
    """
    Get set of currently mounted device paths and their base disks
    Returns both partition paths and base disk paths
    """
    mounted_devices = set()
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 1 and parts[0].startswith('/dev/'):
                    device = parts[0]
                    mounted_devices.add(device)
                    # Also add base disk name for partition checking
                    base_device = get_base_device_from_partition(device)
                    if base_device != device:
                        mounted_devices.add(base_device)
    except (IOError, OSError) as e:
        log_error(f"Could not read /proc/mounts: {str(e)}")
    
    return mounted_devices


def get_base_device_from_partition(device_path: str) -> str:
    """
    Get the base device from a partition path
    Examples: 
        '/dev/sda1' -> '/dev/sda'
        '/dev/nvme0n1p1' -> '/dev/nvme0n1'
        '/dev/sda' -> '/dev/sda' (unchanged)
    """
    try:
        # Handle nvme devices (e.g., /dev/nvme0n1p1 -> /dev/nvme0n1)
        if 'nvme' in device_path and 'p' in device_path:
            match = re.match(r'(/dev/nvme\d+n\d+)', device_path)
            if match:
                return match.group(1)
        
        # Handle traditional devices (e.g., /dev/sda1 -> /dev/sda)
        match = re.match(r'(/dev/[a-zA-Z]+)', device_path)
        if match:
            return match.group(1)
        
        # If no pattern matches, return the original
        return device_path
        
    except re.error as e:
        log_error(f"Invalid regex pattern while processing device path '{device_path}': {str(e)}")
        return device_path
    except TypeError as e:
        log_error(f"Invalid device path type provided '{type(device_path)}': {str(e)}")
        return device_path
    except ValueError as e:
        log_error(f"Invalid device path format '{device_path}': {str(e)}")
        return device_path


def has_mounted_partitions(device_path: str) -> bool:
    """
    Check if a disk has any mounted partitions
    Args:
        device_path: Path to device (e.g., /dev/sda)
    Returns:
        bool: True if any partition is mounted, False otherwise
    """
    try:
        mounted_devices = get_mounted_devices()
        
        # Check if the device itself is mounted
        if device_path in mounted_devices:
            return True
        
        # Get all partitions for this device
        try:
            result = subprocess.run(['lsblk', '-n', '-o', 'NAME', device_path], 
                                  capture_output=True, text=True, check=True)
            
            lines = result.stdout.strip().split('\n')
            device_name = device_path.replace('/dev/', '')
            
            for line in lines:
                if line.strip():
                    partition_name = line.strip()
                    # Remove tree characters from lsblk output
                    partition_name = partition_name.lstrip('â"œâ"€â""â"‚ â"€')
                    partition_path = f"/dev/{partition_name}"
                    
                    # Skip the main device line
                    if partition_name == device_name:
                        continue
                        
                    # Check if this partition is mounted
                    if partition_path in mounted_devices:
                        return True
        
        except subprocess.CalledProcessError as e:
            log_error(f"Error executing lsblk for {device_path}: {e.stderr}")
            return False
        except FileNotFoundError as e:
            log_error(f"lsblk command not found: {str(e)}")
            return False
        
        return False
        
    except OSError as e:
        log_error(f"OS error checking mounted partitions for {device_path}: {str(e)}")
        return False
    except ValueError as e:
        log_error(f"Invalid device path format while checking mounts: {str(e)}")
        return False
    except TypeError as e:
        log_error(f"Invalid type for device_path parameter: {str(e)}")
        return False


def get_disk_list() -> list[dict]:
    """
    Get list of available disks as structured data.
    Returns a list of dictionaries with disk information.
    Each dictionary contains: 'device', 'size', 'model', 'size_bytes', 'label', 'is_active', and 'is_mounted'.
    """
    try:
        # Use more explicit column specification with -o option and -n to skip header
        output = run_command(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,MODEL", "-n", "-b"])
        
        if not output:
            # Fallback to a simpler command if the first one returned no results
            output = run_command(["lsblk", "-d", "-o", "NAME,SIZE", "-n", "-b"])
            if not output:
                log_info("No disks detected. Ensure the program is run with appropriate permissions.")
                return []
        
        # Get active disks for marking
        active_disks = get_active_disk() or []
        active_disk_names = set()
        for active_device in active_disks:
            if isinstance(active_device, str):
                # Remove /dev/ prefix if present
                base_name = active_device.replace('/dev/', '')
                active_disk_names.add(base_name)
        
        # Parse the output from lsblk command
        disks = []
        for line in output.strip().split('\n'):
            if not line.strip():
                continue
                
            # Split the line but preserve the model name which might contain spaces
            parts = line.strip().split(maxsplit=3)
            device = parts[0]
            
            # Ensure we have at least NAME and SIZE
            if len(parts) >= 2:
                try:
                    size_bytes = int(parts[1])
                    size_human = format_bytes(size_bytes)
                except (ValueError, IndexError):
                    size_bytes = 0
                    size_human = "Unknown"
                
                # MODEL may be missing, set to "Unknown" if it is
                model = parts[3] if len(parts) > 3 else "Unknown"
                
                # Get disk label
                label = get_disk_label(device)
                
                # Check if this disk is active (system disk)
                is_active = device in active_disk_names
                
                # Check if this disk has mounted partitions
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
        log_error(f"Error: Command not found: {str(e)}")
        return []
    except subprocess.CalledProcessError as e:
        log_error(f"Error executing command: {str(e)}")
        return []
    except (IndexError, ValueError) as e:
        log_error(f"Error parsing disk information: {str(e)}")
        return []
    except KeyboardInterrupt:
        log_error("Disk listing interrupted by user")
        return []


def check_filesystem(device_path: str) -> str:
    """Check if device has a mountable filesystem and return filesystem type"""
    try:
        # Check for filesystem using lsblk
        result = subprocess.run(['lsblk', '-n', '-o', 'FSTYPE', device_path], 
                              capture_output=True, text=True, check=True)
        
        filesystems = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
        
        # Common mountable filesystems
        mountable_fs = ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'ntfs', 'fat32', 'vfat', 'exfat']
        
        for fs in filesystems:
            if fs.lower() in mountable_fs:
                return fs
        
        return None
    
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def mount_disk(device_path: str, mount_point: str, filesystem_type: str = None) -> bool:
    """
    Mount a disk to a specified mount point
    
    Args:
        device_path: Path to device (e.g., /dev/sdb1)
        mount_point: Directory to mount to
        filesystem_type: Optional filesystem type
    
    Returns:
        bool: True if mount successful, False otherwise
    """
    try:
        # Create mount point if it doesn't exist
        os.makedirs(mount_point, exist_ok=True)
        
        # Build mount command
        mount_cmd = ['sudo', 'mount']
        
        if filesystem_type:
            if filesystem_type.lower() == 'ntfs':
                mount_cmd.extend(['-t', 'ntfs-3g'])
            else:
                mount_cmd.extend(['-t', filesystem_type])
        
        mount_cmd.extend([device_path, mount_point])
        
        # Execute mount command
        result = subprocess.run(mount_cmd, capture_output=True, text=True, check=True)
        
        # Verify mount was successful
        if os.path.ismount(mount_point):
            log_info(f"Successfully mounted {device_path} to {mount_point}")
            return True
        else:
            log_error(f"Mount command succeeded but {mount_point} is not mounted")
            return False
    
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to mount {device_path}: {e.stderr if e.stderr else str(e)}"
        log_error(error_msg)
        return False
    
    except PermissionError as e:
        log_error(f"Permission denied mounting {device_path}: {str(e)}")
        return False
    
    except Exception as e:
        log_error(f"Unexpected error mounting {device_path}: {str(e)}")
        return False


def unmount_disk(mount_point: str) -> bool:
    """
    Unmount a disk from specified mount point
    
    Args:
        mount_point: Directory to unmount
    
    Returns:
        bool: True if unmount successful, False otherwise
    """
    try:
        # Execute unmount command
        result = subprocess.run(['sudo', 'umount', mount_point], 
                              capture_output=True, text=True, check=True)
        
        # Verify unmount was successful
        if not os.path.ismount(mount_point):
            log_info(f"Successfully unmounted {mount_point}")
            return True
        else:
            log_error(f"Unmount command succeeded but {mount_point} is still mounted")
            return False
    
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to unmount {mount_point}: {e.stderr if e.stderr else str(e)}"
        log_error(error_msg)
        return False
    
    except Exception as e:
        log_error(f"Unexpected error unmounting {mount_point}: {str(e)}")
        return False


def get_unmounted_disks() -> list[dict]:
    """
    Get list of unmounted disks suitable for mounting
    Returns list of disk dictionaries with additional 'has_filesystem' field
    """
    try:
        # Get all disks
        all_disks = get_disk_list()
        unmounted_disks = []
        
        # Filter out mounted and system disks
        for disk in all_disks:
            device_path = disk['device']
            
            # Skip if it's a system/active disk or mounted disk
            if disk.get('is_active', False) or disk.get('is_mounted', False) or is_system_disk(device_path):
                continue
            
            # Check if disk has a filesystem we can mount
            has_filesystem = check_filesystem(device_path)
            disk['has_filesystem'] = has_filesystem
            unmounted_disks.append(disk)
        
        return unmounted_disks
    
    except Exception as e:
        log_error(f"Error getting unmounted disks: {str(e)}")
        return []


def get_disk_usage_info(device: str) -> dict:
    """
    Get disk usage information for better space estimation
    Returns dict with filesystem usage info
    """
    try:
        # Try to get filesystem usage information
        result = subprocess.run(['df', device], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 6:
                total = int(parts[1]) * 1024  # Convert from KB to bytes
                used = int(parts[2]) * 1024
                available = int(parts[3]) * 1024
                
                return {
                    'total': total,
                    'used': used,
                    'available': available,
                    'usage_percent': (used / total * 100) if total > 0 else 0
                }
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, IndexError):
        # If we can't get filesystem info, try to estimate from partitions
        try:
            # Get all partitions for this device and try to sum their usage
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
                            total_used += int(df_parts[2]) * 1024  # Convert KB to bytes
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
    """Get detailed information about a disk"""
    try:
        # Get size using blockdev
        result = subprocess.run(['blockdev', '--getsize64', device], 
                              capture_output=True, text=True, check=True)
        size_bytes = int(result.stdout.strip())
        
        # Get model info using lsblk
        result = subprocess.run(['lsblk', '-d', '-n', '-o', 'MODEL', device], 
                              capture_output=True, text=True, check=True)
        model = result.stdout.strip() or "Unknown"
        
        # Get label
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
        log_error(f"Command execution failed for {device}: {e.stderr}")
    except FileNotFoundError as e:
        log_error(f"Required command not found: {str(e)}")
    except ValueError as e:
        log_error(f"Invalid value received while processing disk info for {device}: {str(e)}")
    except OSError as e:
        log_error(f"OS error accessing disk {device}: {str(e)}")
    except TypeError as e:
        log_error(f"Invalid type provided for disk info parameters: {str(e)}")
    
    # Return default values if any error occurred
    return {
        'device': device,
        'size_bytes': 0,
        'size_human': "Unknown",
        'model': "Unknown",
        'label': "Unknown"
    }

def get_active_disk():
    """
    Detect the active device backing the root filesystem.
    Always returns a list of base disk names (e.g., ['nvme0n1', 'sda']) or None for consistency.
    Uses LVM logic if the root device is a logical volume (/dev/mapper/),
    otherwise uses regular disk detection logic including live boot media detection.
    All returned device names are resolved to their base disk names.
    """
    try:
        # Initialize devices set for collecting all active devices
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
                    log_error(f"Error running df command: {str(e)}")
        
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
                log_info(f"Could not check for live boot devices: {str(e)}")

        # Step 4: Return logic
        if devices:
            device_list = list(devices)
            return device_list
        else:
            log_error("No active devices found")
            return None

    except FileNotFoundError as e:
        log_error(f"Required file not found: {str(e)}")
        return None
    except PermissionError as e:
        log_error(f"Permission denied accessing system files: {str(e)}")
        return None
    except OSError as e:
        log_error(f"OS error accessing system information: {str(e)}")
        return None
    except subprocess.CalledProcessError as e:
        log_error(f"Error running command: {str(e)}")
        return None
    except (IndexError, ValueError) as e:
        log_error(f"Error parsing command output: {str(e)}")
        return None
    except re.error as e:
        log_error(f"Regex pattern error: {str(e)}")
        return None
    except KeyboardInterrupt:
        log_error("Operation interrupted by user")
        return None
    except UnicodeDecodeError as e:
        log_error(f"Error decoding file content: {str(e)}")
        return None
    except MemoryError:
        log_error("Insufficient memory to process device information")
        return None


def get_physical_drives_for_logical_volumes(active_devices: list) -> set:
    """
    Map logical volumes (LVM, etc.) to their underlying physical drives.
    
    Args:
        active_devices: List of active device paths (e.g., ['/dev/mapper/rocket--vg-root'])
    
    Returns:
        Set of physical drive names (e.g., {'nvme0n1', 'sda'})
    """
    if not active_devices:
        return set()
    
    physical_drives = set()
    
    try:
        # Get all physical drives from disk list
        disk_list = get_disk_list()
        physical_device_names = [disk['device'].replace('/dev/', '') for disk in disk_list]
        
        for physical_device in physical_device_names:
            try:
                # Use lsblk to get the complete device tree for this physical drive
                # -o NAME shows device names, -l shows in list format, -n removes headers
                output = run_command([
                    "lsblk", 
                    f"/dev/{physical_device}", 
                    "-o", "NAME", 
                    "-l", 
                    "-n"
                ], raise_on_error=False)
                
                # Parse the output to get all devices in the tree
                device_tree = []
                for line in output.strip().split('\n'):
                    if line.strip():
                        device_name = line.strip()
                        # Add both with and without /dev/ prefix for comparison
                        device_tree.append(f"/dev/{device_name}")
                        device_tree.append(device_name)
                
                # Check if any active device is in this physical drive's tree
                for active_device in active_devices:
                    # Handle different formats of device names
                    active_variants = [
                        active_device,
                        active_device.replace('/dev/', ''),
                        active_device.replace('/dev/mapper/', '')
                    ]
                    
                    # Check if any variant of the active device is in the device tree
                    for variant in active_variants:
                        if variant in device_tree:
                            physical_drives.add(physical_device)
                            log_info(f"Found active device '{active_device}' on physical drive '{physical_device}'")
                            break
                    
                    if physical_device in physical_drives:
                        break
                        
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                # Skip this physical device if lsblk fails
                log_error(f"Could not query device tree for {physical_device}: {str(e)}")
                continue
                
    except (AttributeError, TypeError) as e:
        log_error(f"Error processing device data structures: {str(e)}")
    except MemoryError:
        log_error("Insufficient memory to process logical volume mapping")
    except OSError as e:
        log_error(f"OS error during logical volume mapping: {str(e)}")
    
    return physical_drives


def get_base_disk(device_name: str) -> str:
    """
    Extract base disk name from a device name.
    Examples: 
        'nvme0n1p1' -> 'nvme0n1'
        'sda1' -> 'sda'
        'nvme0n1' -> 'nvme0n1'
    """
    try:
        # Handle nvme devices (e.g., nvme0n1p1 -> nvme0n1)
        if 'nvme' in device_name:
            match = re.match(r'(nvme\d+n\d+)', device_name)
            if match:
                return match.group(1)
        
        # Handle traditional devices (e.g., sda1 -> sda)
        match = re.match(r'([a-zA-Z/]+[a-zA-Z])', device_name)
        if match:
            return match.group(1)
        
        # If no pattern matches, return the original
        return device_name
        
    except re.error as e:
        log_error(f"Invalid regex pattern while processing device name '{device_name}': {str(e)}")
    except TypeError as e:
        log_error(f"Invalid type for device_name parameter: {str(e)}")
    except ValueError as e:
        log_error(f"Invalid device name format '{device_name}': {str(e)}")
    
    return device_name


def is_system_disk(device_path: str) -> bool:
    """
    Check if the given device path is a system disk (active/mounted).
    Args:
        device_path: Full device path (e.g., '/dev/sda')
    Returns:
        bool: True if it's a system disk, False otherwise
    """
    try:
        # Extract device name without /dev/ prefix
        device_name = device_path.replace('/dev/', '')
        
        # Get list of active disks
        active_disks = get_active_disk()
        if active_disks:
            return device_name in active_disks
        
        return False
        
    except TypeError as e:
        log_error(f"Invalid type for device path '{type(device_path)}': {str(e)}")
    except ValueError as e:
        log_error(f"Invalid device path format '{device_path}': {str(e)}")
    except OSError as e:
        log_error(f"OS error checking system disk status for {device_path}: {str(e)}")
    
    return False