from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, backup_path: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as file:
            tmp_name = file.name
            file.write(text)
            file.flush()
            os.fsync(file.fileno())

        if backup_path is not None and path.exists():
            shutil.copy2(path, backup_path)

        os.replace(tmp_name, path)
        fsync_directory(path.parent)
    except Exception:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def append_jsonl_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as file:
        file.write(line)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
