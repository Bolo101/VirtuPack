"""
stats_manager.py – Persistent counter of virtualized machines.
Stored in /var/lib/p2v_converter/stats.json.
"""
import json
import logging
import os

STATS_DIR  = "/var/lib/p2v_converter"
STATS_FILE = os.path.join(STATS_DIR, "stats.json")

logger = logging.getLogger("p2v_converter")


def _load() -> dict:
    if not os.path.isfile(STATS_FILE):
        return {"conversion_count": 0, "history": []}
    try:
        with open(STATS_FILE, "r") as f:
            data = json.load(f)
        if "conversion_count" not in data:
            data["conversion_count"] = 0
        if "history" not in data:
            data["history"] = []
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error reading stats: {e}")
        return {"conversion_count": 0, "history": []}


def _save(data: dict) -> None:
    os.makedirs(STATS_DIR, mode=0o700, exist_ok=True)
    tmp = STATS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STATS_FILE)
    except OSError as e:
        logger.error(f"Error writing stats: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass


def get_conversion_count() -> int:
    """Return total number of virtualized machines."""
    return _load().get("conversion_count", 0)


def get_history() -> list:
    """Return conversion history as a list of dicts."""
    return _load().get("history", [])


def record_conversion(source_disk: str, vm_name: str, output_path: str,
                      virtual_size: int = 0, actual_size: int = 0) -> int:
    """
    Record a successful P2V conversion.
    Returns the new total count.
    """
    from datetime import datetime

    data = _load()
    data["conversion_count"] = data.get("conversion_count", 0) + 1

    entry = {
        "date":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_disk":  source_disk,
        "vm_name":      vm_name,
        "output_path":  output_path,
        "virtual_size": virtual_size,
        "actual_size":  actual_size,
        "count_at":     data["conversion_count"],
    }
    data.setdefault("history", []).append(entry)

    _save(data)
    logger.info(f"Conversion recorded #{data['conversion_count']} - {vm_name}")
    return data["conversion_count"]