from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag


def semantic_candidates(
    soup: BeautifulSoup,
    hint_pattern: str,
    *,
    max_nodes: int = 500,
) -> list[Tag]:
    """Find likely blocks using class/id semantics without platform coupling."""
    pattern = re.compile(hint_pattern, re.IGNORECASE)
    result: list[Tag] = []
    seen: set[int] = set()
    for node in soup.find_all(["div", "li", "article", "section"]):
        attrs = " ".join(
            [
                " ".join(node.get("class", [])),
                str(node.get("id", "")),
                str(node.get("data-spm", "")),
            ]
        )
        if not pattern.search(attrs):
            continue
        identity = id(node)
        if identity not in seen:
            seen.add(identity)
            result.append(node)
        if len(result) >= max_nodes:
            break
    return result


def prune_nested(nodes: list[Tag]) -> list[Tag]:
    """Prefer leaf-like repeated cards over their containing sections."""
    identities = {id(node) for node in nodes}
    result = []
    for node in nodes:
        nested_count = sum(
            1
            for child in node.find_all(["div", "li", "article", "section"])
            if id(child) in identities
        )
        if nested_count == 0:
            result.append(node)
    return result or nodes

