#!/usr/bin/env python3
"""
Virtual Disk Image Format Converter
Convert between QCOW2, VHD, VHDX, VMDK, and OVF formats
Integrated with QCOW2 Clone Resizer
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import subprocess
import threading
import json
import time
from pathlib import Path
from QCow2CloneResizer import QCow2CloneResizer


class ImageFormatConverter:
    """GUI for converting virtual disk images between formats"""

    FORMATS = {
        'qcow2': {
            'name': 'QCOW2',
            'description': 'QEMU Copy-On-Write v2 (KVM/QEMU)',
            'extension': '.qcow2',
            'supports_compression': True
        },
        'vdi': {
            'name': 'VDI',
            'description': 'VirtualBox Disk Image',
            'extension': '.vdi',
            'supports_compression': False
        },
        'vhdx': {
            'name': 'VHDX',
            'description': 'Hyper-V Virtual Hard Disk v2',
            'extension': '.vhdx',
            'supports_compression': False
        },
        'vmdk': {
            'name': 'VMDK',
            'description': 'VMware Virtual Machine Disk',
            'extension': '.vmdk',
            'supports_compression': False
        },
        'vpc': {
            'name': 'VHD',
            'description': 'Virtual Hard Disk (Hyper-V/VirtualBox)',
            'extension': '.vhd',
            'supports_compression': False
        },
        'raw': {
            'name': 'RAW',
            'description': 'Raw disk image (dd format)',
            'extension': '.img',
            'supports_compression': False
        }
    }

    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.root.title("Virtual Disk Image Format Converter")
        self.root.geometry("950x900")
        self.root.minsize(850, 700)
        self.root.transient(parent)

        self.image_path = tk.StringVar()
        self.image_info = None
        self.detected_format = None
        self.operation_active = False

        self.target_format = tk.StringVar(value='qcow2')
        self.compress_option = tk.BooleanVar(value=False)

        self.dialog_result_event = threading.Event()
        self.dialog_result_value = None

        self.setup_ui()
        self.check_prerequisites()

        self.root.protocol("WM_DELETE_WINDOW", self.close_window)

    def close_window(self):
        """Handle window close event"""
        if self.operation_active:
            result = messagebox.askyesno(
                "Operation in Progress",
                "A conversion operation is currently running. Stop and close?"
            )
            if not result:
                return
        self.root.destroy()

    def _show_message_and_wait(self, title, message):
        """Show info message and wait for user to click OK"""
        self.dialog_result_event.clear()
        self.dialog_result_value = None

        def show_dialog():
            messagebox.showinfo(title, message)
            self.dialog_result_event.set()

        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()

    def _show_error_and_wait(self, title, message):
        """Show error message and wait for user to click OK"""
        self.dialog_result_event.clear()
        self.dialog_result_value = None

        def show_dialog():
            messagebox.showerror(title, message)
            self.dialog_result_event.set()

        self.root.after(0, show_dialog)
        self.dialog_result_event.wait()

    def setup_ui(self):
        """Setup user interface using the compact ciphering window layout"""
        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.pack(fill="both", expand=True)
        main_frame.grid_rowconfigure(6, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        title = ttk.Label(
            header_frame,
            text="Virtual Disk Image Format Converter",
            font=("Arial", 14, "bold")
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            header_frame,
            text="Convert between QCOW2, VHD, VHDX, VMDK, VDI, and RAW formats",
            font=("Arial", 9)
        )
        subtitle.pack(anchor="w")

        file_frame = ttk.LabelFrame(main_frame, text="Source Image File", padding="8")
        file_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        file_frame.columnconfigure(0, weight=1)

        path_frame = ttk.Frame(file_frame)
        path_frame.grid(row=0, column=0, sticky="ew")
        path_frame.columnconfigure(0, weight=1)

        self.path_entry = ttk.Entry(
            path_frame,
            textvariable=self.image_path,
            font=("Arial", 9)
        )
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        path_button_frame = ttk.Frame(path_frame)
        path_button_frame.grid(row=0, column=1)

        ttk.Button(
            path_button_frame,
            text="Browse",
            command=self.browse_file,
            width=10
        ).pack(side="left", padx=(0, 3))

        ttk.Button(
            path_button_frame,
            text="Analyze",
            command=self.analyze_image,
            width=10
        ).pack(side="left")

        info_frame = ttk.LabelFrame(main_frame, text="Image Information", padding="8")
        info_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(0, weight=1)

        self.info_text = tk.Text(
            info_frame,
            height=6,
            state="disabled",
            wrap="word",
            font=("Consolas", 8),
            bg="white"
        )
        self.info_text.grid(row=0, column=0, sticky="nsew")

        info_scrollbar = ttk.Scrollbar(
            info_frame,
            orient="vertical",
            command=self.info_text.yview
        )
        info_scrollbar.grid(row=0, column=1, sticky="ns")
        self.info_text.configure(yscrollcommand=info_scrollbar.set)

        format_frame = ttk.LabelFrame(main_frame, text="Target Format", padding="8")
        format_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        format_frame.columnconfigure(0, weight=1)
        format_frame.columnconfigure(1, weight=1)

        self.format_radios = {}
        formats_list = list(self.FORMATS.items())
        mid_point = (len(formats_list) + 1) // 2
        left_col = ttk.Frame(format_frame)
        left_col.grid(row=0, column=0, sticky="nw", padx=(0, 12))
        right_col = ttk.Frame(format_frame)
        right_col.grid(row=0, column=1, sticky="nw")

        for idx, (fmt_key, fmt_info) in enumerate(formats_list):
            parent_col = left_col if idx < mid_point else right_col
            radio = ttk.Radiobutton(
                parent_col,
                text=f"{fmt_info['name']} - {fmt_info['description']}",
                variable=self.target_format,
                value=fmt_key,
                command=self.on_format_changed
            )
            radio.pack(anchor="w", pady=1)
            self.format_radios[fmt_key] = radio

        self.compress_check = ttk.Checkbutton(
            format_frame,
            text="Enable compression (QCOW2 only)",
            variable=self.compress_option,
            state="disabled"
        )
        self.compress_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.prereq_frame = ttk.LabelFrame(main_frame, text="System Status", padding="8")
        self.prereq_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        self.prereq_label = ttk.Label(
            self.prereq_frame,
            text="Checking required tools...",
            font=("Arial", 8)
        )
        self.prereq_label.pack()

        progress_frame = ttk.LabelFrame(main_frame, text="Conversion Progress", padding="8")
        progress_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        progress_frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.progress_label = ttk.Label(
            progress_frame,
            text="Ready to convert",
            font=("Arial", 9, "bold")
        )
        self.progress_label.grid(row=1, column=0, sticky="w")

        button_container = ttk.Frame(main_frame)
        button_container.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        button_container.columnconfigure(0, weight=1)

        self.convert_btn = ttk.Button(
            button_container,
            text="START CONVERSION",
            command=self.start_conversion,
            state="disabled",
            style="Accent.TButton"
        )
        self.convert_btn.grid(row=0, column=0, sticky="ew", pady=(0, 6), ipady=5)

        secondary_frame = ttk.Frame(button_container)
        secondary_frame.grid(row=1, column=0, sticky="ew")
        secondary_frame.columnconfigure(1, weight=1)

        ttk.Button(
            secondary_frame,
            text="Refresh",
            command=self.analyze_image,
            width=12
        ).grid(row=0, column=0, padx=(0, 6))

        ttk.Button(
            secondary_frame,
            text="Close",
            command=self.close_window,
            width=12
        ).grid(row=0, column=2, sticky="e")

        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=7, column=0, sticky="ew")

        separator = ttk.Separator(status_frame, orient="horizontal")
        separator.pack(fill="x", pady=(6, 4))

        self.status_label = ttk.Label(
            status_frame,
            text="Ready - Select source image file to begin",
            font=("Arial", 8)
        )
        self.status_label.pack()

        self.setup_styles()

    def setup_styles(self):
        style = ttk.Style()
        style.configure("Accent.TButton", font=("Arial", 12, "bold"), padding=(20, 10))

    def check_prerequisites(self):
        qemu_img_available = self._check_command('qemu-img')
        text = ""
        if not qemu_img_available:
            text = "Missing required tool: qemu-img\n\n"
            text += "Install qemu-img:\n"
            text += "Ubuntu/Debian: sudo apt install qemu-utils\n"
            text += "Fedora/RHEL: sudo dnf install qemu-img\n"
            text += "Arch Linux: sudo pacman -S qemu\n"
            self.prereq_label.config(text=text, foreground="red")
            messagebox.showerror(
                "Missing Required Tool",
                "qemu-img is required for image format conversion.\n\n"
                "Please install qemu-utils package."
            )
        else:
            text = "✓ qemu-img available - All formats supported\n"
            vboxmanage = self._check_command('VBoxManage')
            if vboxmanage:
                text += "✓ VBoxManage available - Enhanced VDI support\n"
            self.prereq_label.config(text=text, foreground="green")

    def _check_command(self, command):
        try:
            subprocess.run(
                [command, '--version'],
                capture_output=True,
                timeout=5,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Virtual Disk Image File",
            filetypes=[
                ("All supported formats", "*.qcow2 *.vdi *.vhd *.vhdx *.vmdk *.img *.raw"),
                ("QCOW2 files", "*.qcow2"),
                ("VDI files", "*.vdi"),
                ("VHD files", "*.vhd"),
                ("VHDX files", "*.vhdx"),
                ("VMDK files", "*.vmdk"),
                ("RAW images", "*.img *.raw"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.image_path.set(file_path)
            self.analyze_image()

    def analyze_image(self):
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("No File Selected", "Please select an image file first")
            return
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", "The selected file does not exist")
            return
        try:
            self.update_progress(True, "Analyzing image file...")
            self.image_info = QCow2CloneResizer.get_image_info(path)
            self.detected_format = self.image_info['format']
            self.display_image_info()
            self.convert_btn.config(state="normal")
            self.update_progress(False, "Analysis complete - Ready for conversion")
            self.status_label.config(text=f"Image analyzed - Detected format: {self.detected_format.upper()}")
        except FileNotFoundError:
            messagebox.showerror("File Not Found", f"Image file not found: {path}")
            self.update_progress(False, "Analysis failed - file not found")
        except PermissionError:
            messagebox.showerror("Permission Denied", f"Permission denied accessing image file: {path}")
            self.update_progress(False, "Analysis failed - permission denied")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Command Failed", f"qemu-img analysis failed:\n\n{e}")
            self.update_progress(False, "Analysis failed - command error")
        except json.JSONDecodeError:
            messagebox.showerror("Parse Error", "Failed to parse image analysis results")
            self.update_progress(False, "Analysis failed - parse error")
        except OSError as e:
            messagebox.showerror("System Error", f"System error during image analysis:\n\n{e}")
            self.update_progress(False, "Analysis failed - system error")

    def display_image_info(self):
        if not self.image_info:
            return
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, "end")
        info = f"SOURCE IMAGE INFORMATION\n"
        info += f"{'='*50}\n"
        info += f"Path: {self.image_path.get()}\n"
        info += f"Name: {os.path.basename(self.image_path.get())}\n"
        info += f"Detected Format: {self.image_info['format'].upper()}\n\n"
        info += f"SIZE INFORMATION\n"
        info += f"{'='*50}\n"
        info += f"Virtual Size: {QCow2CloneResizer.format_size(self.image_info['virtual_size'])}\n"
        info += f"File Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n"
        if self.image_info['virtual_size'] > 0:
            ratio = self.image_info['actual_size'] / self.image_info['virtual_size']
            info += f"Usage: {ratio*100:.1f}% of virtual size\n"
        info += f"\nCONVERSION NOTES:\n"
        info += f"{'='*50}\n"
        info += f"• Select target format from the options above\n"
        info += f"• Conversion preserves virtual disk size\n"
        info += f"• Actual file size may vary by format\n"
        info += f"• Original file will not be modified\n"
        info += f"• Ensure VM is shut down before conversion\n"
        self.info_text.insert(1.0, info)
        self.info_text.config(state="disabled")

    def on_format_changed(self):
        selected = self.target_format.get()
        if self.FORMATS[selected]['supports_compression']:
            self.compress_check.config(state="normal")
        else:
            self.compress_check.config(state="disabled")
            self.compress_option.set(False)

    def start_conversion(self):
        if not self.validate_inputs():
            return
        source_path = self.image_path.get()
        target_format = self.target_format.get()
        source_format = self.detected_format
        if source_format == target_format:
            result = messagebox.askyesno(
                "Same Format Detected",
                f"Source and target formats are both {source_format.upper()}.\n\n"
                f"This will create a copy of the image.\n\n"
                f"Continue?"
            )
            if not result:
                return
        source_file = Path(source_path)
        target_extension = self.FORMATS[target_format]['extension']
        target_path = source_file.parent / f"{source_file.stem}_converted{target_extension}"
        if target_path.exists():
            result = messagebox.askyesno(
                "File Exists",
                f"Target file already exists:\n{target_path}\n\n"
                f"Overwrite?"
            )
            if not result:
                return
        msg = f"IMAGE FORMAT CONVERSION\n\n"
        msg += f"Source:\n"
        msg += f" File: {os.path.basename(source_path)}\n"
        msg += f" Format: {source_format.upper()}\n"
        msg += f" Size: {QCow2CloneResizer.format_size(self.image_info['actual_size'])}\n\n"
        msg += f"Target:\n"
        msg += f" File: {target_path.name}\n"
        msg += f" Format: {target_format.upper()}\n"
        msg += f" Description: {self.FORMATS[target_format]['description']}\n"
        if self.compress_option.get():
            msg += f" Compression: ENABLED\n"
        msg += f"\nIMPORTANT:\n"
        msg += f"• Virtual machine MUST be completely shut down\n"
        msg += f"• Conversion time depends on image size\n"
        msg += f"• Original file will NOT be modified\n"
        msg += f"• Target file will be created: {target_path.name}\n\n"
        msg += f"Continue with conversion?"
        if not messagebox.askyesno("Confirm Conversion", msg):
            return
        self.operation_active = True
        self.convert_btn.config(state="disabled")
        self.status_label.config(text="Conversion in progress...")
        thread = threading.Thread(target=self._conversion_worker, args=(source_path, str(target_path), target_format))
        thread.daemon = True
        thread.start()

    def _conversion_worker(self, source_path, target_path, target_format):
        try:
            self.update_progress(True, f"Converting to {target_format.upper()}...")
            cmd = ['qemu-img', 'convert', '-O', target_format, '-p']
            if self.compress_option.get() and self.FORMATS[target_format]['supports_compression']:
                cmd.extend(['-c'])
            cmd.extend([source_path, target_path])
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
            for line in process.stdout:
                line = line.strip()
                if line:
                    if '%' in line or '/' in line:
                        self.update_progress(True, f"Converting: {line}")
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd, "Conversion failed")
            if not os.path.exists(target_path):
                raise FileNotFoundError(f"Target file was not created: {target_path}")
            target_size = os.path.getsize(target_path)
            if target_size < 1024:
                raise ValueError(f"Target file is too small: {target_size} bytes")
            target_info = QCow2CloneResizer.get_image_info(target_path)
            self._show_conversion_complete(source_path, target_path, target_info, target_size)
        except FileNotFoundError as e:
            self._show_error_and_wait("File Not Found", f"Conversion failed - file not found:\n\n{e}")
        except PermissionError as e:
            self._show_error_and_wait("Permission Denied", f"Conversion failed - permission denied:\n\n{e}\n\nCheck file permissions and available disk space.")
        except subprocess.CalledProcessError as e:
            self._show_error_and_wait("Conversion Failed", f"qemu-img conversion failed:\n\n{e}\n\nCheck that the source image is not corrupted.")
        except ValueError as e:
            self._show_error_and_wait("Invalid Value", f"Conversion failed - invalid value:\n\n{e}")
        except OSError as e:
            self._show_error_and_wait("System Error", f"Conversion failed - system error:\n\n{e}\n\nCheck available disk space and system resources.")
        except Exception as e:
            self._show_error_and_wait("Unexpected Error", f"Conversion failed with unexpected error:\n\n{e}")
        finally:
            self.root.after(0, self.reset_ui)

    def _show_conversion_complete(self, source_path, target_path, target_info, target_size):
        try:
            source_size = self.image_info['actual_size']
            source_format = self.image_info['format']
            target_format = target_info['format']
            msg = f"CONVERSION COMPLETED SUCCESSFULLY!\n\n"
            msg += f"SOURCE IMAGE:\n"
            msg += f"{'='*50}\n"
            msg += f"File: {os.path.basename(source_path)}\n"
            msg += f"Format: {source_format.upper()}\n"
            msg += f"Size: {QCow2CloneResizer.format_size(source_size)}\n\n"
            msg += f"TARGET IMAGE:\n"
            msg += f"{'='*50}\n"
            msg += f"File: {os.path.basename(target_path)}\n"
            msg += f"Format: {target_format.upper()}\n"
            msg += f"Virtual Size: {QCow2CloneResizer.format_size(target_info['virtual_size'])}\n"
            msg += f"File Size: {QCow2CloneResizer.format_size(target_size)}\n\n"
            if target_size < source_size:
                saved = source_size - target_size
                ratio = saved / source_size * 100
                msg += f"✓ Space saved: {QCow2CloneResizer.format_size(saved)} ({ratio:.1f}% smaller)\n"
            elif target_size > source_size:
                added = target_size - source_size
                ratio = added / source_size * 100
                msg += f"⚠ File larger: {QCow2CloneResizer.format_size(added)} ({ratio:.1f}% bigger)\n"
            else:
                msg += f"✓ File size unchanged\n"
            msg += f"\n✓ Virtual disk size preserved\n"
            msg += f"✓ Original file untouched\n"
            msg += f"✓ Ready for use in virtual machine\n\n"
            msg += f"Location: {target_path}"
            self._show_message_and_wait("Conversion Complete", msg)
        except KeyError:
            self._show_message_and_wait("Conversion Complete", f"Image conversion completed successfully!\n\nTarget file: {target_path}")

    def validate_inputs(self):
        path = self.image_path.get().strip()
        if not path:
            messagebox.showwarning("No File Selected", "Please select an image file first")
            return False
        if not os.path.exists(path):
            messagebox.showerror("File Not Found", "The selected file does not exist")
            return False
        if not self.image_info:
            messagebox.showwarning("Image Not Analyzed", "Please analyze the image first by clicking 'Analyze'")
            return False
        target_format = self.target_format.get()
        if not target_format or target_format not in self.FORMATS:
            messagebox.showwarning("No Format Selected", "Please select a target format")
            return False
        return True

    def update_progress(self, active, status):
        def update():
            if active:
                self.progress.start(10)
            else:
                self.progress.stop()
            self.progress_label.config(text=status)
            if not active:
                self.status_label.config(text="Ready - Select image to begin")
            else:
                self.status_label.config(text=f"Operation in progress: {status}")
        self.root.after(0, update)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def reset_ui(self):
        self.operation_active = False
        self.convert_btn.config(state="normal")
        self.progress.stop()
        self.progress_label.config(text="Operation completed")
        self.status_label.config(text="Operation completed - Ready for next conversion")