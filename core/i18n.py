"""
Language registry for the desktop app.

To add a language (e.g. Spanish, German, French):
  1. Append an entry to LANGUAGES below (id, name, html_lang, native dialogs).
  2. Add a matching dictionary block in web/i18n.js (I18N_DICTIONARY.es = {...}).
  3. Missing UI keys fall back to English — partial dictionaries are OK.
"""

from typing import Any, Dict, List, Optional

DEFAULT_LANGUAGE = "en"
FALLBACK_LANGUAGE = "en"

LANGUAGES: Dict[str, Dict[str, Any]] = {
    "en": {
        "id": "en",
        "name": "English",
        "html_lang": "en",
        "browse_folder": "Select Folder",
        "browse_file": "Select Vehicle Mod Archive or Files",
        "filetypes": [
            ("Mod Archives & Files (*.zip;*.rar;*.7z...)", "*.zip;*.rar;*.7z;*.dff;*.txd;*.txt;*.readme;*.fxt;*.cfg;*.dat;*.ide"),
            ("ZIP Archives (*.zip)", "*.zip"),
            ("RAR Archives (*.rar)", "*.rar"),
            ("7-Zip Archives (*.7z)", "*.7z"),
            ("All Files (*.*)", "*.*"),
        ],
    },
}


def supported_ids() -> List[str]:
    return list(LANGUAGES.keys())


def is_supported(lang: Optional[str]) -> bool:
    return bool(lang) and normalize_language(lang, default="") != ""


def normalize_language(lang: Optional[str], default: str = DEFAULT_LANGUAGE) -> str:
    """
    Accept 'zh', 'ZH', 'zh-CN', 'en_US'. Unknown values return default.
    Empty default ('') means 'not a supported language'.
    """
    if lang is None:
        return default
    raw = str(lang).strip().lower().replace("_", "-")
    if not raw:
        return default
    if raw in LANGUAGES:
        return raw
    base = raw.split("-", 1)[0]
    if base in LANGUAGES:
        return base
    return default


def language_meta(lang: Optional[str]) -> Dict[str, Any]:
    code = normalize_language(lang)
    return LANGUAGES[code]


def language_catalog() -> List[Dict[str, str]]:
    return [
        {
            "id": meta.get("id", code),
            "name": meta.get("name", code),
            "html_lang": meta.get("html_lang", meta.get("id", code)),
        }
        for code, meta in LANGUAGES.items()
    ]


def browse_folder_title(lang: Optional[str]) -> str:
    meta = language_meta(lang)
    return meta.get("browse_folder") or LANGUAGES[FALLBACK_LANGUAGE]["browse_folder"]


def browse_file_title(lang: Optional[str]) -> str:
    meta = language_meta(lang)
    return meta.get("browse_file") or LANGUAGES[FALLBACK_LANGUAGE]["browse_file"]


def browse_filetypes(lang: Optional[str]):
    meta = language_meta(lang)
    types = meta.get("filetypes")
    if types:
        return types
    return LANGUAGES[FALLBACK_LANGUAGE]["filetypes"]


def pick_localized(source: Optional[Dict[str, Any]], field: str = "label", lang: Optional[str] = None) -> str:
    """
    Resolve a localized field from API-style objects:
      {label_zh, label_en, label}  or  {zh: '...', en: '...'}
    """
    if not source:
        return ""
    code = normalize_language(lang)
    fallback = FALLBACK_LANGUAGE
    candidates = [
        source.get(code),
        source.get(f"{field}_{code}"),
        source.get(field),
        source.get(fallback),
        source.get(f"{field}_{fallback}"),
        source.get(DEFAULT_LANGUAGE),
        source.get(f"{field}_{DEFAULT_LANGUAGE}"),
    ]
    for value in candidates:
        if value:
            return str(value)
    return ""
