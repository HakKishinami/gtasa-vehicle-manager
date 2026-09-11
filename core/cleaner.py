"""
Mod Cleaner: Handles safe uninstallation/deletion of installed vehicle mods,
cleaning mod directories, and safely reverting modified configuration lines back to vanilla baseline.
"""

import os
import sys
import stat
import re
import shutil
import time
from typing import Dict, Any, Optional, List, Set
from .fla_manager import FLAManager
from .backup_manager import BackupManager
from .vanilla_data import MODEL_TO_ID, TUNING_PREFIX_INFO, VANILLA_VEHICLES
from .parser import normalize_ide_line, DualTrackParser
from .atomic_io import write_text_atomic


def _safe_rmtree(path: str):
    """Safely remove a directory tree, clearing Windows read-only flags and retrying transient locks."""
    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except Exception:
            pass

    try:
        if sys.version_info >= (3, 12):
            def _onexc(func, p, exc):
                try:
                    os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                    func(p)
                except Exception:
                    pass
            shutil.rmtree(path, onexc=_onexc)
        else:
            shutil.rmtree(path, onerror=_onerror)
    except Exception:
        time.sleep(0.15)
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_onexc)
        else:
            shutil.rmtree(path, onerror=_onerror)


class ModCleaner:
    def __init__(self, game_path: str, data_folder: str = "Modded Cars", backup_manager: Optional[BackupManager] = None):
        self.game_path = os.path.normpath(game_path)
        self.data_folder = data_folder
        self.shadow_dir = os.path.join(self.game_path, "modloader", self.data_folder)
        self.vanilla_dir = os.path.join(self.game_path, "data")
        self.backup_manager = backup_manager or BackupManager(game_dir=self.game_path)
        self.fla_mgr = FLAManager(self.game_path, backup_manager=self.backup_manager)

    def set_data_folder(self, data_folder: str):
        self.data_folder = data_folder
        self.shadow_dir = os.path.join(self.game_path, "modloader", self.data_folder)

    def delete_mod(self, mod_path: str, target_model: Optional[str] = None, revert_config: bool = True) -> Dict[str, Any]:
        """
        Safely delete a vehicle mod folder and optionally revert its configurations.
        """
        mod_path = os.path.normpath(mod_path)
        modloader_base = os.path.normpath(os.path.join(self.game_path, "modloader"))

        # 1. Security Check: Must be inside modloader/
        if not mod_path.startswith(modloader_base) or mod_path == modloader_base:
            return {"success": False, "error": "Safety guard: Only mod directories inside modloader/ can be deleted."}

        if not os.path.isdir(mod_path):
            return {"success": False, "error": f"Mod directory to delete does not exist: {mod_path}"}

        # 2. Revert configurations for target_model(s) if requested
        reverted_configs = []
        action_tag = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(target_model or os.path.basename(mod_path)))
        with self.backup_manager.snapshot(action_name=f"uninstall_{action_tag}"):
            if revert_config:
                models_to_revert = []
                if target_model:
                    if isinstance(target_model, str):
                        models_to_revert = [m.strip().lower() for m in target_model.split(",") if m.strip()]
                    elif isinstance(target_model, list):
                        models_to_revert = [str(m).strip().lower() for m in target_model if m]

                # Inspect mod_path to discover ANY vehicle models installed inside this folder
                if os.path.isdir(mod_path):
                    try:
                        for root, _, fnames in os.walk(mod_path):
                            for fn in fnames:
                                if fn.lower().endswith(".dff"):
                                    base = os.path.splitext(fn)[0].lower()
                                    if not any(base.startswith(pfx) for pfx in TUNING_PREFIX_INFO) and "tuning" not in root.lower():
                                        if base not in models_to_revert:
                                            models_to_revert.append(base)
                    except Exception:
                        pass

                    # Also inspect mod directory files/readmes using parser to catch audio or config definitions
                    try:
                        dtp = DualTrackParser()
                        minfo = dtp.inspect_mod_directory(mod_path)
                        if minfo.get("success"):
                            for aud in minfo.get("vehicle_audio", []):
                                am = (aud.get("model") or "").strip().lower()
                                if am and am not in models_to_revert:
                                    models_to_revert.append(am)
                            for tm in minfo.get("target_models", []):
                                tmc = str(tm).strip().lower()
                                if tmc and tmc not in models_to_revert:
                                    models_to_revert.append(tmc)
                    except Exception:
                        pass

                for model_clean in models_to_revert:
                    try:
                        # Collect custom tuning parts before config reversion
                        custom_parts = self._get_model_tuning_parts(model_clean)

                        # A. Revert handling.cfg
                        if self._revert_handling(model_clean):
                            reverted_configs.append(f"handling.cfg ({model_clean})")

                        # B. Revert carcols.dat
                        if self._revert_carcols(model_clean):
                            reverted_configs.append(f"carcols.dat ({model_clean})")

                        # C. Revert carmods.dat
                        if self._revert_carmods(model_clean, custom_parts):
                            reverted_configs.append(f"carmods.dat ({model_clean})")

                        # C2. Revert vehicles.ide
                        if self._revert_vehicles_ide(model_clean):
                            reverted_configs.append(f"vehicles.ide ({model_clean})")

                        # C3. Clean up custom veh_mods.ide entries (freeing IDs)
                        if self._revert_veh_mods(model_clean, custom_parts):
                            reverted_configs.append(f"veh_mods.ide ({model_clean})")

                        # C4. Clean up custom shopping.dat entries
                        if self._revert_shopping(model_clean, custom_parts):
                            reverted_configs.append(f"shopping.dat ({model_clean})")

                        # D. Remove FLA Special Features
                        if self.fla_mgr.get_feature_for_model(model_clean):
                            self.fla_mgr.remove_special_feature(model_clean)
                            reverted_configs.append(f"model_special_features.dat ({model_clean})")

                    except Exception as e:
                        print(f"Warning during config reversion for {model_clean}: {e}")

                # Audio cleanup: ensure all deleted models have their audio cleanly reverted or removed
                if models_to_revert:
                    if self.fla_mgr.remove_audio_settings(models_to_revert):
                        reverted_configs.append("gtasa_vehicleAudioSettings.cfg")

        # 3. Delete Mod Directory
        parent_dir = os.path.dirname(mod_path)
        try:
            _safe_rmtree(mod_path)
        except Exception as e:
            return {"success": False, "error": f"Failed to delete folder: {e}"}

        # 3b. Purge any remaining orphan configs whose .dff no longer exists in modloader
        try:
            orphan_res = self.clean_orphaned_vehicle_entries()
            if orphan_res.get("purged"):
                for cfg_k, items in orphan_res["purged"].items():
                    if items:
                        reverted_configs.append(f"{cfg_k} (cleaned remnants: {', '.join(items)})")
        except Exception as e:
            print(f"Warning during orphan cleanup: {e}")

        # 4. Clean up empty parent author folder if empty
        cleaned_parent = False
        try:
            # Check if parent is an author folder (inside modloader/<category>)
            rel_to_modloader = os.path.relpath(parent_dir, modloader_base)
            parts = rel_to_modloader.split(os.sep)
            if len(parts) == 2 and os.path.isdir(parent_dir):
                entries = [e for e in os.listdir(parent_dir) if e.lower() not in ("desktop.ini", "thumbs.db", ".ds_store")]
                if not entries:
                    for junk in os.listdir(parent_dir):
                        try:
                            jp = os.path.join(parent_dir, junk)
                            os.chmod(jp, stat.S_IWRITE | stat.S_IREAD)
                            os.remove(jp)
                        except Exception:
                            pass
                    os.rmdir(parent_dir)
                    cleaned_parent = True
        except Exception:
            pass

        return {
            "success": True,
            "reverted_configs": reverted_configs,
            "cleaned_parent": cleaned_parent,
            "message": "Mod uninstalled and deleted successfully; configurations reverted to vanilla baseline."
        }

    # ---------------- Specific File Config Reverters ----------------

    def _revert_handling(self, model: str) -> bool:
        """Find vanilla handling line(s) (both main vehicle line and secondary !, $, % lines) and restore in shadow handling.cfg; if addon car, remove lines completely."""
        vanilla_handling_file = os.path.join(self.vanilla_dir, "handling.cfg")
        shadow_handling_file = os.path.join(self.shadow_dir, "handling.cfg")
        if not os.path.exists(shadow_handling_file):
            return False

        vanilla_main_line = None
        vanilla_prefix_lines = {}
        model_upper = model.strip().upper()

        if os.path.exists(vanilla_handling_file):
            with open(vanilla_handling_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith(";") and not stripped.startswith("#") and not stripped.startswith("//"):
                        parts = stripped.split()
                        if not parts:
                            continue
                        if parts[0][0] in ("!", "$", "%", "^"):
                            pfx = parts[0][0]
                            rem = parts[0][1:]
                            ident = rem.upper() if rem else (parts[1].upper() if len(parts) > 1 else "")
                            if ident == model_upper:
                                vanilla_prefix_lines[pfx] = stripped
                        else:
                            if parts[0].upper() == model_upper and len(parts) >= 20:
                                vanilla_main_line = stripped

        with open(shadow_handling_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        vanilla_main_placed = False
        vanilla_prefix_placed = set()

        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(";") and not stripped.startswith("#") and not stripped.startswith("//"):
                parts = stripped.split()
                if parts:
                    line_pfx = ""
                    line_ident = ""
                    if parts[0][0] in ("!", "$", "%", "^"):
                        line_pfx = parts[0][0]
                        rem = parts[0][1:]
                        line_ident = rem.upper() if rem else (parts[1].upper() if len(parts) > 1 else "")
                    else:
                        line_ident = parts[0].upper()

                    if line_pfx:
                        if line_ident == model_upper:
                            if line_pfx in vanilla_prefix_lines and line_pfx not in vanilla_prefix_placed:
                                new_lines.append(vanilla_prefix_lines[line_pfx] + "\n")
                                vanilla_prefix_placed.add(line_pfx)
                                if stripped != vanilla_prefix_lines[line_pfx]:
                                    modified = True
                            else:
                                modified = True
                            continue
                    else:
                        if line_ident == model_upper:
                            if vanilla_main_line and not vanilla_main_placed:
                                new_lines.append(vanilla_main_line + "\n")
                                vanilla_main_placed = True
                                if stripped != vanilla_main_line:
                                    modified = True
                            else:
                                modified = True
                            continue

            new_lines.append(line)

        # If vanilla had a prefix line that was missing from shadow, re-add it
        for pfx, p_line in vanilla_prefix_lines.items():
            if pfx not in vanilla_prefix_placed:
                new_lines.append(p_line + "\n")
                modified = True

        if modified:
            self.backup_manager.backup_file(shadow_handling_file)
            write_text_atomic(shadow_handling_file, new_lines)
            return True
        return False

    def _revert_carcols(self, model: str) -> bool:
        """Find vanilla carcols line and replace in shadow carcols.dat; if addon car, remove matching lines."""
        vanilla_carcols = os.path.join(self.vanilla_dir, "carcols.dat")
        shadow_carcols = os.path.join(self.shadow_dir, "carcols.dat")
        if not os.path.exists(shadow_carcols):
            return False

        model_clean = model.lower()
        vanilla_line = None
        vanilla_sec = "car"

        if os.path.exists(vanilla_carcols):
            with open(vanilla_carcols, "r", encoding="utf-8", errors="ignore") as f:
                cur_sec = None
                for line in f:
                    stripped = line.strip()
                    low = stripped.lower()
                    if low in ("col", "car", "car4"):
                        cur_sec = low
                        continue
                    if low == "end":
                        cur_sec = None
                        continue
                    if cur_sec in ("car", "car4") and stripped and not stripped.startswith("#"):
                        parts = [p.strip() for p in stripped.split(",") if p.strip()]
                        if parts and parts[0].lower() == model_clean:
                            vanilla_line = stripped
                            vanilla_sec = cur_sec
                            break

        with open(shadow_carcols, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        vanilla_placed = False
        cur_sec = None

        for line in lines:
            stripped = line.strip()
            low = stripped.lower()

            if low in ("col", "car", "car4"):
                cur_sec = low
                new_lines.append(line)
                continue

            if low == "end":
                if cur_sec == vanilla_sec and vanilla_line and not vanilla_placed:
                    new_lines.append(vanilla_line + "\n")
                    vanilla_placed = True
                    modified = True
                cur_sec = None
                new_lines.append(line)
                continue

            parts = [p.strip() for p in stripped.split(",") if p.strip()]
            if parts and parts[0].lower() == model_clean:
                if cur_sec == vanilla_sec and vanilla_line and not vanilla_placed:
                    new_lines.append(vanilla_line + "\n")
                    vanilla_placed = True
                    if stripped != vanilla_line:
                        modified = True
                else:
                    # Remove from other sections or rogue lines
                    modified = True
                continue

            # Strip rogue vehicle lines left outside sections
            if cur_sec is None and stripped and not stripped.startswith("#"):
                if len(parts) >= 2 and all(p.isdigit() for p in parts[1:]):
                    if parts[0].lower() == model_clean:
                        modified = True
                        continue

            new_lines.append(line)

        if modified:
            self.backup_manager.backup_file(shadow_carcols)
            write_text_atomic(shadow_carcols, new_lines)
            return True
        return False

    def _get_model_tuning_parts(self, model: str) -> Set[str]:
        """Collect custom tuning parts registered for this model in shadow carmods.dat and veh_mods.ide."""
        model_clean = model.strip().lower()
        parts = set()

        # 1. From shadow carmods.dat
        shadow_cm = os.path.join(self.shadow_dir, "carmods.dat")
        if os.path.exists(shadow_cm):
            try:
                with open(shadow_cm, "r", encoding="utf-8", errors="ignore") as f:
                    in_mods = False
                    for line in f:
                        s = line.strip().lower()
                        if s == "mods":
                            in_mods = True
                            continue
                        if in_mods and s == "end":
                            break
                        if in_mods and s and not s.startswith("#") and not s.startswith(";"):
                            toks = [t.strip().lower() for t in s.split(",") if t.strip()]
                            if toks and toks[0] == model_clean:
                                for p in toks[1:]:
                                    parts.add(p)
            except Exception:
                pass

        # 2. From shadow veh_mods.ide
        shadow_vm = os.path.join(self.shadow_dir, "veh_mods.ide")
        if os.path.exists(shadow_vm):
            try:
                with open(shadow_vm, "r", encoding="utf-8", errors="ignore") as f:
                    in_objs = False
                    for line in f:
                        s = line.strip().lower()
                        if s == "objs":
                            in_objs = True
                            continue
                        if in_objs and s == "end":
                            break
                        if in_objs and s and not s.startswith("#") and not s.startswith(";"):
                            toks = [t.strip().lower() for t in s.split(",") if t.strip()]
                            if len(toks) >= 3 and toks[2] == model_clean:
                                parts.add(toks[1])
            except Exception:
                pass

        # Exclude vanilla tuning parts
        vanilla_cm = os.path.join(self.vanilla_dir, "carmods.dat")
        if os.path.exists(vanilla_cm):
            try:
                with open(vanilla_cm, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip().lower()
                        if s and not s.startswith("#"):
                            toks = [t.strip().lower() for t in s.split(",") if t.strip()]
                            if toks and toks[0] == model_clean:
                                for p in toks[1:]:
                                    parts.discard(p)
            except Exception:
                pass

        return parts

    def _revert_carmods(self, model: str, custom_parts: Optional[Set[str]] = None) -> bool:
        """Find vanilla carmods line and replace in shadow carmods.dat; remove custom mirror links if any."""
        vanilla_carmods = os.path.join(self.vanilla_dir, "carmods.dat")
        shadow_carmods = os.path.join(self.shadow_dir, "carmods.dat")
        if not os.path.exists(shadow_carmods):
            return False

        model_clean = model.lower()
        vanilla_line = None
        vanilla_links = set()

        if os.path.exists(vanilla_carmods):
            with open(vanilla_carmods, "r", encoding="utf-8", errors="ignore") as f:
                in_mods_sec = False
                in_link_sec = False
                for line in f:
                    stripped = line.strip()
                    low = stripped.lower()
                    if low == "link":
                        in_link_sec = True
                        continue
                    if in_link_sec and low == "end":
                        in_link_sec = False
                        continue
                    if in_link_sec and stripped and not stripped.startswith("#"):
                        parts = [p.strip().lower() for p in stripped.split(",") if p.strip()]
                        if len(parts) >= 2:
                            vanilla_links.add(frozenset((parts[0], parts[1])))

                    if low == "mods":
                        in_mods_sec = True
                        continue
                    if in_mods_sec and low == "end":
                        in_mods_sec = False
                        continue
                    if in_mods_sec and stripped and not stripped.startswith("#"):
                        parts = [p.strip() for p in stripped.split(",") if p.strip()]
                        if parts and parts[0].lower() == model_clean:
                            vanilla_line = stripped

        with open(shadow_carmods, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        vanilla_placed = False
        in_mods = False
        in_link = False

        parts_to_clean = set(custom_parts) if custom_parts else set()

        for line in lines:
            stripped = line.strip()
            low = stripped.lower()
            if low == "mods":
                in_mods = True
                new_lines.append(line)
                continue
            if in_mods and low == "end":
                in_mods = False
                new_lines.append(line)
                continue
            if low == "link":
                in_link = True
                new_lines.append(line)
                continue
            if in_link and low == "end":
                in_link = False
                new_lines.append(line)
                continue

            if in_mods and stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if parts and parts[0].lower() == model_clean:
                    if vanilla_line and not vanilla_placed:
                        new_lines.append(vanilla_line + "\n")
                        vanilla_placed = True
                        if stripped != vanilla_line:
                            modified = True
                    else:
                        modified = True
                    continue

            if in_link and stripped and not stripped.startswith("#"):
                parts = [p.strip().lower() for p in stripped.split(",") if p.strip()]
                if len(parts) >= 2:
                    pair = frozenset((parts[0], parts[1]))
                    if pair not in vanilla_links and (parts[0] in parts_to_clean or parts[1] in parts_to_clean):
                        modified = True
                        continue

            new_lines.append(line)

        if modified:
            self.backup_manager.backup_file(shadow_carmods)
            write_text_atomic(shadow_carmods, new_lines)
            return True
        return False

    def _revert_vehicles_ide(self, model: str) -> bool:
        """Find vanilla vehicles.ide line and replace in shadow vehicles.ide; if addon car, remove line."""
        vanilla_ide = os.path.join(self.vanilla_dir, "vehicles.ide")
        shadow_ide = os.path.join(self.shadow_dir, "vehicles.ide")
        if not os.path.exists(shadow_ide):
            return False

        model_clean = model.lower()
        vanilla_line = None
        if os.path.exists(vanilla_ide):
            with open(vanilla_ide, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = normalize_ide_line(line.strip())
                    if stripped and not stripped.startswith("#"):
                        parts = [p.strip() for p in stripped.split(",") if p.strip()]
                        if len(parts) >= 2 and parts[1].lower() == model_clean:
                            vanilla_line = stripped
                            break

        with open(shadow_ide, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        modified = False
        vanilla_placed = False

        for line in lines:
            stripped = normalize_ide_line(line.strip())
            if stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if len(parts) >= 2 and parts[1].lower() == model_clean:
                    if vanilla_line and not vanilla_placed:
                        new_lines.append(vanilla_line + "\n")
                        vanilla_placed = True
                        if stripped != vanilla_line:
                            modified = True
                    else:
                        modified = True
                    continue
            new_lines.append(line)

        if modified:
            self.backup_manager.backup_file(shadow_ide)
            write_text_atomic(shadow_ide, new_lines)
            return True
        return False

    def _revert_veh_mods(self, model: str, custom_parts: Optional[Set[str]] = None) -> bool:
        """Remove custom tuning parts in shadow veh_mods.ide that belong to this model."""
        shadow_veh_mods = os.path.join(self.shadow_dir, "veh_mods.ide")
        if not os.path.exists(shadow_veh_mods):
            return False

        with open(shadow_veh_mods, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        in_objs = False
        removed_count = 0
        model_clean = model.lower()
        parts_to_clean = set(custom_parts) if custom_parts else set()

        # Check if other active vehicles still reference any of these parts in carmods.dat
        other_models_parts = set()
        shadow_cm = os.path.join(self.shadow_dir, "carmods.dat")
        if os.path.exists(shadow_cm):
            try:
                with open(shadow_cm, "r", encoding="utf-8", errors="ignore") as f_cm:
                    for cm_l in f_cm:
                        cm_s = cm_l.strip().lower()
                        if cm_s and not cm_s.startswith("#") and not cm_s.startswith(";") and cm_s not in ("mods", "link", "end"):
                            cm_toks = [t.strip() for t in cm_s.split(",") if t.strip()]
                            if cm_toks and cm_toks[0] != model_clean:
                                for p in cm_toks[1:]:
                                    other_models_parts.add(p)
            except Exception:
                pass

        for line in lines:
            stripped = line.strip()
            if stripped.lower() == "objs":
                in_objs = True
                new_lines.append(line)
                continue
            if in_objs and stripped.lower() == "end":
                in_objs = False
                new_lines.append(line)
                continue
            if in_objs and stripped and not stripped.startswith("#") and not stripped.startswith(";"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                # Format: id, part_name, txd_name, draw_dist, flags
                if parts[0].isdigit() and int(parts[0]) > 1193:
                    part_pname = parts[1].lower() if len(parts) >= 2 else ""
                    if part_pname and part_pname in other_models_parts:
                        new_lines.append(line)
                        continue
                    is_match = False
                    if len(parts) >= 3 and parts[2].lower() == model_clean:
                        is_match = True
                    elif part_pname and part_pname in parts_to_clean:
                        is_match = True
                    if is_match:
                        removed_count += 1
                        continue
            new_lines.append(line)

        if removed_count > 0:
            self.backup_manager.backup_file(shadow_veh_mods)
            write_text_atomic(shadow_veh_mods, new_lines)
            return True
        return False

    def _revert_shopping(self, model: str, custom_parts: Optional[Set[str]] = None) -> bool:
        """Remove custom tuning parts for this model from shadow shopping.dat."""
        shadow_shopping = os.path.join(self.shadow_dir, "shopping.dat")
        if not os.path.exists(shadow_shopping):
            return False

        parts_to_clean = set(custom_parts) if custom_parts else self._get_model_tuning_parts(model)
        if not parts_to_clean:
            return False

        # Protect vanilla shopping items
        vanilla_shopping = os.path.join(self.vanilla_dir, "shopping.dat")
        vanilla_items = set()
        if os.path.exists(vanilla_shopping):
            try:
                with open(vanilla_shopping, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith("#") or s.startswith(";"):
                            continue
                        clean = s.split("#")[0].split(";")[0].strip()
                        toks = clean.split()
                        if toks:
                            if toks[0].lower() == "item" and len(toks) >= 2:
                                vanilla_items.add(toks[1].lower())
                            else:
                                vanilla_items.add(toks[0].lower())
            except Exception:
                pass

        # Check if other active vehicles still reference any of these parts in carmods.dat
        other_models_parts = set()
        shadow_cm = os.path.join(self.shadow_dir, "carmods.dat")
        if os.path.exists(shadow_cm):
            try:
                with open(shadow_cm, "r", encoding="utf-8", errors="ignore") as f_cm:
                    for cm_l in f_cm:
                        cm_s = cm_l.strip().lower()
                        if cm_s and not cm_s.startswith("#") and not cm_s.startswith(";") and cm_s not in ("mods", "link", "end"):
                            cm_toks = [t.strip() for t in cm_s.split(",") if t.strip()]
                            if cm_toks and cm_toks[0] != model.lower():
                                for p in cm_toks[1:]:
                                    other_models_parts.add(p)
            except Exception:
                pass

        parts_to_clean = {p.lower() for p in parts_to_clean if p.lower() not in vanilla_items and p.lower() not in other_models_parts}
        if not parts_to_clean:
            return False

        with open(shadow_shopping, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        modified = False

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                new_lines.append(line)
                continue

            clean = stripped.split("#")[0].split(";")[0].split("//")[0].strip()
            toks = clean.split()
            if not toks:
                new_lines.append(line)
                continue

            # Check section CarMods price lines: <part_name> <nametag> respect ...
            if toks[0].lower() in parts_to_clean:
                modified = True
                continue

            # Check workshop item lines: item <part_name>
            if toks[0].lower() == "item" and len(toks) >= 2 and toks[1].lower() in parts_to_clean:
                modified = True
                continue

            new_lines.append(line)

        if modified:
            self.backup_manager.backup_file(shadow_shopping)
            write_text_atomic(shadow_shopping, new_lines)
            return True
        return False

    def clean_orphaned_vehicle_entries(self) -> Dict[str, Any]:
        """
        Scan ModLoader to find all active model files (.dff), then purge any orphan entries
        in shadow data files that do not exist in vanilla data and have no corresponding .dff in modloader/.
        """
        if not self.game_path or not os.path.isdir(self.game_path):
            return {"success": False, "error": "Invalid game directory"}

        modloader_base = os.path.join(self.game_path, "modloader")
        if not os.path.isdir(modloader_base):
            return {"success": True, "purged": {}}

        active_dffs = set()
        for root, _, files in os.walk(modloader_base):
            for fn in files:
                if fn.lower().endswith(".dff"):
                    active_dffs.add(os.path.splitext(fn)[0].lower())

        purged = {
            "vehicles_ide": [],
            "handling_cfg": [],
            "carcols_dat": [],
            "carmods_dat": [],
            "veh_mods_ide": [],
            "shopping_dat": [],
            "audio_settings": [],
            "special_features": []
        }

        # 1. Clean vehicles.ide
        shadow_ide = os.path.join(self.shadow_dir, "vehicles.ide")
        vanilla_ide = os.path.join(self.vanilla_dir, "vehicles.ide")
        if os.path.exists(shadow_ide):
            vanilla_models = set(MODEL_TO_ID.keys())
            if os.path.exists(vanilla_ide):
                with open(vanilla_ide, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip().startswith("#"):
                            parts = [p.strip() for p in line.split(",") if p.strip()]
                            if len(parts) >= 2:
                                vanilla_models.add(parts[1].lower())

            with open(shadow_ide, "r", encoding="utf-8", errors="ignore") as f:
                ide_lines = f.readlines()

            new_ide_lines = []
            modified_ide = False
            for line in ide_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    parts = [p.strip() for p in stripped.split(",") if p.strip()]
                    if len(parts) >= 2:
                        m = parts[1].lower()
                        if m not in vanilla_models and m not in active_dffs:
                            purged["vehicles_ide"].append(m)
                            modified_ide = True
                            continue
                new_ide_lines.append(line)

            if modified_ide:
                self.backup_manager.backup_file(shadow_ide)
                write_text_atomic(shadow_ide, new_ide_lines)

        # 2. Clean handling.cfg
        shadow_h = os.path.join(self.shadow_dir, "handling.cfg")
        vanilla_h = os.path.join(self.vanilla_dir, "handling.cfg")
        if os.path.exists(shadow_h):
            vanilla_handling_ids = set()
            if os.path.exists(vanilla_h):
                with open(vanilla_h, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if s and not s.startswith(";") and not s.startswith("#") and not s.startswith("//"):
                            parts = s.split()
                            if parts:
                                if parts[0][0] in ("!", "$", "%", "^"):
                                    rem = parts[0][1:]
                                    ident = rem.lower() if rem else (parts[1].lower() if len(parts) > 1 else "")
                                else:
                                    ident = parts[0].lower()
                                if ident:
                                    vanilla_handling_ids.add(ident)

            with open(shadow_h, "r", encoding="utf-8", errors="ignore") as f:
                h_lines = f.readlines()

            new_h_lines = []
            modified_h = False
            for line in h_lines:
                s = line.strip()
                if s and not s.startswith(";") and not s.startswith("#") and not s.startswith("//"):
                    parts = s.split()
                    if parts:
                        pfx = ""
                        if parts[0][0] in ("!", "$", "%", "^"):
                            pfx = parts[0][0]
                            rem = parts[0][1:]
                            ident = rem.lower() if rem else (parts[1].lower() if len(parts) > 1 else "")
                        else:
                            ident = parts[0].lower()
                        # Anim group lines (^ 0 ...) are not vehicle handling
                        if pfx == "^":
                            new_h_lines.append(line)
                            continue
                        if ident and ident not in vanilla_handling_ids and ident not in active_dffs:
                            purged["handling_cfg"].append(ident)
                            modified_h = True
                            continue
                new_h_lines.append(line)

            if modified_h:
                self.backup_manager.backup_file(shadow_h)
                write_text_atomic(shadow_h, new_h_lines)

        # 3. Clean carcols.dat
        shadow_c = os.path.join(self.shadow_dir, "carcols.dat")
        vanilla_c = os.path.join(self.vanilla_dir, "carcols.dat")
        if os.path.exists(shadow_c):
            vanilla_carcols_models = set()
            if os.path.exists(vanilla_c):
                with open(vanilla_c, "r", encoding="utf-8", errors="ignore") as f:
                    cur_sec = None
                    for line in f:
                        s = line.strip()
                        low = s.lower()
                        if low in ("col", "car", "car4"):
                            cur_sec = low
                            continue
                        if low == "end":
                            cur_sec = None
                            continue
                        if cur_sec in ("car", "car4") and s and not s.startswith("#"):
                            parts = [p.strip() for p in s.split(",") if p.strip()]
                            if parts:
                                vanilla_carcols_models.add(parts[0].lower())

            with open(shadow_c, "r", encoding="utf-8", errors="ignore") as f:
                c_lines = f.readlines()

            new_c_lines = []
            modified_c = False
            cur_sec = None
            for line in c_lines:
                s = line.strip()
                low = s.lower()
                if low in ("col", "car", "car4"):
                    cur_sec = low
                    new_c_lines.append(line)
                    continue
                if low == "end":
                    cur_sec = None
                    new_c_lines.append(line)
                    continue
                if cur_sec in ("car", "car4") and s and not s.startswith("#"):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if parts:
                        m = parts[0].lower()
                        if m not in vanilla_carcols_models and m not in active_dffs:
                            purged["carcols_dat"].append(m)
                            modified_c = True
                            continue
                # Also purge rogue vehicle lines outside sections
                elif cur_sec is None and s and not s.startswith("#"):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if len(parts) >= 2 and all(p.isdigit() for p in parts[1:]):
                        m = parts[0].lower()
                        if m not in vanilla_carcols_models and m not in active_dffs:
                            purged["carcols_dat"].append(m)
                            modified_c = True
                            continue
                        else:
                            # Model exists in active_dffs but was stranded after end: strip from after end
                            modified_c = True
                            continue
                new_c_lines.append(line)

            if modified_c:
                self.backup_manager.backup_file(shadow_c)
                write_text_atomic(shadow_c, new_c_lines)

        # 4. Clean carmods.dat
        shadow_cm = os.path.join(self.shadow_dir, "carmods.dat")
        vanilla_cm = os.path.join(self.vanilla_dir, "carmods.dat")
        if os.path.exists(shadow_cm):
            vanilla_carmods_models = set()
            vanilla_links = set()
            vanilla_parts = set()
            if os.path.exists(vanilla_cm):
                with open(vanilla_cm, "r", encoding="utf-8", errors="ignore") as f:
                    cur_sec = None
                    for line in f:
                        s = line.strip()
                        low = s.lower()
                        if low in ("mods", "link"):
                            cur_sec = low
                            continue
                        if low == "end":
                            cur_sec = None
                            continue
                        if cur_sec == "mods" and s and not s.startswith("#"):
                            parts = [p.strip().lower() for p in s.split(",") if p.strip()]
                            if parts:
                                vanilla_carmods_models.add(parts[0])
                                for p in parts[1:]:
                                    vanilla_parts.add(p)
                        elif cur_sec == "link" and s and not s.startswith("#"):
                            parts = [p.strip().lower() for p in s.split(",") if p.strip()]
                            if len(parts) >= 2:
                                vanilla_links.add(frozenset((parts[0], parts[1])))
                                vanilla_parts.add(parts[0])
                                vanilla_parts.add(parts[1])

            with open(shadow_cm, "r", encoding="utf-8", errors="ignore") as f:
                cm_lines = f.readlines()

            new_cm_lines = []
            modified_cm = False
            cur_sec = None
            for line in cm_lines:
                s = line.strip()
                low = s.lower()
                if low in ("mods", "link"):
                    cur_sec = low
                    new_cm_lines.append(line)
                    continue
                if low == "end":
                    cur_sec = None
                    new_cm_lines.append(line)
                    continue
                if cur_sec == "mods" and s and not s.startswith("#"):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if parts:
                        m = parts[0].lower()
                        if m not in vanilla_carmods_models and m not in active_dffs:
                            purged["carmods_dat"].append(m)
                            modified_cm = True
                            continue
                        else:
                            clean_parts = [parts[0]]
                            line_changed = False
                            for p in parts[1:]:
                                pl = p.lower()
                                if pl in vanilla_parts or pl in active_dffs:
                                    clean_parts.append(p)
                                else:
                                    line_changed = True
                            if line_changed:
                                modified_cm = True
                                new_cm_lines.append(", ".join(clean_parts) + "\n")
                                continue
                elif cur_sec == "link" and s and not s.startswith("#"):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if len(parts) >= 2:
                        p1, p2 = parts[0].lower(), parts[1].lower()
                        pair = frozenset((p1, p2))
                        if pair not in vanilla_links:
                            if p1 not in active_dffs or p2 not in active_dffs:
                                purged["carmods_dat"].append(f"link:{parts[0]},{parts[1]}")
                                modified_cm = True
                                continue
                new_cm_lines.append(line)

            if modified_cm:
                self.backup_manager.backup_file(shadow_cm)
                write_text_atomic(shadow_cm, new_cm_lines)

        # 5. Clean veh_mods.ide
        shadow_vm = os.path.join(self.shadow_dir, "veh_mods.ide")
        if os.path.exists(shadow_vm):
            with open(shadow_vm, "r", encoding="utf-8", errors="ignore") as f:
                vm_lines = f.readlines()

            new_vm_lines = []
            modified_vm = False
            in_objs = False
            for line in vm_lines:
                s = line.strip()
                low = s.lower()
                if low == "objs":
                    in_objs = True
                    new_vm_lines.append(line)
                    continue
                if in_objs and low == "end":
                    in_objs = False
                    new_vm_lines.append(line)
                    continue
                if in_objs and s and not s.startswith("#") and not s.startswith(";"):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    # Format: id, part_name, txd_name, draw_dist, flags
                    if parts and parts[0].isdigit() and int(parts[0]) > 1193:
                        part_name = parts[1].lower() if len(parts) >= 2 else ""
                        if part_name and part_name not in active_dffs:
                            purged["veh_mods_ide"].append(part_name)
                            modified_vm = True
                            continue
                new_vm_lines.append(line)

            if modified_vm:
                self.backup_manager.backup_file(shadow_vm)
                write_text_atomic(shadow_vm, new_vm_lines)

        # 6. Clean shopping.dat
        shadow_shop = os.path.join(self.shadow_dir, "shopping.dat")
        vanilla_shop = os.path.join(self.vanilla_dir, "shopping.dat")
        if os.path.exists(shadow_shop):
            vanilla_shop_items = set()
            if os.path.exists(vanilla_shop):
                try:
                    with open(vanilla_shop, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            s = line.strip()
                            if not s or s.startswith("#") or s.startswith(";"):
                                continue
                            clean = s.split("#")[0].split(";")[0].strip()
                            toks = clean.split()
                            if toks:
                                if toks[0].lower() == "item" and len(toks) >= 2:
                                    vanilla_shop_items.add(toks[1].lower())
                                else:
                                    vanilla_shop_items.add(toks[0].lower())
                except Exception:
                    pass

            with open(shadow_shop, "r", encoding="utf-8-sig", errors="ignore") as f:
                shop_lines = f.readlines()

            new_shop_lines = []
            modified_shop = False
            for line in shop_lines:
                s = line.strip()
                if not s or s.startswith("#") or s.startswith(";"):
                    new_shop_lines.append(line)
                    continue

                clean = s.split("#")[0].split(";")[0].split("//")[0].strip()
                toks = clean.split()
                if not toks:
                    new_shop_lines.append(line)
                    continue

                # section carmod1/2/3: item <part_name>
                if toks[0].lower() == "item" and len(toks) >= 2:
                    p = toks[1].lower()
                    if p not in vanilla_shop_items and p not in active_dffs:
                        purged["shopping_dat"].append(p)
                        modified_shop = True
                        continue
                # section CarMods / section prices: <part_name> <nametag> respect ...
                else:
                    p = toks[0].lower()
                    # Skip section keywords
                    if p not in ("section", "end") and p not in vanilla_shop_items and p not in active_dffs:
                        purged["shopping_dat"].append(p)
                        modified_shop = True
                        continue

                new_shop_lines.append(line)

            if modified_shop:
                self.backup_manager.backup_file(shadow_shop)
                write_text_atomic(shadow_shop, new_shop_lines)

        # 7. Clean gtasa_vehicleAudioSettings.cfg
        try:
            audio_purged = self.fla_mgr.clean_misplaced_or_orphan_audio(active_dffs)
            if audio_purged:
                purged["audio_settings"].extend(audio_purged)
        except Exception as e:
            print(f"Warning during audio orphan cleanup: {e}")

        # 8. Clean model_special_features.dat
        try:
            feat_file = os.path.join(self.game_path, "data", "model_special_features.dat")
            if os.path.isfile(feat_file):
                with open(feat_file, "r", encoding="utf-8", errors="ignore") as f:
                    feat_lines = f.readlines()
                new_feat_lines = []
                feat_modified = False
                for line in feat_lines:
                    s = line.strip()
                    if s and not s.startswith("#") and not s.startswith(";"):
                        parts = s.split()
                        if parts:
                            m = parts[0].lower()
                            if m not in MODEL_TO_ID and m not in active_dffs:
                                purged["special_features"].append(m)
                                feat_modified = True
                                continue
                    new_feat_lines.append(line)
                if feat_modified:
                    self.backup_manager.backup_file(feat_file)
                    write_text_atomic(feat_file, new_feat_lines)
        except Exception as e:
            print(f"Warning during special features orphan cleanup: {e}")

        return {"success": True, "purged": purged}
