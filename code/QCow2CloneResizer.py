import tkinter as tk
import os
import subprocess

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
            'qemu-nbd': 'qemu-utils',
            'parted': 'parted',
            'gparted': 'gparted',
            'dd': 'coreutils',
            'partclone.ext4': 'partclone',  # optional for smart cloning
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
    def compress_qcow2_image(image_path, progress_callback=None, delete_original_source=None):
        """Compress QCOW2 image - DOES NOT replace in place, just compresses to temp file
        
        Args:
            image_path: Path to the image to compress  
            progress_callback: Optional progress callback function
            delete_original_source: NOT USED - kept for compatibility
        """
        try:
            if progress_callback:
                progress_callback(92, "Compressing image for optimal storage...")
            
            print(f"Starting compression of: {image_path}")
            
            # Get original image info
            original_info = QCow2CloneResizer.get_image_info(image_path)
            original_file_size = os.path.getsize(image_path)
            
            print(f"Original image stats:")
            print(f"  Virtual size: {QCow2CloneResizer.format_size(original_info['virtual_size'])}")
            print(f"  File size: {QCow2CloneResizer.format_size(original_file_size)}")
            print(f"  Current compression: {original_info.get('compressed', False)}")
            
            # Create temporary compressed version
            temp_compressed_path = f"{image_path}.compressed.tmp"
            
            # Remove temp file if it exists
            if os.path.exists(temp_compressed_path):
                os.remove(temp_compressed_path)
            
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
            
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, check=True, 
                timeout=1800  # 30 minutes for compression
            )
            
            if result.stdout:
                print(f"Compression stdout: {result.stdout}")
            if result.stderr:
                print(f"Compression stderr: {result.stderr}")
            
            # Verify compressed image was created
            if not os.path.exists(temp_compressed_path):
                raise Exception(f"Compressed image was not created: {temp_compressed_path}")
            
            # Get compressed image stats
            compressed_info = QCow2CloneResizer.get_image_info(temp_compressed_path)
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
            
            # Check if compression is worth it (more than 1MB savings)
            min_savings = 1024 * 1024  # 1MB minimum savings
            if compressed_file_size >= (original_file_size - min_savings):
                print(f"WARNING: Compression saved less than 1MB")
                print(f"Keeping original and removing compressed temp file")
                os.remove(temp_compressed_path)
                return {
                    'original_size': original_file_size,
                    'compressed_size': original_file_size,
                    'space_saved': 0,
                    'compression_ratio': 0.0,
                }
            
            # CRITICAL CHANGE: Replace original IN PLACE instead of keeping temp file
            print(f"Replacing original with compressed version...")
            os.remove(image_path)
            os.rename(temp_compressed_path, image_path)
            
            print(f"Image compression completed and replaced in place")
            
            if progress_callback:
                progress_callback(98, f"Image compressed - saved {compression_ratio:.1f}% space")
            
            return {
                'original_size': original_file_size,
                'compressed_size': compressed_file_size,
                'space_saved': original_file_size - compressed_file_size,
                'compression_ratio': compression_ratio,
            }
            
        except Exception as e:
            # Clean up temp file on error
            temp_compressed_path = f"{image_path}.compressed.tmp"
            if os.path.exists(temp_compressed_path):
                try:
                    os.remove(temp_compressed_path)
                except:
                    pass
            print(f"ERROR during compression: {e}")
            raise
    
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
            result = subprocess.run(
                ['qemu-img', 'info', '--output=json', image_path],
                capture_output=True, text=True, check=True, timeout=30
            )
            data = json.loads(result.stdout)
            
            return {
                'virtual_size': data.get('virtual-size', 0),
                'actual_size': data.get('actual-size', 0),
                'format': data.get('format', 'unknown'),
                'compressed': data.get('compressed', False)
            }
        except subprocess.CalledProcessError as e:
            raise Exception(f"qemu-img failed to analyze image: {e}")
        except subprocess.TimeoutExpired:
            raise Exception(f"qemu-img timed out while analyzing image: {image_path}")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse qemu-img JSON output: {e}")
        except FileNotFoundError:
            raise Exception(f"Image file not found: {image_path}")
        except PermissionError:
            raise Exception(f"Permission denied accessing image: {image_path}")
    
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
                        capture_output=True, text=True, timeout=3, check=False
                    )
                    # If --list succeeds, device is connected/busy
                    if list_result.returncode == 0:
                        print(f"Device {device} is connected (qemu-nbd --list succeeded)")
                        device_available = False
                    
                except subprocess.TimeoutExpired:
                    print(f"Device {device} check timed out, assuming busy")
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
                        capture_output=True, text=True, timeout=3, check=False
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
                        capture_output=True, text=True, timeout=3, check=False
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
                                        capture_output=True, timeout=5, check=False)
                        except subprocess.TimeoutExpired:
                            print(f"Timeout while disconnecting {device}")
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
                    capture_output=True, text=True, check=True, timeout=30
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
                                        capture_output=True, timeout=5, check=False)
                            time.sleep(1)
                            # Try to connect
                            subprocess.run(['qemu-nbd', '--connect', alt_device, image_path],
                                        capture_output=True, text=True, check=True, timeout=30)
                            nbd_device = alt_device
                            print(f"Successfully connected to {alt_device}")
                            break
                        except subprocess.CalledProcessError as alt_e:
                            print(f"Alternative device {alt_device} connection failed: {alt_e}")
                            continue
                        except subprocess.TimeoutExpired:
                            print(f"Alternative device {alt_device} connection timed out")
                            continue
                        except FileNotFoundError:
                            print(f"qemu-nbd not found for alternative device {alt_device}")
                            continue
                else:
                    raise Exception(f"Could not connect to any NBD device. Last error: {error_details}")
            except subprocess.TimeoutExpired:
                raise Exception(f"NBD connection timed out for device {nbd_device}")
            except FileNotFoundError:
                raise Exception("qemu-nbd command not found")
            
            # Wait for device to be ready
            print(f"Waiting for {nbd_device} to be ready...")
            max_attempts = 20
            for attempt in range(max_attempts):
                time.sleep(1)
                
                # Force kernel to re-read partition table
                subprocess.run(['partprobe', nbd_device], check=False, 
                            capture_output=True, timeout=10)
                time.sleep(1)
                
                # Check if device is accessible
                try:
                    result = subprocess.run(['lsblk', nbd_device], 
                                        capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        print(f"NBD device {nbd_device} is ready after {attempt + 1} attempts")
                        if result.stdout.strip():
                            print(f"Device info:\n{result.stdout}")
                        break
                except subprocess.TimeoutExpired:
                    print(f"Attempt {attempt + 1}: Device check timed out")
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
                                        capture_output=True, text=True, 
                                        timeout=10, check=True)
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
                except subprocess.TimeoutExpired:
                    print(f"Disconnect attempt {attempt + 1} timed out")
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
                                check=False, timeout=10)
                    time.sleep(2)
                except subprocess.TimeoutExpired:
                    print("pkill command timed out")
                except FileNotFoundError:
                    print("pkill command not found")
                except subprocess.SubprocessError as e:
                    print(f"pkill subprocess error: {e}")
            
            # Final verification
            time.sleep(2)
            try:
                result = subprocess.run(['lsblk', nbd_device],
                                    capture_output=True, text=True, timeout=5)
                if result.returncode != 0 or not result.stdout.strip():
                    print(f"NBD device {nbd_device} appears to be disconnected")
                else:
                    print(f"Warning: {nbd_device} may still be connected")
            except subprocess.TimeoutExpired:
                print(f"NBD device {nbd_device} disconnect verification timed out")
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
                                    capture_output=True, text=True, timeout=3, check=False)
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
                                    capture_output=True, text=True, timeout=3, check=False)
                if result.returncode == 0:
                    return False
            except subprocess.TimeoutExpired:
                print(f"qemu-nbd list timed out for {device_path}")
            except FileNotFoundError:
                print(f"qemu-nbd command not found for {device_path}")
            except subprocess.SubprocessError as e:
                print(f"qemu-nbd list subprocess error for {device_path}: {e}")
            
            # 3. Does lsblk show partitions?
            try:
                result = subprocess.run(['lsblk', '-n', device_path],
                                    capture_output=True, text=True, timeout=3, check=False)
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
        """Get partition layout information after GParted operations"""
        try:
            # Use parted to get detailed info
            result = subprocess.run(
                ['parted', '-s', nbd_device, 'print'],
                capture_output=True, text=True, check=True, timeout=30
            )
            
            print(f"Parted output for {nbd_device}:")
            print(result.stdout)
            print("=" * 50)
            
            lines = result.stdout.split('\n')
            partitions = []
            all_end_values = []
            
            for line in lines:
                line = line.strip()
                if re.match(r'^\s*\d+\s+', line):  # Partition line
                    parts = line.split()
                    print(f"DEBUG: Parsing line: '{line}'")
                    print(f"DEBUG: Split into parts: {parts}")
                    
                    if len(parts) >= 3:
                        partition_num = int(parts[0])
                        start_str = parts[1]
                        end_str = parts[2]
                        
                        print(f"DEBUG: Partition {partition_num} - start:'{start_str}' end:'{end_str}'")
                        
                        # Support both European (comma) and US (dot) decimal separators
                        end_bytes = 0
                        
                        # Method 1: Look for GB values (support both 47.5GB and 47,5GB)
                        gb_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*GB', end_str, re.IGNORECASE)
                        if gb_match:
                            gb_value_str = gb_match.group(1).replace(',', '.')  # Convert European to US format
                            gb_value = float(gb_value_str)
                            end_bytes = int(gb_value * 1024**3)
                            print(f"DEBUG: Found GB value: {gb_value_str}GB = {end_bytes} bytes")
                        else:
                            # Method 2: Look for MB values
                            mb_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*MB', end_str, re.IGNORECASE)
                            if mb_match:
                                mb_value_str = mb_match.group(1).replace(',', '.')
                                mb_value = float(mb_value_str)
                                end_bytes = int(mb_value * 1024**2)
                                print(f"DEBUG: Found MB value: {mb_value_str}MB = {end_bytes} bytes")
                            else:
                                # Method 3: Look for kB values
                                kb_match = re.search(r'(\d+(?:[,\.]\d+)?)\s*kB', end_str, re.IGNORECASE)
                                if kb_match:
                                    kb_value_str = kb_match.group(1).replace(',', '.')
                                    kb_value = float(kb_value_str)
                                    end_bytes = int(kb_value * 1024)
                                    print(f"DEBUG: Found kB value: {kb_value_str}kB = {end_bytes} bytes")
                                else:
                                    print(f"DEBUG: Could not parse end value '{end_str}'")
                                    continue
                        
                        all_end_values.append({
                            'partition': partition_num,
                            'end_str': end_str,
                            'end_bytes': end_bytes,
                            'end_formatted': QCow2CloneResizer.format_size(end_bytes)
                        })
                        
                        # Parse start too (with same European format support)
                        start_bytes = 0
                        gb_start = re.search(r'(\d+(?:[,\.]\d+)?)\s*GB', start_str, re.IGNORECASE)
                        if gb_start:
                            start_bytes = int(float(gb_start.group(1).replace(',', '.')) * 1024**3)
                        else:
                            mb_start = re.search(r'(\d+(?:[,\.]\d+)?)\s*MB', start_str, re.IGNORECASE)
                            if mb_start:
                                start_bytes = int(float(mb_start.group(1).replace(',', '.')) * 1024**2)
                            else:
                                kb_start = re.search(r'(\d+(?:[,\.]\d+)?)\s*kB', start_str, re.IGNORECASE)
                                if kb_start:
                                    start_bytes = int(float(kb_start.group(1).replace(',', '.')) * 1024)
                        
                        partitions.append({
                            'number': partition_num,
                            'start': start_str,
                            'end': end_str,
                            'start_bytes': start_bytes,
                            'end_bytes': end_bytes,
                            'size': parts[3] if len(parts) > 3 else 'unknown',
                            'filesystem': parts[4] if len(parts) > 4 else 'unknown'
                        })
            
            print("\nDEBUG: All end values found:")
            for item in all_end_values:
                print(f"  Partition {item['partition']}: '{item['end_str']}' = {item['end_bytes']} bytes = {item['end_formatted']}")
            
            # Find the maximum end value
            if all_end_values:
                max_end_bytes = max(item['end_bytes'] for item in all_end_values)
                max_partition = max(all_end_values, key=lambda x: x['end_bytes'])
                
                print(f"\nDEBUG: Maximum end value:")
                print(f"  Partition {max_partition['partition']}: {max_partition['end_formatted']} ({max_end_bytes} bytes)")
            else:
                max_end_bytes = 0
                print("\nDEBUG: No partition end values found!")
            
            # Add 200MB buffer
            buffer_size = 200 * 1024 * 1024  # 200MB
            required_minimum_bytes = max_end_bytes + buffer_size
            
            print(f"\nDEBUG: Final calculation:")
            print(f"  Maximum partition end: {QCow2CloneResizer.format_size(max_end_bytes)}")
            print(f"  Buffer: {QCow2CloneResizer.format_size(buffer_size)}")
            print(f"  Required minimum: {QCow2CloneResizer.format_size(required_minimum_bytes)}")
            
            return {
                'partitions': partitions,
                'last_partition_end_bytes': max_end_bytes,
                'required_minimum_bytes': required_minimum_bytes,
                'partition_count': len(partitions)
            }
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"parted command failed: {e}")
        except subprocess.TimeoutExpired:
            raise Exception(f"parted command timed out for device {nbd_device}")
        except FileNotFoundError:
            raise Exception("parted command not found")
        except ValueError as e:
            raise Exception(f"Failed to parse partition information: {e}")
        except IndexError as e:
            raise Exception(f"Unexpected parted output format: {e}")
    
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
                            subprocess.run(cmd, env=env, timeout=3600)
                            return True
                        except subprocess.TimeoutExpired:
                            raise Exception("GParted operation timed out (1 hour limit)")
                        except subprocess.CalledProcessError as e:
                            print(f"Failed with {cmd[0]}: return code {e.returncode}")
                            continue
                        except FileNotFoundError:
                            print(f"Command {cmd[0]} not found")
                            continue
                
                print("Warning: No privilege escalation found, trying direct launch")
            
            # Direct launch
            subprocess.run(['gparted', nbd_device], env=env, timeout=3600)
            return True
            
        except subprocess.TimeoutExpired:
            raise Exception("GParted operation timed out (1 hour limit)")
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
                '-o', 'preallocation=metadata',  # FIXED: Added preallocation=metadata
                target_path, 
                str(size_bytes)
            ]
            
            print(f"Creating new image: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, check=True, timeout=600  # Increased timeout for large images
            )
            
            if result.stdout:
                print(f"qemu-img output: {result.stdout}")
            if result.stderr:
                print(f"qemu-img stderr: {result.stderr}")
            
            # Verify the image was created successfully
            if not os.path.exists(target_path):
                raise Exception(f"Image file was not created: {target_path}")
            
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
        except subprocess.TimeoutExpired:
            raise Exception("Image creation timed out (10 minutes)")
        except FileNotFoundError:
            raise Exception("qemu-img command not found")
        except PermissionError:
            raise Exception(f"Permission denied creating image: {target_path}")
        except OSError as e:
            print(f"ERROR creating image: {e}")
            raise Exception(f"Failed to create image: {e}")
    
    @staticmethod
    def clone_disk_structure(source_nbd, target_nbd, layout_info, progress_callback=None):
        """Clone disk structure (partition table + partitions)"""
        try:
            if progress_callback:
                progress_callback(40, "Cloning partition table...")
            
            print(f"Cloning disk structure from {source_nbd} to {target_nbd}")
            
            # Step 1: Copy partition table and MBR/GPT
            cmd = [
                'dd', 
                f'if={source_nbd}',
                f'of={target_nbd}',
                'bs=1M',
                'count=1',  # First MB for MBR/GPT
                'conv=notrunc'
            ]
            
            print(f"Copying structure: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
            if result.stderr:
                print(f"DD stderr: {result.stderr}")
            
            if progress_callback:
                progress_callback(50, "Recreating partition table...")
            
            # Step 2: Recreate partitions with parted
            parted_result = subprocess.run(
                ['parted', '-s', source_nbd, 'print'],
                capture_output=True, text=True, check=True
            )
            
            # Detect table type (msdos or gpt)
            table_type = 'msdos'  # default
            for line in parted_result.stdout.split('\n'):
                if 'Partition Table:' in line:
                    table_type = line.split(':')[1].strip()
                    break
            
            print(f"Detected partition table type: {table_type}")
            
            # Create partition table on new image
            subprocess.run([
                'parted', '-s', target_nbd, 'mklabel', table_type
            ], check=True)
            
            # Recreate each partition
            for i, partition in enumerate(layout_info['partitions']):
                if progress_callback:
                    progress_callback(55 + i * 5, f"Recreating partition {partition['number']}...")
                
                print(f"Creating partition {partition['number']}: {partition['start']} - {partition['end']}")
                
                # Create partition
                result = subprocess.run([
                    'parted', '-s', target_nbd, 
                    'mkpart', 'primary',
                    partition['start'], partition['end']
                ], capture_output=True, text=True, check=True)
                
                if result.stderr:
                    print(f"Parted stderr for partition {partition['number']}: {result.stderr}")
            
            # Wait for partitions to be available
            print("Waiting for partitions to be available...")
            time.sleep(3)
            subprocess.run(['partprobe', target_nbd], check=False)
            time.sleep(2)
            
            # Verify partitions were created
            verify_result = subprocess.run(['lsblk', target_nbd], 
                                         capture_output=True, text=True, timeout=10)
            print(f"New partition layout:\n{verify_result.stdout}")
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"ERROR in clone_disk_structure: {e}")
            raise Exception(f"Failed to clone structure: {e}")
        except subprocess.TimeoutExpired:
            raise Exception("Disk structure cloning timed out")
        except FileNotFoundError:
            raise Exception("Required command not found for disk structure cloning")
        except PermissionError:
            raise Exception("Permission denied during disk structure cloning")
        except OSError as e:
            print(f"ERROR in clone_disk_structure: {e}")
            raise Exception(f"System error during disk structure cloning: {e}")
    
    
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

