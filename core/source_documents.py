"""Lossless post-install TXT archival and read-only source document access."""
import json
import os
from pathlib import Path

from .atomic_io import write_text_atomic
from .diagnostics import manifest_path_for

USED_SOURCE_SUFFIX = ".used_source"
# Older versions kept the manifest inside the mod folder. New manifests live in
# the application's diagnostics folder; these leftovers are folded in on the
# next install affecting the same folder.
LEGACY_MANIFEST_NAME = ".vmm-used-sources.json"
DOCUMENT_EXTENSIONS = (".txt", ".readme", ".md", ".me", ".doc")
MAX_PREVIEW_BYTES = 512 * 1024


def enrich_archived_vehicle_metadata(inspection, merger):
    """Resolve installed identities from deployed IDEs, never archived presets."""
    if not inspection.get("archived_source_count"):
        return {}
    configs = {model: merger.get_vehicle_active_configs(model)
               for model in inspection.get("target_models", [])}
    for vehicle in inspection.get("target_vehicles", []):
        ide = (configs.get(vehicle.get("model"), {}).get("vehicles_ide") or {}).get("decomposed") or {}
        if ide and vehicle.get("is_addon"):
            vehicle["id"] = ide.get("id")
            vehicle["type"] = ide.get("type", vehicle.get("type", "car"))
            if vehicle.get("model") == inspection.get("target_model"):
                inspection["addon_id"] = ide.get("id")
                if inspection.get("target_vanilla"):
                    inspection["target_vanilla"].update({"id": ide.get("id"), "type": vehicle["type"]})
    return configs


def is_source_document(name):
    name = name.lower()
    return name.endswith(DOCUMENT_EXTENSIONS + (USED_SOURCE_SUFFIX,)) or name == "vehicles.ide.source"


def list_source_documents(mod_dir):
    """Metadata only. Archived text never enters the configuration parser."""
    root = Path(mod_dir).resolve()
    documents = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not Path(directory, d).is_symlink()
                         and Path(directory, d).resolve().is_relative_to(root))
        for name in sorted(files):
            path = Path(directory, name)
            if not is_source_document(name) or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            try:
                documents.append({"path": path.relative_to(root).as_posix(),
                                  "archived": name.lower().endswith(USED_SOURCE_SUFFIX),
                                  "size": path.stat().st_size})
            except OSError:
                continue
    return documents


def read_source_document(mod_dir, relative_path):
    """Read an explicitly listed document, with bounded memory and no traversal."""
    from .parser import detect_text_encoding
    root = Path(mod_dir).resolve()
    path = root / relative_path
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        return {"success": False, "error_code": "unavailable"}
    if relative_path not in {d["path"] for d in list_source_documents(root)}:
        return {"success": False, "error_code": "unavailable"}
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_PREVIEW_BYTES + 1)
        truncated = len(payload) > MAX_PREVIEW_BYTES
        payload = payload[:MAX_PREVIEW_BYTES]
        encoding = detect_text_encoding(payload) or "utf-8"
        return {"success": True, "content": payload.decode(encoding, errors="replace"),
                "encoding": encoding, "truncated": truncated}
    except (OSError, ValueError):
        return {"success": False, "error_code": "unavailable"}


def archive_used_sources(paths, context=None):
    """Archive only this operation's TXT files after configuration success.

    Every byte is retained. Existing archives receive a new numbered sibling;
    an error restores this batch's original names and manifest contents.
    'Processed' includes explicitly excluded options, not just merged entries.
    Manifests are kept beside the application, never inside the game folder.
    """
    pending = []
    manifests = {}
    legacy_paths = {}
    seen = set()
    renamed = []
    written = []
    try:
        for value in paths:
            path = Path(value)
            if path.suffix.lower() != ".txt":
                continue
            if path.is_symlink() or not path.is_file():
                raise OSError("Source document is unavailable: " + str(path))
            key = os.path.normcase(str(path.resolve()))
            if key in seen:
                continue
            seen.add(key)
            manifest_path = manifest_path_for(path.parent)
            if manifest_path not in manifests:
                old = manifest_path.read_bytes() if manifest_path.exists() else None
                records = json.loads(old.decode("utf-8")) if old is not None else []
                if not isinstance(records, list):
                    raise ValueError("Invalid source archive manifest")
                legacy = path.parent / LEGACY_MANIFEST_NAME
                if legacy.exists() and not legacy.is_symlink():
                    try:
                        migrated = json.loads(legacy.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        migrated = None
                    if isinstance(migrated, list) and migrated:
                        records = migrated + records
                        legacy_paths[manifest_path] = legacy
                manifests[manifest_path] = (old, records)
            destination = path.with_name(path.name + USED_SOURCE_SUFFIX)
            number = 2
            while destination.exists():
                destination = path.with_name(path.name + "." + str(number) + USED_SOURCE_SUFFIX)
                number += 1
            pending.append((path, destination))
        for path, destination in pending:
            # On Windows rename refuses to replace an existing destination.
            if destination.exists():
                raise FileExistsError(str(destination))
            path.rename(destination)
            renamed.append((path, destination))
            manifests[manifest_path_for(path.parent)][1].append({
                "original": path.name, "archive": destination.name, "mod_dir": str(path.parent),
                "status": "processed", "context": context or {}})
        for path, (_, records) in manifests.items():
            written.append(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(str(path), json.dumps(records, ensure_ascii=False, indent=2))
        for legacy in legacy_paths.values():
            try:
                legacy.unlink()
            except OSError:
                pass
        return {"success": True, "files": [str(dest) for _, dest in renamed], "errors": []}
    except (OSError, ValueError) as error:
        errors = ["Configuration processing finished, but source archival failed: " + str(error)]
        for path in reversed(written):
            try:
                old = manifests[path][0]
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    from .atomic_io import write_bytes_atomic
                    write_bytes_atomic(str(path), old)
            except OSError as restore_error:
                errors.append("Could not restore archive manifest: " + str(restore_error))
        for original, archived in reversed(renamed):
            try:
                if original.exists():
                    raise FileExistsError(str(original))
                archived.rename(original)
            except OSError as restore_error:
                errors.append("Could not restore source filename: " + str(restore_error))
        return {"success": False, "files": [], "errors": errors}
