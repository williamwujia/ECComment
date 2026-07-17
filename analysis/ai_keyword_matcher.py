from __future__ import annotations

import re
from pathlib import Path

import yaml


SAFE_AI_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:AI|ai|A\.I\.)(?![A-Za-z])"
    r"|(?:问|用|让|找|请|打开|咨询)(?:AI|ai)"
    r"|(?:AI|ai)(?:推荐|建议|助手|分析|对比|说|智能|查)",
)

CASE_INSENSITIVE_SOURCES = {
    "deepseek",
    "chatgpt",
    "gpt",
    "kimi",
    "qwen",
    "gemini",
    "copilot",
}

TERM_JOINER_PATTERN = r"[\s\u00a0\u200b\u200c\u200d\ufeff·・•.\-_—–/\\|:：,，、\[\]【】()（）{}《》<>「」『』\"“”'’`]*"


def load_keywords(keyword_file: str) -> dict:
    path = Path(keyword_file).expanduser()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if "ai_sources" not in data:
        data["ai_sources"] = {
            "strong": data.get("ai_sources_strong", []),
            "generic": data.get("ai_sources_generic", []),
        }
    if data.get("ai_sources_specific"):
        data["ai_sources"]["strong"] = data["ai_sources_specific"]
    if data.get("ai_sources_generic"):
        data["ai_sources"]["generic"] = data["ai_sources_generic"]
    data.setdefault("ai_entry_weak", [])
    data.setdefault("research_intensive", [])
    data.setdefault("human_service_sources", [])
    data.setdefault("exclude_comparison_adverbs", [])
    required = {"ai_sources", "ai_actions", "purchase_context", "decision_context"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"关键词配置缺少字段: {', '.join(sorted(missing))}")
    return data


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _flexible_term_pattern(term: str) -> str:
    compact = re.sub(r"\s+", "", term)
    return TERM_JOINER_PATTERN.join(re.escape(character) for character in compact)


def _term_matches(text: str, term: str) -> bool:
    if not text or not term:
        return False
    flags = re.IGNORECASE if re.search(r"[A-Za-z]", term) else 0
    return bool(re.search(_flexible_term_pattern(term), text, flags))


def safe_match_ai_sources(text: str, keywords: dict) -> list[str]:
    """Match AI sources without treating air/chair/pair/rain as AI."""
    if not text:
        return []
    matches: list[str] = []
    sources = keywords.get("ai_sources", {})
    strong_terms = sorted(sources.get("strong", []), key=len, reverse=True)
    for term in strong_terms:
        if any(term.casefold() in matched.casefold() for matched in matches):
            continue
        if _term_matches(text, term):
            matches.append(term)

    for term in sources.get("generic", []):
        if term in {"AI", "A.I."}:
            if SAFE_AI_PATTERN.search(text):
                matches.append("AI")
        elif term.casefold().startswith("ai"):
            if _term_matches(text, term):
                matches.append(term)
        elif _term_matches(text, term):
            matches.append(term)
    return _unique(matches)


def match_terms(text: str, terms: list[str]) -> list[str]:
    return _unique([term for term in terms if _term_matches(text, term)])


def source_strength(term: str, keywords: dict) -> str:
    strong = {value.casefold() for value in keywords["ai_sources"]["strong"]}
    return "strong" if term.casefold() in strong else "generic"
