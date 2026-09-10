"""
Fastman92 Limit Adjuster (FLA92) Manager:
Handles gtasa_vehicleAudioSettings.cfg and model_special_features.dat.
Includes automatic .bak backup protection and semantic feature toggling (pop-up lights, sirens, suspensions).
"""

import os
import re
import shutil
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple
from .vanilla_data import SPECIAL_FEATURE_TARGETS, NATIVE_SPECIAL_FEATURES, VANILLA_AUDIO_SETTINGS
from .backup_manager import BackupManager
from .atomic_io import write_text_atomic

SOUND_PRESETS = [
    {
        "id": "default",
        "label": "Vanilla Default",
        "label_zh": "Vanilla Default",
        "label_en": "Vanilla Default",
        "vehicle": "Default",
        "is_dynamic": True,
        "bank_a": 0,
        "bank_b": 0,
        "raw_line": ""
    },
    {
        "id": "infernus",
        "label": "Infernus",
        "label_zh": "Infernus",
        "label_en": "Infernus",
        "vehicle": "Infernus",
        "bank_a": 38,
        "bank_b": 37,
        "raw_line": VANILLA_AUDIO_SETTINGS.get("infernus", "infernus 0 38 37 1 0.9 1.0 8 1.12246 2 0 6 0 2 0.0")
    },
    {
        "id": "cheetah",
        "label": "Cheetah",
        "label_zh": "Cheetah",
        "label_en": "Cheetah",
        "vehicle": "Cheetah",
        "bank_a": 103,
        "bank_b": 102,
        "raw_line": VANILLA_AUDIO_SETTINGS.get("cheetah", "cheetah 0 103 102 1 0.9 1.0 8 1.0 2 0 5 0 2 0.0")
    },
    {
        "id": "sultan",
        "label": "Sultan",
        "label_zh": "Sultan",
        "label_en": "Sultan",
        "vehicle": "Sultan",
        "bank_a": 87,
        "bank_b": 86,
        "raw_line": VANILLA_AUDIO_SETTINGS.get("sultan", "sultan 0 87 86 0 1.0 1.0 7 1.18921 2 2 6 0 45 0.0")
    },
    {
        "id": "elegy",
        "label": "Elegy",
        "label_zh": "Elegy",
        "label_en": "Elegy",
        "vehicle": "Elegy",
        "bank_a": 8,
        "bank_b": 7,
        "raw_line": VANILLA_AUDIO_SETTINGS.get("elegy", "elegy 0 8 7 0 0.85 1.0 3 1.12246 2 2 8 0 1 0.0")
    },
    {
        "id": "sabre",
        "label": "Sabre",
        "label_zh": "Sabre",
        "label_en": "Sabre",
        "vehicle": "Sabre",
        "bank_a": 46,
        "bank_b": 45,
        "raw_line": VANILLA_AUDIO_SETTINGS.get("sabre", "sabre 0 46 45 0 0.85 1.0 8 0.943874 1 0 10 0 1 0.0")
    },
    {
        "id": "rancher",
        "label": "Rancher",
        "label_zh": "Rancher",
        "label_en": "Rancher",
        "vehicle": "Rancher",
        "bank_a": 99,
        "bank_b": 98,
        "raw_line": VANILLA_AUDIO_SETTINGS.get("rancher", "rancher 0 99 98 0 0.85 1.0 5 0.943874 2 0 3 0 0 0.0")
    }
]

