# -*- coding: utf-8 -*-
"""
Market Chronicles v3.2 - 키프레이즈 추출기.

목적: master_index.json 에 저장되는 색인이 단순 단어 나열일 때
        "외국인 매수" vs "외국인 매도" 같은 정반대 의미를 같다고 오판할 위험이 있다.
        본 모듈은 [주체 + 동사/행동] 결합 핵심 구문을 추출하여 문맥 왜곡을 차단한다.

전략:
    1) 1순위: Gemini 에게 리포트 본문을 주고 JSON 배열로 핵심 구문을 요청.
    2) 2순위(폴백): 정규식 사전 기반으로 [주체 + 동사] 패턴 직접 매칭.
       - AI 호출 실패, 타임아웃, JSON 파싱 실패 등 어떤 이유로든 1순위가 비면 자동 대체.

반환 포맷(둘 다 동일):
    list[dict] = [
        {"phrase": "외국인 대량 매도", "subject": "외국인",
         "action": "매도",      "tone": "negative"},
        {"phrase": "Fed 금리 동결", "subject": "Fed",
         "action": "동결",      "tone": "positive"},
        ...
    ]

설계 원칙:
    - tone 은 negative / positive / neutral 세 값으로 한정 (검색 가중치에 사용).
    - subject 와 action 은 정규화된 한국어 키워드 (검색 매칭 시 그룹 일치 보너스).
"""
import json
import re

SUBJECTS = [
    "외국인", "기관", "개인", "연기금", "투신", "사모", "은행", "보험",
    "Fed", "연준", "FOMC", "한은", "한국은행", "BOJ", "ECB",
    "코스피", "코스닥", "나스닥", "S&P", "다우", "VIX", "WTI", "달러",
    "원화", "원달러", "위안화", "엔화", "환율", "국채", "금리",
    "반도체", "2차전지", "바이오", "조선", "건설", "금융", "화학",
    "자동차", "철강", "정유", "유틸리티", "방산", "AI", "로봇", "원전",
    "삼성전자", "SK하이닉스", "현대차", "기아", "LG에너지솔루션",
    "트럼프", "백악관", "재무부", "정부",
]

ACTION_BUY = ["매수", "순매수", "매집", "사들였", "사들이"]
ACTION_SELL = ["매도", "순매도", "매물", "팔았", "팔아치"]
ACTION_UP = ["급등", "강세", "반등", "상승", "랠리", "신고가", "사상최고"]
ACTION_DOWN = ["급락", "약세", "조정", "하락", "급변", "공포", "패닉", "신저가"]
ACTION_POLICY_HAWK = ["인상", "긴축", "테이퍼", "긴급인상"]
ACTION_POLICY_DOVE = ["인하", "완화", "동결", "양적완화", "기대인하"]
ACTION_NEUTRAL = ["동결", "발표", "공시", "확정", "발언", "회의"]

TONE_MAP = {
    **{a: "negative" for a in ACTION_SELL},
    **{a: "negative" for a in ACTION_DOWN},
    **{a: "positive" for a in ACTION_BUY},
    **{a: "positive" for a in ACTION_UP},
    **{a: "negative" for a in ACTION_POLICY_HAWK},
    **{a: "positive" for a in ACTION_POLICY_DOVE},
    **{a: "neutral" for a in ACTION_NEUTRAL},
}

_ALL_ACTIONS = sorted(
    set(
        ACTION_BUY
        + ACTION_SELL
        + ACTION_UP
        + ACTION_DOWN
        + ACTION_POLICY_HAWK
        + ACTION_POLICY_DOVE
        + ACTION_NEUTRAL
    ),
    key=len,
    reverse=True,
)

_SUBJECT_ALT = "|".join(re.escape(s) for s in sorted(SUBJECTS, key=len, reverse=True))
_ACTION_ALT = "|".join(re.escape(a) for a in _ALL_ACTIONS)
_PHRASE_RE = re.compile(
    rf"({_SUBJECT_ALT})\s*(대량|순|선제적|적극적|소폭)?\s*({_ACTION_ALT})"
)


def _normalize_action(action_text):
    """정규형 동사로 변환 (검색 시 그룹 매칭에 사용)."""
    for kw in ACTION_BUY:
        if kw in action_text:
            return "매수"
    for kw in ACTION_SELL:
        if kw in action_text:
            return "매도"
    for kw in ACTION_UP:
        if kw in action_text:
            return "상승"
    for kw in ACTION_DOWN:
        if kw in action_text:
            return "하락"
    for kw in ACTION_POLICY_HAWK:
        if kw in action_text:
            return "긴축"
    for kw in ACTION_POLICY_DOVE:
        if kw in action_text:
            return "완화"
    return action_text


def _infer_tone(action_norm):
    if action_norm in ("매수", "상승", "완화"):
        return "positive"
    if action_norm in ("매도", "하락", "긴축"):
        return "negative"
    return "neutral"


