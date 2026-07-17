from __future__ import annotations

import re

from analysis.ai_keyword_matcher import (
    match_terms,
    safe_match_ai_sources,
    source_strength,
)

GENERIC_AI_SOURCE_TERMS = {
    "AI",
    "A.I.",
    "AI助手",
    "ai助手",
    "人工智能",
    "智能助手",
    "智能问答",
    "AI搜索",
    "算法推荐",
    "系统推荐",
    "智能推荐",
    "平台推荐",
    "搜索推荐",
}
ALGORITHM_TERMS = {"算法推荐", "系统推荐", "智能推荐", "平台推荐", "搜索推荐"}
HUMAN_SERVICE_ACTION_RE = re.compile(
    r"(?:问|咨询|联系|找).{0,4}(?:客服|售前|售后|导购|店家|商家)"
    r"|(?:客服|售前|售后|导购|店家|商家).{0,8}(?:解答|推荐|介绍|回复)"
)
FALSE_COMPARE_RE = re.compile(
    r"比较(?:满意|适合|简单|柔和|亮|舒服|负责|好看|不错|足|稳定|方便|划算|实惠|细|高|自然|专业)"
    r"|光比较柔和"
)
TRUE_COMPARE_RE = re.compile(
    r"(?:对比|比较)了(?:很多|好几|好久|几款|几个|多款|多家)"
    r"|(?:和|跟).{1,20}(?:比|对比|比较)"
    r"|几个(?:品牌|牌子|型号).{0,8}比较下来"
    r"|对比(?:好多|很多|好几)(?:家|款|个|品牌|型号)?"
    r"|纠结(?:了)?(?:很久|半天|好久)?"
    r"|选了很久|研究了很久"
)
INFO_SEARCH_RE = re.compile(
    r"(?:小红书|知乎)?做(?:了)?(?:很多)?(?:攻略|功课)"
    r"|认真做了科普|做了科普|查了很多|看了很多|搜了很多|网上搜索"
    r"|抖音看了很多|看了很多(?:测评|攻略)|问了很多"
)
RISK_VALUE_RE = re.compile(r"智商税|值不值|贵不贵|性价比|物有所值|踩坑|怕踩坑|有必要买吗")
FIT_QUESTION_RE = re.compile(r"有用吗|适合.{0,8}吗|推荐买吗|后悔吗|怎么选|选哪个|推荐哪个")
LIGHT_PRE_PURCHASE_RE = re.compile(
    r"推荐购买|客服推荐|朋友推荐|家人推荐|导购推荐|活动.{0,12}(?:下单|买|入手)"
    r"|买来试试|怕.{0,8}眼睛累|希望.{0,8}近视|适合孩子|性价比高|看着不错"
)
MERCHANT_REPLY_TERMS = (
    "接受任何不满意",
    "包邮全额退",
    "免费试用",
    "不满意包邮退",
    "欢迎且支持跟任何竞品比质量",
    "十年质保",
    "包修包换",
    "买家0成本",
    "无任何后顾之忧",
    "保留原包装",
)
MERCHANT_REPLY_RE = re.compile(
    r"1[、.].*2[、.].*3[、.]|包邮.*退|质保.*包修.*包换|101天免费试用",
    re.DOTALL,
)
POST_PURCHASE_RE = re.compile(
    r"收到了|到货了|昨天下单今天就到了|下单后没两天就收到了|物流很快|物流上"
    r"|师傅上门安装|安装很及时|用了|用了一下午|用久了|目前没什么感觉"
    r"|之前家里用的灯|原来那个|另外一个我用了半年|刚到|收到货|图片没有拍出"
    r"|售后服务希望|这是买的第二台"
)
STRONG_PRE_PURCHASE_ANCHOR_RE = re.compile(
    r"买之前|买前|购买前|下单前|入手前|选之前|决定之前|最后选|最终选择|终于确定"
    r"|对比(?:了)?很多品牌后|做了很多功课后"
    r"|(?:推荐|建议|让我|叫我).{0,4}(?:买|购买|入手|下单)"
)
POST_PURCHASE_COMPARISON_RE = re.compile(
    r"和之前.*灯.*对比|和原来.*灯.*对比|和之前家里用的.*对比"
    r"|比之前那个|比原来那个|原来那个|另外一个我用了|用了半年"
)
PRICE_DISPUTE_RE = re.compile(
    r"价格比京东贵|淘宝百亿补贴|第三方比价|不给赔|完全不给赔|价保|保价|赔付|补差价"
)
C_RESEARCH_RE = re.compile(
    r"对比了?(?:很多|好多|多家|多个|几家|几款|不少).*?(?:品牌|型号|产品|款|家)"
    r"|(?:网上搜索|小红书|知乎|抖音|看了很多|查了很多|做了很多功课|做功课|做攻略|看攻略|看测评).*?(?:对比|比较|选|选择)"
    r"|(?:选了很久|纠结很久|研究了很久).*?(?:最后|最终|终于|确定|选择|下单|买)"
    r"|(?:最终|最后|终于).*?(?:选择|确定|选了|买了|下单)"
)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def is_merchant_reply_like(text: str) -> bool:
    hits = sum(term in text for term in MERCHANT_REPLY_TERMS)
    return hits >= 2 or bool(MERCHANT_REPLY_RE.search(text))


