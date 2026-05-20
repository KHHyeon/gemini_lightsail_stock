# -*- coding: utf-8 -*-
"""
유사 시장 국면 행동 지침 검색 및 AI 프롬프트 주입.

v3.2 변경점:
- 단어 일치(set 교집합) 위주의 점수 함수를 **구문 단위 의미적 유사도** 우선으로 재설계.
- 구문(`keyphrases`) 자카드 + subject/action 정규형 매칭 + tone 일치 + 시장 국면(regime)
  그룹 매칭 + 최근성(recency) 가산점의 다층 가중치 합.
- 단어 토큰(`keywords`) 매칭은 구문 정보가 없을 때만 사용하는 **저우선 폴백**으로 강등.
"""
import re
from datetime import date as _date

from src.memory import drive_client

MASTER_INDEX_REL = drive_client.MASTER_INDEX_REL
STOPWORDS = {"및", "등", "의", "이", "가", "을", "를", "에", "에서", "으로", "the", "and", "of"}

REGIME_GROUPS = [
    ["VIX 30", "극단적 공포", "셧다운"],
    ["VIX 25", "공포 확대", "공포", "경계", "VIX 25 이상"],
    ["급락", "패닉", "충격", "하락"],
    ["급등", "랠리", "강세", "상승"],
    ["보통", "박스권", "평이"],
]

WEIGHT_PHRASE_EXACT = 12.0
WEIGHT_PHRASE_HIGH = 8.0
WEIGHT_PHRASE_MID = 4.0
WEIGHT_PHRASE_LOW = 2.0
WEIGHT_SUBJECT_ONLY = 1.5
WEIGHT_ACTION_ONLY = 1.5
WEIGHT_TONE_MATCH = 2.0
WEIGHT_REGIME_GROUP = 5.0
WEIGHT_TOKEN_FALLBACK = 0.5
WEIGHT_RECENCY_30D = 2.0
WEIGHT_RECENCY_90D = 1.0
WEIGHT_RECENCY_180D = 0.3


def _tokenize(text):
    if not text:
        return set()
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", str(text).lower())
    return {t for t in tokens if len(t) >= 2 and t not in STOPWORDS}


def _coerce_phrase(item):
    """str 또는 dict 형태의 phrase 입력을 dict 표준 포맷으로 정규화."""
    if isinstance(item, dict):
        return {
            "phrase": str(item.get("phrase", "")),
            "subject": str(item.get("subject", "")),
            "action": str(item.get("action", "")),
            "tone": str(item.get("tone", "neutral")).lower() or "neutral",
        }
    return {"phrase": str(item or ""), "subject": "", "action": "", "tone": "neutral"}


def _phrase_similarity(p1, p2):
    """
    두 구문의 의미적 유사도(0.0~1.0).
        - 토큰 자카드(기본)
        - subject 일치 보너스
        - action 정규형 일치 보너스
        - 정확히 같은 phrase 면 1.0
    """
    p1 = _coerce_phrase(p1)
    p2 = _coerce_phrase(p2)
    if not p1["phrase"] or not p2["phrase"]:
        return 0.0
    if p1["phrase"].strip() == p2["phrase"].strip():
        return 1.0

    t1 = _tokenize(p1["phrase"])
    t2 = _tokenize(p2["phrase"])
    if not t1 or not t2:
        jac = 0.0
    else:
        jac = len(t1 & t2) / max(1, len(t1 | t2))

    bonus = 0.0
    if p1["subject"] and p2["subject"] and p1["subject"] == p2["subject"]:
        bonus += 0.2
    if p1["action"] and p2["action"] and p1["action"] == p2["action"]:
        bonus += 0.25
    return min(1.0, jac + bonus)


def _regime_group_index(regime_text):
    if not regime_text:
        return -1
    text = str(regime_text)
    for idx, group in enumerate(REGIME_GROUPS):
        if any(kw in text for kw in group):
            return idx
    return -1


def _recency_bonus(date_str):
    if not date_str:
        return 0.0
    try:
        d = _date.fromisoformat(date_str[:10])
    except Exception:
        return 0.0
    age = (_date.today() - d).days
    if age < 0:
        return 0.0
    if age <= 30:
        return WEIGHT_RECENCY_30D
    if age <= 90:
        return WEIGHT_RECENCY_90D
    if age <= 180:
        return WEIGHT_RECENCY_180D
    return 0.0


