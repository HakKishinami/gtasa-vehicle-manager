"""
Mod Installer Engine:
Handles extracting mod archives (ZIP, RAR, 7Z), inspecting unzipped folders,
identifying vehicle models and tuning parts, parsing Readmes,
and safely deploying files and configurations into ModLoader.
"""

import os
import re
import hashlib
import secrets
import shutil
import zipfile
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple

from .parser import DualTrackParser, read_text_file_safe
from .merger import ConfigMerger
from .tuning_manager import TuningManager
from .fla_manager import FLAManager
from .id_manager import IdManager
from .vanilla_data import VANILLA_VEHICLES, MODEL_TO_ID, TUNING_PREFIX_INFO
from .backup_manager import BackupManager
from .fxt_installer import deploy_fxt
from .seven_zip import (
    find_7zip,
    extract_with_7zip,
    format_needs_7zip,
    SevenZipNotFoundError,
    SEVEN_ZIP_DOWNLOAD_URL,
)

KNOWN_TUNING_PREFIXES = tuple(TUNING_PREFIX_INFO.keys())

PREVIEW_TEXT_EXTENSIONS = {".txt", ".readme", ".md", ".me", ".log", ".cfg", ".dat",
                           ".ide", ".ini", ".fxt", ".auid", ".json", ".xml", ".csv",
                           ".html", ".htm", ".doc", ".source"}
MAX_TEXT_PREVIEW_BYTES = 512 * 1024


def _files_identical(paths: list) -> bool:
    """True when every path exists and all contents are byte-identical.

    Used to tell real version variants (IVF vs noIVF) apart from plain
    duplicates of the same file shipped in several folders (paintjobs).
    Size is compared first as a cheap gate, then SHA-1.
    """
    try:
        sizes = {os.path.getsize(p) for p in paths}
        if len(sizes) != 1:
            return False
        digest = None
        for p in paths:
            h = hashlib.sha1()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            d = h.digest()
            if digest is None:
                digest = d
            elif d != digest:
                return False
        return True
    except Exception:
        return False


def _file_sha1(path: str) -> str:
    """SHA-1 of a file's contents ('' when unreadable)."""
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


_DOC_TEXT_EXTENSIONS = {".txt", ".readme", ".md", ".me", ".log", ".cfg", ".dat", ".ide", ".ini"}


def _doc_referenced_models(parser: DualTrackParser, path: str) -> set:
    """Model names a config document declares (vehicles.ide / handling /
    carcols / carmods blocks) so the installer can route it to its vehicle."""
    try:
        parsed = parser.parse_text_content(read_text_file_safe(path))
    except Exception:
        return set()
    models = set()
    for line in parsed.get("vehicles_ide", []) or []:
        toks = [t.strip() for t in line.split(",")]
        if len(toks) >= 2 and toks[1]:
            models.add(toks[1].lower())
    for line in parsed.get("handling_cfg", []) or []:
        toks = line.split()
        if toks:
            name = toks[0].lstrip("!$%").lower()
            if not name and len(toks) > 1:
                name = toks[1].lstrip("!$%").lower()
            if name:
                models.add(name)
    for key in ("carcols_dat", "carmods_dat"):
        for line in parsed.get(key, []) or []:
            toks = [t.strip() for t in line.split(",")]
            if toks and toks[0]:
                models.add(toks[0].lower())
    return models


