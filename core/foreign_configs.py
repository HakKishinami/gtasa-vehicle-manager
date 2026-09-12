"""Foreign copies of the config files this manager owns.

ModLoader loads every copy of ``handling.cfg`` / ``carcols.dat`` /
``carmods.dat`` / ``vehicles.ide`` / ``shopping.dat`` / ``veh_mods.ide`` it can
find under ``modloader/`` and lets a single winner decide each entry, so a copy
the manager did not create silently competes with the shadow copy it merges
into. Such a copy is renamed with ``.vmm-disabled`` as soon as it is seen:
ModLoader ignores the unknown extension, every byte stays on disk, and the user
can still read and merge the contents by hand.

Nothing is ever deleted, and nothing outside the configured shadow folder is
touched on purpose - the guard only takes a copy *out of ModLoader's view*.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

WATCHED_FILES = (
    "handling.cfg",
    "carcols.dat",
    "carmods.dat",
    "vehicles.ide",
    "shopping.dat",
    "veh_mods.ide",
)
DISABLED_SUFFIX = ".vmm-disabled"


def _classify(name: str) -> Optional[tuple]:
    """("active"|"disabled", canonical name) for a watched file, else None."""
    lowered = name.lower()
    if lowered in WATCHED_FILES:
        return "active", lowered
    if lowered.endswith(DISABLED_SUFFIX):
        stem = lowered[: -len(DISABLED_SUFFIX)]
        head, _, tail = stem.rpartition(".")
        if head and tail.isdigit():
            stem = head
        if stem in WATCHED_FILES:
            return "disabled", stem
    return None


def _inside(path: Path, root: Optional[Path]) -> bool:
    if root is None:
        return False
    try:
        return path.resolve() == root or path.resolve().is_relative_to(root)
    except OSError:
        return False


def scan(game_path: str, shadow_dir: str = "") -> List[Dict[str, Any]]:
    """Every watched copy under modloader/, excluding the manager's shadow folder."""
    root = Path(game_path) / "modloader"
    if not game_path or not root.is_dir():
        return []
    shadow = Path(shadow_dir).resolve() if shadow_dir else None
    found: List[Dict[str, Any]] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        current = Path(directory)
        dirs[:] = sorted(
            name for name in dirs
            if not name.startswith(".")
            and not (current / name).is_symlink()
            and not _inside(current / name, shadow)
        )
        for name in sorted(files):
            classified = _classify(name)
            if not classified:
                continue
            path = current / name
            if path.is_symlink():
                continue
            found.append({
                "path": str(path),
                "name": name,
                "watched": classified[1],
                "state": classified[0],
            })
    return found


def disable(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rename each entry out of ModLoader's view. Never deletes anything."""
    disabled: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for entry in entries:
        source = Path(entry["path"])
        try:
            if source.is_symlink() or not source.is_file():
                raise OSError("not a regular file")
            destination = source.with_name(source.name + DISABLED_SUFFIX)
            number = 2
            while destination.exists():
                destination = source.with_name(f"{source.name}.{number}{DISABLED_SUFFIX}")
                number += 1
            source.rename(destination)
        except OSError as error:
            errors.append({"path": str(source), "error": str(error)})
            continue
        disabled.append({"path": str(source), "disabled_path": str(destination), "name": source.name})
    return {"disabled": disabled, "errors": errors}


def scan_and_disable(game_path: str, shadow_dir: str = "") -> Dict[str, Any]:
    """Take every competing copy out of ModLoader's view and report what was done."""
    entries = scan(game_path, shadow_dir)
    result = disable([entry for entry in entries if entry["state"] == "active"])
    return {
        "disabled": result["disabled"],
        "errors": result["errors"],
        "already_disabled": [
            {"path": entry["path"], "name": entry["name"]}
            for entry in entries if entry["state"] == "disabled"
        ],
    }
