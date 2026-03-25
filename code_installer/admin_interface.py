"""
admin_interface.py – Password-protected administration panel for the P2V Converter.

Features:
  • Conversion counter (total virtualised machines)
  • PDF export: session report / complete logs → external storage
  • Raw log export (all rotated files) → external storage
  • Log purge
  • Admin password change
  • Power off / Reboot
  • Exit to OS
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from typing import List

from config_manager import (change_password, is_password_set,
                             set_password, verify_password)
from log_handler import (generate_log_file_pdf, generate_session_pdf,
                          get_all_log_files, log_error, log_info,
                          log_application_exit, purge_logs,
                          session_end, is_session_active)
from stats_manager import get_conversion_count


# ── Password dialog ────────────────────────────────────────────────────────────

class PasswordDialog(tk.Toplevel):
    """Modal password entry dialog."""

    def __init__(self, parent: tk.Widget, title: str = "Authentication") -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.result: str | None = None

        ttk.Label(self, text="Administrator password:",
                  font=("Arial", 11)).pack(padx=20, pady=(16, 4))
        self._entry = ttk.Entry(self, show="•", width=28, font=("Arial", 11))
        self._entry.pack(padx=20, pady=4)
        self._entry.bind("<Return>", lambda _: self._ok())
        self._entry.focus_set()

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="OK",     command=self._ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=6)

        self._center(parent)
        self.wait_window()

    def _center(self, parent: tk.Widget) -> None:
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

    def _ok(self) -> None:
        self.result = self._entry.get()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


# ── First-run password setup ───────────────────────────────────────────────────

def prompt_initial_password(parent: tk.Widget) -> None:
    """
    Displayed on first launch: forces creation of the admin password.
    Loops until a valid password is set.
    """
    while True:
        win = tk.Toplevel(parent)
        win.title("Initial Setup – Administrator Password")
        win.resizable(False, False)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", lambda: None)   # non-closeable

        ttk.Label(win,
                  text="Set the administrator password.",
                  font=("Arial", 11, "bold")).pack(padx=20, pady=(14, 6))
        ttk.Label(win,
                  text="This password protects the administration panel\n"
                       "(log export, system shutdown, etc.)",
                  justify=tk.LEFT).pack(padx=20)

        fields: dict[str, ttk.Entry] = {}
        for label in ("Password:", "Confirm:"):
            ttk.Label(win, text=label).pack(anchor="w", padx=20, pady=(6, 0))
            e = ttk.Entry(win, show="•", width=28)
            e.pack(padx=20, pady=2)
            fields[label] = e

        err_var = tk.StringVar()
        ttk.Label(win, textvariable=err_var, foreground="red").pack(pady=2)

        submitted: list[bool] = [False]

        def on_submit() -> None:
            pw  = fields["Password:"].get()
            pw2 = fields["Confirm:"].get()
            if len(pw) < 8:
                err_var.set("Password must be at least 8 characters.")
                return
            if pw != pw2:
                err_var.set("Passwords do not match.")
                return
            try:
                set_password(pw)
                submitted[0] = True
                win.destroy()
            except Exception as exc:
                err_var.set(f"Error: {exc}")

        ttk.Button(win, text="Set Password", command=on_submit).pack(pady=10)
        win.wait_window()

        if submitted[0]:
            log_info("Administrator password set successfully.")
            break


# ── External-storage helpers ───────────────────────────────────────────────────

def _get_external_disks() -> list:
    """
    Return non-system, non-loop block devices visible to lsblk.
    Each entry: {device, path, size, model, partitions, mount_points}.
    """
    result = []
    try:
        raw  = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MODEL,MOUNTPOINT"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ).stdout.decode()
        data = json.loads(raw)
    except Exception as e:
        log_error(f"lsblk JSON failed: {e}")
        return result

    # Detect system disk
    system_disk = ""
    try:
        from utils import is_system_disk as _isd
        _isd_fn = _isd
    except ImportError:
        _isd_fn = None

    for dev in data.get("blockdevices", []):
        dev_name = dev.get("name", "")
        dev_type = dev.get("type", "")
        if dev_type != "disk":
            continue
        if dev_name.startswith("loop"):
            continue
        if _isd_fn and _isd_fn(f"/dev/{dev_name}"):
            continue

        partitions: List[str] = []
        mount_map: dict       = {}
        for child in (dev.get("children") or []):
            if child.get("type") == "part":
                pname = child["name"]
                partitions.append(pname)
                mount_map[pname] = child.get("mountpoint") or None
        if not partitions:
            partitions.append(dev_name)
            mount_map[dev_name] = dev.get("mountpoint") or None

        result.append({
            "device":       dev_name,
            "path":         f"/dev/{dev_name}",
            "size":         dev.get("size", "?"),
            "model":        (dev.get("model") or "").strip(),
            "partitions":   partitions,
            "mount_points": mount_map,
        })
    return result


def _mount_partition(partition: str) -> str | None:
    """Mount /dev/<partition> to a temp dir. Returns mount point or None."""
    mount_dir = tempfile.mkdtemp(prefix="p2v_admin_export_")
    try:
        r = subprocess.run(
            ["mount", f"/dev/{partition}", mount_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if r.returncode != 0:
            log_error(f"mount /dev/{partition} -> {mount_dir} failed: "
                      f"{r.stderr.decode().strip()}")
            try:
                os.rmdir(mount_dir)
            except OSError:
                pass
            return None
        log_info(f"Mounted /dev/{partition} at {mount_dir}")
        return mount_dir
    except Exception as e:
        log_error(f"Unexpected error mounting /dev/{partition}: {e}")
        return None


def _unmount_partition(mount_dir: str) -> None:
    """Unmount and remove the temp mount directory."""
    try:
        r = subprocess.run(["umount", mount_dir],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            log_error(f"umount {mount_dir} failed: {r.stderr.decode().strip()}")
        else:
            log_info(f"Unmounted {mount_dir}")
    except Exception as e:
        log_error(f"Error during umount {mount_dir}: {e}")
    finally:
        try:
            os.rmdir(mount_dir)
        except OSError:
            pass


def _show_disk_picker(parent: tk.Widget, external_disks: list):
    """
    Modal dialog to pick one partition.
    Returns (partition_name, already_mounted, existing_mount_point)
    or (None, False, None) if cancelled.
    """
    result = {"partition": None, "already_mounted": False, "mount_point": None}

    dlg = tk.Toplevel(parent)
    dlg.title("Select External Storage")
    dlg.grab_set()
    dlg.resizable(False, False)

    ttk.Label(dlg,
              text="Choose the external storage for export",
              font=("Arial", 11, "bold"),
              padding=(10, 10)).pack(fill=tk.X)
    ttk.Label(dlg,
              text="Only non-system disks are listed.\n"
                   "The device will be mounted automatically if needed.",
              foreground="#555555",
              padding=(10, 0, 10, 6)).pack(fill=tk.X)

    frame = ttk.Frame(dlg, padding=(10, 0, 10, 6))
    frame.pack(fill=tk.BOTH, expand=True)

    lb = tk.Listbox(frame, width=70, height=12, font=("Courier", 9),
                    selectmode=tk.SINGLE, activestyle="dotbox")
    sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    entries = []
    for disk in external_disks:
        model_str = f" [{disk['model']}]" if disk['model'] else ""
        lb.insert(tk.END, f"── {disk['path']}  {disk['size']}{model_str}")
        lb.itemconfig(tk.END, foreground="#333388", background="#eeeeff")
        entries.append(None)
        for part in disk["partitions"]:
            mp     = disk["mount_points"].get(part)
            status = f"mounted at {mp}" if mp else "not mounted"
            lb.insert(tk.END, f"     /dev/{part:<14}  {status}")
            entries.append((part, mp is not None, mp))

    btn_frame = ttk.Frame(dlg, padding=(10, 6))
    btn_frame.pack(fill=tk.X)

    def on_select():
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("No Selection",
                                   "Please select a partition.",
                                   parent=dlg)
            return
        entry = entries[sel[0]]
        if entry is None:
            messagebox.showwarning("Invalid Selection",
                                   "Please select a partition, not a disk header.",
                                   parent=dlg)
            return
        result.update({"partition": entry[0],
                        "already_mounted": entry[1],
                        "mount_point": entry[2]})
        dlg.destroy()

    ttk.Button(btn_frame, text="Select",  command=on_select).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_frame, text="Cancel",  command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    dlg.update_idletasks()
    w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width()  - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    dlg.geometry(f"+{x}+{y}")
    parent.wait_window(dlg)

    return result["partition"], result["already_mounted"], result["mount_point"]


def _request_external_export_path(parent: tk.Widget,
                                  default_filename: str,
                                  status_callback=None) -> tuple[str | None, str | None]:
    """
    Full export-path workflow: detect → pick → mount → save-as dialog.

    Returns (chosen_path, mount_dir_to_unmount_after_write)
    or       (None, None) if cancelled / error.
    The caller must call _unmount_partition(mount_dir) after the file is written.
    """
    def _status(msg: str) -> None:
        if status_callback:
            status_callback(msg)

    external_disks = _get_external_disks()
    if not external_disks:
        messagebox.showerror(
            "No External Storage Detected",
            "No external disk was found.\n\n"
            "Connect a USB drive or external disk and try again.",
            parent=parent
        )
        return None, None

    partition, already_mounted, existing_mp = _show_disk_picker(parent, external_disks)
    if not partition:
        return None, None

    pending_unmount = None
    if already_mounted and existing_mp:
        mount_point = existing_mp
    else:
        _status(f"Mounting /dev/{partition}…")
        mount_point = _mount_partition(partition)
        if not mount_point:
            messagebox.showerror(
                "Mount Error",
                f"Could not mount /dev/{partition}.\n\n"
                "Check that the device is properly connected.",
                parent=parent
            )
            return None, None
        pending_unmount = mount_point

    chosen_path = filedialog.asksaveasfilename(
        title="Export to External Storage",
        initialdir=mount_point,
        initialfile=default_filename,
        defaultextension=os.path.splitext(default_filename)[1] or "",
        filetypes=[("All files", "*.*")],
        parent=parent,
    )

    if not chosen_path:
        if pending_unmount:
            _unmount_partition(pending_unmount)
        return None, None

    # Validate destination is on the external mount
    mp_norm   = mount_point.rstrip("/") + "/"
    path_norm = os.path.abspath(chosen_path).rstrip("/") + "/"
    if not path_norm.startswith(mp_norm):
        messagebox.showwarning(
            "Invalid Destination",
            f"The chosen path is not on the external storage.\n"
            f"Please choose a location under: {mount_point}",
            parent=parent
        )
        if pending_unmount:
            _unmount_partition(pending_unmount)
        return None, None

    return chosen_path, pending_unmount


# ── Log file selection dialog ─────────────────────────────────────────────────

class LogFileSelectionDialog(tk.Toplevel):
    """
    Modal dialog that lists all available log files with individual checkboxes
    and Select All / Deselect All convenience buttons.

    Usage:
        dlg = LogFileSelectionDialog(parent, log_files)
        # dlg.selected_files is a list of paths chosen by the user,
        # or None if the dialog was cancelled.
    """

    def __init__(self, parent: tk.Widget, log_files: List[str]) -> None:
        super().__init__(parent)
        self.title("Select Log Files to Export")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.selected_files: List[str] | None = None
        self._log_files = log_files
        self._vars: List[tk.BooleanVar] = []

        self._build_ui()
        self._center(parent)
        self.wait_window()

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        ttk.Label(self,
                  text="Choose the files to copy to the external storage:",
                  font=("Arial", 10, "bold"),
                  padding=(12, 10, 12, 4)).pack(fill=tk.X)

        # ── Select All / Deselect All ──
        ctrl_frame = ttk.Frame(self, padding=(12, 0, 12, 6))
        ctrl_frame.pack(fill=tk.X)
        ttk.Button(ctrl_frame, text="Select All",
                   command=self._select_all, width=16).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(ctrl_frame, text="Deselect All",
                   command=self._deselect_all, width=16).pack(side=tk.LEFT)

        # ── File list with checkboxes ──
        list_outer = ttk.Frame(self, padding=(10, 0, 10, 6))
        list_outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(list_outer, width=520, height=min(240, len(self._log_files) * 28 + 10),
                           highlightthickness=0)
        sb = ttk.Scrollbar(list_outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)

        # Mouse-wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.protocol("WM_DELETE_WINDOW", lambda: (
            canvas.unbind_all("<MouseWheel>"), self._cancel()))

        for path in self._log_files:
            var = tk.BooleanVar(value=True)   # all selected by default
            self._vars.append(var)

            row = ttk.Frame(inner)
            row.pack(fill=tk.X, padx=4, pady=1)

            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)

            # File info: name + size + mtime
            name = os.path.basename(path)
            try:
                stat   = os.stat(path)
                size   = _human_size(stat.st_size)
                mtime  = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                label  = f"{name:<40}  {size:>8}   {mtime}"
            except OSError:
                label  = f"{name}  (unreadable)"

            ttk.Label(row, text=label, font=("Courier", 9)).pack(side=tk.LEFT, padx=(4, 0))

        # ── Counter label ──
        self._count_var = tk.StringVar()
        self._update_count()
        for v in self._vars:
            v.trace_add("write", lambda *_: self._update_count())

        ttk.Label(self, textvariable=self._count_var,
                  foreground="#555555",
                  padding=(12, 0, 12, 4)).pack(fill=tk.X)

        # ── Action buttons ──
        ttk.Separator(self).pack(fill=tk.X, padx=10, pady=4)
        btn_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Export Selected",
                   command=self._confirm, width=18).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel",
                   command=self._cancel, width=12).pack(side=tk.LEFT)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _select_all(self) -> None:
        for v in self._vars:
            v.set(True)

    def _deselect_all(self) -> None:
        for v in self._vars:
            v.set(False)

    def _update_count(self) -> None:
        n = sum(v.get() for v in self._vars)
        self._count_var.set(f"{n} of {len(self._vars)} file(s) selected")

    def _confirm(self) -> None:
        chosen = [p for p, v in zip(self._log_files, self._vars) if v.get()]
        if not chosen:
            messagebox.showwarning("Nothing Selected",
                                   "Please select at least one file.",
                                   parent=self)
            return
        self.selected_files = chosen
        self.destroy()

    def _cancel(self) -> None:
        self.selected_files = None
        self.destroy()

    def _center(self, parent: tk.Widget) -> None:
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")


def _human_size(n: int) -> str:
    """Convert bytes to a short human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── Administration panel ───────────────────────────────────────────────────────

