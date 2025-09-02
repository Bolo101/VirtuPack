#!/usr/bin/env python3
"""
QCOW2 Virtual Disk Resizer - Enhanced Implementation with Filesystem Support
Handles resizing of QCOW2 virtual machine disk images and their filesystems
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import json
import shutil
import time
import re
import sys
from pathlib import Path
import tempfile

class QCow2Resizer:
    """Core QCOW2 resize functionality with filesystem support"""
    
    @staticmethod
    def check_tools():
        """Check if required tools are available"""
        essential_tools = {
            'qemu-img': 'qemu-utils',
            'qemu-nbd': 'qemu-utils',
            'parted': 'parted',
        }
        
        # Optional tools for specific filesystems
        optional_tools = {
            'resize2fs': 'e2fsprogs (for ext2/3/4)',
            'e2fsck': 'e2fsprogs (for ext2/3/4)',
            'ntfsresize': 'ntfs-3g (for NTFS/Windows)',
            'ntfsfix': 'ntfs-3g (for NTFS/Windows)',
            'gparted': 'gparted (GUI alternative)',
        }
        
        missing = []
        for tool, package in essential_tools.items():
            if not shutil.which(tool):
                missing.append(f"{tool} ({package}) - REQUIRED")
        
        optional_missing = []
        for tool, package in optional_tools.items():
            if not shutil.which(tool):
                optional_missing.append(f"{tool} ({package}) - OPTIONAL")
        
        return missing, optional_missing
    
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
        except Exception as e:
            raise Exception(f"Failed to analyze image: {e}")
    
    @staticmethod
    def get_filesystem_type(partition_device):
        """Detect filesystem type of partition"""
        try:
            # Method 1: Try blkid first (most reliable for mounted/unmounted filesystems)
            if shutil.which('blkid'):
                try:
                    result = subprocess.run(
                        ['blkid', '-o', 'value', '-s', 'TYPE', partition_device],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        fs_type = result.stdout.strip().lower()
                        # Normalize some filesystem names
                        if fs_type == 'vfat':
                            return 'fat32'
                        elif fs_type == 'msdos':
                            return 'fat32'
                        elif fs_type.startswith('ext'):
                            return fs_type
                        elif fs_type == 'ntfs':
                            return 'ntfs'
                        elif fs_type in ['xfs', 'btrfs', 'reiserfs', 'jfs', 'hfs', 'hfsplus']:
                            return fs_type
                        else:
                            return fs_type
                except subprocess.TimeoutExpired:
                    pass
                except Exception:
                    pass
            
            # Method 2: Try file command for filesystem detection
            if shutil.which('file'):
                try:
                    result = subprocess.run(
                        ['file', '-s', partition_device],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        output = result.stdout.lower()
                        if 'ntfs' in output:
                            return 'ntfs'
                        elif 'ext4' in output:
                            return 'ext4'
                        elif 'ext3' in output:
                            return 'ext3'
                        elif 'ext2' in output:
                            return 'ext2'
                        elif 'fat' in output or 'vfat' in output:
                            return 'fat32'
                        elif 'xfs' in output:
                            return 'xfs'
                        elif 'btrfs' in output:
                            return 'btrfs'
                        elif 'reiserfs' in output:
                            return 'reiserfs'
                        elif 'hfs' in output:
                            return 'hfs'
                except subprocess.TimeoutExpired:
                    pass
                except Exception:
                    pass
            
            # Method 3: Parse parted output for filesystem info
            try:
                # Extract the base device (remove partition number)
                if 'p' in partition_device:
                    base_device = partition_device.rsplit('p', 1)[0]
                    partition_num = partition_device.rsplit('p', 1)[1]
                else:
                    # Handle cases like /dev/sda1 vs /dev/nbd0p1
                    import re
                    match = re.match(r'(.+?)(\d+)$', partition_device)
                    if match:
                        base_device = match.group(1)
                        partition_num = match.group(2)
                    else:
                        base_device = partition_device
                        partition_num = '1'
                
                result = subprocess.run(
                    ['parted', '-s', base_device, 'print'],
                    capture_output=True, text=True, timeout=15
                )
                
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        line = line.strip()
                        # Look for partition lines that start with a number
                        if re.match(r'^\s*' + re.escape(partition_num) + r'\s+', line):
                            parts = line.split()
                            if len(parts) >= 5:
                                # Filesystem type is usually in position 4 or 5
                                for part in parts[4:]:
                                    part_lower = part.lower()
                                    if part_lower in ['ntfs', 'fat32', 'fat', 'vfat']:
                                        return 'ntfs' if part_lower == 'ntfs' else 'fat32'
                                    elif part_lower.startswith('ext'):
                                        if 'ext4' in part_lower:
                                            return 'ext4'
                                        elif 'ext3' in part_lower:
                                            return 'ext3'
                                        elif 'ext2' in part_lower:
                                            return 'ext2'
                                        else:
                                            return 'ext4'  # Default to ext4
                                    elif part_lower in ['xfs', 'btrfs', 'reiserfs', 'jfs']:
                                        return part_lower
                                    elif 'hfs' in part_lower:
                                        return 'hfs'
                            break
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            
            # Method 4: Try fsck to detect filesystem (read-only check)
            filesystem_checkers = [
                ('ntfs', ['ntfsfix', '-n']),  # -n for no changes
                ('ext4', ['e2fsck', '-n']),   # -n for no changes
                ('ext3', ['e2fsck', '-n']),
                ('ext2', ['e2fsck', '-n']),
                ('xfs', ['xfs_check']),
            ]
            
            for fs_type, cmd in filesystem_checkers:
                if shutil.which(cmd[0]):
                    try:
                        result = subprocess.run(
                            cmd + [partition_device],
                            capture_output=True, text=True, timeout=15
                        )
                        # If the command succeeds or gives a specific error indicating the filesystem type
                        if result.returncode in [0, 1, 2]:  # Common exit codes for detected filesystems
                            if fs_type == 'ntfs' and ('ntfs' in result.stderr.lower() or result.returncode == 0):
                                return 'ntfs'
                            elif fs_type.startswith('ext') and ('ext' in result.stderr.lower() or result.returncode in [0, 1]):
                                return fs_type
                            elif fs_type == 'xfs' and result.returncode == 0:
                                return 'xfs'
                    except subprocess.TimeoutExpired:
                        continue
                    except Exception:
                        continue
            
            # Method 5: Try hexdump to read filesystem signatures
            try:
                if shutil.which('hexdump'):
                    # Read first few sectors for filesystem signatures
                    result = subprocess.run(
                        ['hexdump', '-C', '-n', '1024', partition_device],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        hex_output = result.stdout.lower()
                        # NTFS signature
                        if 'ntfs' in hex_output:
                            return 'ntfs'
                        # ext filesystem signatures
                        elif '53ef' in hex_output.replace(' ', ''):  # ext magic number
                            return 'ext4'  # Default to ext4
                        # FAT signature
                        elif 'fat' in hex_output or 'msdos' in hex_output:
                            return 'fat32'
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            
            # If all methods fail, return unknown
            return 'unknown'
            
        except Exception as e:
            # Log the error if needed
            print(f"Warning: Could not detect filesystem type for {partition_device}: {e}")
            return 'unknown'
    
    @staticmethod
    def get_partition_info(nbd_device, progress_callback=None):
        """Get partition information from mounted NBD device"""
        try:
            if progress_callback:
                progress_callback(5, "Analyzing partitions...")
            
            # Get partition table info
            result = subprocess.run(
                ['parted', '-s', nbd_device, 'print'],
                capture_output=True, text=True, check=True, timeout=30
            )
            
            partitions = []
            lines = result.stdout.split('\n')
            
            for line in lines:
                line = line.strip()
                if re.match(r'^\s*\d+\s+', line):  # Partition line
                    parts = line.split()
                    if len(parts) >= 6:
                        partition_num = int(parts[0])
                        start = parts[1]
                        end = parts[2]
                        size = parts[3]
                        fs_type = parts[4] if len(parts) > 4 else 'unknown'
                        flags = ' '.join(parts[5:]) if len(parts) > 5 else ''
                        
                        partition_device = f"{nbd_device}p{partition_num}"
                        
                        # Get more accurate filesystem type
                        actual_fs = QCow2Resizer.get_filesystem_type(partition_device)
                        if actual_fs != 'unknown':
                            fs_type = actual_fs
                        
                        # Determine partition type
                        partition_type = QCow2Resizer.classify_partition(fs_type, flags, size)
                        
                        partitions.append({
                            'number': partition_num,
                            'start': start,
                            'end': end,
                            'size': size,
                            'filesystem': fs_type,
                            'device': partition_device,
                            'flags': flags,
                            'type': partition_type
                        })
            
            return partitions
            
        except Exception as e:
            raise Exception(f"Failed to analyze partitions: {e}")
    
    @staticmethod
    def classify_partition(filesystem, flags, size):
        """Classify partition type (system, data, swap, boot, etc.)"""
        fs_lower = filesystem.lower()
        flags_lower = flags.lower()
        
        # Skip swap partitions
        if fs_lower in ['swap', 'linux-swap', 'linux-swap(v1)']:
            return 'swap'
        
        # Skip boot partitions (usually small and have boot flag)
        if 'boot' in flags_lower or 'esp' in flags_lower:
            return 'boot'
        
        # Small partitions are likely boot/EFI (< 1GB)
        try:
            if 'mb' in size.lower():
                size_mb = float(size.lower().replace('mb', ''))
                if size_mb < 1000:  # Less than 1GB
                    return 'boot'
        except:
            pass
        
        # System/Data partitions we want to resize
        if fs_lower in ['ntfs', 'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'fat32']:
            return 'data'
        
        return 'unknown'
    
    @staticmethod
    def find_resizable_partitions(partitions):
        """Find partitions that should be resized (data/system only)"""
        resizable = []
        
        for partition in partitions:
            if partition['type'] == 'data':
                resizable.append(partition)
        
        # Sort by partition number and return the largest data partition
        if resizable:
            # Return the last (usually largest) data partition
            return sorted(resizable, key=lambda p: p['number'])[-1]
        
        return None
    
    @staticmethod
    def setup_nbd_device(image_path, progress_callback=None):
        """Setup NBD device for filesystem operations"""
        try:
            if progress_callback:
                progress_callback(5, "Setting up NBD device...")
            
            # Load nbd module
            subprocess.run(['modprobe', 'nbd'], check=False)
            
            # Find available NBD device
            nbd_device = None
            for i in range(16):  # Check nbd0 to nbd15
                device = f"/dev/nbd{i}"
                if os.path.exists(device):
                    # Check if device is free
                    try:
                        result = subprocess.run(
                            ['lsblk', device],
                            capture_output=True, text=True, timeout=5
                        )
                        if device not in result.stdout or "disk" not in result.stdout:
                            nbd_device = device
                            break
                    except:
                        nbd_device = device
                        break
            
            if not nbd_device:
                raise Exception("No available NBD device found")
            
            # Connect image to NBD device
            subprocess.run(
                ['qemu-nbd', '--connect', nbd_device, image_path],
                check=True, timeout=30
            )
            
            # Wait for device to be ready
            time.sleep(2)
            
            # Trigger partition re-read
            subprocess.run(['partprobe', nbd_device], check=False)
            time.sleep(1)
            
            return nbd_device
            
        except Exception as e:
            raise Exception(f"Failed to setup NBD device: {e}")
    
    @staticmethod
    def cleanup_nbd_device(nbd_device):
        """Cleanup NBD device"""
        try:
            subprocess.run(['qemu-nbd', '--disconnect', nbd_device], 
                         check=False, timeout=10)
        except:
            pass
    
    @staticmethod
    def resize_ntfs_filesystem(partition_device, operation, target_size_mb=None, progress_callback=None):
        """Resize NTFS filesystem using ntfsresize"""
        try:
            if not shutil.which('ntfsresize'):
                raise Exception("ntfsresize not available - install ntfs-3g package")
            
            if progress_callback:
                progress_callback(30, "Checking NTFS filesystem...")
            
            # Check filesystem
            subprocess.run(['ntfsfix', partition_device], check=True, timeout=300)
            
            if progress_callback:
                progress_callback(60, f"Resizing NTFS filesystem...")
            
            if operation == "shrink":
                if not target_size_mb:
                    raise Exception("Target size required for NTFS shrinking")
                # Shrink NTFS filesystem
                subprocess.run(['ntfsresize', '-f', '-s', f"{target_size_mb}M", partition_device],
                             check=True, timeout=600)
            else:
                # Expand NTFS filesystem to fill partition
                subprocess.run(['ntfsresize', '-f', partition_device],
                             check=True, timeout=600)
            
            if progress_callback:
                progress_callback(90, "Verifying NTFS filesystem...")
            
            # Final check
            subprocess.run(['ntfsfix', partition_device], check=True, timeout=300)
            
        except Exception as e:
            raise Exception(f"NTFS filesystem resize failed: {e}")
    
    @staticmethod
    def resize_filesystem(partition_device, operation, progress_callback=None):
        """Resize filesystem on partition"""
        try:
            if progress_callback:
                progress_callback(30, f"Checking filesystem...")
            
            # Check filesystem
            result = subprocess.run(['e2fsck', '-f', '-y', partition_device],
                                  capture_output=True, text=True, timeout=300)
            
            if progress_callback:
                progress_callback(60, f"Resizing filesystem...")
            
            if operation == "shrink":
                # For shrinking, we need to calculate the target size
                # This is a simplified approach - in practice you'd want more sophisticated size calculation
                raise Exception("Filesystem shrinking requires manual size calculation")
            else:
                # Expand filesystem to fill partition
                subprocess.run(['resize2fs', partition_device],
                             check=True, timeout=600)
            
            if progress_callback:
                progress_callback(90, "Verifying filesystem...")
            
            # Final check
            subprocess.run(['e2fsck', '-f', '-y', partition_device],
                         check=True, capture_output=True, text=True, timeout=300)
            
        except Exception as e:
            raise Exception(f"Filesystem resize failed: {e}")
    
    @staticmethod
    def resize_filesystem_universal(partition_device, filesystem, operation, target_size_mb=None, progress_callback=None):
        """Universal filesystem resize function with stop flag support"""
        try:
            # Check for stop flag
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'stop_flag'):
                if progress_callback.__self__.stop_flag:
                    raise KeyboardInterrupt("Operation cancelled")
            
            if progress_callback:
                progress_callback(25, f"Resizing {filesystem} filesystem...")
            
            if filesystem.startswith('ext'):
                # Use existing ext2/3/4 resize logic
                if operation == "shrink":
                    if not target_size_mb:
                        raise Exception("Target size required for ext filesystem shrinking")
                    QCow2Resizer.shrink_filesystem_first(partition_device, target_size_mb, progress_callback)
                else:
                    QCow2Resizer.resize_filesystem(partition_device, operation, progress_callback)
            
            elif filesystem == 'ntfs':
                # Use NTFS resize
                QCow2Resizer.resize_ntfs_filesystem(partition_device, operation, target_size_mb, progress_callback)
            
            elif filesystem in ['fat32', 'fat', 'vfat']:
                # FAT32 doesn't support online resizing - suggest gparted
                raise Exception("FAT32 resize requires GParted GUI - use manual resize")
                
            elif filesystem in ['xfs', 'btrfs', 'reiserfs']:
                # These would need specific tools - suggest gparted
                raise Exception(f"{filesystem} resize requires specific tools - use GParted for complex operations")
            
            else:
                raise Exception(f"Unsupported filesystem: {filesystem}. Use GParted for manual resize.")
                
        except Exception as e:
            raise Exception(f"Filesystem resize failed: {e}")
    
    @staticmethod
    def resize_partition(nbd_device, partition_num, new_end_size, progress_callback=None):
        """Resize partition using parted with stop flag support"""
        try:
            # Check for stop flag
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'stop_flag'):
                if progress_callback.__self__.stop_flag:
                    raise KeyboardInterrupt("Operation cancelled")
            
            if progress_callback:
                progress_callback(20, "Resizing partition...")
            
            # Resize partition
            subprocess.run([
                'parted', '-s', nbd_device, 'resizepart', 
                str(partition_num), new_end_size
            ], check=True, timeout=60)
            
            # Trigger partition table re-read
            subprocess.run(['partprobe', nbd_device], check=False)
            time.sleep(1)
            
        except Exception as e:
            raise Exception(f"Partition resize failed: {e}")
    
    @staticmethod
    def shrink_filesystem_first(partition_device, target_size_mb, progress_callback=None):
        """Shrink filesystem before shrinking partition with stop flag support"""
        try:
            # Check for stop flag
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'stop_flag'):
                if progress_callback.__self__.stop_flag:
                    raise KeyboardInterrupt("Operation cancelled")
            
            if progress_callback:
                progress_callback(15, "Checking filesystem before shrink...")
            
            # Force check filesystem
            subprocess.run(['e2fsck', '-f', '-y', partition_device],
                         check=True, capture_output=True, text=True, timeout=300)
            
            # Check for stop flag
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'stop_flag'):
                if progress_callback.__self__.stop_flag:
                    raise KeyboardInterrupt("Operation cancelled")
            
            if progress_callback:
                progress_callback(25, "Shrinking filesystem...")
            
            # Shrink filesystem (size in 1K blocks)
            target_blocks = target_size_mb * 1024
            subprocess.run(['resize2fs', partition_device, f"{target_blocks}"],
                         check=True, timeout=600)
            
            if progress_callback:
                progress_callback(35, "Verifying shrunken filesystem...")
            
            # Verify filesystem
            subprocess.run(['e2fsck', '-f', '-y', partition_device],
                         check=True, capture_output=True, text=True, timeout=300)
            
        except Exception as e:
            raise Exception(f"Filesystem shrink failed: {e}")
    
    @staticmethod
    def launch_gparted(nbd_device):
        """Launch GParted GUI for manual filesystem operations and wait for completion"""
        try:
            if not shutil.which('gparted'):
                raise Exception("GParted not available - install gparted package")
            
            # Launch GParted with the NBD device and wait for it to complete
            process = subprocess.run(['gparted', nbd_device], timeout=3600)  # 1 hour timeout
            
            # GParted closed normally
            return True
            
        except subprocess.TimeoutExpired:
            raise Exception("GParted operation timed out (1 hour limit)")
        except Exception as e:
            raise Exception(f"Could not launch GParted: {e}")
    
    @staticmethod
    def resize_image(image_path, new_size_bytes, progress_callback=None):
        """Resize QCOW2 image to new size with stop flag support"""
        try:
            # Check for stop flag
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'stop_flag'):
                if progress_callback.__self__.stop_flag:
                    raise KeyboardInterrupt("Operation cancelled")
            
            if progress_callback:
                progress_callback(10, "Starting resize...")
            
            # Execute resize
            result = subprocess.run(
                ['qemu-img', 'resize', image_path, str(new_size_bytes)],
                capture_output=True, text=True, check=True, timeout=600
            )
            
            # Check for stop flag
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'stop_flag'):
                if progress_callback.__self__.stop_flag:
                    raise KeyboardInterrupt("Operation cancelled")
            
            if progress_callback:
                progress_callback(90, "Verifying resize...")
            
            # Verify resize
            new_info = QCow2Resizer.get_image_info(image_path)
            actual_size = new_info['virtual_size']
            
            if abs(actual_size - new_size_bytes) > 1024 * 1024:  # 1MB tolerance
                raise Exception(f"Resize verification failed: expected {new_size_bytes}, got {actual_size}")
            
            if progress_callback:
                progress_callback(100, "Resize completed")
            
            return new_info
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"qemu-img resize failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise Exception("Resize operation timed out") str(new_size_bytes)],
                capture_output=True, text=True, check=True, timeout=600
            )
            
            if progress_callback:
                progress_callback(90, "Verifying resize...")
            
            # Verify resize
            new_info = QCow2Resizer.get_image_info(image_path)
            actual_size = new_info['virtual_size']
            
            if abs(actual_size - new_size_bytes) > 1024 * 1024:  # 1MB tolerance
                raise Exception(f"Resize verification failed: expected {new_size_bytes}, got {actual_size}")
            
            if progress_callback:
                progress_callback(100, "Resize completed")
            
            return new_info
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"qemu-img resize failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise Exception("Resize operation timed out")
    
    @staticmethod
    def resize_with_filesystem(image_path, new_size_bytes, resize_filesystem=True, use_gparted=False, progress_callback=None):
        """Resize QCOW2 image and optionally resize filesystem"""
        nbd_device = None
        
        try:
            current_info = QCow2Resizer.get_image_info(image_path)
            current_size = current_info['virtual_size']
            operation = "expand" if new_size_bytes > current_size else "shrink"
            
            if resize_filesystem or use_gparted:
                # Setup NBD device for filesystem operations
                nbd_device = QCow2Resizer.setup_nbd_device(image_path, progress_callback)
                
                # Get partition information
                partitions = QCow2Resizer.get_partition_info(nbd_device, progress_callback)
                
                if not partitions:
                    raise Exception("No partitions found in image")
                
                # Find the main data/system partition (skip boot, swap, etc.)
                main_partition = QCow2Resizer.find_resizable_partitions(partitions)
                
                if not main_partition:
                    raise Exception("No resizable data/system partitions found. Only boot/swap partitions detected.")
                
                partition_device = main_partition['device']
                filesystem = main_partition['filesystem']
                
                # Log partition info for debugging
                print(f"Found resizable partition: {partition_device} ({filesystem}, {main_partition['size']})")
                for p in partitions:
                    print(f"  Partition {p['number']}: {p['filesystem']} ({p['type']}) - {p['size']}")
                
                # Check if partition device exists
                if not os.path.exists(partition_device):
                    # Wait a bit more for device to appear
                    time.sleep(3)
                    subprocess.run(['partprobe', nbd_device], check=False)
                    time.sleep(2)
                    
                    if not os.path.exists(partition_device):
                        raise Exception(f"Partition device not found: {partition_device}")
                
                if use_gparted:
                    # Launch GParted for manual operations
                    if progress_callback:
                        progress_callback(20, "Launching GParted...")
                    
                    print(f"\nLaunching GParted for manual resize...")
                    print(f"Device: {nbd_device}")
                    print(f"Target partition: {partition_device} ({filesystem})")
                    print(f"Operation: {operation}")
                    print(f"\nGParted will open - resize the data/system partition as needed.")
                    print(f"The script will continue automatically when GParted is closed.")
                    
                    # Launch GParted and wait for completion
                    QCow2Resizer.launch_gparted(nbd_device)
                    
                    if progress_callback:
                        progress_callback(80, "GParted operations completed...")
                    
                    # Cleanup NBD before image resize
                    QCow2Resizer.cleanup_nbd_device(nbd_device)
                    nbd_device = None
                    
                    # Resize image to match the new partition layout
                    new_info = QCow2Resizer.resize_image(image_path, new_size_bytes, progress_callback)
                    
                elif resize_filesystem:
                    # Automatic filesystem resize
                    if operation == "shrink":
                        # Check for stop flag
                        if self.stop_flag:
                            raise KeyboardInterrupt("Operation cancelled")
                        
                        # For shrinking: shrink filesystem first, then partition, then image
                        target_size_mb = int((new_size_bytes * 0.9) / (1024 * 1024))
                        
                        QCow2Resizer.resize_filesystem_universal(
                            partition_device, filesystem, operation, target_size_mb, self.update_progress
                        )
                        
                        # Check for stop flag
                        if self.stop_flag:
                            raise KeyboardInterrupt("Operation cancelled")
                        
                        # Calculate new partition end
                        new_end_mb = int(new_size_bytes / (1024 * 1024))
                        QCow2Resizer.resize_partition(nbd_device, main_partition['number'], f"{new_end_mb}MB", self.update_progress)
                        
                        # Cleanup NBD before resizing image
                        QCow2Resizer.cleanup_nbd_device(nbd_device)
                        nbd_device = None
                        
                        # Check for stop flag
                        if self.stop_flag:
                            raise KeyboardInterrupt("Operation cancelled")
                        
                        # Resize image
                        new_info = QCow2Resizer.resize_image(image_path, new_size_bytes, self.update_progress)
                    
                    else:
                        # For expanding: resize image first, then partition, then filesystem
                        # Cleanup NBD before resizing image
                        QCow2Resizer.cleanup_nbd_device(nbd_device)
                        nbd_device = None
                        
                        # Check for stop flag
                        if self.stop_flag:
                            raise KeyboardInterrupt("Operation cancelled")
                        
                        # Resize image first
                        new_info = QCow2Resizer.resize_image(image_path, new_size_bytes, self.update_progress)
                        
                        # Check for stop flag
                        if self.stop_flag:
                            raise KeyboardInterrupt("Operation cancelled")
                        
                        # Reconnect NBD device
                        nbd_device = QCow2Resizer.setup_nbd_device(image_path, self.update_progress)
                        
                        # Resize partition to use all available space
                        QCow2Resizer.resize_partition(nbd_device, main_partition['number'], "100%", self.update_progress)
                        
                        # Check for stop flag before filesystem resize
                        if self.stop_flag:
                            raise KeyboardInterrupt("Operation cancelled")
                        
                        # Resize filesystem to fill partition
                        partition_device = f"{nbd_device}p{main_partition['number']}"
                        QCow2Resizer.resize_filesystem_universal(
                            partition_device, filesystem, operation, None, self.update_progress
                        )
            
            else:
                # Just resize the image without filesystem changes
                new_info = QCow2Resizer.resize_image(image_path, new_size_bytes, progress_callback)
            
            return new_info
            
        except Exception as e:
            raise e
        finally:
            # Always cleanup NBD device
            if nbd_device:
                QCow2Resizer.cleanup_nbd_device(nbd_device)
    
    @staticmethod
    def create_backup(image_path):
        """Create backup of image"""
        backup_path = f"{image_path}.backup.{int(time.time())}"
        shutil.copy2(image_path, backup_path)
        return backup_path


class QCow2ResizerGUI:
    """GUI for QCOW2 resizing with filesystem support"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("QCOW2 Resizer")
        self.root.geometry("700x700")  # Increased height for new options
        
        # Only set fullscreen if this is the main window (not a Toplevel)
        if isinstance(root, tk.Tk):
            self.root.attributes('-fullscreen', True)
        
        self.image_path = tk.StringVar()
        self.image_info = None
        self.operation_active = False
        self.stop_flag = False
        self.resize_filesystem = tk.BooleanVar(value=False)  # Automatic resize
        self.use_gparted = tk.BooleanVar(value=False)      # Manual GParted mode
        
        self.setup_ui()
        self.check_prerequisites()
        
        # Set up proper close protocol
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
    

    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno("Operation in Progress", 
                                    "An operation is currently running.\n\n"
                                    "Are you sure you want to close?\n"
                                    "This will stop the current operation.",
                                    parent=self.root)
            if not result:
                return
            
            # Stop the operation
            self.stop_flag = True
        
        # Destroy the window
        self.root.destroy()

    def setup_ui(self):
        """Setup user interface"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title = ttk.Label(main_frame, text="QCOW2 Virtual Disk Resizer", 
                        font=("Arial", 14, "bold"))
        title.pack(pady=(0, 20))
        
        # Prerequisites
        self.prereq_frame = ttk.LabelFrame(main_frame, text="Prerequisites", padding="10")
        self.prereq_frame.pack(fill="x", pady=(0, 10))
        
        self.prereq_label = ttk.Label(self.prereq_frame, text="Checking...")
        self.prereq_label.pack()
        
        # File selection
        file_frame = ttk.LabelFrame(main_frame, text="Image File", padding="10")
        file_frame.pack(fill="x", pady=(0, 10))
        
        path_frame = ttk.Frame(file_frame)
        path_frame.pack(fill="x")
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.image_path, width=50)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        ttk.Button(path_frame, text="Browse", command=self.browse_file).pack(side="right", padx=(0, 5))
        ttk.Button(path_frame, text="Analyze", command=self.analyze_image).pack(side="right")
        
        # Image info
        info_frame = ttk.LabelFrame(main_frame, text="Image Information", padding="10")
        info_frame.pack(fill="x", pady=(0, 10))
        
        self.info_text = tk.Text(info_frame, height=6, state="disabled", wrap="word")
        self.info_text.pack(fill="x")
        
        # Resize controls
        resize_frame = ttk.LabelFrame(main_frame, text="Resize Configuration", padding="10")
        resize_frame.pack(fill="x", pady=(0, 10))
        
        # New size input
        size_frame = ttk.Frame(resize_frame)
        size_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(size_frame, text="New Size:").pack(side="left")
        
        self.new_size = tk.StringVar(value="20G")
        size_entry = ttk.Entry(size_frame, textvariable=self.new_size, width=15)
        size_entry.pack(side="right")
        
        ttk.Label(size_frame, text="(e.g., 20G, 512M, 1.5T)").pack(side="right", padx=(0, 10))
        
        # Filesystem resize options
        fs_frame = ttk.LabelFrame(resize_frame, text="Filesystem Options", padding="5")
        fs_frame.pack(fill="x", pady=(0, 10))
        
        fs_auto = ttk.Checkbutton(fs_frame, text="Automatically resize filesystem (ext2/3/4, NTFS)", 
                                 variable=self.resize_filesystem, command=self.update_target_info)
        fs_auto.pack(anchor="w", pady=(0, 5))
        
        fs_manual = ttk.Checkbutton(fs_frame, text="Use GParted for manual resize (supports all filesystems)", 
                                   variable=self.use_gparted, command=self.update_target_info)
        fs_manual.pack(anchor="w")
        
        # Add note
        fs_note = ttk.Label(fs_frame, text="Note: Both options require root privileges", 
                           font=("Arial", 8), foreground="gray")
        fs_note.pack(anchor="w", pady=(2, 0))
        
        # Target size display
        self.target_label = ttk.Label(resize_frame, text="", font=("Arial", 9, "bold"))
        self.target_label.pack(pady=(5, 0))
        
        # Warnings
        self.warning_label = ttk.Label(resize_frame, text="", foreground="red", wraplength=600)
        self.warning_label.pack(pady=(5, 0))
        
        # Bind size input changes
        self.new_size.trace('w', self.update_target_info)
        
        # Progress
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill="x", pady=(0, 10))
        
        self.progress = ttk.Progressbar(progress_frame, length=400)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.progress_label = ttk.Label(progress_frame, text="Ready")
        self.progress_label.pack(side="right")
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        
        self.resize_btn = ttk.Button(button_frame, text="Resize Image", command=self.start_resize)
        self.resize_btn.pack(side="left", padx=(0, 10))
        
        self.stop_btn = ttk.Button(button_frame, text="Stop", command=self.stop_operation, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 10))
        
        ttk.Button(button_frame, text="Close", command=self.close_window).pack(side="right")
    
    def check_prerequisites(self):
        """Check if required tools are installed"""
        missing, optional_missing = QCow2Resizer.check_tools()
        
        if missing:
            text = f"Missing required: {', '.join(missing)}"
            self.prereq_label.config(text=text, foreground="red")
            self.resize_btn.config(state="disabled")
            
            install_msg = "Required tools missing!\n\n"
            install_msg += "Ubuntu/Debian:\n"
            install_msg += "sudo apt install qemu-utils parted\n\n"
            install_msg += "For Windows/NTFS support:\n"
            install_msg += "sudo apt install ntfs-3g\n\n"
            install_msg += "For GUI operations:\n"
            install_msg += "sudo apt install gparted\n\n"
            install_msg += "For ext2/3/4 filesystems:\n"
            install_msg += "sudo apt install e2fsprogs"
            
            messagebox.showerror("Missing Tools", install_msg)
        else:
            optional_count = len(optional_missing)
            if optional_count > 0:
                text = f"Core tools OK ({optional_count} optional tools missing)"
                self.prereq_label.config(text=text, foreground="orange")
            else:
                self.prereq_label.config(text="All tools available", foreground="green")
    
    def browse_file(self):
        """Browse for QCOW2 file"""
        file_path = filedialog.askopenfilename(
            title="Select QCOW2 Image",
            filetypes=[("QCOW2 files", "*.qcow2"), ("All files", "*.*")]
        )
        if file_path:
            self.image_path.set(file_path)
            self.analyze_image()
    
    def analyze_image(self):
        """Analyze selected image"""
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("Warning", "Please select an image file")
            return
        
        if not os.path.exists(path):
            messagebox.showerror("Error", "File does not exist")
            return
        
        try:
            self.image_info = QCow2Resizer.get_image_info(path)
            self.display_image_info()
            self.update_target_info()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to analyze image: {e}")
    
    def display_image_info(self):
        """Display image information"""
        if not self.image_info:
            return
        
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        
        info = f"File: {os.path.basename(self.image_path.get())}\n"
        info += f"Format: {self.image_info['format']}\n"
        info += f"Virtual Size: {QCow2Resizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"Actual Size: {QCow2Resizer.format_size(self.image_info['actual_size'])}\n"
        
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Space Usage: {ratio*100:.1f}%\n"
        
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")
    
    def update_target_info(self, *args):
        """Update target size information and warnings"""
        if not self.image_info:
            return
        
        try:
            new_size_str = self.new_size.get().strip()
            if not new_size_str:
                return
            
            new_size_bytes = QCow2Resizer.parse_size(new_size_str)
            current_size = self.image_info['virtual_size']
            
            # Update target display
            self.target_label.config(
                text=f"Target: {QCow2Resizer.format_size(new_size_bytes)}"
            )
            
            # Generate warnings
            warnings = []
            
            if new_size_bytes == current_size:
                warnings.append("No change - target equals current size")
            elif new_size_bytes < current_size:
                # Shrinking
                reduction = current_size - new_size_bytes
                warnings.append(f"SHRINKING by {QCow2Resizer.format_size(reduction)}")
                if self.resize_filesystem.get():
                    warnings.append("Will shrink filesystem first, then partition, then image")
                    warnings.append("REQUIRES ROOT PRIVILEGES")
                else:
                    warnings.append("WARNING: Must shrink filesystem FIRST!")
                warnings.append("BACKUP required before shrinking!")
            else:
                # Expanding
                increase = new_size_bytes - current_size
                warnings.append(f"Expanding by {QCow2Resizer.format_size(increase)}")
                if self.resize_filesystem.get():
                    warnings.append("Will resize image, then partition, then filesystem")
                    warnings.append("REQUIRES ROOT PRIVILEGES")
                else:
                    warnings.append("Safe operation - can extend partitions after")
            
            # Filesystem resize warnings
            if self.resize_filesystem.get() or self.use_gparted.get():
                if self.use_gparted.get():
                    warnings.append("GParted mode: will launch GUI for manual operations")
                    warnings.append("Supports ALL filesystems (NTFS, ext4, FAT32, etc.)")
                else:
                    warnings.append("Automatic resize: supports ext2/3/4 and NTFS only")
                
                warnings.append("REQUIRES ROOT PRIVILEGES")
                warnings.append("Ensure VM is completely shut down")
                
                # Check if running as root
                if os.geteuid() != 0:
                    warnings.append("ERROR: Root privileges required for filesystem operations")
                    
                # Mutual exclusion warning
                if self.resize_filesystem.get() and self.use_gparted.get():
                    warnings.append("WARNING: Select either automatic OR GParted mode, not both!")
            
            # Check disk space
            try:
                free_space = shutil.disk_usage(os.path.dirname(self.image_path.get())).free
                if new_size_bytes > current_size:
                    needed = new_size_bytes - current_size
                    if needed > free_space:
                        warnings.append(f"Insufficient space (need {QCow2Resizer.format_size(needed)})")
            except:
                pass
            
            self.warning_label.config(text="\n".join(warnings))
            
        except ValueError as e:
            self.target_label.config(text="Invalid size format")
            self.warning_label.config(text=str(e))
    
    def start_resize(self):
        """Start resize operation"""
        if not self.validate_inputs():
            return
        
        path = self.image_path.get()
        new_size_str = self.new_size.get()
        resize_fs = self.resize_filesystem.get()
        use_gparted = self.use_gparted.get()
        
        # Validate mutual exclusion
        if resize_fs and use_gparted:
            messagebox.showerror("Invalid Configuration", 
                "Please select either automatic resize OR GParted mode, not both.")
            return
        
        try:
            new_size_bytes = QCow2Resizer.parse_size(new_size_str)
            current_size = self.image_info['virtual_size']
            
            # Confirmation
            operation = "expand" if new_size_bytes > current_size else "shrink"
            
            msg = f"Resize QCOW2 Image\n\n"
            msg += f"File: {os.path.basename(path)}\n"
            msg += f"Current: {QCow2Resizer.format_size(current_size)}\n"
            msg += f"Target: {QCow2Resizer.format_size(new_size_bytes)}\n"
            msg += f"Operation: {operation.upper()}\n"
            
            if use_gparted:
                msg += f"Mode: GParted Manual Resize\n\n"
                msg += "Process:\n"
                msg += "1. GParted will open for manual operations\n"
                msg += "2. Resize partitions as needed\n"
                msg += "3. Close GParted when finished\n"
                msg += "4. Image will be resized automatically\n\n"
            elif resize_fs:
                msg += f"Mode: Automatic Filesystem Resize\n\n"
            else:
                msg += f"Mode: Image Only (no filesystem changes)\n\n"
            
            if operation == "shrink":
                msg += "WARNING: Shrinking can cause data loss!\n"
                if not resize_fs and not use_gparted:
                    msg += "Ensure filesystem is already shrunk!\n\n"
                else:
                    msg += "Filesystem will be handled automatically!\n\n"
            
            if resize_fs or use_gparted:
                msg += "REQUIRES ROOT PRIVILEGES!\n"
                msg += "Ensure VM is completely shut down!\n\n"
            
            msg += "Continue?"
            
            if not messagebox.askyesno("Confirm Resize", msg):
                return
            
            # Check root privileges for filesystem operations
            if (resize_fs or use_gparted) and os.geteuid() != 0:
                messagebox.showerror("Permission Error", 
                    "Root privileges required for filesystem operations.\n"
                    "Run this application with sudo or disable filesystem resizing.")
                return
            
            # Start resize in thread
            self.operation_active = True
            self.stop_flag = False
            self.resize_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            
            thread = threading.Thread(
                target=self._resize_worker,
                args=(path, new_size_bytes, operation, resize_fs, use_gparted)
            )
            thread.daemon = True
            thread.start()
            
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid size: {e}")
    
    def _resize_worker(self, image_path, new_size_bytes, operation, resize_filesystem, use_gparted):
        """Worker thread for resize operation"""
        backup_path = None
        
        try:
            # Create backup for shrink operations
            if operation == "shrink":
                self.update_progress(5, "Creating backup...")
                backup_path = QCow2Resizer.create_backup(image_path)
                self.log(f"Backup created: {backup_path}")
            
            if self.stop_flag:
                raise KeyboardInterrupt("Cancelled")
            
            # Perform resize with appropriate method
            self.update_progress(20, f"Resizing image...")
            if resize_filesystem or use_gparted:
                new_info = QCow2Resizer.resize_with_filesystem(
                    image_path, new_size_bytes, resize_filesystem, use_gparted, self.update_progress
                )
            else:
                new_info = QCow2Resizer.resize_image(image_path, new_size_bytes, self.update_progress)
            
            if self.stop_flag:
                raise KeyboardInterrupt("Cancelled")
            
            # Success
            self.log(f"Resize completed successfully!")
            self.log(f"New size: {QCow2Resizer.format_size(new_info['virtual_size'])}")
            
            # Update image info
            self.image_info = new_info
            self.root.after(0, self.display_image_info)
            
            # Remove backup on successful shrink
            if backup_path and os.path.exists(backup_path):
                os.remove(backup_path)
                self.log("Backup removed (operation successful)")
            
            # Show completion message
            success_msg = f"Resize completed!\n\n"
            success_msg += f"New size: {QCow2Resizer.format_size(new_info['virtual_size'])}\n\n"
            
            if use_gparted:
                success_msg += "GParted operations completed successfully."
            elif resize_filesystem:
                if operation == "expand":
                    success_msg += "Filesystem has been expanded to fill the new space."
                else:
                    success_msg += "Filesystem and partition have been shrunk."
            else:
                if operation == "expand":
                    success_msg += "Use partition tools to extend partitions"
                else:
                    success_msg += "Verify VM boots correctly"
            
            self.root.after(0, lambda: messagebox.showinfo("Success", success_msg))
            
        except KeyboardInterrupt:
            self.log("Operation cancelled by user")
        except Exception as e:
            self.log(f"Error: {e}")
            
            # Restore backup on shrink failure
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.move(backup_path, image_path)
                    self.log("Image restored from backup")
                except Exception as restore_err:
                    self.log(f"CRITICAL: Could not restore backup: {restore_err}")
            
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        
        finally:
            self.root.after(0, self.reset_ui)
    
    def validate_inputs(self):
        """Validate user inputs"""
        path = self.image_path.get().strip()
        
        if not path:
            messagebox.showwarning("Warning", "Select an image file")
            return False
        
        if not os.path.exists(path):
            messagebox.showerror("Error", "File does not exist")
            return False
        
        if not self.image_info:
            messagebox.showwarning("Warning", "Analyze the image first")
            return False
        
        try:
            new_size_bytes = QCow2Resizer.parse_size(self.new_size.get())
            current_size = self.image_info['virtual_size']
            
            if new_size_bytes <= 0:
                messagebox.showerror("Error", "Size must be positive")
                return False
            
            if abs(new_size_bytes - current_size) < 1024 * 1024:  # Less than 1MB
                messagebox.showwarning("Warning", "Size change too small (minimum 1MB)")
                return False
            
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid size format: {e}")
            return False
        
        return True
    
    def update_progress(self, percent, status):
        """Update progress bar and status"""
        def update():
            self.progress['value'] = percent
            self.progress_label.config(text=status)
        
        self.root.after(0, update)
    
    def log(self, message):
        """Log message to console"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    def stop_operation(self):
        """Stop current operation"""
        if self.operation_active:
            self.stop_flag = True
            self.log("Stop requested - cancelling operation...")
            self.update_progress(0, "Stopping...")
            
            # Force cleanup after a short delay if needed
            def force_cleanup():
                time.sleep(3)
                if self.operation_active:
                    self.log("Force stopping operation")
                    self.reset_ui()
            
            thread = threading.Thread(target=force_cleanup)
            thread.daemon = True
            thread.start()
    
    def reset_ui(self):
        """Reset UI after operation"""
        self.operation_active = False
        self.stop_flag = False
        self.resize_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress['value'] = 0
        self.progress_label.config(text="Ready")