def extract_market_context(macro, news_snippets=None):
    """
    현재 시장 국면을 분석하여 (query_phrases, regime) 을 반환한다.

    v3.2: 단어 토큰 대신 [주체+동사] 구문 후보를 우선 반환한다.
    keyphrase_extractor 의 정규식 폴백을 사용하여 지연 없이 동작한다.
    """
    from src.memory.keyphrase_extractor import extract_query_phrases

    news_snippets = news_snippets or []
    macro_dict = macro if isinstance(macro, dict) else {}

    phrases = extract_query_phrases(news_snippets=news_snippets, macro=macro_dict)
    seen = {p.get("phrase") for p in phrases}

    def _append(phrase, subject, action, tone):
        if phrase in seen:
            return
        phrases.append(
            {"phrase": phrase, "subject": subject, "action": action, "tone": tone}
        )
        seen.add(phrase)

    try:
        vix = float(macro_dict.get("VIX", 20.0) or 20.0)
    except (TypeError, ValueError):
        vix = 20.0
    if vix >= 30:
        regime = f"극단적 공포 (VIX {vix:.0f}+)"
        _append("VIX 극단적 공포", "VIX", "하락", "negative")
    elif vix >= 25:
        regime = f"공포 확대 (VIX {vix:.0f}+)"
        _append("VIX 25 이상 경계", "VIX", "경계", "negative")
    else:
        regime = "보통 국면"

    try:
        kospi_chg = float(macro_dict.get("KOSPI_CHG", 0) or 0)
    except (TypeError, ValueError):
        kospi_chg = 0.0
    if abs(kospi_chg) >= 1.5:
        if kospi_chg < 0:
            regime = f"코스피 급락 ({kospi_chg:+.2f}%)"
            _append("코스피 급락", "코스피", "하락", "negative")
        else:
            regime = f"코스피 급등 ({kospi_chg:+.2f}%)"
            _append("코스피 급등", "코스피", "상승", "positive")

    try:
        kosdaq_chg = float(macro_dict.get("KOSDAQ_CHG", 0) or 0)
    except (TypeError, ValueError):
        kosdaq_chg = 0.0
    if abs(kosdaq_chg) >= 1.5:
        if kosdaq_chg < 0:
            _append("코스닥 급락", "코스닥", "하락", "negative")
        else:
            _append("코스닥 급등", "코스닥", "상승", "positive")

    return phrases, regime


def _query_dominant_tone(query_phrases):
    """쿼리 phrase 들의 다수결 tone (positive / negative / neutral)."""
    counter = {"positive": 0, "negative": 0, "neutral": 0}
    for p in query_phrases or []:
        tone = p.get("tone") if isinstance(p, dict) else None
        if tone in counter:
            counter[tone] += 1
    if counter["negative"] > counter["positive"]:
        return "negative"
    if counter["positive"] > counter["negative"]:
        return "positive"
    return "neutral"