def _regex_extract(text):
    """AI 실패 시 폴백: 정규식 사전으로 [주체+동사] 직접 매칭."""
    if not text:
        return []
    seen = set()
    results = []
    for match in _PHRASE_RE.finditer(text):
        subject = match.group(1)
        modifier = (match.group(2) or "").strip()
        action_raw = match.group(3)
        phrase_parts = [subject]
        if modifier:
            phrase_parts.append(modifier)
        phrase_parts.append(action_raw)
        phrase = " ".join(phrase_parts)
        key = (subject, action_raw, modifier)
        if key in seen:
            continue
        seen.add(key)
        action_norm = _normalize_action(action_raw)
        results.append(
            {
                "phrase": phrase,
                "subject": subject,
                "action": action_norm,
                "tone": _infer_tone(action_norm),
            }
        )
        if len(results) >= 15:
            break
    return results


def _build_ai_prompt(report_text):
    return f"""
[작업] 아래 시황 리포트에서 "주체(누가/무엇이) + 동사(어떻게 행동/움직)" 결합 핵심 구문을 5~12개 뽑아라.

[좋은 예]
- "외국인 대량 매도"
- "Fed 금리 동결"
- "반도체 섹터 강세"
- "원달러 환율 급등"
- "기관 선제적 매수"

[금지 사항]
- 단일 단어만 뽑지 말 것 (예: "시장", "투자자", "변동성")
- 주관적 형용사 위주 구문 금지 (예: "큰 충격", "강한 영향")
- 중복 의미 구문은 1개로 통합

[출력 형식]
오직 JSON 배열로만 답하라. 주석/설명/코드펜스 금지. 형식:
[
  {{"phrase": "외국인 대량 매도", "subject": "외국인", "action": "매도", "tone": "negative"}},
  {{"phrase": "Fed 금리 동결",   "subject": "Fed",     "action": "동결", "tone": "positive"}}
]

tone 은 negative | positive | neutral 중 정확히 하나로 채워라.

[분석 대상 리포트]
{report_text[:6000]}
""".strip()


def _try_parse_json_array(raw):
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        parsed = json.loads(snippet)
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    return parsed


def _ai_extract(report_text):
    try:
        from src.strategy import ai_logic as ai_strategy
    except Exception:
        return []
    prompt = _build_ai_prompt(report_text)
    try:
        raw = ai_strategy.generate_text(prompt)
    except Exception as exc:
        print(f"Log: [KeyphraseExtractor AI error] {exc}", flush=True)
        return []
    parsed = _try_parse_json_array(raw)
    if not parsed:
        return []
    normalized = []
    seen = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase", "")).strip()
        subject = str(item.get("subject", "")).strip()
        action = _normalize_action(str(item.get("action", "")).strip())
        tone = str(item.get("tone", "")).strip().lower()
        if tone not in ("positive", "negative", "neutral"):
            tone = _infer_tone(action)
        if not phrase or len(phrase) < 3:
            continue
        key = phrase
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "phrase": phrase,
                "subject": subject or "",
                "action": action or "",
                "tone": tone,
            }
        )
        if len(normalized) >= 15:
            break
    return normalized


def extract_keyphrases(report_text, max_phrases=12, ai_enabled=True):
    """
    리포트 본문에서 [주체+동사] 결합 핵심 구문을 추출한다.

    Args:
        report_text: 분석 대상 본문 (시황 리포트, 뉴스 모음 등).
        max_phrases: 반환할 최대 구문 수.
        ai_enabled: True 면 Gemini 호출 1차 시도. False 면 정규식만 사용.

    Returns:
        list[dict] - 각 항목: {phrase, subject, action, tone}
    """
    if not report_text or not str(report_text).strip():
        return []

    phrases = []
    if ai_enabled:
        phrases = _ai_extract(str(report_text))

    if len(phrases) < 3:
        regex_phrases = _regex_extract(str(report_text))
        existing = {p["phrase"] for p in phrases}
        for p in regex_phrases:
            if p["phrase"] in existing:
                continue
            phrases.append(p)
            existing.add(p["phrase"])

    return phrases[:max_phrases]


def derive_tokens(phrases):
    """검색 폴백/하위 호환용: phrases 에서 단어 토큰을 파생."""
    tokens = set()
    for p in phrases or []:
        phrase = p.get("phrase") if isinstance(p, dict) else str(p)
        if not phrase:
            continue
        for tok in re.findall(r"[가-힣a-zA-Z0-9]{2,}", phrase):
            tokens.add(tok)
    return sorted(tokens)


def extract_query_phrases(news_snippets=None, macro=None):
    """
    검색 시점(매수/매도 판단)의 현재 컨텍스트에서 phrase 후보를 뽑는다.
    AI 호출 없이 정규식만 사용 (지연 최소화).
    """
    text_parts = []
    if news_snippets:
        for n in news_snippets[:12]:
            text_parts.append(str(n))
    if macro:
        if isinstance(macro, dict):
            text_parts.append(str(macro.get("ai_summary", "")))
        else:
            text_parts.append(str(macro))
    combined = "\n".join(text_parts)
    return _regex_extract(combined)