class ModInstaller:
    def __init__(self, game_path: str, data_folder: str = "Modded Cars", backup_manager: Optional[BackupManager] = None):
        self.game_path = os.path.normpath(game_path)
        self.data_folder = data_folder
        self.shadow_dir = os.path.join(self.game_path, "modloader", self.data_folder)
        self.backup_manager = backup_manager or BackupManager(game_dir=self.game_path)
        self.parser = DualTrackParser()
        self.merger = ConfigMerger(self.shadow_dir, self.game_path, backup_manager=self.backup_manager)
        self.id_mgr = IdManager(self.game_path)
        self.staging_base = os.path.join(tempfile.gettempdir(), "gtasa_installer_staging")
        os.makedirs(self.staging_base, exist_ok=True)
        self._preview_sessions = {}

    def set_data_folder(self, data_folder: str):
        self.data_folder = data_folder
        self.shadow_dir = os.path.join(self.game_path, "modloader", self.data_folder)
        self.merger = ConfigMerger(self.shadow_dir, self.game_path, backup_manager=self.backup_manager)

    # ---------------- Archive Extraction ----------------

    def extract_archive(self, archive_path: str) -> str:
        """
        Extract archive to a temporary directory in staging_base.
        Returns the extraction folder path.
        """
        if not os.path.isfile(archive_path):
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        session_id = f"mod_{int(time.time())}_{os.getpid()}"
        out_dir = os.path.join(self.staging_base, session_id)
        os.makedirs(out_dir, exist_ok=True)

        ext = os.path.splitext(archive_path)[1].lower()
        seven_zip = find_7zip()

        if seven_zip:
            res = extract_with_7zip(seven_zip, archive_path, out_dir)
            if res.returncode == 0:
                return out_dir
            if format_needs_7zip(archive_path):
                detail = (res.stderr or res.stdout or "").strip()
                raise RuntimeError(
                    f"7-Zip extraction failed ({ext})" + (f": {detail}" if detail else ".")
                )

        # ZIP never requires 7-Zip — stdlib is enough.
        if ext == ".zip":
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(out_dir)
            return out_dir

        if format_needs_7zip(archive_path):
            raise SevenZipNotFoundError()

        raise RuntimeError(
            f"Cannot extract archive format ({ext}). Please install 7-Zip ({SEVEN_ZIP_DOWNLOAD_URL}) or unpack manually first."
        )

    def get_existing_authors(self, category_folder: Optional[str] = None) -> List[str]:
        """Scan subdirectories in target modloader folder to find existing author folders."""
        cat = category_folder or self.data_folder
        cat_dir = os.path.join(self.game_path, "modloader", cat)
        authors = set()
        if os.path.isdir(cat_dir):
            for entry in os.listdir(cat_dir):
                entry_path = os.path.join(cat_dir, entry)
                if os.path.isdir(entry_path):
                    has_direct_dff = any(f.lower().endswith(".dff") for f in os.listdir(entry_path) if os.path.isfile(os.path.join(entry_path, f)))
                    sub_dirs = [s for s in os.listdir(entry_path) if os.path.isdir(os.path.join(entry_path, s))]
                    if sub_dirs and not has_direct_dff:
                        authors.add(entry)
                    elif not has_direct_dff:
                        authors.add(entry)
        return sorted(list(authors), key=lambda s: s.lower())

    # ---------------- Pre-Install Inspection ----------------

    def inspect_source(self, source_path: str) -> Dict[str, Any]:
        """
        Inspect a mod folder or archive file.
        Recursively discovers DFF, TXD, tuning parts, and Readme.
        Parses configuration and suggests target vehicle and author.
        """
        source_path = os.path.normpath(source_path.strip('"\''))
        if not os.path.exists(source_path):
            return {"success": False, "error": f"Specified path does not exist: {source_path}"}

        extracted_temp = None
        inspect_dir = source_path
        original_name = os.path.basename(source_path)

        # If it's a file, attempt extraction
        if os.path.isfile(source_path):
            try:
                extracted_temp = self.extract_archive(source_path)
                inspect_dir = extracted_temp
                original_name = os.path.splitext(os.path.basename(source_path))[0]
            except SevenZipNotFoundError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "error_code": e.error_code,
                    "download_url": e.download_url,
                }
            except Exception as e:
                return {"success": False, "error": f"Extraction failed: {str(e)}"}

        # Scan files in inspect_dir
        primary_dffs = []
        primary_txds = []
        tuning_dffs = []
        tuning_txds = []
        readme_files = []
        fxt_files = []
        other_files = []

        for root, _, files in os.walk(inspect_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                lower = fname.lower()
                rel = os.path.relpath(fpath, inspect_dir)
                try:
                    fsize = os.path.getsize(fpath)
                except Exception:
                    fsize = 0

                if lower.endswith(".dff"):
                    base = os.path.splitext(lower)[0]
                    if base.startswith(KNOWN_TUNING_PREFIXES):
                        tuning_dffs.append({"name": fname, "path": fpath, "rel": rel, "size": fsize})
                    else:
                        primary_dffs.append({"name": fname, "path": fpath, "rel": rel, "model": base, "size": fsize})

                elif lower.endswith(".txd"):
                    base = os.path.splitext(lower)[0]
                    if base.startswith(KNOWN_TUNING_PREFIXES):
                        tuning_txds.append({"name": fname, "path": fpath, "rel": rel, "size": fsize})
                    else:
                        primary_txds.append({"name": fname, "path": fpath, "rel": rel, "model": base, "size": fsize})

                elif lower.endswith(".fxt"):
                    fxt_content = read_text_file_safe(fpath)
                    fxt_files.append({"name": fname, "path": fpath, "rel": rel, "content": fxt_content})

                elif lower in ("vehicles.ide", "vehicles.ide.source", "carcols.dat", "handling.cfg") or any(lower.endswith(ext) for ext in [".txt", ".readme", ".doc", ".me", ".log", ".cfg", ".dat", ".ide", ".md"]):
                    readme_files.append({"name": fname, "path": fpath, "rel": rel})
                else:
                    other_files.append({"name": fname, "path": fpath, "rel": rel})

        # Read and merge readme content
        combined_text = ""
        for r in readme_files:
            c = read_text_file_safe(r["path"])
            if c:
                combined_text += f"\n\n--- Readme: {r['name']} ---\n" + c

        # Parse on-disk author FXT entries (authoritative!)
        author_fxt_entries = {}
        for fxt_f in fxt_files:
            for line in fxt_f.get("content", "").splitlines():
                df = self.parser.decompose_fxt(line)
                if df and df.get("key"):
                    k = df["key"].upper()
                    if k not in author_fxt_entries:
                        author_fxt_entries[k] = {
                            "key": df["key"],
                            "name": df.get("name", ""),
                            "file": fxt_f["name"],
                            "rel": fxt_f["rel"]
                        }

        parsed_config = self.parser.parse_text_content(combined_text)

        # Merge on-disk FXT lines into parsed_config["fxt_text"] (highest priority)
        for entry in author_fxt_entries.values():
            line_str = f"{entry['key']} {entry['name']}".strip()
            if line_str not in parsed_config["fxt_text"]:
                parsed_config["fxt_text"].insert(0, line_str)

        # Collect all target vehicles
        target_vehicles = []
        seen_models = set()

        for pd in primary_dffs:
            m = pd["model"]
            if m in MODEL_TO_ID and m not in seen_models:
                seen_models.add(m)
                v_info = VANILLA_VEHICLES[MODEL_TO_ID[m]]
                target_vehicles.append({
                    "model": m,
                    "id": MODEL_TO_ID[m],
                    "name": v_info["name"],
                    "is_addon": False
                })

        for h_line in parsed_config["handling_cfg"]:
            tokens = h_line.split()
            if tokens:
                m = tokens[0].lstrip("!$%").lower()
                if not m and len(tokens) > 1:
                    m = tokens[1].lstrip("!$%").lower()
                if m in MODEL_TO_ID and m not in seen_models:
                    seen_models.add(m)
                    v_info = VANILLA_VEHICLES[MODEL_TO_ID[m]]
                    target_vehicles.append({
                        "model": m,
                        "id": MODEL_TO_ID[m],
                        "name": v_info["name"],
                        "is_addon": False
                    })

        for ide_line in parsed_config["vehicles_ide"]:
            tokens = [t.strip() for t in ide_line.split(",")]
            if len(tokens) >= 2:
                m = tokens[1].lower()
                if m in MODEL_TO_ID and m not in seen_models:
                    seen_models.add(m)
                    v_info = VANILLA_VEHICLES[MODEL_TO_ID[m]]
                    target_vehicles.append({
                        "model": m,
                        "id": MODEL_TO_ID[m],
                        "name": v_info["name"],
                        "is_addon": False
                    })

        # Addon candidates missed above: non-vanilla models declared by IDE
        # lines (numeric or placeholder ID) or present as model files on disk.
        # Without this, mixed replace+addon packs (e.g. rancher pack with
        # ranchxlt/agitator on "ID," placeholders) only expose the replace
        # half and the addon half can never be installed.
        ide_by_raw_model = {}
        for ide_line in parsed_config["vehicles_ide"]:
            toks = [t.strip() for t in ide_line.split(",")]
            if len(toks) >= 2 and toks[1]:
                ide_by_raw_model.setdefault(toks[1].lower(), ide_line)
        for m, ide_line in ide_by_raw_model.items():
            if m in seen_models or m in MODEL_TO_ID:
                continue
            toks = [t.strip() for t in ide_line.split(",")]
            try:
                nid = int(toks[0]) if toks[0] else None
            except (ValueError, TypeError):
                nid = None
            seen_models.add(m)
            target_vehicles.append({
                "model": m,
                "id": nid,
                "name": m.upper(),
                "is_addon": True
            })

        for pd in primary_dffs:
            m = pd["model"]
            if m not in seen_models and m not in MODEL_TO_ID:
                seen_models.add(m)
                target_vehicles.append({
                    "model": m,
                    "id": None,
                    "name": m.upper(),
                    "is_addon": True
                })

        # Name-clash guard: a vanilla model declared with a placeholder or
        # non-vanilla ID would collide on model name if installed as addon.
        # Keep replace behavior, but surface it so the user can rename.
        addon_name_conflicts = []
        for m, ide_line in ide_by_raw_model.items():
            if m in MODEL_TO_ID and m in seen_models:
                toks = [t.strip() for t in ide_line.split(",")]
                try:
                    nid = int(toks[0]) if toks and toks[0] else None
                except (ValueError, TypeError):
                    nid = None
                if nid is None or nid != MODEL_TO_ID[m]:
                    addon_name_conflicts.append({
                        "model": m,
                        "ide_id": nid,
                        "vanilla_id": MODEL_TO_ID[m]
                    })

        if not target_vehicles and primary_dffs:
            for pd in primary_dffs:
                m = pd["model"]
                if m not in seen_models:
                    seen_models.add(m)
                    target_vehicles.append({
                        "model": m,
                        "id": None,
                        "name": m.upper()
                    })

        orig_clean = original_name.lower().replace("_", " ").replace("-", " ")
        def v_prio(v):
            m = v["model"]
            if m in orig_clean or v["name"].lower() in orig_clean:
                return (0, m)
            if "shit" in m or "dam" in m:
                return (2, m)
            return (1, m)

        target_vehicles.sort(key=v_prio)

        # Config presence maps from raw readme lines. NOTE the parsed_config
        # keys are the plural raw forms (handling_cfg / carcols_dat /
        # carmods_dat / vehicles_ide), not the decomposed singulars.
        _handling_ids = set()
        for _h in parsed_config.get("handling_cfg", []) or []:
            _toks = _h.split()
            if _toks:
                _t0 = _toks[0].lstrip("!$%").lower()
                if not _t0 and len(_toks) > 1:
                    _t0 = _toks[1].lstrip("!$%").lower()
                if _t0:
                    _handling_ids.add(_t0)
        _ide_handling = {}
        _ide_game_names = {}
        for _il in parsed_config.get("vehicles_ide", []) or []:
            _toks = [_t.strip() for _t in _il.split(",")]
            if len(_toks) >= 5:
                _ide_handling[_toks[1].lower()] = _toks[4].lower()
            if len(_toks) >= 6:
                _ide_game_names[_toks[1].lower()] = _toks[5].strip()
        _carcols_models = set()
        for _cc in parsed_config.get("carcols_dat", []) or []:
            _raw_cc = _cc
            if _raw_cc.lower().startswith("car4 "):
                _raw_cc = _raw_cc[5:].strip()
            _ct = [_t.strip() for _t in _raw_cc.split(",")]
            if _ct and _ct[0]:
                _carcols_models.add(_ct[0].lower())
        _carmods_models = set()
        _carmods_parts_by_model = {}
        for _cl in parsed_config.get("carmods_dat", []) or []:
            _ct = [_t.strip() for _t in _cl.split(",")]
            if _ct and _ct[0]:
                _cm = _ct[0].lower()
                _carmods_models.add(_cm)
                _parts = [p.lower() for p in _ct[1:] if re.match(r'^[a-z0-9_]{2,24}$', p.strip().lower())]
                _carmods_parts_by_model.setdefault(_cm, [])
                for _p in _parts:
                    if _p not in _carmods_parts_by_model[_cm]:
                        _carmods_parts_by_model[_cm].append(_p)

        # Enrich each target vehicle with specific assets and config indicators
        for v in target_vehicles:
            m = v["model"]
            v["source_model"] = m
            v["target_model"] = m
            v["dff_files"] = [f["name"] for f in primary_dffs if f["model"] == m or f["model"].startswith(m)]
            v["txd_files"] = [f["name"] for f in primary_txds if f["model"] == m or f["model"].startswith(m)]
            
            # Find vehicle-specific fxt if present
            v_fxt_key = _ide_game_names.get(m.lower(), m.upper()).upper()
            v_fxt_name = ""
            v_has_author_fxt = False
            v_fxt_file = ""

            # Check authoritative on-disk .fxt files first
            if v_fxt_key in author_fxt_entries:
                v_fxt_name = author_fxt_entries[v_fxt_key]["name"]
                v_has_author_fxt = True
                v_fxt_file = author_fxt_entries[v_fxt_key]["file"]
            elif m.upper() in author_fxt_entries:
                v_fxt_key = m.upper()
                v_fxt_name = author_fxt_entries[v_fxt_key]["name"]
                v_has_author_fxt = True
                v_fxt_file = author_fxt_entries[v_fxt_key]["file"]
            elif len(author_fxt_entries) == 1 and len(target_vehicles) == 1:
                single_fxt = next(iter(author_fxt_entries.values()))
                v_fxt_key = single_fxt["key"]
                v_fxt_name = single_fxt["name"]
                v_has_author_fxt = True
                v_fxt_file = single_fxt["file"]

            # Fallback to readme-scraped fxt_text
            if not v_fxt_name:
                for f_line in parsed_config.get("fxt_text", []):
                    parts = f_line.split(None, 1)
                    if parts and parts[0].upper() in (v_fxt_key, m.upper()):
                        v_fxt_key = parts[0].upper()
                        if len(parts) >= 2:
                            v_fxt_name = parts[1]
                        break

            if not v_fxt_name:
                v_fxt_name = v.get("name", m.upper())

            v["fxt_proposal"] = {
                "key": v_fxt_key,
                "name": v_fxt_name,
                "has_author_fxt": v_has_author_fxt,
                "fxt_file": v_fxt_file
            }

            # Config flags (handling falls back to the shared physics ID from
            # vehicles.ide, e.g. zr250/zr250b both ride on ZR250)
            v["has_handling"] = (m in _handling_ids) or (_ide_handling.get(m, "") in _handling_ids)
            v["has_carcols"] = m in _carcols_models
            v["has_carmods"] = m in _carmods_models
            v["carmods_parts"] = list(_carmods_parts_by_model.get(m, []))

        # Detect mutually exclusive install modes: many packs ship the same car
        # as an Added (new model) and a Replace (vanilla model) version with
        # byte-identical DFFs under different names. Keep the first vehicle
        # (the archive-name match wins via v_prio above) and tag the rest so
        # the wizard can default-skip them instead of installing duplicates.
        _size_groups: Dict[int, List[Dict[str, Any]]] = {}
        for _f in primary_dffs:
            _sz = _f.get("size") or 0
            if _sz > 0:
                _size_groups.setdefault(_sz, []).append(_f)
        _file_hashes: Dict[str, str] = {}
        for _items in _size_groups.values():
            if len(_items) < 2:
                continue
            for _f in _items:
                _digest = _file_sha1(_f.get("path", ""))
                if _digest:
                    _file_hashes[_f.get("path", "")] = _digest

        def _vehicle_asset_hashes(model_name: str) -> set:
            out = set()
            for _f in primary_dffs:
                _fm = _f["model"]
                _same = (_fm == model_name
                         or (_fm.startswith(model_name)
                             and _fm[len(model_name):] in ("1", "2", "3", "4", "5", "_1", "_2")))
                if _same and _f.get("path") in _file_hashes:
                    out.add(_file_hashes[_f["path"]])
            return out

        _hash_owner: Dict[str, str] = {}
        for _v in target_vehicles:
            _hashes = _vehicle_asset_hashes(_v["model"])
            if not _hashes:
                continue
            for _h in sorted(_hashes):
                if _h in _hash_owner:
                    _v["alternative_of"] = _hash_owner[_h]
                    break
            for _h in _hashes:
                _hash_owner.setdefault(_h, _v["model"])

        target_model = target_vehicles[0]["model"] if target_vehicles else (primary_dffs[0]["model"] if primary_dffs else None)
        target_id = MODEL_TO_ID.get(target_model) if target_model else None
        friendly_vanilla_name = " / ".join(v["name"] for v in target_vehicles) if target_vehicles else (VANILLA_VEHICLES.get(target_id, {}).get("name", target_model.upper() if target_model else ""))

        # Clean folder name proposal
        proposed_folder_name = re.sub(r'[<>:"/\\|?*]', '_', original_name).strip()
        if not proposed_folder_name:
            proposed_folder_name = f"Mod_{target_model or 'Vehicle'}"

        # FXT name proposal
        fxt_name = ""
        fxt_key = ""
        has_author_fxt = bool(author_fxt_entries)
        fxt_file = ""

        if target_vehicles and target_vehicles[0].get("fxt_proposal"):
            tp = target_vehicles[0]["fxt_proposal"]
            fxt_key = tp.get("key", "")
            fxt_name = tp.get("name", "")
            has_author_fxt = tp.get("has_author_fxt", has_author_fxt)
            fxt_file = tp.get("fxt_file", "")

        if not fxt_name:
            if author_fxt_entries:
                first_entry = next(iter(author_fxt_entries.values()))
                fxt_key = first_entry["key"]
                fxt_name = first_entry["name"]
                has_author_fxt = True
                fxt_file = first_entry["file"]
            elif parsed_config["fxt_text"]:
                first_fxt = parsed_config["fxt_text"][0]
                parts = first_fxt.split(None, 1)
                if len(parts) >= 2:
                    fxt_key = parts[0]
                    fxt_name = parts[1]
                elif len(parts) == 1:
                    fxt_key = parts[0]

        if not fxt_name and friendly_vanilla_name:
            fxt_name = proposed_folder_name

        # Author proposal detection
        detected_author = ""
        author_match = re.search(
            r'(?im)^\s*(?:author|autor|credits|by|mod by|made by|creator|model by|作者|制作|原作者)\s*[:：\-]\s*([^\r\n,;]+)',
            combined_text
        )
        if author_match:
            raw_author = author_match.group(1).strip()
            if not re.search(r'(?i)\b(rockstar|r\*|unknown|none|gta|turn 10|ea games)\b', raw_author):
                detected_author = re.sub(r'[<>:"/\\|?*]', '_', raw_author).strip()

        existing_authors = self.get_existing_authors()

        # Collect all tuning parts (DFF files plus carmods-only names such as
        # Look for any .ide files inside inspect_dir to find author-defined IDs
        author_ide_mods = {}
        for root, _, files in os.walk(inspect_dir):
            for f in files:
                if f.lower().endswith(".ide"):
                    ide_p = os.path.join(root, f)
                    try:
                        ide_text = read_text_file_safe(ide_p)
                        in_objs = False
                        for line in ide_text.splitlines():
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            if line.lower() == "objs":
                                in_objs = True
                                continue
                            if line.lower() == "end":
                                in_objs = False
                                continue
                            if in_objs:
                                parts = [p.strip() for p in line.split(",") if p.strip()]
                                if len(parts) >= 2 and parts[0].isdigit():
                                    m_id = int(parts[0])
                                    m_name = parts[1].lower()
                                    author_ide_mods[m_name] = m_id
                    except Exception:
                        pass

        # Load known registered veh_mods.ide parts (vanilla + existing shadow)
        try:
            known_veh_mods = self.merger.tuning_mgr.get_all_veh_mods_details() or {}
        except Exception:
            known_veh_mods = {}

        # Collect only genuinely NEW / CUSTOM tuning parts that require ID allocation or IDE registration.
        # Tuning parts already registered in veh_mods.ide (vanilla or shadow) without author IDE
        # are existing game parts referenced by carmods.dat and MUST NOT be treated as new parts.
        all_part_names = []
        for td in tuning_dffs:
            pname = os.path.splitext(td["name"])[0].lower()
            if pname not in known_veh_mods and pname not in all_part_names:
                all_part_names.append(pname)
        for m_name in author_ide_mods:
            if m_name not in all_part_names:
                all_part_names.append(m_name)
        for _cm_parts in _carmods_parts_by_model.values():
            for p_lower in _cm_parts:
                if p_lower not in known_veh_mods and p_lower not in all_part_names:
                    all_part_names.append(p_lower)
        tuning_parts_analysis = []
        for pname in all_part_names:
            category_info = {"category": "misc", "name_cn": "Miscellaneous", "name_en": "Miscellaneous", "prefix": ""}
            for prefix, info in TUNING_PREFIX_INFO.items():
                if pname.startswith(prefix):
                    category_info = info
                    break

            suggested_id = author_ide_mods.get(pname)
            is_conflict = False
            conflict_reason = ""
            conflict_reason_en = ""
            status = "auto"
            assigned_id = None

            if suggested_id is not None:
                id_stat = self.id_mgr.check_id_status(suggested_id)
                if id_stat["is_free"]:
                    assigned_id = suggested_id
                    status = "suggested_safe"
                else:
                    is_conflict = True
                    conflict_reason = f"Occupied by {id_stat.get('file', 'game file')} ({id_stat.get('name', 'unknown model')})"
                    conflict_reason_en = f"Occupied by {id_stat.get('file', 'game file')} ({id_stat.get('name', 'unknown')})"
                    status = "conflict"
            elif pname in known_veh_mods:
                # Already registered (vanilla or another installed mod):
                # no new ID needed, keep the existing one for display.
                try:
                    assigned_id = int(known_veh_mods[pname].get("id"))
                except Exception:
                    assigned_id = None
                status = "registered"

            tuning_parts_analysis.append({
                "part_name": pname,
                "category": category_info.get("category", "misc"),
                "name_cn": category_info.get("name_en", "Miscellaneous"),
                "name_en": category_info.get("name_en", "Miscellaneous"),
                "suggested_id": suggested_id,
                "assigned_id": assigned_id,
                "is_conflict": is_conflict,
                "conflict_reason": conflict_reason,
                "conflict_reason_en": conflict_reason_en if is_conflict else "",
                "status": status
            })

        # Second pass: allocate safe free IDs for unassigned or conflicted items
        unassigned_items = [item for item in tuning_parts_analysis if item["assigned_id"] is None]
        if unassigned_items:
            already_claimed = set(item["assigned_id"] for item in tuning_parts_analysis if item["assigned_id"] is not None)
            newly_allocated = self.id_mgr.allocate_free_ids(len(unassigned_items), exclude_ids=already_claimed)
            for idx, item in enumerate(unassigned_items):
                if idx < len(newly_allocated):
                    item["assigned_id"] = newly_allocated[idx]

        tuning_summary = {
            "total_parts": len(tuning_parts_analysis),
            "conflicts_count": sum(1 for p in tuning_parts_analysis if p["is_conflict"]),
            "auto_allocated_count": sum(1 for p in tuning_parts_analysis if p["status"] == "auto" or p["is_conflict"])
        }

        # Propose free addon vehicle IDs for ID-less new models (readme
        # [YOUR ID] placeholders). Replace packs keep their vanilla IDs.
        addon_id_proposals = {}
        try:
            _need_addon = [v for v in target_vehicles if v.get("id") is None]
            if _need_addon:
                _ids = self.id_mgr.allocate_free_addon_ids(len(_need_addon))
                for _v, _nid in zip(_need_addon, _ids):
                    _v["proposed_addon_id"] = _nid
                    addon_id_proposals[_v["model"]] = _nid
        except Exception:
            pass

        # Detect same-name multi-version files in different subfolders
        # (e.g. IVF/ vs noIVF/ zr350.dff). The UI lets the user pick one.
        variant_groups = []
        for _kind, _pool in (("vehicle", primary_dffs + primary_txds),
                             ("tuning", tuning_dffs + tuning_txds)):
            _by_name = {}
            for _f in _pool:
                _by_name.setdefault((_f.get("name") or "").lower(), []).append(_f)
            for _lname, _items in _by_name.items():
                _rels = {os.path.normpath(_f.get("rel", "")) for _f in _items}
                if len(_rels) > 1:
                    # Byte-identical copies in several folders are not versions
                    # worth asking about (e.g. same paintjob TXD twice).
                    try:
                        _paths = [_f.get("path", "") for _f in _items]
                        if _files_identical(_paths):
                            continue
                    except Exception:
                        pass
                    _opts = []
                    for _f in sorted(_items, key=lambda x: os.path.normpath(x.get("rel", "")).lower()):
                        _rel_norm = os.path.normpath(_f.get("rel", ""))
                        _parent = os.path.dirname(_rel_norm).replace(os.sep, "/") or "."
                        _opts.append({
                            "rel": _rel_norm,
                            "dir": _parent,
                            "size": _f.get("size", 0)
                        })
                    variant_groups.append({
                        "key": f"{_kind}:{_lname}",
                        "name": _items[0].get("name", _lname),
                        "kind": _kind,
                        "options": _opts
                    })
        variant_groups.sort(key=lambda g: (0 if g["kind"] == "vehicle" else 1, g["name"].lower()))

        asset_files = {
            "models": primary_dffs,
            "textures": primary_txds,
            "tuning": tuning_dffs + tuning_txds,
            "documents": [],
            "other": [],
        }
        preview_paths = {}
        for file_info in readme_files + fxt_files + other_files:
            item = dict(file_info)
            item["size"] = os.path.getsize(item["path"])
            lower_name = item["name"].lower()
            is_text = (os.path.splitext(lower_name)[1] in PREVIEW_TEXT_EXTENSIONS
                       or lower_name in {"readme", "license", "changelog", "credits"})
            asset_files["documents" if is_text else "other"].append(item)
            if is_text:
                preview_paths[item["rel"].replace(os.sep, "/")] = item["path"]
        for items in asset_files.values():
            items.sort(key=lambda item: item["rel"].lower())
        inspection_id = secrets.token_urlsafe(24)
        self._preview_sessions[inspection_id] = (os.path.realpath(inspect_dir), preview_paths, readme_files + fxt_files)
        while len(self._preview_sessions) > 8:
            del self._preview_sessions[next(iter(self._preview_sessions))]

        return {
            "success": True,
            "source_path": source_path,
            "inspection_id": inspection_id,
            "asset_files": asset_files,
            "inspect_dir": inspect_dir,
            "is_temp_extracted": bool(extracted_temp),
            "original_name": original_name,
            "proposed_folder_name": proposed_folder_name,
            "detected_author": detected_author,
            "existing_authors": existing_authors,
            "target_model": target_model,
            "target_id": target_id,
            "target_models": [v["model"] for v in target_vehicles],
            "target_vehicles": target_vehicles,
            "addon_name_conflicts": addon_name_conflicts,
            "friendly_vanilla_name": friendly_vanilla_name,
            "primary_dffs": primary_dffs,
            "primary_txds": primary_txds,
            "tuning_dffs": tuning_dffs,
            "tuning_txds": tuning_txds,
            "tuning_parts_analysis": tuning_parts_analysis,
            "tuning_summary": tuning_summary,
            "addon_id_proposals": addon_id_proposals,
            "variant_groups": variant_groups,
            "readme_files": readme_files,
            "fxt_files": [f["name"] for f in fxt_files],
            "other_files": other_files,
            "parsed_config": parsed_config,
            "has_author_fxt": has_author_fxt,
            "fxt_proposal": {
                "key": (fxt_key or (target_model.upper() if target_model else ""))[:7],
                "name": fxt_name,
                "has_author_fxt": has_author_fxt,
                "fxt_file": fxt_file
            }
        }

    def preview_source_text(self, inspection_id: str, relative_path: str) -> Dict[str, Any]:
        """Read only text files registered by a recent source inspection."""
        session = self._preview_sessions.get(inspection_id)
        if not session:
            return {"success": False, "error_code": "expired"}
        root, paths = session[0], session[1]
        file_path = paths.get(relative_path.replace("\\", "/"))
        if not file_path:
            return {"success": False, "error_code": "not_found"}
        try:
            resolved = os.path.realpath(file_path)
            if os.path.commonpath([root, resolved]) != root:
                return {"success": False, "error_code": "not_found"}
            with open(resolved, "rb") as f:
                payload = f.read(MAX_TEXT_PREVIEW_BYTES + 1)
            truncated = len(payload) > MAX_TEXT_PREVIEW_BYTES
            payload = payload[:MAX_TEXT_PREVIEW_BYTES]
            if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
                encoding = "utf-16"
            elif b"\x00" in payload:
                return {"success": False, "error_code": "binary"}
            else:
                encoding = None
                for candidate in ("utf-8-sig", "gb18030", "cp1252"):
                    try:
                        payload.decode(candidate)
                        encoding = candidate
                        break
                    except UnicodeDecodeError:
                        pass
                encoding = encoding or "utf-8"
            return {"success": True, "content": payload.decode(encoding, errors="replace"),
                    "encoding": encoding, "truncated": truncated}
        except Exception:
            return {"success": False, "error_code": "unavailable"}

    def reparse_inspection(self, inspection_id: str, excluded_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Re-parse configuration lines excluding user-deselected text/readme files.
        """
        session = self._preview_sessions.get(inspection_id)
        if not session:
            return {"success": False, "error": "Preview session expired or invalid"}

        inspect_dir = session[0]
        readme_files = session[2] if len(session) > 2 else []

        excluded_set = set()
        excluded_naked_basenames = set()
        for ef in (excluded_files or []):
            try:
                s = str(ef).strip()
                norm = os.path.normpath(s).replace("\\", "/").lower()
                excluded_set.add(norm)
                if "/" not in norm and "\\" not in s:
                    excluded_naked_basenames.add(norm)
            except Exception:
                pass

        combined_text = ""
        used_files = []
        for r in readme_files:
            rel_norm = os.path.normpath(r.get("rel", "")).replace("\\", "/").lower()
            base_norm = os.path.basename(r.get("name", "")).lower()
            if rel_norm in excluded_set or base_norm in excluded_naked_basenames:
                continue

            c = read_text_file_safe(r["path"])
            if c:
                combined_text += f"\n\n--- Readme: {r['name']} ---\n" + c
                used_files.append(r.get("rel"))

        parsed_config = self.parser.parse_text_content(combined_text)
        return {
            "success": True,
            "parsed_config": parsed_config,
            "used_files_count": len(used_files),
            "excluded_count": len(excluded_files or [])
        }

    # ---------------- Execute Installation ----------------

    def execute_install(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deploy vehicle files into ModLoader and inject configs into shadow copies.
        """
        inspect_dir = params.get("inspect_dir")
        if not inspect_dir or not os.path.isdir(inspect_dir):
            return {"success": False, "error": "Invalid source directory for installation"}

        target_category = params.get("target_category", self.data_folder).strip()
        folder_name = params.get("folder_name", "").strip()
        folder_name = re.sub(r'[<>:"/\\|?*]', '_', folder_name)
        if not folder_name:
            return {"success": False, "error": "Mod installation folder name cannot be empty"}

        # Vehicles to install (support both multi-vehicle wizard payload and legacy single-vehicle payload)
        raw_vehicles = params.get("vehicles")
        if raw_vehicles and isinstance(raw_vehicles, list):
            vehicles = [v for v in raw_vehicles if not v.get("skip")]
        else:
            target_model = params.get("target_model", "").strip().lower()
            if not target_model:
                return {"success": False, "error": "Target replacement vehicle model name not specified"}
            vehicles = [{
                "source_model": target_model,
                "target_model": target_model,
                "copy_files": params.get("copy_files", True),
                "merge_handling": params.get("merge_handling", True),
                "merge_carcols": params.get("merge_carcols", True),
                "merge_carmods": params.get("merge_carmods", True),
                "generate_fxt": params.get("generate_fxt", True),
                "fxt_key": params.get("fxt_key", target_model.upper()[:7]),
                "fxt_name": params.get("fxt_name", folder_name),
                "merge_fla": params.get("merge_fla", True),
                "tuning_id_assignments": params.get("tuning_id_assignments", {}),
                "skip": False
            }]

        if not vehicles:
            return {"success": False, "error": "All selected vehicles were skipped; installation aborted."}

        primary_target = vehicles[0]["target_model"].lower()
        author_folder = params.get("author_folder", "").strip()
        author_folder = re.sub(r'[<>:"/\\|?*]', '_', author_folder).strip()

        # Destination in ModLoader. Each vehicle may override the subfolder
        # (folder_name, blank = follow shared) and/or the top category
        # (category, blank = follow shared target_category), so addon cars
        # can live under e.g. Addon Cars while replaces stay in Modded Cars.
        def _clean_folder(s):
            return re.sub(r'[<>:"/\\|?*]', '_', (s or "").strip()).strip()

        shared_sub = _clean_folder(folder_name)
        veh_dest = {}
        dest_dirs_ordered = []
        for _idx, _v in enumerate(vehicles):
            _sub = _clean_folder(_v.get("folder_name") or "") or shared_sub
            _cat = _clean_folder(_v.get("category") or "") or target_category
            _au = _clean_folder(_v.get("author") or "") or author_folder
            if _au:
                _d = os.path.join(self.game_path, "modloader", _cat, _au, _sub)
            else:
                _d = os.path.join(self.game_path, "modloader", _cat, _sub)
            os.makedirs(_d, exist_ok=True)
            veh_dest[_idx] = _d
            if _d not in dest_dirs_ordered:
                dest_dirs_ordered.append(_d)
        mod_dest_dir = dest_dirs_ordered[0]

        copied_files = []
        applied_configs = []

        # 1. Copy Model & Texture Files with Collision Prevention
        # NOTE: packs may ship same-name variants in different subfolders
        # (e.g. IVF/ vs noIVF/ zr350.dff). Collect first, copy in sorted rel
        # order, and keep only the first file per destination name so the
        # result is deterministic instead of filesystem-order dependent.
        active_sources = {v["source_model"].lower(): v for v in vehicles if v.get("source_model")}
        all_vehicles = raw_vehicles if raw_vehicles and isinstance(raw_vehicles, list) else vehicles
        skipped_sources = {
            str(v.get("source_model") or "").lower()
            for v in all_vehicles if v.get("skip") and v.get("source_model")
        }

        # Addon conversion / rename guard: a custom model (DFF) name must be
        # valid and must not already be claimed by another vehicle anywhere in
        # ModLoader. The TXD name, when provided, follows the same rules.
        _new_names = set()
        try:
            _known_names = {rec.get("name", "").lower() for rec in (self.id_mgr.scan_all_ides() or {}).values()}
        except Exception:
            _known_names = set()
        for _v in vehicles:
            _tm = (_v.get("target_model") or "").strip().lower()
            _sm = (_v.get("source_model") or "").strip().lower()
            # GXT keys are hard-limited to 7 characters: the engine stores the
            # vehicle display name in an 8-byte field (name + NUL terminator),
            # so an 8th character can never be referenced by the game.
            _fk = str(_v.get("fxt_key") or "").strip().upper()
            if _fk and not re.fullmatch(r'[A-Z0-9_]{2,7}', _fk):
                return {"success": False,
                        "error": f"GXT key '{_fk}' is invalid (must be 2-7 uppercase alphanumeric characters or underscores)"}
            # Internal identifiers are editable for any addon target (including
            # genuine addon packages being renamed): handling ID + GXT key.
            if _tm and _tm not in MODEL_TO_ID:
                _th = str(_v.get("target_handling") or "").strip()
                if _th and not re.fullmatch(r'[A-Za-z0-9_]{2,14}', _th):
                    return {"success": False,
                            "error": f"Handling identifier '{_th}' is invalid (must be 2-14 alphanumeric characters or underscores)"}
            if not _tm or _tm in MODEL_TO_ID or _tm == _sm:
                continue
            if not re.fullmatch(r'[a-z0-9_]{2,20}', _tm):
                return {"success": False,
                        "error": f"New model name '{_tm}' is invalid (must be 2-20 lowercase alphanumeric characters or underscores)"}
            _txd = str(_v.get("target_txd") or "").strip().lower()
            if _txd and not re.fullmatch(r'[a-z0-9_]{2,20}', _txd):
                return {"success": False,
                        "error": f"Texture dictionary name '{_txd}' is invalid (must be 2-20 lowercase alphanumeric characters or underscores)"}
            if _tm in _new_names:
                return {"success": False,
                        "error": f"Multiple vehicles use the same model name '{_tm.upper()}' in this batch; please specify unique names"}
            _new_names.add(_tm)
            _existing = None
            try:
                _existing = self.merger.get_vehicle_active_configs(_tm).get("vehicles_ide")
            except Exception:
                _existing = None
            if _existing or _tm in _known_names:
                return {"success": False,
                        "error": f"Model name '{_tm.upper()}' is already occupied by an existing vehicle; please choose another name"}

        copy_tasks = []
        raw_excluded = params.get("excluded_files") or []
        excluded_files = set()
        excluded_naked_basenames = set()
        for ef in raw_excluded:
            try:
                s = str(ef).strip()
                norm = os.path.normpath(s).replace("\\", "/").lower()
                excluded_files.add(norm)
                if "/" not in norm and "\\" not in s:
                    excluded_naked_basenames.add(norm)
            except Exception:
                pass

        for root, _, files in os.walk(inspect_dir):
            for fname in files:
                src_file = os.path.join(root, fname)
                lower = fname.lower()
                base, ext = os.path.splitext(lower)
                dest_name = fname
                if lower == "vehicles.ide":
                    # Keep the author's definitions for inspection, without
                    # deploying a second active vehicles.ide beside the assets.
                    dest_name = "vehicles.ide.source"
                should_copy = True
                _vidx_task = None

                if ext in [".dff", ".txd"]:
                    if base.startswith(KNOWN_TUNING_PREFIXES) or "tuning" in root.lower():
                        # Dedicated tuning part: preserve original filename
                        dest_name = fname
                    else:
                        # Primary vehicle model / texture
                        matched_v = None
                        suffix = ""
                        if base in active_sources:
                            matched_v = active_sources[base]
                        else:
                            for sm, v_obj in active_sources.items():
                                if base.startswith(sm) and len(base) > len(sm):
                                    rest = base[len(sm):]
                                    if rest in ["1", "2", "3", "4", "5", "_1", "_2"]:
                                        matched_v = v_obj
                                        suffix = rest
                                        break

                        if matched_v:
                            if not matched_v.get("copy_files", True):
                                should_copy = False
                            else:
                                _vidx_task = vehicles.index(matched_v)
                                t_model = matched_v["target_model"].lower()
                                out_name = t_model
                                if ext == ".txd" and matched_v.get("target_txd"):
                                    out_name = str(matched_v["target_txd"]).strip().lower() or t_model
                                dest_name = f"{out_name}{suffix}{ext}"
                        elif any(
                            base == sm
                            or (base.startswith(sm) and base[len(sm):] in ("1", "2", "3", "4", "5", "_1", "_2"))
                            for sm in skipped_sources
                        ):
                            # Asset of a vehicle deselected in the wizard: never
                            # rename/copy it onto the selected vehicle.
                            should_copy = False
                        else:
                            if len(vehicles) == 1:
                                matched_v = vehicles[0]
                                if not matched_v.get("copy_files", True):
                                    should_copy = False
                                else:
                                    _vidx_task = 0
                                    t_model = matched_v["target_model"].lower()
                                    out_name = t_model
                                    if ext == ".txd" and matched_v.get("target_txd"):
                                        out_name = str(matched_v["target_txd"]).strip().lower() or t_model
                                    for s in ["1", "2", "3", "4", "5"]:
                                        if base.endswith(s) and len(base) > len(s):
                                            suffix = s
                                            break
                                    dest_name = f"{out_name}{suffix}{ext}"
                            else:
                                # In multi-car pack, keep original name to prevent overwriting
                                dest_name = fname
                elif ext in _DOC_TEXT_EXTENSIONS and len(all_vehicles) > 1:
                    # Route config documents (readme/txt/ide/cfg) to the vehicle
                    # they declare instead of dumping every one into the first
                    # destination folder.
                    _doc_models = _doc_referenced_models(self.parser, src_file)
                    _active_owners = []
                    for _vi, _vv in enumerate(vehicles):
                        _sm = (_vv.get("source_model") or "").lower()
                        if _sm and _sm in _doc_models:
                            _active_owners.append(_vi)
                    if len(_active_owners) == 1:
                        _vidx_task = _active_owners[0]
                    elif not _active_owners and any(sm in _doc_models for sm in skipped_sources):
                        # Document belongs solely to a skipped vehicle: deploy
                        # neither its files nor its configs.
                        should_copy = False

                if should_copy:
                    rel = os.path.relpath(src_file, inspect_dir)
                    rel_norm = os.path.normpath(rel).replace("\\", "/").lower()
                    if rel_norm in excluded_files or fname.lower() in excluded_naked_basenames:
                        continue
                    _is_tuning_file = ext in [".dff", ".txd"] and (
                        base.startswith(KNOWN_TUNING_PREFIXES) or "tuning" in root.lower())
                    _gkey = f"{'tuning' if _is_tuning_file else 'vehicle'}:{fname.lower()}"
                    copy_tasks.append((rel, src_file, dest_name, _gkey, _vidx_task))

        copy_tasks.sort(key=lambda t: os.path.normpath(t[0]).lower())
        # Honor explicit multi-version choices from the UI variant picker.
        # variant_choices: {group_key: rel}. Unchosen groups fall back to the
        # first sorted option (with a warning, see below).
        raw_choices = params.get("variant_choices") or {}
        norm_choices = {}
        if isinstance(raw_choices, dict):
            for _k, _v in raw_choices.items():
                try:
                    norm_choices[str(_k)] = os.path.normpath(str(_v))
                except Exception:
                    continue
        if norm_choices:
            _grouped = {}
            for _t in copy_tasks:
                _grouped.setdefault(_t[3], []).append(_t)
            _filtered = []
            for _gk, _items in _grouped.items():
                _rels = {os.path.normpath(_t[0]) for _t in _items}
                if _gk in norm_choices and len(_rels) > 1:
                    _want = norm_choices[_gk]
                    _hit = [_t for _t in _items if os.path.normpath(_t[0]) == _want]
                    if _hit:
                        _filtered.extend(_hit)
                        continue
                _filtered.extend(_items)
            copy_tasks = _filtered

        used_dest = {}
        variant_warnings = []
        multi_dir = len(dest_dirs_ordered) > 1
        for rel, src_file, dest_name, _gkey, _vidx_task in copy_tasks:
            if dest_name.lower().endswith(".fxt"):
                continue  # FXT entries are routed by their keys below.
            _ddir = veh_dest.get(_vidx_task, dest_dirs_ordered[0])
            dest_key = (_ddir.lower(), dest_name.lower())
            if dest_key in used_dest:
                _prev_rel, _prev_src = used_dest[dest_key]
                if _files_identical([_prev_src, src_file]):
                    continue
                variant_warnings.append(
                    f"Multiple versions of {dest_name}: selected {_prev_rel}, skipped {rel}"
                )
                continue
            dest_file = os.path.join(_ddir, dest_name)
            try:
                shutil.copy2(src_file, dest_file)
                if multi_dir:
                    copied_files.append(f"{os.path.basename(_ddir)}/{dest_name}")
                else:
                    copied_files.append(dest_name)
                used_dest[dest_key] = (rel, src_file)
            except Exception as e:
                print(f"Error copying {src_file}: {e}")

        # 2. Resolve original IDE name keys before applying user overrides.
        # Use only selected source files (the same exclusion/variant filters as
        # deployment), including Readmes whose model IDs are placeholders.
        source_keys = {}
        ide_lines = []
        for _, source_file, _, _, _ in copy_tasks:
            if os.path.splitext(source_file)[1].lower() in (".txt", ".readme", ".md", ".ide", ".cfg", ".dat"):
                parsed_source = self.parser.parse_text_content(read_text_file_safe(source_file))
                ide_lines.extend(parsed_source.get("vehicles_ide", []))
        ide_lines.extend((params.get("parsed_config") or {}).get("vehicles_ide", []))
        for line in ide_lines:
            tokens = [token.strip() for token in line.split(",")]
            if len(tokens) >= 6:
                source_keys[tokens[1].lower()] = tokens[5].upper()
        all_destinations = []
        active_index = 0
        for vehicle in all_vehicles:
            if vehicle.get("skip"):
                all_destinations.append(None)
            else:
                all_destinations.append(veh_dest[active_index])
                active_index += 1
        previous_fxt_keys = {}
        for vehicle in vehicles:
            target = vehicle.get("target_model", "").lower()
            active_ide = self.merger.get_vehicle_active_configs(target).get("vehicles_ide")
            if active_ide:
                tokens = [token.strip() for token in active_ide["raw"].split(",")]
                if len(tokens) >= 6:
                    previous_fxt_keys[target] = tokens[5].upper()
        # Keys owned by skipped vehicles must not be re-homed into an active
        # destination by the shared "unowned author entry" fallback.
        skipped_fxt_keys = set()
        for vehicle in all_vehicles:
            if not vehicle.get("skip"):
                continue
            sm = (vehicle.get("source_model") or "").lower()
            if not sm:
                continue
            skipped_fxt_keys.add(sm.upper())
            ide_key = source_keys.get(sm, "")
            if ide_key:
                skipped_fxt_keys.add(ide_key.upper())
        try:
            fxt_changed, final_fxt_keys = deploy_fxt(
                [task[1] for task in copy_tasks if task[2].lower().endswith(".fxt")],
                all_vehicles, all_destinations, source_keys, self.backup_manager, previous_fxt_keys,
                ignored_keys=skipped_fxt_keys)
            applied_configs.extend(os.path.relpath(path, os.path.join(self.game_path, "modloader"))
                                   for path in fxt_changed)
        except (OSError, ValueError) as error:
            return {"success": False, "error": f"Failed to deploy FXT vehicle name: {error}"}

        # 3. Merge Configurations into the single replacement shadow data set.
        # Addon Cars is an asset directory only; global vehicles.ide and the
        # other shared config files must stay in the active Modded Cars folder.
        # With per-vehicle folders, inspect every created folder and combine
        # the parsed configs (readme usually lands in the first folder while
        # split folders contribute their model files).
        mod_info = None
        for _ddir in dest_dirs_ordered:
            _info = self.parser.inspect_mod_directory(_ddir)
            if not _info.get("success"):
                continue
            if mod_info is None:
                mod_info = _info
            else:
                for _pk in ("handling", "ide", "carcols", "carmods", "veh_mods_ide",
                            "fxt", "fxt_text", "audio_lines", "special_features"):
                    _dst = mod_info["parsed"].setdefault(_pk, [])
                    for _it in _info["parsed"].get(_pk, []) or []:
                        if _it not in _dst:
                            _dst.append(_it)
                if "shopping" in _info.get("parsed", {}):
                    _dst_shop = mod_info["parsed"].setdefault("shopping", {"carmods": [], "workshops": {}})
                    _src_shop = _info["parsed"]["shopping"]
                    for _ce in _src_shop.get("carmods", []):
                        if not any(x.get("part_name") == _ce.get("part_name") for x in _dst_shop.get("carmods", [])):
                            _dst_shop.setdefault("carmods", []).append(_ce)
                    for _wname, _wparts in _src_shop.get("workshops", {}).items():
                        _dw = _dst_shop.setdefault("workshops", {}).setdefault(_wname, [])
                        for _wp in _wparts:
                            if _wp not in _dw:
                                _dw.append(_wp)
                for _fk in ("dff_files", "tuning_dffs", "txd_files"):
                    _fd = mod_info["files"].setdefault(_fk, [])
                    for _it in _info["files"].get(_fk, []) or []:
                        if _it not in _fd:
                            _fd.append(_it)
        if params.get("parsed_config"):
            pcfg = params["parsed_config"]
            if mod_info is None or not mod_info.get("success"):
                mod_info = {
                    "success": True,
                    "mod_name": folder_name,
                    "files": {"dff_files": [], "txd_files": [], "fxt_files": [], "tuning_dffs": []},
                    "parsed": {
                        "handling": [], "ide": [], "carcols": [], "carmods": [],
                        "veh_mods_ide": [], "shopping": {"carmods": [], "workshops": {}},
                        "fxt": [], "fxt_text": [], "audio_lines": [], "special_features": []
                    }
                }
            if "handling_cfg" in pcfg:
                mod_info["parsed"]["handling"] = [
                    self.parser.decompose_handling(l) for l in pcfg["handling_cfg"]
                ]
                mod_info["parsed"]["handling"] = [h for h in mod_info["parsed"]["handling"] if h]
            if "vehicles_ide" in pcfg:
                mod_info["parsed"]["ide"] = [
                    self.parser.decompose_ide(l) for l in pcfg["vehicles_ide"]
                ]
                mod_info["parsed"]["ide"] = [i for i in mod_info["parsed"]["ide"] if i]
            if "carcols_dat" in pcfg:
                mod_info["parsed"]["carcols"] = [
                    self.parser.decompose_carcols(l) for l in pcfg["carcols_dat"]
                ]
                mod_info["parsed"]["carcols"] = [c for c in mod_info["parsed"]["carcols"] if c]
            if "carmods_dat" in pcfg:
                mod_info["parsed"]["carmods"] = [
                    self.parser.decompose_carmods(l) for l in pcfg["carmods_dat"]
                ]
                mod_info["parsed"]["carmods"] = [cm for cm in mod_info["parsed"]["carmods"] if cm]
            if "veh_mods_ide" in pcfg:
                mod_info["parsed"]["veh_mods_ide"] = [
                    self.parser.decompose_ide(l) for l in pcfg["veh_mods_ide"]
                ]
                mod_info["parsed"]["veh_mods_ide"] = [vm for vm in mod_info["parsed"]["veh_mods_ide"] if vm]
            if "shopping_dat" in pcfg:
                mod_info["parsed"]["shopping"] = self.parser.decompose_shopping(pcfg["shopping_dat"])
            if "vehicle_audio" in pcfg:
                mod_info["parsed"]["audio_lines"] = list(pcfg["vehicle_audio"])
            if "special_features" in pcfg:
                mod_info["parsed"]["special_features"] = list(pcfg["special_features"])
        elif mod_info is None:
            mod_info = {"success": False}

        if mod_info.get("success"):
            mod_info["target_model"] = primary_target
            mod_info["target_models"] = [v["target_model"].lower() for v in vehicles]

            # Re-align Handling for all vehicles
            final_handling = []
            orig_handling = [h for h in (mod_info["parsed"].get("handling", []) or []) if h]
            _ide_handling_by_model = {}
            for _ide in (mod_info["parsed"].get("ide", []) or []):
                if _ide and _ide.get("model_name") and _ide.get("handling_id"):
                    _ide_handling_by_model[(_ide.get("model_name") or "").lower()] = (_ide.get("handling_id") or "").lower()

            def _target_handling_id(model_name: str) -> str:
                try:
                    _info = self.merger.get_vehicle_active_configs(model_name)
                    _decomp = (_info.get("vehicles_ide") or {}).get("decomposed") or {}
                    if _decomp.get("handling_id"):
                        return _decomp["handling_id"].upper()
                except Exception:
                    pass
                return model_name.upper()[:14]

            # New handling IDs produced for replace->addon conversions, so the
            # finalised vehicles.ide line can reference them.
            final_handling_ids = {}

            for v in vehicles:
                if not v.get("merge_handling", True):
                    continue
                s_model = v.get("source_model", "").lower()
                t_model = v.get("target_model", "").lower()
                # Handling IDs often differ from the model name (blister ->
                # BLISTR, zr350b -> ZR250 ...). Resolve the author's handling
                # ID from the parsed vehicles.ide before matching.
                source_hid = _ide_handling_by_model.get(s_model, "")
                matched_h = None
                for h in orig_handling:
                    hid = (h.get("identifier") or "").lower()
                    if hid and hid in {s_model, t_model, source_hid}:
                        matched_h = h
                        break
                if not matched_h and len(vehicles) == 1 and len(orig_handling) == 1:
                    matched_h = orig_handling[0]

                if matched_h:
                    h_copy = dict(matched_h)
                    explicit_hid = str(v.get("target_handling") or "").strip().upper()
                    current_hid = (matched_h.get("identifier") or "").strip().upper()
                    if explicit_hid:
                        target_hid = explicit_hid
                    elif s_model == t_model:
                        # Addon / same-slot install: the deployed vehicles.ide
                        # keeps referencing the author's handling ID (e.g.
                        # BLISTR for model "blister"), so never rename the line.
                        final_handling.append(h_copy)
                        continue
                    else:
                        target_hid = _target_handling_id(t_model)
                    if t_model not in MODEL_TO_ID and target_hid:
                        # Addon target: the finalised vehicles.ide Handling
                        # column must reference this identifier.
                        final_handling_ids[t_model] = target_hid
                    if not target_hid or target_hid == current_hid:
                        final_handling.append(h_copy)
                        continue
                    prefix = matched_h.get("prefix", "")
                    prefix_spaced = matched_h.get("prefix_spaced", False)
                    raw_str = h_copy.get("raw", "").strip()
                    tokens = raw_str.split()
                    if tokens:
                        if tokens[0] in ("!", "$", "%"):
                            tokens[0] = prefix or tokens[0]
                            if len(tokens) > 1:
                                tokens[1] = target_hid
                        else:
                            pfx = prefix
                            if not pfx and tokens[0] and tokens[0][0] in ("!", "$", "%"):
                                pfx = tokens[0][0]
                            if pfx:
                                tokens[0] = f"{pfx} {target_hid}" if prefix_spaced else f"{pfx}{target_hid}"
                            else:
                                tokens[0] = target_hid
                        h_copy["raw"] = " ".join(tokens)
                        h_copy["identifier"] = target_hid
                        if prefix:
                            h_copy["prefix"] = prefix
                    final_handling.append(h_copy)
            mod_info["parsed"]["handling"] = final_handling

            # Re-align Carcols for all vehicles
            final_carcols = []
            orig_carcols = [c for c in (mod_info["parsed"].get("carcols", []) or []) if c]
            for v in vehicles:
                if not v.get("merge_carcols", True):
                    continue
                s_model = v.get("source_model", "").lower()
                t_model = v.get("target_model", "").lower()
                matched_c = None
                for c in orig_carcols:
                    if (c.get("model_name") or "").lower() == s_model:
                        matched_c = c
                        break
                if not matched_c and len(vehicles) == 1 and orig_carcols:
                    matched_c = orig_carcols[0]

                if matched_c:
                    c_copy = dict(matched_c)
                    raw_c = c_copy.get("raw", "").strip()
                    is_car4 = c_copy.get("is_car4", False) or raw_c.lower().startswith("car4 ")
                    if raw_c.lower().startswith("car4 "):
                        raw_c = raw_c[5:].strip()
                    tokens = [t.strip() for t in raw_c.split(",")]
                    if tokens:
                        tokens[0] = t_model.lower()
                        new_raw = ", ".join(tokens)
                        if is_car4:
                            new_raw = f"car4 {new_raw}"
                        c_copy["raw"] = new_raw
                        c_copy["model_name"] = t_model.lower()
                        c_copy["is_car4"] = is_car4
                    final_carcols.append(c_copy)
            mod_info["parsed"]["carcols"] = final_carcols

            # Re-align Carmods for all vehicles
            final_carmods = []
            orig_carmods = [cm for cm in (mod_info["parsed"].get("carmods", []) or []) if cm]
            for v in vehicles:
                if not v.get("merge_carmods", True):
                    continue
                s_model = v.get("source_model", "").lower()
                t_model = v.get("target_model", "").lower()
                matched_cm = None
                for cm in orig_carmods:
                    cm_m = (cm.get("model") or cm.get("model_name") or "").lower()
                    if cm_m == s_model:
                        matched_cm = cm
                        break
                if not matched_cm and len(vehicles) == 1 and orig_carmods:
                    matched_cm = orig_carmods[0]

                if matched_cm:
                    cm_copy = dict(matched_cm)
                    tokens = [t.strip() for t in cm_copy.get("raw", "").split(",")]
                    if tokens:
                        tokens[0] = t_model.lower()
                        cm_copy["raw"] = ", ".join(tokens)
                        cm_copy["model"] = t_model.lower()
                        cm_copy["model_name"] = t_model.lower()
                    final_carmods.append(cm_copy)
            mod_info["parsed"]["carmods"] = final_carmods

            # Only merge selected vehicles' FLA rows, honoring each checkbox
            # and remapping the model name when installing onto another slot.
            for config_key in ("audio_lines", "special_features"):
                rows = {}
                for raw in mod_info["parsed"].get(config_key, []):
                    parts = raw.split(None, 1)
                    if len(parts) == 2:
                        rows[parts[0].lower()] = parts[1]
                selected_rows = []
                for vehicle in vehicles:
                    source = vehicle.get("source_model", "").lower()
                    target = vehicle.get("target_model", "").lower()
                    if vehicle.get("merge_fla", True) and source in rows:
                        if config_key == "audio_lines":
                            selected_rows.append(FLAManager.format_audio_line(target, rows[source]))
                        else:
                            selected_rows.append(f"{target} {rows[source]}")
                mod_info["parsed"][config_key] = selected_rows

            # Finalize addon vehicles.ide lines: replace [YOUR ID] placeholders
            # with real free IDs so the merger can deploy them. Replace packs
            # (vanilla models) are intentionally left untouched.
            # User-supplied IDs (addon_id_assignments / vehicles[].addon_id)
            # are validated strictly: out-of-range or occupied-by-other IDs
            # abort the install instead of being silently replaced.
            try:
                _addon_assign = params.get("addon_id_assignments") or {}
                _addon_assign = {str(_k).lower(): _v for _k, _v in _addon_assign.items()} \
                    if isinstance(_addon_assign, dict) else {}
                for _v in vehicles:
                    _vk = (_v.get("target_model") or "").lower()
                    if _vk and _vk not in MODEL_TO_ID and _v.get("addon_id") not in (None, ""):
                        _addon_assign.setdefault(_vk, _v.get("addon_id"))
                for _mk, _mv in list(_addon_assign.items()):
                    try:
                        _iv = int(_mv)
                    except (ValueError, TypeError):
                        return {"success": False,
                                "error": f"Invalid ID {_mv} for new vehicle {_mk} (must be a number between 612 and 65535)"}
                    if _iv < 612 or _iv > 65535:
                        return {"success": False,
                                "error": f"ID {_iv} for new vehicle {_mk} is out of range (must be between 612 and 65535)"}
                    try:
                        _st0 = self.id_mgr.check_id_status(_iv)
                    except Exception:
                        _st0 = {"is_free": True}
                    if not _st0.get("is_free") and str(_st0.get("name", "")).lower() != _mk:
                        return {"success": False,
                                "error": f"ID {_iv} for new vehicle {_mk} is already occupied ({_st0.get('name', '')})"}
                    _addon_assign[_mk] = _iv
                _ide_entries = mod_info["parsed"].get("ide", []) or []
                _final_ide = []
                _used_addon_ids = set()
                for _k, _vv in _addon_assign.items():
                    try:
                        _used_addon_ids.add(int(_vv))
                    except (ValueError, TypeError):
                        pass
                for _v in vehicles:
                    _tm = (_v.get("target_model") or "").lower()
                    if not _tm or _tm in MODEL_TO_ID:
                        continue
                    _nid = None
                    try:
                        if _tm in _addon_assign:
                            _nid = int(_addon_assign[_tm])
                    except (ValueError, TypeError):
                        _nid = None
                    if _nid is None:
                        _got = self.id_mgr.allocate_free_addon_ids(1, exclude_ids=_used_addon_ids)
                        _nid = _got[0] if _got else None
                    if _nid is None:
                        continue
                    try:
                        _st = self.id_mgr.check_id_status(int(_nid))
                        if not _st.get("is_free") and str(_st.get("name", "")).lower() != _tm:
                            _got = self.id_mgr.allocate_free_addon_ids(1, exclude_ids=_used_addon_ids)
                            _nid = _got[0] if _got else None
                    except Exception:
                        pass
                    if _nid is None:
                        continue
                    _used_addon_ids.add(int(_nid))
                    _matched = next(
                        (d for d in _ide_entries if d and (d.get("model_name") or "").lower() == (_v.get("source_model") or _tm).lower()), None)
                    if _matched is None:
                        # Only adopt a single unambiguous non-vanilla IDE entry;
                        # never steal a vanilla or skipped-vehicle definition.
                        _candidates = [
                            d for d in _ide_entries
                            if d and (d.get("model_name") or "").lower() not in MODEL_TO_ID
                            and (d.get("model_name") or "").lower() not in skipped_sources
                        ]
                        if len(vehicles) == 1 and len(_candidates) == 1:
                            _matched = _candidates[0]
                    if _matched and _matched.get("raw"):
                        _toks = [_t.strip() for _t in _matched["raw"].split(",")]
                        if len(_toks) >= 3:
                            _toks[0] = str(int(_nid))
                            _toks[1] = _tm
                            _txd = str(_v.get("target_txd") or "").strip().lower()
                            _toks[2] = _txd if _txd else _tm
                            if len(_toks) >= 5 and _tm in final_handling_ids:
                                _toks[4] = final_handling_ids[_tm]
                            if len(_toks) >= 6 and _tm in final_fxt_keys:
                                _toks[5] = final_fxt_keys[_tm]
                            _new_raw = ", ".join(_toks)
                            _dec = self.parser.decompose_ide(_new_raw)
                            _final_ide.append(_dec or {"raw": _new_raw, "model_name": _tm, "id": int(_nid)})
                _kept = [d for d in _ide_entries
                         if d and (d.get("model_name") or "").lower() in MODEL_TO_ID]
                mod_info["parsed"]["ide"] = _kept + _final_ide
            except Exception as _ide_exc:
                variant_warnings.append(f"Failed to register new vehicle in vehicles.ide: {_ide_exc}")

            # Surface silently unregistered addon vehicles instead of shipping
            # assets that can never appear in game.
            _registered_models = {
                (d.get("model_name") or "").lower()
                for d in (mod_info["parsed"].get("ide", []) or []) if d
            }
            for _v in vehicles:
                _tm_reg = (_v.get("target_model") or "").lower()
                if _tm_reg and _tm_reg not in MODEL_TO_ID and _tm_reg not in _registered_models:
                    variant_warnings.append(
                        f"New vehicle {_tm_reg.upper()} was not added to vehicles.ide (missing available ID or IDE definition); it may not spawn in game")

            # Custom / User-assigned Tuning Part IDs: only include genuinely new parts
            combined_custom_ids = {}
            for v in vehicles:
                combined_custom_ids.update(v.get("tuning_id_assignments", {}))
            if params.get("tuning_id_assignments"):
                combined_custom_ids.update(params.get("tuning_id_assignments"))
            try:
                existing_mods = self.merger.tuning_mgr.get_existing_veh_mods()
            except Exception:
                existing_mods = {}
            combined_custom_ids = {
                k.lower(): v for k, v in combined_custom_ids.items()
                if k.lower() not in existing_mods
            }
            if combined_custom_ids:
                mod_info["custom_tuning_ids"] = combined_custom_ids

            merge_res = self.merger.apply_merge(mod_info)
            if merge_res.get("success"):
                applied_configs.extend(merge_res.get("applied_files", []))
                # Replacement IDE definitions retain all baseline fields. Only
                # update their name reference when an FXT key actually changed.
                for model, key in final_fxt_keys.items():
                    if model not in MODEL_TO_ID:
                        continue
                    active_ide = self.merger.get_vehicle_active_configs(model).get("vehicles_ide")
                    if not active_ide:
                        if key != model.upper():
                            merge_res["success"] = False
                            merge_res.setdefault("errors", []).append(f"Cannot update FXT key for {model}: missing vehicle IDE definition")
                        continue
                    tokens = [token.strip() for token in active_ide["raw"].split(",")]
                    if len(tokens) >= 6 and tokens[5].upper() != key:
                        tokens[5] = key
                        result = self.merger.save_vehicle_config(model, "vehicles_ide", ", ".join(tokens))
                        if result.get("success"):
                            if "vehicles.ide" not in applied_configs:
                                applied_configs.append("vehicles.ide")
                        else:
                            merge_res["success"] = False
                            merge_res.setdefault("errors", []).append(result.get("error", "Failed to update IDE reference for FXT key"))

        else:
            merge_res = {"success": True, "applied_files": [], "errors": []}

        # Clean up temp staging directory if was extracted from archive
        if params.get("is_temp_extracted", False):
            try:
                shutil.rmtree(inspect_dir, ignore_errors=True)
            except Exception:
                pass

        _modloader_root = os.path.join(self.game_path, "modloader")
        return {
            "success": merge_res.get("success", False),
            "installed_path": mod_dest_dir,
            "installed_paths": dest_dirs_ordered,
            "vehicle_folders": {
                v["target_model"].lower(): os.path.relpath(veh_dest[idx], _modloader_root).replace(os.sep, "/")
                for idx, v in enumerate(vehicles)
            },
            "target_category": target_category,
            "folder_name": folder_name,
            "target_model": primary_target,
            "target_models": [v["target_model"].lower() for v in vehicles],
            "vehicles_count": len(vehicles),
            "copied_files_count": len(copied_files),
            "copied_files": copied_files,
            "applied_configs": applied_configs,
            "warnings": variant_warnings,
            "errors": merge_res.get("errors", []),
            "error": "; ".join(merge_res.get("errors", [])) if not merge_res.get("success") and merge_res.get("errors") else ""
        }
