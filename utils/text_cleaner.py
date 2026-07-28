from __future__ import annotations

import re


# XML 1.0 (and therefore .xlsx worksheets) rejects these control characters.
# Keep tab, line feed, and carriage return because they are valid cell content.
INVALID_XML_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\uFFFE\uFFFF]")


def remove_invalid_xml_chars(text: str | None) -> str:
    """Remove characters that cannot be stored in an Excel worksheet."""
    if not text:
        return ""
    return INVALID_XML_CONTROL_RE.sub("", str(text))


OPERATION_TEXTS = (
    "查看全部回答",
    "查看全部",
    "查看更多",
    "展开",
    "收起",
    "更多",
    "追评",
    "默认好评",
)


def clean_text(text: str | None) -> str:
    """Clean platform controls while preserving consumer wording."""
    if not text:
        return ""

    value = remove_invalid_xml_chars(text).replace("\u200b", "").replace("\xa0", " ")
    for operation in OPERATION_TEXTS:
        value = re.sub(re.escape(operation), " ", value, flags=re.IGNORECASE)

    value = re.sub(r"(?m)^\s*(?:\.{3,}|…+)\s*$", " ", value)
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\s*\n\s*", "\n", value)
    value = re.sub(r"\n{2,}", "\n", value)
    return value.strip(" \t\r\n|")


def split_visible_lines(text: str | None) -> list[str]:
    """Split a rendered block into useful, cleaned text lines."""
    if not text:
        return []
    lines = []
    for line in re.split(r"[\r\n]+", text):
        cleaned = clean_text(line)
        if cleaned and cleaned not in OPERATION_TEXTS:
            lines.append(cleaned)
    return lines
