from __future__ import annotations

import csv
import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


MiB = 1024 * 1024


class UploadLimitError(ValueError):
    """Raised when an uploaded file exceeds the public-service limits."""


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class UploadLimits:
    max_files: int = 10
    max_file_bytes: int = 20 * MiB
    max_total_bytes: int = 50 * MiB
    max_zip_expanded_bytes: int = 80 * MiB
    max_csv_rows: int = 50_000

    @classmethod
    def from_environment(cls) -> "UploadLimits":
        return cls(
            max_files=_positive_int_env("TMC_MAX_UPLOAD_FILES", cls.max_files),
            max_file_bytes=_positive_int_env(
                "TMC_MAX_UPLOAD_FILE_MB", cls.max_file_bytes // MiB
            )
            * MiB,
            max_total_bytes=_positive_int_env(
                "TMC_MAX_UPLOAD_TOTAL_MB", cls.max_total_bytes // MiB
            )
            * MiB,
            max_zip_expanded_bytes=_positive_int_env(
                "TMC_MAX_ZIP_EXPANDED_MB", cls.max_zip_expanded_bytes // MiB
            )
            * MiB,
            max_csv_rows=_positive_int_env("TMC_MAX_CSV_ROWS", cls.max_csv_rows),
        )


PUBLIC_UPLOAD_LIMITS = UploadLimits.from_environment()
ALLOWED_UPLOAD_SUFFIXES = {".html", ".htm", ".csv"}


def _display_bytes(value: int) -> str:
    return f"{value / MiB:g} MB"


def validate_upload_batch(
    files: Iterable[Mapping[str, object]],
    *,
    limits: UploadLimits = PUBLIC_UPLOAD_LIMITS,
) -> None:
    """Validate Streamlit upload bytes before they reach parsers or disk."""
    items = list(files)
    if not items:
        raise UploadLimitError("请至少选择一个数据文件。")
    if len(items) > limits.max_files:
        raise UploadLimitError(f"一次最多上传 {limits.max_files} 个文件。")

    total = 0
    for item in items:
        name = Path(str(item.get("name") or "")).name
        suffix = Path(name).suffix.casefold()
        raw = item.get("bytes")
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise UploadLimitError(f"不支持的文件类型：{name or '未命名文件'}")
        if not isinstance(raw, bytes):
            raise UploadLimitError(f"无法读取上传文件：{name or '未命名文件'}")
        if len(raw) > limits.max_file_bytes:
            raise UploadLimitError(
                f"{name} 超过单文件 {_display_bytes(limits.max_file_bytes)} 限制。"
            )
        total += len(raw)
        if suffix in {".html", ".htm"}:
            _validate_embedded_zip(name, raw, limits)
        elif suffix == ".csv":
            _validate_csv_rows(name, raw, limits)

    if total > limits.max_total_bytes:
        raise UploadLimitError(
            f"本次上传总量超过 {_display_bytes(limits.max_total_bytes)} 限制。"
        )


def _validate_embedded_zip(name: str, raw: bytes, limits: UploadLimits) -> None:
    """Bound the compressed SingleFile variant before any entry is extracted."""
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            expanded = sum(info.file_size for info in infos)
            if any(info.flag_bits & 0x1 for info in infos):
                raise UploadLimitError(f"不接受加密压缩 HTML：{name}")
            if expanded > limits.max_zip_expanded_bytes:
                raise UploadLimitError(
                    f"{name} 解压后超过 {_display_bytes(limits.max_zip_expanded_bytes)} 限制。"
                )
    except zipfile.BadZipFile as exc:
        raise UploadLimitError(f"压缩 HTML 文件无效：{name}") from exc


def _validate_csv_rows(name: str, raw: bytes, limits: UploadLimits) -> None:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UploadLimitError(f"无法解码 CSV 文件：{name}")

    try:
        row_count = sum(1 for _ in csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise UploadLimitError(f"CSV 文件格式无效：{name}") from exc
    if row_count > limits.max_csv_rows + 1:  # one header row is allowed
        raise UploadLimitError(
            f"{name} 超过 {limits.max_csv_rows:,} 行数据限制。"
        )
