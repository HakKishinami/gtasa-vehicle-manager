"""
Baseline Manager: Manages shadow copies of GTA SA configuration data in ModLoader.
Ensures vanilla data/ directory is strictly read-only and provides backup / rollback capabilities.
"""

import os
import re
import shutil
import time
from typing import Dict, Any, List, Optional
from .backup_manager import BackupManager

DEFAULT_GAME_PATH = ""
DEFAULT_DATA_FOLDER = "Modded Cars"
SHADOW_REL_PATH = os.path.join("modloader", DEFAULT_DATA_FOLDER)

# Files to manage as shadow copies
DATA_FILES = [
    {"name": "carmods.dat", "vanilla_rel": os.path.join("data", "carmods.dat"), "essential": True},
    {"name": "handling.cfg", "vanilla_rel": os.path.join("data", "handling.cfg"), "essential": True},
    {"name": "carcols.dat", "vanilla_rel": os.path.join("data", "carcols.dat"), "essential": True},
    {"name": "shopping.dat", "vanilla_rel": os.path.join("data", "shopping.dat"), "essential": True},
    {"name": "veh_mods.ide", "vanilla_rel": os.path.join("data", "maps", "veh_mods", "veh_mods.ide"), "essential": True},
    {"name": "vehicles.ide", "vanilla_rel": os.path.join("data", "vehicles.ide"), "essential": False},
]

