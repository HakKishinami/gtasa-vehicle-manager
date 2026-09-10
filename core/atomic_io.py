"""
Atomic text writes for the GTA SA configuration files.

The game reads these files directly (handling.cfg, carmods.dat, shopping.dat,
vehicles.ide, ...). Writing them in place means an exception, a full disk or a
concurrent reader can catch a truncated file, which makes the game crash on
load. Writing to a temp file next to the target and swapping it in with
os.replace keeps the previous content intact until the new content is complete.
"""

import os
import tempfile
from typing import Iterable, Union


def write_bytes_atomic(path: str, data: bytes) -> None:
    """
    Write raw `data` to `path`, replacing it atomically.

    Use this when the file's encoding must be preserved verbatim (legacy
    game files are not always UTF-8); write_text_atomic is the text-mode
    convenience wrapper around it.
    """
    directory = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def write_text_atomic(path: str, content: Union[str, Iterable[str]]) -> None:
    """
    Write `content` to `path`, replacing it atomically.

    `content` is either a string or an iterable of lines. Text mode is used with
    the default newline handling, so the bytes produced are the same as a plain
    open(path, "w", encoding="utf-8").write(...) would have produced.

    Parent directories are not created; a missing directory raises exactly as
    the direct write it replaces did.
    """
    directory = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if isinstance(content, str):
                handle.write(content)
            else:
                handle.writelines(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
