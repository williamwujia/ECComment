from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from extractor.generic_blocks import prune_nested, semantic_candidates
from utils.dedupe import md5_text
from utils.text_cleaner import clean_text, split_visible_lines


QUESTION_HINT = re.compile(r"(question|ask|quest|issue|问)", re.IGNORECASE)
ANSWER_HINT = re.compile(r"(answer|reply|response|答)", re.IGNORECASE)
QA_CARD_HINT = r"(qa|question|answer|ask|everyone|wenda|问大家|问答)"


def _class_text(node: Tag, pattern: re.Pattern) -> str:
    for child in node.find_all(True):
        attrs = " ".join(child.get("class", [])) + " " + str(child.get("id", ""))
        if pattern.search(attrs):
            value = clean_text(child.get_text("\n", strip=True))
            if value:
                return value
    return ""


def _strip_prefix(text: str, prefix: str) -> str:
    return clean_text(re.sub(rf"^\s*{prefix}\s*[:：]?\s*", "", text, count=1))


def _pair_from_lines(lines: list[str]) -> tuple[str, str]:
    question = ""
    answer = ""
    for index, line in enumerate(lines):
        if re.match(r"^(?:问题|问|Q)\s*[:：]", line, re.IGNORECASE):
            question = _strip_prefix(line, r"(?:问题|问|Q)")
            if index + 1 < len(lines) and not answer:
                next_line = lines[index + 1]
                if re.match(r"^(?:回答|答|A)\s*[:：]", next_line, re.IGNORECASE):
                    answer = _strip_prefix(next_line, r"(?:回答|答|A)")
        elif re.match(r"^(?:回答|答|A)\s*[:：]", line, re.IGNORECASE):
            answer = _strip_prefix(line, r"(?:回答|答|A)")

    if not question and len(lines) >= 2:
        useful = [
            line
            for line in lines
            if not re.fullmatch(r"(?:已购|查看.*|全部回答|\d+个?回答)", line)
        ]
        if len(useful) >= 2:
            question, answer = useful[0], useful[1]
    return clean_text(question), clean_text(answer)


def _extract_tags(soup: BeautifulSoup) -> str:
    tags: list[str] = []
    for node in soup.select("[class*='conditionItem--']"):
        count_node = node.select_one("[class*='conditionItemCount--']")
        count = clean_text(count_node.get_text(" ", strip=True) if count_node else "")
        if count_node:
            count_node.extract()
        name = clean_text(node.get_text(" ", strip=True))
        if name and name not in tags:
            tags.append(f"{name}:{count}" if count else name)
    if tags:
        return ";".join(tags[:30])

    for node in soup.find_all(["button", "li", "span", "div"]):
        attrs = " ".join(node.get("class", [])) + " " + str(node.get("id", ""))
        if not re.search(r"(tag|filter|topic)", attrs, re.IGNORECASE):
            continue
        value = clean_text(node.get_text(" ", strip=True))
        match = re.fullmatch(r"([\u4e00-\u9fffA-Za-z]{1,10})\s*(\d{1,7})?", value)
        if match and value not in tags:
            tags.append(
                f"{match.group(1)}:{match.group(2)}"
                if match.group(2)
                else match.group(1)
            )
        if len(tags) >= 30:
            break
    return ";".join(tags)


def _candidate_cards(soup: BeautifulSoup) -> list[Tag]:
    selectors = (
        "[class*='qaItem--']",
        "[class*='question-item']",
        "[class*='QuestionItem']",
        "[class*='qa-item']",
        "[class*='QaItem']",
        "[class*='ask-item']",
        "[class*='wenda-item']",
    )
    cards: list[Tag] = []
    for selector in selectors:
        cards.extend(soup.select(selector))
    if cards:
        return list(dict.fromkeys(cards))
    cards.extend(semantic_candidates(soup, QA_CARD_HINT))
    return prune_nested(list(dict.fromkeys(cards)))


