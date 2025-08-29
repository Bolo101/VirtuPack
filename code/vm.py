import subprocess
import os
import json
import time
import select
import re
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


def parse_qemu_progress(line: str) -> float:
    """
    Parse qemu-img progress output and return percentage
    qemu-img -p outputs lines like: (45.67/100%)\r
    """
    try:
        # Look for pattern like (XX.XX/100%) or (XX/100%)
        match = re.search(r'\((\d+(?:\.\d+)?)/100%\)', line)
        if match:
            return float(match.group(1))
        
        # Alternative pattern: (XX.XX%)
        match = re.search(r'\((\d+(?:\.\d+)?)%\)', line)
        if match:
            return float(match.group(1))
            
        # Look for standalone percentage: XX.XX%
        match = re.search(r'(\d+(?:\.\d+)?)%', line)
        if match:
            return float(match.group(1))
            
    except (ValueError, AttributeError):
        pass
    
    return None


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
            progress_callback(0, "Initializing conversion...")
        
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
        
        # Run qemu-img convert with proper progress monitoring
        process = subprocess.Popen(qemu_convert_cmd, 
                                 stderr=subprocess.PIPE, 
                                 stdout=subprocess.PIPE, 
                                 text=True, 
                                 bufsize=0,  # Unbuffered for real-time output
                                 universal_newlines=True)
        
        last_progress = 0
        progress_buffer = ""
        
        while process.poll() is None:
            if stop_flag and stop_flag():
                process.terminate()
                process.wait()
                # Clean up files
                for temp_file in [temp_qcow2_path]:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                raise KeyboardInterrupt("Operation cancelled by user")
            
            # Check for available output from stderr (where qemu-img sends progress)
            if process.stderr:
                try:
                    # Use select to check if data is available (Unix/Linux)
                    if hasattr(select, 'select'):
                        ready, _, _ = select.select([process.stderr], [], [], 0.1)
                        if ready:
                            # Read available data
                            char = process.stderr.read(1)
                            if char:
                                progress_buffer += char
                                
                                # Process complete lines or carriage return updates
                                if char == '\n' or char == '\r':
                                    if progress_buffer.strip():
                                        # Try to parse progress from the buffer
                                        parsed_progress = parse_qemu_progress(progress_buffer)
                                        
                                        if parsed_progress is not None:
                                            # Scale progress: 0-95% for conversion, 95-100% for finalization
                                            scaled_progress = int(parsed_progress * 0.95)
                                            
                                            if scaled_progress > last_progress:
                                                last_progress = scaled_progress
                                                if progress_callback:
                                                    progress_callback(scaled_progress, f"Converting disk data... {parsed_progress:.1f}%")
                                        
                                        # Log significant progress milestones
                                        if parsed_progress and parsed_progress % 10 < 1:  # Every ~10%
                                            log_info(f"Conversion progress: {parsed_progress:.1f}%")
                                    
                                    progress_buffer = ""
                    else:
                        # Fallback for systems without select (Windows)
                        time.sleep(0.5)
                        if progress_callback and last_progress == 0:
                            # Provide generic progress updates
                            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
                            estimated_progress = min(50, elapsed_time / 10)  # Rough estimate
                            progress_callback(estimated_progress, "Converting disk data...")
                            
                except (OSError, IOError, ValueError):
                    # Handle any errors in progress reading
                    pass
            
            # Provide fallback progress updates if no progress parsed yet
            if progress_callback and last_progress == 0:
                if 'fallback_progress' not in locals():
                    fallback_progress = 10
                    start_time = time.time()
                else:
                    # Increment fallback progress slowly
                    elapsed = time.time() - start_time
                    fallback_progress = min(50, 10 + (elapsed / 20))  # Slow increase
                
                progress_callback(fallback_progress, "Converting disk data...")
            
            time.sleep(0.1)  # Short sleep to prevent excessive CPU usage
        
        # Wait for process to complete and capture any remaining output
        stdout, stderr = process.communicate()
        
        # Process any remaining progress in stderr
        if stderr:
            for line in stderr.split('\n'):
                if line.strip():
                    parsed_progress = parse_qemu_progress(line)
                    if parsed_progress is not None and parsed_progress > last_progress:
                        last_progress = int(parsed_progress * 0.95)
                        if progress_callback:
                            progress_callback(last_progress, f"Converting disk data... {parsed_progress:.1f}%")
        
        if process.returncode != 0:
            # Clean up on failure
            if os.path.exists(temp_qcow2_path):
                os.remove(temp_qcow2_path)
            error_msg = f"qemu-img convert failed with return code {process.returncode}"
            if stderr:
                # Filter out progress lines from error message
                error_lines = []
                for line in stderr.split('\n'):
                    if line.strip() and not re.search(r'\d+(?:\.\d+)?%', line):
                        error_lines.append(line)
                if error_lines:
                    error_msg += f"\nError output: {chr(10).join(error_lines)}"
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
        if progress_callback:
            progress_callback(98, "Verifying VM image...")
        
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