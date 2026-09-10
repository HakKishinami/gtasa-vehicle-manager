"""
GTASA Vehicle Mod Manager - Local HTTP API Server & Web UI Host
Runs with standard Python library (zero third-party dependencies required).
"""

import os
import sys
import json
import re
import shutil
import time
import traceback
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import threading
from typing import Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.baseline import BaselineManager, DEFAULT_DATA_FOLDER
from core.fla_manager import FLAManager, SOUND_PRESETS
from core.scanner import ModScanner
from core.parser import DualTrackParser
from core.merger import ConfigMerger
from core.installer import ModInstaller
from core.cleaner import ModCleaner
from core.mod_renamer import rename_mod_folder
from core.install_reminder import check_existing_models
from core.id_manager import IdManager
from core.atomic_io import write_text_atomic
from core.fxt_installer import update_fxt_entry
from core.vanilla_data import CARCOLS_PALETTE, SPECIAL_FEATURE_TARGETS, VANILLA_VEHICLES
from core.backup_manager import BackupManager
from core.seven_zip import get_7zip_status, SEVEN_ZIP_DOWNLOAD_URL
from core.i18n import (
    DEFAULT_LANGUAGE as I18N_DEFAULT,
    normalize_language,
    is_supported as is_supported_language,
    language_catalog,
    browse_folder_title,
    browse_file_title,
    browse_filetypes,
)

PORT = 28848
WINDOW_TITLE = "GTASA Vehicle Manager"
if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    # In onedir mode, data might be in _internal
    if not os.path.exists(os.path.join(BASE_DIR, "web")):
        alt_base = os.path.join(os.path.dirname(sys.executable), "_internal")
        if os.path.exists(os.path.join(alt_base, "web")):
            BASE_DIR = alt_base
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_DIR = os.path.join(BASE_DIR, "web")
CONFIG_PATH = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_MOD_FOLDER = "Modded Cars"
DEFAULT_ADDON_FOLDER = "Addon Cars"
DEFAULT_CARD_DENSITY = "comfortable"
VALID_CARD_DENSITIES = ("comfortable", "compact")

# The API only ever serves this machine's own UI. Requests carrying a foreign
# Host (DNS rebinding) or a foreign Origin (any page the user happens to visit)
# are refused, so a random website cannot drive the manager over 127.0.0.1.
LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
# Guard against clients that open a connection and then stall the serial server.
REQUEST_SOCKET_TIMEOUT_SECONDS = 30.0


def _authority_hostname(authority: str) -> str:
    """Hostname part of a Host header value or an Origin URL, lowercased."""
    if not authority:
        return ""
    value = str(authority).strip().lower()
    if "://" in value:
        value = urllib.parse.urlsplit(value).netloc
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[:end + 1] if end != -1 else value
    return value.split(":", 1)[0]


def _is_loopback_authority(authority: str) -> bool:
    """True when a Host/Origin authority targets the local loopback interface."""
    host = _authority_hostname(authority)
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return bool(host) and host in LOOPBACK_HOSTNAMES


