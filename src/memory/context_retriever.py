# -*- coding: utf-8 -*-
"""유사 시장 국면 행동 지침 검색 및 AI 프롬프트 주입."""
import re

from src.memory import drive_client

MASTER_INDEX_REL = drive_client.MASTER_INDEX_REL
STOPWORDS = {"및", "등", "의", "이", "가", "을", "를", "에", "에서", "으로", "the", "and", "of"}


def _tokenize(text):
    if not text:
        return set()
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", str(text).lower())
    return {t for t in tokens if len(t) >= 2 and t not in STOPWORDS}


def extract_market_context(macro, news_snippets=None):
    """뉴스 키워드 + 시장 국면 추출."""
    news_snippets = news_snippets or []
    keywords = set()
    vix = float(macro.get("VIX", 20.0) or 20.0)
    if vix >= 30:
        keywords.update(["vix", "공포", "셧다운", "관망"])
        regime = "극단적 공포 (VIX 30+)"
    elif vix >= 25:
        keywords.update(["vix", "경계", "축소매수"])
        regime = "공포 확대 (VIX 25+)"
    else:
        regime = "보통 국면"

    kospi_chg = macro.get("KOSPI_CHG")
    kosdaq_chg = macro.get("KOSDAQ_CHG")
    if kospi_chg is not None and abs(float(kospi_chg)) >= 1.5:
        keywords.add("코스피급변")
        regime = f"코스피 {'급락' if float(kospi_chg) < 0 else '급등'} ({kospi_chg:+.2f}%)"
    if kosdaq_chg is not None and abs(float(kosdaq_chg)) >= 1.5:
        keywords.add("코스닥급변")

    for line in news_snippets[:8]:
        keywords |= _tokenize(line)

    return sorted(keywords), regime


def _score_entry(entry, query_tokens, regime):
    entry_kw = set(entry.get("keywords", []))
    overlap = len(query_tokens & entry_kw)
    score = overlap * 3
    if entry.get("regime") and regime and entry["regime"][:4] == regime[:4]:
        score += 2
    score += min(len(entry.get("guideline_summary", "")) // 20, 3)
    return score


def search_similar_guidelines(keywords, regime, top_n=3):
    if not drive_client.is_ready():
        return []
    try:
        index = drive_client.read_json_relative(MASTER_INDEX_REL) or {"entries": []}
    except Exception:
        return []

    query_tokens = _tokenize(" ".join(keywords))
    if regime:
        query_tokens |= _tokenize(regime)

    ranked = []
    for entry in index.get("entries", []):
        sc = _score_entry(entry, query_tokens, regime)
        if sc > 0:
            ranked.append((sc, entry))
    ranked.sort(key=lambda x: x[0], reverse=True)

    results = []
    for _, entry in ranked[:top_n]:
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
                "keywords": entry.get("keywords", []),
                "regime": entry.get("regime"),
                "guideline_summary": entry.get("guideline_summary", ""),
                "body_excerpt": (body or "")[:2500],
            }
        )
    return results


def build_context_injection_block(keywords, regime, top_n=3):
    entries = search_similar_guidelines(keywords, regime, top_n=top_n)
    if not entries:
        return ""

    lines = [
        "[필수 준수 배경 지식 - Market Chronicles]",
        "아래는 과거 유사 시장 국면에서 확정한 행동 지침이다. 현재 판단 시 반드시 참고하라.",
    ]
    for i, e in enumerate(entries, 1):
        kw = ", ".join(e.get("keywords", [])[:8])
        lines.append(f"--- 지침 {i} ({e.get('date', '?')}) | 키워드: {kw} ---")
        lines.append(f"요약: {e.get('guideline_summary', '')}")
        excerpt = (e.get("body_excerpt") or "").strip()
        if excerpt:
            lines.append(excerpt[:1200])
        lines.append("")
    return "\n".join(lines).strip()