def _tmall_pair(card: Tag) -> tuple[str, str, str]:
    """Parse the current Tmall qaItem DOM while tolerating hashed suffixes."""
    question_icon = card.select_one("[class*='questionIcon--']")
    question = ""
    if question_icon:
        sibling = question_icon.find_next_sibling()
        if sibling:
            question = clean_text(sibling.get_text(" ", strip=True))

    status_node = card.select_one("[class*='initTag--']")
    status = clean_text(status_node.get_text(" ", strip=True) if status_node else "")
    answer = ""
    if status_node:
        sibling = status_node.find_next_sibling()
        if sibling:
            answer = clean_text(sibling.get_text(" ", strip=True))

    if not answer and question_icon:
        direct_texts = [
            clean_text(child.get_text(" ", strip=True))
            for child in card.find_all(["span", "div"], recursive=True)
            if clean_text(child.get_text(" ", strip=True))
        ]
        excluded = {"问", question, "查看全部回答", status}
        candidates = [
            text
            for text in direct_texts
            if text not in excluded
            and text not in {"已购", "回头客"}
            and not text.startswith("问" + question)
        ]
        answer = candidates[-1] if candidates else ""
    return question, answer, status


def parse_taobao_qa(
    html_text: str,
    soup: BeautifulSoup,
    meta: dict,
    debug_samples: list[dict] | None = None,
) -> list[dict]:
    """Extract Taobao/Tmall Q&A pairs from repeated DOM cards."""
    if meta.get("platform") not in {"taobao", "tmall"} and "问大家" not in html_text:
        return []

    tags = _extract_tags(soup)
    pairs: list[dict] = []
    seen: set[str] = set()

    for card in _candidate_cards(soup):
        raw = clean_text(card.get_text("\n", strip=True))
        if len(raw) < 4 or len(raw) > 3000:
            continue

        question, answer, detected_status = _tmall_pair(card)
        question = question or _class_text(card, QUESTION_HINT)
        answer = answer or _class_text(card, ANSWER_HINT)
        question = _strip_prefix(question, r"(?:问题|问|Q)") if question else ""
        answer = _strip_prefix(answer, r"(?:回答|答|A)") if answer else ""
        if not question or not answer:
            fallback_question, fallback_answer = _pair_from_lines(split_visible_lines(raw))
            question = question or fallback_question
            answer = answer or fallback_answer

        if not question:
            continue
        if question == answer:
            answer = ""

        confidence = 0.9 if question and answer else 0.55
        answer_count_match = re.search(r"(\d+)\s*个?回答", raw)
        is_buyer = bool(re.search(r"(?:已购|购买过|买家)", raw))
        digest = md5_text(
            meta.get("platform"),
            meta.get("product_id"),
            question,
            answer,
        )
        if digest in seen:
            continue
        seen.add(digest)

        base = {key: meta.get(key, "") for key in (
            "source_file", "platform", "product_title", "shop_name",
            "product_url", "product_id",
        )}
        pairs.append(
            {
                **base,
                "qa_order": len(pairs) + 1,
                "question_text_raw": question,
                "question_text_clean": clean_text(question),
                "answer_text_raw": answer,
                "answer_text_clean": clean_text(answer),
                "answer_user_status": detected_status or ("已购" if is_buyer else ""),
                "answer_count": int(answer_count_match.group(1))
                if answer_count_match
                else "",
                "question_tags": tags,
                "is_buyer_answer": is_buyer,
                "qa_hash": digest,
                "extract_confidence": confidence,
            }
        )

        if not answer and debug_samples is not None:
            debug_samples.append(
                {
                    "source_file": meta.get("source_file", ""),
                    "platform": meta.get("platform", ""),
                    "debug_type": "qa_pair_uncertain",
                    "raw_block_text": raw,
                    "possible_question": question,
                    "possible_answer": "",
                    "reason": "找到问题但未能稳定识别回答",
                }
            )
    return pairs
