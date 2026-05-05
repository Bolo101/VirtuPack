import tkinter as tk
import os
import subprocess
import tempfile
import json
import shutil
import time
import re
from pathlib import Path



class QCow2CloneResizer:
    """Secure version using cloning instead of direct resizing"""
    
    @staticmethod
    def check_tools():
        """Check if required tools are available"""
        essential_tools = {
            'qemu-img': 'qemu-utils',
            'parted': 'parted',
            'gparted': 'gparted',
            'dd': 'coreutils',
        }
        
        missing = []
        optional = []
        for tool, package in essential_tools.items():
            if not shutil.which(tool):
                if tool in ['partclone.ext4']:
                    optional.append(f"{tool} ({package}) - recommended")
                else:
                    missing.append(f"{tool} ({package})")
        
        return missing, optional
    
    @staticmethod
    def compress_qcow2_image(image_path, progress_callback=None, delete_original_source=None, process_tracker=None):
        """Compress QCOW2 image with detailed progress updates (0-100%)
        
        Args:
            image_path: Path to the image to compress  
            progress_callback: Optional progress callback function
            delete_original_source: NOT USED - kept for compatibility
            process_tracker: Optional dict/object to track the subprocess for external termination
        """
        temp_compressed_path = f"{image_path}.compressed.tmp"
        process = None
        
        try:
            if progress_callback:
                progress_callback(0, "Preparing compression...")
            
            print(f"Starting compression of: {image_path}")
            
            # Get original image info
            original_info = QCow2CloneResizer.get_image_info(image_path)
            original_file_size = os.path.getsize(image_path)
            
            print(f"Original image stats:")
            print(f"  Virtual size: {QCow2CloneResizer.format_size(original_info['virtual_size'])}")
            print(f"  File size: {QCow2CloneResizer.format_size(original_file_size)}")
            
            if progress_callback:
                progress_callback(2, "Creating temporary file...")
            
            # Remove temp file if it exists
            if os.path.exists(temp_compressed_path):
                try:
                    os.remove(temp_compressed_path)
                except (FileNotFoundError, PermissionError, OSError) as e:
                    print(f"Warning: Could not remove existing temp file: {e}")
            
            if progress_callback:
                progress_callback(5, "Starting compression...")
            
            # Compression command
            cmd = [
                'qemu-img', 'convert',
                '-f', 'qcow2',
                '-O', 'qcow2',
                '-c',  # Enable compression
                '-o', 'compression_type=zlib,cluster_size=65536',
                '-p',  # Show progress
                image_path,
                temp_compressed_path
            ]
            
            print(f"Compressing image: {' '.join(cmd)}")
            
            # Execute with progress monitoring
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Track the process for external termination
            if process_tracker is not None:
                process_tracker.compression_process = process
            
            last_update_time = time.time()
            update_interval = 0.5
            
            # Monitor compression progress
            for line in process.stdout:
                line = line.strip()
                if line and '%' in line:
                    current_time = time.time()
                    if current_time - last_update_time >= update_interval:
                        try:
                            match = re.search(r'\((\d+(?:\.\d+)?)/100%\)', line)
                            if match:
                                percent = float(match.group(1))
                                scaled_progress = 5 + int(percent * 0.85)
                                
                                if progress_callback:
                                    progress_callback(scaled_progress, f"Compressing: {int(percent)}%")
                                
                                last_update_time = current_time
                        except (ValueError, IndexError, AttributeError):
                            pass
            
            return_code = process.wait()
            
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, cmd)
            
            if progress_callback:
                progress_callback(92, "Compression complete, verifying...")
            
            # Verify compressed image was created
            if not os.path.exists(temp_compressed_path):
                raise FileNotFoundError(f"Compressed image was not created: {temp_compressed_path}")
            
            compressed_file_size = os.path.getsize(temp_compressed_path)
            
            print(f"Compressed image stats:")
            print(f"  File size: {QCow2CloneResizer.format_size(compressed_file_size)}")
            
            # Calculate compression ratio
            compression_ratio = (original_file_size - compressed_file_size) / original_file_size * 100 if original_file_size > 0 else 0
            
            print(f"Compression results:")
            print(f"  Original file size: {QCow2CloneResizer.format_size(original_file_size)}")
            print(f"  Compressed file size: {QCow2CloneResizer.format_size(compressed_file_size)}")
            print(f"  Space saved: {QCow2CloneResizer.format_size(original_file_size - compressed_file_size)}")
            print(f"  Compression ratio: {compression_ratio:.1f}%")
            
            if progress_callback:
                progress_callback(95, "Checking compression savings...")
            
            # Check if compression is worth it (more than 1MB savings)
            min_savings = 1024 * 1024
            if compressed_file_size >= (original_file_size - min_savings):
                print(f"WARNING: Compression saved less than 1MB")
                QCow2CloneResizer._force_remove_file(temp_compressed_path)
                
                if progress_callback:
                    progress_callback(100, "Compression skipped (minimal savings)")
                
                return {
                    'original_size': original_file_size,
                    'compressed_size': original_file_size,
                    'space_saved': 0,
                    'compression_ratio': 0.0,
                }
            
            if progress_callback:
                progress_callback(97, "Replacing original with compressed version...")
            
            print(f"Replacing original with compressed version...")
            
            # Windows-safe file replacement with retries
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    os.remove(image_path)
                    os.rename(temp_compressed_path, image_path)
                    print(f"Image replaced successfully")
                    break
                except (PermissionError, FileNotFoundError, OSError) as e:
                    if attempt < max_retries - 1:
                        print(f"Attempt {attempt + 1} failed: {e}")
                        time.sleep(2)
                    else:
                        raise
            
            print(f"Image compression completed and replaced in place")
            
            if progress_callback:
                progress_callback(100, "Compression complete")
            
            return {
                'original_size': original_file_size,
                'compressed_size': compressed_file_size,
                'space_saved': original_file_size - compressed_file_size,
                'compression_ratio': compression_ratio,
            }
            
        except subprocess.CalledProcessError as e:
            print(f"ERROR - compression command failed: {e}")
            QCow2CloneResizer._force_remove_file(temp_compressed_path)
            raise
        except FileNotFoundError as e:
            print(f"ERROR - file not found during compression: {e}")
            QCow2CloneResizer._force_remove_file(temp_compressed_path)
            raise
        except PermissionError as e:
            print(f"ERROR - permission denied during compression: {e}")
            QCow2CloneResizer._force_remove_file(temp_compressed_path)
            raise
        except OSError as e:
            print(f"ERROR - OS error during compression: {e}")
            QCow2CloneResizer._force_remove_file(temp_compressed_path)
            raise
        except json.JSONDecodeError as e:
            print(f"ERROR - JSON parsing error during compression: {e}")
            QCow2CloneResizer._force_remove_file(temp_compressed_path)
            raise
        except ValueError as e:
            print(f"ERROR - invalid value during compression: {e}")
            QCow2CloneResizer._force_remove_file(temp_compressed_path)
            raise
        finally:
            # Clear process reference
            if process_tracker is not None:
                process_tracker.compression_process = None

    @staticmethod
    def _force_remove_file(file_path):
        """Force remove a file with retries (for Windows file locking)
        
        Gère le cas où le fichier a déjà été supprimé par qemu-img lors de son interruption
        """
        if not file_path:
            return True
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"✓ File already cleaned up: {Path(file_path).name}")
            return True
        
        print(f"\nCleaning up temporary file: {file_path}")
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                os.remove(file_path)
                print(f"✓ Temporary file successfully removed: {Path(file_path).name}")
                return True
            except FileNotFoundError:
                print(f"✓ File already cleaned up: {Path(file_path).name}")
                return True
            except (PermissionError, OSError) as e:
                if attempt < max_retries - 1:
                    print(f"  Attempt {attempt + 1}/{max_retries}: File locked, retrying in 1 second...")
                    time.sleep(1)
                else:
                    print(f"✗ Could not remove temporary file after {max_retries} attempts: {e}")
                    return False
        
        return False
        
    @staticmethod
    def parse_size(size_str):
        """Parse size string like '20G', '512M' to bytes"""
        if isinstance(size_str, (int, float)):
            return int(size_str)
        
        size_str = str(size_str).strip().upper()
        
        # Match pattern like "20G", "512M", "1.5T"
        match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT]?)B?$', size_str)
        if not match:
            raise ValueError(f"Invalid size format: {size_str}")
        
        number = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {'': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        return int(number * multipliers[unit])
    
    @staticmethod
    def format_size(bytes_val):
        """Format bytes to human readable"""
        if bytes_val == 0:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
    
    @staticmethod
    def get_image_info(image_path):
        """Get QCOW2 image information"""
        try:
            # First check if file exists and is readable
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file does not exist: {image_path}")
            
            if not os.access(image_path, os.R_OK):
                raise PermissionError(f"Image file is not readable (check permissions): {image_path}")
            
            file_size = os.path.getsize(image_path)
            print(f"Image file exists: {image_path} ({QCow2CloneResizer.format_size(file_size)})")
            
            result = subprocess.run(
                ['qemu-img', 'info', '--output=json', image_path],
                capture_output=True, text=True, check=True
            )
            data = json.loads(result.stdout)
            
            return {
                'virtual_size': data.get('virtual-size', 0),
                'actual_size': data.get('actual-size', 0),
                'format': data.get('format', 'unknown'),
                'compressed': data.get('compressed', False)
            }
        except subprocess.CalledProcessError as e:
            error_msg = f"qemu-img failed to analyze image: {image_path}\n"
            error_msg += f"Return code: {e.returncode}\n"
            if e.stdout:
                error_msg += f"Stdout: {e.stdout}\n"
            if e.stderr:
                error_msg += f"Stderr: {e.stderr}\n"
            
            # Try to get more info with non-JSON output
            try:
                fallback_result = subprocess.run(
                    ['qemu-img', 'info', image_path],
                    capture_output=True, text=True, check=False
                )
                if fallback_result.stdout:
                    error_msg += f"Fallback info output:\n{fallback_result.stdout}\n"
                if fallback_result.stderr:
                    error_msg += f"Fallback info stderr:\n{fallback_result.stderr}\n"
            except subprocess.CalledProcessError as fallback_e:
                error_msg += f"Fallback check also failed: {fallback_e}\n"
            except FileNotFoundError as fallback_file:
                error_msg += f"qemu-img command not found in fallback: {fallback_file}\n"
            except OSError as fallback_os:
                error_msg += f"OS error in fallback check: {fallback_os}\n"
            
            print(f"ERROR: {error_msg}")
            raise RuntimeError(error_msg)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Failed to parse qemu-img JSON output", e.doc, e.pos)
        except FileNotFoundError:
            raise FileNotFoundError(f"Image file not found: {image_path}")
        except PermissionError:
            raise PermissionError(f"Permission denied accessing image: {image_path}")
        except OSError as e:
            raise OSError(f"OS error accessing image {image_path}: {e}")
    
    @staticmethod
    def setup_nbd_device(image_path, progress_callback=None, exclude_devices=None):
        """Setup NBD device with proper availability detection"""
        try:
            if progress_callback:
                progress_callback(5, "Setting up NBD device...")
            
            # Load nbd module
            subprocess.run(['modprobe', 'nbd'], check=False)
            
            exclude_devices = exclude_devices or []
            
            # Find available NBD device with better detection
            nbd_device = None
            for i in range(16):  # Check nbd0 to nbd15
                device = f"/dev/nbd{i}"
                
                # Skip excluded devices
                if device in exclude_devices:
                    print(f"Skipping excluded device: {device}")
                    continue
                    
                if not os.path.exists(device):
                    print(f"Device {device} does not exist")
                    continue
                
                # Check if device is available using multiple methods
                device_available = True
                
                try:
                    # Method 1: Check if qemu-nbd can list the device (means it's connected)
                    list_result = subprocess.run(
                        ['qemu-nbd', '--list', device],
                        capture_output=True, text=True, check=False
                    )
                    # If --list succeeds, device is connected/busy
                    if list_result.returncode == 0:
                        print(f"Device {device} is connected (qemu-nbd --list succeeded)")
                        device_available = False
                    
                except FileNotFoundError:
                    print(f"qemu-nbd not found for checking {device}")
                except subprocess.SubprocessError as e:
                    print(f"Subprocess error checking {device} with qemu-nbd --list: {e}")
                    # Continue with other checks
                
                if not device_available:
                    continue
                
                try:
                    # Method 2: Check if blockdev can get size (means device has content)
                    size_result = subprocess.run(
                        ['blockdev', '--getsize64', device],
                        capture_output=True, text=True, check=False
                    )
                    # If blockdev succeeds and shows size > 0, device is connected
                    if size_result.returncode == 0:
                        size = int(size_result.stdout.strip())
                        if size > 0:
                            print(f"Device {device} has size {size}, appears connected")
                            device_available = False
                    
                except ValueError as e:
                    print(f"Error parsing size for {device}: {e}")
                    # This is actually good - means device is likely free
                except FileNotFoundError:
                    print(f"blockdev command not found for checking {device}")
                except subprocess.SubprocessError as e:
                    print(f"Subprocess error checking {device} size: {e}")
                    # This is actually good - means device is likely free
                
                if not device_available:
                    continue
                
                try:
                    # Method 3: Check lsblk more carefully
                    lsblk_result = subprocess.run(
                        ['lsblk', '-n', device],  # -n for no headers
                        capture_output=True, text=True, check=False
                    )
                    # If lsblk shows the device with partitions, it's in use
                    if lsblk_result.returncode == 0 and lsblk_result.stdout.strip():
                        lines = [line.strip() for line in lsblk_result.stdout.strip().split('\n') if line.strip()]
                        if len(lines) > 1:  # More than just the device line means partitions
                            print(f"Device {device} has partitions: {lines}")
                            device_available = False
                    
                except FileNotFoundError:
                    print(f"lsblk command not found for checking {device}")
                except subprocess.SubprocessError as e:
                    print(f"Subprocess error checking {device} with lsblk: {e}")
                
                if device_available:
                    nbd_device = device
                    print(f"Device {device} appears to be available")
                    break
                else:
                    print(f"Device {device} is busy/connected")
            
            if not nbd_device:
                # Last resort: try to force disconnect all devices and retry
                print("No free NBD device found, attempting cleanup...")
                for i in range(16):
                    device = f"/dev/nbd{i}"
                    if device not in exclude_devices and os.path.exists(device):
                        try:
                            print(f"Force disconnecting {device}...")
                            subprocess.run(['qemu-nbd', '--disconnect', device], 
                                        capture_output=True, check=False)
                        except subprocess.SubprocessError as e:
                            print(f"Subprocess error disconnecting {device}: {e}")
                        except FileNotFoundError:
                            print(f"qemu-nbd not found for disconnecting {device}")
                
                # Wait and try again
                time.sleep(3)
                
                # Retry with first non-excluded device
                for i in range(16):
                    device = f"/dev/nbd{i}"
                    if device not in exclude_devices and os.path.exists(device):
                        nbd_device = device
                        print(f"Using {device} after cleanup attempt")
                        break
            
            if not nbd_device:
                raise Exception("No available NBD device found after cleanup attempts")
            
            print(f"Selected NBD device: {nbd_device}")
            
            # Try to connect
            connect_cmd = ['qemu-nbd', '--connect', nbd_device, image_path]
            print(f"Connecting: {' '.join(connect_cmd)}")
            
            try:
                result = subprocess.run(
                    connect_cmd,
                    capture_output=True, text=True, check=True
                )
                
                if result.stdout:
                    print(f"qemu-nbd stdout: {result.stdout}")
                if result.stderr:
                    print(f"qemu-nbd stderr: {result.stderr}")
                    
            except subprocess.CalledProcessError as e:
                error_details = f"qemu-nbd connect failed for {nbd_device}:\n"
                error_details += f"Return code: {e.returncode}\n"
                if e.stdout:
                    error_details += f"Stdout: {e.stdout}\n"
                if e.stderr:
                    error_details += f"Stderr: {e.stderr}\n"
                    
                # Try next available device if this one failed
                print(f"Connection failed, trying alternative devices...")
                for i in range(16):
                    alt_device = f"/dev/nbd{i}"
                    if alt_device != nbd_device and alt_device not in exclude_devices and os.path.exists(alt_device):
                        try:
                            print(f"Trying alternative device: {alt_device}")
                            # Force disconnect first
                            subprocess.run(['qemu-nbd', '--disconnect', alt_device], 
                                        capture_output=True, check=False)
                            time.sleep(1)
                            # Try to connect
                            subprocess.run(['qemu-nbd', '--connect', alt_device, image_path],
                                        capture_output=True, text=True, check=True)
                            nbd_device = alt_device
                            print(f"Successfully connected to {alt_device}")
                            break
                        except subprocess.CalledProcessError as alt_e:
                            print(f"Alternative device {alt_device} connection failed: {alt_e}")
                            continue
                        except FileNotFoundError:
                            print(f"qemu-nbd not found for alternative device {alt_device}")
                            continue
                else:
                    raise Exception(f"Could not connect to any NBD device. Last error: {error_details}")
            except FileNotFoundError:
                raise Exception("qemu-nbd command not found")
            
            # Wait for device to be ready
            print(f"Waiting for {nbd_device} to be ready...")
            max_attempts = 20
            for attempt in range(max_attempts):
                time.sleep(1)
                
                # Force kernel to re-read partition table
                subprocess.run(['partprobe', nbd_device], check=False, 
                            capture_output=True)
                time.sleep(1)
                
                # Check if device is accessible
                try:
                    result = subprocess.run(['lsblk', nbd_device], 
                                        capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"NBD device {nbd_device} is ready after {attempt + 1} attempts")
                        if result.stdout.strip():
                            print(f"Device info:\n{result.stdout}")
                        break
                except FileNotFoundError:
                    print(f"Attempt {attempt + 1}: lsblk command not found")
                except subprocess.SubprocessError as e:
                    print(f"Attempt {attempt + 1}: Device check subprocess error: {e}")
                
                if attempt == max_attempts - 1:
                    print(f"Warning: NBD device setup may be incomplete after {max_attempts} attempts")
                    print("Proceeding anyway...")
            
            return nbd_device
            
        except FileNotFoundError:
            print(f"ERROR: Required command not found during NBD setup")
            raise Exception("Required system commands not available for NBD setup")
        except PermissionError:
            print(f"ERROR: Permission denied during NBD setup")
            raise Exception("Permission denied - run as root or with sudo")
        except OSError as e:
            print(f"ERROR: System error during NBD setup: {e}")
            raise Exception(f"System error during NBD setup: {e}")

    @staticmethod
    def cleanup_nbd_device(nbd_device):
        """Enhanced NBD device cleanup with better error handling"""
        if not nbd_device:
            return
            
        try:
            print(f"Cleaning up NBD device: {nbd_device}")
            
            # Multiple disconnect attempts
            success = False
            for attempt in range(5):  # Try up to 5 times
                try:
                    print(f"Disconnect attempt {attempt + 1}")
                    result = subprocess.run(['qemu-nbd', '--disconnect', nbd_device], 
                                        capture_output=True, text=True, check=True)
                    print(f"Disconnect successful on attempt {attempt + 1}")
                    if result.stdout:
                        print(f"  stdout: {result.stdout}")
                    success = True
                    break
                except subprocess.CalledProcessError as e:
                    print(f"Disconnect attempt {attempt + 1} failed: return code {e.returncode}")
                    if e.stderr:
                        print(f"  stderr: {e.stderr}")
                    time.sleep(2)
                except FileNotFoundError:
                    print(f"Disconnect attempt {attempt + 1}: qemu-nbd command not found")
                    time.sleep(2)
                except subprocess.SubprocessError as e:
                    print(f"Disconnect attempt {attempt + 1} subprocess error: {e}")
                    time.sleep(2)
            
            if not success:
                print(f"Warning: Could not cleanly disconnect {nbd_device}")
                print("Trying force kill of qemu-nbd processes...")
                try:
                    # Try to kill any qemu-nbd processes using this device
                    subprocess.run(['pkill', '-f', f'qemu-nbd.*{nbd_device}'], 
                                check=False)
                    time.sleep(2)
                except FileNotFoundError:
                    print("pkill command not found")
                except subprocess.SubprocessError as e:
                    print(f"pkill subprocess error: {e}")
            
            # Final verification
            time.sleep(2)
            try:
                result = subprocess.run(['lsblk', nbd_device],
                                    capture_output=True, text=True)
                if result.returncode != 0 or not result.stdout.strip():
                    print(f"NBD device {nbd_device} appears to be disconnected")
                else:
                    print(f"Warning: {nbd_device} may still be connected")
            except FileNotFoundError:
                print(f"lsblk command not found for verification")
            except subprocess.SubprocessError as e:
                print(f"NBD device {nbd_device} disconnect verification subprocess error: {e}")
                
        except OSError as e:
            print(f"OS error in cleanup_nbd_device: {e}")
        except PermissionError:
            print(f"Permission error in cleanup_nbd_device")

    # Also need a simple helper to check if a specific NBD device is actually free
    @staticmethod
    def is_nbd_device_free(device_path):
        """Check if a specific NBD device is actually free"""
        try:
            if not os.path.exists(device_path):
                return False
            
            # Quick checks
            # 1. Can we get size? If yes and > 0, it's connected
            try:
                result = subprocess.run(['blockdev', '--getsize64', device_path],
                                    capture_output=True, text=True, check=False)
                if result.returncode == 0 and int(result.stdout.strip()) > 0:
                    return False
            except ValueError as e:
                print(f"Error parsing blockdev size for {device_path}: {e}")
            except FileNotFoundError:
                print(f"blockdev command not found for {device_path}")
            except subprocess.SubprocessError as e:
                print(f"blockdev subprocess error for {device_path}: {e}")
            
            # 2. Does qemu-nbd think it's connected?
            try:
                result = subprocess.run(['qemu-nbd', '--list', device_path],
                                    capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    return False
            except FileNotFoundError:
                print(f"qemu-nbd command not found for {device_path}")
            except subprocess.SubprocessError as e:
                print(f"qemu-nbd list subprocess error for {device_path}: {e}")
            
            # 3. Does lsblk show partitions?
            try:
                result = subprocess.run(['lsblk', '-n', device_path],
                                    capture_output=True, text=True, check=False)
                if result.returncode == 0 and result.stdout.strip():
                    lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
                    if len(lines) > 1:
                        return False
            except FileNotFoundError:
                print(f"lsblk command not found for {device_path}")
            except subprocess.SubprocessError as e:
                print(f"lsblk subprocess error for {device_path}: {e}")
            
            return True
            
        except FileNotFoundError:
            print(f"Device file not found: {device_path}")
            return False
        except PermissionError:
            print(f"Permission denied checking if {device_path} is free")
            return False
        except OSError as e:
            print(f"OS error checking if {device_path} is free: {e}")
            return False

    @staticmethod
    def get_partition_layout(nbd_device):
        """Get partition layout — multi-tool fallback with aggressive retry.

        Tool priority (most to least reliable):
          1. sfdisk -J   : JSON, sector-precise, never crashes on exotic types
          2. parted -s   : human-readable, well-tested; may crash on some GPTs
          3. lsblk -P    : reads kernel metadata; requires prior successful partprobe

        Between each failed attempt the kernel partition table is forcibly
        re-read (partprobe + blockdev --rereadpt) and we wait up to 10 s total
        before giving up.  This eliminates the race condition where the kernel
        has not yet propagated the partition layout after qemu-nbd connected.
        """
        sep = '=' * 60
        print(f"\nGetting partition layout from {nbd_device}...")

        # ── Helper: enrich partitions with blockdev kernel sizes ─────────────
        def _fill_blockdev_sizes(partitions):
            for p in partitions:
                if p.get('blockdev_size_bytes') is not None:
                    continue
                for fmt in (f"{nbd_device}p{p['number']}", f"{nbd_device}{p['number']}"):
                    if os.path.exists(fmt):
                        try:
                            bv = subprocess.run(
                                ['blockdev', '--getsize64', fmt],
                                capture_output=True, text=True, check=True, timeout=10
                            )
                            p['blockdev_size_bytes'] = int(bv.stdout.strip())
                        except Exception:
                            pass
                        break

        # ── Helper: build final result dict ──────────────────────────────────
        def _make_result(partitions):
            if not partitions:
                return None
            max_end = max(p['end_bytes'] for p in partitions)
            buf     = int(max_end * 0.05)
            req     = max_end + buf
            print(f"\n{sep}")
            print("Image size calculation:")
            print(f"  Last partition ends at: {QCow2CloneResizer.format_size(max_end)}")
            print(f"  Safety buffer (5%):     {QCow2CloneResizer.format_size(buf)}")
            print(f"  RECOMMENDED IMAGE SIZE: {QCow2CloneResizer.format_size(req)}")
            print(f"{sep}\n")
            return {
                'partitions':              partitions,
                'last_partition_end_bytes': max_end,
                'required_minimum_bytes':  req,
                'partition_count':         len(partitions),
            }

        # ── Helper: parted text parse (extracted from old implementation) ────
        def _parse_parted_output(parted_output):
            partitions = []
            for line in parted_output.split('\n'):
                line = line.strip()
                if not re.match(r'^\d+\s+', line):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    part_num  = int(parts[0])
                    start_str = parts[1]
                    end_str   = parts[2]
                except (ValueError, IndexError):
                    continue

                def _parse(s):
                    s = (s or '').strip().replace(',', '.')
                    _UNITS = [
                        (r'([\d.]+)\s*TiB', 1024**4), (r'([\d.]+)\s*GiB', 1024**3),
                        (r'([\d.]+)\s*MiB', 1024**2), (r'([\d.]+)\s*KiB', 1024),
                        (r'([\d.]+)\s*TB',  1000**4), (r'([\d.]+)\s*GB',  1000**3),
                        (r'([\d.]+)\s*MB',  1000**2), (r'([\d.]+)\s*kB',  1000),
                        (r'([\d.]+)\s*B',   1),
                    ]
                    for pat, mul in _UNITS:
                        m = re.search(pat, s, re.IGNORECASE)
                        if m:
                            try:
                                return int(float(m.group(1)) * mul)
                            except Exception:
                                continue
                    try:
                        return int(float(s))
                    except Exception:
                        return 0

                partitions.append({
                    'number':            part_num,
                    'start':             start_str,
                    'end':               end_str,
                    'start_bytes':       _parse(start_str),
                    'end_bytes':         _parse(end_str),
                    'size':              parts[3] if len(parts) > 3 else 'unknown',
                    'blockdev_size_bytes': None,
                })
            return partitions

        # ════════════════════════════════════════════════════════════════════
        # Retry loop — up to 4 rounds, increasingly longer waits
        # ════════════════════════════════════════════════════════════════════
        wait_seq = [0, 3, 5, 7]   # seconds to wait before each attempt

        for attempt, wait in enumerate(wait_seq):
            if wait > 0:
                print(f"\n  [Attempt {attempt + 1}/{len(wait_seq)}] "
                      f"Waiting {wait}s then re-reading partition table...")
                time.sleep(wait)

            # Force kernel re-read every attempt
            QCow2CloneResizer._force_reread_partition_table(nbd_device, wait=2)

            # ── Method 1: sfdisk (most reliable) ─────────────────────────
            print(f"  [Attempt {attempt + 1}] Trying sfdisk -J...")
            layout = QCow2CloneResizer._layout_from_sfdisk(nbd_device)
            if layout and layout['partition_count'] > 0:
                _fill_blockdev_sizes(layout['partitions'])
                print(f"  ✓ sfdisk succeeded with "
                      f"{layout['partition_count']} partition(s)")
                return layout

            # ── Method 2: parted ──────────────────────────────────────────
            print(f"  [Attempt {attempt + 1}] Trying parted...")
            parted_out = QCow2CloneResizer._safe_parted_print(nbd_device)
            if parted_out:
                print(parted_out)
                parts = _parse_parted_output(parted_out)
                if parts:
                    _fill_blockdev_sizes(parts)
                    result = _make_result(parts)
                    if result:
                        print(f"  ✓ parted succeeded with {len(parts)} partition(s)")
                        return result

            # ── Method 3: lsblk ───────────────────────────────────────────
            print(f"  [Attempt {attempt + 1}] Trying lsblk...")
            layout = QCow2CloneResizer._layout_from_lsblk(nbd_device)
            if layout and layout['partition_count'] > 0:
                print(f"  ✓ lsblk succeeded with "
                      f"{layout['partition_count']} partition(s)")
                return layout

            print(f"  ✗ Attempt {attempt + 1}: no partitions visible yet")

        # All attempts exhausted
        raise Exception(
            f"No partitions found on {nbd_device} after "
            f"{len(wait_seq)} attempts using sfdisk, parted, and lsblk. "
            f"The NBD device may not be properly connected or the image "
            f"may have an unsupported partition table format."
        )


    def _perform_safe_sync_static(operation_name="Sync"):
        """Perform sync operation with proper error handling"""
        try:
            print(f"{operation_name}: Starting sync...")
            
            process = subprocess.Popen(['sync'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                print(f"{operation_name}: Sync completed")
                time.sleep(2)
                return True
            # Fallback
            subprocess.run(['sync', '-f'], check=False)
            time.sleep(2)
            return True
            
        except Exception as e:
            print(f"{operation_name}: Error (non-fatal): {e}")
            time.sleep(5)
            return False
    
    @staticmethod
    def launch_gparted(nbd_device):
        """Launch GParted GUI for partition operations"""
        try:
            if not shutil.which('gparted'):
                raise Exception("GParted not available - install gparted package")
            
            print(f"Launching GParted for device: {nbd_device}")
            
            # Launch GParted with proper environment
            env = os.environ.copy()
            env['DISPLAY'] = env.get('DISPLAY', ':0')
            
            # Use privilege escalation if needed
            if os.geteuid() != 0:
                escalation_commands = [
                    ['pkexec', 'gparted', nbd_device],
                    ['gksudo', 'gparted', nbd_device],
                    ['sudo', 'gparted', nbd_device]
                ]
                
                for cmd in escalation_commands:
                    if shutil.which(cmd[0]):
                        try:
                            print(f"Using {cmd[0]} for privilege escalation")
                            subprocess.run(cmd, env=env)
                            return True
                        except subprocess.CalledProcessError as e:
                            print(f"Failed with {cmd[0]}: return code {e.returncode}")
                            continue
                        except FileNotFoundError:
                            print(f"Command {cmd[0]} not found")
                            continue
                
                print("Warning: No privilege escalation found, trying direct launch")
            
            # Direct launch
            subprocess.run(['gparted', nbd_device], env=env)
            return True
            
        except FileNotFoundError:
            raise Exception("GParted command not found")
        except PermissionError:
            raise Exception("Permission denied launching GParted")
        except OSError as e:
            raise Exception(f"System error launching GParted: {e}")
    
    @staticmethod
    def create_new_qcow2_image(target_path, size_bytes, progress_callback=None):
        """Create a new QCOW2 image with specified size and metadata preallocation"""
        try:
            if progress_callback:
                progress_callback(20, "Creating new image with metadata preallocation...")
            
            # Remove file if it already exists
            if os.path.exists(target_path):
                print(f"Removing existing file: {target_path}")
                os.remove(target_path)
            
            # Create new QCOW2 image with metadata preallocation
            cmd = [
                'qemu-img', 'create', 
                '-f', 'qcow2',
                '-o', 'preallocation=metadata',
                target_path, 
                str(size_bytes)
            ]
            
            print(f"Creating new image: {' '.join(cmd)}")
            print(f"This may take several minutes for large disks...")
            
            # Start the process WITHOUT timeout - let it finish naturally
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # Monitor progress with periodic updates (no timeout limit)
            start_time = time.time()
            last_update = start_time
            update_interval = 5.0  # Update every 5 seconds instead of 2
            last_percent = 20
            
            while process.poll() is None:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Update progress periodically
                if current_time - last_update >= update_interval:
                    if progress_callback:
                        # Linear progress based on time (assume 1 minute per GB)
                        size_gb = size_bytes / (1024**3)
                        estimated_time = max(60, size_gb * 60)  # 1 minute per GB minimum
                        percent = min(29, 20 + int((elapsed / estimated_time) * 9))
                        
                        if percent > last_percent:
                            progress_callback(
                                percent,
                                f"Creating image... {int(elapsed)}s elapsed ({int(size_gb)}GB)"
                            )
                            last_percent = percent
                    
                    last_update = current_time
                
                # NO HARD TIMEOUT - just a warning every 5 minutes
                if elapsed > 300 and int(elapsed) % 300 == 0:
                    print(f"Note: Image creation still in progress ({int(elapsed)}s elapsed)...")
                
                time.sleep(1)  # Check process status every 1 second
            
            # Get final output
            stdout, stderr = process.communicate()
            
            if stdout:
                print(f"qemu-img output: {stdout}")
            if stderr:
                print(f"qemu-img stderr: {stderr}")
            
            # Check return code
            if process.returncode != 0:
                error_msg = f"qemu-img failed with return code {process.returncode}"
                if stderr:
                    error_msg += f"\nError: {stderr}"
                raise subprocess.CalledProcessError(process.returncode, cmd, stderr)
            
            # Verify the image was created successfully
            if not os.path.exists(target_path):
                raise Exception(f"Image file was not created: {target_path}")
            
            # Brief wait for filesystem to catch up
            time.sleep(2)
            
            # Verify image properties
            verify_info = QCow2CloneResizer.get_image_info(target_path)
            if verify_info['virtual_size'] != size_bytes:
                print(f"WARNING: Image size mismatch - requested: {size_bytes}, actual: {verify_info['virtual_size']}")
            
            print(f"New image created successfully:")
            print(f"  Path: {target_path}")
            print(f"  Virtual Size: {QCow2CloneResizer.format_size(verify_info['virtual_size'])}")
            print(f"  File Size: {QCow2CloneResizer.format_size(verify_info['actual_size'])}")
            print(f"  Format: {verify_info['format']}")
            
            if progress_callback:
                progress_callback(30, "New image created successfully")
            
            return target_path
            
        except subprocess.CalledProcessError as e:
            error_msg = f"qemu-img failed: {e.stderr if e.stderr else str(e)}"
            print(f"ERROR: {error_msg}")
            raise Exception(error_msg)
        except FileNotFoundError:
            raise Exception("qemu-img command not found")
        except PermissionError:
            raise Exception(f"Permission denied creating image: {target_path}")
        except OSError as e:
            print(f"ERROR creating image: {e}")
            raise Exception(f"Failed to create image: {e}")

    @staticmethod
    @staticmethod
    def clone_disk_structure(source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone disk structure: partition table + partitions sized from kernel blockdev.

        KEY DESIGN — guarantees tgt_size >= src_size for every partition:

        • Non-last partitions: end = start_bytes + blockdev_size_bytes + 2 MiB alignment pad,
          expressed as exact bytes to parted ("-s … <N>B").  The 2 MiB pad absorbs any
          sector-alignment rounding parted applies, so the created partition is always
          >= the source.

        • Last partition: always created with end = "100%" so it fills all remaining
          space on the target disk, unconditionally >= source last partition.

        This eliminates the "target N bytes smaller than source" condition that previously
        caused either a hard ValueError or silent data truncation at the tail of the partition.
        """
        try:
            if progress_callback:
                progress_callback(40, "Cloning partition table...")

            print(f"Cloning disk structure from {source_nbd} to {target_nbd}")

            # ── Step 1: Copy MBR / GPT header (first 1 MB) ───────────────────
            dd_cmd = [
                'dd',
                f'if={source_nbd}',
                f'of={target_nbd}',
                'bs=1M', 'count=1',
                'conv=notrunc',
                'status=none',
            ]
            print(f"Copying MBR/GPT: {' '.join(dd_cmd)}")
            subprocess.run(dd_cmd, capture_output=True, text=True, check=True)

            if progress_callback:
                progress_callback(50, "Recreating partition table...")

            # ── Step 2: Detect partition table type and flags from source ─────
            parted_result = subprocess.run(
                ['parted', '-s', source_nbd, 'print'],
                capture_output=True, text=True, check=True
            )
            source_parted_output = parted_result.stdout

            table_type = 'msdos'
            for line in source_parted_output.split('\n'):
                if 'Partition Table:' in line:
                    table_type = line.split(':')[1].strip()
                    break
            print(f"Partition table type: {table_type}")

            # Build flag map: {part_num: [flag, …]}
            flag_map = {}
            for line in source_parted_output.split('\n'):
                if re.match(r'^\s*\d+\s+', line):
                    try:
                        part_num = int(line.split()[0])
                    except (ValueError, IndexError):
                        continue
                    flags = []
                    ll = line.lower()
                    if 'esp'       in ll: flags.append('esp')
                    elif 'boot'    in ll: flags.append('boot')
                    if 'bios_grub' in ll: flags.append('bios_grub')
                    if 'swap'      in ll: flags.append('swap')
                    if 'lvm'       in ll: flags.append('lvm')
                    if 'raid'      in ll: flags.append('raid')
                    flag_map[part_num] = flags

            # ── Step 3: Recreate partition table on target ────────────────────
            subprocess.run(
                ['parted', '-s', target_nbd, 'mklabel', table_type],
                check=True
            )
            subprocess.run(['sync'], check=False)

            # ── Step 4: Recreate each partition with kernel-accurate sizing ───
            partitions = layout_info['partitions']
            last_index  = len(partitions) - 1

            for i, partition in enumerate(partitions):
                part_num = partition['number']
                is_last  = (i == last_index)

                if progress_callback:
                    progress_callback(55 + i * 5, f"Creating partition {part_num}...")

                # ── Both start AND end must use the same unit (bytes) ─────────
                # Mixing units (e.g. '538MB' start + '32234274816B' end) causes
                # parted to exit with status 1.  We always express both in bytes.
                start_bytes_val = partition['start_bytes']
                start_str       = f"{start_bytes_val}B"

                if is_last:
                    # Last partition → fill ALL remaining space on target disk.
                    # '100%' is special parted syntax, not a bytes value — it is
                    # compatible with any start unit when used as end.
                    end_str = '100%'
                    print(f"Partition {part_num} (LAST): {start_str} → {end_str}  [fills disk]")
                else:
                    # Non-last partition: true kernel size + 2 MiB alignment pad,
                    # expressed in bytes so unit is consistent with start_str.
                    src_part_device = None
                    for fmt in (f"{source_nbd}p{part_num}", f"{source_nbd}{part_num}"):
                        if os.path.exists(fmt):
                            src_part_device = fmt
                            break

                    blockdev_bytes = partition.get('blockdev_size_bytes')
                    if blockdev_bytes is None and src_part_device:
                        try:
                            blockdev_bytes = int(subprocess.run(
                                ['blockdev', '--getsize64', src_part_device],
                                capture_output=True, text=True, check=True
                            ).stdout.strip())
                        except Exception as bde:
                            print(f"  ⚠ blockdev fallback failed for {src_part_device}: {bde}")

                    if blockdev_bytes and blockdev_bytes > 0:
                        ALIGN_PAD = 2 * 1024 * 1024   # 2 MiB — absorbs sector rounding
                        end_bytes = start_bytes_val + blockdev_bytes + ALIGN_PAD
                        end_str   = f"{end_bytes}B"
                        print(f"Partition {part_num}: {start_str} → {end_str}  "
                              f"(blockdev={QCow2CloneResizer.format_size(blockdev_bytes)} + 2 MiB pad)")
                    else:
                        # Last-resort fallback: parted end + 5 % buffer, in bytes
                        end_bytes_fallback = int(partition['end_bytes'] * 1.05)
                        end_str = f"{end_bytes_fallback}B"
                        print(f"Partition {part_num}: {start_str} → {end_str}  "
                              f"(fallback: parted end + 5 %)")

                result = subprocess.run(
                    ['parted', '-s', target_nbd, 'mkpart', 'primary', start_str, end_str],
                    capture_output=True, text=True, check=True
                )
                if result.stderr:
                    print(f"  parted stderr: {result.stderr.strip()}")

                # Apply flags for this partition
                for flag in flag_map.get(part_num, []):
                    try:
                        subprocess.run(
                            ['parted', '-s', target_nbd, 'set', str(part_num), flag, 'on'],
                            capture_output=True, text=True, check=True
                        )
                        print(f"  ✓ Flag '{flag}' on partition {part_num}")
                    except subprocess.CalledProcessError as fe:
                        print(f"  ⚠ Could not set flag '{flag}' on partition {part_num}: {fe.stderr}")

                subprocess.run(['sync'], check=False)
                subprocess.run(['partprobe', target_nbd], check=False)

            # ── Step 5: Final probe + verify ──────────────────────────────────
            time.sleep(3)
            subprocess.run(['partprobe', target_nbd], check=False)
            time.sleep(2)

            verify = subprocess.run(
                ['lsblk', target_nbd], capture_output=True, text=True
            )
            print(f"Target partition layout:\n{verify.stdout}")

            # ── Step 6: Confirm tgt >= src for every partition ────────────────
            print("Verifying target partition sizes >= source partition sizes...")
            all_ok = True
            for partition in layout_info['partitions']:
                part_num = partition['number']
                src_dev = dst_dev = None
                for fmt in (f"{source_nbd}p{part_num}", f"{source_nbd}{part_num}"):
                    if os.path.exists(fmt): src_dev = fmt; break
                for fmt in (f"{target_nbd}p{part_num}", f"{target_nbd}{part_num}"):
                    if os.path.exists(fmt): dst_dev = fmt; break
                if not src_dev or not dst_dev:
                    continue
                try:
                    src_sz = int(subprocess.run(
                        ['blockdev', '--getsize64', src_dev],
                        capture_output=True, text=True, check=True
                    ).stdout.strip())
                    dst_sz = int(subprocess.run(
                        ['blockdev', '--getsize64', dst_dev],
                        capture_output=True, text=True, check=True
                    ).stdout.strip())
                    status = "✓" if dst_sz >= src_sz else "✗"
                    print(f"  {status} Partition {part_num}: "
                          f"src={QCow2CloneResizer.format_size(src_sz)}  "
                          f"tgt={QCow2CloneResizer.format_size(dst_sz)}")
                    if dst_sz < src_sz:
                        all_ok = False
                        print(f"    ⚠ Shortfall: {src_sz - dst_sz} bytes")
                except Exception as ve:
                    print(f"  ⚠ Could not verify partition {part_num}: {ve}")

            if not all_ok:
                raise Exception(
                    "One or more target partitions are still smaller than their source. "
                    "Check parted alignment or increase target disk size."
                )

            print("✓ Disk structure cloning complete — all target partitions >= source")
            return True

        except subprocess.CalledProcessError as e:
            print(f"ERROR in clone_disk_structure: {e}")
            raise Exception(f"Failed to clone structure: {e}")
        except FileNotFoundError:
            raise Exception("Required command not found for disk structure cloning")
        except PermissionError:
            raise Exception("Permission denied during disk structure cloning")
        except OSError as e:
            print(f"ERROR in clone_disk_structure: {e}")
            raise Exception(f"System error during disk structure cloning: {e}")
    @staticmethod
    def get_partition_size_bytes(part_device):
        """Get the TRUE size of a partition device via kernel blockdev.
        
        This is the ONLY reliable method — never use parted sizes for dd cloning,
        as parted rounds to MB boundaries and can cause I/O errors on the last partition.
        
        Args:
            part_device: e.g. '/dev/nbd0p2'
        Returns:
            int: exact partition size in bytes
        Raises:
            Exception if blockdev fails
        """
        try:
            result = subprocess.run(
                ['blockdev', '--getsize64', part_device],
                capture_output=True, text=True, check=True
            )
            size = int(result.stdout.strip())
            print(f"blockdev --getsize64 {part_device} => {QCow2CloneResizer.format_size(size)} ({size} bytes)")
            return size
        except subprocess.CalledProcessError as e:
            raise Exception(f"blockdev failed for {part_device}: {e.stderr}")
        except ValueError as e:
            raise Exception(f"Could not parse blockdev output for {part_device}: {e}")
        except FileNotFoundError:
            raise Exception("blockdev command not found — install util-linux")

    @staticmethod
    def clone_partition_data(source_nbd, target_nbd, layout_info, os_type,
                             progress_callback=None):
        """Clone actual partition DATA for Linux systems (UEFI and BIOS).
        
        Uses blockdev --getsize64 on the SOURCE partition to get the true kernel size,
        then clones with dd WITHOUT a 'count' argument so dd stops naturally at EOF.
        This prevents any I/O overrun on the last (largest) partition.
        
        Windows partitions are intentionally skipped — their cloning logic is handled
        elsewhere and must not be modified.
        
        Args:
            source_nbd: source NBD device, e.g. '/dev/nbd0'
            target_nbd: target NBD device, e.g. '/dev/nbd1'
            layout_info: dict returned by get_partition_layout()
            os_type: 'linux' | 'windows' | 'unknown'
            progress_callback: optional callable(percent, message)
        Returns:
            True on success
        Raises:
            Exception on dd failure
        """
        # ── Windows: do NOT touch — handled by a different, working workflow ──
        if os_type == 'windows':
            print("clone_partition_data: Windows detected — skipping (Windows uses its own clone logic).")
            return True

        partitions = layout_info.get('partitions', [])
        if not partitions:
            raise Exception("clone_partition_data: no partitions found in layout_info")

        print(f"\n{'='*60}")
        print(f"CLONING PARTITION DATA  ({os_type.upper()})")
        print(f"  Source : {source_nbd}")
        print(f"  Target : {target_nbd}")
        print(f"  Partitions to clone: {len(partitions)}")
        print(f"{'='*60}")

        total = len(partitions)

        for idx, partition in enumerate(partitions):
            part_num = partition['number']

            # ── Build device paths (handle both /dev/nbdXpN and /dev/nbdXN) ──
            src_device = None
            dst_device = None
            for fmt in [f"{source_nbd}p{part_num}", f"{source_nbd}{part_num}"]:
                if os.path.exists(fmt):
                    src_device = fmt
                    break
            for fmt in [f"{target_nbd}p{part_num}", f"{target_nbd}{part_num}"]:
                if os.path.exists(fmt):
                    dst_device = fmt
                    break

            if not src_device:
                raise Exception(f"Source partition device not found for partition {part_num} on {source_nbd}")
            if not dst_device:
                raise Exception(f"Target partition device not found for partition {part_num} on {target_nbd}")

            # ── Get TRUE size from kernel — never trust parted for this ──
            try:
                src_size_bytes = QCow2CloneResizer.get_partition_size_bytes(src_device)
            except Exception as e:
                raise Exception(f"Cannot get size of {src_device}: {e}")

            # ── Safety: verify target partition is at least as large ──
            try:
                dst_size_bytes = QCow2CloneResizer.get_partition_size_bytes(dst_device)
                if dst_size_bytes < src_size_bytes:
                    raise Exception(
                        f"Target partition {dst_device} ({QCow2CloneResizer.format_size(dst_size_bytes)}) "
                        f"is smaller than source {src_device} ({QCow2CloneResizer.format_size(src_size_bytes)}). "
                        f"Aborting to prevent data truncation."
                    )
            except Exception as e:
                raise Exception(f"Cannot verify target partition {dst_device}: {e}")

            if progress_callback:
                pct = 60 + int((idx / total) * 30)
                progress_callback(pct, f"Cloning partition {part_num}/{total} ({QCow2CloneResizer.format_size(src_size_bytes)})...")

            print(f"\n[Partition {part_num}/{total}]")
            print(f"  src : {src_device}  ({QCow2CloneResizer.format_size(src_size_bytes)})")
            print(f"  dst : {dst_device}  ({QCow2CloneResizer.format_size(dst_size_bytes)})")

            # ── dd WITHOUT 'count' — stops naturally at EOF, zero I/O overrun risk ──
            # conv=sync,noerror : pad incomplete blocks, continue past read errors
            # status=progress   : live throughput display
            cmd = [
                'dd',
                f'if={src_device}',
                f'of={dst_device}',
                'bs=64K',
                'conv=sync,noerror',
                'status=progress',
            ]

            print(f"  cmd : {' '.join(cmd)}")

            max_retries = 1  # No retry loop — if dd fails the root cause must be fixed, not hidden
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        check=True)
                if result.stderr:
                    print(f"  dd stderr: {result.stderr}")
                print(f"  ✓ Partition {part_num} cloned successfully")

            except subprocess.CalledProcessError as e:
                # dd exit ≠ 0  →  real I/O error
                err_detail = e.stderr if e.stderr else str(e)
                raise Exception(
                    f"dd FAILED for partition {part_num} ({src_device} → {dst_device}):\n{err_detail}"
                )
        if progress_callback:
            progress_callback(90, f"All {total} partitions cloned successfully")

        print(f"\n{'='*60}")
        print(f"✓ All {total} partition(s) cloned — {os_type.upper()} ({source_nbd} → {target_nbd})")
        print(f"{'='*60}\n")
        return True

    @staticmethod
    def create_backup(image_path):
        """Create backup of image"""
        try:
            backup_path = f"{image_path}.backup.{int(time.time())}"
            print(f"Creating backup: {image_path} -> {backup_path}")
            shutil.copy2(image_path, backup_path)
            return backup_path
        except FileNotFoundError:
            raise Exception(f"Source image not found: {image_path}")
        except PermissionError:
            raise Exception(f"Permission denied creating backup")
        except OSError as e:
            raise Exception(f"System error creating backup: {e}")
        except shutil.Error as e:
            raise Exception(f"Copy error creating backup: {e}")

    @staticmethod
    def _force_reread_partition_table(nbd_device, wait=2):
        """Force the kernel to re-read the partition table of an NBD device.

        Uses every available tool in sequence so at least one succeeds:
          1. partprobe   — asks the kernel to re-read via ioctl BLKPG
          2. blockdev --rereadpt — alternative ioctl, often works when partprobe fails
          3. kpartx -u   — device-mapper fallback (some distros)
        Then waits `wait` seconds and gives udev time to create the /dev nodes.
        """
        print(f"  Force re-reading partition table on {nbd_device}...")

        for cmd in (
            ['partprobe', nbd_device],
            ['blockdev', '--rereadpt', nbd_device],
        ):
            try:
                r = subprocess.run(cmd, capture_output=True, check=False, timeout=15)
                if r.returncode == 0:
                    print(f"    ✓ {cmd[0]} succeeded")
                else:
                    print(f"    ⚠ {cmd[0]} returned {r.returncode}: "
                          f"{(r.stderr or b'').decode(errors='replace').strip()[:80]}")
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
                print(f"    ⚠ {cmd[0]} not available: {e}")

        # kpartx as last resort
        try:
            subprocess.run(['kpartx', '-u', nbd_device],
                           capture_output=True, check=False, timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        # Give udev time to create /dev/nbdXpN nodes
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _layout_from_sfdisk(nbd_device):
        """Parse partition layout via sfdisk -J (JSON output).

        sfdisk is part of util-linux and is present on every Linux distro.
        Its JSON output is sector-precise, handles GPT/MBR equally well, and
        does NOT crash on unusual partition types (MSR, WinRE, BitLocker, etc.).

        Returns a layout dict compatible with get_partition_layout(), or None
        on failure (so the caller can fall through to the next method).
        """
        try:
            r = subprocess.run(
                ['sfdisk', '-J', nbd_device],
                capture_output=True, text=True,
                check=False, timeout=15
            )
            if r.returncode != 0 or not r.stdout.strip():
                print(f"  sfdisk -J failed (rc={r.returncode}): "
                      f"{r.stderr.strip()[:120]}")
                return None

            data = json.loads(r.stdout)
            ptable = data.get('partitiontable', {})
            sector_size = int(ptable.get('sectorsize', 512))
            raw_parts   = ptable.get('partitions', [])

            if not raw_parts:
                print("  sfdisk returned empty partition list")
                return None

            partitions   = []
            max_end_bytes = 0

            for entry in raw_parts:
                node       = entry.get('node', '')          # e.g. /dev/nbd0p1
                start_sec  = int(entry.get('start', 0))
                size_sec   = int(entry.get('size',  0))

                start_bytes = start_sec * sector_size
                end_bytes   = (start_sec + size_sec) * sector_size

                # Extract partition number from node path
                m = re.search(r'(?:p)?(\d+)$', node)
                if not m:
                    continue
                part_num = int(m.group(1))

                # Try to get the real kernel size via blockdev (more accurate)
                blockdev_bytes = None
                for fmt in (f"{nbd_device}p{part_num}", f"{nbd_device}{part_num}"):
                    if os.path.exists(fmt):
                        try:
                            bv = subprocess.run(
                                ['blockdev', '--getsize64', fmt],
                                capture_output=True, text=True,
                                check=True, timeout=10
                            )
                            blockdev_bytes = int(bv.stdout.strip())
                        except Exception:
                            pass
                        break

                partitions.append({
                    'number':            part_num,
                    'start':             f'{start_bytes}B',
                    'end':               f'{end_bytes}B',
                    'start_bytes':       start_bytes,
                    'end_bytes':         end_bytes,
                    'size':              f'{size_sec * sector_size}B',
                    'blockdev_size_bytes': blockdev_bytes,
                    'node':              node,
                    'type':              entry.get('type', ''),
                    'name':              entry.get('name', ''),
                })
                max_end_bytes = max(max_end_bytes, end_bytes)

            partitions.sort(key=lambda p: p['number'])

            if not partitions:
                print("  sfdisk: partitions parsed but list is empty")
                return None

            buffer_5pct = int(max_end_bytes * 0.05)
            required    = max_end_bytes + buffer_5pct

            print(f"  sfdisk found {len(partitions)} partition(s):")
            for p in partitions:
                name_hint = f" ({p['name']})" if p.get('name') else ''
                print(f"    Partition {p['number']}{name_hint}: "
                      f"{QCow2CloneResizer.format_size(p['start_bytes'])} → "
                      f"{QCow2CloneResizer.format_size(p['end_bytes'])}")

            print("=" * 60)
            print("Image size calculation (sfdisk):")
            print(f"  Last partition ends at: {QCow2CloneResizer.format_size(max_end_bytes)}")
            print(f"  Safety buffer (5%):     {QCow2CloneResizer.format_size(buffer_5pct)}")
            print(f"  RECOMMENDED IMAGE SIZE: {QCow2CloneResizer.format_size(required)}")
            print("=" * 60)

            return {
                'partitions':              partitions,
                'last_partition_end_bytes': max_end_bytes,
                'required_minimum_bytes':  required,
                'partition_count':         len(partitions),
            }

        except json.JSONDecodeError as e:
            print(f"  sfdisk JSON parse error: {e}")
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            print(f"  sfdisk not available: {e}")
            return None

    @staticmethod
    def _safe_parted_print(device):
        """Run parted print defensively and tolerate parted crashes."""
        try:
            result = subprocess.run(
                ['parted', '-s', device, 'print'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout
            stderr = (result.stderr or '').strip()
            stdout = (result.stdout or '').strip()
            combined = f"{stdout}\n{stderr}".strip().lower()
            if result.returncode == -6 or 'realloc(): invalid next size' in combined:
                print(f"WARNING: parted crashed on {device}; ignoring unsafe parted output")
                return None
            raise subprocess.CalledProcessError(
                result.returncode,
                ['parted', '-s', device, 'print'],
                output=result.stdout,
                stderr=result.stderr
            )
        except FileNotFoundError:
            print("WARNING: parted command not found")
            return None

    @staticmethod
    def _layout_from_lsblk(nbd_device):
        """Build a usable partition layout using lsblk when parted crashes.
        Returns None (does NOT raise) when no partitions are visible yet —
        the caller is responsible for retrying.
        """
        result = subprocess.run(
            ['lsblk', '-b', '-P', '-o', 'NAME,PATH,TYPE,START,SIZE,PARTLABEL,PARTFLAGS', nbd_device],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"  lsblk returned no output for {nbd_device}")
            return None

        partitions = []
        max_end_bytes = 0
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line or 'PATH=' not in line:
                continue
            fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
            if fields.get('TYPE') != 'part':
                continue
            path = fields.get('PATH', '')
            start_bytes = int(fields.get('START') or 0)
            size_bytes = int(fields.get('SIZE') or 0)
            end_bytes = start_bytes + size_bytes
            m = re.search(r'(?:p)?(\d+)$', path)
            if not m:
                continue
            partition_num = int(m.group(1))
            partitions.append({
                'number': partition_num,
                'start': f'{start_bytes}B',
                'end': f'{end_bytes}B',
                'start_bytes': start_bytes,
                'end_bytes': end_bytes,
                'size': f'{size_bytes}B',
                'blockdev_size_bytes': size_bytes,
                'path': path,
                'partlabel': fields.get('PARTLABEL', ''),
                'partflags': fields.get('PARTFLAGS', ''),
            })
            max_end_bytes = max(max_end_bytes, end_bytes)

        partitions.sort(key=lambda p: p['number'])
        if not partitions:
            print(f"  lsblk found 0 partitions on {nbd_device} (table not yet visible to kernel)")
            return None

        buffer_5_percent = int(max_end_bytes * 0.05)
        required_minimum_bytes = max_end_bytes + buffer_5_percent
        print("WARNING: using lsblk fallback for partition layout")
        print("=" * 60)
        print("Image size calculation (lsblk fallback):")
        print(f"  Last partition ends at: {QCow2CloneResizer.format_size(max_end_bytes)}")
        print(f"  Safety buffer (5%): {QCow2CloneResizer.format_size(buffer_5_percent)}")
        print(f"  RECOMMENDED IMAGE SIZE: {QCow2CloneResizer.format_size(required_minimum_bytes)}")
        print("=" * 60)
        return {
            'partitions': partitions,
            'last_partition_end_bytes': max_end_bytes,
            'required_minimum_bytes': required_minimum_bytes,
            'partition_count': len(partitions)
        }

    @staticmethod
    def detect_boot_mode(nbd_device):
        """Detect boot mode without relying primarily on parted."""
        try:
            result = subprocess.run(
                ['lsblk', '-P', '-o', 'NAME,PATH,PARTTYPE,FSTYPE,PARTLABEL,PARTFLAGS', nbd_device],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                for raw_line in result.stdout.splitlines():
                    line = raw_line.strip()
                    if not line or 'PATH=' not in line:
                        continue
                    fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
                    path = fields.get('PATH', '')
                    if path == nbd_device:
                        continue
                    parttype = (fields.get('PARTTYPE', '') or '').lower()
                    fstype = (fields.get('FSTYPE', '') or '').lower()
                    partlabel = (fields.get('PARTLABEL', '') or '').lower()
                    partflags = (fields.get('PARTFLAGS', '') or '').lower()
                    if parttype == 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b':
                        return 'uefi'
                    if 'esp' in partlabel or 'esp' in partflags:
                        return 'uefi'
                    if fstype in ('vfat', 'fat16', 'fat32') and ('efi' in partlabel or 'system' in partlabel):
                        return 'uefi'
                    if parttype == '21686148-6449-6e6f-744e-656564454649':
                        return 'bios'
                    if 'bios_grub' in partflags or 'bios' in partlabel:
                        return 'bios'
        except Exception as e:
            print(f"lsblk-based boot mode detection warning: {e}")
        try:
            parted_output = QCow2CloneResizer._safe_parted_print(nbd_device)
            if parted_output:
                lowered = parted_output.lower()
                if 'bios_grub' in lowered or 'bios boot' in lowered:
                    return 'bios'
                if 'partition table: gpt' in lowered:
                    return 'uefi'
                if 'partition table: msdos' in lowered:
                    return 'bios'
        except subprocess.CalledProcessError as e:
            print(f"parted fallback failed during boot detection: {e}")
        return 'unknown'

    @staticmethod
    def detect_vm_os(nbd_device):
        """Detect if VM is Linux or Windows — robust 3-phase strategy.

        Phase 1 (no mount): lsblk PARTTYPE GUID scan.
            Windows 11 always contains at least one partition with a Microsoft-
            exclusive GUID (MSR, WinRE).  Linux disks contain Linux-exclusive
            GUIDs (ext4 data, swap, LVM, RAID).  This is the fastest and most
            reliable method and works even with BitLocker, hibernation, Fast
            Startup, dirty NTFS bits.

        Phase 2 (no mount): blkid / lsblk FSTYPE scan.
            If no conclusive GUID was found, check raw filesystem signatures.
            blkid reads the superblock directly, bypassing any mount constraints.
            NTFS → Windows; ext4/xfs/btrfs/… → Linux.

        Phase 3 (mount-based fallback): Only reached when phases 1 & 2 are
            inconclusive (e.g. fresh/empty disk, unusual layout).
            Uses improved NTFS mount options (ntfs3 kernel driver with rescue,
            then ntfs-3g with force) to handle dirty/hibernated Windows volumes.

        Returns:
            'linux', 'windows', or 'unknown'
        """
        # ── Windows-exclusive GPT partition type GUIDs ───────────────────────
        _WINDOWS_GUIDS = {
            'e3c9e316-0b5c-4db8-817d-f92df00215ae',  # Microsoft Reserved (MSR)
            'de94bba4-06d1-4d40-a16a-bfd50179d6ac',  # Windows Recovery (WinRE)
            'e75caf8f-f680-4cee-afa3-b001e56efc2d',  # Storage Spaces
        }
        # ── Linux-exclusive GPT partition type GUIDs ─────────────────────────
        _LINUX_GUIDS = {
            '0fc63daf-8483-4772-8e79-3d69d8477de4',  # Linux filesystem data
            'a19d880f-05fc-4d3b-a006-743f0f84911e',  # Linux RAID
            '0657fd6d-a4ab-43c4-84e5-0933c84b4f4f',  # Linux swap
            'e6d6d379-f507-44c2-a23c-238f2a3df928',  # Linux LVM
            '933ac7e1-2eb4-4f13-b844-0e14e2aef915',  # Linux /home
            '3b8f8425-20e0-4f3b-907f-1a25a76f98e8',  # Linux /srv
            '4f68bce3-e8cd-4db1-96e7-fbcaf984b709',  # Linux x86-64 root (/)
            '69dad710-2ce4-4e3c-b16c-21a1d49abed3',  # Linux ARM root (/)
        }
        # ── Linux native filesystem types (blkid/lsblk FSTYPE column) ────────
        _LINUX_FS = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'f2fs',
                     'jfs', 'reiserfs', 'reiser4', 'nilfs2', 'ocfs2'}
        # ── Windows native filesystem types ──────────────────────────────────
        _WINDOWS_FS = {'ntfs', 'bitlocker'}

        sep = '=' * 60
        print(f"\n{sep}")
        print("DETECTING VM OPERATING SYSTEM")
        print(sep)
        print(f"NBD Device: {nbd_device}")

        # ════════════════════════════════════════════════════════════════════
        # PHASE 1 — PARTTYPE GUID scan (no mounting)
        # ════════════════════════════════════════════════════════════════════
        print("\n[Phase 1] PARTTYPE GUID scan (no mounting)...")
        try:
            lsblk_r = subprocess.run(
                ['lsblk', '-P', '-o',
                 'PATH,TYPE,PARTTYPE,FSTYPE,LABEL,PARTLABEL', nbd_device],
                capture_output=True, text=True, check=False, timeout=15
            )
            if lsblk_r.returncode == 0 and lsblk_r.stdout.strip():
                win_guid_score = 0
                lin_guid_score = 0
                ntfs_count     = 0
                linux_fs_count = 0

                for raw in lsblk_r.stdout.splitlines():
                    fields = dict(re.findall(r'(\w+)="([^"]*)"', raw))
                    if fields.get('TYPE') != 'part':
                        continue

                    parttype  = (fields.get('PARTTYPE')  or '').lower().strip('{}')
                    fstype    = (fields.get('FSTYPE')    or '').lower()
                    label     = (fields.get('LABEL')     or '').lower()
                    partlabel = (fields.get('PARTLABEL') or '').lower()

                    if parttype in _WINDOWS_GUIDS:
                        win_guid_score += 2          # strong signal
                        print(f"  → Windows GUID: {parttype} ({partlabel})")
                    if parttype in _LINUX_GUIDS:
                        lin_guid_score += 2
                        print(f"  → Linux GUID: {parttype}")

                    # EBD0A0A2 = Microsoft Basic Data — also used by Linux FAT,
                    # so only count it when combined with NTFS fstype.
                    if (parttype == 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'
                            and fstype in _WINDOWS_FS):
                        win_guid_score += 1

                    if fstype in _WINDOWS_FS:
                        ntfs_count += 1
                    if fstype in _LINUX_FS:
                        linux_fs_count += 1

                    # Partition label heuristics (lower weight)
                    win_labels = ('microsoft', 'windows', 'winre', 'recovery',
                                  'system reserved', 'basic data')
                    lin_labels = ('linux', 'swap', 'root', 'home', 'boot', 'lvm')
                    if any(x in partlabel for x in win_labels):
                        win_guid_score += 1
                    if any(x in partlabel for x in lin_labels):
                        lin_guid_score += 1

                print(f"  Scores — Windows: {win_guid_score}, Linux: {lin_guid_score}, "
                      f"NTFS: {ntfs_count}, LinuxFS: {linux_fs_count}")

                # ── Decision rules ──────────────────────────────────────────
                # 1. Exclusive GUID → definitive answer
                if win_guid_score >= 2 and lin_guid_score == 0:
                    print(f"\n✓ DETECTED (Phase 1): Windows (score={win_guid_score})")
                    print(f"{sep}\n")
                    return 'windows'
                if lin_guid_score >= 2 and win_guid_score == 0:
                    print(f"\n✓ DETECTED (Phase 1): Linux (score={lin_guid_score})")
                    print(f"{sep}\n")
                    return 'linux'

                # 2. Filesystem type when no exclusive GUID
                if ntfs_count > 0 and linux_fs_count == 0 and lin_guid_score == 0:
                    print(f"\n✓ DETECTED (Phase 1): Windows ({ntfs_count}× NTFS, no Linux fs)")
                    print(f"{sep}\n")
                    return 'windows'
                if linux_fs_count > 0 and ntfs_count == 0 and win_guid_score == 0:
                    print(f"\n✓ DETECTED (Phase 1): Linux ({linux_fs_count} Linux filesystems)")
                    print(f"{sep}\n")
                    return 'linux'
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            print(f"  ⚠ Phase 1 lsblk error: {e}")

        # ════════════════════════════════════════════════════════════════════
        # PHASE 2 — blkid raw superblock probe (no mounting)
        # Reads filesystem signatures directly from the block device.
        # Works on NTFS with dirty bit, hibernation, BitLocker containers.
        # ════════════════════════════════════════════════════════════════════
        print("\n[Phase 2] blkid superblock probe (no mounting)...")
        ntfs_hits    = 0
        linux_hits   = 0
        efi_ms_found = False

        partitions = []
        for i in range(1, 16):
            for fmt in (f"{nbd_device}p{i}", f"{nbd_device}{i}"):
                if os.path.exists(fmt):
                    partitions.append((i, fmt))
                    break

        print(f"  Partitions found: {[p[1] for p in partitions]}")

        for part_num, part_dev in partitions:
            try:
                blk = subprocess.run(
                    ['blkid', '-o', 'export', part_dev],
                    capture_output=True, text=True,
                    check=False, timeout=10
                )
                fields = {}
                for line in blk.stdout.splitlines():
                    if '=' in line:
                        k, _, v = line.partition('=')
                        fields[k.strip()] = v.strip()

                fs   = fields.get('TYPE',  '').lower()
                lbl  = fields.get('LABEL', '').lower()
                plbl = fields.get('PARTLABEL', '').lower()

                print(f"  Part {part_num}: TYPE={fs!r} LABEL={lbl!r} PARTLABEL={plbl!r}")

                if fs in _WINDOWS_FS:
                    ntfs_hits += 1
                if fs in _LINUX_FS:
                    linux_hits += 1

                # EFI partition — check if it contains Microsoft boot files
                if fs in ('vfat', 'fat16', 'fat32'):
                    efi_win_labels = ('efi system', 'system', 'esp')
                    if any(x in plbl for x in efi_win_labels) or any(
                            x in lbl for x in efi_win_labels):
                        # Quick check: is there an EFI/Microsoft folder?
                        with tempfile.TemporaryDirectory() as mnt:
                            r = subprocess.run(
                                ['mount', '-t', 'vfat', '-o', 'ro', part_dev, mnt],
                                capture_output=True, check=False, timeout=10
                            )
                            if r.returncode == 0:
                                try:
                                    efi_dir = os.path.join(mnt, 'EFI')
                                    if os.path.isdir(efi_dir):
                                        contents = os.listdir(efi_dir)
                                        # Case-insensitive check for Microsoft folder
                                        if any(x.lower() == 'microsoft' for x in contents):
                                            efi_ms_found = True
                                            print(f"    → EFI/Microsoft found on part {part_num}")
                                finally:
                                    subprocess.run(['umount', mnt],
                                                   check=False, timeout=10)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                print(f"  ⚠ blkid error on {part_dev}: {e}")

        print(f"  blkid scores — NTFS: {ntfs_hits}, Linux FS: {linux_hits}, "
              f"EFI/Microsoft: {efi_ms_found}")

        if efi_ms_found or (ntfs_hits > 0 and linux_hits == 0):
            print(f"\n✓ DETECTED (Phase 2): Windows")
            print(f"{sep}\n")
            return 'windows'
        if linux_hits > 0 and ntfs_hits == 0 and not efi_ms_found:
            print(f"\n✓ DETECTED (Phase 2): Linux")
            print(f"{sep}\n")
            return 'linux'

        # ════════════════════════════════════════════════════════════════════
        # PHASE 3 — Mount-based filesystem content scan (fallback)
        # Uses improved NTFS mount options to handle dirty/hibernated volumes.
        # ════════════════════════════════════════════════════════════════════
        print("\n[Phase 3] Mount-based filesystem content scan (fallback)...")

        def _try_mount_ntfs(device, mount_point):
            """Try multiple NTFS drivers/options; return (success, driver_used)."""
            # ntfs3 kernel driver (Linux ≥ 5.15) — handles dirty bit natively
            for opts in ('ro,rescue', 'ro'):
                r = subprocess.run(
                    ['mount', '-t', 'ntfs3', '-o', opts, device, mount_point],
                    capture_output=True, check=False, timeout=15
                )
                if r.returncode == 0:
                    return True, f'ntfs3 -{opts}'

            # ntfs-3g FUSE driver — use force to bypass dirty-bit refusal
            for opts in ('ro,ignore_case,remove_hiberfile',
                         'ro,force',
                         'ro'):
                r = subprocess.run(
                    ['mount', '-t', 'ntfs-3g', '-o', opts, device, mount_point],
                    capture_output=True, check=False, timeout=15
                )
                if r.returncode == 0:
                    return True, f'ntfs-3g -{opts}'

            # Generic auto (may pick ntfs3 or ntfs-3g depending on distro)
            r = subprocess.run(
                ['mount', '-t', 'ntfs', '-o', 'ro', device, mount_point],
                capture_output=True, check=False, timeout=15
            )
            if r.returncode == 0:
                return True, 'ntfs-generic'
            return False, None

        _WINDOWS_PATHS = [
            'Windows', 'WINDOWS', 'windows',
            'Program Files', 'Program Files (x86)', 'ProgramData',
            'Users', 'System Volume Information',
            'bootmgr', 'BOOTMGR', 'pagefile.sys', 'hiberfil.sys',
            'Boot',
        ]
        _LINUX_PATHS = [
            ('etc/fstab',          'fstab'),
            ('etc/passwd',         'passwd'),
            ('etc/hostname',       'hostname'),
            ('etc/os-release',     'os-release'),
            ('bin/bash',           'bash'),
            ('usr/bin',            'usr/bin'),
            ('var/log',            'var/log'),
            ('etc/debian_version', 'debian_version'),
            ('etc/redhat-release', 'redhat-release'),
        ]

        for part_num, part_dev in partitions:
            print(f"\n  Checking partition {part_num}: {part_dev}")

            # Determine which filesystem to try first
            try:
                blk = subprocess.run(
                    ['blkid', '-o', 'value', '-s', 'TYPE', part_dev],
                    capture_output=True, text=True, check=False, timeout=8
                )
                detected_fs = blk.stdout.strip().lower()
            except Exception:
                detected_fs = ''

            if detected_fs in ('swap',):
                print(f"    → Swap partition, skipping")
                continue

            with tempfile.TemporaryDirectory() as mnt:
                mount_success = False
                used_driver   = None

                # Priority: detected FS first, then generic fallback list
                if detected_fs in ('ntfs', 'bitlocker'):
                    mount_success, used_driver = _try_mount_ntfs(part_dev, mnt)
                elif detected_fs in _LINUX_FS:
                    r = subprocess.run(
                        ['mount', '-t', detected_fs, '-o', 'ro', part_dev, mnt],
                        capture_output=True, check=False, timeout=15
                    )
                    if r.returncode == 0:
                        mount_success, used_driver = True, detected_fs
                elif detected_fs in ('vfat', 'fat16', 'fat32'):
                    r = subprocess.run(
                        ['mount', '-t', 'vfat', '-o', 'ro', part_dev, mnt],
                        capture_output=True, check=False, timeout=10
                    )
                    if r.returncode == 0:
                        mount_success, used_driver = True, 'vfat'

                # Generic fallback when blkid was inconclusive
                if not mount_success:
                    for fs in ('auto', 'ext4', 'ext3', 'btrfs', 'xfs', 'vfat'):
                        r = subprocess.run(
                            ['mount', '-t', fs, '-o', 'ro', part_dev, mnt],
                            capture_output=True, check=False, timeout=15
                        )
                        if r.returncode == 0:
                            mount_success, used_driver = True, fs
                            break

                    # NTFS last resort with all options
                    if not mount_success:
                        mount_success, used_driver = _try_mount_ntfs(part_dev, mnt)

                if not mount_success:
                    print(f"    ⚠ Could not mount partition {part_num} with any driver")
                    continue

                print(f"    Mounted with: {used_driver}")
                try:
                    contents = os.listdir(mnt)[:20]
                    print(f"    Contents: {contents}")
                except OSError:
                    contents = []

                try:
                    # ── Windows content check ────────────────────────────
                    win_found = [x for x in _WINDOWS_PATHS
                                 if os.path.exists(os.path.join(mnt, x))]
                    if win_found:
                        subprocess.run(['umount', mnt], check=False, timeout=10)
                        print(f"\n✓ DETECTED (Phase 3): Windows "
                              f"(found: {win_found[:3]})")
                        print(f"{sep}\n")
                        return 'windows'

                    # ── EFI/Microsoft check ──────────────────────────────
                    efi_dir = os.path.join(mnt, 'EFI')
                    if os.path.isdir(efi_dir):
                        try:
                            efi_contents_lower = [x.lower()
                                                  for x in os.listdir(efi_dir)]
                            if 'microsoft' in efi_contents_lower:
                                subprocess.run(['umount', mnt],
                                               check=False, timeout=10)
                                print(f"\n✓ DETECTED (Phase 3): Windows (EFI/Microsoft)")
                                print(f"{sep}\n")
                                return 'windows'
                        except OSError:
                            pass

                    # ── Linux content check ──────────────────────────────
                    lin_found = [(d, n) for d, n in _LINUX_PATHS
                                 if os.path.exists(os.path.join(mnt, d))]
                    if lin_found:
                        subprocess.run(['umount', mnt], check=False, timeout=10)
                        print(f"\n✓ DETECTED (Phase 3): Linux "
                              f"({', '.join(n for _, n in lin_found[:3])})")
                        print(f"{sep}\n")
                        return 'linux'

                    # ── /boot or /grub ───────────────────────────────────
                    for dname in ('boot', 'grub'):
                        if os.path.isdir(os.path.join(mnt, dname)):
                            subprocess.run(['umount', mnt],
                                           check=False, timeout=10)
                            print(f"\n✓ DETECTED (Phase 3): Linux (/{dname} found)")
                            print(f"{sep}\n")
                            return 'linux'
                finally:
                    subprocess.run(['umount', mnt], check=False, timeout=10)

        print(f"\n✗ DETECTED: Unknown (all 3 phases inconclusive)")
        print(f"{sep}\n")
        return 'unknown'

    @staticmethod
    def _detect_vm_os_safe(nbd_device):
        """Public wrapper around detect_vm_os that always returns a string."""
        try:
            return QCow2CloneResizer.detect_vm_os(nbd_device)
        except Exception as e:
            print(f"detect_vm_os unexpected error: {type(e).__name__}: {e}")
            return 'unknown'