import os
import sys
import time
import json
import shutil
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Set

from .atomic_io import write_text_atomic


def get_default_backup_dir() -> str:
    """
    Returns <app_root>/backups.
    If running as a PyInstaller bundle, sys.executable's directory is used.
    Otherwise, the project root directory is used.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        # Development mode: D:\gtasa-vehicle-manager
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "backups")


class BackupManager:
    """
    Centralized backup manager for GTA SA Vehicle Manager.
    
    Principles:
    - Never write backup files into the user's game or modloader directories.
    - Organize backups by operation session snapshots (e.g. backups/20260909_153000_install_Premier).
    - Maintain original filenames and directory structures inside each snapshot.
    - Support snapshot manifest metadata, atomic rollback/restoration, and rotation limit.
    """

    def __init__(
        self,
        backup_dir: Optional[str] = None,
        game_dir: Optional[str] = None,
        max_snapshots: int = 20
    ):
        self.backup_dir = os.path.abspath(backup_dir) if backup_dir else get_default_backup_dir()
        self.game_dir = os.path.abspath(game_dir) if game_dir else None
        self.max_snapshots = max_snapshots

        self._active_snapshot_dir: Optional[str] = None
        self._active_manifest: Optional[Dict[str, Any]] = None
        self._active_backed_up_files: Set[str] = set()
        self._snapshot_depth: int = 0

        os.makedirs(self.backup_dir, exist_ok=True)

    def set_game_dir(self, game_dir: Optional[str]):
        """Update active game root directory."""
        self.game_dir = os.path.abspath(game_dir) if game_dir else None

    def start_snapshot(self, action_name: str = "operation", description: str = "") -> str:
        """
        Begins an operation snapshot session. Nested calls reuse the current snapshot.
        """
        if self._snapshot_depth > 0 and self._active_snapshot_dir:
            self._snapshot_depth += 1
            return self._active_snapshot_dir

        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_action = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in action_name).strip("_")
        if not safe_action:
            safe_action = "operation"

        folder_name = f"{ts}_{safe_action}"
        snap_dir = os.path.join(self.backup_dir, folder_name)
        counter = 1
        while os.path.exists(snap_dir):
            snap_dir = os.path.join(self.backup_dir, f"{folder_name}_{counter}")
            counter += 1

        os.makedirs(snap_dir, exist_ok=True)
        self._active_snapshot_dir = snap_dir
        self._active_manifest = {
            "id": os.path.basename(snap_dir),
            "timestamp": ts,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action_name,
            "description": description,
            "game_dir": self.game_dir,
            "files": []
        }
        self._active_backed_up_files = set()
        self._snapshot_depth = 1
        return snap_dir

    def finish_snapshot(self) -> Optional[str]:
        """
        Concludes the current snapshot session, writes manifest.json, and triggers rotation.
        If no files were backed up, cleans up the empty snapshot directory.
        """
        if self._snapshot_depth > 1:
            self._snapshot_depth -= 1
            return self._active_snapshot_dir

        snap_dir = self._active_snapshot_dir
        manifest = self._active_manifest

        self._snapshot_depth = 0
        self._active_snapshot_dir = None
        self._active_manifest = None
        self._active_backed_up_files = set()

        if not snap_dir or not manifest:
            return None

        # Clean up if empty
        if not manifest.get("files"):
            try:
                if os.path.exists(snap_dir):
                    shutil.rmtree(snap_dir, ignore_errors=True)
            except Exception:
                pass
            return None

        # Write manifest
        manifest_path = os.path.join(snap_dir, "manifest.json")
        try:
            write_text_atomic(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"[BackupManager] Error writing manifest: {e}")

        # Rotate old snapshots
        self.rotate_snapshots()
        return snap_dir

    @contextmanager
    def snapshot(self, action_name: str = "operation", description: str = ""):
        """
        Context manager for grouping multiple file modifications into a single snapshot.
        """
        snap_dir = self.start_snapshot(action_name, description)
        try:
            yield snap_dir
        finally:
            self.finish_snapshot()

    def backup_file(self, filepath: str) -> Optional[str]:
        """
        Backs up a file into the active snapshot (or a single-action snapshot if none is active).
        Preserves original pre-operation content if called repeatedly on the same file.
        """
        if not filepath or not os.path.exists(filepath):
            return None

        norm_path = os.path.normpath(os.path.abspath(filepath))

        auto_finish = False
        if not self._active_snapshot_dir:
            action_hint = os.path.splitext(os.path.basename(norm_path))[0]
            self.start_snapshot(action_name=f"edit_{action_hint}")
            auto_finish = True

        try:
            # If already backed up in this session, don't overwrite with newer modifications
            if norm_path in self._active_backed_up_files:
                for entry in self._active_manifest.get("files", []):
                    if os.path.normpath(entry.get("source_path", "")) == norm_path:
                        return os.path.join(self._active_snapshot_dir, entry["relative_path"])
                return None

            # Compute relative subpath
            if self.game_dir and norm_path.lower().startswith(self.game_dir.lower()):
                rel_path = os.path.relpath(norm_path, self.game_dir)
            else:
                rel_path = os.path.basename(norm_path)

            rel_path = os.path.normpath(rel_path).lstrip(os.sep).lstrip("/")
            target_path = os.path.join(self._active_snapshot_dir, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            shutil.copy2(norm_path, target_path)
            self._active_backed_up_files.add(norm_path)
            self._active_manifest["files"].append({
                "source_path": norm_path,
                "relative_path": rel_path.replace("\\", "/"),
                "size": os.path.getsize(norm_path)
            })
            return target_path
        finally:
            if auto_finish:
                self.finish_snapshot()

    def rotate_snapshots(self):
        """
        Keeps only the latest max_snapshots. Removes older snapshots.
        Ignores folders starting with '_' (e.g. _legacy_game_backups).
        """
        if self.max_snapshots <= 0 or not os.path.exists(self.backup_dir):
            return

        snapshots = []
        try:
            for entry in os.listdir(self.backup_dir):
                if entry.startswith("_"):
                    continue
                full_path = os.path.join(self.backup_dir, entry)
                if os.path.isdir(full_path):
                    mtime = os.path.getmtime(full_path)
                    snapshots.append((mtime, full_path))
        except Exception as e:
            print(f"[BackupManager] Error listing snapshots for rotation: {e}")
            return

        snapshots.sort(key=lambda x: x[0])  # Oldest first

        while len(snapshots) > self.max_snapshots:
            oldest = snapshots.pop(0)
            try:
                shutil.rmtree(oldest[1], ignore_errors=True)
            except Exception as e:
                print(f"[BackupManager] Failed to remove expired snapshot {oldest[1]}: {e}")

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        Lists all available snapshots sorted newest first.
        """
        if not os.path.exists(self.backup_dir):
            return []

        results = []
        for entry in os.listdir(self.backup_dir):
            if entry.startswith("_"):
                continue
            full_path = os.path.join(self.backup_dir, entry)
            if not os.path.isdir(full_path):
                continue

            manifest_path = os.path.join(full_path, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                        manifest["dir_path"] = full_path
                        results.append(manifest)
                        continue
                except Exception:
                    pass

            # Fallback for folder without valid manifest
            results.append({
                "id": entry,
                "timestamp": entry.split("_")[0] if "_" in entry else "",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(full_path))),
                "action": entry,
                "description": "",
                "game_dir": "",
                "files": [],
                "dir_path": full_path
            })

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results

    def restore_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """
        Restores files from a specified snapshot back to their original locations.
        """
        snap_dir = os.path.join(self.backup_dir, snapshot_id)
        if not os.path.isdir(snap_dir):
            return {"success": False, "error": f"Snapshot does not exist: {snapshot_id}"}

        manifest_path = os.path.join(snap_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return {"success": False, "error": f"Snapshot metadata missing: {manifest_path}"}

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"Cannot parse snapshot metadata: {e}"}

        restored = []
        errors = []

        # Before restoring, create a safety snapshot of current state
        with self.snapshot(action_name=f"prerestore_{snapshot_id}"):
            for item in manifest.get("files", []):
                source_path = item.get("source_path")
                rel_path = item.get("relative_path")
                if not source_path or not rel_path:
                    continue

                snapshot_file = os.path.join(snap_dir, rel_path.replace("/", os.sep))
                if not os.path.exists(snapshot_file):
                    errors.append(f"Snapshot file missing: {rel_path}")
                    continue

                try:
                    if os.path.exists(source_path):
                        self.backup_file(source_path)
                    os.makedirs(os.path.dirname(source_path), exist_ok=True)
                    shutil.copy2(snapshot_file, source_path)
                    restored.append(source_path)
                except Exception as e:
                    errors.append(f"Restore failed {source_path}: {e}")

        return {
            "success": len(errors) == 0,
            "restored_count": len(restored),
            "restored_files": restored,
            "errors": errors
        }

    def clean_legacy_game_backups(
        self,
        game_dir: Optional[str] = None,
        archive_to_backup: bool = True
    ) -> Dict[str, Any]:
        """
        Finds and cleans legacy *.bak_* and *.bak files from the game directory
        (data/, modloader/, etc.) and archives them into backups/_legacy_game_backups/.
        """
        target_game = os.path.abspath(game_dir) if game_dir else self.game_dir
        if not target_game or not os.path.isdir(target_game):
            return {"success": False, "error": "Game directory is invalid or not specified"}

        search_dirs = [
            os.path.join(target_game, "data"),
            os.path.join(target_game, "modloader"),
            target_game
        ]

        found_files = set()
        for s_dir in search_dirs:
            if not os.path.isdir(s_dir):
                continue
            for root, _, files in os.walk(s_dir):
                for f in files:
                    if ".bak" in f.lower():
                        found_files.add(os.path.join(root, f))

        if not found_files:
            return {
                "success": True,
                "cleaned_count": 0,
                "message": "No legacy backup files found. Game directory is clean."
            }

        archive_dir = None
        if archive_to_backup:
            ts = time.strftime("%Y%m%d_%H%M%S")
            archive_dir = os.path.join(self.backup_dir, "_legacy_game_backups", f"archived_{ts}")
            os.makedirs(archive_dir, exist_ok=True)

        cleaned = []
        errors = []

        for fpath in sorted(found_files):
            try:
                if archive_to_backup and archive_dir:
                    rel = os.path.relpath(fpath, target_game)
                    rel = os.path.normpath(rel).lstrip(os.sep).lstrip("/")
                    dest = os.path.join(archive_dir, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(fpath, dest)
                else:
                    os.remove(fpath)
                cleaned.append(fpath)
            except Exception as e:
                errors.append(f"Cleanup failed {fpath}: {e}")

        return {
            "success": len(errors) == 0,
            "cleaned_count": len(cleaned),
            "archive_dir": archive_dir,
            "cleaned_files": cleaned,
            "errors": errors
        }
