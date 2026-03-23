"""
log_handler.py – Logging with volume-based rotation.

Rotation: when disk2qcow2.log exceeds MAX_LOG_SIZE it is renamed
          disk2qcow2.log.YYYYMMDD_HHMMSS and a new file is started.
          The oldest files beyond MAX_ROTATED_FILES are deleted.

Paths:
  /var/log/p2v_converter/disk2qcow2.log        <- current log
  /var/log/p2v_converter/disk2qcow2.log.*      <- rotated logs
"""

import glob
import logging
import os
import sys
import textwrap
from datetime import datetime
from typing import List

# ── Constants ──────────────────────────────────────────────────────────────────
LOG_DIR           = "/var/log/p2v_converter"
log_file          = os.path.join(LOG_DIR, "disk2qcow2.log")
MAX_LOG_SIZE      = 10 * 1024 * 1024   # 10 MB
MAX_ROTATED_FILES = 10

# ── Session state ──────────────────────────────────────────────────────────────
_session_logs: List[str] = []
_session_active: bool    = False


# ── Session-capturing handler ──────────────────────────────────────────────────
class SessionCapturingHandler(logging.Handler):
    """Captures all log records while a session is active."""
    def emit(self, record: logging.LogRecord) -> None:
        global _session_logs, _session_active
        if _session_active:
            ts  = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            msg = f"[{ts}] {record.levelname}: {record.getMessage()}"
            _session_logs.append(msg)


# ── Rotation ───────────────────────────────────────────────────────────────────
def _rotate_if_needed() -> None:
    """Rotate current log if it exceeds MAX_LOG_SIZE."""
    if not os.path.isfile(log_file):
        return
    if os.path.getsize(log_file) < MAX_LOG_SIZE:
        return

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    rotated = f"{log_file}.{ts}"
    try:
        os.rename(log_file, rotated)
    except OSError as e:
        print(f"[log_handler] Cannot rotate log: {e}", file=sys.stderr)
        return

    # Purge oldest beyond quota
    existing = sorted(glob.glob(f"{log_file}.*"))
    while len(existing) > MAX_ROTATED_FILES:
        oldest = existing.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass


def _setup_file_handler() -> None:
    """(Re-)attach a FileHandler after rotation or on startup."""
    global _file_handler
    try:
        if _file_handler:
            _logger.removeHandler(_file_handler)
            _file_handler.close()
    except NameError:
        pass

    try:
        h = logging.FileHandler(log_file)
        h.setLevel(logging.INFO)
        h.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        _logger.addHandler(h)
        _file_handler = h
    except (PermissionError, OSError) as e:
        print(f"[log_handler] Cannot open log file: {e}", file=sys.stderr)


# ── Logger initialisation ──────────────────────────────────────────────────────
os.makedirs(LOG_DIR, mode=0o750, exist_ok=True)

_logger = logging.getLogger("p2v_converter")
_logger.setLevel(logging.INFO)
_logger.propagate = False

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
_logger.addHandler(_console)

_session_handler = SessionCapturingHandler()
_logger.addHandler(_session_handler)

_file_handler = None
_rotate_if_needed()
_setup_file_handler()


# ── Public logging API ─────────────────────────────────────────────────────────
def log_info(message: str) -> None:
    _logger.info(message)


def log_error(message: str) -> None:
    _logger.error(message)


def log_warning(message: str) -> None:
    _logger.warning(message)


# ── Session management ─────────────────────────────────────────────────────────
def session_start() -> None:
    global _session_logs, _session_active
    _session_logs   = []
    _session_active = True

    _rotate_if_needed()
    _setup_file_handler()

    sep = "=" * 80
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_file, "a") as f:
            f.write(f"\n{sep}\nSESSION START: {ts}\n{sep}\n")
    except OSError as e:
        _logger.error(f"Cannot write session start: {e}")

    log_info(f"New session started at {ts}")


def session_end() -> None:
    global _session_active
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_info(f"Session ended at {ts}")
    _session_active = False

    sep = "=" * 80
    try:
        with open(log_file, "a") as f:
            f.write(f"\n{sep}\nSESSION END: {ts}\n{sep}\n\n")
    except OSError as e:
        _logger.error(f"Cannot write session end: {e}")


def log_application_exit(exit_method: str = "Exit button") -> None:
    log_info(f"Application closed via {exit_method}")
    session_end()


def get_current_session_logs() -> List[str]:
    return _session_logs.copy()


def is_session_active() -> bool:
    return _session_active


def get_all_log_files() -> List[str]:
    """Return all log files (current + rotated), newest first."""
    files = []
    if os.path.isfile(log_file):
        files.append(log_file)
    files.extend(sorted(glob.glob(f"{log_file}.*"), reverse=True))
    return files