def resize_qcow2_cli(image_path, new_size, create_backup=True, resize_filesystem=False, use_gparted=False):
    """Command-line resize function"""
    try:
        # Validate inputs
        if not os.path.exists(image_path):
            raise Exception(f"Image file not found: {image_path}")
        
        # Validate mutual exclusion
        if resize_filesystem and use_gparted:
            raise Exception("Cannot use both automatic resize and GParted mode simultaneously")
        
        # Get current info
        current_info = QCow2Resizer.get_image_info(image_path)
        new_size_bytes = QCow2Resizer.parse_size(new_size)
        
        current_size = current_info['virtual_size']
        operation = "expand" if new_size_bytes > current_size else "shrink"
        
        print(f"Image: {image_path}")
        print(f"Current size: {QCow2Resizer.format_size(current_size)}")
        print(f"Target size: {QCow2Resizer.format_size(new_size_bytes)}")
        print(f"Operation: {operation}")
        print(f"Resize filesystem: {resize_filesystem}")
        print(f"Use GParted: {use_gparted}")
        
        if new_size_bytes == current_size:
            print("No change needed - sizes are equal")
            return True
        
        # Check root privileges for filesystem operations
        if (resize_filesystem or use_gparted) and os.geteuid() != 0:
            print("ERROR: Root privileges required for filesystem operations")
            print("Run with sudo or disable filesystem resizing")
            return False
        
        # Create backup for shrink operations
        backup_path = None
        if operation == "shrink" and create_backup:
            print("Creating backup...")
            backup_path = QCow2Resizer.create_backup(image_path)
            print(f"Backup: {backup_path}")
        
        # Perform resize
        print("Resizing...")
        if resize_filesystem or use_gparted:
            new_info = QCow2Resizer.resize_with_filesystem(image_path, new_size_bytes, resize_filesystem, use_gparted)
        else:
            new_info = QCow2Resizer.resize_image(image_path, new_size_bytes)
        
        print(f"Success! New size: {QCow2Resizer.format_size(new_info['virtual_size'])}")
        
        # Clean up backup on success
        if backup_path and os.path.exists(backup_path):
            os.remove(backup_path)
            print("Backup removed")
        
        if use_gparted:
            print("\nGParted operations completed successfully")
        elif resize_filesystem:
            if operation == "expand":
                print("\nFilesystem has been expanded to fill the new space")
            else:
                print("\nFilesystem and partition have been shrunk")
        else:
            if operation == "expand":
                print("\nNext: Use partition tools to extend partitions")
            else:
                print("\nNext: Verify VM boots correctly")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        
        # Restore backup on failure
        if backup_path and os.path.exists(backup_path):
            try:
                shutil.move(backup_path, image_path)
                print("Image restored from backup")
            except Exception as restore_err:
                print(f"CRITICAL: Could not restore backup: {restore_err}")
                print(f"Manual restore: mv {backup_path} {image_path}")
        
        return False


def main():
    """Main entry point - launches GUI by default"""
    # Check tools
    missing, optional_missing = QCow2Resizer.check_tools()
    if missing:
        print(f"Error: Missing required tools: {', '.join(missing)}")
        print("Install required packages:")
        print("Ubuntu/Debian: sudo apt install qemu-utils parted")
        print("For Windows/NTFS: sudo apt install ntfs-3g")
        print("For GUI operations: sudo apt install gparted")
        print("For ext filesystems: sudo apt install e2fsprogs")
        sys.exit(1)
    
    if optional_missing:
        print(f"Optional tools missing: {', '.join(optional_missing)}")
        print("For full functionality, install:")
        print("Ubuntu/Debian: sudo apt install ntfs-3g gparted e2fsprogs")
        print()
    
    # Launch GUI
    root = tk.Tk()
    app = QCow2ResizerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()