"""
Locate the user's 7-Zip installation at runtime.

ZIP archives fall back to the standard library. RAR / 7Z require 7z.exe;
if it is missing, callers raise SevenZipNotFoundError so the UI can
prompt the user to install 7-Zip from https://www.7-zip.org/.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

SEVEN_ZIP_DOWNLOAD_URL = "https://www.7-zip.org/"
SEVEN_ZIP_EXE_NAMES = ("7z.exe", "7za.exe")
FORMATS_NEEDING_7ZIP = {".rar", ".7z"}
# 7z.exe has no timeout of its own, and the HTTP server is single-threaded, so
# a hung extraction would freeze the whole UI. Kill it after this long instead.
EXTRACT_TIMEOUT_SECONDS = 600

_ENV_VARS = ("GTASA_7ZIP", "SEVEN_ZIP", "SEVENZIP", "7ZIP")

_cached_path: Optional[str] = None
_cached_checked: bool = False


class SevenZipNotFoundError(RuntimeError):
    """Raised when RAR/7Z extraction is requested but 7-Zip is not installed."""

    error_code = "seven_zip_missing"
    download_url = SEVEN_ZIP_DOWNLOAD_URL

    def __init__(self, message: str = ""):
        super().__init__(message or default_missing_message())
        self.error_code = SevenZipNotFoundError.error_code
        self.download_url = SEVEN_ZIP_DOWNLOAD_URL


def default_missing_message() -> str:
    return (
        "7-Zip not detected. ZIP archives can still be installed directly; "
        "RAR / 7Z require 7-Zip to extract. "
        f"Please visit {SEVEN_ZIP_DOWNLOAD_URL} to download and install, then click re-detect."
    )


def reset_cache() -> None:
    global _cached_path, _cached_checked
    _cached_path = None
    _cached_checked = False


def format_needs_7zip(archive_path: str) -> bool:
    ext = os.path.splitext(archive_path or "")[1].lower()
    return ext in FORMATS_NEEDING_7ZIP


def _looks_like_7z(path: str) -> Optional[str]:
    if not path:
        return None
    candidate = os.path.normpath(str(path).strip().strip('"'))
    if os.path.isdir(candidate):
        for name in SEVEN_ZIP_EXE_NAMES:
            exe = os.path.join(candidate, name)
            if os.path.isfile(exe):
                return exe
        return None
    if os.path.isfile(candidate) and os.path.basename(candidate).lower() in SEVEN_ZIP_EXE_NAMES:
        return candidate
    return None


def _candidates_from_env() -> List[str]:
    found = []
    for key in _ENV_VARS:
        raw = os.environ.get(key, "")
        exe = _looks_like_7z(raw)
        if exe:
            found.append(exe)
    return found


def _candidates_from_which() -> List[str]:
    found = []
    for name in ("7z", "7z.exe", "7za", "7za.exe"):
        hit = shutil.which(name)
        exe = _looks_like_7z(hit or "")
        if exe:
            found.append(exe)
    return found


def _candidates_from_registry() -> List[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\7-Zip"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\7-Zip"),
    ]
    found = []
    for hive, subkey in keys:
        try:
            with winreg.OpenKey(hive, subkey) as handle:
                for value_name in ("Path", "Path64"):
                    try:
                        raw, _ = winreg.QueryValueEx(handle, value_name)
                    except OSError:
                        continue
                    exe = _looks_like_7z(raw)
                    if exe:
                        found.append(exe)
        except OSError:
            continue
    return found


def _candidates_from_common_paths() -> List[str]:
    roots = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        val = os.environ.get(env_key)
        if val:
            roots.append(val)
    local = os.environ.get("LOCALAPPDATA", "")
    user = os.environ.get("USERPROFILE", "")
    program_data = os.environ.get("ProgramData", "")

    guessed = []
    for root in roots:
        guessed.append(os.path.join(root, "7-Zip", "7z.exe"))
    if local:
        guessed.append(os.path.join(local, "Programs", "7-Zip", "7z.exe"))
    if user:
        guessed.append(os.path.join(user, "scoop", "apps", "7zip", "current", "7z.exe"))
        guessed.append(os.path.join(user, "scoop", "shims", "7z.exe"))
    if program_data:
        guessed.append(os.path.join(program_data, "chocolatey", "bin", "7z.exe"))

    found = []
    for path in guessed:
        exe = _looks_like_7z(path)
        if exe:
            found.append(exe)
    return found


def find_7zip(force_refresh: bool = False) -> Optional[str]:
    """
    Return the absolute path to 7z.exe if the user has 7-Zip installed.
    Result is cached for the process; pass force_refresh=True after install.
    """
    global _cached_path, _cached_checked

    if not force_refresh and _cached_checked:
        if _cached_path and os.path.isfile(_cached_path):
            return _cached_path
        if _cached_path:
            reset_cache()
        else:
            return None

    ordered: List[str] = []
    for group in (
        _candidates_from_env(),
        _candidates_from_registry(),
        _candidates_from_which(),
        _candidates_from_common_paths(),
    ):
        for path in group:
            if path not in ordered:
                ordered.append(path)

    hit = ordered[0] if ordered else None
    _cached_path = hit
    _cached_checked = True
    return hit


def require_7zip() -> str:
    exe = find_7zip()
    if not exe:
        raise SevenZipNotFoundError()
    return exe


def get_7zip_status(force_refresh: bool = False) -> Dict[str, object]:
    exe = find_7zip(force_refresh=force_refresh)
    return {
        "found": bool(exe),
        "path": exe or "",
        "download_url": SEVEN_ZIP_DOWNLOAD_URL,
        "required_for": sorted(FORMATS_NEEDING_7ZIP),
    }


def extract_with_7zip(seven_zip: str, archive_path: str, out_dir: str,
                      timeout: float = EXTRACT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """
    Run 7z extraction. Raises RuntimeError when 7z.exe exceeds `timeout`
    seconds, so a damaged or pathological archive cannot hang the caller.
    """
    cmd = [seven_zip, "x", "-y", f"-o{out_dir}", archive_path]
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"7-Zip extraction timed out (over {int(timeout)}s), aborted: {os.path.basename(archive_path)}"
        ) from exc