def normalize_card_density(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in VALID_CARD_DENSITIES else DEFAULT_CARD_DENSITY

def load_saved_config() -> dict:
    """Load saved game path and modloader target folder from config.json."""
    cfg = {
        "game_path": "",
        "data_folder": DEFAULT_DATA_FOLDER,
        "addon_folder": DEFAULT_ADDON_FOLDER,
        "mod_folder": DEFAULT_MOD_FOLDER,
        "remember_default_path": False,
        "dismiss_fla_warning": False,
        "is_configured": False,
        "language": I18N_DEFAULT,
        "default_language": I18N_DEFAULT,
        "card_density": DEFAULT_CARD_DENSITY
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    remember = bool(saved.get("remember_default_path", False))
                    p = saved.get("game_path")
                    # Only load persisted path if explicitly saved as default and path is valid
                    if remember and p and p.strip() != "." and os.path.isdir(p):
                        cfg["game_path"] = os.path.normpath(p)
                        cfg["remember_default_path"] = True
                        cfg["is_configured"] = True
                    else:
                        cfg["game_path"] = ""
                        cfg["remember_default_path"] = False
                        cfg["is_configured"] = False

                    df = saved.get("data_folder")
                    if df:
                        cfg["data_folder"] = df.strip()
                    af = saved.get("addon_folder")
                    if af:
                        cfg["addon_folder"] = af.strip()
                    mf = saved.get("mod_folder")
                    if mf:
                        cfg["mod_folder"] = mf.strip()
                    if "dismiss_fla_warning" in saved:
                        cfg["dismiss_fla_warning"] = bool(saved["dismiss_fla_warning"])
                    if "language" in saved and is_supported_language(saved["language"]):
                        cfg["language"] = normalize_language(saved["language"])
                    if "default_language" in saved and is_supported_language(saved["default_language"]):
                        cfg["default_language"] = normalize_language(saved["default_language"])
                    if "language" not in saved:
                        cfg["language"] = cfg["default_language"]
                    if "card_density" in saved:
                        cfg["card_density"] = normalize_card_density(saved["card_density"])
        except Exception:
            pass

    # A normal language switch lasts only for this process. Ignore the last
    # session language written by older versions when restoring startup state.
    cfg["language"] = cfg["default_language"]
    cfg["candidate_path"] = cfg.get("game_path", "") if cfg.get("remember_default_path") else ""
    return cfg

def save_config(game_path: str = None, data_folder: str = None, addon_folder: str = None, mod_folder: str = None,
                remember_default_path: bool = None, dismiss_fla_warning: bool = None,
                is_configured: bool = None, language: str = None, default_language: str = None,
                card_density: str = None):
    """Save config to config.json. Only persists game_path if remember_default_path is True."""
    try:
        cfg = load_saved_config()
        if remember_default_path is not None:
            cfg["remember_default_path"] = bool(remember_default_path)

        if game_path is not None:
            clean_p = game_path.strip()
            # Only persist path if explicitly selected to save as default
            if cfg["remember_default_path"]:
                cfg["game_path"] = os.path.normpath(clean_p) if (clean_p and clean_p != ".") else ""
                cfg["is_configured"] = bool(cfg["game_path"])
            else:
                cfg["game_path"] = ""
                cfg["is_configured"] = False
        elif not cfg["remember_default_path"]:
            cfg["game_path"] = ""
            cfg["is_configured"] = False

        if is_configured is not None and cfg["remember_default_path"]:
            cfg["is_configured"] = bool(is_configured)
        elif not cfg["remember_default_path"]:
            cfg["is_configured"] = False

        if data_folder is not None:
            cfg["data_folder"] = data_folder.strip()
        if addon_folder is not None:
            cfg["addon_folder"] = addon_folder.strip()
        if mod_folder is not None:
            cfg["mod_folder"] = mod_folder.strip()
        if dismiss_fla_warning is not None:
            cfg["dismiss_fla_warning"] = bool(dismiss_fla_warning)
        if language is not None and is_supported_language(language):
            cfg["language"] = normalize_language(language)
        if default_language is not None and is_supported_language(default_language):
            cfg["default_language"] = normalize_language(default_language)
        if card_density is not None:
            cfg["card_density"] = normalize_card_density(card_density)

        save_data = {
            "game_path": cfg.get("game_path", ""),
            "data_folder": cfg.get("data_folder", DEFAULT_DATA_FOLDER),
            "addon_folder": cfg.get("addon_folder", DEFAULT_ADDON_FOLDER),
            "mod_folder": cfg.get("mod_folder", DEFAULT_MOD_FOLDER),
            "remember_default_path": cfg.get("remember_default_path", False),
            "dismiss_fla_warning": cfg.get("dismiss_fla_warning", False),
            "is_configured": cfg.get("is_configured", False),
            "language": cfg.get("language", I18N_DEFAULT),
            "default_language": cfg.get("default_language", I18N_DEFAULT),
            "card_density": cfg.get("card_density", DEFAULT_CARD_DENSITY)
        }
        write_text_atomic(CONFIG_PATH, json.dumps(save_data, ensure_ascii=False, indent=2))
    except Exception as e:
        print("Error saving config:", e)

def browse_folder_native(initial_dir: str = "", title: str = "", lang: str = "") -> str:
    """Open a native Windows directory picker dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        use_lang = normalize_language(lang or globals().get("LANGUAGE") or I18N_DEFAULT)
        if not title:
            title = browse_folder_title(use_lang)
        folder = filedialog.askdirectory(
            initialdir=initial_dir if (initial_dir and os.path.exists(initial_dir)) else "C:\\",
            title=title
        )
        root.destroy()
        return os.path.normpath(folder) if folder else ""
    except Exception as e:
        print("Folder picker error:", e)
        return ""

def browse_file_native(initial_dir: str = "", title: str = "", lang: str = "") -> str:
    """Open a native Windows file picker dialog for mod files or archives."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        use_lang = normalize_language(lang or globals().get("LANGUAGE") or I18N_DEFAULT)
        if not title:
            title = browse_file_title(use_lang)
        filetypes = browse_filetypes(use_lang)

        file_path = filedialog.askopenfilename(
            initialdir=initial_dir if (initial_dir and os.path.exists(initial_dir)) else "C:\\",
            title=title,
            filetypes=filetypes
        )
        root.destroy()
        return os.path.normpath(file_path) if file_path else ""
    except Exception as e:
        print("File picker error:", e)
        return ""

# Runtime state
_init_cfg = load_saved_config()
REMEMBER_DEFAULT_PATH = bool(_init_cfg.get("remember_default_path", False))
GAME_PATH = _init_cfg.get("game_path", "") if (REMEMBER_DEFAULT_PATH and _init_cfg.get("game_path") and os.path.isdir(_init_cfg.get("game_path"))) else ""
DATA_FOLDER = _init_cfg["data_folder"]
ADDON_FOLDER = _init_cfg.get("addon_folder", DEFAULT_ADDON_FOLDER)
MOD_FOLDER = _init_cfg["mod_folder"]
DISMISS_FLA_WARNING = bool(_init_cfg.get("dismiss_fla_warning", False))
CANDIDATE_PATH = _init_cfg.get("candidate_path", "")
LANGUAGE = normalize_language(_init_cfg.get("language", _init_cfg.get("default_language", I18N_DEFAULT)))
DEFAULT_LANGUAGE = normalize_language(_init_cfg.get("default_language", I18N_DEFAULT))
CARD_DENSITY = normalize_card_density(_init_cfg.get("card_density", DEFAULT_CARD_DENSITY))
# Determine if startup path prompt is required:
# If user has not chosen to remember default path OR game_path is empty/invalid, we prompt them.
SHOULD_PROMPT_PATH = not (REMEMBER_DEFAULT_PATH and GAME_PATH and os.path.isdir(GAME_PATH))

backup_mgr = BackupManager(game_dir=GAME_PATH)
baseline_mgr = BaselineManager(GAME_PATH, DATA_FOLDER, backup_manager=backup_mgr)
fla_mgr = FLAManager(GAME_PATH, backup_manager=backup_mgr)
shadow_dir = baseline_mgr.shadow_dir
parser = DualTrackParser()
merger = ConfigMerger(shadow_dir, GAME_PATH, backup_manager=backup_mgr)
installer = ModInstaller(GAME_PATH, DATA_FOLDER, backup_manager=backup_mgr)
cleaner = ModCleaner(GAME_PATH, DATA_FOLDER, backup_manager=backup_mgr)
id_mgr = IdManager(GAME_PATH, shadow_dir=shadow_dir)

def _get_mod_scan_dir() -> str:
    path = os.path.join(GAME_PATH, "modloader", DATA_FOLDER)
    if not os.path.isdir(path) and os.path.isdir(shadow_dir):
        return shadow_dir
    return path

def _get_addon_scan_dir() -> str:
    path = os.path.join(GAME_PATH, "modloader", ADDON_FOLDER)
    return path

scanner = ModScanner(_get_mod_scan_dir(), GAME_PATH, data_dir=shadow_dir, addon_dir=_get_addon_scan_dir())

def set_active_data_folder(new_folder: str):
    global DATA_FOLDER, baseline_mgr, shadow_dir, scanner, merger, installer, cleaner, id_mgr
    baseline_mgr.set_data_folder(new_folder)
    DATA_FOLDER = baseline_mgr.data_folder
    shadow_dir = baseline_mgr.shadow_dir
    save_config(data_folder=DATA_FOLDER)
    merger = ConfigMerger(shadow_dir, GAME_PATH, backup_manager=backup_mgr)
    installer.set_data_folder(DATA_FOLDER)
    cleaner.set_data_folder(DATA_FOLDER)
    scanner = ModScanner(_get_mod_scan_dir(), GAME_PATH, data_dir=shadow_dir, addon_dir=_get_addon_scan_dir())
    id_mgr.set_shadow_dir(shadow_dir)
    id_mgr.scan_all_ides(force_refresh=True)

def set_active_addon_folder(new_folder: str):
    global ADDON_FOLDER, scanner
    clean = BaselineManager._sanitize_folder_name(new_folder)
    ADDON_FOLDER = clean
    save_config(addon_folder=ADDON_FOLDER)
    addon_path = _get_addon_scan_dir()
    if os.path.isdir(GAME_PATH):
        try:
            os.makedirs(addon_path, exist_ok=True)
        except Exception:
            pass
    scanner = ModScanner(_get_mod_scan_dir(), GAME_PATH, data_dir=shadow_dir, addon_dir=addon_path)

def set_active_game_path(new_path: str, new_data_folder: str = None, new_addon_folder: str = None, remember_default: bool = None):
    global GAME_PATH, DATA_FOLDER, ADDON_FOLDER, REMEMBER_DEFAULT_PATH, SHOULD_PROMPT_PATH, backup_mgr, baseline_mgr, fla_mgr, shadow_dir, scanner, merger, installer, cleaner, id_mgr
    GAME_PATH = os.path.normpath(new_path.strip()) if new_path else ""
    if new_data_folder:
        DATA_FOLDER = new_data_folder.strip()
    if new_addon_folder:
        ADDON_FOLDER = new_addon_folder.strip()
    if remember_default is not None:
        REMEMBER_DEFAULT_PATH = bool(remember_default)
    SHOULD_PROMPT_PATH = False

    path_to_persist = GAME_PATH if REMEMBER_DEFAULT_PATH else ""
    save_config(game_path=path_to_persist, data_folder=DATA_FOLDER, addon_folder=ADDON_FOLDER,
                remember_default_path=REMEMBER_DEFAULT_PATH, is_configured=REMEMBER_DEFAULT_PATH)
    backup_mgr.set_game_dir(GAME_PATH)
    baseline_mgr = BaselineManager(GAME_PATH, DATA_FOLDER, backup_manager=backup_mgr)
    fla_mgr = FLAManager(GAME_PATH, backup_manager=backup_mgr)
    shadow_dir = baseline_mgr.shadow_dir
    merger = ConfigMerger(shadow_dir, GAME_PATH, backup_manager=backup_mgr)
    installer = ModInstaller(GAME_PATH, DATA_FOLDER, backup_manager=backup_mgr)
    cleaner = ModCleaner(GAME_PATH, DATA_FOLDER, backup_manager=backup_mgr)
    id_mgr = IdManager(GAME_PATH, shadow_dir=shadow_dir)
    scanner = ModScanner(_get_mod_scan_dir(), GAME_PATH, data_dir=shadow_dir, addon_dir=_get_addon_scan_dir())



class ModManagerHandler(BaseHTTPRequestHandler):
    # Bounds how long a stalled client can hold the single-threaded server.
    timeout = REQUEST_SOCKET_TIMEOUT_SECONDS

    # Class-level default so handlers built via __new__ (tests) still work.
    _response_started = False

    def send_response(self, code, message=None):
        # Marks the point of no return: once the status line is out, an
        # unexpected error can no longer be reported as a clean JSON response.
        self._response_started = True
        super().send_response(code, message)

    def end_headers(self):
        # No Access-Control-Allow-* here on purpose: the UI is same-origin, and
        # a wildcard would let any visited website read these responses.
        super().end_headers()

    def _run_handler(self, handler):
        """
        Run one request handler. An unexpected error becomes a JSON 500 instead
        of a dropped connection, so the UI can surface what went wrong.
        """
        self._response_started = False
        try:
            handler()
        except Exception as exc:
            self._on_unhandled_error(exc)

    def _on_unhandled_error(self, exc: BaseException):
        try:
            traceback.print_exc()
        except Exception:
            pass

        if self._response_started:
            # A partial response is already on the wire; appending a second one
            # would corrupt the stream, so drop the connection instead.
            self.close_connection = True
            return

        # The packaged build runs without a console, so the reason is sent to
        # the client as well - otherwise a crash is completely invisible.
        detail = f"{type(exc).__name__}: {exc}"
        try:
            self._send_error(f"Internal server error ({detail})", status=500)
        except Exception:
            self.close_connection = True

    def _reject_non_local_request(self) -> bool:
        """
        Refuse requests that did not come from this machine's own UI.
        Returns True when the request was refused and a response was sent.
        """
        host = self.headers.get("Host", "")
        if host and not _is_loopback_authority(host):
            self._send_error("Access denied: Host header is not a local loopback address", status=403)
            return True
        origin = self.headers.get("Origin", "")
        if origin and not _is_loopback_authority(origin):
            self._send_error("Access denied: Cross-origin request blocked", status=403)
            return True
        return False

    def do_OPTIONS(self):
        if self._reject_non_local_request():
            return
        self.send_response(200)
        self.end_headers()

    def _send_json(self, data: Any, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_error(self, message: str, status: int = 400):
        self._send_json({"success": False, "error": message}, status=status)

    def do_GET(self):
        self._run_handler(self._handle_get)

    def _handle_get(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if self._reject_non_local_request():
            return

        # ---------------- API Endpoints ----------------
        if path == "/api/status":
            b_status = baseline_mgr.get_status()
            f_status = fla_mgr.get_fla_status()
            self._send_json({
                "success": True,
                "game_path": GAME_PATH,
                "data_folder": DATA_FOLDER,
                "addon_folder": ADDON_FOLDER,
                "mod_folder": MOD_FOLDER,
                "shadow_dir": shadow_dir,
                "replace_folder_full": _get_mod_scan_dir(),
                "addon_folder_full": _get_addon_scan_dir(),
                "modloader_folders": baseline_mgr.list_modloader_folders(),
                "baseline": b_status,
                "fla": f_status,
                "sound_presets": SOUND_PRESETS,
                "special_targets": SPECIAL_FEATURE_TARGETS,
                "should_prompt_path": SHOULD_PROMPT_PATH,
                "remember_default_path": REMEMBER_DEFAULT_PATH,
                "dismiss_fla_warning": DISMISS_FLA_WARNING,
                "candidate_path": CANDIDATE_PATH,
                "language": LANGUAGE,
                "default_language": DEFAULT_LANGUAGE,
                "card_density": CARD_DENSITY,
                "languages": language_catalog(),
                "is_valid_game_path": baseline_mgr.is_valid_game_path(),
                "seven_zip": get_7zip_status(),
            })
            return

        elif path == "/api/languages":
            self._send_json({
                "success": True,
                "language": LANGUAGE,
                "default_language": DEFAULT_LANGUAGE,
                "languages": language_catalog(),
            })
            return

        elif path == "/api/seven-zip":
            self._send_json({"success": True, **get_7zip_status(force_refresh=True)})
            return

        elif path == "/api/modloader-folders":
            folders = baseline_mgr.list_modloader_folders()
            self._send_json({
                "success": True,
                "folders": folders,
                "current": DATA_FOLDER,
                "current_addon": ADDON_FOLDER
            })
            return

        elif path == "/api/backups":
            snapshots = backup_mgr.list_snapshots()
            self._send_json({
                "success": True,
                "backups": snapshots,
                "backup_dir": backup_mgr.backup_dir
            })
            return

        elif path == "/api/mods":
            mods = scanner.scan_installed_mods()
            replace_mods = [m for m in mods if m.get("mod_type") != "addon"]
            addon_mods = [m for m in mods if m.get("mod_type") == "addon"]
            replace_folders = len(replace_mods)
            addon_folders = len(addon_mods)
            replace_vehicles = sum(len(m.get("target_vehicles") or m.get("target_models") or [1]) for m in replace_mods)
            addon_vehicles = sum(len(m.get("target_vehicles") or m.get("target_models") or [1]) for m in addon_mods)
            total_folders = len(mods)
            total_vehicles = replace_vehicles + addon_vehicles

            self._send_json({
                "success": True,
                "total": total_folders,
                "total_folders": total_folders,
                "total_vehicles": total_vehicles,
                "replace_count": replace_vehicles,
                "addon_count": addon_vehicles,
                "replace_folders": replace_folders,
                "replace_vehicles": replace_vehicles,
                "addon_folders": addon_folders,
                "addon_vehicles": addon_vehicles,
                "mods": mods
            })
            return

        elif path == "/api/mod-detail":
            rel = query.get("rel_path", [None])[0]
            full = query.get("full_path", [None])[0]
            target_dir = full if full else (os.path.join(shadow_dir, rel) if rel else None)

            if not target_dir or not os.path.isdir(target_dir):
                self._send_error("Specified mod path does not exist", status=404)
                return

            detail = parser.inspect_mod_directory(target_dir)
            if detail.get("success"):
                t_models = detail.get("target_models", [])
                req_model = query.get("model", [None])[0]
                active_model = req_model.strip().lower() if req_model else detail.get("target_model")

                all_configs = {}
                for m in t_models:
                    all_configs[m] = merger.get_vehicle_active_configs(m)

                if active_model and active_model not in all_configs:
                    all_configs[active_model] = merger.get_vehicle_active_configs(active_model)

                # --- Fallback for addon/multi-vehicle packs: authoritative data often
                # lives only inside the mod folder (readme/ide), not in shadow/vanilla.
                # Also used when the slot only resolved to the clean vanilla baseline
                # (the mod ships a txt preset that has not been merged into the shadow
                # copies yet) so the inspector compares the mod's values, not vanilla
                # against itself.
                try:
                    parsed = detail.get("parsed", {}) or {}
                    ide_list = parsed.get("ide", []) or []
                    handling_list = parsed.get("handling", []) or []
                    carcols_list = parsed.get("carcols", []) or []
                    carmods_list = parsed.get("carmods", []) or []
                    audio_lines = parsed.get("audio_lines", []) or []
                    special_lines = parsed.get("special_features", []) or []

                    def _find_ide(m):
                        ml = (m or "").lower()
                        for d in ide_list:
                            if d and (d.get("model_name") or "").lower() == ml:
                                return d
                        return None

                    def _find_handling(m):
                        ml = (m or "").lower()
                        for d in handling_list:
                            if d and (d.get("identifier") or "").lower() == ml:
                                return d
                        # Shared handling ID (e.g. 5 addon cars share PREMIER2/STANIER2):
                        # resolve via this model's own vehicles.ide handling_id.
                        try:
                            ide_hit = _find_ide(ml)
                            hid = (ide_hit.get("handling_id") or "") if ide_hit else ""
                            if hid:
                                hl = hid.lower()
                                for d in handling_list:
                                    if d and (d.get("identifier") or "").lower() == hl:
                                        return d
                        except Exception:
                            pass
                        return None

                    def _find_carcols(m):
                        ml = (m or "").lower()
                        for d in carcols_list:
                            if d and (d.get("model_name") or "").lower() == ml:
                                return d
                        return None

                    def _find_carmods(m):
                        ml = (m or "").lower()
                        for d in carmods_list:
                            if not d:
                                continue
                            dm = (d.get("model_name") or d.get("model") or "").lower()
                            if dm == ml:
                                return d
                        return None

                    def _needs_mod_preset(slot):
                        # Missing entirely, or only resolved to the clean vanilla
                        # baseline (mod override not deployed in shadow yet).
                        return (not slot) or (slot.get("source") == "vanilla")

                    mod_fla = {}
                    for m in list(all_configs.keys()):
                        cfg = all_configs[m] or {}
                        ml = (m or "").lower()
                        if _needs_mod_preset(cfg.get("vehicles_ide")):
                            hit = _find_ide(ml)
                            if hit and hit.get("raw"):
                                cfg["vehicles_ide"] = {"raw": hit.get("raw"), "source": "mod", "decomposed": hit}
                        if _needs_mod_preset(cfg.get("handling")):
                            hit = _find_handling(ml)
                            if hit and hit.get("raw"):
                                cfg["handling"] = {"raw": hit.get("raw"), "source": "mod", "decomposed": hit}
                        if _needs_mod_preset(cfg.get("carcols")):
                            hit = _find_carcols(ml)
                            if hit and hit.get("raw"):
                                cfg["carcols"] = {"raw": hit.get("raw"), "source": "mod", "decomposed": hit}
                        if _needs_mod_preset(cfg.get("carmods")):
                            hit = _find_carmods(ml)
                            if hit and hit.get("raw"):
                                cfg["carmods"] = {"raw": hit.get("raw"), "source": "mod", "decomposed": hit}
                        all_configs[m] = cfg

                        aud_raw = None
                        for ln in audio_lines:
                            try:
                                parts = (ln or "").strip().split()
                                if parts and parts[0].lower() == ml:
                                    aud_raw = (ln or "").strip()
                                    break
                            except Exception:
                                continue
                        sp_raw = None
                        for ln in special_lines:
                            try:
                                parts = (ln or "").strip().split()
                                if len(parts) >= 2 and parts[0].lower() == ml:
                                    sp_raw = (ln or "").strip()
                                    break
                            except Exception:
                                continue
                        mod_fla[ml] = {"audio_raw": aud_raw, "special_raw": sp_raw}
                    detail["mod_fla"] = mod_fla

                    # Compat aliases for older frontend keys
                    if "vehicles_ide" not in parsed:
                        parsed["vehicles_ide"] = ide_list
                    if "handling_cfg" not in parsed:
                        parsed["handling_cfg"] = handling_list
                    if "carcols_dat" not in parsed:
                        parsed["carcols_dat"] = carcols_list
                    if "carmods_dat" not in parsed:
                        parsed["carmods_dat"] = carmods_list
                except Exception:
                    pass

                # Enrich every carmods part (mod preset AND active/shadow) with:
                #   1. registered veh_mods.ide IDs (vanilla or shadow)
                #   2. the mod's own author .ide IDs (source "mod")
                #   3. the REAL shopping.dat price (instead of category default)
                try:
                    _mod_details = merger.tuning_mgr.get_all_veh_mods_details() or {}
                    _author_ids = detail.get("author_tuning_ides") or {}
                    try:
                        _shop_prices = merger.tuning_mgr.get_shopping_prices()
                    except Exception:
                        _shop_prices = {}
                    _enriched = set()

                    def _enrich_part(_p):
                        if not isinstance(_p, dict) or id(_p) in _enriched:
                            return
                        _enriched.add(id(_p))
                        _pn = (_p.get("part_name") or "").lower()
                        if not _pn:
                            return
                        if _pn in _mod_details:
                            _info = _mod_details[_pn]
                            _p["model_id"] = _info.get("id")
                            _p["txd_name"] = _info.get("txd_name", "")
                            _p["draw_dist"] = _info.get("draw_dist", 100.0)
                            _p["flags"] = _info.get("flags", 2097152)
                            _p["ide_source"] = _info.get("source", "unknown")
                        elif _pn in _author_ids:
                            _info = _author_ids[_pn]
                            _p["model_id"] = _info.get("id")
                            _p["txd_name"] = _info.get("txd_name", "")
                            _p["draw_dist"] = _info.get("draw_dist", 100.0)
                            _p["flags"] = _info.get("flags", 2097152)
                            _p["ide_source"] = "mod"
                        else:
                            _p.setdefault("model_id", None)
                            _p.setdefault("txd_name", "")
                            _p.setdefault("draw_dist", 100.0)
                            _p.setdefault("flags", 2097152)
                            _p.setdefault("ide_source", "none")
                        if _pn in _shop_prices:
                            _p["shopping_price"] = _shop_prices[_pn]
                            _p["shopping_registered"] = True
                        else:
                            _p.setdefault("shopping_price", None)
                            _p.setdefault("shopping_registered", False)

                    for _cm in (detail.get("parsed", {}) or {}).get("carmods", []) or []:
                        if _cm:
                            for _p in _cm.get("parts", []) or []:
                                _enrich_part(_p)
                    for _cfg in (all_configs or {}).values():
                        _cm_cfg = (_cfg or {}).get("carmods") or {}
                        _dec = _cm_cfg.get("decomposed") if isinstance(_cm_cfg, dict) else None
                        for _p in (_dec or {}).get("parts", []) or []:
                            _enrich_part(_p)
                except Exception:
                    pass

                detail["all_active_configs"] = all_configs
                detail["active_configs"] = all_configs.get(active_model, merger.get_vehicle_active_configs(active_model) if active_model else {})
                if active_model:
                    detail["target_model"] = active_model
            self._send_json(detail)
            return

        elif path == "/api/vehicle/configs":
            model = query.get("model", [""])[0].strip()
            if not model:
                self._send_error("Missing 'model' parameter")
                return
            configs = merger.get_vehicle_active_configs(model)
            self._send_json({"success": True, "configs": configs})
            return

        elif path == "/api/colors":
            self._send_json({"success": True, "palette": CARCOLS_PALETTE})
            return

        elif path == "/api/vehicles":
            veh_list = []
            for vid, info in sorted(VANILLA_VEHICLES.items(), key=lambda x: x[1]["name"]):
                veh_list.append({
                    "id": vid,
                    "model": info["model"],
                    "name": info["name"],
                    "type": info.get("type", "Car")
                })
            self._send_json({"success": True, "vehicles": veh_list})
            return

        elif path == "/api/fla/detail":
            model = query.get("model", [""])[0].strip()
            if not model:
                self._send_error("Missing 'model' parameter")
                return
            detail = fla_mgr.get_model_fla_detail(model)
            self._send_json({"success": True, "detail": detail})
            return

        elif path == "/api/installer/preview-text":
            result = installer.preview_source_text(
                query.get("inspection_id", [""])[0], query.get("rel", [""])[0]
            )
            self._send_json(result, status=200 if result["success"] else 400)
            return

        elif path == "/api/installer/authors":
            category = query.get("category", [DATA_FOLDER])[0].strip() or DATA_FOLDER
            authors = installer.get_existing_authors(category)
            self._send_json({"success": True, "authors": authors, "category": category})
            return

        elif path == "/api/ids/stats":
            stats = id_mgr.get_stats()
            self._send_json(stats)
            return

        elif path == "/api/ids/check":
            id_str = query.get("id", [""])[0].strip()
            if not id_str or not id_str.isdigit():
                self._send_error("Missing valid 'id' parameter")
                return
            res = id_mgr.check_id_status(int(id_str))
            self._send_json({"success": True, "result": res})
            return

        elif path == "/api/ids/search":
            q = query.get("query", [""])[0].strip()
            filter_type = query.get("filter_type", ["all"])[0].strip() or "all"
            limit = int(query.get("limit", [60])[0])
            res = id_mgr.search_ids(q, filter_type=filter_type, limit=limit)
            self._send_json({"success": True, "query": q, "filter_type": filter_type, "total": len(res), "results": res})
            return



        # ---------------- Static Web Hosting ----------------
        if path == "/" or path == "":
            path = "/index.html"

        rel_static = path.lstrip("/")
        # Resolve inside WEB_DIR and refuse anything that escapes it, so a
        # request like "/../config.json" cannot read files outside the UI.
        web_root = os.path.realpath(WEB_DIR)
        file_path = os.path.realpath(os.path.join(web_root, rel_static))
        try:
            inside_web_root = os.path.commonpath([web_root, file_path]) == web_root
        except ValueError:
            inside_web_root = False

        if inside_web_root and os.path.isfile(file_path):
            content_type = "text/plain"
            if file_path.endswith(".html"):
                content_type = "text/html; charset=utf-8"
            elif file_path.endswith(".css"):
                content_type = "text/css; charset=utf-8"
            elif file_path.endswith(".js"):
                content_type = "application/javascript; charset=utf-8"
            elif file_path.endswith(".png"):
                content_type = "image/png"
            elif file_path.endswith(".svg"):
                content_type = "image/svg+xml"

            with open(file_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def do_POST(self):
        self._run_handler(self._handle_post)

    def _handle_post(self):
        global LANGUAGE, DEFAULT_LANGUAGE, DISMISS_FLA_WARNING, CARD_DENSITY
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if self._reject_non_local_request():
            return

        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            body = json.loads(post_data)
        except Exception:
            body = {}

        if path == "/api/sync-baseline":
            res = baseline_mgr.sync_missing_shadow_copies()
            self._send_json(res)
            return

        elif path == "/api/revert-baseline":
            filename = body.get("filename")
            if not filename:
                self._send_error("Missing 'filename' parameter")
                return
            res = baseline_mgr.revert_to_vanilla(filename)
            self._send_json(res)
            return

        elif path == "/api/dry-run":
            target_dir = body.get("path")
            if not target_dir or not os.path.isdir(target_dir):
                self._send_error("Invalid mod path specified")
                return
            info = parser.inspect_mod_directory(target_dir)
            if not info["success"]:
                self._send_json(info, status=400)
                return
            plan = merger.plan_merge(info)
            self._send_json(plan)
            return

        elif path == "/api/apply-merge":
            target_dir = body.get("path")
            if not target_dir or not os.path.isdir(target_dir):
                self._send_error("Invalid mod path specified")
                return
            info = parser.inspect_mod_directory(target_dir)
            if not info["success"]:
                self._send_json(info, status=400)
                return
            res = merger.apply_merge(info)
            self._send_json(res)
            return

        elif path == "/api/fla/toggle-feature" or path == "/api/fla/set-special":
            model = body.get("model")
            target = body.get("target")  # e.g. 'zr350' or None
            if not model:
                self._send_error("Missing 'model' parameter")
                return
            success = fla_mgr.set_special_feature(model, target)
            detail = fla_mgr.get_model_fla_detail(model)
            self._send_json({"success": success, "model": model, "target": target, "detail": detail})
            return

        elif path == "/api/fla/remove-special":
            model = body.get("model")
            if not model:
                self._send_error("Missing 'model' parameter")
                return
            success = fla_mgr.remove_special_feature(model)
            detail = fla_mgr.get_model_fla_detail(model)
            self._send_json({"success": success, "model": model, "detail": detail})
            return

        elif path == "/api/fla/set-audio":
            model = body.get("model")
            raw_line = body.get("raw_line")
            if not model or not raw_line:
                self._send_error("Missing 'model' or 'raw_line' parameter")
                return
            formatted_line = FLAManager.format_audio_line(model, raw_line)
            success = fla_mgr.update_audio_setting(model, formatted_line)
            detail = fla_mgr.get_model_fla_detail(model)
            self._send_json({"success": success, "detail": detail})
            return

        elif path == "/api/fla/remove-audio":
            model = body.get("model")
            if not model:
                self._send_error("Missing 'model' parameter")
                return
            success = fla_mgr.remove_audio_setting(model)
            detail = fla_mgr.get_model_fla_detail(model)
            self._send_json({"success": success, "detail": detail})
            return


        elif path == "/api/parse-raw-text":
            raw_text = body.get("text", "")
            parsed_res = parser.parse_text_content(raw_text)
            self._send_json({"success": True, "parsed": parsed_res})
            return

        elif path == "/api/browse-folder":
            current = body.get("initial", GAME_PATH)
            title = body.get("title", "")
            lang = body.get("lang", LANGUAGE)
            selected = browse_folder_native(current, title=title, lang=lang)
            self._send_json({"success": bool(selected), "path": selected})
            return

        elif path == "/api/set-data-folder":
            folder = body.get("folder", "").strip()
            if not folder:
                self._send_error("Folder name cannot be empty")
                return
            set_active_data_folder(folder)
            self._send_json({
                "success": True,
                "data_folder": DATA_FOLDER,
                "shadow_dir": shadow_dir,
                "modloader_folders": baseline_mgr.list_modloader_folders(),
                "baseline": baseline_mgr.get_status()
            })
            return

        elif path == "/api/set-mod-folder":
            folder_type = body.get("type", "replace").strip().lower()
            folder = body.get("folder", "").strip()
            if not folder:
                self._send_error("Folder name cannot be empty")
                return

            if folder_type == "addon":
                set_active_addon_folder(folder)
            else:
                set_active_data_folder(folder)

            mods = scanner.scan_installed_mods()
            replace_mods = [m for m in mods if m.get("mod_type") != "addon"]
            addon_mods = [m for m in mods if m.get("mod_type") == "addon"]
            replace_folders = len(replace_mods)
            addon_folders = len(addon_mods)
            replace_vehicles = sum(len(m.get("target_vehicles") or m.get("target_models") or [1]) for m in replace_mods)
            addon_vehicles = sum(len(m.get("target_vehicles") or m.get("target_models") or [1]) for m in addon_mods)
            total_folders = len(mods)
            total_vehicles = replace_vehicles + addon_vehicles

            self._send_json({
                "success": True,
                "type": folder_type,
                "data_folder": DATA_FOLDER,
                "addon_folder": ADDON_FOLDER,
                "replace_folder_full": _get_mod_scan_dir(),
                "addon_folder_full": _get_addon_scan_dir(),
                "modloader_folders": baseline_mgr.list_modloader_folders(),
                "total": total_folders,
                "total_folders": total_folders,
                "total_vehicles": total_vehicles,
                "replace_count": replace_vehicles,
                "addon_count": addon_vehicles,
                "replace_folders": replace_folders,
                "replace_vehicles": replace_vehicles,
                "addon_folders": addon_folders,
                "addon_vehicles": addon_vehicles,
                "mods": mods
            })
            return

        elif path == "/api/set-game-path":
            new_path = body.get("path", "").strip()
            new_folder = body.get("data_folder", "").strip() or None
            remember_default = body.get("remember_default", None)
            if not new_path or not os.path.isdir(new_path):
                self._send_error("Specified path does not exist or is not a valid directory")
                return

            temp_bm = BaselineManager(new_path)
            if not temp_bm.is_valid_game_path():
                self._send_error("Neither gta_sa.exe nor data/ directory found in the selected folder. Please verify this is the GTA San Andreas installation root directory.")
                return

            set_active_game_path(new_path, new_data_folder=new_folder, remember_default=remember_default)
            self._send_json({
                "success": True,
                "game_path": GAME_PATH,
                "data_folder": DATA_FOLDER,
                "shadow_dir": shadow_dir,
                "modloader_folders": baseline_mgr.list_modloader_folders(),
                "baseline": baseline_mgr.get_status(),
                "fla": fla_mgr.get_fla_status(),
                "remember_default_path": REMEMBER_DEFAULT_PATH,
                "should_prompt_path": SHOULD_PROMPT_PATH
            })
            return

        elif path == "/api/config/dismiss-fla":
            DISMISS_FLA_WARNING = True
            save_config(dismiss_fla_warning=True)
            self._send_json({"success": True, "dismiss_fla_warning": True})
            return

        elif path in ("/api/config/language", "/api/set-language"):
            lang = body.get("language")
            set_default = bool(body.get("set_default", False) or body.get("persist_default", False))
            def_lang = body.get("default_language")

            if is_supported_language(lang):
                LANGUAGE = normalize_language(lang)
            if set_default or is_supported_language(def_lang):
                DEFAULT_LANGUAGE = normalize_language(def_lang if is_supported_language(def_lang) else LANGUAGE)
                save_config(language=LANGUAGE, default_language=DEFAULT_LANGUAGE)

            self._send_json({
                "success": True,
                "language": LANGUAGE,
                "default_language": DEFAULT_LANGUAGE,
                "languages": language_catalog(),
            })
            return

        elif path == "/api/config/card-density":
            CARD_DENSITY = normalize_card_density(body.get("density"))
            save_config(card_density=CARD_DENSITY)
            self._send_json({"success": True, "card_density": CARD_DENSITY})
            return

        elif path == "/api/backups/restore":
            snapshot_id = body.get("snapshot_id")
            if not snapshot_id:
                self._send_error("Missing 'snapshot_id' parameter")
                return
            res = backup_mgr.restore_snapshot(snapshot_id)
            if res.get("success"):
                self._send_json(res)
            else:
                self._send_json(res, status=400)
            return

        elif path == "/api/backups/clean-legacy":
            archive = bool(body.get("archive", True))
            res = backup_mgr.clean_legacy_game_backups(GAME_PATH, archive_to_backup=archive)
            self._send_json(res)
            return

        elif path == "/api/browse-file":
            current = body.get("initial", "")
            title = body.get("title", "")
            lang = body.get("lang", LANGUAGE)
            selected = browse_file_native(current, title=title, lang=lang)
            self._send_json({"success": bool(selected), "path": selected})
            return

        elif path == "/api/installer/inspect":
            source_path = body.get("source_path", "").strip()
            if not source_path:
                self._send_error("Missing mod source path")
                return
            res = installer.inspect_source(source_path)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            self._send_json(res)
            return

        elif path == "/api/installer/reparse-config":
            inspection_id = body.get("inspection_id", "").strip()
            excluded = body.get("excluded_files", [])
            if not inspection_id:
                self._send_error("Missing 'inspection_id' parameter")
                return
            res = installer.reparse_inspection(inspection_id, excluded)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            self._send_json(res)
            return

        elif path == "/api/installer/check-existing":
            try:
                self._send_json(check_existing_models(GAME_PATH, body))
            except OSError as error:
                self._send_error(f"Failed to check existing installations: {error}")
            return

        elif path == "/api/installer/install":
            res = installer.execute_install(body)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            try:
                id_mgr.scan_all_ides(force_refresh=True)
            except Exception:
                pass
            self._send_json(res)
            return

        elif path == "/api/ids/allocate":
            count = int(body.get("count", 1))
            kind = str(body.get("kind", "tuning")).strip().lower()
            start_preferred = body.get("start_preferred")
            exclude_ids = body.get("exclude_ids")
            if start_preferred:
                start_preferred = int(start_preferred)
            if exclude_ids:
                exclude_ids = set(int(x) for x in exclude_ids)
            if kind == "addon":
                allocated = id_mgr.allocate_free_addon_ids(count, start_preferred=start_preferred, exclude_ids=exclude_ids)
            else:
                allocated = id_mgr.allocate_free_ids(count, start_preferred=start_preferred, exclude_ids=exclude_ids)
            self._send_json({"success": True, "allocated": allocated})
            return

        elif path == "/api/open-url":
            url = str(body.get("url", "")).strip()
            if not (url.startswith("https://") or url.startswith("http://")):
                self._send_error("Only http(s) URLs are allowed")
                return
            try:
                webbrowser.open(url)
                self._send_json({"success": True, "url": url})
            except Exception as e:
                self._send_error(f"Failed to open URL: {e}")
            return

        elif path == "/api/open-folder":
            target_folder = body.get("path", "").strip()
            if target_folder and os.path.isdir(target_folder):
                try:
                    os.startfile(target_folder)
                    self._send_json({"success": True})
                    return
                except Exception as e:
                    self._send_error(f"Failed to open folder: {e}")
                    return
            self._send_error("Specified folder does not exist")
            return

        elif path == "/api/mods/delete":
            target_path = body.get("path", "").strip()
            target_model = body.get("model", "").strip()
            revert_config = body.get("revert_config", True)

            if not target_path:
                self._send_error("Missing 'path' parameter")
                return

            res = cleaner.delete_mod(target_path, target_model=target_model, revert_config=revert_config)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            try:
                id_mgr.scan_all_ides(force_refresh=True)
            except Exception:
                pass
            self._send_json(res)
            return

        elif path == "/api/mods/rename":
            target_path = str(body.get("path", "") or "").strip()
            new_name = body.get("new_name", "")

            if not target_path:
                self._send_error("Missing 'path' parameter")
                return

            res = rename_mod_folder(target_path, new_name, os.path.join(GAME_PATH, "modloader"))
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            try:
                id_mgr.scan_all_ides(force_refresh=True)
            except Exception:
                pass
            self._send_json(res)
            return

        elif path == "/api/vehicle/update-config":
            model = body.get("model", "").strip()
            config_type = body.get("config_type", "").strip()
            raw_line = body.get("raw_line", "").strip()

            if not model or not config_type or not raw_line:
                self._send_error("Missing 'model', 'config_type', or 'raw_line' parameter")
                return

            res = merger.save_vehicle_config(model, config_type, raw_line)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            self._send_json(res)
            return

        elif path == "/api/vehicle/update-fxt":
            res = update_fxt_entry(
                body.get("mod_dir") or body.get("full_path") or "",
                body.get("key") or "",
                body.get("name") or "",
                body.get("model") or "",
                backup_manager=backup_mgr,
            )
            self._send_json(res, status=200 if res.get("success") else 400)
            return

        elif path == "/api/vehicle/update-tuning-id":
            model = body.get("model", "").strip()
            part_name = body.get("part_name", "").strip()
            new_id = body.get("new_id")

            if not model or not part_name or new_id is None:
                self._send_error("Missing 'model', 'part_name', or 'new_id' parameter")
                return

            try:
                new_id_int = int(new_id)
            except (ValueError, TypeError):
                self._send_error("'new_id' must be a valid integer")
                return

            res = merger.update_tuning_part_id(model, part_name, new_id_int)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            self._send_json(res)
            return

        elif path == "/api/vehicle/delete-tuning-part":
            model = body.get("model", "").strip()
            part_name = body.get("part_name", "").strip()

            if not model or not part_name:
                self._send_error("Missing 'model' or 'part_name' parameter")
                return

            res = merger.delete_tuning_part(model, part_name)
            if not res.get("success"):
                self._send_json(res, status=400)
                return
            self._send_json(res)
            return

        self._send_error("Endpoint not found", status=404)


    def log_message(self, format, *args):
        # Mute standard noisy HTTP log lines for clean console output
        pass


def _bind_http_backend(preferred_port: Optional[int] = None) -> Tuple[HTTPServer, int]:
    """Bind the local API on preferred_port, or any free port if that fails / is omitted."""
    host = "127.0.0.1"
    try:
        server = HTTPServer((host, preferred_port if preferred_port is not None else 0), ModManagerHandler)
    except OSError:
        server = HTTPServer((host, 0), ModManagerHandler)
    return server, server.server_address[1]


def _shutdown_http(server: HTTPServer) -> None:
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass


def start_server(auto_open: bool = True, preferred_port: Optional[int] = PORT):
    """Debug / fallback: host the UI in the system browser. Not the packaged-exe path."""
    server, port = _bind_http_backend(preferred_port)
    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print(f"  {WINDOW_TITLE}")
    print("  Browser mode (debug)")
    print(f"  Service started: {url}")
    print("=" * 60)

    if auto_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nService stopped.")
    finally:
        _shutdown_http(server)


def start_desktop_app(preferred_port: Optional[int] = None):
    """Canonical launch path for the packaged exe: local API + native WebView2 window."""
    server, port = _bind_http_backend(preferred_port)
    url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print("=" * 60)
    print(f"  {WINDOW_TITLE}")
    print("  Desktop client started")
    print(f"  Backend service: {url}")
    print("=" * 60)

    import webview
    webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        width=1340,
        height=880,
        min_size=(1000, 660),
        resizable=True,
        text_select=True,
        background_color="#0a0c10",
    )
    try:
        webview.start(private_mode=False)
    finally:
        _shutdown_http(server)


def main(argv: Optional[list] = None) -> None:
    """Single process entry used by the exe, python server.py, and thin desktop wrappers."""
    args = list(sys.argv[1:] if argv is None else argv)
    browser_mode = "--browser" in args
    if browser_mode:
        start_server(auto_open=True)
        return

    try:
        start_desktop_app()
    except Exception as e:
        print("Desktop window failed, falling back to browser:", e)
        start_server(auto_open=True)


if __name__ == "__main__":
    main()
