"""Route author FXT entries by vehicle and deploy each managed key once."""
import os
import re

from .parser import read_text_file_safe, detect_text_encoding
from .atomic_io import write_bytes_atomic


FXT_KEY_RE = re.compile(r'^[A-Z0-9_]{2,40}$')


def line_key(line):
    """The GXT key a line defines, or "" when the line is not a mapping."""
    stripped = line.strip()
    if not stripped:
        return ""
    parts = stripped.split(None, 1)
    return parts[0].upper() if parts else ""


def validate_fxt_name(name: str) -> str:
    """Return an error message when `name` is not a usable in-game car name."""
    if not name or len(name) > 64 or "\n" in name or "\r" in name:
        return "Display name cannot be empty and must not exceed 64 characters"
    if not re.search(r'[A-Za-z\u4e00-\u9fff]{2,}', name):
        return "Display name must contain valid text (pure numeric configs rejected)"
    numeric = 0
    for token in name.split():
        try:
            float(token)
            numeric += 1
        except (ValueError, TypeError):
            pass
    if numeric >= 3:
        return "Display name appears to be a configuration line (too many numbers); please check and retry"
    return ""


def _read_preserving(path: str):
    """
    Read `path` as (codec, text), or (None, "") when the bytes cannot be
    reproduced exactly.

    Detection is a heuristic, so the decision to write is made on proof rather
    than on the guess: the decoded text must re-encode to the original bytes.
    If it does not, the file is left alone - rewriting it would silently alter
    every line we did not mean to touch.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None, ""

    codec = detect_text_encoding(raw)
    if codec is None:
        return None, ""

    try:
        if codec == "utf-16":
            text = raw.decode("utf-16").lstrip('\ufeff')
        else:
            text = raw.decode(codec)
        # Prove the guess before anyone writes: the decoded text must
        # reproduce the original bytes exactly.
        if text.encode(codec) != raw:
            return None, ""
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
        return None, ""
    return codec, text


def _rename_key(text: str, key: str, name: str):
    """
    Rewrite the first line defining `key`. Line endings, a trailing-newline
    choice and every unrelated byte position are preserved verbatim.
    Returns (new_text, replaced).
    """
    out, done = [], False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if not done and line_key(body) == key:
            out.append(f"{key} {name}" + line[len(body):])
            done = True
        else:
            out.append(line)
    return "".join(out), done


def update_fxt_entry(mod_dir, key, name, model_hint="", backup_manager=None):
    """
    Rename one GXT key inside an already-installed mod folder.

    Every file keeps its original encoding, line endings and byte layout; a
    file whose encoding cannot be determined aborts the whole update instead of
    being silently rewritten. All writes share one snapshot and are rolled back
    together when any of them fails.
    """
    if not mod_dir or not os.path.isdir(mod_dir):
        return {"success": False, "error": "Invalid mod directory"}

    key = (key or "").strip().upper()
    if not FXT_KEY_RE.match(key):
        return {"success": False, "error": "Invalid FXT key (must be 2-40 uppercase alphanumeric characters or underscores)"}

    name = (name or "").strip()
    name_error = validate_fxt_name(name)
    if name_error:
        return {"success": False, "error": name_error}

    base = os.path.normpath(mod_dir)
    targets = []
    for root, _, files in os.walk(base):
        for filename in sorted(files):
            if not filename.lower().endswith(".fxt"):
                continue
            path = os.path.join(root, filename)
            codec, text = _read_preserving(path)
            if codec is None:
                # Only a problem if this is a file we would have to rewrite.
                # FXT keys are ASCII, so a byte scan finds them in any
                # ASCII-compatible encoding without decoding.
                try:
                    with open(path, "rb") as handle:
                        raw = handle.read()
                    contains = key.encode("ascii") in raw
                except (OSError, UnicodeEncodeError):
                    contains = False
                if contains:
                    return {"success": False,
                            "error": f"Cannot safely read this .fxt file, aborted to prevent corruption: {filename}"}
                continue
            if any(line_key(ln) == key for ln in text.splitlines()):
                targets.append((path, codec, text))

    if not targets:
        # The key is not deployed yet: create the file the game will load.
        safe_model = re.sub(r'[^a-z0-9_]', '_', (model_hint or "").strip().lower())[:24]
        filename = f"{safe_model or key.lower()[:24] or 'custom'}.fxt"
        path = os.path.join(base, filename)
        try:
            if backup_manager is not None:
                with backup_manager.snapshot('edit_fxt', 'Create FXT vehicle name entry'):
                    write_bytes_atomic(path, f"{key} {name}\r\n".encode("utf-8"))
            else:
                write_bytes_atomic(path, f"{key} {name}\r\n".encode("utf-8"))
        except OSError as exc:
            return {"success": False, "error": f"Write failed: {exc}"}
        return {"success": True, "key": key, "name": name, "files": [path], "created": True}

    written, errors = [], []

    def _apply():
        for path, codec, text in targets:
            new_text, replaced = _rename_key(text, key, name)
            if not replaced or new_text == text:
                continue
            if backup_manager is not None:
                backup_manager.backup_file(path)
            try:
                write_bytes_atomic(path, new_text.encode(codec))
            except (OSError, UnicodeEncodeError) as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")
                continue
            written.append(path)

    # One snapshot for the whole rename: either every file moves to the new
    # name or none does, so the car list can't end up half-renamed.
    snapshot_dir = None
    if backup_manager is not None:
        with backup_manager.snapshot('edit_fxt', 'Update FXT vehicle name entry') as snapshot_dir:
            _apply()
    else:
        _apply()

    if errors:
        rolled_back = True
        if backup_manager is not None and snapshot_dir:
            res = backup_manager.restore_snapshot(os.path.basename(snapshot_dir))
            rolled_back = bool(res.get("success"))
        return {
            "success": False,
            "rolled_back": rolled_back,
            "error": "Write failed, rolled back: " + "; ".join(errors),
        }

    return {"success": True, "key": key, "name": name, "files": written, "created": False}


def entry(line):
    # Unlike Readme detection, a known .fxt file can contain localized names,
    # punctuation and long sentences. Comments are not name mappings.
    line = line.strip().lstrip('\ufeff')
    match = re.match(r'^([A-Za-z0-9_]{2,40})\s+(.+)$', line)
    return (match[1].upper(), match[2].strip()) if match else None


def deploy_fxt(source_files, vehicles, destinations, source_keys, backup_manager, previous_keys=None, ignored_keys=None):
    """Only reconcile keys for this install inside its selected destinations.

    destinations parallels vehicles; None denotes a skipped vehicle. Disabling
    generate_fxt retains author mappings but does not synthesize/rename them.
    Source files have already passed the installer's exclusion/variant filters.
    ``ignored_keys`` lists FXT keys owned by skipped vehicles so the shared
    "unowned author entry" fallback cannot leak them into an active folder.
    """
    active_dirs = list(dict.fromkeys(d for d in destinations if d))
    if not active_dirs:
        return [], {}
    ignored = {str(k).upper() for k in (ignored_keys or set()) if k}
    aliases, managed, source_rows = {}, set(), {}
    for index, vehicle in enumerate(vehicles):
        model = vehicle.get('source_model', '').lower()
        keys = {model.upper(), source_keys.get(model, '').upper()}
        keys.discard('')
        for key in keys:
            aliases.setdefault(key, []).append(index)

    files = []
    for path in source_files:
        lines = read_text_file_safe(path).splitlines()
        files.append((path, lines))
        for line in lines:
            parsed = entry(line)
            if parsed:
                source_rows.setdefault(parsed[0], (parsed[1], path))

    # Keep the single-car compatibility case where the author key differs from
    # the model and there is no IDE entry identifying it.
    if len(vehicles) == 1 and len(source_rows) == 1 and not any(k in aliases for k in source_rows):
        key = next(iter(source_rows))
        aliases[key] = [0]

    all_package_models = {
        v.get('source_model', '').lower() for v in vehicles if v.get('source_model')
    } | {
        v.get('target_model', '').lower() for v in vehicles if v.get('target_model')
    }
    all_package_models.discard('')

    desired, final_keys = {}, {}
    for index, vehicle in enumerate(vehicles):
        directory = destinations[index]
        if not directory:
            continue
        model = vehicle.get('source_model', '').lower()
        target = vehicle.get('target_model', model).lower()
        owned = [k for k, owners in aliases.items() if index in owners and k in source_rows]
        preferred = source_keys.get(model, '').upper()
        owned.sort(key=lambda k: (k != preferred, k != model.upper(), k))
        original = owned[0] if owned else preferred or model.upper()
        author = source_rows.get(original)
        enabled = vehicle.get('generate_fxt', True)
        if not enabled and not author:
            continue
        managed.update(k for k, owners in aliases.items() if index in owners)
        previous = (previous_keys or {}).get(target)
        if previous:
            managed.add(previous.upper())
        key = (vehicle.get('fxt_key') or original or target).strip().upper() if enabled else original
        name = (vehicle.get('fxt_name') or (author[0] if author else target)).strip() if enabled else author[0]
        if not re.fullmatch(r'[A-Z0-9_]{2,40}', key) or not name or '\n' in name or '\r' in name:
            raise ValueError(f'Invalid FXT key or name for vehicle {target}')
        managed.add(key)
        if key in desired and desired[key][0] != name:
            raise ValueError(f'Multiple vehicles share FXT key {key} with different names; please assign distinct keys')

        author_file = os.path.basename(author[1]) if author else None
        fxt_filename = target + '.fxt'
        is_addon = (
            vehicle.get('category') == 'Addon Cars'
            or vehicle.get('addon_id') is not None
            or bool(vehicle.get('is_addon'))
        )
        if author_file:
            author_stem = os.path.splitext(author_file)[0].lower()
            other_models = {
                v.get('source_model', '').lower()
                for j, v in enumerate(vehicles)
                if j != index and v.get('source_model')
            } | {
                v.get('target_model', '').lower()
                for j, v in enumerate(vehicles)
                if j != index and v.get('target_model')
            }
            other_models.discard('')
            belongs_to_other = author_stem in other_models and author_stem not in (target, model)
            addon_mismatch = is_addon and author_stem not in (target, model)
            if not (belongs_to_other or addon_mismatch):
                fxt_filename = author_file

        # A shared key with the same name needs one global definition only.
        desired.setdefault(key, (name, directory, fxt_filename, author_file, is_addon))
        final_keys[target] = key

    existing, locations, styles = {}, {}, {}
    for directory in active_dirs:
        for root, dirs, names in os.walk(directory):
            dirs.sort()
            for name in sorted(names, key=str.lower):
                if not name.lower().endswith('.fxt'):
                    continue
                path = os.path.join(root, name)
                if path in existing:
                    continue
                text = read_text_file_safe(path)
                lines = text.splitlines()
                existing[path] = lines
                # Remember how this file was laid out so a rewrite does not
                # silently convert its line endings or add a trailing newline.
                styles[path] = ('\r\n' if '\r\n' in text else '\n',
                                text.endswith(('\n', '\r')))
                for line in lines:
                    parsed = entry(line)
                    if parsed:
                        locations.setdefault((directory, parsed[0]), path)

    existing_paths = {os.path.normcase(os.path.abspath(path)): path for path in existing}

    def destination_path(directory, filename):
        path = os.path.join(directory, filename)
        return existing_paths.get(os.path.normcase(os.path.abspath(path)), path)

    output = {}
    removed_from = set()
    for path, lines in existing.items():
        kept = []
        for line in lines:
            parsed = entry(line)
            if parsed and parsed[0] in managed:
                removed_from.add(path)
            else:
                kept.append(line)
        output[path] = kept

    # Unowned author entries are shared resources: preserve them once in the
    # first destination. Recognized skipped-vehicle entries are not deployed.
    unowned_seen = set()
    comments = {}
    for path, lines in files:
        filename = os.path.basename(path)
        comments.setdefault(filename, [line for line in lines if not entry(line)])
        for line in lines:
            parsed = entry(line)
            if not parsed:
                continue
            key, name = parsed
            if key in aliases or key in managed or key in unowned_seen or key in ignored:
                continue
            unowned_seen.add(key)
            dest = locations.get((active_dirs[0], key), destination_path(active_dirs[0], filename))
            if not any(entry(row) and entry(row)[0] == key for row in output.get(dest, [])):
                output.setdefault(dest, list(comments[filename])).append(f'{key} {name}')

    for key, (name, directory, filename, author_file, is_addon) in desired.items():
        # Prefer the author's destination file when it already exists; otherwise
        # reuse an existing mapping instead of generating a second file.
        author_dest = destination_path(directory, filename)
        existing_loc = locations.get((directory, key))
        if existing_loc and os.path.basename(existing_loc).lower() != filename.lower():
            existing_stem = os.path.splitext(os.path.basename(existing_loc))[0].lower()
            if existing_stem in all_package_models or is_addon:
                existing_loc = None
        dest = author_dest if author_dest in existing else (existing_loc or author_dest)
        output.setdefault(dest, list(comments.get(filename, comments.get(author_file, [])))).append(f'{key} {name}')

    changed = []
    with backup_manager.snapshot('install_fxt', 'Assign and update FXT names per vehicle'):
        for path, lines in output.items():
            # Preserve unrelated text. Remove a duplicate-only file after its
            # last managed entry has moved to the proper vehicle directory.
            has_content = any(line.strip() and not line.lstrip().startswith(('#', ';', '//')) for line in lines)
            if not has_content and path in removed_from:
                backup_manager.backup_file(path)
                os.remove(path)
                changed.append(path)
                continue
            if path in existing and existing[path] == lines:
                continue
            # Rebuild with the file's own layout. A generated file follows the
            # convention this function has always produced (CRLF, terminated).
            newline, trailing = styles.get(path, ('\r\n', True))
            text = newline.join(lines)
            if lines and trailing:
                text += newline
            if path in existing:
                backup_manager.backup_file(path)
            write_bytes_atomic(path, text.encode('utf-8'))
            changed.append(path)
    return changed, final_keys