def has_strong_pre_purchase_anchor(text: str) -> bool:
    return bool(STRONG_PRE_PURCHASE_ANCHOR_RE.search(text))


def is_after_purchase_context(text: str) -> bool:
    return bool(POST_PURCHASE_RE.search(text))


def is_price_dispute_context(text: str) -> bool:
    return bool(PRICE_DISPUTE_RE.search(text))


def is_post_purchase_comparison(text: str) -> bool:
    return bool(POST_PURCHASE_COMPARISON_RE.search(text))


def pre_purchase_block_reason(text: str) -> str:
    if is_merchant_reply_like(text):
        return "merchant_reply_like_text"
    if is_price_dispute_context(text) and not has_strong_pre_purchase_anchor(text):
        return "after_purchase_price_dispute"
    if is_post_purchase_comparison(text) and not has_strong_pre_purchase_anchor(text):
        return "post_purchase_comparison"
    if is_after_purchase_context(text) and not has_strong_pre_purchase_anchor(text):
        return "post_purchase_experience"
    return ""


def detect_research_intensive(text: str, keywords: dict) -> tuple[bool, list[str]]:
    compare_text = FALSE_COMPARE_RE.sub("", text or "")
    terms = match_terms(compare_text, keywords.get("research_intensive", []))
    if C_RESEARCH_RE.search(compare_text):
        terms.append("对比筛选")
    if INFO_SEARCH_RE.search(text) and re.search(r"选|选择|对比|比较|买|下单|最终|最后", text):
        terms.append("信息搜集")
    return bool(terms), _unique(terms)


def detect_pre_purchase(text: str, keywords: dict) -> tuple[bool, list[str], str]:
    """Detect purchase-decision context without treating it as AI evidence."""
    terms: list[str] = []
    reasons: list[str] = []

    compare_text = FALSE_COMPARE_RE.sub("", text or "")
    if has_strong_pre_purchase_anchor(text):
        terms.append("明确购前决策")
        reasons.append("存在买前、下单前、最终选择或推荐购买等明确购前锚点")
    if TRUE_COMPARE_RE.search(compare_text):
        terms.append("比较/选择")
        reasons.append("存在筛选、对比或纠结语境")
    if INFO_SEARCH_RE.search(text):
        terms.append("攻略/信息搜集")
        reasons.append("存在攻略、功课或信息搜集语境")
    if RISK_VALUE_RE.search(text):
        terms.append("风险/价值判断")
        reasons.append("存在值不值、智商税或踩坑等风险判断")
    if FIT_QUESTION_RE.search(text):
        terms.append("效用/适配疑问")
        reasons.append("存在适配、效用或购买建议疑问")
    if LIGHT_PRE_PURCHASE_RE.search(text):
        terms.append("普通购前决策")
        reasons.append("存在推荐、活动、适配或尝试购买等普通购前决策语境")
    if HUMAN_SERVICE_ACTION_RE.search(text):
        terms.append("人工咨询")
        reasons.append("存在客服、导购或商家等人工来源咨询")

    # Keep configured decision terms, but ignore plain false-comparison adjectives.
    configured = [
        term
        for term in match_terms(compare_text, keywords.get("decision_context", []))
        if term not in {"比较", "适合吗"} or not FALSE_COMPARE_RE.search(text)
    ]
    if configured:
        terms.extend(configured)
        reasons.append("命中购前决策关键词")

    return bool(terms), _unique(terms), "；".join(_unique(reasons))


