import subprocess
import sys
import os
import json
import time
from log_handler import log_error, log_info
from utils import (
    format_bytes, 
    get_disk_info, 
    get_directory_space,
    get_disk_usage_info
)


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
        message += f"Status: {'Sufficient space' if has_space else 'Insufficient space'}"
        
        return has_space, message
        
    except Exception as e:
        return False, f"Error checking space: {str(e)}"


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