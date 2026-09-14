"""
Configuration Merger: Performs virtual dry-runs and safe delta merges into ModLoader shadow files.
"""

import os
import re
import shutil
import time
from typing import Dict, Any, List, Optional, Set
from .tuning_manager import TuningManager, determine_veh_mod_flags
from .fla_manager import FLAManager
from .parser import DualTrackParser, normalize_ide_line
from .vanilla_data import MODEL_TO_ID
from .backup_manager import BackupManager
from .atomic_io import write_text_atomic

def _norm_config_line(raw: str) -> str:
    """Whitespace/case-insensitive normalization used to tell a shadow line
    apart from an untouched vanilla baseline line."""
    if raw is None:
        return ""
    return " ".join(str(raw).replace(",", " , ").split()).lower()


class ConfigMerger:
    def __init__(self, shadow_dir: str, game_path: str, backup_manager: Optional[BackupManager] = None):
        self.shadow_dir = os.path.normpath(shadow_dir)
        self.game_path = os.path.normpath(game_path)
        self.backup_manager = backup_manager or BackupManager(game_dir=self.game_path)
        self.tuning_mgr = TuningManager(self.shadow_dir, self.game_path)
        self.fla_mgr = FLAManager(self.game_path, backup_manager=self.backup_manager)
        self.parser = DualTrackParser()

    def plan_merge(self, parsed_mod: Dict[str, Any]) -> Dict[str, Any]:
        """
        Produce a Dry-Run plan showing exact line additions / replacements
        for all relevant configuration files.
        """
        target_model = parsed_mod.get("target_model")
        target_vanilla_info = parsed_mod.get("target_vanilla")
        if not target_model:
            return {"success": False, "error": "Cannot determine target replacement vehicle model"}

        changes = {
            "carmods_dat": {"file": os.path.join(self.shadow_dir, "carmods.dat"), "actions": []},
            "shopping_dat": {"file": os.path.join(self.shadow_dir, "shopping.dat"), "actions": []},
            "veh_mods_ide": {"file": os.path.join(self.shadow_dir, "veh_mods.ide"), "actions": []},
            "handling_cfg": {"file": os.path.join(self.shadow_dir, "handling.cfg"), "actions": []},
            "carcols_dat": {"file": os.path.join(self.shadow_dir, "carcols.dat"), "actions": []},
            "vehicles_ide": {"file": os.path.join(self.shadow_dir, "vehicles.ide"), "actions": []},
            "audio_settings": {"file": self.fla_mgr.audio_path, "actions": []},
            "special_features": {"file": self.fla_mgr.special_path, "actions": []},
        }

        # 1. Tuning parts & carmods
        carmods_parsed = parsed_mod["parsed"]["carmods"]
        tuning_dffs = parsed_mod["files"].get("tuning_dffs", [])
        custom_tuning_ids = parsed_mod.get("custom_tuning_ids") or {}
        allocated_tuning_ids = dict(custom_tuning_ids)
        shopping_parsed = parsed_mod["parsed"].get("shopping") or {}
        author_carmods_dict = {e["part_name"].lower(): e for e in shopping_parsed.get("carmods", [])}
        author_workshops = shopping_parsed.get("workshops") or {}
        author_veh_mods = {
            vm["part_name"].lower(): vm
            for vm in (parsed_mod.get("parsed", {}).get("veh_mods_ide") or [])
            if isinstance(vm, dict) and vm.get("part_name")
        }
        dff_map = {
            os.path.splitext(td.get("name", ""))[0].lower(): td.get("path")
            for td in tuning_dffs
            if isinstance(td, dict) and td.get("name") and td.get("path")
        }

        seen_veh_mods_parts = set()
        seen_shopping_carmods = set()
        seen_workshop_parts = set()

        def _plan_shopping_for_parts(cm_model_name: str, part_list: List[str]):
            # 1. Price definitions for section CarMods
            for p in part_list:
                pl = p.lower().strip()
                if self.tuning_mgr.is_mirror_counterpart(pl):
                    continue
                if pl in seen_shopping_carmods:
                    continue
                seen_shopping_carmods.add(pl)

                if pl in author_carmods_dict:
                    auth_e = author_carmods_dict[pl]
                    ntag = auth_e["nametag"]
                    pr = auth_e["price"]
                    resp = auth_e.get("respect", 0)
                    sxy = auth_e.get("sexy", 0)
                    raw_cmt = auth_e.get("comment", "").lstrip('#').strip()
                    cmt = f"\t# {raw_cmt}" if raw_cmt else f"\t# FOR {cm_model_name.upper()}"
                    line = f"\t\t{pl:<16}\t{ntag:<8}\trespect {resp} \tsexy {sxy}\t\t{pr}{cmt}"
                    changes["shopping_dat"]["actions"].append({
                        "type": "append_carmods_entry",
                        "part": pl,
                        "line": line,
                        "price": pr,
                        "author": True,
                        "desc": f"Register part price ({ntag}): {pl} (${pr})"
                    })
                else:
                    missing_shop = self.tuning_mgr.generate_missing_shopping_entries([pl], cm_model_name)
                    for item in missing_shop:
                        changes["shopping_dat"]["actions"].append({
                            "type": "append_carmods_entry",
                            "part": item["part_name"],
                            "line": item["line"].rstrip(),
                            "price": item["price"],
                            "desc": f"Add crash-prevention price entry: {item['part_name']} (${item['price']})"
                        })

            # 2. Workshop items for section carmod1/2/3
            if author_workshops:
                for w_sec, w_parts in author_workshops.items():
                    for wp in w_parts:
                        wp_clean = wp.lower().strip()
                        pair_key = (w_sec.lower(), wp_clean)
                        if pair_key in seen_workshop_parts:
                            continue
                        if not part_list or wp_clean in [x.lower() for x in part_list]:
                            seen_workshop_parts.add(pair_key)
                            changes["shopping_dat"]["actions"].append({
                                "type": "append_workshop_item",
                                "workshop": w_sec.lower(),
                                "part": wp_clean,
                                "line": f"\t\titem {wp_clean}",
                                "desc": f"Add to tuning shop ({w_sec}): item {wp_clean}"
                            })
            else:
                inferred_sec = self.tuning_mgr.infer_workshop_section(
                    cm_model_name, part_list, (target_vanilla_info or {}).get("shop")
                )
                for p in part_list:
                    pl = p.lower().strip()
                    if self.tuning_mgr.is_mirror_counterpart(pl):
                        continue
                    pair_key = (inferred_sec.lower(), pl)
                    if pair_key in seen_workshop_parts:
                        continue
                    seen_workshop_parts.add(pair_key)
                    changes["shopping_dat"]["actions"].append({
                        "type": "append_workshop_item",
                        "workshop": inferred_sec,
                        "part": pl,
                        "line": f"\t\titem {pl}",
                        "desc": f"Add to tuning shop ({inferred_sec}): item {pl}"
                    })

        if carmods_parsed:
            for cm in carmods_parsed:
                cm_model = (cm.get("model") or cm.get("model_name") or target_model).lower()
                parts = list(cm.get("part_names", []))
                if len(carmods_parsed) == 1:
                    for tdff in tuning_dffs:
                        pname = os.path.splitext(tdff["name"])[0].lower()
                        if pname not in parts:
                            parts.append(pname)
                if parts:
                    # The package declares this part list: deploy it as-is
                    # (mirror counterparts move to the link section below).
                    # Generic upgrades are only preserved when the tool has to
                    # synthesize the list itself - see the tuning_dffs branch.
                    vehicle_parts = [p for p in parts if not self.tuning_mgr.is_mirror_counterpart(p)]
                    if vehicle_parts:
                        mods_line = f"{cm_model}, " + ", ".join(vehicle_parts)
                        changes["carmods_dat"]["actions"].append({
                            "type": "replace_or_insert_car_mods",
                            "car": cm_model,
                            "line": mods_line,
                            "desc": f"Assign {len(vehicle_parts)} tuning parts to {cm_model}"
                        })
                    links = self.tuning_mgr.find_mirror_links(parts)
                    existing_links = self.tuning_mgr.get_existing_link_pairs()
                    for l, r in links:
                        if frozenset((l.lower(), r.lower())) in existing_links:
                            continue
                        changes["carmods_dat"]["actions"].append({
                            "type": "insert_link",
                            "line": f"{l}, {r}",
                            "desc": f"Register symmetrical mirror parts: {l} <-> {r}"
                        })
                    _plan_shopping_for_parts(cm_model, vehicle_parts)
                    missing_mods = self.tuning_mgr.generate_missing_veh_mods_entries(
                        parts, cm_model, custom_ids=allocated_tuning_ids,
                        part_configs=author_veh_mods, dff_map=dff_map
                    )
                    for item in missing_mods:
                        pname = item["part_name"]
                        allocated_tuning_ids[pname] = item["id"]
                        if pname not in seen_veh_mods_parts:
                            seen_veh_mods_parts.add(pname)
                            changes["veh_mods_ide"]["actions"].append({
                                "type": "append_veh_mod_id",
                                "id": item["id"],
                                "part": pname,
                                "line": item["line"],
                                "desc": f"Allocate new tuning part model ID: {item['id']} -> {pname}"
                            })
        elif tuning_dffs:
            parts = []
            for tdff in tuning_dffs:
                pname = os.path.splitext(tdff["name"])[0].lower()
                if pname not in parts:
                    parts.append(pname)
            if parts:
                vehicle_parts = [p for p in parts if not self.tuning_mgr.is_mirror_counterpart(p)]
                # No carmods.dat came with the package: the tool builds the
                # list from the shipped part files, so the vehicle keeps the
                # generic upgrades its baseline line had instead of silently
                # losing e.g. its nitro options.
                vehicle_parts = self.merge_generic_carmods_parts(target_model, vehicle_parts)
                if vehicle_parts:
                    mods_line = f"{target_model.lower()}, " + ", ".join(vehicle_parts)
                    changes["carmods_dat"]["actions"].append({
                        "type": "replace_or_insert_car_mods",
                        "car": target_model,
                        "line": mods_line,
                        "desc": f"Assign {len(vehicle_parts)} tuning parts to {target_model}"
                    })
                links = self.tuning_mgr.find_mirror_links(parts)
                existing_links = self.tuning_mgr.get_existing_link_pairs()
                for l, r in links:
                    if frozenset((l.lower(), r.lower())) in existing_links:
                        continue
                    changes["carmods_dat"]["actions"].append({
                        "type": "insert_link",
                        "line": f"{l}, {r}",
                        "desc": f"Register symmetrical mirror parts: {l} <-> {r}"
                    })
                _plan_shopping_for_parts(target_model, vehicle_parts)
                missing_mods = self.tuning_mgr.generate_missing_veh_mods_entries(
                    parts, target_model, custom_ids=allocated_tuning_ids,
                    part_configs=author_veh_mods, dff_map=dff_map
                )
                for item in missing_mods:
                    changes["veh_mods_ide"]["actions"].append({
                        "type": "append_veh_mod_id",
                        "id": item["id"],
                        "part": item["part_name"],
                        "line": item["line"],
                        "desc": f"Allocate new tuning part model ID: {item['id']} -> {item['part_name']}"
                    })

        # 2. Handling
        handling_parsed = parsed_mod["parsed"]["handling"]
        for h_info in handling_parsed:
            if h_info and h_info.get("identifier"):
                ident = h_info["identifier"].upper()
                pfx = h_info.get("prefix", "")
                full_ident = f"{pfx} {ident}".strip() if pfx else ident
                if pfx:
                    desc_text = f"Update dedicated handling dynamics ({full_ident})"
                else:
                    desc_text = f"Update handling physics ({ident}): top speed {h_info.get('max_speed_kmh', 'N/A')} km/h, mass {h_info.get('mass_kg', 'N/A')} kg, drive {h_info.get('drive_type_label', 'N/A')}"
                changes["handling_cfg"]["actions"].append({
                    "type": "replace_or_insert_handling",
                    "identifier": full_ident,
                    "line": h_info["raw"].strip(),
                    "desc": desc_text
                })

        # 3. Carcols
        carcols_parsed = parsed_mod["parsed"]["carcols"]
        for c_info in carcols_parsed:
            if c_info and c_info.get("model_name"):
                c_model = c_info["model_name"].lower()
                changes["carcols_dat"]["actions"].append({
                    "type": "replace_or_insert_carcols",
                    "model": c_model,
                    "line": c_info["raw"].strip(),
                    "is_car4": c_info.get("is_car4", False),
                    "desc": f"Update vehicle colors ({c_model}, {c_info.get('count', 0)} palette(s))"
                })

        # 4. vehicles.ide for ADDON models only. Replace packs keep the
        # vanilla IDE untouched (only DFF/TXD are swapped), so any line whose
        # model is a known vanilla model is deliberately skipped here.
        for ide_info in parsed_mod["parsed"].get("ide", []) or []:
            if ide_info and ide_info.get("model_name") and ide_info.get("id"):
                im = ide_info["model_name"].lower()
                if im not in MODEL_TO_ID:
                    changes["vehicles_ide"]["actions"].append({
                        "type": "replace_or_insert_vehicles_ide",
                        "model": im,
                        "line": ide_info["raw"].strip(),
                        "desc": f"Add vehicles.ide entry ({im}, ID {ide_info.get('id')})"
                    })

        # 5. Audio settings
        audio_lines = parsed_mod["parsed"].get("audio_lines", [])
        for aline in audio_lines:
            parts = aline.strip().split()
            if parts:
                a_model = parts[0].lower()
                changes["audio_settings"]["actions"].append({
                    "type": "update_audio",
                    "model": a_model,
                    "line": FLAManager.format_audio_line(a_model, aline),
                    "desc": f"Update FLA92 vehicle audio settings ({a_model})"
                })

        # 6. Special features
        spec_lines = parsed_mod["parsed"].get("special_features", [])
        for sline in spec_lines:
            parts = sline.strip().split()
            if len(parts) >= 2:
                changes["special_features"]["actions"].append({
                    "type": "set_special_feature",
                    "model": parts[0].lower(),
                    "target": parts[1].lower(),
                    "desc": f"Configure FLA92 special feature ({parts[0]}): mapped to {parts[1]}"
                })

        # Summarize total action count
        total_actions = sum(len(c["actions"]) for c in changes.values())

        return {
            "success": True,
            "target_model": target_model,
            "total_actions": total_actions,
            "changes": changes
        }

    def apply_merge(self, parsed_mod: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the planned merge onto actual shadow files and FLA files.
        Automatically takes backups before writing.
        All-or-nothing: when any target file fails to write, every file touched by
        this merge is restored from its snapshot, so a failed merge can never leave
        the game with a half-applied configuration.
        """
        plan = self.plan_merge(parsed_mod)
        if not plan["success"]:
            return plan

        applied = []
        errors = []
        shopping_notes = []

        # Every file this merge may touch. Files that do not exist yet must be
        # removed again on rollback, because a snapshot can only restore files
        # that already existed when it was taken.
        target_files = [c["file"] for c in plan["changes"].values() if c.get("file")]
        pre_existing = {f for f in target_files if os.path.exists(f)}

        target_model = parsed_mod.get("target_model") or "merge"
        snapshot_dir = None
        try:
            with self.backup_manager.snapshot(action_name=f"merge_{target_model}") as snapshot_dir:
                # 1. Apply carmods.dat
                carmods_actions = plan["changes"]["carmods_dat"]["actions"]
                if carmods_actions:
                    res = self._merge_carmods(carmods_actions)
                    if res["success"]:
                        applied.append("carmods.dat")
                    else:
                        errors.append(res["error"])

                # 2. Apply shopping.dat
                shop_actions = plan["changes"]["shopping_dat"]["actions"]
                if shop_actions:
                    res = self._merge_shopping(shop_actions)
                    if res["success"]:
                        applied.append("shopping.dat")
                    else:
                        errors.append(res["error"])
                    shopping_notes.extend(res.get("skipped_author_entries") or [])

                # 3. Apply veh_mods.ide
                ide_actions = plan["changes"]["veh_mods_ide"]["actions"]
                if ide_actions:
                    res = self._merge_veh_mods(ide_actions)
                    if res["success"]:
                        applied.append("veh_mods.ide")
                    else:
                        errors.append(res["error"])

                # 4. Apply handling.cfg
                h_actions = plan["changes"]["handling_cfg"]["actions"]
                if h_actions:
                    res = self._merge_handling(h_actions)
                    if res["success"]:
                        applied.append("handling.cfg")
                    else:
                        errors.append(res["error"])

                # 5. Apply carcols.dat
                c_actions = plan["changes"]["carcols_dat"]["actions"]
                if c_actions:
                    res = self._merge_carcols(c_actions)
                    if res["success"]:
                        applied.append("carcols.dat")
                    else:
                        errors.append(res["error"])

                # 5b. Apply vehicles.ide (addon models only, see plan_merge)
                ide_actions = plan["changes"]["vehicles_ide"]["actions"]
                if ide_actions:
                    res = self._merge_vehicles_ide([{"model": a.get("model"), "line": a.get("line")} for a in ide_actions])
                    if res["success"]:
                        applied.append("vehicles.ide")
                    else:
                        errors.append(res["error"])

                # 6. Apply FLA Audio & Special features. Batch audio rows so one
                # install creates one backup and inserts all rows before the trailer.
                audio_actions = plan["changes"]["audio_settings"]["actions"]
                if audio_actions:
                    audio_ok = self.fla_mgr.update_audio_settings(
                        [(a["model"], a["line"]) for a in audio_actions]
                    )
                    if audio_ok:
                        applied.append("gtasa_vehicleAudioSettings.cfg")
                    else:
                        errors.append("Failed to update gtasa_vehicleAudioSettings.cfg")

                for s in plan["changes"]["special_features"]["actions"]:
                    if self.fla_mgr.set_special_feature(s["model"], s["target"]):
                        applied.append("model_special_features.dat")
                    else:
                        errors.append(f"Failed to write model_special_features.dat: {s['model']}")
        except Exception as e:
            # A raised write error leaves the files just as half-applied as a
            # returned failure does, so it has to go through the rollback too.
            errors.append(f"Exception during merge: {e}")

        # A merge writes model/tuning IDs to disk, and a rollback rewrites the
        # files again; either way no cached IDE scan can be trusted afterwards.
        self._invalidate_id_cache()

        if errors:
            errors.extend(self._rollback_merge(snapshot_dir, pre_existing, target_files))
            return {
                "success": False,
                "applied_files": [],
                "rolled_back": True,
                "errors": errors,
                "shopping_notes": shopping_notes,
                "plan": plan
            }

        return {
            "success": True,
            "applied_files": list(set(applied)),
            "errors": errors,
            "shopping_notes": shopping_notes,
            "plan": plan
        }

    def _invalidate_id_cache(self):
        """Tell every IdManager that the IDE data on disk has changed."""
        id_mgr = self.tuning_mgr.id_mgr
        if id_mgr:
            id_mgr.invalidate_shared_cache(self.game_path)

    def _rollback_merge(
        self,
        snapshot_dir: Optional[str],
        pre_existing: Set[str],
        target_files: List[str]
    ) -> List[str]:
        """
        Undo a partially applied merge: restore every file captured in the
        snapshot, then delete target files the merge created from scratch.
        Returns rollback problems (empty when the rollback was clean).
        """
        rollback_errors: List[str] = []

        if snapshot_dir and os.path.isdir(snapshot_dir):
            try:
                res = self.backup_manager.restore_snapshot(os.path.basename(snapshot_dir))
            except Exception as e:
                res = {"success": False, "errors": [str(e)]}
            if not res.get("success"):
                problems = res.get("errors") or [res.get("error") or "Unknown error"]
                rollback_errors.extend(f"Rollback failed: {p}" for p in problems)

        for path in target_files:
            if path in pre_existing:
                continue
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                rollback_errors.append(f"Failed to rollback new file {path}: {e}")

        return rollback_errors

    # ---------------- File Specific Delta Mergers ----------------

    def _backup(self, path: str):
        if os.path.exists(path):
            self.backup_manager.backup_file(path)

    def _merge_carmods(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        path = os.path.join(self.shadow_dir, "carmods.dat")
        if not os.path.exists(path):
            if not self._ensure_shadow_file("carmods.dat"):
                return {"success": False, "error": f"Cannot find {path} and unable to create shadow copy from vanilla data"}

        self._backup(path)
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        in_mods = False
        in_link = False
        cars_to_replace = {}
        new_links = []

        for a in actions:
            if a["type"] == "replace_or_insert_car_mods":
                c = a["car"].lower()
                l = a["line"].strip()
                toks = [t.strip() for t in l.split(",") if t.strip()]
                if len(toks) > 1:
                    toks = [toks[0]] + [t for t in toks[1:] if not self.tuning_mgr.is_mirror_counterpart(t)]
                    l = ", ".join(toks)
                cars_to_replace[c] = l + "\n"
            elif a["type"] == "insert_link":
                new_links.append(a["line"].strip() + "\n")

        # Keep mirror links idempotent: never append a pair that already exists
        # in this file (repeated installs / inspector saves must not duplicate).
        if new_links:
            existing_pairs = set()
            _scan_link = False
            for line in lines:
                s = line.strip().lower()
                if s == "link":
                    _scan_link = True
                    continue
                if _scan_link and s == "end":
                    break
                if _scan_link and s and not s.startswith("#") and not s.startswith(";"):
                    parts = [p.strip() for p in s.split(",") if p.strip()]
                    if len(parts) >= 2:
                        existing_pairs.add(frozenset((parts[0], parts[1])))
            _filtered_links = []
            for nl in new_links:
                parts = [p.strip().lower() for p in nl.split(",") if p.strip()]
                if len(parts) == 2 and frozenset(parts) in existing_pairs:
                    continue
                _filtered_links.append(nl)
                if len(parts) == 2:
                    existing_pairs.add(frozenset(parts))
            new_links = _filtered_links

        handled_cars = set()

        for line in lines:
            stripped = line.strip()
            if stripped.lower() == "link":
                in_link = True
                new_lines.append(line)
                continue
            if stripped.lower() == "mods":
                in_mods = True
                new_lines.append(line)
                continue
            if stripped.lower() == "end":
                if in_link and new_links:
                    for nl in new_links:
                        new_lines.append(nl)
                    new_links = []
                if in_mods and cars_to_replace:
                    for car, car_l in cars_to_replace.items():
                        if car not in handled_cars:
                            new_lines.append(car_l)
                            handled_cars.add(car)
                in_link = False
                in_mods = False
                new_lines.append(line)
                continue

            if in_mods and cars_to_replace:
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if parts and parts[0].lower() in cars_to_replace:
                    car_k = parts[0].lower()
                    new_lines.append(cars_to_replace[car_k])
                    handled_cars.add(car_k)
                    continue

            new_lines.append(line)

        write_text_atomic(path, new_lines)
        return {"success": True}

    def _merge_shopping(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        path = os.path.join(self.shadow_dir, "shopping.dat")
        if not os.path.exists(path):
            if not self._ensure_shadow_file("shopping.dat"):
                return {"success": False, "error": f"Cannot find {path} and unable to create shadow copy from vanilla data"}

        self._backup(path)
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        # Group actions by destination section
        carmods_actions = []
        workshop_actions = {}

        for a in actions:
            a_type = a.get("type")
            if a_type in ("append_carmods_entry", "append_shopping_entry"):
                carmods_actions.append(a)
            elif a_type == "append_workshop_item":
                w = (a.get("workshop") or "carmod3").lower()
                workshop_actions.setdefault(w, []).append(a)

        # 1. Parse existing parts in section CarMods to prevent duplicates
        existing_carmods_parts = set()
        in_carmods_scan = False
        for line in lines:
            s = line.strip()
            if re.search(r'(?i)^\s*section\s+CarMods\b', s):
                in_carmods_scan = True
                continue
            if in_carmods_scan:
                if s.lower() == "end":
                    in_carmods_scan = False
                    continue
                clean = s.split('#')[0].split(';')[0].split('//')[0].strip()
                if clean:
                    toks = clean.split()
                    if toks:
                        existing_carmods_parts.add(toks[0].lower())

        filtered_carmods_actions = []
        skipped_author_entries = []
        seen_cm = set()
        for a in carmods_actions:
            p = (a.get("part") or "").lower()
            if not p or p in seen_cm:
                continue
            if p in existing_carmods_parts:
                # The part already has a price entry (vanilla or another mod).
                # Rewriting that shared line is riskier than the rare override
                # is worth, so the existing values stay - but the caller gets
                # told instead of the declaration vanishing silently.
                if a.get("author"):
                    skipped_author_entries.append(a)
                continue
            seen_cm.add(p)
            filtered_carmods_actions.append(a)

        # 2. Parse existing items in each workshop section
        existing_workshop_items = {}
        in_w_scan = False
        current_w_scan = None
        for line in lines:
            s = line.strip()
            m_sec = re.search(r'(?i)^\s*section\s+(carmod[1-3])\b', s)
            if m_sec:
                in_w_scan = True
                current_w_scan = m_sec.group(1).lower()
                existing_workshop_items.setdefault(current_w_scan, set())
                continue
            if in_w_scan:
                if s.lower() == "end":
                    in_w_scan = False
                    current_w_scan = None
                    continue
                clean = s.split('#')[0].split(';')[0].split('//')[0].strip()
                toks = clean.split()
                if len(toks) >= 2 and toks[0].lower() == "item":
                    existing_workshop_items[current_w_scan].add(toks[1].lower())

        filtered_workshop_actions = {}
        for w, w_acts in workshop_actions.items():
            ext = existing_workshop_items.get(w, set())
            seen_w = set()
            for a in w_acts:
                p = (a.get("part") or "").lower()
                if p and p not in ext and p not in seen_w:
                    seen_w.add(p)
                    filtered_workshop_actions.setdefault(w, []).append(a)

        # 3. Build new lines by inserting before each section's 'end'
        new_lines = []
        in_carmods = False
        carmods_inserted = False

        in_workshop = False
        current_workshop = None
        inserted_workshops = set()

        for line in lines:
            s = line.strip()

            # Check section CarMods start
            if re.search(r'(?i)^\s*section\s+CarMods\b', s):
                in_carmods = True
                new_lines.append(line)
                continue

            # Check section CarMods end
            if in_carmods and s.lower() == "end":
                if not carmods_inserted and filtered_carmods_actions:
                    for a in filtered_carmods_actions:
                        l = a["line"].rstrip()
                        if not l.startswith("\t"):
                            l = "\t\t" + l
                        new_lines.append(l + "\n")
                    carmods_inserted = True
                in_carmods = False
                new_lines.append(line)
                continue

            # Check workshop section start (carmod1, carmod2, carmod3)
            m_w = re.search(r'(?i)^\s*section\s+(carmod[1-3])\b', s)
            if m_w:
                in_workshop = True
                current_workshop = m_w.group(1).lower()
                new_lines.append(line)
                continue

            # Check workshop section end
            if in_workshop and s.lower() == "end":
                if current_workshop in filtered_workshop_actions and current_workshop not in inserted_workshops:
                    for a in filtered_workshop_actions[current_workshop]:
                        l = a["line"].rstrip()
                        if not l.startswith("\t"):
                            l = "\t\t" + l
                        new_lines.append(l + "\n")
                    inserted_workshops.add(current_workshop)
                in_workshop = False
                current_workshop = None
                new_lines.append(line)
                continue

            new_lines.append(line)

        # 4. If any workshop section didn't exist in file, create it before the last 'end'
        remaining_workshops = set(filtered_workshop_actions.keys()) - inserted_workshops
        if remaining_workshops:
            last_end_idx = -1
            for idx in range(len(new_lines) - 1, -1, -1):
                if new_lines[idx].strip().lower() == "end":
                    last_end_idx = idx
                    break

            extra_lines = []
            for w in sorted(remaining_workshops):
                extra_lines.append(f"\n\tsection {w}\n\ttype CarMods\n")
                for a in filtered_workshop_actions[w]:
                    l = a["line"].rstrip()
                    if not l.startswith("\t"):
                        l = "\t\t" + l
                    extra_lines.append(l + "\n")
                extra_lines.append("\tend\n")

            if last_end_idx != -1:
                new_lines = new_lines[:last_end_idx] + extra_lines + new_lines[last_end_idx:]
            else:
                new_lines.extend(extra_lines)

        write_text_atomic(path, new_lines)
        return {"success": True, "skipped_author_entries": skipped_author_entries}

    def _merge_veh_mods(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        path = os.path.join(self.shadow_dir, "veh_mods.ide")
        if not os.path.exists(path):
            if not self._ensure_shadow_file("veh_mods.ide"):
                return {"success": False, "error": f"Cannot find {path} and unable to create shadow copy from vanilla data"}

        self._backup(path)
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        # Parse existing model names and IDs in the file to prevent duplicates
        existing_models = set()
        existing_ids = set()
        for line in lines:
            s = line.strip()
            if s and not s.startswith("#") and s.lower() not in ("objs", "end"):
                parts = [p.strip() for p in s.split(",") if p.strip()]
                if len(parts) >= 2:
                    existing_models.add(parts[1].lower())
                    if parts[0].isdigit():
                        existing_ids.add(int(parts[0]))

        new_lines = []
        in_objs = False
        inserted = False

        for line in lines:
            stripped = line.strip()
            if stripped.lower() == "objs":
                in_objs = True
                new_lines.append(line)
                continue
            if in_objs and stripped.lower() == "end" and not inserted:
                for a in actions:
                    part_name = str(a.get("part", "")).lower()
                    part_id = a.get("id")
                    if part_name and part_name in existing_models:
                        continue
                    if part_id is not None and part_id in existing_ids:
                        continue
                    line_str = a["line"]
                    tokens = [p.strip() for p in line_str.split(",") if p.strip()]
                    if len(tokens) >= 5:
                        p_name = tokens[1].lower()
                        cur_flags = int(tokens[4]) if tokens[4].isdigit() else 2097152
                        corr_flags = determine_veh_mod_flags(p_name, cur_flags)
                        if corr_flags != cur_flags:
                            tokens[4] = str(corr_flags)
                            line_str = ", ".join(tokens)
                    new_lines.append(line_str + "\n")
                    if part_name:
                        existing_models.add(part_name)
                    if part_id is not None:
                        existing_ids.add(part_id)
                inserted = True
                in_objs = False

            new_lines.append(line)

        write_text_atomic(path, new_lines)
        return {"success": True}

    def _merge_handling(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        path = os.path.join(self.shadow_dir, "handling.cfg")
        if not os.path.exists(path):
            if not self._ensure_shadow_file("handling.cfg"):
                return {"success": False, "error": f"Cannot find {path} and unable to create shadow copy from vanilla data"}

        self._backup(path)
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        main_actions = {}
        prefix_actions = {}

        for a in actions:
            raw_id = (a.get("identifier") or "").strip()
            raw_line = (a.get("line") or "").strip()
            if not raw_line and not raw_id:
                continue
            # Check if this action specifies a prefixed secondary physics line (!, $, %, ^)
            pfx = ""
            ident = ""
            if raw_id and raw_id[0] in ("!", "$", "%", "^"):
                pfx = raw_id[0]
                ident = raw_id[1:].strip().upper()
            elif raw_line and raw_line[0] in ("!", "$", "%", "^"):
                pfx = raw_line[0]
                rest = raw_line[1:].strip()
                ident = rest.split()[0].upper() if rest else ""
            else:
                pfx = ""
                ident = raw_id.upper() if raw_id else (raw_line.split()[0].upper() if raw_line else "")

            if ident:
                line_to_write = raw_line + "\n"
                if pfx:
                    prefix_actions[(pfx, ident)] = line_to_write
                else:
                    main_actions[ident] = line_to_write

        handled_main = set()
        handled_prefix = set()
        new_lines = []

        for line in lines:
            line_s = line.strip()
            if not line_s or line_s.startswith(";") or line_s.startswith("#") or line_s.startswith("//"):
                new_lines.append(line)
                continue
            parts = line.split()
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
                    key = (line_pfx, line_ident)
                    if key in prefix_actions:
                        new_lines.append(prefix_actions[key])
                        handled_prefix.add(key)
                        continue
                else:
                    if line_ident in main_actions:
                        new_lines.append(main_actions[line_ident])
                        handled_main.add(line_ident)
                        continue

            new_lines.append(line)

        for ident, line_to_write in main_actions.items():
            if ident not in handled_main:
                new_lines.append(line_to_write)

        for key, line_to_write in prefix_actions.items():
            if key not in handled_prefix:
                new_lines.append(line_to_write)

        write_text_atomic(path, new_lines)
        return {"success": True}

    def _merge_carcols(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        path = os.path.join(self.shadow_dir, "carcols.dat")
        if not os.path.exists(path):
            if not self._ensure_shadow_file("carcols.dat"):
                return {"success": False, "error": f"Cannot find {path} and unable to create shadow copy from vanilla data"}

        self._backup(path)
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        action_map = {}
        for a in actions:
            if a.get("model"):
                m = a["model"].lower()
                clean_l = a["line"].strip()
                is_car4 = bool(a.get("is_car4"))
                if clean_l.lower().startswith("car4"):
                    is_car4 = True
                    clean_l = clean_l[4:].strip().lstrip(",").strip()
                # strip inline comments if any
                for c_marker in ("#", ";", "//"):
                    if c_marker in clean_l:
                        clean_l = clean_l.split(c_marker)[0].strip()
                action_map[m] = {
                    "line": clean_l + "\n",
                    "is_car4": is_car4
                }

        # First pass: check which models already exist in 'car' vs 'car4',
        # and collect any existing rogue vehicle lines stranded after car4's end.
        existing_in_car = set()
        existing_in_car4 = set()
        has_car4_section = False
        rogue_vehicle_lines = []
        cur_sec = None

        for line in lines:
            stripped = line.strip()
            low = stripped.lower()
            if low in ("col", "car", "car4"):
                cur_sec = low
                if low == "car4":
                    has_car4_section = True
                continue
            if low == "end":
                cur_sec = None
                continue
            if cur_sec in ("car", "car4") and stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if parts:
                    m = parts[0].lower()
                    if cur_sec == "car":
                        existing_in_car.add(m)
                    elif cur_sec == "car4":
                        existing_in_car4.add(m)
            elif cur_sec is None and stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if len(parts) >= 2 and all(p.isdigit() for p in parts[1:]):
                    m = parts[0].lower()
                    if m not in action_map:
                        rogue_vehicle_lines.append((m, line if line.endswith("\n") else line + "\n"))

        # Determine target section for each action
        for m, info in action_map.items():
            if info["is_car4"]:
                info["target_sec"] = "car4"
            elif m in existing_in_car4:
                info["target_sec"] = "car4"
            else:
                info["target_sec"] = "car"

        # Migrate any rogue vehicle lines to the 'car' section so they are no longer stranded after end
        for rm, rl in rogue_vehicle_lines:
            if rm not in existing_in_car and rm not in existing_in_car4 and rm not in action_map:
                action_map[rm] = {
                    "line": rl,
                    "is_car4": False,
                    "target_sec": "car"
                }

        handled_models = set()
        new_lines = []
        cur_sec = None

        for line in lines:
            stripped = line.strip()
            low = stripped.lower()

            if low in ("col", "car", "car4"):
                cur_sec = low
                new_lines.append(line)
                continue

            if low == "end":
                # Before closing "car", insert all remaining 2-color entries
                if cur_sec == "car":
                    for m, info in action_map.items():
                        if info["target_sec"] == "car" and m not in handled_models:
                            new_lines.append(info["line"])
                            handled_models.add(m)
                # Before closing "car4", insert all remaining 4-color entries
                elif cur_sec == "car4":
                    for m, info in action_map.items():
                        if info["target_sec"] == "car4" and m not in handled_models:
                            new_lines.append(info["line"])
                            handled_models.add(m)
                cur_sec = None
                new_lines.append(line)
                continue

            if cur_sec in ("car", "car4"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if parts and parts[0].lower() in action_map:
                    m = parts[0].lower()
                    if action_map[m]["target_sec"] == cur_sec:
                        new_lines.append(action_map[m]["line"])
                        handled_models.add(m)
                        continue
                    else:
                        # Model is targeted to a different section; omit from here
                        continue

            # Strip any rogue vehicle data lines from after 'end'
            if cur_sec is None and stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if len(parts) >= 2 and all(p.isdigit() for p in parts[1:]):
                    continue

            new_lines.append(line)

        # If there are unhandled car4 entries and no car4 section was encountered
        remaining_car4 = [info["line"] for m, info in action_map.items() if info["target_sec"] == "car4" and m not in handled_models]
        if remaining_car4:
            new_lines.append("\ncar4\n")
            for r_line in remaining_car4:
                new_lines.append(r_line)
            new_lines.append("end\n")

        write_text_atomic(path, new_lines)
        return {"success": True}

    def _ensure_shadow_file(self, filename: str) -> bool:
        """Ensure a target configuration file exists in shadow_dir. If missing, copy from vanilla data/."""
        target = os.path.join(self.shadow_dir, filename)
        if os.path.exists(target):
            return True
        if not self.game_path or not os.path.isdir(self.game_path):
            return False

        vanilla_src = os.path.join(self.game_path, "data", filename)
        if filename == "veh_mods.ide" and not os.path.exists(vanilla_src):
            vanilla_src = os.path.join(self.game_path, "data", "maps", "veh_mods", "veh_mods.ide")

        if os.path.exists(vanilla_src):
            try:
                os.makedirs(self.shadow_dir, exist_ok=True)
                shutil.copy2(vanilla_src, target)
                return True
            except Exception as e:
                print(f"Error copying baseline {filename}: {e}")
                return False

        # Fallback to standard empty skeleton if vanilla source is missing (e.g. test environment)
        DEFAULT_SKELETONS = {
            "carmods.dat": "mods\nend\nlink\nend\n",
            "shopping.dat": "section prices\nsection CarMods\nend\nend\n",
            "handling.cfg": "; handling.cfg\n",
            "carcols.dat": "col\nend\ncar\nend\n",
            "vehicles.ide": "cars\nend\n",
            "veh_mods.ide": "objs\nend\n",
        }
        if filename in DEFAULT_SKELETONS:
            try:
                os.makedirs(self.shadow_dir, exist_ok=True)
                write_text_atomic(target, DEFAULT_SKELETONS[filename])
                return True
            except Exception as e:
                print(f"Error creating default skeleton for {filename}: {e}")
                return False
        return False

    def _merge_vehicles_ide(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update or insert vehicles.ide lines inside cars ... end section."""
        path = os.path.join(self.shadow_dir, "vehicles.ide")
        if not os.path.exists(path):
            if not self._ensure_shadow_file("vehicles.ide"):
                return {"success": False, "error": f"Cannot find {path} and unable to create shadow copy from vanilla data"}

        self._backup(path)
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        action_map = {}
        for a in actions:
            clean_l = a["line"].strip()
            for c_marker in ("#", ";", "//"):
                if c_marker in clean_l:
                    clean_l = clean_l.split(c_marker)[0].strip()
            parts = [p.strip() for p in clean_l.split(",") if p.strip()]
            if len(parts) >= 2:
                model_name = parts[1].lower()
                action_map[model_name] = clean_l + "\n"
            elif a.get("model"):
                action_map[a["model"].lower()] = clean_l + "\n"

        # A model in a later cars block is an update, not a new entry to
        # insert at the first end. Locate existing models across all blocks.
        existing_models = set()
        in_cars = False
        for line in lines:
            stripped = normalize_ide_line(line.strip())
            if stripped.lower() == "cars":
                in_cars = True
            elif stripped.lower() == "end":
                in_cars = False
            elif in_cars and stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if len(parts) >= 2:
                    existing_models.add(parts[1].lower())

        handled_models = set()
        new_lines = []
        in_cars = False

        for line in lines:
            stripped = line.strip()
            if stripped.lower() == "cars":
                in_cars = True
                new_lines.append(line)
                continue
            if in_cars and stripped.lower() == "end":
                for m, line_to_write in action_map.items():
                    if m not in existing_models and m not in handled_models:
                        new_lines.append(line_to_write)
                        handled_models.add(m)
                in_cars = False
                new_lines.append(line)
                continue

            if in_cars and stripped and not stripped.startswith("#"):
                parts = [p.strip() for p in normalize_ide_line(stripped).split(",") if p.strip()]
                if len(parts) >= 2 and parts[1].lower() in action_map:
                    m = parts[1].lower()
                    # Keep the first occurrence and remove duplicates only
                    # for models explicitly updated by this operation.
                    if m not in handled_models:
                        new_lines.append(action_map[m])
                        handled_models.add(m)
                    continue

            new_lines.append(line)

        unhandled = [line_to_write for m, line_to_write in action_map.items() if m not in handled_models]
        if unhandled:
            new_lines.append("\ncars\n")
            for line_to_write in unhandled:
                new_lines.append(line_to_write)
            new_lines.append("end\n")

        write_text_atomic(path, new_lines)
        return {"success": True}

    def _find_model_line_in_ide(self, shadow_path: str, vanilla_path: str, model: str):
        for fpath, src in [(shadow_path, "shadow"), (vanilla_path, "vanilla")]:
            if fpath and os.path.exists(fpath):
                try:
                    in_cars = False
                    with open(fpath, "r", encoding="utf-8-sig", errors="ignore") as f:
                        for line in f:
                            s = normalize_ide_line(line.strip())
                            if s.lower() == "cars":
                                in_cars = True
                                continue
                            if in_cars and s.lower() == "end":
                                # A file may hold several cars blocks (the merge
                                # appends one when a model cannot be placed), so
                                # keep scanning instead of stopping here.
                                in_cars = False
                                continue
                            if in_cars and s and not s.startswith("#"):
                                parts = [p.strip() for p in s.split(",") if p.strip()]
                                if len(parts) >= 2 and parts[1].lower() == model:
                                    return s, src
                except Exception:
                    pass
        return None, None

    def _find_handling_line(self, shadow_path: str, vanilla_path: str, handling_id: str):
        hid_upper = handling_id.upper()
        for fpath, src in [(shadow_path, "shadow"), (vanilla_path, "vanilla")]:
            if fpath and os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8-sig", errors="ignore") as f:
                        for line in f:
                            s = line.strip()
                            if not s or s.startswith(";") or s.startswith("#") or s.startswith("//"):
                                continue
                            clean = s.split(';')[0].split('//')[0].strip()
                            if clean and clean[0] in ("!", "$", "%", "^"):
                                continue
                            parts = clean.split()
                            if parts and parts[0].upper() == hid_upper:
                                return s, src
                except Exception:
                    pass
        return None, None

    def _find_model_line_in_carcols(self, shadow_path: str, vanilla_path: str, model: str):
        """Find a vehicle's carcols line, keeping the section it lives in.

        carcols.dat is laid out as "car ... end" followed by "car4 ... end", so
        the scan has to continue past the first section end: stopping there hid
        every 4-color vehicle from the inspector and the card editors. Lines
        from the car4 section are returned with the "car4 " marker the parser
        expects, so they keep being read as 4-color sets downstream.
        """
        for fpath, src in [(shadow_path, "shadow"), (vanilla_path, "vanilla")]:
            if fpath and os.path.exists(fpath):
                try:
                    section = None
                    with open(fpath, "r", encoding="utf-8-sig", errors="ignore") as f:
                        for line in f:
                            s = line.strip()
                            low = s.lower()
                            if low in ("car", "car4"):
                                section = low
                                continue
                            if low == "end":
                                section = None
                                continue
                            if section and s and not s.startswith("#"):
                                parts = [p.strip() for p in s.split(",") if p.strip()]
                                if parts and parts[0].lower() == model:
                                    if section == "car4" and not low.startswith("car4"):
                                        return f"car4 {s}", src
                                    return s, src
                except Exception:
                    pass
        return None, None

    def _find_model_line_in_carmods(self, shadow_path: str, vanilla_path: str, model: str):
        for fpath, src in [(shadow_path, "shadow"), (vanilla_path, "vanilla")]:
            if fpath and os.path.exists(fpath):
                try:
                    in_mods = False
                    with open(fpath, "r", encoding="utf-8-sig", errors="ignore") as f:
                        for line in f:
                            s = line.strip()
                            if s.lower() == "mods":
                                in_mods = True
                                continue
                            if in_mods and s.lower() == "end":
                                break
                            if in_mods and s and not s.startswith("#"):
                                parts = [p.strip() for p in s.split(",") if p.strip()]
                                if parts and parts[0].lower() == model:
                                    return s, src
                except Exception:
                    pass
        return None, None

    def get_original_generic_carmods_parts(self, model: str) -> Dict[str, List[str]]:
        """
        Reads baseline/active carmods.dat for model (shadow first, vanilla fallback).
        Strictly matches and returns specific generic upgrade categories that the vehicle originally had:
        - nitro: e.g. ['nto_b_l', 'nto_b_s', 'nto_b_tw'] or ['nto_b_s']
        - hydraulics: e.g. ['hydralics']
        - stereo: e.g. ['stereo']
        Only returns parts that were explicitly present in the vehicle's original carmods line.
        Used when the package ships no carmods.dat list and the tool generates a fallback one.
        """
        model_clean = (model or "").strip().lower()
        res = {"nitro": [], "hydraulics": [], "stereo": []}
        if not model_clean:
            return res

        shadow_m = os.path.join(self.shadow_dir, "carmods.dat")
        vanilla_m = os.path.join(self.game_path, "data", "carmods.dat") if self.game_path else ""
        m_line, _ = self._find_model_line_in_carmods(shadow_m, vanilla_m, model_clean)
        if not m_line:
            return res

        clean = m_line.split("#")[0].split(";")[0].split("//")[0].strip()
        parts = [p.strip().lower() for p in clean.split(",") if p.strip()]
        if len(parts) <= 1:
            return res

        for p in parts[1:]:
            if p.startswith("nto_"):
                if p not in res["nitro"]:
                    res["nitro"].append(p)
            elif p in ("hydralics", "hydraulics"):
                if p not in res["hydraulics"]:
                    res["hydraulics"].append(p)
            elif p in ("stereo", "bass", "bassboost"):
                if p not in res["stereo"]:
                    res["stereo"].append(p)

        return res

    def merge_generic_carmods_parts(self, model: str, current_parts: List[str]) -> List[str]:
        """
        Strictly preserves original vehicle's generic parts (nitro, hydraulics, stereo)
        if the vehicle originally had them and current parts list does not already contain that category.
        Only used for generated fallback lists - a list the package declared is
        deployed verbatim, so an author who drops e.g. nitro is followed.
        """
        orig = self.get_original_generic_carmods_parts(model)
        merged = list(current_parts)

        # 1. Nitro: only add if current parts has NO nitro, and original vehicle had nitro
        has_nitro = any(p.lower().startswith("nto_") for p in merged)
        if not has_nitro and orig["nitro"]:
            for np in orig["nitro"]:
                if np not in merged:
                    merged.append(np)

        # 2. Hydraulics: only add if current parts has NO hydraulics, and original vehicle had hydraulics
        has_hydraulics = any(p.lower() in ("hydralics", "hydraulics") for p in merged)
        if not has_hydraulics and orig["hydraulics"]:
            for hp in orig["hydraulics"]:
                if hp not in merged:
                    merged.append(hp)

        # 3. Stereo: only add if current parts has NO stereo, and original vehicle had stereo
        has_stereo = any(p.lower() in ("stereo", "bass", "bassboost") for p in merged)
        if not has_stereo and orig["stereo"]:
            for sp in orig["stereo"]:
                if sp not in merged:
                    merged.append(sp)

        return merged

    def _resolve_source(self, line, src, vanilla_path, finder, key):
        """A shadow copy is usually a full baseline copy, so a matching line is
        often byte-identical to vanilla. Report those as 'vanilla' (baseline)
        instead of falsely advertising the vehicle as shadow-customised, which
        would hide the mod's own preset in the inspector."""
        if not line or src != "shadow" or not vanilla_path or not os.path.exists(vanilla_path):
            return src
        try:
            v_line, _ = finder("", vanilla_path, key)
        except Exception:
            v_line = None
        if v_line and _norm_config_line(v_line) == _norm_config_line(line):
            return "vanilla"
        return src

    def get_vehicle_active_configs(self, model: str) -> Dict[str, Any]:
        """
        Retrieve live configurations (vehicles.ide, handling.cfg, carcols.dat, carmods.dat)
        for a specific model, checking shadow copies first, then vanilla baselines.
        """
        model_clean = (model or "").strip().lower()
        res = {
            "model": model_clean,
            "vehicles_ide": None,
            "handling": None,
            "vanilla_handling": None,
            "carcols": None,
            "carmods": None
        }
        if not model_clean:
            return res

        # 1. vehicles.ide
        shadow_ide = os.path.join(self.shadow_dir, "vehicles.ide")
        vanilla_ide = os.path.join(self.game_path, "data", "vehicles.ide") if self.game_path else ""
        ide_line, ide_src = self._find_model_line_in_ide(shadow_ide, vanilla_ide, model_clean)
        ide_src = self._resolve_source(ide_line, ide_src, vanilla_ide, self._find_model_line_in_ide, model_clean)
        if ide_line:
            res["vehicles_ide"] = {
                "raw": ide_line,
                "source": ide_src,
                "decomposed": self.parser.decompose_ide(ide_line)
            }

        # Handling ID resolution
        handling_id = model_clean.upper()
        if res["vehicles_ide"] and res["vehicles_ide"]["decomposed"]:
            hid = res["vehicles_ide"]["decomposed"].get("handling_id")
            if hid:
                handling_id = hid.upper()

        # 2. handling.cfg
        shadow_h = os.path.join(self.shadow_dir, "handling.cfg")
        vanilla_h = os.path.join(self.game_path, "data", "handling.cfg") if self.game_path else ""
        h_line, h_src = self._find_handling_line(shadow_h, vanilla_h, handling_id)
        h_src = self._resolve_source(h_line, h_src, vanilla_h, self._find_handling_line, handling_id)
        if h_line:
            res["handling"] = {
                "raw": h_line,
                "source": h_src,
                "decomposed": self.parser.decompose_handling(h_line)
            }

        # Vanilla baseline handling for comparison (from pure data/handling.cfg)
        if vanilla_h and os.path.exists(vanilla_h):
            v_hid = handling_id
            if vanilla_ide and os.path.exists(vanilla_ide):
                v_ide_line, _ = self._find_model_line_in_ide("", vanilla_ide, model_clean)
                if v_ide_line:
                    v_decomp = self.parser.decompose_ide(v_ide_line)
                    if v_decomp and v_decomp.get("handling_id"):
                        v_hid = v_decomp["handling_id"].upper()
            vh_line, _ = self._find_handling_line("", vanilla_h, v_hid)
            if not vh_line and v_hid != model_clean.upper():
                vh_line, _ = self._find_handling_line("", vanilla_h, model_clean.upper())
            if vh_line:
                res["vanilla_handling"] = {
                    "raw": vh_line,
                    "source": "vanilla",
                    "decomposed": self.parser.decompose_handling(vh_line)
                }

        # 3. carcols.dat
        shadow_c = os.path.join(self.shadow_dir, "carcols.dat")
        vanilla_c = os.path.join(self.game_path, "data", "carcols.dat") if self.game_path else ""
        c_line, c_src = self._find_model_line_in_carcols(shadow_c, vanilla_c, model_clean)
        c_src = self._resolve_source(c_line, c_src, vanilla_c, self._find_model_line_in_carcols, model_clean)
        if c_line:
            res["carcols"] = {
                "raw": c_line,
                "source": c_src,
                "decomposed": self.parser.decompose_carcols(c_line)
            }

        # 4. carmods.dat
        shadow_m = os.path.join(self.shadow_dir, "carmods.dat")
        vanilla_m = os.path.join(self.game_path, "data", "carmods.dat") if self.game_path else ""
        m_line, m_src = self._find_model_line_in_carmods(shadow_m, vanilla_m, model_clean)
        m_src = self._resolve_source(m_line, m_src, vanilla_m, self._find_model_line_in_carmods, model_clean)
        if m_line:
            carmods_decomp = self.parser.decompose_carmods(m_line)
            if carmods_decomp and carmods_decomp.get("parts"):
                mod_details = self.tuning_mgr.get_all_veh_mods_details()
                for p in carmods_decomp["parts"]:
                    pname = p.get("part_name", "").lower()
                    if pname in mod_details:
                        p["model_id"] = mod_details[pname]["id"]
                        p["txd_name"] = mod_details[pname]["txd_name"]
                        p["draw_dist"] = mod_details[pname]["draw_dist"]
                        p["flags"] = mod_details[pname]["flags"]
                        p["ide_source"] = mod_details[pname]["source"]
                    else:
                        p["model_id"] = None
                        p["txd_name"] = ""
                        p["draw_dist"] = 100.0
                        p["flags"] = determine_veh_mod_flags(pname, 2097152)
                        p["ide_source"] = "none"

            res["carmods"] = {
                "raw": m_line,
                "source": m_src,
                "decomposed": carmods_decomp
            }

        return res

    def save_vehicle_config(self, model: str, config_type: str, raw_line: str) -> Dict[str, Any]:
        """
        Safely update an individual configuration line (handling, carcols, carmods, vehicles_ide)
        in the shadow files, ensuring backups and returning decomposed data.
        """
        model_clean = (model or "").strip().lower()
        raw_clean = (raw_line or "").strip()
        if not model_clean:
            return {"success": False, "error": "Missing target model parameter"}
        if not raw_clean:
            return {"success": False, "error": "Configuration entry content cannot be empty"}

        cfg_type = config_type.strip().lower()

        if cfg_type == "handling":
            self._ensure_shadow_file("handling.cfg")
            decomposed = self.parser.decompose_handling(raw_clean)
            if not decomposed or not decomposed.get("valid"):
                return {"success": False, "error": "Invalid handling line format; please check parameter count and drive/engine type"}
            ident = decomposed.get("identifier", model_clean.upper())
            res = self._merge_handling([{"identifier": ident, "line": raw_clean}])
            if not res.get("success"):
                return res
            return {
                "success": True,
                "type": "handling",
                "model": model_clean,
                "raw": raw_clean,
                "decomposed": decomposed,
                "file": "handling.cfg"
            }

        elif cfg_type == "carcols":
            self._ensure_shadow_file("carcols.dat")
            decomposed = self.parser.decompose_carcols(raw_clean)
            if not decomposed:
                return {"success": False, "error": "Invalid carcols format; expected: model, color1, color2, ..."}
            # Keep a 4-color entry in the car4 section instead of downgrading it
            # to a 2-color "car" line.
            res = self._merge_carcols([{
                "model": model_clean,
                "line": raw_clean,
                "is_car4": bool(decomposed.get("is_car4")),
            }])
            if not res.get("success"):
                return res
            return {
                "success": True,
                "type": "carcols",
                "model": model_clean,
                "raw": raw_clean,
                "decomposed": decomposed,
                "file": "carcols.dat"
            }

        elif cfg_type == "carmods":
            self._ensure_shadow_file("carmods.dat")
            decomposed = self.parser.decompose_carmods(raw_clean)
            if not decomposed:
                return {"success": False, "error": "Invalid carmods format; expected: model, part1, part2, ..."}
            res = self._merge_carmods([{"type": "replace_or_insert_car_mods", "car": model_clean, "line": raw_clean}])
            if not res.get("success"):
                return res
            # Check mirror links if applicable
            part_names = decomposed.get("part_names", [])
            if part_names:
                links = self.tuning_mgr.find_mirror_links(part_names)
                if links:
                    link_actions = [{"type": "insert_link", "line": f"{l[0]}, {l[1]}"} for l in links]
                    self._merge_carmods(link_actions)
            return {
                "success": True,
                "type": "carmods",
                "model": model_clean,
                "raw": raw_clean,
                "decomposed": decomposed,
                "file": "carmods.dat"
            }

        elif cfg_type in ("vehicles_ide", "ide"):
            self._ensure_shadow_file("vehicles.ide")
            decomposed = self.parser.decompose_ide(raw_clean)
            if not decomposed:
                return {"success": False, "error": "Invalid vehicles.ide format; please check parameter count and structure"}
            res = self._merge_vehicles_ide([{"model": model_clean, "line": raw_clean}])
            if not res.get("success"):
                return res
            return {
                "success": True,
                "type": "vehicles_ide",
                "model": model_clean,
                "raw": raw_clean,
                "decomposed": decomposed,
                "file": "vehicles.ide"
            }

        return {"success": False, "error": f"Unsupported configuration type: {config_type}"}

    def update_tuning_part_id(self, model: str, part_name: str, new_id: int) -> Dict[str, Any]:
        """
        Update or assign the model ID for a specific tuning part in veh_mods.ide.
        Performs ID collision checks via IdManager to protect against duplicate/conflicting IDs.
        Saves changes to shadow veh_mods.ide and creates timestamped .bak backups.
        """
        model_clean = (model or "").strip().lower()
        part_clean = (part_name or "").strip().lower()

        if not model_clean:
            return {"success": False, "error": "Missing target model parameter"}
        if not part_clean:
            return {"success": False, "error": "Missing part name parameter"}

        try:
            new_id = int(new_id)
            if new_id < 400 or new_id > 65535:
                return {"success": False, "error": f"ID {new_id} is out of GTA SA valid range (400 - 65535)"}
        except (ValueError, TypeError):
            return {"success": False, "error": "ID must be a valid integer"}

        # 1. Collision check via IdManager
        if self.tuning_mgr.id_mgr:
            status = self.tuning_mgr.id_mgr.check_id_status(new_id)
            if not status.get("is_free"):
                occupied_name = status.get("name", "").lower()
                if occupied_name != part_clean:
                    occ_file = status.get("file", "unknown file")
                    return {
                        "success": False,
                        "error": f"ID {new_id} is occupied ({status.get('name')}, from {occ_file}); please choose another available ID!",
                        "conflict": status
                    }

        # 2. Ensure shadow veh_mods.ide exists
        vpath = os.path.join(self.shadow_dir, "veh_mods.ide")
        if not os.path.exists(vpath):
            if not self._ensure_shadow_file("veh_mods.ide"):
                os.makedirs(self.shadow_dir, exist_ok=True)
                write_text_atomic(vpath, "objs\nend\n")

        self._backup(vpath)

        # 3. Read and modify veh_mods.ide
        with open(vpath, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        in_objs = False
        part_found = False

        mod_details = self.tuning_mgr.get_all_veh_mods_details()
        existing_info = mod_details.get(part_clean)
        txd_name = existing_info["txd_name"] if existing_info else model_clean
        draw_dist = existing_info["draw_dist"] if existing_info else 100.0
        raw_flags = existing_info["flags"] if existing_info else 2097152
        flags = determine_veh_mod_flags(part_clean, base_flags=raw_flags)
        draw_str = str(int(draw_dist)) if isinstance(draw_dist, float) and draw_dist.is_integer() else str(draw_dist)

        for line in lines:
            stripped = line.strip()
            if stripped.lower() == "objs":
                in_objs = True
                new_lines.append(line)
                continue
            if in_objs and stripped.lower() == "end":
                if not part_found:
                    new_lines.append(f"{new_id}, {part_clean}, {txd_name}, {draw_str}, {flags}\n")
                    part_found = True
                in_objs = False
                new_lines.append(line)
                continue
            if in_objs:
                parts = [p.strip() for p in stripped.split(",") if p.strip()]
                if len(parts) >= 2 and parts[1].lower() == part_clean:
                    cur_txd = parts[2].lower() if len(parts) > 2 else txd_name
                    cur_draw = parts[3] if len(parts) > 3 else draw_str
                    cur_flags = parts[4] if len(parts) > 4 else str(flags)
                    if cur_flags.isdigit():
                        cur_flags = str(determine_veh_mod_flags(part_clean, int(cur_flags)))
                    new_lines.append(f"{new_id}, {part_clean}, {cur_txd}, {cur_draw}, {cur_flags}\n")
                    part_found = True
                    continue
            new_lines.append(line)

        if not part_found:
            new_lines.append("\nobjs\n")
            new_lines.append(f"{new_id}, {part_clean}, {txd_name}, {draw_str}, {flags}\n")
            new_lines.append("end\n")

        write_text_atomic(vpath, new_lines)

        # 4. Refresh IdManager cache
        if self.tuning_mgr.id_mgr:
            self.tuning_mgr.id_mgr.scan_all_ides(force_refresh=True)

        # 5. Return updated vehicle configs
        active_configs = self.get_vehicle_active_configs(model_clean)
        return {
            "success": True,
            "model": model_clean,
            "part_name": part_clean,
            "new_id": new_id,
            "active_configs": active_configs
        }

    def delete_tuning_part(self, model: str, part_name: str) -> Dict[str, Any]:
        """
        Completely delete a tuning part from the active vehicle setup:
        1. Remove the part token from carmods.dat vehicle mods line.
        2. Remove any mirror pairs involving the part from carmods.dat link section.
        3. Remove the object definition line from shadow veh_mods.ide (if defined).
        4. Remove any fallback entry from shadow shopping.dat (if present).
        Creates timestamped backups (.bak) before modifying any shadow file.
        """
        model_clean = (model or "").strip().lower()
        part_clean = (part_name or "").strip().lower()

        if not model_clean:
            return {"success": False, "error": "Missing target model parameter"}
        if not part_clean:
            return {"success": False, "error": "Missing part name parameter"}

        # 1. Update carmods.dat
        self._ensure_shadow_file("carmods.dat")
        carmods_path = os.path.join(self.shadow_dir, "carmods.dat")
        if os.path.exists(carmods_path):
            self._backup(carmods_path)
            with open(carmods_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                carmods_lines = f.readlines()

            new_carmods_lines = []
            in_mods = False
            in_link = False

            for line in carmods_lines:
                stripped = line.strip()
                if stripped.lower() == "mods":
                    in_mods = True
                    new_carmods_lines.append(line)
                    continue
                if stripped.lower() == "link":
                    in_link = True
                    new_carmods_lines.append(line)
                    continue
                if stripped.lower() == "end":
                    in_mods = False
                    in_link = False
                    new_carmods_lines.append(line)
                    continue

                if in_mods:
                    parts = [p.strip() for p in stripped.split(",") if p.strip()]
                    if parts and parts[0].lower() == model_clean:
                        remaining_parts = [p for p in parts[1:] if p.lower() != part_clean]
                        if remaining_parts:
                            new_carmods_lines.append(f"{model_clean}, " + ", ".join(remaining_parts) + "\n")
                        else:
                            new_carmods_lines.append(f"{model_clean}\n")
                        continue

                if in_link:
                    parts = [p.strip() for p in stripped.split(",") if p.strip()]
                    if len(parts) >= 2 and (parts[0].lower() == part_clean or parts[1].lower() == part_clean):
                        continue

                new_carmods_lines.append(line)

            write_text_atomic(carmods_path, new_carmods_lines)

        # 2. Update shadow veh_mods.ide (remove definition line)
        veh_mods_path = os.path.join(self.shadow_dir, "veh_mods.ide")
        if os.path.exists(veh_mods_path):
            self._backup(veh_mods_path)
            with open(veh_mods_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                vm_lines = f.readlines()

            new_vm_lines = []
            in_objs = False
            for line in vm_lines:
                stripped = line.strip()
                if stripped.lower() == "objs":
                    in_objs = True
                    new_vm_lines.append(line)
                    continue
                if stripped.lower() == "end":
                    in_objs = False
                    new_vm_lines.append(line)
                    continue
                if in_objs:
                    parts = [p.strip() for p in stripped.split(",") if p.strip()]
                    if len(parts) >= 2 and parts[1].lower() == part_clean:
                        continue
                new_vm_lines.append(line)

            write_text_atomic(veh_mods_path, new_vm_lines)

        # 3. Update shadow shopping.dat (remove fallback item if present)
        shopping_path = os.path.join(self.shadow_dir, "shopping.dat")
        if os.path.exists(shopping_path):
            self._backup(shopping_path)
            with open(shopping_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                shop_lines = f.readlines()

            new_shop_lines = []
            for line in shop_lines:
                stripped = line.strip()
                parts = stripped.split()
                if parts:
                    if parts[0].lower() == part_clean:
                        continue
                    if parts[0].lower() == "item" and len(parts) >= 2 and parts[1].lower() == part_clean:
                        continue
                new_shop_lines.append(line)

            write_text_atomic(shopping_path, new_shop_lines)

        # 4. Refresh IdManager cache
        if self.tuning_mgr.id_mgr:
            self.tuning_mgr.id_mgr.scan_all_ides(force_refresh=True)

        # 5. Return updated vehicle configs
        active_configs = self.get_vehicle_active_configs(model_clean)
        return {
            "success": True,
            "model": model_clean,
            "deleted_part": part_clean,
            "active_configs": active_configs
        }