def _is_human_service_only(text: str, ai_sources: list[str], weak_sources: list[str]) -> bool:
    return bool(HUMAN_SERVICE_ACTION_RE.search(text)) and not ai_sources and not weak_sources


def detect_source_type(
    text: str,
    specific_sources: list[str],
    generic_sources: list[str],
    algorithm_terms: list[str],
    research_terms: list[str],
) -> str:
    has_human = bool(HUMAN_SERVICE_ACTION_RE.search(text))
    if specific_sources:
        return "specific_ai"
    if algorithm_terms:
        return "algorithm_or_system"
    if generic_sources:
        return "generic_ai"
    if research_terms:
        if has_human:
            return "mixed_research_and_customer_service"
        if re.search(r"小红书|知乎|抖音", text):
            return "social_media_research"
        if re.search(r"搜索|搜了|查了", text):
            return "search_research"
        return "content_research"
    if has_human:
        return "customer_service"
    if re.search(r"朋友|同事|家人", text):
        return "friends_or_family"
    return "unknown"


def extract_matched_sentence(text: str, matched_terms: list[str]) -> str:
    if not text:
        return ""
    if len(text) <= 80:
        return text
    compact_text = re.sub(r"\s+", "", text)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"[。！？!?；;\r\n]+", text)
        if sentence.strip()
    ]
    matched = [
        sentence
        for sentence in sentences
        if any(
            re.sub(r"\s+", "", term).casefold()
            in re.sub(r"\s+", "", sentence).casefold()
            for term in matched_terms
        )
    ]
    if matched:
        return " || ".join(dict.fromkeys(matched))
    positions = [
        compact_text.casefold().find(re.sub(r"\s+", "", term).casefold())
        for term in matched_terms
        if compact_text.casefold().find(re.sub(r"\s+", "", term).casefold()) >= 0
    ]
    if positions:
        start = max(0, min(positions) - 40)
        return text[start : start + 80]
    return text[:80]


def assign_evidence_level(record: dict) -> dict:
    item = dict(record)
    not_pre_purchase_reason = item.get("_not_pre_purchase_reason", "")
    specific_source = bool(item.get("_specific_ai_source_hit"))
    generic_source = bool(item.get("_generic_ai_source_hit"))
    research_inferred = bool(item.get("_research_inferred_hit"))
    pre_purchase = bool(item.get("pre_purchase_decision"))

    if not_pre_purchase_reason:
        level = ""
        evidence_type = "none"
        reason = ""
    elif specific_source:
        level = "A"
        evidence_type = "explicit"
        reason = "明确提到具体AI工具，作为信息来源或决策上下文"
    elif generic_source:
        level = "B"
        evidence_type = "generic"
        reason = "提到泛AI、算法、系统或智能推荐入口"
    elif research_inferred and pre_purchase:
        level = "C"
        evidence_type = "inferred"
        reason = "高强度购前调研下的AI介入可能，需要人工复核"
    elif pre_purchase:
        level = "D"
        evidence_type = "none"
        reason = item.get("exclude_reason") or "普通购前决策评论，无AI入口，也无高强度调研"
    else:
        level = ""
        evidence_type = "none"
        reason = ""
    ai_candidate = level in {"A", "B", "C"}
    item["ai_influence_level"] = level
    item["ai_evidence_type"] = evidence_type
    item["ai_level_reason"] = reason
    item["evidence_level"] = level
    item["evidence_reason"] = reason
    item["ai_candidate"] = ai_candidate
    item["ai_candidate_gate_reason"] = item.get("ai_candidate_gate_reason", "")
    item["ai_related"] = item["ai_candidate"]
    item["excluded_by_rule"] = not ai_candidate
    if not_pre_purchase_reason:
        item["exclude_reason"] = not_pre_purchase_reason
    if ai_candidate:
        item["exclude_reason"] = ""
    return item


