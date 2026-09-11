"""
Tuning Parts Manager:
Handles carmods.dat, veh_mods.ide, and shopping.dat dependencies.
Automatically detects left/right mirror pairs (link section), assigns IDs,
and creates anti-crash fallback shopping.dat entries.
"""

import os
import re
import struct
from typing import Dict, Any, List, Tuple, Optional
from .vanilla_data import TUNING_PREFIX_INFO, VANILLA_VEHICLES, MODEL_TO_ID
from .id_manager import IdManager


def check_dff_has_damage_model(dff_path: str) -> bool:
    """
    Inspect a RenderWare .dff file to check if any atomic/frame node ends with '_dam'.
    RenderWare node names are stored in 0x0253F2FE (rwID_NODENAME) plugin chunks.
    """
    if not dff_path or not os.path.isfile(dff_path):
        return False
    try:
        with open(dff_path, "rb") as f:
            data = f.read()
        pos = 0
        data_len = len(data)
        while pos < data_len - 12:
            chunk_type, chunk_size, _ = struct.unpack("<III", data[pos:pos+12])
            if chunk_type == 0x0253F2FE:  # rwID_NODENAME
                name_bytes = data[pos+12 : pos+12+chunk_size]
                name = name_bytes.split(b"\x00")[0].decode("latin1", errors="replace").lower()
                if name.endswith("_dam"):
                    return True
                pos += 12 + chunk_size
            else:
                pos += 1
    except Exception:
        pass
    return False


def is_damageable_tuning_part(part_name: str, dff_path: Optional[str] = None) -> bool:
    """
    Determine whether a tuning part has damaged mesh states.
    In GTA SA, tuning parts with damaged states must have flag bit 4096 (0x1000) set in veh_mods.ide.
    Missing flag 4096 causes CFileLoader::SetRelatedModelInfoCB to pass a NULL CDamageAtomicModelInfo
    pointer to CDamagableModelInfo::SetDamagedAtomic, crashing at 0x004C48D6 (Access Violation writing [0x20]).
    """
    # 1. Inspect actual .dff binary if available
    if dff_path and check_dff_has_damage_model(dff_path):
        return True

    # 2. GTA San Andreas part naming convention:
    # - fbmp_*: front bumper (e.g. fbmp_a_zr, fbmp_c_zr, fbmp_a_l, fbmp_c_s)
    # - rbmp_*: rear bumper (e.g. rbmp_a_zr, rbmp_c_zr, rbmp_a_l, rbmp_c_s)
    #   (Vanilla exception: fbmp_lr_slv1 is the only bumper with no damage model in vanilla SA)
    # - spl_*_b: boot/trunk spoiler (e.g. spl_a_zr_b, spl_c_zr_b, spl_a_s_b, spl_c_l_b)
    # - bntr_* / bntl_*: bonnet vents/scoops attached to damageable bonnet
    # - part containing '_dam'
    p = (part_name or "").lower().strip()
    if p == "fbmp_lr_slv1":
        return False
    if p.startswith("fbmp_") or p.startswith("rbmp_"):
        return True
    if p.startswith("spl_") and p.endswith("_b"):
        return True
    if p.startswith("bntr_") or p.startswith("bntl_"):
        return True
    if "_dam" in p:
        return True

    return False


def determine_veh_mod_flags(part_name: str, base_flags: Optional[int] = 2097152, dff_path: Optional[str] = None) -> int:
    """
    Calculates correct flags for a veh_mods.ide entry.
    Ensures bit 4096 is set if the part has damage states.
    """
    flags = 2097152 if base_flags is None else int(base_flags)
    if is_damageable_tuning_part(part_name, dff_path):
        flags |= 4096
    return flags


