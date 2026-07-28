from __future__ import annotations

import io
import zipfile
from pathlib import Path

from utils.text_cleaner import remove_invalid_xml_chars


def _decode_html(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return remove_invalid_xml_chars(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return remove_invalid_xml_chars(raw.decode("utf-8", errors="replace"))


def load_html(file_path: str) -> str:
    """Read normal or compressed SingleFile HTML with common encodings."""
    path = Path(file_path)
    raw = path.read_bytes()
    # SingleFile's compressed self-extracting format is a valid ZIP archive
    # with an HTML bootstrap prepended. Python's zipfile handles that prefix.
    if zipfile.is_zipfile(io.BytesIO(raw)):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = archive.namelist()
                entry = next(
                    (name for name in names if name.casefold() == "index.html"),
                    next(
                        (
                            name
                            for name in names
                            if name.casefold().endswith((".html", ".htm"))
                        ),
                        "",
                    ),
                )
                if entry:
                    return _decode_html(archive.read(entry))
        except (OSError, zipfile.BadZipFile, RuntimeError):
            pass
    return _decode_html(raw)


def iter_html_files(input_dir: str, recursive: bool = False) -> list[str]:
    """List .html/.htm files in stable, case-insensitive order."""
    root = Path(input_dir).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是文件夹: {root}")

    paths = root.rglob("*") if recursive else root.glob("*")
    files = [
        str(path)
        for path in paths
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    ]
    return sorted(files, key=lambda value: value.casefold())
