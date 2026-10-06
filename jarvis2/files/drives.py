"""Finding the drives that are not the system drive.

A flash disk normally reports itself as a fixed disk rather than a removable
one, so both kinds are kept. Windows is asked directly rather than through
psutil or WMI, which would mean another dependency for one function.
"""

from __future__ import annotations

import ctypes
import os
import string

from jarvis2.logging_utils import get_logger

_log = get_logger("files.drives")

# GetDriveTypeW: 2 is removable, 3 is fixed. Network, optical and unknown are
# skipped, because walking those is slow and never finds the user's files.
REMOVABLE = 2
FIXED = 3
USABLE = (REMOVABLE, FIXED)

# "System Reserved" and recovery partitions are tiny. Walking them wastes
# seconds and finds nothing.
MINIMUM_GB = 1.0


def _kernel32():
    try:
        return ctypes.windll.kernel32
    except (AttributeError, OSError) as error:
        # Not Windows, or no ctypes support. The assistant still works; it just
        # will not search other drives.
        _log.info("drives are unavailable here: %s", error)
        return None


def volume_size_gb(root: str) -> float:
    """A volume's total size in gigabytes, or 0 if it cannot be read."""
    kernel32 = _kernel32()
    if kernel32 is None:
        return 0.0

    free_to_caller = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    free_total = ctypes.c_ulonglong(0)

    read = kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(root),
        ctypes.byref(free_to_caller),
        ctypes.byref(total),
        ctypes.byref(free_total),
    )
    return total.value / (1024 ** 3) if read else 0.0


def extra_drives() -> list:
    """Every drive except the system drive and the tiny system volumes."""
    kernel32 = _kernel32()
    if kernel32 is None:
        return []

    mask = kernel32.GetLogicalDrives()
    system = os.environ.get("SystemDrive", "C:")[0].upper()

    roots = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not (mask >> index) & 1 or letter == system:
            continue

        root = f"{letter}:{os.sep}"
        try:
            kind = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except OSError:
            continue
        if kind not in USABLE:
            continue
        if volume_size_gb(root) < MINIMUM_GB:
            continue

        roots.append(root)
    return roots


def describe() -> list:
    """The drives found, for the dashboard."""
    system = os.environ.get("SystemDrive", "C:")[0].upper()
    found = []
    for root in extra_drives():
        found.append({
            "root": root,
            "letter": root[0].upper(),
            "sizeGb": round(volume_size_gb(root), 1),
            "isSystem": root[0].upper() == system,
        })
    return found
