"""
ID Manager for GTA San Andreas:
Scans all .ide files in vanilla data/ and across modloader/ (including addon cars,
addon weapons, proper fixes, map mods, and vehicle mods).
Analyzes occupied IDs and discovers safe, conflict-free gaps for new vehicle tuning parts.
Provides live single ID probing, search, and intelligent ID allocation.
"""

import os
import glob
import re
import time
from typing import Dict, Any, List, Optional, Tuple, Set
from .vanilla_data import VANILLA_VEHICLES
from .parser import normalize_ide_line

# Localized vehicle type labels
VEHICLE_TYPE_LABELS = {
    "car": "🚗 Car",
    "bike": "🏍️ Motorcycle",
    "bmx": "🚲 Bicycle",
    "quad": "🏎️ Quad",
    "heli": "🚁 Helicopter",
    "plane": "✈️ Airplane",
    "boat": "🛥️ Boat",
    "trailer": "🚛 Trailer",
    "train": "🚆 Train",
}

# vehicles.ide fingerprint
RE_IDE_FINGERPRINT = re.compile(
    r'^\s*(\d+)\s*,\s*([a-zA-Z0-9_]+)\s*,\s*([a-zA-Z0-9_]+)\s*,\s*(car|bike|heli|plane|boat|trailer|bmx|quad)\b',
    re.IGNORECASE
)

_IDE_SECTION_TAGS = ("cars", "objs", "peds", "weap", "tobj", "hier", "2dfx", "anim")
# Author config snippets kept as .txt always open with one of these headers.
# A readme's stray numeric examples must not occupy model IDs.
_TXT_CONFIG_HEADER_RE = re.compile(
    r'^(vehicles?[\s._-]*ide|veh[\s._-]*mods?(?:[\s._-]*ide)?|carmods?[\s._-]*dat?|'
    r'carcols?[\s._-]*dat?|handling[\s._-]*cfg?)\s*[:：]?\s*$',
    re.IGNORECASE
)

# Zone edges inside the 1000-20000 gap range. Free runs are split here (and at
# the FLA killable ceiling) so every reported block sits fully inside one zone.
_GAP_ZONE_EDGES = (1194, 1207, 11682, 12051, 12093, 13501, 15000, 18631)