class TuningManager:
    def __init__(self, shadow_dir: str, game_path: Optional[str] = None):
        self.shadow_dir = os.path.normpath(shadow_dir)
        self.carmods_path = os.path.join(self.shadow_dir, "carmods.dat")
        self.shopping_path = os.path.join(self.shadow_dir, "shopping.dat")
        self.veh_mods_path = os.path.join(self.shadow_dir, "veh_mods.ide")

        if game_path and os.path.exists(game_path):
            self.game_path = os.path.normpath(game_path)
        else:
            # Attempt to infer game_path from shadow_dir if inside modloader
            lower_sd = self.shadow_dir.lower()
            if "modloader" in lower_sd:
                idx = lower_sd.find("modloader")
                self.game_path = self.shadow_dir[:idx].rstrip(r"\/")
            else:
                self.game_path = ""

        self.id_mgr = IdManager(self.game_path) if self.game_path and os.path.exists(self.game_path) else None

        # Mirror-link cache, revalidated against the carmods.dat fingerprint.
        self._cached_linked_parts: Optional[set] = None
        self._cached_linked_parts_stamp = None

    # ---------------- Left / Right Mirror Matching ----------------

    def find_mirror_links(self, part_names: List[str]) -> List[Tuple[str, str]]:
        """
        Detect left/right mirror pairs for carmods.dat 'link ... end' section.
        e.g. wg_l_lr_tah1 and wg_r_lr_tah1 -> ('wg_l_lr_tah1', 'wg_r_lr_tah1')
        """
        parts_set = set(p.lower() for p in part_names)
        links = []
        visited = set()

        for p in parts_set:
            if p in visited:
                continue
            # Check left to right patterns
            right_counterpart = None
            if "_l_" in p:
                right_counterpart = p.replace("_l_", "_r_", 1)
            elif p.startswith("bntl_"):
                right_counterpart = "bntr_" + p[5:]

            if right_counterpart and right_counterpart in parts_set:
                links.append((p, right_counterpart))
                visited.add(p)
                visited.add(right_counterpart)

        return links

    # ---------------- shopping.dat Safety Checks & Generation ----------------

    def get_existing_shopping_items(self) -> set:
        """Returns set of lowercased item names registered in shopping.dat."""
        items = set()
        candidates = [self.shopping_path]
        if self.game_path:
            vanilla_shopping = os.path.join(self.game_path, "data", "shopping.dat")
            candidates.append(vanilla_shopping)

        for path in candidates:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        items.add(parts[0].lower())
        return items

    def get_existing_link_pairs(self) -> set:
        """
        Existing link pairs from carmods.dat 'link ... end' (shadow + vanilla),
        as frozensets of the two lowercased part names. Used to keep mirror-link
        merges idempotent instead of appending duplicates on every install.
        """
        pairs = set()
        candidates = [self.carmods_path]
        if self.game_path:
            candidates.append(os.path.join(self.game_path, "data", "carmods.dat"))
        for path in candidates:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    in_link = False
                    for line in f:
                        s = line.strip().lower()
                        if s == "link":
                            in_link = True
                            continue
                        if in_link and s == "end":
                            break
                        if in_link and s and not s.startswith("#") and not s.startswith(";"):
                            parts = [p.strip() for p in s.split(",") if p.strip()]
                            if len(parts) >= 2:
                                pairs.add(frozenset((parts[0], parts[1])))
            except Exception:
                pass
        return pairs

    def get_shopping_prices(self) -> Dict[str, int]:
        """
        Returns item_name -> price parsed from shopping.dat (vanilla first,
        shadow overrides). Used by the inspector to show the real shop price
        instead of the category default.
        """
        prices = {}
        candidates = []
        if self.game_path:
            candidates.append(os.path.join(self.game_path, "data", "shopping.dat"))
        candidates.append(self.shopping_path)
        for path in candidates:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith("#") or s.startswith(";") or s.startswith("section"):
                            continue
                        parts = s.split()
                        if len(parts) >= 2:
                            try:
                                price = int(parts[-1])
                            except (ValueError, TypeError):
                                continue
                            if price >= 0:
                                prices[parts[0].lower()] = price
            except Exception:
                pass
        return prices

    def _carmods_candidates(self) -> List[str]:
        """carmods.dat files the mirror-link set is read from, shadow first."""
        candidates = [self.carmods_path]
        if self.game_path:
            candidates.append(os.path.join(self.game_path, "data", "carmods.dat"))
        return candidates

    def _linked_parts_stamp(self):
        """Fingerprint used to notice that carmods.dat changed on disk."""
        stamp = []
        for path in self._carmods_candidates():
            try:
                st = os.stat(path)
                stamp.append((path, st.st_mtime_ns, st.st_size))
            except OSError:
                stamp.append((path, None, None))
        return tuple(stamp)

    def _linked_parts(self) -> set:
        """
        Cached mirror-link set. Re-read whenever carmods.dat changes, so a merge
        that registers a new pair is visible to later installs in the session.
        """
        stamp = self._linked_parts_stamp()
        if self._cached_linked_parts is None or stamp != self._cached_linked_parts_stamp:
            self._cached_linked_parts = self.get_linked_mirror_parts()
            self._cached_linked_parts_stamp = stamp
        return self._cached_linked_parts

    def get_linked_mirror_parts(self) -> set:
        """
        Returns set of lowercased secondary/mirror part names from carmods.dat link section.
        In GTA SA, mirror counterparts (like wg_r_...) are linked to primary parts (wg_l_...)
        and installed automatically as pairs; they are NEVER sold in shopping.dat and do not
        cause shopping crashes.
        """
        linked_parts = set()

        for path in self._carmods_candidates():
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                in_link = False
                for line in f:
                    s = line.strip().lower()
                    if s == "link":
                        in_link = True
                        continue
                    if in_link and s == "end":
                        in_link = False
                        break
                    if in_link and s and not s.startswith("#") and not s.startswith(";"):
                        parts = [p.strip() for p in s.split(",") if p.strip()]
                        if len(parts) >= 2:
                            linked_parts.add(parts[1].lower())
        return linked_parts

    def is_mirror_counterpart(self, part_name: str, existing_shopping: Optional[set] = None) -> bool:
        """
        Check if a part is a right-side mirror counterpart (installed automatically in pairs,
        never sold individually in shopping.dat and does not cause shopping crashes).
        """
        p = part_name.lower().strip()
        linked = self._linked_parts()

        if p in linked:
            return True

        if "_r_" in p:
            left = p.replace("_r_", "_l_", 1)
            if existing_shopping and left in existing_shopping:
                return True
            if left in linked:
                return True
            if p.startswith("wg_r_"):
                return True

        if p.startswith("bntr_"):
            return True

        return False

    def generate_missing_shopping_entries(self, part_names: List[str], car_name: str) -> List[Dict[str, Any]]:
        """
        Detect parts missing from shopping.dat and generate safe fallback entries
        to prevent game crashes when entering tuning shops.
        Filters out mirrored secondary parts that do not need shopping entries.
        """
        existing = self.get_existing_shopping_items()
        missing_entries = []

        for p in part_names:
            p_lower = p.lower().strip()
            # Skip mirrored counterparts which are never sold in shopping.dat
            if self.is_mirror_counterpart(p_lower, existing):
                continue

            if p_lower not in existing:
                # Find category info
                default_price = 350
                category = "misc"
                for prefix, info in TUNING_PREFIX_INFO.items():
                    if p_lower.startswith(prefix):
                        default_price = info["default_price"]
                        category = info["category"]
                        break

                # Generate a compact 7-char tag
                tag = (p_lower[:6].upper() + "1")[:7]
                entry_line = f"\t\t{p_lower:<16}\t{tag:<8}\trespect 0 \tsexy 0\t\t{default_price}\t# AUTO-GENERATED FOR {car_name.upper()}"

                missing_entries.append({
                    "part_name": p_lower,
                    "tag": tag,
                    "price": default_price,
                    "category": category,
                    "line": entry_line
                })

        return missing_entries

    def infer_workshop_section(self, car_name: str, part_names: List[str], target_vanilla_shop: Optional[str] = None) -> str:
        """
        Infer the target workshop section (carmod1, carmod2, carmod3) for a vehicle.
        Priority:
        1. Part name heuristic fingerprint:
           - '_lr_', 'fbb_', 'bbb_' -> carmod2 (Loco Low Co.)
           - '_a_', '_c_' with WAA prefixes -> carmod3 (Wheel Arch Angels)
        2. target_vanilla_shop / Car name lookup in MODEL_TO_ID -> VANILLA_VEHICLES
        3. default -> carmod1 (TransFender)
        """
        # 1. Part features take precedence for custom bodykits (e.g. ZR350 vanilla is transfender, but mod gives it WAA parts)
        for p in part_names:
            pl = p.lower()
            if "_lr_" in pl or pl.startswith("fbb_") or pl.startswith("bbb_"):
                return "carmod2"
            if any(pl.startswith(pfx) for pfx in ("spl_a_", "spl_c_", "exh_a_", "exh_c_", "fbmp_a_", "fbmp_c_", "rbmp_a_", "rbmp_c_", "rf_a_", "rf_c_", "wg_l_a_", "wg_l_c_")):
                return "carmod3"

        # 2. Vanilla shop lookup
        if target_vanilla_shop:
            s = target_vanilla_shop.lower()
            if "arch" in s or "wheel" in s:
                return "carmod3"
            if "loco" in s or "low" in s:
                return "carmod2"
            if "trans" in s or "fender" in s:
                return "carmod1"

        c_lower = (car_name or "").strip().lower()
        if c_lower in MODEL_TO_ID:
            v_info = VANILLA_VEHICLES.get(MODEL_TO_ID[c_lower], {})
            shop = v_info.get("shop", "").lower()
            if shop == "wheelarchangels":
                return "carmod3"
            if shop == "locolowco":
                return "carmod2"
            if shop == "transfender":
                return "carmod1"

        return "carmod1"

    # ---------------- veh_mods.ide Safety & Free ID Allocation ----------------

    def _parse_veh_mods_file(self, file_path: str, mods_dict: Dict[str, int]):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                in_objs = False
                for line in f:
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
                            mods_dict[parts[1].lower()] = int(parts[0])
        except Exception:
            pass

    def _parse_veh_mods_details(self, file_path: str, details_dict: Dict[str, Dict[str, Any]], source: str = "shadow"):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                in_objs = False
                for line in f:
                    raw_line = line.strip()
                    if not raw_line or raw_line.startswith("#"):
                        continue
                    if raw_line.lower() == "objs":
                        in_objs = True
                        continue
                    if raw_line.lower() == "end":
                        in_objs = False
                        continue
                    if in_objs:
                        parts = [p.strip() for p in raw_line.split(",") if p.strip()]
                        if len(parts) >= 5 and parts[0].isdigit() and parts[4].isdigit():
                            pname = parts[1].lower()
                            details_dict[pname] = {
                                "id": int(parts[0]),
                                "part_name": pname,
                                "txd_name": parts[2].lower(),
                                "draw_dist": float(parts[3]) if re.match(r'^\d+(\.\d+)?$', parts[3]) else 100.0,
                                "flags": int(parts[4]),
                                "source": source,
                                "file": file_path,
                                "raw": raw_line
                            }
        except Exception:
            pass

    def get_existing_veh_mods(self) -> Dict[str, int]:
        """Returns dict of part_name -> model_id registered in veh_mods.ide (vanilla + shadow)."""
        mods = {}
        if self.game_path:
            vanilla_veh_mods = os.path.join(self.game_path, "data", "maps", "veh_mods", "veh_mods.ide")
            self._parse_veh_mods_file(vanilla_veh_mods, mods)
        self._parse_veh_mods_file(self.veh_mods_path, mods)
        return mods

    def get_all_veh_mods_details(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns dict of part_name -> { id, txd_name, draw_dist, flags, source, file, raw }
        Checks vanilla baseline first, then overrides with shadow entries.
        """
        details = {}
        if self.game_path:
            vanilla_veh_mods = os.path.join(self.game_path, "data", "maps", "veh_mods", "veh_mods.ide")
            self._parse_veh_mods_details(vanilla_veh_mods, details, source="vanilla")
        self._parse_veh_mods_details(self.veh_mods_path, details, source="shadow")
        return details

    def get_max_veh_mod_id(self) -> int:
        """Find highest ID in veh_mods.ide (e.g. 11747)."""
        mods = self.get_existing_veh_mods()
        if not mods:
            return 1193
        return max(mods.values())

    def generate_missing_veh_mods_entries(
        self,
        part_names: List[str],
        txd_name: str,
        custom_ids: Optional[Dict[str, int]] = None,
        part_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        dff_map: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate veh_mods.ide entries for custom parts not yet registered.
        If custom_ids is supplied (e.g. from user manual entry), respects those IDs.
        Otherwise automatically allocates safe, conflict-free IDs using IdManager.
        Respects author IDE flags/draw_dist/txd if part_configs is provided, and
        ensures damageable parts (fbmp_, rbmp_, spl_*_b, _dam in DFF) have bit 4096 set.
        """
        custom_ids = {k.lower(): int(v) for k, v in (custom_ids or {}).items()}
        existing = self.get_existing_veh_mods()

        # Identify which parts need an allocated ID vs custom ID
        # Strictly skip any part already registered in veh_mods.ide (vanilla or shadow)
        parts_to_assign = []
        for p in part_names:
            p_lower = p.lower()
            if p_lower in existing:
                continue
            if p_lower in custom_ids:
                continue
            if p_lower not in parts_to_assign:
                parts_to_assign.append(p_lower)

        # Allocate free IDs for remaining parts
        allocated_ids = []
        if parts_to_assign:
            if self.id_mgr:
                allocated_ids = self.id_mgr.allocate_free_ids(
                    len(parts_to_assign),
                    exclude_ids=set(custom_ids.values())
                )
            else:
                next_id = max(self.get_max_veh_mod_id(), 11746) + 1
                for _ in parts_to_assign:
                    while next_id in custom_ids.values():
                        next_id += 1
                    allocated_ids.append(next_id)
                    next_id += 1

        missing_entries = []
        assign_idx = 0
        seen_generated = set()

        for p in part_names:
            p_lower = p.lower()
            # If already defined in veh_mods.ide (vanilla or shadow), NEVER duplicate into veh_mods.ide!
            if p_lower in existing or p_lower in seen_generated:
                continue

            assigned_id = None
            if p_lower in custom_ids:
                assigned_id = custom_ids[p_lower]
            else:
                if assign_idx < len(allocated_ids):
                    assigned_id = allocated_ids[assign_idx]
                    assign_idx += 1

            if assigned_id is not None:
                seen_generated.add(p_lower)
                p_cfg = (part_configs or {}).get(p_lower, {})
                part_txd = (p_cfg.get("txd_name") or txd_name).lower()
                part_draw = p_cfg.get("draw_dist") if p_cfg.get("draw_dist") is not None else 100
                raw_flags = p_cfg.get("flags")
                dff_p = (dff_map or {}).get(p_lower)
                flags = determine_veh_mod_flags(p_lower, base_flags=raw_flags, dff_path=dff_p)

                draw_str = str(int(part_draw)) if isinstance(part_draw, float) and part_draw.is_integer() else str(part_draw)
                line = f"{assigned_id}, {p_lower}, {part_txd}, {draw_str}, {flags}"

                missing_entries.append({
                    "id": assigned_id,
                    "part_name": p_lower,
                    "txd_name": part_txd,
                    "draw_dist": part_draw,
                    "flags": flags,
                    "line": line
                })

        return missing_entries

