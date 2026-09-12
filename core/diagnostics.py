"""Application-side diagnostics: an operation log and a one-file support export.

Everything is written next to the application (beside ``backups/`` and
``config.json``), never into the game or modloader directories. The log records
what the manager decided during an install or a merge - including the failures a
user would ask about - and the export bundles it into a single zip that can be
attached to a support request.
"""

import hashlib
import json
import os
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .atomic_io import write_text_atomic

DIAGNOSTICS_DIRNAME = "diagnostics"
LOGS_SUBDIR = "logs"
MANIFESTS_SUBDIR = "manifests"
EXPORTS_SUBDIR = "exports"
OPERATIONS_FILE = "operations.jsonl"

# Keep the log small enough to attach to any support request.
MAX_OPERATIONS = 200
MAX_LIST_FIELDS = 50

SUPPORT_README = """GTASA Vehicle Mod Manager - diagnostics package

What is inside
  system.json            the application and machine the log came from
  logs/operations.jsonl  one JSON object per install or merge, oldest first
  manifests/*.json       which author documents were archived for which mod
  config.json            your manager settings

How to use it
  Attach this zip to your support request and describe what you did and what
  went wrong. The operation you are asking about is normally the last line of
  logs/operations.jsonl, unless you performed another action afterwards.

Privacy
  Absolute paths (game folder, Windows user name) and mod file names are
  included on purpose, because they identify what was scanned. Skim the
  contents before posting them publicly.
"""


def app_root() -> Path:
    """<app_root>: the exe's directory when frozen, the project root otherwise.

    ``VMM_DIAGNOSTICS_ROOT`` redirects the whole diagnostics tree, so test runs
    never write into the working copy.
    """
    override = os.environ.get("VMM_DIAGNOSTICS_ROOT")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable))
    return Path(__file__).resolve().parent.parent


def diagnostics_dir() -> Path:
    return app_root() / DIAGNOSTICS_DIRNAME


def operations_path() -> Path:
    return diagnostics_dir() / LOGS_SUBDIR / OPERATIONS_FILE


def manifests_dir() -> Path:
    return diagnostics_dir() / MANIFESTS_SUBDIR


def exports_dir() -> Path:
    return diagnostics_dir() / EXPORTS_SUBDIR


def manifest_path_for(mod_dir: Union[str, os.PathLike]) -> Path:
    """One manifest per mod folder, keyed by that folder's resolved path."""
    folder = Path(mod_dir).resolve()
    label = re.sub(r"[^0-9A-Za-z._-]+", "_", folder.name) or "mod"
    digest = hashlib.sha1(os.path.normcase(str(folder)).encode("utf-8")).hexdigest()[:8]
    return manifests_dir() / f"{label}-{digest}.json"


def system_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "app_root": str(app_root()),
    }
    if info["frozen"]:
        info["executable"] = sys.executable
        try:
            info["executable_modified"] = datetime.fromtimestamp(
                os.path.getmtime(sys.executable)).astimezone().isoformat(timespec="seconds")
        except OSError:
            pass
    return info


def _bounded(values: Any, limit: int = MAX_LIST_FIELDS) -> List[Any]:
    if not isinstance(values, (list, tuple)):
        return [] if values is None else [values]
    return list(values[:limit])


def record_operation(operation: str, result: Dict[str, Any],
                     context: Optional[Dict[str, Any]] = None) -> bool:
    """Append one JSONL record. Covers failures as well as successes.

    Diagnostics must never be able to break an installation, so any error while
    writing is reported as a False return instead of being raised.
    """
    try:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "operation": operation,
            "success": bool(result.get("success")),
            "error": result.get("error"),
            "errors": _bounded(result.get("errors")),
            "warnings": _bounded(result.get("warnings")),
            "context": context or {},
        }
        path = operations_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if path.exists():
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        lines.append(json.dumps(record, ensure_ascii=False))
        write_text_atomic(str(path), "\n".join(lines[-MAX_OPERATIONS:]) + "\n")
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_operations(limit: int = 50) -> List[Dict[str, Any]]:
    """The newest operations first. Malformed lines are skipped, not raised."""
    if limit <= 0:
        return []
    try:
        records: List[Dict[str, Any]] = []
        for line in operations_path().read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records[-limit:][::-1]
    except OSError:
        return []


def export_bundle(config_path: Optional[Union[str, os.PathLike]] = None) -> Dict[str, Any]:
    """Zip the log, the manifests and the settings into one attachable file."""
    try:
        target = exports_dir() / f"vmm-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        entries = 0
        with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", SUPPORT_README)
            archive.writestr("system.json", json.dumps(system_info(), indent=2, ensure_ascii=False))
            entries += 2
            operations = operations_path()
            if operations.exists():
                archive.write(str(operations), f"logs/{OPERATIONS_FILE}")
                entries += 1
            known = manifests_dir()
            if known.exists():
                for manifest in sorted(known.glob("*.json")):
                    archive.write(str(manifest), f"manifests/{manifest.name}")
                    entries += 1
            if config_path and Path(config_path).exists():
                archive.write(str(config_path), "config.json")
                entries += 1
        return {"success": True, "path": str(target), "size": target.stat().st_size, "entries": entries}
    except OSError as error:
        return {"success": False, "error": f"Could not write diagnostics package: {error}"}
