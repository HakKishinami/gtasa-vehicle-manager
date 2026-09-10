"""
Dual-Track Readme and Mod Package Parser for GTASA.
Combines Section Anchor Matching (Track 1) and Heuristic Syntax Fingerprinting (Track 2).
"""

import os
import re
from typing import Dict, Any, List, Optional
from .vanilla_data import VANILLA_VEHICLES, MODEL_TO_ID, TUNING_PREFIX_INFO, CARCOLS_PALETTE

# Section header regex (Track 1) - matches standalone section headers with optional markers/decorations
RE_SECTION_HEADER = re.compile(
    r'(?i)^\s*[-*#=_/\[\(]*\s*(veh_mods(?:\.ide)?|objs?|vehicles?\.ide|handling(?:\.cfg)?|carcols(?:\.dat)?|carmods(?:\.dat)?|shopping(?:\.dat)?|section\s+carmods?|section\s+carmod[1-3]|(?:gtasa_)?(?:vehicle[\s_]*)?audio(?:[\s_]*settings)?(?:\.cfg)?|model_special_features(?:\.dat)?|special_features|fxt(?:\.txt)?|gxt|cleo_text|vehicle_names?|car_names?)\b(?:\s*(?:data|lines?|settings?|code|section|parts?|\(fla\)))?[:\s\-*#=_/\]\)]*$'
)

# Inline section header regex - matches headers that have data directly on the same line (e.g. "#handling: PREVION ...", "[carcols] previon ...")
RE_INLINE_HEADER = re.compile(
    r'(?i)^\s*[-*#=_/\[\(]*\s*(veh_mods(?:\.ide)?|objs?|vehicles?\.ide|handling(?:\.cfg)?|carcols(?:\.dat)?|carmods(?:\.dat)?|shopping(?:\.dat)?|section\s+carmods?|section\s+carmod[1-3]|(?:gtasa_)?(?:vehicle[\s_]*)?audio(?:[\s_]*settings)?(?:\.cfg)?|model_special_features(?:\.dat)?|special_features|fxt(?:\.txt)?)\s*[\]\):=*#_/-]+\s*(.+)$'
)

RE_SHOPPING_INSTRUCTION = re.compile(
    r'(?i)(?:shopping(?:\.dat)?.*)?section\s+(carmods?|carmod[1-3])\b'
)

# Handling Header exclusion pattern (skip descriptive column header lines)
RE_HANDLING_COMMENT_HEADER = re.compile(
    r'(?i)\b(mass|turnmass|drag|centreofmass|traction|transmission|brakes|steer|suspension)\b'
)

# Valid vehicles.ide vehicle types (vanilla GTASA supported types)
VALID_IDE_TYPES = ("car", "bike", "heli", "plane", "boat", "trailer", "bmx", "quad", "mtruck", "dodo", "train", "wayfarer")

# vehicles.ide fingerprint (Track 2)
RE_IDE_FINGERPRINT = re.compile(
    r'^\s*(\d+)\s*,\s*([a-zA-Z0-9_]+)\s*,\s*([a-zA-Z0-9_]+)\s*,\s*(car|bike|heli|plane|boat|trailer|bmx|quad|mtruck|dodo|train|wayfarer)\b',
    re.IGNORECASE
)

# Vanilla vehicles.ide ships one malformed row whose two leading names are
# separated by a tab instead of a comma (id 586 wayfarer). The game's sscanf
# parser tolerates it; every comma-splitting reader must do the same.
RE_IDE_MISSING_COMMA = re.compile(
    r'^(\s*\d+\s*,\s*)([A-Za-z0-9_]+)[ \t]+([A-Za-z0-9_]+)(\s*,\s*)'
)


def normalize_ide_line(raw_line: str) -> str:
    """Insert the missing comma in the vanilla wayfarer vehicles.ide typo."""
    if not raw_line:
        return raw_line
    return RE_IDE_MISSING_COMMA.sub(r'\1\2, \3\4', raw_line, count=1)

# Carmods tuning parts prefix check
KNOWN_TUNING_PREFIXES = tuple(TUNING_PREFIX_INFO.keys())

# Unicode Private Use Area. GBK/GB18030 maps these to its user-defined slots,
# so a PUA code point in the result means the bytes were decoded with the wrong
# codec - typically a Big5 file read as GB18030.
_PUA_RANGES = (
    (0xE000, 0xF8FF),      # BMP
    (0xF0000, 0xFFFFD),    # Supplementary A
    (0x100000, 0x10FFFD),  # Supplementary B
)


def has_private_use(text: str) -> bool:
    """True when `text` contains a Private Use Area code point."""
    for ch in text:
        cp = ord(ch)
        for low, high in _PUA_RANGES:
            if low <= cp <= high:
                return True
    return False


def _has_cjk(text: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)


def detect_text_encoding(raw_bytes: bytes) -> Optional[str]:
    """
    Best-effort encoding detection for a game text file.

    Returns the codec that decodes `raw_bytes` losslessly, or None when no
    single codec does (in which case reading is lossy and the caller must not
    write the file back, or the original bytes are destroyed).

    Order: BOM, strict UTF-8, then legacy CJK (GB18030, then Big5), then
    Cyrillic, then a CP1252 fallback. The CJK candidates are validated by the
    script they produce, so a wrong guess is rejected instead of accepted.
    """
    if not raw_bytes:
        return "utf-8"

    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        try:
            raw_bytes.decode("utf-8-sig")
            return "utf-8-sig"
        except UnicodeDecodeError:
            pass

    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            raw_bytes.decode("utf-16")
            return "utf-16"
        except UnicodeDecodeError:
            pass

    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Legacy CJK. gb18030 decodes almost any byte sequence, so accept it only
    # when the result is plausible CJK text - PUA code points mean it guessed
    # wrong. A traditional-Chinese file lands here first and is rejected, then
    # Big5 picks it up; a simplified-Chinese file matches gb18030 directly.
    try:
        txt_gb = raw_bytes.decode("gb18030")
        if _has_cjk(txt_gb) and not has_private_use(txt_gb):
            return "gb18030"
    except UnicodeDecodeError:
        pass

    try:
        txt_big5 = raw_bytes.decode("big5")
        if _has_cjk(txt_big5) and not has_private_use(txt_big5):
            return "big5"
    except UnicodeDecodeError:
        pass

    # Legacy 8-bit encodings: detect Cyrillic before the generic CP1252 fallback.
    try:
        txt_cp1251 = raw_bytes.decode("cp1251")
        if any('\u0400' <= ch <= '\u04ff' for ch in txt_cp1251):
            return "cp1251"
    except UnicodeDecodeError:
        pass

    try:
        raw_bytes.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        pass

    try:
        raw_bytes.decode("utf-16")
        return "utf-16"
    except UnicodeDecodeError:
        pass

    return None


