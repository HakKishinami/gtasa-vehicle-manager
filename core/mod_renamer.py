"""
Mod Folder Renamer: Safely renames an installed vehicle mod folder inside ModLoader.

Merged configuration files bind to vehicle model names, never to mod folder paths,
so a rename is a pure filesystem move within the same parent directory. The scanner
picks the new folder name up on the next scan.
"""

import os
import re
import time
from typing import Any, Dict, Optional

MAX_FOLDER_NAME_LENGTH = 100
MAX_DEST_PATH_LENGTH = 240

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_STEMS = {"con", "prn", "aux", "nul"}


def validate_mod_folder_name(name: str) -> Optional[str]:
    """Return a user-facing error message, or None when the folder name is safe."""
    if not name or not name.strip():
        return "Folder name cannot be empty"
    if len(name) > MAX_FOLDER_NAME_LENGTH:
        return f"Folder name too long (maximum {MAX_FOLDER_NAME_LENGTH} characters)"
    if name in (".", "..") or name.endswith("."):
        return "Folder name cannot end with a period"
    if _INVALID_CHARS.search(name):
        return 'Folder name cannot contain characters: < > : " / \\ | ? *'
    stem = name.split(".")[0].strip().lower()
    if stem in _RESERVED_STEMS or re.fullmatch(r"(com|lpt)[1-9]", stem):
        return f"'{name}' is a Windows reserved name and cannot be used"
    return None


def _is_inside(path: str, root: str) -> bool:
    try:
        path_abs = os.path.normcase(os.path.realpath(path))
        root_abs = os.path.normcase(os.path.realpath(root))
        return os.path.commonpath([path_abs, root_abs]) == root_abs
    except ValueError:
        return False


def rename_mod_folder(target_path: str, new_name: str, modloader_root: str) -> Dict[str, Any]:
    """
    Rename a mod folder inside modloader_root without touching its contents.

    Returns a dict with success flag plus new_name/new_path/rel_path on success
    (unchanged=True when the requested name equals the current one), or error.
    """
    clean_name = (new_name if isinstance(new_name, str) else "").strip()

    error = validate_mod_folder_name(clean_name)
    if error:
        return {"success": False, "error": error}

    if not target_path or not os.path.isdir(target_path):
        return {"success": False, "error": "Specified mod folder does not exist"}

    if not modloader_root or not os.path.isdir(modloader_root):
        return {"success": False, "error": "ModLoader directory not found; please configure a valid game path first"}

    src = os.path.normpath(str(target_path))
    root = os.path.normpath(str(modloader_root))

    src_key = os.path.normcase(os.path.realpath(src))
    root_key = os.path.normcase(os.path.realpath(root))
    if src_key == root_key or not _is_inside(src, root):
        return {"success": False, "error": "The folder is outside the ModLoader directory; operation denied"}

    parent = os.path.dirname(src)
    dst = os.path.join(parent, clean_name)
    rel_path = os.path.relpath(dst, root)

    if len(dst) > MAX_DEST_PATH_LENGTH:
        return {"success": False, "error": "Target path is too long; please choose a shorter name"}

    if src == dst:
        return {
            "success": True,
            "unchanged": True,
            "new_name": clean_name,
            "new_path": src,
            "old_path": src,
            "rel_path": rel_path,
        }

    case_only = os.path.normcase(src) == os.path.normcase(dst)
    if os.path.exists(dst) and not case_only:
        return {"success": False, "error": f"Target folder '{clean_name}' already exists; please choose another name"}

    try:
        if case_only and os.name == "nt":
            # Windows cannot rename to a name differing only by case directly;
            # move to a temporary sibling first, then to the final name.
            tmp = dst + f"__rename_{int(time.time() * 1000)}"
            os.rename(src, tmp)
            try:
                os.rename(tmp, dst)
            except Exception:
                if os.path.isdir(tmp) and not os.path.exists(src):
                    try:
                        os.rename(tmp, src)
                    except Exception:
                        pass
                raise
        else:
            os.rename(src, dst)
    except PermissionError:
        return {"success": False, "error": "Rename failed: folder is locked by another process. Please close the game or File Explorer and retry."}
    except OSError as exc:
        return {"success": False, "error": f"Rename failed: {exc}"}

    return {
        "success": True,
        "unchanged": False,
        "new_name": clean_name,
        "new_path": dst,
        "old_path": src,
        "rel_path": rel_path,
    }