class FLAManager:
    def __init__(self, game_path: str, backup_manager: Optional[BackupManager] = None):
        self.game_path = os.path.normpath(game_path) if (game_path and game_path.strip() != ".") else ""
        self.ini_path = os.path.join(self.game_path, "fastman92limitAdjuster_GTASA.ini") if self.game_path else ""
        self.audio_path = os.path.join(self.game_path, "data", "gtasa_vehicleAudioSettings.cfg") if self.game_path else ""
        self.special_path = os.path.join(self.game_path, "data", "model_special_features.dat") if self.game_path else ""
        self.backup_manager = backup_manager or BackupManager(game_dir=self.game_path)

    def find_fla_installation(self) -> Dict[str, Any]:
        """
        Comprehensive search for Fastman92 Limit Adjuster binaries (.asi/.dll) 
        and configuration files (.ini) across root, scripts/, plugins/, and modloader/.
        Resolves the issue where newly installed FLA has no .ini before first game launch.
        """
        detected_asi = None
        detected_ini = None

        if not self.game_path or not os.path.isdir(self.game_path):
            return {
                "installed": False,
                "has_asi": False,
                "has_ini": False,
                "ini_orphaned": False,
                "asi_path": None,
                "ini_path": self.ini_path,
                "is_pending_launch": False
            }

        search_dirs = [
            self.game_path,
            os.path.join(self.game_path, "scripts"),
            os.path.join(self.game_path, "plugins"),
        ]

        # Only Fastman92-branded files count. Matching a generic
        # "*limitadjuster*" name would mistake other mods for FLA (e.g. Open
        # Limit Adjuster's III.VC.SA.LimitAdjuster.asi / .ini).
        def _is_fla_name(name_lower: str) -> bool:
            return "fastman92" in name_lower

        # 1. Search root, scripts/, plugins/
        for sdir in search_dirs:
            if not os.path.isdir(sdir):
                continue
            try:
                for fname in os.listdir(sdir):
                    f_lower = fname.lower()
                    if not _is_fla_name(f_lower):
                        continue
                    full_p = os.path.join(sdir, fname)
                    if (f_lower.endswith(".asi") or f_lower.endswith(".dll")) and not detected_asi:
                        detected_asi = full_p
                    elif f_lower.endswith(".ini") and not detected_ini:
                        detected_ini = full_p
            except Exception:
                pass

        # 2. Search modloader/ directory
        modloader_dir = os.path.join(self.game_path, "modloader")
        if os.path.isdir(modloader_dir):
            try:
                for root, _, files in os.walk(modloader_dir):
                    for fname in files:
                        f_lower = fname.lower()
                        if not _is_fla_name(f_lower):
                            continue
                        full_p = os.path.join(root, fname)
                        if (f_lower.endswith(".asi") or f_lower.endswith(".dll")) and not detected_asi:
                            detected_asi = full_p
                        elif f_lower.endswith(".ini") and not detected_ini:
                            detected_ini = full_p
                    if detected_asi and detected_ini:
                        break
            except Exception:
                pass

        # If ini not found by scan, check standard default ini_path
        if not detected_ini and self.ini_path and os.path.exists(self.ini_path):
            detected_ini = self.ini_path

        has_asi = bool(detected_asi)
        has_ini = bool(detected_ini)
        # A config file alone cannot load FLA: the ASI/DLL must be present.
        # An ini without it is an orphan left behind after removing FLA.
        installed = has_asi
        is_pending_launch = bool(has_asi and not has_ini)

        return {
            "installed": installed,
            "has_asi": has_asi,
            "has_ini": has_ini,
            "ini_orphaned": bool(has_ini and not has_asi),
            "asi_path": detected_asi,
            "ini_path": detected_ini or self.ini_path,
            "is_pending_launch": is_pending_launch
        }

    def get_fla_status(self) -> Dict[str, Any]:
        """Check FLA installation and active addons."""
        fla_info = self.find_fla_installation()
        has_ini = fla_info["has_ini"]
        has_asi = fla_info["has_asi"]
        installed = fla_info["installed"]
        is_pending_launch = fla_info["is_pending_launch"]

        has_audio = bool(self.audio_path and os.path.exists(self.audio_path))
        has_special = bool(self.special_path and os.path.exists(self.special_path))

        audio_loader_enabled = False
        special_loader_enabled = False

        # Loader switches only take effect when the FLA ASI actually loads;
        # an orphan ini must not report the loaders as enabled.
        effective_ini = fla_info["ini_path"] if (has_ini and installed) else None
        if effective_ini and os.path.isfile(effective_ini):
            try:
                with open(effective_ini, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or line.startswith(";"):
                            continue
                        if "Enable vehicle audio loader" in line and "= 1" in line:
                            audio_loader_enabled = True
                        elif "Enable model special feature loader" in line and "= 1" in line:
                            special_loader_enabled = True
            except Exception:
                pass
        elif is_pending_launch:
            # If ASI is installed but game hasn't been launched yet to generate ini,
            # loaders are supported and active by default in fastman92 Limit Adjuster.
            audio_loader_enabled = True
            special_loader_enabled = True

        return {
            "installed": installed,
            "has_fla_asi": has_asi,
            "has_fla_ini": has_ini,
            "ini_orphaned": bool(fla_info.get("ini_orphaned")),
            "is_pending_launch": is_pending_launch,
            "asi_path": fla_info["asi_path"],
            "ini_path": fla_info["ini_path"],
            "has_audio_file": has_audio,
            "has_special_file": has_special,
            "audio_loader_enabled": audio_loader_enabled,
            "special_loader_enabled": special_loader_enabled,
            "special_count": len(self.get_all_special_features()) if has_special else 0,
            "audio_count": len(self.get_all_audio_settings()) if has_audio else 0,
        }

    # ---------------- Special Features ----------------

    def get_all_special_features(self) -> Dict[str, str]:
        """Returns mapping of model_name -> standard_model_name (e.g. cheetah -> zr350)."""
        mapping = {}
        if not os.path.exists(self.special_path):
            return mapping

        with open(self.special_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    mapping[parts[0].lower()] = parts[1].lower()
        return mapping

    def get_feature_for_model(self, model: str) -> Optional[Dict[str, Any]]:
        model_lower = (model or "").strip().lower()
        mapping = self.get_all_special_features()
        target = mapping.get(model_lower)
        if target:
            target_info = SPECIAL_FEATURE_TARGETS.get(target, {
                "label": target,
                "label_en": target,
                "desc": "Custom special feature",
                "desc_en": f"Custom special feature ({target})"
            })
            nat_info = NATIVE_SPECIAL_FEATURES.get(target, {})
            return {
                "target": target,
                "label": target_info.get("label", target),
                "label_zh": target_info.get("label", target),
                "label_en": target_info.get("label_en", nat_info.get("label_en", target)),
                "desc": target_info.get("desc", ""),
                "desc_en": target_info.get("desc_en", nat_info.get("desc_en", "")),
                "is_native": False,
                "icon": nat_info.get("icon", "⭐")
            }

        # Native GTA:SA vehicles with hardcoded special features (zr350, sandking, etc.)
        if model_lower in NATIVE_SPECIAL_FEATURES:
            nat = NATIVE_SPECIAL_FEATURES[model_lower]
            return {
                "target": model_lower,
                "label": nat["label_zh"],
                "label_zh": nat["label_zh"],
                "label_en": nat["label_en"],
                "desc": nat["desc_zh"],
                "desc_en": nat["desc_en"],
                "is_native": True,
                "icon": nat.get("icon", "⭐")
            }
        return None

    def set_special_feature(self, model: str, target_feature: Optional[str]) -> bool:
        """
        Set or remove special feature for model.
        e.g. set_special_feature('cheetah', 'zr350')
        If target_feature is None or empty, removes the feature.
        """
        if not os.path.exists(self.special_path):
            try:
                os.makedirs(os.path.dirname(self.special_path), exist_ok=True)
                write_text_atomic(self.special_path, "# model_special_features.dat (FLA92)\n")
            except Exception:
                return False

        self._backup_file(self.special_path)

        lines = []
        model_lower = model.lower()
        found = False

        with open(self.special_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(";"):
                parts = stripped.split()
                if len(parts) >= 2 and parts[0].lower() == model_lower:
                    found = True
                    if target_feature:
                        new_lines.append(f"{model_lower} {target_feature.lower()}\n")
                    continue  # if removing, don't re-add
            new_lines.append(line)

        if not found and target_feature:
            new_lines.append(f"{model_lower} {target_feature.lower()}\n")

        write_text_atomic(self.special_path, new_lines)
        return True

    def remove_special_feature(self, model: str) -> bool:
        """Remove special feature entry for model."""
        return self.set_special_feature(model, None)

    # ---------------- Audio Settings ----------------

    def get_all_audio_settings(self) -> Dict[str, str]:
        """Returns dict of model_name -> raw audio line."""
        settings = {}
        if not os.path.exists(self.audio_path):
            return settings

        with open(self.audio_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                parts = line.split()
                if len(parts) >= 8:
                    model = parts[0].lower()
                    settings[model] = line
        return settings

    def get_audio_for_model(self, model: str) -> Optional[str]:
        return self.get_all_audio_settings().get(model.lower())

    def update_audio_setting(self, model: str, raw_line: str) -> bool:
        """Add or update an audio configuration line for a vehicle."""
        return self.update_audio_settings([(model, raw_line)])

    @staticmethod
    def _audio_row_model(line: str) -> Optional[str]:
        parts = line.split()
        if len(parts) < 8 or not re.fullmatch(r"[A-Za-z0-9_]+", parts[0]):
            return None
        try:
            for value in parts[1:4]:
                int(value)
        except ValueError:
            return None
        return parts[0].lower()

    AUDIO_COLUMN_WIDTHS = [44, 14, 7, 7, 10, 13, 13, 10, 13, 12, 11, 11, 12, 18]

    @classmethod
    def format_audio_line(cls, model_or_line: str, raw_line: Optional[str] = None) -> str:
        """
        Format an FLA gtasa_vehicleAudioSettings.cfg line so that columns align perfectly
        with the fastman92 Limit Adjuster audio settings standard header (columns A through O).
        """
        if raw_line is None:
            raw_clean = str(model_or_line or "").strip()
            model = None
        else:
            raw_clean = str(raw_line or "").strip()
            model = str(model_or_line or "").strip().lower()

        tokens = raw_clean.split()
        if not tokens:
            return ""
        if model:
            try:
                int(tokens[0])
                tokens.insert(0, model)
            except ValueError:
                tokens[0] = model
        else:
            tokens[0] = tokens[0].lower()

        widths = cls.AUDIO_COLUMN_WIDTHS
        if len(tokens) >= len(widths) + 1:
            res = "".join(f"{tokens[i]:<{widths[i]}}" for i in range(len(widths)))
            res += " ".join(tokens[len(widths):])
            return res
        elif len(tokens) > 1:
            res = f"{tokens[0]:<{widths[0]}}"
            for i in range(1, len(tokens)):
                w = widths[i] if i < len(widths) else 10
                res += f"{tokens[i]:<{w}}"
            return res.rstrip()
        return tokens[0]

    def update_audio_settings(self, settings: List[Tuple[str, str]]) -> bool:
        """Apply one audio batch with at most one backup, and none for a no-op."""
        normalized = {}
        for model, raw_line in settings:
            model_lower = str(model or "").strip().lower()
            raw_clean = str(raw_line or "").strip()
            if ("\n" in raw_clean or "\r" in raw_clean
                    or not model_lower or self._audio_row_model(raw_clean) != model_lower):
                return False
            normalized[model_lower] = self.format_audio_line(model_lower, raw_clean)
        if not normalized:
            return True
        return self._rewrite_audio_settings(normalized, set())

    def remove_audio_setting(self, model: str) -> bool:
        """
        Revert audio setting for model.
        If model is a vanilla vehicle, restores its authentic vanilla FLA audio line.
        If model is an addon vehicle, removes its row.
        """
        return self.remove_audio_settings([model])

    def remove_audio_settings(self, models: List[str]) -> bool:
        updates = {}
        removed = set()
        for m in models:
            m_lower = str(m or "").strip().lower()
            if not m_lower:
                continue
            if m_lower in VANILLA_AUDIO_SETTINGS:
                # Revert vanilla vehicle to its authentic FLA default
                updates[m_lower] = self.format_audio_line(m_lower, VANILLA_AUDIO_SETTINGS[m_lower])
            else:
                # Addon vehicle: remove from file
                removed.add(m_lower)
        return self._rewrite_audio_settings(updates, removed)

    def _rewrite_audio_settings(self, updates: Dict[str, str], removed: set) -> bool:
        temp_path = None
        try:
            exists = os.path.isfile(self.audio_path)
            if exists:
                with open(self.audio_path, "rb") as f:
                    original = f.read()
            elif not updates:
                return True
            else:
                original = b""
            text = original.decode("utf-8", errors="surrogateescape")
            newline = "\r\n" if "\r\n" in text else "\n"
            lines = text.splitlines(keepends=True)
            if not exists:
                lines = ["# gtasa_vehicleAudioSettings.cfg (FLA92)\n", ";\n", ";\n", ";the end\n"]

            # Separate the trailer and recover valid rows written after (or
            # glued to) it by older versions. Preserve unrelated comment bytes.
            body, trailer, recovered = lines, [], []
            for idx, line in enumerate(lines):
                match = re.fullmatch(r"([ \t]*;[ \t]*the[ \t]+end)(.*)",
                                     line.rstrip("\r\n"), re.IGNORECASE)
                if not match:
                    continue
                suffix = match.group(2).strip()
                if suffix and not self._audio_row_model(suffix):
                    continue
                start = idx
                while start > 0 and lines[start - 1].strip() in ("", ";"):
                    start -= 1
                body = lines[:start]
                trailer = lines[start:idx] + [match.group(1) + newline if suffix else line]
                if suffix:
                    recovered.append(suffix + newline)
                for tail in lines[idx + 1:]:
                    if self._audio_row_model(tail):
                        recovered.append(tail)
                    else:
                        trailer.append(tail)
                break

            # Separate body into standard vehicles section and added vehicles section if header exists
            added_idx = None
            for idx, line in enumerate(body):
                if re.search(r"added\s+vehicles", line, re.IGNORECASE):
                    added_idx = idx
                    break

            # Last existing row wins; explicit updates take precedence. Collapse
            # duplicates without reformatting unchanged aligned parameter rows.
            records = {}
            for line in body + recovered:
                key = self._audio_row_model(line)
                if key:
                    records[key] = line
            for key, raw in updates.items():
                if key not in records or records[key].split() != raw.split():
                    records[key] = raw + newline

            output = []

            if added_idx is not None:
                std_body = body[:added_idx]
                added_header_and_body = body[added_idx:]
                added_header_end = 1
                while added_header_end < len(added_header_and_body):
                    s = added_header_and_body[added_header_end].strip()
                    if s.startswith(";") or s.startswith("#") or not s:
                        added_header_end += 1
                    else:
                        break
                added_header = added_header_and_body[:added_header_end]
                added_data = added_header_and_body[added_header_end:]

                std_emitted = set()
                # 1. Emit standard vehicles section
                for line in std_body:
                    key = self._audio_row_model(line)
                    if key:
                        if key in VANILLA_AUDIO_SETTINGS:
                            if key not in std_emitted:
                                output.append(records[key])
                                std_emitted.add(key)
                        else:
                            # Misplaced addon vehicle in standard section; will emit in added section
                            pass
                    else:
                        output.append(line)

                # Any standard vehicles in records that were missing from std_body:
                for key, line in records.items():
                    if key in VANILLA_AUDIO_SETTINGS and key not in std_emitted:
                        output.append(line)
                        std_emitted.add(key)

                # 2. Emit added vehicles section
                output.extend(added_header)

                added_emitted = set()
                for line in added_data:
                    key = self._audio_row_model(line)
                    if key:
                        if key in VANILLA_AUDIO_SETTINGS:
                            # Strip vanilla vehicles from added vehicles section
                            continue
                        if key not in removed and key not in added_emitted:
                            output.append(records[key])
                            added_emitted.add(key)
                    else:
                        output.append(line)

                # Emit any new addon vehicles in records
                for key, line in records.items():
                    if key not in VANILLA_AUDIO_SETTINGS and key not in removed and key not in added_emitted:
                        output.append(line)
                        added_emitted.add(key)
            else:
                # Flat format (e.g. unit tests or minimal files without section markers)
                emitted = set()
                for line in body:
                    key = self._audio_row_model(line)
                    if key:
                        if key not in removed and key not in emitted:
                            output.append(records[key])
                            emitted.add(key)
                    else:
                        output.append(line)
                for key, line in records.items():
                    if key not in removed and key not in emitted:
                        output.append(line)
                        emitted.add(key)

            # 3. Emit trailer
            output.extend(trailer)

            # Only add missing line breaks at boundaries, keeping a valid
            # original trailer's final newline (or lack of it) unchanged.
            result = "".join(line if i == len(output) - 1 or line.endswith(("\n", "\r"))
                             else line + newline for i, line in enumerate(output))
            encoded = result.encode("utf-8", errors="surrogateescape")
            if encoded == original:
                return True
            os.makedirs(os.path.dirname(self.audio_path), exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=".vehicle_audio_", suffix=".tmp",
                                             dir=os.path.dirname(self.audio_path))
            with os.fdopen(fd, "wb") as f:
                f.write(encoded)
            if exists:
                self._backup_file(self.audio_path)
            os.replace(temp_path, self.audio_path)
            temp_path = None
            return True
        except OSError:
            return False
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def clean_misplaced_or_orphan_audio(self, active_dffs: Set[str]) -> List[str]:
        """
        Scan gtasa_vehicleAudioSettings.cfg and:
        1. Completely purge orphan addon vehicles whose .dff is not in active_dffs.
        2. Clean up any misplaced vanilla vehicle entries lingering in the 'added vehicles' section,
           ensuring standard vanilla entries are safely situated in the standard vehicles section.
        """
        if not self.audio_path or not os.path.isfile(self.audio_path):
            return []

        active_lower = {str(d).lower() for d in active_dffs}
        purged = []
        updates = {}
        removed = set()

        try:
            with open(self.audio_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return []

        in_added_section = False
        std_models_present = set()

        for line in lines:
            s = line.strip()
            if re.search(r"added\s+vehicles", line, re.IGNORECASE):
                in_added_section = True
                continue
            if re.search(r";\s*the\s+end", line, re.IGNORECASE):
                break
            if not s or s.startswith(";") or s.startswith("#"):
                continue

            m = self._audio_row_model(s)
            if not m:
                continue

            if in_added_section:
                if m in VANILLA_AUDIO_SETTINGS:
                    # Misplaced vanilla vehicle in added vehicles section!
                    purged.append(f"{m} (purged from addon section)")
                    if m not in std_models_present and m not in updates:
                        updates[m] = self.format_audio_line(m, VANILLA_AUDIO_SETTINGS[m])
                elif m not in active_lower:
                    # Orphan addon vehicle without active .dff!
                    purged.append(m)
                    removed.add(m)
            else:
                std_models_present.add(m)
                if m not in VANILLA_AUDIO_SETTINGS and m not in active_lower:
                    # Addon vehicle in standard section without active .dff!
                    purged.append(m)
                    removed.add(m)

        if purged or updates or removed:
            self._rewrite_audio_settings(updates, removed)

        return purged

    # ---------------- Comprehensive Per-Model FLA Inspection ----------------

    def get_model_fla_detail(self, model: str) -> Dict[str, Any]:
        """
        Inspect both model_special_features.dat and gtasa_vehicleAudioSettings.cfg
        specifically for the given vehicle model.
        Returns live file status, target mapping, raw file lines, and matched audio preset.
        """
        model_lower = (model or "").strip().lower()

        # 1. Special Feature
        special_exists = False
        is_native = False
        special_target = None
        special_label = None
        special_label_en = None
        special_desc = None
        special_desc_en = None
        special_raw = None

        if os.path.exists(self.special_path):
            with open(self.special_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                        continue
                    parts = stripped.split()
                    if len(parts) >= 2 and parts[0].lower() == model_lower:
                        special_exists = True
                        is_native = False
                        special_target = parts[1].lower()
                        special_raw = stripped
                        target_info = SPECIAL_FEATURE_TARGETS.get(special_target, {
                            "label": special_target,
                            "label_en": special_target,
                            "desc": f"Mapped to {special_target} exclusive feature",
                            "desc_en": f"Vehicle mechanics mapped to {special_target}"
                        })
                        nat_info = NATIVE_SPECIAL_FEATURES.get(special_target, {})
                        special_label = target_info["label"]
                        special_label_en = target_info.get("label_en", nat_info.get("label_en", target_info["label"]))
                        special_desc = target_info["desc"]
                        special_desc_en = target_info.get("desc_en", nat_info.get("desc_en", target_info["desc"]))
                        break

        # Fallback: check if vehicle is natively an archetype with built-in mechanics (zr350, sandking, etc.)
        if not special_exists and model_lower in NATIVE_SPECIAL_FEATURES:
            nat = NATIVE_SPECIAL_FEATURES[model_lower]
            special_exists = True
            is_native = True
            special_target = model_lower
            special_label = nat["label_zh"]
            special_label_en = nat["label_en"]
            special_desc = nat["desc_zh"]
            special_desc_en = nat["desc_en"]
            special_raw = f"# (GTA:SA Native Archetype / Vanilla Feature) {model_lower}"
            special_raw_en = f"# (GTA:SA Native Archetype) {model_lower}"

        # 2. Vehicle Audio
        audio_exists = False
        audio_raw = None
        matched_preset_id = None
        matched_preset_label = None
        matched_preset_label_zh = None
        matched_preset_label_en = None

        is_vanilla = model_lower in VANILLA_AUDIO_SETTINGS
        vanilla_raw = VANILLA_AUDIO_SETTINGS.get(model_lower)
        vanilla_line = self.format_audio_line(model_lower, vanilla_raw) if vanilla_raw else None
        is_modified = False

        if os.path.exists(self.audio_path):
            with open(self.audio_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                        continue
                    parts = stripped.split()
                    if len(parts) >= 1 and parts[0].lower() == model_lower:
                        audio_exists = True
                        audio_raw = stripped
                        # Try to match preset by sound bank a/b
                        if len(parts) >= 4:
                            try:
                                b_a = int(parts[2])
                                b_b = int(parts[3])
                                for sp in SOUND_PRESETS:
                                    if sp["id"] != "default" and sp["bank_a"] == b_a and sp["bank_b"] == b_b:
                                        matched_preset_id = sp["id"]
                                        matched_preset_label = sp["label"]
                                        matched_preset_label_zh = sp.get("label_zh", sp["label"])
                                        matched_preset_label_en = sp.get("label_en", sp["label"])
                                        break
                            except Exception:
                                pass
                        break

        if audio_exists and audio_raw:
            if is_vanilla and vanilla_raw:
                is_modified = (audio_raw.split() != vanilla_raw.split())
                if not is_modified:
                    matched_preset_id = "default"
                    matched_preset_label = "Vanilla Default"
                    matched_preset_label_zh = "Vanilla Default"
                    matched_preset_label_en = "Vanilla Default"

        return {
            "model": model_lower,
            "has_special_file": os.path.exists(self.special_path),
            "has_audio_file": os.path.exists(self.audio_path),
            "special": {
                "exists": special_exists,
                "is_native": is_native,
                "target": special_target,
                "label": special_label,
                "label_en": special_label_en,
                "desc": special_desc,
                "desc_en": special_desc_en,
                "raw_line": special_raw,
                "raw_line_en": special_raw_en if is_native else special_raw
            },
            "audio": {
                "exists": audio_exists,
                "is_vanilla": is_vanilla,
                "vanilla_line": vanilla_line,
                "is_modified": is_modified,
                "raw_line": audio_raw,
                "matched_preset_id": matched_preset_id,
                "matched_preset_label": matched_preset_label,
                "matched_preset_label_zh": matched_preset_label_zh,
                "matched_preset_label_en": matched_preset_label_en
            }
        }

    def _backup_file(self, filepath: str) -> str:
        """Create a safety backup outside game directory using BackupManager."""
        if not filepath or not os.path.exists(filepath):
            return ""
        bak = self.backup_manager.backup_file(filepath)
        return bak or ""
