"""
Mod Scanner: Discovers and catalogs installed vehicle mods in ModLoader.
"""

import os
import re
from typing import Dict, Any, List, Optional
from .parser import DualTrackParser
from .merger import ConfigMerger
from .source_documents import enrich_archived_vehicle_metadata
from .tuning_manager import TuningManager
from .fla_manager import FLAManager
from .vanilla_data import VANILLA_VEHICLES, MODEL_TO_ID, SPECIAL_FEATURE_TARGETS, NATIVE_SPECIAL_FEATURES, VANILLA_AUDIO_SETTINGS

class ModScanner:
    def __init__(self, mod_dir: str, game_path: str, data_dir: Optional[str] = None, addon_dir: Optional[str] = None):
        self.mod_dir = os.path.normpath(mod_dir)
        self.shadow_dir = self.mod_dir
        self.game_path = os.path.normpath(game_path)
        self.parser = DualTrackParser()
        self.data_dir = os.path.normpath(data_dir) if data_dir else self.mod_dir
        self.tuning_mgr = TuningManager(self.data_dir, self.game_path)
        self.fla_mgr = FLAManager(self.game_path)
        self.addon_dir = os.path.normpath(addon_dir) if addon_dir else os.path.join(self.game_path, "modloader", "Addon Cars")

    def set_addon_dir(self, addon_dir: str):
        self.addon_dir = os.path.normpath(addon_dir)

    def set_shadow_dir(self, shadow_dir: str):
        self.shadow_dir = os.path.normpath(shadow_dir)
        self.mod_dir = self.shadow_dir

    def scan_installed_mods(self) -> List[Dict[str, Any]]:
        """
        Scan all vehicle mods across both replacement directory (Modded Cars)
        and addon directory (Addon Cars).
        """
        existing_shopping = self.tuning_mgr.get_existing_shopping_items()
        scan_roots = []
        if os.path.isdir(self.shadow_dir):
            scan_roots.append((self.shadow_dir, False))

        addon_path = self.addon_dir if (self.addon_dir and os.path.isdir(self.addon_dir)) else os.path.join(self.game_path, "modloader", "Addon Cars")
        if os.path.isdir(addon_path) and os.path.normpath(addon_path) != os.path.normpath(self.shadow_dir):
            scan_roots.append((addon_path, True))

        installed = []
        for root_path, is_addon_folder in scan_roots:
            installed.extend(self._scan_directory(root_path, is_addon_folder, existing_shopping))

        return installed

    def _scan_directory(self, root_path: str, is_addon_folder: bool, existing_shopping: set) -> List[Dict[str, Any]]:
        """Scan a specific root folder (e.g. Modded Cars or Addon Cars)."""
        if not os.path.isdir(root_path):
            return []

        installed = []
        modloader_dir = os.path.join(self.game_path, "modloader")

        for entry in os.listdir(root_path):
            entry_path = os.path.join(root_path, entry)
            if not os.path.isdir(entry_path):
                continue

            # Look for vehicle mods directly or under author folders
            # Check if entry_path itself has .dff
            has_direct_dff = any(f.lower().endswith(".dff") for f in os.listdir(entry_path) if os.path.isfile(os.path.join(entry_path, f)))

            if has_direct_dff:
                mod_info = self._analyze_mod_folder(
                    entry_path,
                    author="Root",
                    existing_shopping=existing_shopping,
                    is_addon_folder=is_addon_folder,
                    modloader_dir=modloader_dir
                )
                if mod_info:
                    installed.append(mod_info)
            else:
                # Treat entry as author folder, scan subfolders
                author_name = entry
                for sub in os.listdir(entry_path):
                    sub_path = os.path.join(entry_path, sub)
                    if os.path.isdir(sub_path):
                        # Nested mod folder
                        mod_info = self._analyze_mod_folder(
                            sub_path,
                            author=author_name,
                            existing_shopping=existing_shopping,
                            is_addon_folder=is_addon_folder,
                            modloader_dir=modloader_dir
                        )
                        if mod_info:
                            installed.append(mod_info)
                        else:
                            # Could be 3-level deep (e.g. 1300corollavan-san / Previon / 1.8 Twin Carb)
                            for subsub in os.listdir(sub_path):
                                subsub_path = os.path.join(sub_path, subsub)
                                if os.path.isdir(subsub_path):
                                    deep_info = self._analyze_mod_folder(
                                        subsub_path,
                                        author=f"{author_name} / {sub}",
                                        existing_shopping=existing_shopping,
                                        is_addon_folder=is_addon_folder,
                                        modloader_dir=modloader_dir
                                    )
                                    if deep_info:
                                        installed.append(deep_info)

        return installed

    def _analyze_mod_folder(self, mod_path: str, author: str, existing_shopping: set,
                            is_addon_folder: bool = False,
                            modloader_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Analyze a single candidate vehicle mod folder."""
        # Quick check: does it or its immediate children have .dff files?
        has_dff = False
        for root, dirs, files in os.walk(mod_path):
            if any(f.lower().endswith(".dff") for f in files):
                has_dff = True
                break

        if not has_dff:
            return None

        inspection = self.parser.inspect_mod_directory(mod_path)
        if not inspection["success"]:
            return None

        deployed_configs = enrich_archived_vehicle_metadata(
            inspection, ConfigMerger(self.shadow_dir, self.game_path)) if inspection.get("archived_source_count") else {}
        target_model = inspection.get("target_model")
        vanilla_info = inspection.get("target_vanilla")
        target_models = inspection.get("target_models", [target_model] if target_model else [])
        target_vehicles = inspection.get("target_vehicles", [])
        target_names = [v["name"] for v in target_vehicles] if target_vehicles else ([vanilla_info["name"]] if vanilla_info else [])

        # Categorize replace vs addon
        is_addon = bool(
            is_addon_folder
            or (vanilla_info and vanilla_info.get("is_addon"))
            or (target_vehicles and all(v.get("is_addon") for v in target_vehicles))
            or (target_model and target_model.lower() not in MODEL_TO_ID)
        )
        mod_type = "addon" if is_addon else "replace"

        addon_id = None
        if is_addon:
            if vanilla_info and vanilla_info.get("id"):
                addon_id = vanilla_info["id"]
            elif target_vehicles and target_vehicles[0].get("id"):
                addon_id = target_vehicles[0]["id"]
            elif inspection.get("parsed", {}).get("ide"):
                for ide in inspection["parsed"]["ide"]:
                    if ide and ide.get("id"):
                        addon_id = ide["id"]
                        break
            if not addon_id:
                addon_id = inspection.get("addon_id")

        if not modloader_dir:
            modloader_dir = os.path.join(self.game_path, "modloader")

        if os.path.isabs(mod_path) and modloader_dir and mod_path.startswith(modloader_dir):
            rel_path = os.path.relpath(mod_path, modloader_dir)
        else:
            rel_path = os.path.relpath(mod_path, self.shadow_dir)

        # Check tuning safety across all carmods
        tuning_parts = []
        installed_carmods = list(inspection["parsed"]["carmods"])
        for cfg in deployed_configs.values():
            cm = (cfg.get("carmods") or {}).get("decomposed")
            if cm and cm not in installed_carmods:
                installed_carmods.append(cm)
        for cmod in installed_carmods:
            for pname in cmod.get("part_names", []):
                p_clean = pname.lower().strip()
                if re.match(r'^[a-z0-9_]{2,24}$', p_clean) and p_clean not in tuning_parts:
                    tuning_parts.append(p_clean)
        for tdff in inspection["files"]["tuning_dffs"]:
            pname = os.path.splitext(tdff["name"])[0].lower().strip()
            if re.match(r'^[a-z0-9_]{2,24}$', pname) and pname not in tuning_parts:
                tuning_parts.append(pname)

        missing_shopping_parts = [
            p for p in tuning_parts
            if p.lower() not in existing_shopping
            and not self.tuning_mgr.is_mirror_counterpart(p, existing_shopping)
        ]

        # Check FLA audio & special features across all target models.
        # The FLA audio cfg always ships a baseline row for every vanilla
        # vehicle, so "has custom audio" must come from the mod's own txt
        # preset or from a deployed line that actually differs from vanilla.
        all_fla_specials = []
        has_any_audio = False
        target_set = {(m or "").lower() for m in target_models}
        for al in (inspection.get("parsed", {}) or {}).get("audio_lines", []) or []:
            parts = (al or "").strip().split()
            if parts and parts[0].lower() in target_set:
                has_any_audio = True
                break
        for tm in target_models:
            sp = self.fla_mgr.get_feature_for_model(tm)
            if sp and not any(s["target"] == sp["target"] for s in all_fla_specials):
                all_fla_specials.append(sp)
        if not has_any_audio:
            for tm in target_models:
                deployed = self.fla_mgr.get_audio_for_model(tm)
                vanilla = VANILLA_AUDIO_SETTINGS.get((tm or "").lower())
                if deployed and (not vanilla or deployed.split() != vanilla.split()):
                    has_any_audio = True
                    break

        if not all_fla_specials and inspection.get("parsed", {}).get("special_features"):
            for sf_line in inspection["parsed"]["special_features"]:
                parts = sf_line.split()
                if len(parts) >= 2:
                    sf_target = parts[1].lower()
                    info = SPECIAL_FEATURE_TARGETS.get(sf_target, NATIVE_SPECIAL_FEATURES.get(sf_target))
                    if info and not any(s["target"] == sf_target for s in all_fla_specials):
                        all_fla_specials.append({
                            "target": sf_target,
                            "label": info.get("label_zh", info.get("label", sf_target)),
                            "label_en": info.get("label_en", sf_target),
                            "desc": info.get("desc_zh", info.get("desc", "")),
                            "desc_en": info.get("desc_en", ""),
                            "is_native": False,
                            "from_readme": True,
                            "icon": info.get("icon", "⭐")
                        })

        vanilla_display_name = " / ".join(target_names) if target_names else (vanilla_info["name"] if vanilla_info else (target_model.upper() if target_model else "UNKNOWN"))

        return {
            "name": inspection["mod_name"],
            "author": author,
            "mod_type": mod_type,
            "is_addon": is_addon,
            "addon_id": addon_id,
            "rel_path": rel_path,
            "full_path": mod_path,
            "target_model": target_model,
            "target_id": addon_id if is_addon else (MODEL_TO_ID.get(target_model) if target_model else None),
            "target_models": target_models,
            "target_vehicles": target_vehicles,
            "target_names": target_names,
            "vanilla_name": vanilla_display_name,
            "vanilla_type": vanilla_info["type"] if vanilla_info else "car",
            "tuning_shop": vanilla_info["shop"] if vanilla_info else "none",
            "has_handling": bool(inspection["parsed"]["handling"]) or any(
                c.get("handling") and c["handling"].get("source") != "vanilla" for c in deployed_configs.values()),
            "has_carcols": bool(inspection["parsed"]["carcols"]) or any(
                c.get("carcols") and c["carcols"].get("source") != "vanilla" for c in deployed_configs.values()),
            "has_carmods": bool(inspection["parsed"]["carmods"]) or any(
                c.get("carmods") and c["carmods"].get("source") != "vanilla" for c in deployed_configs.values()),
            "tuning_dff_count": inspection["files"]["tuning_dff_count"],
            "total_tuning_parts": len(tuning_parts),
            "missing_shopping_parts": missing_shopping_parts,
            "has_shopping_risk": len(missing_shopping_parts) > 0,
            "fla_special": all_fla_specials[0] if all_fla_specials else None,
            "fla_specials": all_fla_specials,
            "fla_has_audio": has_any_audio,
            "inspection": inspection
        }
