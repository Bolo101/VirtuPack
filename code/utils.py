import subprocess
import sys
import re
import time
import os
import shutil
import json
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

def get_disk_list() -> list[dict]:
    """
    Get list of available disks as structured data.
    Returns a list of dictionaries with disk information.
    Each dictionary contains: 'device', 'size', 'model', 'size_bytes', 'label', and 'is_active'.
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
                
                disks.append({
                    "device": f"/dev/{device}",
                    "size": size_human,
                    "size_bytes": size_bytes,
                    "model": model,
                    "label": label,
                    "is_active": is_active
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

def check_output_space(output_path: str, source_disk: str) -> tuple[bool, str]:
    """
    Improved space checking that considers actual disk usage
    Args:
        output_path: Path to output directory
        source_disk: Path to source disk or disk size in bytes (for backward compatibility)
    Returns:
        tuple: (has_enough_space, message)
    """
    try:
        # Ensure directory exists
        os.makedirs(output_path, exist_ok=True)
        
        # Get output directory space
        space_info = get_directory_space(output_path)
        
        # Handle both disk path and size inputs for backward compatibility
        if isinstance(source_disk, str) and source_disk.startswith('/dev/'):
            # It's a disk path - get disk info and usage
            disk_info = get_disk_info(source_disk)
            disk_size = disk_info['size_bytes']
            usage_info = get_disk_usage_info(source_disk)
            
            if usage_info['used'] > 0:
                # Use actual filesystem usage + 30% overhead for metadata/compression variation
                estimated_size = int(usage_info['used'] * 1.3)
                estimation_method = "filesystem usage + 30% overhead"
            else:
                # Fallback to conservative estimate (50% of disk size)
                estimated_size = int(disk_size * 0.5)
                estimation_method = "50% of total disk size (conservative)"
            
            message = (
                f"Source disk size: {format_bytes(disk_size)}\n"
                f"Available output space: {format_bytes(space_info['free'])}\n"
                f"Estimated VM size: {format_bytes(estimated_size)} ({estimation_method})\n"
            )
            
            if usage_info['used'] > 0:
                message += f"Filesystem usage: {format_bytes(usage_info['used'])} ({usage_info['usage_percent']:.1f}%)\n"
        
        else:
            # Backward compatibility: source_disk is actually disk size in bytes
            disk_size = int(source_disk) if isinstance(source_disk, (int, str)) else source_disk
            estimated_size = int(disk_size * 0.5)  # 50% compression ratio
            estimation_method = "50% compression ratio (conservative)"
            
            message = (
                f"Source disk size: {format_bytes(disk_size)}\n"
                f"Available output space: {format_bytes(space_info['free'])}\n"
                f"Estimated VM size: {format_bytes(estimated_size)} ({estimation_method})\n"
            )
        
        # Add additional 10% safety margin
        required_space = int(estimated_size * 1.1)
        has_space = space_info['free'] >= required_space
        
        message += f"Required space (with 10% margin): {format_bytes(required_space)}\n"
        message += f"Status: {'✅ Sufficient space' if has_space else '❌ Insufficient space'}"
        
        return has_space, message
        
    except Exception as e:
        return False, f"Error checking space: {str(e)}"

def check_qemu_tools() -> tuple[bool, str]:
    """Check if required QEMU tools are available"""
    tools = ['qemu-img', 'dd']
    missing = []
    
    for tool in tools:
        try:
            subprocess.run([tool, '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing.append(tool)
    
    if missing:
        return False, f"Missing required tools: {', '.join(missing)}"
    return True, "All required tools available"

def verify_vm_image(qcow2_path: str) -> dict:
    """
    Verify and get information about a qcow2 VM image
    Returns dict with verification results and image information
    """
    try:
        # Use qemu-img info to get image details
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
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, KeyError):
        # Fallback to file size if qemu-img info fails
        try:
            actual_size = os.path.getsize(qcow2_path)
            return {
                'success': False,
                'virtual_size': 0,
                'actual_size': actual_size,
                'format': 'qcow2',
                'compressed': True
            }
        except OSError:
            return {
                'success': False,
                'virtual_size': 0,
                'actual_size': 0,
                'format': 'unknown',
                'compressed': False
            }

def create_vm_from_disk(source_disk: str, output_path: str, vm_name: str, progress_callback=None, stop_flag=None) -> str:
    """
    Convert physical disk to qcow2 VM with sparse allocation (only used data)
    Args:
        source_disk: Path to source disk (e.g., /dev/sda)
        output_path: Directory to save VM files
        vm_name: Name for the VM files
        progress_callback: Function to call for progress updates
        stop_flag: Function that returns True if operation should stop
    Returns:
        str: Path to created qcow2 file
    """
    try:
        # Create output directory
        os.makedirs(output_path, exist_ok=True)
        
        # Generate file paths
        qcow2_path = os.path.join(output_path, f"{vm_name}.qcow2")
        temp_qcow2_path = os.path.join(output_path, f"{vm_name}_temp.qcow2")
        
        log_info(f"Starting P2V conversion: {source_disk} -> {qcow2_path}")
        
        # Get original disk size
        disk_info = get_disk_info(source_disk)
        original_size = disk_info['size_bytes']
        
        log_info(f"Original disk size: {format_bytes(original_size)}")
        
        # Step 1: Convert directly from physical disk to qcow2 with sparse allocation
        log_info("Step 1: Converting disk with sparse allocation...")
        if progress_callback:
            progress_callback(10, "Starting sparse disk conversion...")
        
        # Convert directly from physical disk to qcow2 with sparse and compression
        qemu_convert_cmd = [
            'qemu-img', 'convert',
            '-f', 'raw',                    # Input format
            '-O', 'qcow2',                  # Output format  
            '-c',                           # Compress
            '-S', '4k',                     # Skip empty sectors (4k blocks)
            '-p',                           # Show progress
            source_disk,                    # Input device
            temp_qcow2_path                # Temporary output
        ]
        
        log_info(f"Running command: {' '.join(qemu_convert_cmd)}")
        
        # Run qemu-img convert with monitoring
        process = subprocess.Popen(qemu_convert_cmd, stderr=subprocess.PIPE, 
                                 stdout=subprocess.PIPE, text=True, bufsize=1)
        
        last_progress = 0
        while process.poll() is None:
            if stop_flag and stop_flag():
                process.terminate()
                process.wait()
                # Clean up files
                for temp_file in [temp_qcow2_path]:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                raise KeyboardInterrupt("Operation cancelled by user")
            
            # Try to parse progress from stderr
            if process.stderr and process.stderr.readable():
                try:
                    # Non-blocking read
                    import select
                    if select.select([process.stderr], [], [], 0)[0]:
                        line = process.stderr.readline()
                        if line and '(' in line and '%' in line:
                            # Extract percentage from qemu-img progress output
                            import re
                            match = re.search(r'\((\d+\.\d+)/100%\)', line)
                            if match:
                                current_progress = int(10 + float(match.group(1)) * 0.8)  # Scale to 10-90%
                                if current_progress > last_progress:
                                    last_progress = current_progress
                                    if progress_callback:
                                        progress_callback(current_progress, "Converting disk data...")
                except:
                    pass  # Ignore errors in progress parsing
            
            if progress_callback and last_progress == 0:
                progress_callback(50, "Converting disk data...")
            
            time.sleep(2)
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            # Clean up on failure
            if os.path.exists(temp_qcow2_path):
                os.remove(temp_qcow2_path)
            error_msg = f"qemu-img convert failed with return code {process.returncode}"
            if stderr:
                error_msg += f"\nError output: {stderr}"
            raise subprocess.CalledProcessError(process.returncode, qemu_convert_cmd, stdout, stderr)
        
        log_info("Sparse disk conversion completed")
        
        # Step 2: Move temporary file to final location
        log_info("Step 2: Finalizing VM image...")
        if progress_callback:
            progress_callback(95, "Finalizing VM image...")
        
        # Move the converted file to final location
        os.rename(temp_qcow2_path, qcow2_path)
        
        # Step 3: Verify and get final information
        if not os.path.exists(qcow2_path):
            raise Exception("qcow2 file was not created successfully")
        
        # Get detailed image information
        verification_info = verify_vm_image(qcow2_path)
        
        if verification_info['success']:
            actual_size = verification_info['actual_size']
            virtual_size = verification_info['virtual_size']
            
            log_info(f"P2V conversion completed successfully")
            log_info(f"Output file: {qcow2_path}")
            log_info(f"Virtual disk size: {format_bytes(virtual_size)}")
            log_info(f"Actual file size: {format_bytes(actual_size)}")
            
            if virtual_size > 0:
                space_saved = virtual_size - actual_size
                savings_percent = (space_saved / virtual_size * 100)
                log_info(f"Space saved: {format_bytes(space_saved)} ({savings_percent:.1f}%)")
        else:
            log_info(f"P2V conversion completed - file created: {qcow2_path}")
            actual_size = os.path.getsize(qcow2_path)
            log_info(f"Final file size: {format_bytes(actual_size)}")
        
        if progress_callback:
            progress_callback(100, "Conversion completed successfully!")
        
        return qcow2_path
        
    except KeyboardInterrupt:
        log_error("P2V conversion cancelled by user")
        raise
    except Exception as e:
        log_error(f"P2V conversion failed: {str(e)}")
        raise

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
        
    except Exception as e:
        log_error(f"Error getting disk info for {device}: {str(e)}")
        return {
            'device': device,
            'size_bytes': 0,
            'size_human': "Unknown",
            'model': "Unknown",
            'label': "Unknown"
        }

def validate_vm_name(name: str) -> tuple[bool, str]:
    """Validate VM name for filesystem compatibility"""
    if not name:
        return False, "VM name cannot be empty"
    
    # Check for invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        if char in name:
            return False, f"VM name contains invalid character: {char}"
    
    # Check length
    if len(name) > 100:
        return False, "VM name is too long (max 100 characters)"
    
    # Check for reserved names
    reserved = ['con', 'prn', 'aux', 'nul', 'com1', 'com2', 'com3', 'com4', 'com5', 'com6', 'com7', 'com8', 'com9', 'lpt1', 'lpt2', 'lpt3', 'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9']
    if name.lower() in reserved:
        return False, f"VM name '{name}' is reserved"
    
    return True, "Valid name"

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
        
    except Exception as e:
        log_error(f"Error processing device name '{device_name}': {str(e)}")
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
    except Exception as e:
        log_error(f"Error checking if {device_path} is system disk: {str(e)}")
        return False