def read_text_file_safe(file_path: str) -> str:
    """Read a text file trying multiple encodings (utf-8-sig, gb18030, cp1252, cp1251, utf-16)."""
    if not os.path.isfile(file_path):
        return ""
    try:
        with open(file_path, "rb") as bf:
            raw_bytes = bf.read()
    except Exception:
        return ""

    if not raw_bytes:
        return ""

    codec = detect_text_encoding(raw_bytes)
    if codec is None:
        return raw_bytes.decode("utf-8", errors="replace").lstrip('\ufeff')
    if codec == "utf-16":
        return raw_bytes.decode("utf-16").lstrip('\ufeff')
    return raw_bytes.decode(codec)


class DualTrackParser:
    def __init__(self):
        pass

    def parse_text_content(self, text: str) -> Dict[str, Any]:
        """
        Parse raw readme/txt content into recognized configuration categories.
        Uses Section Anchors (Track 1) + Syntax Fingerprint (Track 2).
        Robust against both explicit section headers and headerless raw data dumps.
        """
        result = {
            "vehicles_ide": [],
            "handling_cfg": [],
            "carcols_dat": [],
            "carmods_dat": [],
            "veh_mods_ide": [],
            "shopping_dat": [],
            "vehicle_audio": [],
            "special_features": [],
            "fxt_text": [],
            "unrecognized": []
        }

        lines = text.splitlines()
        current_section = None
        carcols_submode = "car"

        for raw_line in lines:
            line = raw_line.strip().lstrip('\ufeff')
            if not line:
                continue

            # Check for descriptive shopping instruction (e.g. 'add this to shopping.dat "section CarMods"...')
            shop_instr = RE_SHOPPING_INSTRUCTION.search(line)
            if shop_instr and not self._is_shopping_carmods_line(line) and not self._is_shopping_item_line(line):
                current_section = "shopping_dat"
                result["shopping_dat"].append(f"section {shop_instr.group(1)}")
                continue

            # Track 1.A: Detect standalone section header first
            header_match = RE_SECTION_HEADER.match(line)
            if header_match:
                tag = header_match.group(1).lower()
                if "veh_mods" in tag or tag in ("obj", "objs"):
                    current_section = "veh_mods_ide"
                elif "ide" in tag:
                    current_section = "vehicles_ide"
                elif "handling" in tag:
                    current_section = "handling_cfg"
                elif "carcols" in tag:
                    current_section = "carcols_dat"
                    carcols_submode = "car"
                elif "shopping" in tag:
                    current_section = "shopping_dat"
                elif "section" in tag and "carmod" in tag:
                    current_section = "shopping_dat"
                    result["shopping_dat"].append(line)
                elif "carmods" in tag:
                    current_section = "carmods_dat"
                elif "audio" in tag:
                    current_section = "vehicle_audio"
                elif "special" in tag:
                    current_section = "special_features"
                elif "fxt" in tag or "gxt" in tag or "text" in tag or "name" in tag:
                    current_section = "fxt_text"
                continue

            # Track 1.B: Detect inline section header on same line (e.g. "#handling: PREVION 1350.0 ...")
            inline_match = RE_INLINE_HEADER.match(line)
            if inline_match:
                data_candidate = inline_match.group(2).strip()
                # Must contain actual alphanumeric characters
                if re.search(r'[a-zA-Z0-9]', data_candidate):
                    tag = inline_match.group(1).lower()
                    if "veh_mods" in tag or tag in ("obj", "objs"):
                        current_section = "veh_mods_ide"
                    elif "ide" in tag:
                        current_section = "vehicles_ide"
                    elif "handling" in tag:
                        current_section = "handling_cfg"
                    elif "carcols" in tag:
                        current_section = "carcols_dat"
                        carcols_submode = "car"
                    elif "shopping" in tag:
                        current_section = "shopping_dat"
                    elif "section" in tag and "carmod" in tag:
                        current_section = "shopping_dat"
                        result["shopping_dat"].append(line)
                    elif "carmods" in tag:
                        current_section = "carmods_dat"
                    elif "audio" in tag:
                        current_section = "vehicle_audio"
                    elif "special" in tag:
                        current_section = "special_features"
                    elif "fxt" in tag or "gxt" in tag or "text" in tag or "name" in tag:
                        current_section = "fxt_text"
                    
                    line = data_candidate

            # Handle sub-modes inside carcols_dat (e.g. "car4", "car", "end")
            if current_section == "carcols_dat":
                low_check = line.strip().lower()
                if low_check == "car4":
                    carcols_submode = "car4"
                    continue
                elif low_check in ("car", "col"):
                    carcols_submode = "car"
                    continue
                elif low_check == "end":
                    carcols_submode = "car"
                    current_section = None
                    continue

            # Ignore comment lines and divider bars
            if (line.startswith("#") or line.startswith(";") or line.startswith("//")) and not inline_match:
                # Check if this comment line is actually a commented data line (e.g. "; PREVION 1350.0 ...")
                uncommented = re.sub(r'^[#;//\s]+', '', line).strip().lstrip('\ufeff')
                if self._is_handling_line(uncommented):
                    line = uncommented
                elif self._is_veh_mod_line(uncommented):
                    line = uncommented
                elif self._is_ide_line(uncommented):
                    line = uncommented
                elif self._is_carcols_line(uncommented):
                    line = uncommented
                elif self._is_carmods_line(uncommented):
                    line = uncommented
                elif self._is_audio_line(uncommented):
                    line = uncommented
                elif self._is_shopping_carmods_line(uncommented):
                    line = uncommented
                elif self._is_shopping_item_line(uncommented):
                    line = uncommented
                else:
                    continue

            if current_section == "handling_cfg" and RE_HANDLING_COMMENT_HEADER.search(line):
                continue
            if line.startswith("---") or line.startswith("===") or line.startswith("***"):
                continue

            categorized = False

            # Track 2: Direct heuristic check first to avoid cross-contamination
            if self._is_handling_line(line):
                result["handling_cfg"].append(line)
                categorized = True
            elif self._is_veh_mod_line(line):
                result["veh_mods_ide"].append(line)
                categorized = True
            elif self._is_ide_line(line):
                result["vehicles_ide"].append(normalize_ide_line(line))
                categorized = True
            elif self._is_carcols_line(line):
                c_line = line
                if carcols_submode == "car4" and not c_line.lower().startswith("car4"):
                    c_line = f"car4 {c_line}"
                result["carcols_dat"].append(c_line)
                categorized = True
            elif self._is_carmods_line(line):
                result["carmods_dat"].append(line)
                categorized = True
            elif self._is_shopping_carmods_line(line):
                result["shopping_dat"].append(line)
                categorized = True
            elif self._is_shopping_item_line(line):
                result["shopping_dat"].append(line)
                categorized = True
            elif self._is_audio_line(line):
                result["vehicle_audio"].append(line)
                categorized = True
            elif self._is_special_feature_line(line):
                result["special_features"].append(line)
                categorized = True
            elif self._is_fxt_line(line):
                result["fxt_text"].append(line)
                categorized = True

            # If not heuristically categorized but inside an explicit section:
            if not categorized and current_section:
                if current_section == "shopping_dat":
                    low_s = line.strip().lower()
                    if low_s.startswith("section carmod") or low_s.startswith("section  carmod"):
                        result[current_section].append(line)
                        categorized = True
                    elif low_s.startswith("type carmods"):
                        categorized = True
                    elif low_s == "end":
                        result[current_section].append(line)
                        categorized = True
                    elif self._is_shopping_carmods_line(line) or self._is_shopping_item_line(line):
                        result[current_section].append(line)
                        categorized = True
                    elif re.match(r'^[#;//\s]*\(.*?\)\s*$', line):
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "carmods_dat":
                    if self._is_carmods_line(line) or line.strip().lower() in ("mods", "link", "end"):
                        result[current_section].append(line)
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "veh_mods_ide":
                    if line.strip().lower() == "end":
                        current_section = None
                        categorized = True
                    elif line.strip().lower() in ("obj", "objs"):
                        categorized = True
                    elif self._is_veh_mod_line(line):
                        result[current_section].append(line)
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "handling_cfg":
                    if self._is_handling_line(line):
                        result[current_section].append(line)
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "vehicles_ide":
                    if self._is_ide_line(line) or line.strip().lower() in ("cars", "end"):
                        result[current_section].append(normalize_ide_line(line))
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "carcols_dat":
                    if self._is_carcols_line(line) or line.strip().lower() in ("car", "car4", "end"):
                        c_line = line
                        if carcols_submode == "car4" and not c_line.lower().startswith("car4"):
                            c_line = f"car4 {c_line}"
                        result[current_section].append(c_line)
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "fxt_text":
                    if self._is_fxt_line(line):
                        result[current_section].append(line)
                        categorized = True
                    else:
                        current_section = None
                elif current_section == "vehicle_audio":
                    if self._is_audio_line(line):
                        result[current_section].append(line)
                        categorized = True
                    else:
                        current_section = None
                else:
                    result[current_section].append(line)
                    categorized = True

            if not categorized:
                result["unrecognized"].append(line)

        return result

    def _is_handling_line(self, line: str) -> bool:
        """
        Robust heuristic for handling.cfg lines (with or without section headers).
        Matches: [!|$|%]IDENTIFIER mass turn_mass ... [F|R|4] [P|D|E] ...
        Case-insensitive, supports lowercase/uppercase/mixed-case model names.
        """
        clean = line.strip().lstrip('\ufeff')
        clean = clean.split(';')[0].split('//')[0].split('#')[0].strip()
        if not clean:
            return False
        is_prefixed = False
        if clean and clean[0] in ("!", "$", "%"):
            is_prefixed = True
            clean = clean[1:].strip()
        parts = clean.split()

        # Exclude column header comments (e.g. "mass turnmass drag ...")
        if RE_HANDLING_COMMENT_HEADER.search(clean):
            return False

        if is_prefixed:
            # Secondary physics line (! bike ~15 cols, $ flying ~21 cols, % boat ~14 cols)
            if len(parts) < 10 or len(parts) > 30:
                return False
            ident = parts[0]
            if not re.match(r'^[A-Za-z0-9_]{2,20}$', ident):
                return False
            num_count = 0
            for p in parts[1:]:
                try:
                    float(p)
                    num_count += 1
                except ValueError:
                    pass
            return num_count >= (len(parts) - 2)

        if len(parts) < 25:
            return False

        # Exclude column header comments (e.g. "mass turnmass drag ...")
        if RE_HANDLING_COMMENT_HEADER.search(clean):
            return False

        # Identifier: 2-20 alphanumeric characters or underscores
        ident = parts[0]
        if not re.match(r'^[A-Za-z0-9_]{2,20}$', ident):
            return False

        # Find drive type [FR4] and engine type [PDE] (case-insensitive)
        drive_idx = -1
        for i in range(10, min(25, len(parts) - 1)):
            if parts[i].upper() in ("F", "R", "4") and parts[i + 1].upper() in ("P", "D", "E"):
                drive_idx = i
                break

        if drive_idx == -1:
            return False

        # Ensure parts before drive_idx are numbers
        num_count = 0
        for p in parts[1:drive_idx]:
            try:
                float(p)
                num_count += 1
            except ValueError:
                pass

        return num_count >= 8

    def _is_veh_mod_line(self, line: str) -> bool:
        """
        Robust heuristic for veh_mods.ide lines (ID, ModelName, TxdName, DrawDist, Flags).
        Matches: 11735, exh_a_zr, zr350, 100, 2097152
                 1000, spoiler1, generic, 100, 2097152
        """
        clean = line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        if clean.lower() in ("obj", "objs", "end"):
            return False
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) != 5:
            return False

        # Token 0: numeric ID
        if not parts[0].isdigit():
            return False

        # Token 1: part name
        part_name = parts[1].lower()
        if not re.match(r'^[a-z0-9_]{2,28}$', part_name):
            return False

        # Token 2: txd name
        txd_name = parts[2].lower()
        if not re.match(r'^[a-z0-9_]{2,28}$', txd_name):
            return False

        # Token 3: draw distance
        try:
            float(parts[3])
        except ValueError:
            return False

        # Token 4: flags
        if not parts[4].isdigit():
            return False

        return True

    def _is_ide_line(self, line: str) -> bool:
        """
        Robust heuristic for vehicles.ide lines.
        Matches: ID, model, txd, type(car|bike|heli|...), handling_id, ...
        The first column only needs to be numeric for a final ID; anything
        else (empty, [YOUR ID], XXXX, ???, N/A, -1, ...) is treated as a
        "to be assigned" placeholder. The line SHAPE decides, so unknown
        placeholder styles can never block reading or ID assignment.
        """
        clean = line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        clean = normalize_ide_line(clean)
        parts = [p.strip() for p in clean.split(",")]
        while parts and parts[-1] == "":
            parts.pop()
        if len(parts) < 8:
            return False

        # Second column must look like a vehicle model code
        if not re.match(r'^[A-Za-z0-9_]{2,20}$', parts[1]):
            return False

        veh_type = parts[3].lower()
        if veh_type not in VALID_IDE_TYPES:
            return False

        return True

    def _is_carcols_line(self, line: str) -> bool:
        """
        Robust heuristic for carcols.dat lines:
        Format: model, c1, c2, c3, c4... or model, c1,c2, c1,c2...
        First item is vehicle model name, all subsequent tokens are integer color indices (0-255).
        """
        clean = line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        if clean.lower().startswith("car4"):
            clean = clean[4:].strip()
        if clean.lower().startswith("car"):
            clean = clean[3:].strip()
        if not clean:
            return False

        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) < 2:
            return False

        model_candidate = parts[0].strip().lower()
        if not re.match(r'^[a-z0-9_]{2,20}$', model_candidate) or model_candidate.isdigit():
            return False

        # Gather all color numbers from the rest of the parts
        color_nums = []
        for p in parts[1:]:
            sub_tokens = p.split()
            for st in sub_tokens:
                if not st.isdigit():
                    return False
                val = int(st)
                if val < 0 or val > 255:
                    return False
                color_nums.append(val)

        return len(color_nums) >= 2

    def _is_carmods_line(self, line: str) -> bool:
        """
        Robust heuristic for carmods.dat lines:
        Format: model, part1, part2, ... or link: wg_l_..., wg_r_...
        """
        clean = line.split('#')[0].split(';')[0].split('//')[0].strip()
        if clean.lower() in ("mods", "link", "end"):
            return False

        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) < 2:
            return False

        # Mirror link line: e.g. wg_l_..., wg_r_...
        if len(parts) == 2 and any(parts[0].lower().startswith(p) for p in KNOWN_TUNING_PREFIXES):
            return bool(re.match(r'^[a-z0-9_]{2,24}$', parts[0].lower())) and bool(re.match(r'^[a-z0-9_]{2,24}$', parts[1].lower()))

        model_cand = parts[0].lower()
        if not re.match(r'^[a-z0-9_]{2,20}$', model_cand) or model_cand.isdigit():
            return False

        part_names = parts[1:]
        # Every part in a carmods line must be a valid single identifier without spaces or punctuation
        if not all(re.match(r'^[a-z0-9_]{2,24}$', p.lower()) for p in part_names):
            return False

        # Check known tuning prefixes or keywords
        has_known_prefix = any(
            any(pname.lower().startswith(pfx) for pfx in KNOWN_TUNING_PREFIXES)
            for pname in part_names
        )
        is_known_vehicle = model_cand in MODEL_TO_ID

        tuning_keywords = ("exhaust", "spoiler", "bumper", "hood", "bonnet", "roof", "wheel", "light", "skirt", "nitro", "exh", "fbmp", "rbmp", "wg_")
        has_tuning_keyword = any(any(kw in pname.lower() for kw in tuning_keywords) for pname in part_names)

        return is_known_vehicle or has_known_prefix or has_tuning_keyword

    def _is_fxt_line(self, line: str) -> bool:
        """
        Check if line matches FXT text entry: KEY Display Name
        e.g. 'RBER20V Schrauber 20V', 'SLASH1 Slamin Ornament', 'SLAMVAN 1953 Slamvan Custom'
        Deliberately strict so misplaced handling/audio/carmods lines (numeric
        soup with single stray letters like 'R' or 'C04000') are never taken
        for display names.
        """
        line = line.strip().lstrip('\ufeff')
        if "," in line or ";" in line or line.startswith("---"):
            return False
        tokens = line.split()
        if len(tokens) > 12:
            return False
        parts = line.split(None, 1)
        if len(parts) == 2:
            key, val = parts[0], parts[1].strip()
            if re.match(r'^[A-Z0-9_]{2,8}$', key):
                # Display name must contain a real word (2+ consecutive
                # letters); bare numbers / single letters are config data.
                if re.search(r'[A-Za-z]{2,}', val) and not val.lower().startswith("car4"):
                    return True
        return False

    def _is_audio_line(self, line: str) -> bool:
        """
        Check if line matches Fastman92 vehicleAudioSettings format (Heuristic Syntax Fingerprinting).
        Format: <model> <audio_type:0-10> <bank_a:int> <bank_b:int> <bass_set:int> <bass_fac:float> <pitch:float> ...
        Characteristics:
        - 10 to 16 columns
        - Strictly NO commas (audio lines never use commas)
        - Model name is a valid alphanumeric identifier (not purely numeric)
        - Audio type is an integer between 0 and 10
        - Bank A and Bank B are integers
        - Bass setting is an integer
        - Bass factor and pitch are valid floats
        """
        clean = line.split(';')[0].split('#')[0].split('//')[0].strip()
        if not clean or ',' in clean:
            return False
        parts = clean.split()
        if len(parts) < 10 or len(parts) > 16:
            return False
        # Model name must be a valid identifier and not purely numbers
        if not re.fullmatch(r"[A-Za-z0-9_]+", parts[0]) or parts[0].isdigit():
            return False
        try:
            v_type = int(parts[1])
            if not (0 <= v_type <= 10):
                return False
            # Bank A, Bank B
            int(parts[2])
            int(parts[3])
            # BassSetting
            int(parts[4])
            # BassFactor, Pitch
            float(parts[5])
            float(parts[6])
            return True
        except (ValueError, IndexError):
            return False

    def _is_special_feature_line(self, line: str) -> bool:
        """Check if line matches model_special_features.dat: 'uranus zr350'"""
        parts = line.split()
        if len(parts) == 2:
            target = parts[1].lower()
            return target in ("zr350", "sandking", "copcarla", "copcarsf", "copcarvg", "fbiranch", "taxi", "cabbie", "securica", "ambulan")
        return False

    def _is_shopping_carmods_line(self, line: str) -> bool:
        """
        Check if line matches shopping.dat section CarMods price line:
        Format: <part_name> <nametag> respect <r:int> sexy <s:int> <price:int>
        e.g. 'exh_a_zr    ZR2AE    respect 0   sexy 0   850   # END OF ZR350'
             'exh_lr_tah1 TAHEX1   respect 0   sexy 0   2500  #LOWRIDERS MOD'
        """
        clean = line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        if not clean:
            return False
        parts = clean.split()
        if len(parts) < 7:
            return False
        if not re.match(r'^[a-zA-Z0-9_]{2,28}$', parts[0]):
            return False
        if not re.match(r'^[a-zA-Z0-9_]{2,16}$', parts[1]):
            return False
        resp_found = False
        sexy_found = False
        for i in range(2, len(parts) - 1):
            if parts[i].lower() == "respect" and parts[i + 1].isdigit():
                resp_found = True
            elif parts[i].lower() == "sexy" and parts[i + 1].isdigit():
                sexy_found = True
        if not (resp_found and sexy_found):
            return False
        return parts[-1].isdigit()

    def _is_shopping_item_line(self, line: str) -> bool:
        """
        Check if line matches shopping.dat workshop item line:
        Format: item <part_name>
        e.g. 'item exh_a_zr', 'item exh_lr_tah1 #LOWRIDERS MOD'
        """
        clean = line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        parts = clean.split()
        if len(parts) == 2 and parts[0].lower() == "item":
            return bool(re.match(r'^[a-zA-Z0-9_]{2,28}$', parts[1]))
        return False

    def decompose_shopping(self, raw_lines: List[str]) -> Dict[str, Any]:
        """
        Decompose shopping.dat lines from readme/mod files.
        Extracts price/nametag definitions for section CarMods,
        and workshop assignments for section carmod1/2/3.
        """
        carmods_entries = []
        workshops = {}
        current_shop_sec = "carmods"

        for raw_line in raw_lines:
            s = raw_line.strip()
            if not s:
                continue

            sec_match = re.search(r'(?i)section\s+(carmods?|carmod[1-3])\b', s)
            if sec_match:
                tag = sec_match.group(1).lower()
                if "carmod" in tag and tag[-1].isdigit():
                    current_shop_sec = f"carmod{tag[-1]}"
                else:
                    current_shop_sec = "carmods"
                continue

            clean = s.split('#')[0].split(';')[0].split('//')[0].strip()
            if not clean:
                continue

            if self._is_shopping_carmods_line(s):
                parts = clean.split()
                try:
                    pname = parts[0].lower()
                    nametag = parts[1].upper()
                    resp_idx = -1
                    sexy_idx = -1
                    for i in range(2, len(parts) - 1):
                        if parts[i].lower() == "respect":
                            resp_idx = i
                        elif parts[i].lower() == "sexy":
                            sexy_idx = i

                    respect = int(parts[resp_idx + 1]) if resp_idx != -1 else 0
                    sexy = int(parts[sexy_idx + 1]) if sexy_idx != -1 else 0
                    price = int(parts[-1])

                    comment = ""
                    if "#" in s:
                        comment = "#" + s.split("#", 1)[1].rstrip()

                    carmods_entries.append({
                        "part_name": pname,
                        "nametag": nametag,
                        "respect": respect,
                        "sexy": sexy,
                        "price": price,
                        "comment": comment,
                        "raw": s
                    })
                except Exception:
                    pass
                continue

            if self._is_shopping_item_line(s):
                parts = clean.split()
                if len(parts) >= 2 and parts[0].lower() == "item":
                    pname = parts[1].lower()
                    target_sec = current_shop_sec if current_shop_sec.startswith("carmod") and current_shop_sec[-1].isdigit() else "carmod3"
                    if target_sec not in workshops:
                        workshops[target_sec] = []
                    if pname not in workshops[target_sec]:
                        workshops[target_sec].append(pname)
                continue

        return {
            "carmods": carmods_entries,
            "workshops": workshops
        }

    # ---------------- Decomposition into UI Friendly Structures ----------------

    def decompose_handling(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """Decompose a handling.cfg line into human-readable parameters."""
        raw_clean = raw_line.strip().lstrip('\ufeff')
        clean = raw_clean.split(';')[0].split('//')[0].split('#')[0].strip()
        if not clean:
            return None
        prefix = ""
        prefix_spaced = False
        if clean[0] in ("!", "$", "%"):
            prefix = clean[0]
            rest = clean[1:]
            if rest and rest[0].isspace():
                prefix_spaced = True
            clean = rest.strip()
        parts = clean.split()
        if prefix and 10 <= len(parts) < 25:
            vals = []
            for p in parts[1:]:
                try:
                    vals.append(float(p))
                except ValueError:
                    pass
            return {
                "valid": True,
                "raw": raw_line,
                "clean_raw": clean,
                "prefix": prefix,
                "prefix_spaced": prefix_spaced,
                "identifier": parts[0].upper(),
                "is_secondary": True,
                "values": vals
            }

        if len(parts) < 25:
            return None

        try:
            drive_type_map = {"F": "FWD", "R": "RWD", "4": "AWD"}
            engine_type_map = {"P": "Petrol", "D": "Diesel", "E": "Electric"}

            # Find drive and engine type index
            drive_idx = -1
            for i in range(10, min(25, len(parts) - 1)):
                if parts[i].upper() in ("F", "R", "4") and parts[i + 1].upper() in ("P", "D", "E"):
                    drive_idx = i
                    break

            if drive_idx == -1:
                return {"raw": raw_line, "valid": False}

            d_type = parts[drive_idx].upper()
            e_type = parts[drive_idx + 1].upper()

            res_dict = {
                "valid": True,
                "raw": raw_line,
                "clean_raw": clean,
                "prefix": prefix,
                "prefix_spaced": prefix_spaced,
                "identifier": parts[0].upper(),
                "mass_kg": float(parts[1]),
                "turn_mass": float(parts[2]),
                "drag_mult": float(parts[3]),
                "center_of_mass": [float(parts[4]), float(parts[5]), float(parts[6])],
                "submerged_percent": int(parts[7]) if parts[7].isdigit() else parts[7],
                "traction_mult": float(parts[8]),
                "traction_loss": float(parts[9]),
                "traction_bias": float(parts[10]),
                "gears": int(parts[drive_idx - 4]),
                "max_speed_kmh": float(parts[drive_idx - 3]),
                "acceleration": float(parts[drive_idx - 2]),
                "engine_inertia": float(parts[drive_idx - 1]),
                "drive_type": d_type,
                "drive_type_label": drive_type_map.get(d_type, d_type),
                "engine_type": e_type,
                "engine_type_label": engine_type_map.get(e_type, e_type),
                "brake_decel": float(parts[drive_idx + 2]),
                "brake_bias": float(parts[drive_idx + 3]),
                "steering_lock_deg": float(parts[drive_idx + 5]),
            }
            if len(parts) > drive_idx + 6:
                try:
                    res_dict["suspension_force"] = float(parts[drive_idx + 6])
                except Exception:
                    pass
            if len(parts) > drive_idx + 7:
                try:
                    res_dict["suspension_damping"] = float(parts[drive_idx + 7])
                except Exception:
                    pass
            if len(parts) > drive_idx + 8:
                try:
                    res_dict["suspension_high_speed_damping"] = float(parts[drive_idx + 8])
                except Exception:
                    pass
            if len(parts) > drive_idx + 9:
                try:
                    res_dict["suspension_upper_limit"] = float(parts[drive_idx + 9])
                except Exception:
                    pass
            if len(parts) > drive_idx + 10:
                try:
                    res_dict["suspension_lower_limit"] = float(parts[drive_idx + 10])
                except Exception:
                    pass
            if len(parts) > drive_idx + 11:
                try:
                    res_dict["suspension_bias"] = float(parts[drive_idx + 11])
                except Exception:
                    pass
            if len(parts) > drive_idx + 12:
                try:
                    res_dict["suspension_anti_dive"] = float(parts[drive_idx + 12])
                except Exception:
                    pass
            if len(parts) > drive_idx + 14:
                try:
                    res_dict["collision_damage_multiplier"] = float(parts[drive_idx + 14])
                except Exception:
                    pass
            if len(parts) > drive_idx + 15:
                try:
                    res_dict["monetary_value"] = int(float(parts[drive_idx + 15]))
                except Exception:
                    pass
            return res_dict
        except Exception:
            return {"raw": raw_line, "valid": False}

    def decompose_ide(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """Decompose vehicles.ide line (non-numeric first column -> id None)."""
        clean = raw_line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        clean = normalize_ide_line(clean)
        parts = [p.strip() for p in clean.split(",")]
        while parts and parts[-1] == "":
            parts.pop()
        if len(parts) < 8:
            return None
        if not re.match(r'^[A-Za-z0-9_]{2,20}$', parts[1]):
            return None
        if parts[3].lower() not in VALID_IDE_TYPES:
            return None

        try:
            try:
                _v = int(parts[0]) if parts[0] else None
                ide_id = _v if (_v is not None and 100 <= _v <= 65535) else None
            except (ValueError, TypeError):
                ide_id = None
            return {
                "raw": clean,
                "id": ide_id,
                "model_name": parts[1].lower(),
                "txd_name": parts[2].lower(),
                "type": parts[3].lower(),
                "vehicle_type": parts[3].lower(),
                "handling_id": parts[4].upper(),
                "game_name": parts[5],
                "anim": parts[6] if len(parts) > 6 else "null",
                "class": parts[7] if len(parts) > 7 else "normal",
                "frequency": int(parts[8]) if len(parts) > 8 and parts[8].isdigit() else 5,
                "flags": int(parts[9]) if len(parts) > 9 and parts[9].isdigit() else 0,
                "wheel_scale": float(parts[12]) if len(parts) > 12 else 0.7,
                "wheel_scale_front": float(parts[12]) if len(parts) > 12 else 0.7,
                "wheel_scale_rear": float(parts[13]) if len(parts) > 13 else 0.7,
            }
        except Exception:
            return {"raw": raw_line, "valid": False}

    def decompose_veh_mod(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """Decompose veh_mods.ide line (ID, ModelName, TxdName, DrawDist, Flags)."""
        clean = raw_line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 5 and parts[0].isdigit() and parts[4].isdigit():
            try:
                return {
                    "id": int(parts[0]),
                    "part_name": parts[1].lower(),
                    "txd_name": parts[2].lower(),
                    "draw_dist": float(parts[3]),
                    "flags": int(parts[4]),
                    "raw": raw_line.strip()
                }
            except Exception:
                return None
        return None

    def decompose_carcols(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """Decompose carcols.dat line into color sets with hex previews (supporting both 2-color and 4-color car4)."""
        clean = raw_line.strip().lstrip('\ufeff').split('#')[0].split(';')[0].split('//')[0].strip()
        is_car4 = False
        if clean.lower().startswith("car4"):
            is_car4 = True
            clean = clean[4:].strip().lstrip(",").strip()
        elif clean.lower().startswith("car"):
            clean = clean[3:].strip().lstrip(",").strip()

        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) < 2:
            return None

        model_name = parts[0].lower()
        color_ids = []
        for p in parts[1:]:
            for token in p.split():
                if token.isdigit():
                    color_ids.append(int(token))

        if not color_ids:
            return None

        stride = 4 if is_car4 else 2
        color_sets = []
        color_pairs = []
        for i in range(0, len(color_ids) - (stride - 1), stride):
            c1 = color_ids[i]
            c2 = color_ids[i + 1]
            entry = {
                "c1": c1,
                "hex1": CARCOLS_PALETTE.get(c1, "#888888"),
                "c2": c2,
                "hex2": CARCOLS_PALETTE.get(c2, "#888888")
            }
            if stride == 4:
                c3 = color_ids[i + 2]
                c4 = color_ids[i + 3]
                entry["c3"] = c3
                entry["hex3"] = CARCOLS_PALETTE.get(c3, "#888888")
                entry["c4"] = c4
                entry["hex4"] = CARCOLS_PALETTE.get(c4, "#888888")
            color_sets.append(entry)
            color_pairs.append(entry)

        return {
            "model_name": model_name,
            "raw": raw_line,
            "is_car4": is_car4,
            "color_pairs": color_pairs,
            "color_sets": color_sets,
            "count": len(color_sets)
        }

    def decompose_carmods(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """Decompose carmods.dat line into categorized tuning parts."""
        clean = raw_line.split('#')[0].split(';')[0].split('//')[0].strip()
        if clean.lower() in ("mods", "link", "end"):
            return None

        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) < 2:
            return None

        model_name = parts[0].lower()
        if not re.match(r'^[a-z0-9_]{2,20}$', model_name) or model_name.isdigit():
            return None

        valid_part_names = []
        categorized_parts = []
        for raw_p in parts[1:]:
            p_clean = raw_p.strip().lower()
            if not re.match(r'^[a-z0-9_]{2,24}$', p_clean):
                continue
            valid_part_names.append(p_clean)
            matched_info = None
            for prefix, info in TUNING_PREFIX_INFO.items():
                if p_clean.startswith(prefix):
                    matched_info = info
                    break
            categorized_parts.append({
                "part_name": p_clean,
                "category": matched_info["category"] if matched_info else "other",
                "name_cn": matched_info["name_en"] if matched_info else "Miscellaneous",
                "name_en": matched_info.get("name_en", "Other") if matched_info else "Other",
                "default_price": matched_info["default_price"] if matched_info else 300
            })

        if not valid_part_names:
            return None

        return {
            "model_name": model_name,
            "raw": raw_line,
            "parts": categorized_parts,
            "part_names": valid_part_names,
            "total_parts": len(categorized_parts)
        }

    def decompose_fxt(self, raw_line: str) -> Optional[Dict[str, Any]]:
        """Decompose FXT line into GXT Key and Display Name."""
        raw_clean = raw_line.strip().lstrip('\ufeff')
        if not self._is_fxt_line(raw_clean):
            return None
        parts = raw_clean.split(None, 1)
        if len(parts) == 2:
            key = parts[0].upper()
            name = parts[1].strip()
            if (name.startswith('"') and name.endswith('"')) or (name.startswith("'") and name.endswith("'")):
                name = name[1:-1].strip()
            return {"key": key, "name": name, "raw": raw_clean}
        return None

    # ---------------- Full Folder / Mod Inspector ----------------

    def inspect_mod_directory(self, mod_dir: str) -> Dict[str, Any]:
        """
        Thoroughly inspect an installed mod folder or downloaded mod pack.
        Gathers DFF, TXD, FXT files, reads readme/txt files, and decomposes configs.
        """
        if not os.path.isdir(mod_dir):
            return {"success": False, "error": f"Directory does not exist: {mod_dir}"}

        mod_name = os.path.basename(os.path.normpath(mod_dir))
        dff_files = []
        txd_files = []
        fxt_files = []
        txt_files = []
        tuning_dffs = []

        for root, dirs, files in os.walk(mod_dir):
            for file in files:
                f_lower = file.lower()
                rel_path = os.path.relpath(os.path.join(root, file), mod_dir)

                if f_lower.endswith(".dff"):
                    # Check if tuning part
                    is_tuning = any(f_lower.startswith(p) for p in KNOWN_TUNING_PREFIXES) or "tuning" in root.lower()
                    if is_tuning:
                        tuning_dffs.append({"name": file, "rel_path": rel_path, "size": os.path.getsize(os.path.join(root, file))})
                    else:
                        dff_files.append({"name": file, "rel_path": rel_path, "size": os.path.getsize(os.path.join(root, file))})
                elif f_lower.endswith(".txd"):
                    txd_files.append({"name": file, "rel_path": rel_path, "size": os.path.getsize(os.path.join(root, file))})
                elif f_lower.endswith(".fxt"):
                    # Read FXT lines using multi-encoding safe reader
                    fxt_content = read_text_file_safe(os.path.join(root, file)).strip()
                    fxt_files.append({"name": file, "content": fxt_content})
                elif f_lower.endswith((".txt", ".readme", ".dat", ".cfg", ".ide", ".md", ".me", ".doc")) or f_lower in ("vehicles.ide.source",):
                    txt_files.append({"name": file, "path": os.path.join(root, file)})

        # Aggregate text contents
        combined_text = ""
        for tf in txt_files:
            file_text = read_text_file_safe(tf["path"])
            if file_text:
                combined_text += f"\n\n--- FILE: {tf['name']} ---\n" + file_text

        parsed_raw = self.parse_text_content(combined_text)

        # Decompose
        handling_decomp = [self.decompose_handling(line) for line in parsed_raw["handling_cfg"]]
        ide_decomp = [self.decompose_ide(line) for line in parsed_raw["vehicles_ide"]]
        carcols_decomp = [self.decompose_carcols(line) for line in parsed_raw["carcols_dat"]]
        carmods_decomp = [self.decompose_carmods(line) for line in parsed_raw["carmods_dat"]]
        veh_mods_decomp = [self.decompose_veh_mod(line) for line in parsed_raw.get("veh_mods_ide", [])]
        veh_mods_decomp = [v for v in veh_mods_decomp if v]
        shopping_decomp = self.decompose_shopping(parsed_raw.get("shopping_dat", []))

        author_tuning_ides = {}
        custom_tuning_ids = {}
        for vm in veh_mods_decomp:
            pname = vm["part_name"].lower()
            author_tuning_ides[pname] = vm
            custom_tuning_ids[pname] = vm["id"]
        
        # FXT display names: on-disk .fxt files are authoritative (they are
        # what the game loads), readme-scraped lines only fill gaps. This
        # ordering also prevents a misclassified readme line from shadowing
        # the real entry.
        fxt_decomp = []
        for fxt_f in fxt_files:
            for l in fxt_f.get("content", "").splitlines():
                df = self.decompose_fxt(l)
                if df and not any(x and x["key"] == df["key"] for x in fxt_decomp):
                    fxt_decomp.append(df)
        for line in parsed_raw["fxt_text"]:
            df = self.decompose_fxt(line)
            if df and not any(x and x["key"] == df["key"] for x in fxt_decomp):
                fxt_decomp.append(df)

        # Determine target replaced vehicle(s)
        # Determine target replaced vehicle(s) or addon vehicle(s)
        target_vehicles = []
        seen_models = set()

        # Build quick lookups from parsed IDE and FXT
        ide_by_model = {}
        for ide in ide_decomp:
            if ide and ide.get("model_name"):
                ide_by_model[ide["model_name"].lower()] = ide

        fxt_by_key = {}
        for f in fxt_decomp:
            if f and f.get("key"):
                fxt_by_key[f["key"].upper()] = f.get("name", "")

        # 1. From primary DFF filenames
        for dff in dff_files:
            mname = os.path.splitext(dff["name"])[0].lower()
            if mname in seen_models:
                continue

            if mname in MODEL_TO_ID:
                seen_models.add(mname)
                v_info = VANILLA_VEHICLES[MODEL_TO_ID[mname]]
                target_vehicles.append({
                    "model": mname,
                    "id": MODEL_TO_ID[mname],
                    "name": v_info["name"],
                    "type": v_info.get("type", "car"),
                    "shop": v_info.get("shop", "none"),
                    "dff_name": dff["name"],
                    "dff_size": dff["size"],
                    "is_addon": False
                })
            else:
                # Custom DFF: Check if it corresponds to an Addon vehicle
                seen_models.add(mname)
                matched_ide = ide_by_model.get(mname)
                addon_id = matched_ide["id"] if matched_ide else None
                veh_type = matched_ide["type"] if matched_ide else "car"
                game_name = matched_ide.get("game_name", mname.upper()) if matched_ide else mname.upper()
                fxt_name = fxt_by_key.get(game_name.upper()) or fxt_by_key.get(mname.upper()) or mname.capitalize()

                target_vehicles.append({
                    "model": mname,
                    "id": addon_id,
                    "name": fxt_name,
                    "type": veh_type,
                    "shop": "none",
                    "dff_name": dff["name"],
                    "dff_size": dff["size"],
                    "is_addon": True
                })

        # 2. From IDE or handling if any extra or if no DFF matched
        for ide in ide_decomp:
            if not ide or not ide.get("model_name"):
                continue
            mname = ide["model_name"].lower()
            if mname in seen_models:
                continue

            seen_models.add(mname)
            if mname in MODEL_TO_ID:
                v_info = VANILLA_VEHICLES[MODEL_TO_ID[mname]]
                target_vehicles.append({
                    "model": mname,
                    "id": MODEL_TO_ID[mname],
                    "name": v_info["name"],
                    "type": v_info.get("type", "car"),
                    "shop": v_info.get("shop", "none"),
                    "dff_name": f"{mname}.dff",
                    "dff_size": 0,
                    "is_addon": False
                })
            else:
                addon_id = ide.get("id")
                veh_type = ide.get("type", "car")
                game_name = ide.get("game_name", mname.upper())
                fxt_name = fxt_by_key.get(game_name.upper()) or fxt_by_key.get(mname.upper()) or mname.capitalize()
                target_vehicles.append({
                    "model": mname,
                    "id": addon_id,
                    "name": fxt_name,
                    "type": veh_type,
                    "shop": "none",
                    "dff_name": f"{mname}.dff",
                    "dff_size": 0,
                    "is_addon": True
                })

        for h in handling_decomp:
            if not h or not h.get("identifier"):
                continue
            mname = h["identifier"].lower()
            if mname in seen_models:
                continue

            seen_models.add(mname)
            if mname in MODEL_TO_ID:
                v_info = VANILLA_VEHICLES[MODEL_TO_ID[mname]]
                target_vehicles.append({
                    "model": mname,
                    "id": MODEL_TO_ID[mname],
                    "name": v_info["name"],
                    "type": v_info.get("type", "car"),
                    "shop": v_info.get("shop", "none"),
                    "dff_name": f"{mname}.dff",
                    "dff_size": 0,
                    "is_addon": False
                })
            else:
                target_vehicles.append({
                    "model": mname,
                    "id": None,
                    "name": fxt_by_key.get(mname.upper(), mname.capitalize()),
                    "type": "car",
                    "shop": "none",
                    "dff_name": f"{mname}.dff",
                    "dff_size": 0,
                    "is_addon": True
                })

        # Filter out 0-byte dummy entries if real DFF entries exist
        real_dff_vehicles = [v for v in target_vehicles if v.get("dff_size", 0) > 0]
        if real_dff_vehicles:
            target_vehicles = real_dff_vehicles

        # Intelligent sorting:
        # Prioritize vehicle model that matches folder name / mod name
        mod_name_clean = mod_name.lower().replace("_", " ").replace("-", " ")
        def vehicle_priority(v):
            m = v["model"]
            vname = v.get("name", "").lower()
            if m in mod_name_clean or vname in mod_name_clean:
                return (0, m)
            if "shit" in m or "dam" in m:
                return (2, m)
            return (1, m)

        target_vehicles.sort(key=vehicle_priority)

        target_model = target_vehicles[0]["model"] if target_vehicles else None
        is_mod_addon = False
        addon_id = None
        if target_vehicles:
            first_v = target_vehicles[0]
            if first_v.get("is_addon"):
                is_mod_addon = True
                addon_id = first_v.get("id")
                target_vanilla_info = {
                    "model": first_v["model"],
                    "id": first_v["id"],
                    "name": first_v["name"],
                    "type": first_v.get("type", "car"),
                    "shop": "none",
                    "is_addon": True
                }
            else:
                target_vanilla_info = VANILLA_VEHICLES.get(first_v["id"])
        else:
            target_vanilla_info = None

        if not addon_id and ide_decomp:
            for ide in ide_decomp:
                if ide and ide.get("id"):
                    addon_id = ide["id"]
                    break

        return {
            "success": True,
            "mod_name": mod_name,
            "mod_dir": mod_dir,
            "target_model": target_model,
            "is_addon": is_mod_addon,
            "addon_id": addon_id,
            "target_vanilla": target_vanilla_info,
            "target_models": [v["model"] for v in target_vehicles],
            "target_vehicles": target_vehicles,
            "files": {
                "dff_count": len(dff_files),
                "dff_files": dff_files,
                "tuning_dff_count": len(tuning_dffs),
                "tuning_dffs": tuning_dffs,
                "txd_count": len(txd_files),
                "txd_files": txd_files,
                "fxt_files": fxt_files,
                "txt_count": len(txt_files)
            },
            "parsed": {
                "handling": handling_decomp,
                "ide": ide_decomp,
                "carcols": carcols_decomp,
                "carmods": carmods_decomp,
                "veh_mods_ide": veh_mods_decomp,
                "shopping": shopping_decomp,
                "fxt": [f for f in fxt_decomp if f],
                "fxt_text": parsed_raw["fxt_text"],
                "audio_lines": parsed_raw["vehicle_audio"],
                "special_features": parsed_raw["special_features"],
                "unrecognized_count": len(parsed_raw["unrecognized"])
            },
            "author_tuning_ides": author_tuning_ides,
            "custom_tuning_ids": custom_tuning_ids,
            "raw_text_summary": combined_text[:1000] if combined_text else ""
        }