def _score_entry(entry, query_phrases, query_tone, regime):
    """
    v3.2 의미적 점수 함수.
        1) 구문 단위 자카드+subject/action 매칭 (높음)
        2) subject 또는 action 만 일치하는 경우도 약하게 가산
        3) tone 다수결 일치 시 가산
        4) regime 그룹 일치 시 가산
        5) 단어 토큰 폴백 (낮음)
        6) 최근성 보너스
    """
    entry_phrases = entry.get("keyphrases") or []
    entry_phrase_objs = [_coerce_phrase(p) for p in entry_phrases]

    score = 0.0
    matched_phrase = False
    for qp in query_phrases or []:
        qp_obj = _coerce_phrase(qp)
        best_sim = 0.0
        subj_only = False
        act_only = False
        for ep in entry_phrase_objs:
            sim = _phrase_similarity(qp_obj, ep)
            if sim > best_sim:
                best_sim = sim
            if qp_obj["subject"] and ep["subject"] and qp_obj["subject"] == ep["subject"] and sim < 0.5:
                subj_only = True
            if qp_obj["action"] and ep["action"] and qp_obj["action"] == ep["action"] and sim < 0.5:
                act_only = True

        if best_sim >= 0.95:
            score += WEIGHT_PHRASE_EXACT
            matched_phrase = True
        elif best_sim >= 0.6:
            score += WEIGHT_PHRASE_HIGH
            matched_phrase = True
        elif best_sim >= 0.35:
            score += WEIGHT_PHRASE_MID
            matched_phrase = True
        elif best_sim >= 0.15:
            score += WEIGHT_PHRASE_LOW
        else:
            if subj_only:
                score += WEIGHT_SUBJECT_ONLY
            if act_only:
                score += WEIGHT_ACTION_ONLY

    if query_tone and query_tone != "neutral":
        ent_tones = [p.get("tone", "neutral") for p in entry_phrase_objs]
        if ent_tones and ent_tones.count(query_tone) >= max(1, len(ent_tones) // 3):
            score += WEIGHT_TONE_MATCH

    q_idx = _regime_group_index(regime)
    e_idx = _regime_group_index(entry.get("regime", ""))
    if q_idx >= 0 and q_idx == e_idx:
        score += WEIGHT_REGIME_GROUP

    if not matched_phrase:
        entry_tokens = set(entry.get("keywords") or [])
        query_tokens = set()
        for qp in query_phrases or []:
            query_tokens |= _tokenize(_coerce_phrase(qp)["phrase"])
        overlap = len(query_tokens & entry_tokens)
        score += overlap * WEIGHT_TOKEN_FALLBACK

    score += _recency_bonus(entry.get("date"))
    return score


def search_similar_guidelines(query_phrases, regime, top_n=3, min_score=2.0):
    """
    Args:
        query_phrases: extract_market_context() 가 반환한 구문 리스트(또는 단순 str 리스트).
        regime: 현재 시장 국면 라벨.
        top_n: 반환할 최대 엔트리 수.
        min_score: 이 점수 미만은 무관 항목으로 간주.
    """
    if not drive_client.is_ready():
        return []
    try:
        index = drive_client.read_json_relative(MASTER_INDEX_REL) or {"entries": []}
    except Exception:
        return []

    query_tone = _query_dominant_tone(query_phrases)

    ranked = []
    for entry in index.get("entries", []):
        sc = _score_entry(entry, query_phrases, query_tone, regime)
        if sc >= min_score:
            ranked.append((sc, entry))
    ranked.sort(key=lambda x: x[0], reverse=True)

    results = []
    for sc, entry in ranked[:top_n]:
        body = ""
        rel = entry.get("report_rel_path")
        if rel:
            try:
                body = drive_client.read_text_relative(rel) or ""
            except Exception:
                body = entry.get("guideline_summary", "")
        else:
            body = entry.get("guideline_summary", "")
        results.append(
            {
                "date": entry.get("date"),
                "score": round(sc, 2),
                "keyphrases": entry.get("keyphrases", []),
                "keywords": entry.get("keywords", []),
                "regime": entry.get("regime"),
                "guideline_summary": entry.get("guideline_summary", ""),
                "body_excerpt": (body or "")[:2500],
            }
        )
    return results


def build_context_injection_block(query_phrases, regime, top_n=3):
    entries = search_similar_guidelines(query_phrases, regime, top_n=top_n)
    if not entries:
        return ""

    lines = [
        "[필수 준수 배경 지식 - Market Chronicles]",
        "아래는 과거 유사 시장 국면에서 확정한 행동 지침이다. 현재 판단 시 반드시 참고하라.",
    ]
    for i, e in enumerate(entries, 1):
        phrases = e.get("keyphrases") or []
        phrase_labels = []
        for p in phrases[:6]:
            if isinstance(p, dict):
                phrase_labels.append(p.get("phrase", ""))
            else:
                phrase_labels.append(str(p))
        phrase_text = " / ".join([pl for pl in phrase_labels if pl]) or "(구문 없음)"
        lines.append(
            f"--- 지침 {i} ({e.get('date', '?')}) | 점수 {e.get('score', 0)} | 구문: {phrase_text} ---"
        )
        lines.append(f"요약: {e.get('guideline_summary', '')}")
        excerpt = (e.get("body_excerpt") or "").strip()
        if excerpt:
            lines.append(excerpt[:1200])
        lines.append("")
    return "\n".join(lines).strip()
