"""Symlink-safe, crash-durable atomic file writers."""

import json
import os
import stat
import tempfile
from pathlib import Path


def write_bytes_atomic(path, content):
    """Replace *path* from a private same-directory inode and fsync the commit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = None
    try:
        existing_stat = os.stat(path, follow_symlinks=False)
        if stat.S_ISREG(existing_stat.st_mode):
            existing_mode = stat.S_IMODE(existing_stat.st_mode)
    except FileNotFoundError:
        pass

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            temporary.chmod(existing_mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_text_atomic(path, content):
    write_bytes_atomic(path, content.encode("utf-8"))


def write_json_atomic(path, value):
    write_text_atomic(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _fsync_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