def analyze_ai_related(record: dict, keywords: dict) -> dict:
    item = dict(record)
    text = item.get("content_text_clean", "")
    parent = item.get("parent_text_clean", "")
    sources = safe_match_ai_sources(text, keywords)
    parent_sources = safe_match_ai_sources(parent, keywords)
    weak_sources = match_terms(text, keywords.get("ai_entry_weak", []))
    actions = match_terms(text, keywords.get("ai_actions", []))
    purchases = match_terms(text, keywords.get("purchase_context", []))
    compare_text = FALSE_COMPARE_RE.sub("", text)
    decisions = match_terms(compare_text, keywords.get("decision_context", []))
    block_reason = pre_purchase_block_reason(text)
    pre_purchase, pre_terms, pre_reason = detect_pre_purchase(text, keywords)
    if block_reason:
        pre_purchase, pre_terms, pre_reason = False, [], ""
    research_hit, research_terms = detect_research_intensive(text, keywords)
    if block_reason:
        research_hit, research_terms = False, []

    source_terms = _unique(sources + weak_sources)
    specific_sources = [
        term for term in sources if source_strength(term, keywords) == "strong"
    ]
    generic_sources = [
        term for term in source_terms if term in GENERIC_AI_SOURCE_TERMS
    ]
    algorithm_terms = [term for term in source_terms if term in ALGORITHM_TERMS]

    human_service_only = _is_human_service_only(text, sources, weak_sources)
    generic_gate = bool(generic_sources) and not human_service_only
    inferred_gate = bool(research_hit and pre_purchase and not sources and not weak_sources and not block_reason)
    ai_candidate = bool(specific_sources or generic_gate or inferred_gate)
    excluded_by_rule = not ai_candidate
    if human_service_only:
        ai_candidate = False
        excluded_by_rule = True
        exclude_reason = "命中客服、导购或商家等人工来源，不作为AI候选"
    elif block_reason:
        ai_candidate = False
        excluded_by_rule = True
        exclude_reason = block_reason
    elif not source_terms and not research_hit:
        exclude_reason = "未命中AI入口词或高强度调研行为"
    elif research_hit and not pre_purchase:
        exclude_reason = "命中调研词，但购前决策语境不足"
    else:
        exclude_reason = ""

    if ai_candidate:
        if specific_sources:
            gate_reason = "命中具体AI来源词"
        elif generic_sources:
            gate_reason = "命中泛AI、算法或智能推荐入口"
        else:
            gate_reason = "命中高强度购前调研行为，推定AI介入可能"
    else:
        gate_reason = exclude_reason

    score = len(specific_sources) * 6 + len(generic_sources) * 4
    score += len(weak_sources) * 2
    score += len(research_terms) * 2
    score += 3 if actions else 0
    score += 2 if purchases else 0
    score += 2 if decisions or pre_purchase else 0
    if item.get("content_role") in {"question", "answer"} and (sources or parent_sources):
        score += 1

    source_type = detect_source_type(
        text, specific_sources, generic_sources, algorithm_terms, research_terms
    )
    all_terms = _unique(source_terms + research_terms + actions + purchases + decisions + pre_terms)
    item.update(
        {
            "pre_purchase_decision": pre_purchase,
            "pre_purchase_terms": ";".join(pre_terms),
            "pre_purchase_reason": pre_reason,
            "ai_candidate": ai_candidate,
            "ai_candidate_gate_reason": gate_reason,
            "research_terms": ";".join(research_terms),
            "algorithm_terms": ";".join(algorithm_terms),
            "source_type": source_type,
            "ai_source_hit": bool(source_terms),
            "ai_source_terms": ";".join(source_terms),
            "ai_action_hit": bool(actions),
            "ai_action_terms": ";".join(actions),
            "purchase_context_hit": bool(purchases),
            "purchase_context_terms": ";".join(purchases),
            "decision_context_hit": bool(decisions),
            "decision_context_terms": ";".join(decisions),
            "matched_keywords": ";".join(all_terms),
            "matched_sentence": extract_matched_sentence(text, all_terms),
            "match_score": score,
            "excluded_by_rule": excluded_by_rule,
            "exclude_reason": exclude_reason,
            "_not_pre_purchase_reason": block_reason,
            "_specific_ai_source_hit": bool(specific_sources),
            "_generic_ai_source_hit": bool(generic_sources),
            "_research_inferred_hit": bool(inferred_gate),
        }
    )
    return assign_evidence_level(item)