# ── PDF generation (stdlib only) ───────────────────────────────────────────────
def generate_session_pdf(output_path: str = None) -> str:
    """Generate a PDF from the current session logs. Returns path to PDF."""
    logs = get_current_session_logs()
    if not logs:
        raise ValueError("No session logs available to generate PDF")

    if output_path is None:
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path  = f"/tmp/p2v_session_{ts}.pdf"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    _create_simple_pdf(
        output_path,
        "P2V Converter - Session Log Report",
        logs,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total entries: {len(logs)}",
    )
    log_info(f"Session PDF generated: {output_path}")
    return output_path


def generate_log_file_pdf(output_path: str = None) -> str:
    """Generate a PDF from all log files (current + rotated). Returns path to PDF."""
    all_lines: List[str] = []
    for lf in get_all_log_files():
        try:
            with open(lf, "r", errors="replace") as f:
                all_lines.append("=" * 60)
                all_lines.append(f"File: {os.path.basename(lf)}")
                all_lines.append("=" * 60)
                all_lines.extend(f.read().splitlines())
        except OSError as e:
            all_lines.append(f"[Error reading {lf}: {e}]")

    if not all_lines:
        raise ValueError("No log content available")

    if output_path is None:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"/tmp/p2v_complete_log_{ts}.pdf"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    _create_simple_pdf(
        output_path,
        "P2V Converter - Complete Log Report",
        all_lines,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Source files: {len(get_all_log_files())}",
        f"Total lines: {len(all_lines)}",
    )
    log_info(f"Complete log PDF generated: {output_path}")
    return output_path


# ── Low-level PDF builder (stdlib only) ───────────────────────────────────────
def _escape_pdf_string(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("(", "\\(")
    text = text.replace(")", "\\)")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return "".join(c if 32 <= ord(c) <= 126 else " " for c in text)


def _create_simple_pdf(pdf_path: str, title: str,
                       lines: List[str], *info_lines: str) -> None:
    LINES_PER_PAGE = 55
    wrapped: List[str] = []
    for i, line in enumerate(lines, 1):
        prefix = f"{i:4d}: "
        avail  = 90 - len(prefix)
        parts  = textwrap.wrap(line or " ", avail, break_long_words=True) or [" "]
        for j, part in enumerate(parts):
            wrapped.append(f"{prefix if j == 0 else '      '}{part}")

    pages = [wrapped[i: i + LINES_PER_PAGE]
             for i in range(0, max(1, len(wrapped)), LINES_PER_PAGE)]

    objects: List[str] = []

    def add(obj: str) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add("")   # 1
    pages_id   = add("")   # 2
    font_id    = add("3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj")

    page_ids: List[int] = []

    for p_idx, page_lines in enumerate(pages):
        is_first = (p_idx == 0)
        page_num = p_idx + 1

        cl: List[str] = ["BT", "/F1 8 Tf"]
        if is_first:
            cl += ["50 750 Td", "/F1 14 Tf",
                   f"({_escape_pdf_string(title)}) Tj", "/F1 9 Tf"]
            for il in info_lines:
                cl += ["0 -14 Td", f"({_escape_pdf_string(il)}) Tj"]
            cl += ["0 -18 Td", "/F1 8 Tf"]
        else:
            cl += ["50 750 Td", "/F1 11 Tf",
                   f"({_escape_pdf_string(f'{title} - page {page_num}')}) Tj",
                   "0 -20 Td", "/F1 8 Tf"]

        for line in page_lines:
            cl += ["0 -11 Td", f"({_escape_pdf_string(line)}) Tj"]

        cl += ["50 25 Td", "/F1 7 Tf",
               f"(Page {page_num}/{len(pages)}) Tj", "ET"]
        stream_body = "\n".join(cl)

        sid = add(f"{len(objects)+1} 0 obj\n<< /Length {len(stream_body)} >>\n"
                  f"stream\n{stream_body}\nendstream\nendobj")
        pid = add(f"{len(objects)+1} 0 obj\n"
                  f"<< /Type /Page /Parent {pages_id} 0 R "
                  f"/MediaBox [0 0 612 792] "
                  f"/Contents {sid} 0 R "
                  f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>\n"
                  f"endobj")
        page_ids.append(pid)

    objects[catalog_id - 1] = (
        f"1 0 obj\n<< /Type /Catalog /Pages {pages_id} 0 R >>\nendobj"
    )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = (
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>\nendobj"
    )

    numbered: List[str] = []
    for i, obj in enumerate(objects, 1):
        if not obj.startswith(f"{i} 0 obj"):
            obj = f"{i} 0 obj\n" + obj.split(" 0 obj\n", 1)[-1]
        numbered.append(obj)

    body    = "%PDF-1.4\n"
    offsets: List[int] = []
    for obj in numbered:
        offsets.append(len(body))
        body += obj + "\n"

    xref_offset = len(body)
    xref = f"xref\n0 {len(numbered)+1}\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"

    trailer = (f"trailer\n<< /Size {len(numbered)+1} /Root 1 0 R >>\n"
               f"startxref\n{xref_offset}\n%%EOF\n")

    with open(pdf_path, "w", errors="replace") as f:
        f.write(body + xref + trailer)