class AdminInterface(tk.Toplevel):
    """Full administration window, opened after successful authentication."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._parent = parent
        self.title("Administration – P2V Converter")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._status_var = tk.StringVar(value="Ready")
        self._build_ui()
        self._refresh_stats()
        self._center()

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # Header
        ttk.Label(self, text="Administration Panel",
                  font=("Arial", 15, "bold"),
                  padding=(0, 10, 0, 4)).pack()

        # ── Stats ──
        stats_frame = ttk.LabelFrame(self, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X, padx=14, pady=6)

        self._count_var = tk.StringVar(value="—")
        ttk.Label(stats_frame, text="Machines virtualised (total):").grid(
            row=0, column=0, sticky="w")
        ttk.Label(stats_frame, textvariable=self._count_var,
                  font=("Arial", 22, "bold"), foreground="#1a6e1a").grid(
            row=0, column=1, padx=12)

        # ── PDF export ──
        pdf_frame = ttk.LabelFrame(self, text="PDF Reports – Export to External Storage",
                                   padding=10)
        pdf_frame.pack(fill=tk.X, padx=14, pady=4)

        ttk.Button(pdf_frame,
                   text="→  Export Session Report (PDF) to USB…",
                   command=self._export_session_pdf,
                   width=46).pack(side=tk.LEFT, padx=6, pady=2)
        ttk.Button(pdf_frame,
                   text="→  Export Complete Log (PDF) to USB…",
                   command=self._export_full_pdf,
                   width=46).pack(side=tk.LEFT, padx=6, pady=2)

        # ── Raw log export ──
        raw_frame = ttk.LabelFrame(self, text="Raw Log Export – External Storage",
                                   padding=10)
        raw_frame.pack(fill=tk.X, padx=14, pady=4)

        ttk.Label(raw_frame,
                  text="Select which log files (current + rotated) to copy to the external device.",
                  foreground="#555555").pack(anchor="w", pady=(0, 6))
        ttk.Button(raw_frame,
                   text="→  Export Raw Logs to USB…",
                   command=self._export_raw_logs,
                   width=38).pack(anchor="w", padx=6)

        # ── Maintenance ──
        maint_frame = ttk.LabelFrame(self, text="Maintenance", padding=10)
        maint_frame.pack(fill=tk.X, padx=14, pady=4)

        ttk.Button(maint_frame,
                   text="×  Purge all logs",
                   command=self._purge_logs,
                   width=26).grid(row=0, column=0, padx=6, pady=4, sticky="w")
        ttk.Button(maint_frame,
                   text="◇  Change admin password",
                   command=self._change_password,
                   width=28).grid(row=0, column=1, padx=6, pady=4, sticky="w")

        # ── System ──
        sys_frame = ttk.LabelFrame(self, text="System", padding=10)
        sys_frame.pack(fill=tk.X, padx=14, pady=4)

        ttk.Button(sys_frame, text="■  Power Off",
                   command=self._shutdown, width=16).grid(
            row=0, column=0, padx=8, pady=4)
        ttk.Button(sys_frame, text="↺  Reboot",
                   command=self._reboot, width=16).grid(
            row=0, column=1, padx=8, pady=4)
        ttk.Button(sys_frame, text="←  Exit to OS",
                   command=self._exit_to_os, width=16).grid(
            row=0, column=2, padx=8, pady=4)

        # ── Status bar ──
        ttk.Separator(self).pack(fill=tk.X, padx=14, pady=6)
        status_bar = ttk.Frame(self)
        status_bar.pack(fill=tk.X, padx=14, pady=(0, 4))
        ttk.Label(status_bar, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_bar, textvariable=self._status_var,
                  foreground="#1a6e1a").pack(side=tk.LEFT, padx=6)
        ttk.Button(self, text="Close Panel",
                   command=self.destroy, width=20).pack(pady=(0, 12))

    # ── Centering ──────────────────────────────────────────────────────────────
    def _center(self) -> None:
        self.update_idletasks()
        px = self._parent.winfo_rootx() + (self._parent.winfo_width()  - self.winfo_width())  // 2
        py = self._parent.winfo_rooty() + (self._parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)
        self.update_idletasks()

    # ── Actions ───────────────────────────────────────────────────────────────
    def _refresh_stats(self) -> None:
        self._count_var.set(str(get_conversion_count()))

    # -- PDF session export ----------------------------------------------------
    def _export_session_pdf(self) -> None:
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"p2v_session_{ts}.pdf"

        chosen_path, to_unmount = _request_external_export_path(
            self, default_name, self._set_status)
        if not chosen_path:
            self._set_status("Export cancelled.")
            return

        try:
            self._set_status("Generating PDF…")
            pdf_path = generate_session_pdf(output_path=chosen_path)
            if to_unmount:
                self._set_status("Unmounting device…")
                _unmount_partition(to_unmount)
            messagebox.showinfo("Export Successful",
                f"Session PDF exported:\n{pdf_path}", parent=self)
            log_info(f"Admin: session PDF exported to external storage: {pdf_path}")
        except ValueError as e:
            messagebox.showwarning("Warning", str(e), parent=self)
        except (PermissionError, OSError) as e:
            messagebox.showerror("Error", f"Could not create PDF:\n{e}", parent=self)
            log_error(f"Admin: session PDF export error: {e}")
        finally:
            self._set_status("Ready")

    # -- PDF full log export ---------------------------------------------------
    def _export_full_pdf(self) -> None:
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"p2v_complete_log_{ts}.pdf"

        chosen_path, to_unmount = _request_external_export_path(
            self, default_name, self._set_status)
        if not chosen_path:
            self._set_status("Export cancelled.")
            return

        try:
            self._set_status("Generating PDF…")
            pdf_path = generate_log_file_pdf(output_path=chosen_path)
            if to_unmount:
                self._set_status("Unmounting device…")
                _unmount_partition(to_unmount)
            messagebox.showinfo("Export Successful",
                f"Complete log PDF exported:\n{pdf_path}", parent=self)
            log_info(f"Admin: complete log PDF exported to external storage: {pdf_path}")
        except ValueError as e:
            messagebox.showwarning("Warning", str(e), parent=self)
        except (PermissionError, OSError) as e:
            messagebox.showerror("Error", f"Could not create PDF:\n{e}", parent=self)
            log_error(f"Admin: complete log PDF export error: {e}")
        finally:
            self._set_status("Ready")

    # -- Raw log export --------------------------------------------------------
    def _export_raw_logs(self) -> None:
        all_log_files = get_all_log_files()
        if not all_log_files:
            messagebox.showwarning("No Logs", "No log files found.", parent=self)
            return

        # ── Step 1: let the user choose which files to export ──
        selector = LogFileSelectionDialog(self, all_log_files)
        log_files = selector.selected_files
        if not log_files:
            self._set_status("Export cancelled.")
            return

        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"p2v_logs_{ts}"   # destination sub-directory name

        # ── Step 2: pick the external device ──
        external_disks = _get_external_disks()
        if not external_disks:
            messagebox.showerror(
                "No External Storage",
                "No external disk was found.\n\n"
                "Connect a USB drive or external disk and try again.",
                parent=self
            )
            return

        partition, already_mounted, existing_mp = _show_disk_picker(self, external_disks)
        if not partition:
            return

        pending_unmount = None
        if already_mounted and existing_mp:
            mount_point = existing_mp
        else:
            self._set_status(f"Mounting /dev/{partition}…")
            mount_point = _mount_partition(partition)
            if not mount_point:
                messagebox.showerror(
                    "Mount Error",
                    f"Could not mount /dev/{partition}.",
                    parent=self
                )
                self._set_status("Ready")
                return
            pending_unmount = mount_point

        # ── Step 3: destination folder on the external device ──
        dest_dir = filedialog.askdirectory(
            title="Choose destination folder on external storage",
            initialdir=mount_point,
            parent=self,
        )
        if not dest_dir:
            if pending_unmount:
                _unmount_partition(pending_unmount)
            self._set_status("Export cancelled.")
            return

        # Validate destination is on the mount point
        mp_norm  = mount_point.rstrip("/") + "/"
        dir_norm = os.path.abspath(dest_dir).rstrip("/") + "/"
        if not dir_norm.startswith(mp_norm):
            messagebox.showwarning(
                "Invalid Destination",
                f"Please choose a folder under: {mount_point}",
                parent=self
            )
            if pending_unmount:
                _unmount_partition(pending_unmount)
            self._set_status("Ready")
            return

        # ── Step 4: copy selected files ──
        export_subdir = os.path.join(dest_dir, default_name)
        try:
            os.makedirs(export_subdir, exist_ok=True)
            copied, errors = 0, []
            for lf in log_files:
                dest_file = os.path.join(export_subdir, os.path.basename(lf))
                self._set_status(f"Copying {os.path.basename(lf)}…")
                try:
                    shutil.copy2(lf, dest_file)
                    copied += 1
                except OSError as e:
                    errors.append(f"{os.path.basename(lf)}: {e}")

            if pending_unmount:
                self._set_status("Unmounting device…")
                _unmount_partition(pending_unmount)
                pending_unmount = None

            summary = f"{copied} of {len(log_files)} file(s) copied to:\n{export_subdir}"
            if errors:
                summary += f"\n\nErrors ({len(errors)}):\n" + "\n".join(errors)
                messagebox.showwarning("Export Completed with Errors", summary, parent=self)
            else:
                messagebox.showinfo("Export Successful", summary, parent=self)
            log_info(f"Admin: {copied} raw log file(s) exported to {export_subdir}")

        except (PermissionError, OSError) as e:
            messagebox.showerror("Export Error", f"Export failed:\n{e}", parent=self)
            log_error(f"Admin: raw log export error: {e}")
        finally:
            if pending_unmount:
                _unmount_partition(pending_unmount)
            self._set_status("Ready")

    # -- Log purge -------------------------------------------------------------
    def _purge_logs(self) -> None:
        if not messagebox.askyesno(
            "Confirm Purge",
            "Delete ALL log files?\n\n"
            "This action is irreversible.\n"
            "Existing PDF reports will NOT be deleted.",
            parent=self,
        ):
            return
        purge_logs()
        messagebox.showinfo("Logs Purged",
                            "All log files have been deleted.", parent=self)

    # -- Password change -------------------------------------------------------
    def _change_password(self) -> None:
        win = tk.Toplevel(self)
        win.title("Change Password")
        win.resizable(False, False)
        win.grab_set()

        fields: dict[str, ttk.Entry] = {}
        for label in ("Current password:", "New password:", "Confirm new:"):
            ttk.Label(win, text=label).pack(anchor="w", padx=20, pady=(8, 0))
            e = ttk.Entry(win, show="•", width=26)
            e.pack(padx=20, pady=2)
            fields[label] = e

        err_var = tk.StringVar()
        ttk.Label(win, textvariable=err_var, foreground="red").pack(pady=2)

        def submit() -> None:
            old = fields["Current password:"].get()
            new = fields["New password:"].get()
            cnf = fields["Confirm new:"].get()
            if len(new) < 8:
                err_var.set("New password must be at least 8 characters.")
                return
            if new != cnf:
                err_var.set("New passwords do not match.")
                return
            try:
                change_password(old, new)
                win.destroy()
                messagebox.showinfo("Success", "Password changed.", parent=self)
                log_info("Admin password changed.")
            except ValueError as exc:
                err_var.set(str(exc))

        ttk.Button(win, text="Confirm", command=submit).pack(pady=10)

    # -- System actions --------------------------------------------------------
    def _shutdown(self) -> None:
        if not messagebox.askyesno("Power Off",
                                   "Shut down the system now?", parent=self):
            return
        log_application_exit("System shutdown via admin panel")
        try:
            subprocess.run(["systemctl", "poweroff"], check=False)
        except FileNotFoundError:
            try:
                subprocess.run(["shutdown", "-h", "now"], check=False)
            except FileNotFoundError:
                subprocess.run(["poweroff"], check=False)

    def _reboot(self) -> None:
        if not messagebox.askyesno("Reboot",
                                   "Reboot the system now?", parent=self):
            return
        log_application_exit("System reboot via admin panel")
        try:
            subprocess.run(["reboot"], check=False)
        except FileNotFoundError:
            subprocess.run(["shutdown", "-r", "now"], check=False)

    def _exit_to_os(self) -> None:
        if not messagebox.askyesno(
            "Exit to OS",
            "Close the P2V Converter and return to the operating system?",
            parent=self,
        ):
            return
        log_application_exit("Exit to OS via admin panel")
        try:
            if is_session_active():
                session_end()
        except Exception:
            pass
        self._parent.quit()
        self._parent.destroy()


def open_admin_panel(parent: tk.Widget) -> None:
    """
    Verify authentication then open the admin panel.
    Handles first-launch password setup automatically.
    """
    if not is_password_set():
        prompt_initial_password(parent)

    dlg = PasswordDialog(parent, title="Administration Access")
    if dlg.result is None:
        return   # cancelled

    if not verify_password(dlg.result):
        messagebox.showerror("Access Denied",
                             "Incorrect password.", parent=parent)
        log_error("Failed admin login attempt (wrong password).")
        return

    log_info("Admin panel access granted.")
    AdminInterface(parent)