class BaselineManager:
    def __init__(self, game_path: str = DEFAULT_GAME_PATH, data_folder: str = DEFAULT_DATA_FOLDER, backup_manager: Optional[BackupManager] = None):
        clean_gp = (game_path or "").strip()
        self.game_path = os.path.normpath(clean_gp) if (clean_gp and clean_gp != ".") else ""
        self.data_folder = self._sanitize_folder_name(data_folder)
        self.shadow_dir = os.path.join(self.game_path, "modloader", self.data_folder) if self.game_path else ""
        self.backup_manager = backup_manager or BackupManager(game_dir=self.game_path)

    @staticmethod
    def _sanitize_folder_name(name: str) -> str:
        if not name:
            return DEFAULT_DATA_FOLDER
        clean = name.strip().replace("/", "\\").strip("\\")
        clean = os.path.basename(clean)
        clean = re.sub(r'[<>:"/\\|?*]', '_', clean).strip()
        return clean if clean else DEFAULT_DATA_FOLDER

    def set_data_folder(self, folder_name: str):
        """Switch target folder inside modloader and ensure directory exists."""
        self.data_folder = self._sanitize_folder_name(folder_name)
        self.shadow_dir = os.path.join(self.game_path, "modloader", self.data_folder) if self.game_path else ""
        if self.is_valid_game_path():
            try:
                os.makedirs(self.shadow_dir, exist_ok=True)
            except Exception:
                pass

    def list_modloader_folders(self) -> List[str]:
        """List all valid directory names under modloader/."""
        modloader_path = os.path.join(self.game_path, "modloader")
        folders = []
        if os.path.isdir(modloader_path):
            try:
                for entry in sorted(os.listdir(modloader_path), key=lambda s: s.lower()):
                    if entry.startswith("."):
                        continue
                    full = os.path.join(modloader_path, entry)
                    if os.path.isdir(full):
                        folders.append(entry)
            except Exception:
                pass
        if self.data_folder and self.data_folder not in folders:
            folders.insert(0, self.data_folder)
        if DEFAULT_DATA_FOLDER not in folders:
            folders.append(DEFAULT_DATA_FOLDER)
        return folders

    def is_valid_game_path(self) -> bool:
        """Check if game path exists and contains gta_sa.exe and data folder."""
        if not self.game_path or self.game_path == "." or not os.path.isdir(self.game_path):
            return False
        exe_path = os.path.join(self.game_path, "gta_sa.exe")
        alt_exe = os.path.join(self.game_path, "GTA_SA.EXE")
        data_path = os.path.join(self.game_path, "data")
        return (os.path.exists(exe_path) or os.path.exists(alt_exe)) and os.path.isdir(data_path)

    def get_status(self) -> Dict[str, Any]:
        """Get current status of vanilla vs shadow files."""
        if not self.is_valid_game_path():
            return {
                "valid": False,
                "game_path": self.game_path,
                "data_folder": self.data_folder,
                "shadow_dir": self.shadow_dir,
                "modloader_folders": self.list_modloader_folders(),
                "error": "Specified GTA SA path is invalid or missing gta_sa.exe / data folder",
                "files": {}
            }

        os.makedirs(self.shadow_dir, exist_ok=True)
        files_status = {}

        for item in DATA_FILES:
            fname = item["name"]
            vanilla_path = os.path.join(self.game_path, item["vanilla_rel"])
            # Fallback search for veh_mods.ide if not in maps/veh_mods
            if not os.path.exists(vanilla_path) and fname == "veh_mods.ide":
                alt = os.path.join(self.game_path, "data", "veh_mods.ide")
                if os.path.exists(alt):
                    vanilla_path = alt

            shadow_path = os.path.join(self.shadow_dir, fname)

            has_vanilla = os.path.exists(vanilla_path)
            has_shadow = os.path.exists(shadow_path)

            v_size = os.path.getsize(vanilla_path) if has_vanilla else 0
            s_size = os.path.getsize(shadow_path) if has_shadow else 0

            # Count lines
            v_lines = 0
            s_lines = 0
            if has_vanilla:
                try:
                    with open(vanilla_path, "r", encoding="utf-8", errors="ignore") as f:
                        v_lines = sum(1 for _ in f)
                except Exception:
                    pass
            if has_shadow:
                try:
                    with open(shadow_path, "r", encoding="utf-8", errors="ignore") as f:
                        s_lines = sum(1 for _ in f)
                except Exception:
                    pass

            files_status[fname] = {
                "vanilla_exists": has_vanilla,
                "vanilla_path": vanilla_path,
                "vanilla_lines": v_lines,
                "vanilla_size": v_size,
                "shadow_exists": has_shadow,
                "shadow_path": shadow_path,
                "shadow_lines": s_lines,
                "shadow_size": s_size,
                "modified": (has_shadow and has_vanilla and (s_size != v_size or s_lines != v_lines)),
                "missing_shadow": (has_vanilla and not has_shadow)
            }

        return {
            "valid": True,
            "game_path": self.game_path,
            "data_folder": self.data_folder,
            "shadow_dir": self.shadow_dir,
            "modloader_folders": self.list_modloader_folders(),
            "files": files_status
        }

    def sync_missing_shadow_copies(self) -> Dict[str, Any]:
        """
        Copy missing baseline data files from vanilla data/ into modloader/Modded Cars/.
        Never overwrites existing shadow files.
        """
        status = self.get_status()
        if not status["valid"]:
            return {"success": False, "error": status["error"]}

        copied = []
        skipped = []

        for fname, info in status["files"].items():
            if info["missing_shadow"] and info["vanilla_exists"]:
                shutil.copy2(info["vanilla_path"], info["shadow_path"])
                copied.append(fname)
            else:
                skipped.append(fname)

        return {
            "success": True,
            "copied": copied,
            "skipped": skipped,
            "updated_status": self.get_status()
        }

    def backup_shadow_file(self, filename: str) -> str:
        """Create a backup of a shadow file using BackupManager outside the game directory."""
        shadow_path = os.path.join(self.shadow_dir, filename)
        if not os.path.exists(shadow_path):
            return ""
        bak = self.backup_manager.backup_file(shadow_path)
        return bak or ""

    def revert_to_vanilla(self, filename: str) -> Dict[str, Any]:
        """
        Revert a shadow file in modloader back to pure vanilla baseline.
        Creates a backup first.
        """
        status = self.get_status()
        if filename not in status["files"]:
            return {"success": False, "error": f"Unknown file: {filename}"}

        info = status["files"][filename]
        if not info["vanilla_exists"]:
            return {"success": False, "error": f"Vanilla file does not exist: {info['vanilla_path']}"}

        backup_path = self.backup_shadow_file(filename)
        shutil.copy2(info["vanilla_path"], info["shadow_path"])

        return {
            "success": True,
            "file": filename,
            "backup_created": backup_path,
            "message": f"{filename} successfully reverted to vanilla baseline."
        }