class IdManager:
    # Shared scan generation per game folder. The installer, merger and tuning
    # manager each own an IdManager, so a write through one of them must
    # invalidate the cached scan of all the others - otherwise a freshly
    # assigned ID can be handed out a second time from a stale cache.
    _shared_generation: Dict[str, int] = {}

    def __init__(self, game_path: str, shadow_dir: str = ""):
        self.game_path = os.path.normpath(game_path) if (game_path and game_path.strip() != ".") else ""
        self.shadow_dir = os.path.normpath(shadow_dir) if shadow_dir else ""
        self.occupied_ids: Dict[int, Dict[str, Any]] = {}
        self.cached_gaps: List[Dict[str, Any]] = []
        self.max_veh_mod_id = 1193
        self.max_addon_veh_id = 611
        self.conflicts: List[Dict[str, Any]] = []
        self.vanilla_id_set: Set[int] = set()
        self.modloader_id_set: Set[int] = set()
        self.last_scan_time = 0.0
        self._scanned_generation = -1
        self.fla_status = self._read_fla_limits()

    @classmethod
    def _generation_key(cls, game_path: str) -> str:
        if not game_path:
            return ""
        return os.path.normpath(game_path).lower()

    @classmethod
    def invalidate_shared_cache(cls, game_path: str):
        """
        Mark the cached IDE scan of `game_path` as outdated for every IdManager.
        Called from any code path that writes vehicle/tuning IDs to disk.
        """
        key = cls._generation_key(game_path)
        cls._shared_generation[key] = cls._shared_generation.get(key, 0) + 1

    def _current_generation(self) -> int:
        return self._shared_generation.get(self._generation_key(self.game_path), 0)

    def set_shadow_dir(self, shadow_dir: str):
        self.shadow_dir = os.path.normpath(shadow_dir) if shadow_dir else ""

    def _read_fla_limits(self) -> Dict[str, Any]:
        """Read ID limits from fastman92 Limit Adjuster binaries (.asi) or .ini if present."""
        status = {
            "has_fla": False,
            "apply_id_limit_patch": False,
            "count_of_killable_model_ids": 800, # default GTA SA
            "file_type_dff_limit": 20000,
            "is_pending_launch": False,
        }
        if not self.game_path or not os.path.isdir(self.game_path):
            return status

        try:
            from .fla_manager import FLAManager
            fla_mgr = FLAManager(self.game_path)
            fla_info = fla_mgr.find_fla_installation()
        except Exception:
            fla_info = {"installed": False}

        if not fla_info.get("installed"):
            return status

        status["has_fla"] = True

        if fla_info.get("is_pending_launch"):
            # ASI file installed; pending first game launch to create ini.
            # FLA limit patch is active by default.
            status["is_pending_launch"] = True
            status["apply_id_limit_patch"] = True
            status["count_of_killable_model_ids"] = 20000
            status["file_type_dff_limit"] = 20000
            return status

        ini_path = fla_info.get("ini_path")
        if ini_path and os.path.isfile(ini_path):
            try:
                with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        clean = line.strip()
                        if not clean or clean.startswith(";") or clean.startswith("#"):
                            continue
                        if "Apply ID limit patch" in clean and "=" in clean:
                            val = clean.split("=")[1].strip()
                            status["apply_id_limit_patch"] = (val == "1")
                        elif "Count of killable model IDs" in clean and "=" in clean:
                            val = clean.split("=")[1].strip()
                            if val.isdigit():
                                status["count_of_killable_model_ids"] = int(val)
                        elif "FILE_TYPE_DFF" in clean and "=" in clean:
                            val = clean.split("=")[1].strip()
                            if val.isdigit():
                                status["file_type_dff_limit"] = int(val)
            except Exception:
                pass
        return status

    def _killable_limit(self) -> Optional[int]:
        """
        Effective killable model-ID ceiling when FLA's ID limit patch is active.
        Returns None when the ceiling is unknown or the patch is inactive.
        """
        try:
            if self.fla_status.get("apply_id_limit_patch"):
                limit = int(self.fla_status.get("count_of_killable_model_ids") or 0)
                if 0 < limit <= 65535:
                    return limit
        except Exception:
            pass
        return None

    def scan_all_ides(self, force_refresh: bool = False) -> Dict[int, Dict[str, Any]]:
        """
        Recursively scan all .ide files in vanilla data/ and modloader/.
        Accurately differentiates vanilla baseline replicas from true mod overrides and addons.
        Caches results for a short window, and reuses them only while no manager
        has invalidated the game folder since this instance last scanned it.
        """
        if not self.game_path or not os.path.isdir(self.game_path):
            return {}

        now = time.time()
        if force_refresh:
            self.invalidate_shared_cache(self.game_path)
        generation = self._current_generation()

        if (not force_refresh and self.occupied_ids
                and self._scanned_generation == generation
                and (now - self.last_scan_time < 3.0)):
            return self.occupied_ids

        # 1. First scan all .dff models in modloader/ to discover which models actually have replacement assets
        modloader_dir = os.path.join(self.game_path, "modloader")
        dff_map: Dict[str, str] = {}
        if os.path.isdir(modloader_dir):
            for root, _, files in os.walk(modloader_dir):
                for f in files:
                    if f.lower().endswith(".dff"):
                        m = os.path.splitext(f)[0].lower()
                        if m not in dff_map:
                            dff_map[m] = os.path.relpath(os.path.join(root, f), self.game_path)

        vanilla_records: Dict[int, Dict[str, Any]] = {}
        mod_records: Dict[int, Dict[str, Any]] = {}
        highest_tuning_id = 1193

        # 2. Scan Vanilla data/
        data_dir = os.path.join(self.game_path, "data")
        if os.path.isdir(data_dir):
            for ide_path in glob.glob(os.path.join(data_dir, "**", "*.ide"), recursive=True):
                rel_path = os.path.relpath(ide_path, self.game_path)
                self._parse_single_ide_file(ide_path, rel_path, "vanilla", vanilla_records)

        # Ensure all standard 212 vanilla vehicles (400-611) are mapped in vanilla_records
        for mid, vinfo in VANILLA_VEHICLES.items():
            if mid not in vanilla_records:
                vanilla_records[mid] = {
                    "id": mid,
                    "name": vinfo["model"].lower(),
                    "display_name": vinfo["name"],
                    "veh_type": vinfo["type"],
                    "veh_type_label": VEHICLE_TYPE_LABELS.get(vinfo["type"], "🚗 Car"),
                    "section": "cars",
                    "file": os.path.join("data", "vehicles.ide"),
                    "source": "vanilla",
                    "is_vehicle": True,
                    "is_tuning": False,
                    "raw": f"{mid}, {vinfo['model']}, {vinfo['model']}, {vinfo['type']}, ..."
                }
            else:
                vanilla_records[mid]["display_name"] = vinfo["name"]
                vanilla_records[mid]["veh_type"] = vinfo["type"]
                vanilla_records[mid]["veh_type_label"] = VEHICLE_TYPE_LABELS.get(vinfo["type"], "🚗 Car")

        self.vanilla_id_set = set(vanilla_records.keys())

        # 3. Scan ModLoader .ide and .txt files
        all_sources: Dict[int, List[Dict[str, Any]]] = {}
        highest_addon_veh_id = 611

        if os.path.isdir(modloader_dir):
            for root, _, files in os.walk(modloader_dir):
                for f in files:
                    fl = f.lower()
                    if fl.endswith(".ide") or fl.endswith(".txt"):
                        file_path = os.path.join(root, f)
                        rel_path = os.path.relpath(file_path, self.game_path)
                        self._parse_single_config_file(file_path, rel_path, "modloader", mod_records, all_sources, dff_map)

        self.modloader_id_set = set(mod_records.keys())

        # 3b. Prefer deployed .ide declarations over author readme/txt snippets:
        # after an installer merge the shadow .ide holds the real assigned ID;
        # a leftover txt (example/stale ID) for the same model must not occupy
        # an extra slot nor raise phantom conflicts.
        if all_sources:
            name_has_ide = {
                e.get("name", "").lower()
                for entries in all_sources.values() for e in entries
                if e.get("file", "").lower().endswith(".ide") and e.get("name")
            }
            drop_ids = []
            for mid, rec in mod_records.items():
                entries = all_sources.get(mid) or []
                if any(e.get("file", "").lower().endswith(".ide") for e in entries):
                    continue
                if not rec.get("file", "").lower().endswith(".txt"):
                    continue
                if rec.get("name", "").lower() in name_has_ide:
                    drop_ids.append(mid)
            for mid in drop_ids:
                mod_records.pop(mid, None)
                all_sources.pop(mid, None)

        # 4. Merge records: Differentiate shadow copies from true addons / overrides
        records: Dict[int, Dict[str, Any]] = {}

        for mid, item in vanilla_records.items():
            if item.get("is_tuning") and mid > highest_tuning_id:
                highest_tuning_id = mid
            records[mid] = {**item, "status_tag": "vanilla"}

        for mid, item in mod_records.items():
            if item.get("is_tuning") and mid > highest_tuning_id:
                highest_tuning_id = mid
            if item.get("is_vehicle") and mid > highest_addon_veh_id:
                highest_addon_veh_id = mid

            if mid not in self.vanilla_id_set:
                # Genuinely new ID added by mod
                records[mid] = {**item, "status_tag": "addon"}
            else:
                vanilla_item = vanilla_records[mid]
                item_name = item["name"].lower()
                vanilla_name = vanilla_item["name"].lower()

                if item_name != vanilla_name:
                    # Model name was redefined in .ide by mod
                    records[mid] = {**item, "status_tag": "override"}
                else:
                    # Same model name as vanilla
                    # Check if there is an actual replacement .dff in modloader
                    if item_name in dff_map:
                        records[mid] = {
                            **item,
                            "file": dff_map[item_name],
                            "status_tag": "override"
                        }
                    else:
                        # Replicated data copy (e.g. shadow baseline vehicles.ide or veh_mods.ide)
                        # Retain vanilla classification
                        records[mid] = {
                            **vanilla_item,
                            "status_tag": "vanilla"
                        }

        # 5. Check all 212 vanilla vehicles against dff_map
        for mid, vinfo in VANILLA_VEHICLES.items():
            m = vinfo["model"].lower()
            if mid in records:
                records[mid]["display_name"] = vinfo["name"]
                records[mid]["veh_type"] = vinfo["type"]
                records[mid]["veh_type_label"] = VEHICLE_TYPE_LABELS.get(vinfo["type"], "🚗 Car")
            if m in dff_map:
                if mid in records:
                    records[mid]["status_tag"] = "override"
                    records[mid]["file"] = dff_map[m]
                    records[mid]["is_vehicle"] = True
            else:
                if mid in records and records[mid].get("status_tag") != "addon":
                    records[mid]["status_tag"] = "vanilla"
                    if "modloader" in records[mid]["file"].lower():
                        records[mid]["file"] = os.path.join("data", "vehicles.ide")

        # 6. Check vanilla tuning parts (1000-1193): do not let shadow veh_mods.ide mark them as override
        for mid, item in records.items():
            if item.get("is_tuning") and 1000 <= mid <= 1193:
                tname = item["name"].lower()
                if tname in dff_map:
                    item["status_tag"] = "override"
                    item["file"] = dff_map[tname]
                else:
                    item["status_tag"] = "vanilla"
                    if "modloader" in item["file"].lower():
                        item["file"] = os.path.join("data", "maps", "veh_mods", "veh_mods.ide")

        self.max_veh_mod_id = max(highest_tuning_id, 11746)
        self.max_addon_veh_id = max(highest_addon_veh_id, 611)

        # 7. Detect conflicts across distinct mod folders
        conflicts = []
        for mid, entries in all_sources.items():
            distinct_folders = set(e["mod_folder"] for e in entries if e.get("mod_folder"))
            if len(distinct_folders) > 1:
                distinct_names = set(e["name"].lower() for e in entries if e.get("name"))
                if len(distinct_names) > 1:
                    conflicts.append({
                        "id": mid,
                        "type": "model_mismatch",
                        "folders": list(distinct_folders),
                        "names": list(distinct_names),
                        "files": [e["file"] for e in entries]
                    })
                elif any(e.get("is_vehicle") for e in entries) and mid > 611:
                    conflicts.append({
                        "id": mid,
                        "type": "addon_collision",
                        "folders": list(distinct_folders),
                        "names": list(distinct_names),
                        "files": [e["file"] for e in entries]
                    })
        self.conflicts = conflicts

        self.occupied_ids = records
        self.cached_gaps = self._compute_free_gaps(records)
        self.last_scan_time = now
        self._scanned_generation = generation
        return self.occupied_ids

    def _parse_single_config_file(
        self, file_path: str, rel_path: str, source: str,
        records: Dict[int, Dict[str, Any]],
        all_sources: Optional[Dict[int, List[Dict[str, Any]]]] = None,
        dff_map: Optional[Dict[str, str]] = None
    ):
        """Parse one .ide or .txt file into records map."""
        cur_sec = None
        txt_header_seen = False
        is_txt = file_path.lower().endswith(".txt")
        parts = rel_path.split(os.sep)
        if len(parts) >= 2 and parts[0].lower() == "modloader":
            top_folder = parts[1]
            if top_folder in ("Modded Cars", "Addon Cars") and len(parts) >= 3:
                mod_folder = os.sep.join(parts[:3])
            else:
                mod_folder = os.sep.join(parts[:2])
        else:
            mod_folder = parts[0]

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = normalize_ide_line(line.strip())
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    tokens = [x.strip() for x in line.split(",") if x.strip()]
                    if len(tokens) == 1:
                        sec_tag = tokens[0].lower()
                        if sec_tag == "end":
                            cur_sec = None
                        elif sec_tag in _IDE_SECTION_TAGS:
                            cur_sec = sec_tag
                            txt_header_seen = True
                        elif is_txt and _TXT_CONFIG_HEADER_RE.match(tokens[0]):
                            txt_header_seen = True
                        continue

                    token0 = line.split()[0].rstrip(",")
                    if not token0.isdigit():
                        continue

                    model_id = int(token0)
                    m_veh = RE_IDE_FINGERPRINT.match(line)
                    is_vehicle = bool(m_veh or cur_sec == "cars" or (400 <= model_id <= 611))
                    is_tuning = bool(
                        cur_sec == "objs" and (1000 <= model_id <= 1193 or "veh_mods" in rel_path.lower() or "carmods" in rel_path.lower())
                    )

                    if not is_vehicle and not is_tuning and is_txt:
                        continue

                    model_name = m_veh.group(2) if m_veh else (tokens[1] if len(tokens) > 1 else line.split()[1].rstrip(","))

                    if is_txt and not txt_header_seen:
                        # Headerless snippet: only trust it when the model asset
                        # really exists (author config with no header), so prose
                        # examples in readmes cannot occupy model IDs.
                        if model_name.lower() not in (dff_map or {}):
                            continue

                    veh_type = "unknown"
                    display_name = model_name
                    if is_vehicle:
                        if model_id in VANILLA_VEHICLES:
                            vinfo = VANILLA_VEHICLES[model_id]
                            veh_type = vinfo.get("type", "car")
                            display_name = vinfo.get("name", model_name)
                        elif m_veh:
                            veh_type = m_veh.group(4).lower()
                        elif len(tokens) > 3:
                            veh_type = tokens[3].lower()
                            if len(tokens) > 5 and tokens[5].lower() != "null":
                                display_name = tokens[5]
                    elif is_tuning:
                        veh_type = "tuning"

                    veh_type_label = VEHICLE_TYPE_LABELS.get(
                        veh_type,
                        "🔧 Tuning" if is_tuning else ("🚗 Vehicle" if is_vehicle else "Object")
                    )

                    rec = {
                        "id": model_id,
                        "name": model_name,
                        "display_name": display_name,
                        "veh_type": veh_type,
                        "veh_type_label": veh_type_label,
                        "section": cur_sec or ("cars" if is_vehicle else "objs"),
                        "file": rel_path,
                        "source": source,
                        "is_vehicle": is_vehicle,
                        "is_tuning": is_tuning,
                        "raw": line
                    }
                    records[model_id] = rec

                    if all_sources is not None:
                        all_sources.setdefault(model_id, []).append({
                            **rec,
                            "mod_folder": mod_folder
                        })
        except Exception:
            pass

    def _parse_single_ide_file(self, file_path: str, rel_path: str, source: str, records: Dict[int, Dict[str, Any]],
                               dff_map: Optional[Dict[str, str]] = None):
        """Backward compatibility wrapper."""
        self._parse_single_config_file(file_path, rel_path, source, records, dff_map=dff_map)

    def _compute_free_gaps(self, occupied: Dict[int, Dict[str, Any]], max_limit: int = 20000) -> List[Dict[str, Any]]:
        """
        Compute contiguous free runs up to max_limit, split at zone edges and at
        the FLA killable ceiling so each reported block belongs to exactly one
        zone and never straddles the safe/over-limit boundary.
        """
        all_ids = set(occupied.keys())
        limit = self._killable_limit()
        edges = set(_GAP_ZONE_EDGES)
        if limit is not None:
            edges.add(limit)
        gaps = []
        i = 1000
        while i <= max_limit:
            if i in all_ids:
                i += 1
                continue
            run_start = i
            while i <= max_limit and i not in all_ids:
                i += 1
            run_end = i - 1
            split_points = [run_start] + sorted(e for e in edges if run_start < e <= run_end)
            for idx, seg_start in enumerate(split_points):
                seg_end = (split_points[idx + 1] - 1) if idx + 1 < len(split_points) else run_end
                gaps.append(self._format_gap(seg_start, seg_end))
        return gaps

    def _gap_zone(self, start: int) -> Dict[str, Any]:
        """Zone metadata for a free segment (segments are pre-split at edges)."""
        if 1194 <= start <= 1206:
            return {"category": "tuning", "recommended": True, "recommend_rank": 3,
                    "zone_label_zh": "Tuning part post-adjacent range",
                    "zone_label_en": "Adjacent Vanilla Tuning Range"}
        if 11682 <= start <= 12050:
            return {"category": "tuning", "recommended": True, "recommend_rank": 1,
                    "zone_label_zh": "Tuning prime range (Vanilla/ModLoader Safe)",
                    "zone_label_en": "Tuning Prime Range (Vanilla/ModLoader Safe)"}
        if 12093 <= start <= 13500:
            return {"category": "addon", "recommended": True, "recommend_rank": 2,
                    "zone_label_zh": "Addon vehicle prime range (Addon Vehicles Safe)",
                    "zone_label_en": "Addon Vehicle Prime Range (Addon Safe)"}
        if 13501 <= start <= 14999:
            return {"category": "reserve", "recommended": False, "recommend_rank": 4,
                    "zone_label_zh": "Mid-tier reserve range",
                    "zone_label_en": "Mid-Range Reserve Block"}
        if 15000 <= start <= 18630:
            return {"category": "reserve", "recommended": False, "recommend_rank": 5,
                    "zone_label_zh": "High-tier extension range",
                    "zone_label_en": "High-Range Reserve Block"}
        if start >= 18631:
            return {"category": "fla", "recommended": False, "recommend_rank": 6,
                    "zone_label_zh": "FLA extended range (requires FLA patch)",
                    "zone_label_en": "FLA Extended Range (Requires FLA Patch)"}
        return {"category": "general", "recommended": False, "recommend_rank": 99,
                "zone_label_zh": "General free range",
                "zone_label_en": "Standard Free Block"}

    def _format_gap(self, start: int, end: int) -> Dict[str, Any]:
        count = end - start + 1
        zone = self._gap_zone(start)
        limit = self._killable_limit()
        over_limit = bool(limit is not None and start >= limit)
        return {
            "start": start,
            "end": end,
            "count": count,
            "category": zone["category"],
            "is_large": (count >= 100),
            "recommended": zone["recommended"] and not over_limit,
            "recommend_rank": zone["recommend_rank"],
            "over_killable_limit": over_limit,
            "killable_limit": limit,
            "zone_label": zone["zone_label_zh"],
            "zone_label_zh": zone["zone_label_zh"],
            "zone_label_en": zone["zone_label_en"]
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get overview statistics of all registered IDs and free ranges."""
        self.scan_all_ides()
        total_occupied = len(self.occupied_ids)
        vanilla_total = sum(1 for v in self.occupied_ids.values() if v.get("status_tag") == "vanilla")
        mod_addon_count = sum(1 for v in self.occupied_ids.values() if v.get("status_tag") == "addon")
        mod_override_count = sum(1 for v in self.occupied_ids.values() if v.get("status_tag") == "override")
        max_used_id = max(self.occupied_ids.keys()) if self.occupied_ids else 0

        # Filter prominent gaps (at least 5 free IDs)
        prominent_gaps = [g for g in self.cached_gaps if g["count"] >= 5]
        prominent_gaps.sort(key=lambda g: (not g["recommended"], g["recommend_rank"], -g["count"]))

        # Count total free IDs between 1000 and 20000
        total_free_in_range = sum(g["count"] for g in self.cached_gaps if g["start"] <= 20000)

        # Compute next recommended free ID for vehicle tuning parts
        _next_tuning = self.allocate_free_ids(1)
        next_tuning_id = _next_tuning[0] if _next_tuning else 11748
        # Compute next recommended free ID for addon vehicles
        _next_addon = self.allocate_free_addon_ids(1)
        next_addon_id = _next_addon[0] if _next_addon else 12501
        limit = self._killable_limit()

        return {
            "success": True,
            "total_occupied": total_occupied,
            "vanilla_total": vanilla_total,
            "mod_addon_count": mod_addon_count,
            "mod_override_count": mod_override_count,
            "max_used_id": max_used_id,
            "total_free_in_range": total_free_in_range,
            "total_free_safe": sum(g["count"] for g in self.cached_gaps
                                   if not g.get("over_killable_limit")),
            "killable_limit": limit,
            "next_recommended_tuning_id": next_tuning_id,
            "next_recommended_tuning_over_limit": bool(limit is not None and next_tuning_id >= limit),
            "max_veh_mod_id": self.max_veh_mod_id,
            "next_recommended_addon_id": next_addon_id,
            "next_recommended_addon_over_limit": bool(limit is not None and next_addon_id >= limit),
            "max_addon_veh_id": self.max_addon_veh_id,
            "conflict_count": len(self.conflicts),
            "conflicts": self.conflicts,
            "gaps": prominent_gaps,
            "fla_status": self.fla_status,
            "scanned_time": self.last_scan_time
        }

    def _scan_free_ids(self, start: int, end: int, count: int, occupied: Set[int]) -> List[int]:
        out: List[int] = []
        candidate = start
        while candidate <= end and len(out) < count:
            if candidate not in occupied:
                out.append(candidate)
            candidate += 1
        return out

    def _allocate_ids(self, start: int, count: int, occupied: Set[int]) -> List[int]:
        """Allocate free IDs from `start`, preferring slots below the FLA
        killable ceiling. Over-ceiling IDs are only used as a last resort once
        every safe slot after `start` is taken."""
        limit = self._killable_limit()
        if limit is not None and start < limit:
            allocated = self._scan_free_ids(start, limit - 1, count, occupied)
            if len(allocated) < count:
                allocated.extend(self._scan_free_ids(max(start, limit), 65535,
                                                     count - len(allocated), occupied))
            return allocated
        return self._scan_free_ids(start, 65535, count, occupied)

    def allocate_free_ids(self, count: int, start_preferred: Optional[int] = None, exclude_ids: Optional[Set[int]] = None) -> List[int]:
        """
        Allocate `count` free IDs guaranteed not to conflict with vanilla or modloader.
        Defaults to continuing immediately after the highest existing tuning ID in veh_mods.ide.
        """
        self.scan_all_ides()
        occupied = set(self.occupied_ids.keys())
        if exclude_ids:
            occupied.update(exclude_ids)

        if count <= 0:
            return []

        # Determine starting point
        if start_preferred and start_preferred >= 1000:
            candidate = start_preferred
        else:
            # Continue right after highest veh_mods ID (e.g. 11747 -> 11748)
            candidate = self.max_veh_mod_id + 1

        return self._allocate_ids(candidate, count, occupied)

    def allocate_free_addon_ids(self, count: int, start_preferred: Optional[int] = None, exclude_ids: Optional[Set[int]] = None) -> List[int]:
        """
        Allocate `count` free vehicle model IDs guaranteed not to conflict with vanilla or modloader.
        Defaults to continuing immediately after the highest existing addon vehicle ID (or 12093).
        """
        self.scan_all_ides()
        occupied = set(self.occupied_ids.keys())
        if exclude_ids:
            occupied.update(exclude_ids)

        if count <= 0:
            return []

        if start_preferred and start_preferred >= 612:
            candidate = start_preferred
        else:
            candidate = max(self.max_addon_veh_id + 1, 12093)
            limit = self._killable_limit()
            # If "continue after highest" already sits above the killable
            # ceiling, first reuse the safe addon window instead.
            if limit is not None and candidate >= limit and 12093 < limit:
                candidate = 12093

        return self._allocate_ids(candidate, count, occupied)

    def check_id_status(self, test_id: int) -> Dict[str, Any]:
        """Check if a specific ID is free or occupied."""
        self.scan_all_ides()
        if test_id in self.occupied_ids:
            item = self.occupied_ids[test_id]
            return {
                "id": test_id,
                "is_free": False,
                "name": item["name"],
                "section": item["section"],
                "file": item["file"],
                "source": item["source"],
                "status_tag": item.get("status_tag", item["source"]),
                "is_vehicle": item["is_vehicle"],
                "is_tuning": item["is_tuning"]
            }
        else:
            belonging_gap = next((g for g in self.cached_gaps if g["start"] <= test_id <= g["end"]), None)
            return {
                "id": test_id,
                "is_free": True,
                "gap": belonging_gap,
                "is_recommended": belonging_gap["recommended"] if belonging_gap else False
            }

    def search_ids(self, query: str, filter_type: str = "all", limit: int = 60) -> List[Dict[str, Any]]:
        """
        Search occupied IDs by model name, section, or ID number.
        filter_type: 'all', 'addon', 'override', 'vanilla', 'cars', 'tuning'
        """
        self.scan_all_ides()
        query = query.strip().lower()
        results = []

        is_num_query = query.isdigit()
        query_num = int(query) if is_num_query else None

        for mid in sorted(self.occupied_ids.keys()):
            item = self.occupied_ids[mid]
            status_tag = item.get("status_tag", item["source"])
            v_type = item.get("veh_type", "")

            # Filter logic
            if filter_type == "addon" and status_tag != "addon":
                continue
            elif filter_type == "override" and status_tag != "override":
                continue
            elif filter_type == "vanilla" and status_tag != "vanilla":
                continue
            elif filter_type == "cars" and not item["is_vehicle"]:
                continue
            elif filter_type == "car" and (not item["is_vehicle"] or v_type != "car"):
                continue
            elif filter_type == "bike" and (not item["is_vehicle"] or v_type not in ("bike", "bmx", "quad")):
                continue
            elif filter_type == "plane_heli" and (not item["is_vehicle"] or v_type not in ("plane", "heli")):
                continue
            elif filter_type == "boat" and (not item["is_vehicle"] or v_type != "boat"):
                continue
            elif filter_type == "trailer" and (not item["is_vehicle"] or v_type != "trailer"):
                continue
            elif filter_type == "tuning" and not item["is_tuning"]:
                continue

            matched = False
            if not query:
                matched = True
            elif is_num_query:
                if str(mid).startswith(query) or mid == query_num:
                    matched = True
            else:
                if (
                    query in item["name"].lower()
                    or query in item.get("display_name", "").lower()
                    or query in item.get("veh_type", "").lower()
                    or query in item.get("veh_type_label", "").lower()
                    or query in item["file"].lower()
                    or query in item["section"].lower()
                ):
                    matched = True

            if matched:
                results.append(item)
                if len(results) >= limit:
                    break

        return results
