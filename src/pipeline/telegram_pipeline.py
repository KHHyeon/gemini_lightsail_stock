# -*- coding: utf-8 -*-
"""Telegram Ingestion Pipeline.

본 모듈의 단일 책임:
    1) src/core/telegram_client.py 를 통해 raw 메시지를 받아온다.
    2) 정규화(파싱/필터/길이 상한)하여 telegram_message_dict 리스트로 변환한다.
    3) 결과(telegram_ingestion_result_dict)를 오케스트레이터에 반환한다.

본 모듈은 후속 도메인 모듈(Market Chronicles 적재기, ai_logic 등)을 import 하지
않는다. 인덱스 적재·AI 주입은 오케스트레이터가 본 결과를 받아 위임 라우팅한다
(관심사 분리, 의존성 단방향).

에러 정책 (A-Type 격리):
    - 본 모듈의 모든 공개 함수는 호출자에게 예외를 던지지 않는다.
    - 외부 장애·일시 오류는 결과 dict 의 status / note 필드로만 표현한다.
    - 트레이딩 코어의 실행 흐름은 텔레그램 장애와 무관하게 진행된다.
"""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv

from src.core import telegram_client
from src.utils.jsonio import read_local_json, write_local_json
from src.utils.paths import project_root

load_dotenv()

MAX_TEXT_LENGTH = 1000
LAST_ID_MAP_FILENAME = "telegram_last_id_map.json"


def run_ingestion(channel_id_list=None):
    """텔레그램 수집·정제 + 결과 반환(적재 없음).

    Args:
        channel_id_list: 수집 대상 채널 식별자 리스트. None 이면 운영 설정 기본값.

    Returns:
        dict: telegram_ingestion_result_dict.
            - status: "ok" | "disabled" | "transient_error"
            - message_list: list[telegram_message_dict]
            - last_id_map: 갱신된 채널별 마지막 메시지 식별자 맵
            - skipped_count: 정규화 스킵 수
            - note: 운영자 안내가 필요한 경우의 간단 사유
    """
    empty_result = {
        "status": "disabled",
        "message_list": [],
        "last_id_map": {},
        "skipped_count": 0,
        "note": "",
    }

    try:
        if not telegram_client.is_configured():
            empty_result["note"] = "텔레그램 인증/채널 설정 누락"
            return empty_result

        target_channel_id_list = list(channel_id_list or _load_default_channel_id_list())
        if not target_channel_id_list:
            empty_result["note"] = "수집 대상 채널 목록이 비어 있음"
            return empty_result

        last_id_map = _load_last_id_map()
        raw_message_list = telegram_client.fetch_new_messages(
            target_channel_id_list, last_id_map
        )

        if not raw_message_list:
            # 외부 일시 장애와 단순 신규 미발생을 구분하지 못하므로 보수적으로 ok 처리.
            return {
                "status": "ok",
                "message_list": [],
                "last_id_map": last_id_map,
                "skipped_count": 0,
                "note": "",
            }

        message_list = []
        skipped_count = 0
        for raw_dict in raw_message_list:
            normalized_dict = normalize_message(raw_dict)
            if normalized_dict is None:
                skipped_count += 1
                continue
            message_list.append(normalized_dict)

        updated_last_id_map = _update_last_id_map(last_id_map, message_list)
        _save_last_id_map(updated_last_id_map)

        return {
            "status": "ok",
            "message_list": message_list,
            "last_id_map": updated_last_id_map,
            "skipped_count": skipped_count,
            "note": "",
        }
    except Exception as exc:
        # 어떤 예외도 호출자에게 전파하지 않는다 (A-Type 격리).
        print(f"Log: [TelegramPipeline] 캡슐화: {exc}")
        return {
            "status": "transient_error",
            "message_list": [],
            "last_id_map": {},
            "skipped_count": 0,
            "note": str(exc),
        }


# 해외 글로벌 리더 기본 목록 (R3 사양: env 또는 별도 설정 분리 관리).
# 운영 환경에서는 TG_GLOBAL_LEADER_LIST 환경 변수로 override 가능.
_DEFAULT_GLOBAL_LEADER_SET = {
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "GOOG",
    "TSMC", "TSM", "AMD", "INTC", "MU", "ASML", "QCOM", "AVGO",
    "BABA", "SE", "JPM", "BAC", "BRK.B",
}

# 국내 종목 코드 정규식 (6자리 숫자).
_KR_TICKER_PATTERN = re.compile(r"\b(\d{6})\b")


def normalize_message(raw_dict):
    """단일 raw 메시지를 telegram_message_dict 로 변환 + analysis 중첩 dict 합성.

    Args:
        raw_dict: telegram_client.fetch_new_messages 가 반환한 단일 원본 dict.

    Returns:
        dict | None: 정규화 결과(telegram_message_dict). 정규화 불가 시 None.
            반환 키: source_channel, message_id, posted_at, text, keyword_list, analysis.
            analysis 키: category, related_kr_tickers, value_chain_type, transmission_path.
    """
    try:
        if not isinstance(raw_dict, dict):
            return None
        channel_id = raw_dict.get("channel_id")
        message_id = raw_dict.get("message_id")
        posted_at = raw_dict.get("posted_at")
        raw_text = raw_dict.get("raw_text") or ""

        if not channel_id or message_id is None:
            return None
        if not isinstance(raw_text, str) or not raw_text.strip():
            return None

        clean_text = raw_text.strip()[:MAX_TEXT_LENGTH]
        keyword_list = _extract_keyword_list(clean_text)
        analysis_dict = _build_analysis_dict(clean_text)

        return {
            "source_channel": str(channel_id),
            "message_id": int(message_id),
            "posted_at": posted_at,
            "text": clean_text,
            "keyword_list": keyword_list,
            "analysis": analysis_dict,
        }
    except Exception as exc:
        print(f"Log: [TelegramPipeline] normalize_message 캡슐화: {exc}")
        return None


def _extract_keyword_list(clean_text):
    """텍스트에서 보조 키워드를 추출(국내 종목코드 6자리 + 해외 글로벌 리더 심볼).

    AI 호출 없이 결정론적 추출만 수행한다(토큰 효율).
    """
    if not clean_text:
        return []
    kw_set = set(_KR_TICKER_PATTERN.findall(clean_text))
    upper = clean_text.upper()
    for sym in _global_leader_set():
        if sym in upper:
            kw_set.add(sym)
    return sorted(kw_set)


def _global_leader_set():
    """env override 또는 기본 글로벌 리더 집합."""
    raw = os.getenv("TG_GLOBAL_LEADER_LIST", "").strip()
    if not raw:
        return _DEFAULT_GLOBAL_LEADER_SET
    return {item.strip().upper() for item in raw.split(",") if item.strip()}


def _classify_category(clean_text):
    """국내 종목 / 해외 종목 / 국내 시황 / 해외 시황 분류 (결정론적 휴리스틱).

    AI 비용 없이 정규화 단계에서 1차 라우팅만 결정한다.
    """
    upper = clean_text.upper()
    has_kr_ticker = bool(_KR_TICKER_PATTERN.search(clean_text))
    has_overseas_symbol = any(sym in upper for sym in _global_leader_set())

    overseas_market_keyword_list = [
        "S&P", "NASDAQ", "다우", "FOMC", "FED", "연준", "10년물", "WTI", "DXY",
        "환율", "달러인덱스", "필라델피아", "VIX",
    ]
    has_overseas_market = any(kw in clean_text or kw in upper for kw in overseas_market_keyword_list)

    if has_kr_ticker and not has_overseas_symbol:
        return "DOMESTIC_STOCK"
    if has_overseas_symbol:
        return "OVERSEAS_STOCK"
    if has_overseas_market:
        return "OVERSEAS_MARKET"
    return "DOMESTIC_MARKET"


def _find_first_overseas_symbol(clean_text):
    """본문에서 첫 번째 해외 글로벌 리더 심볼을 찾아 반환(없으면 None)."""
    upper = clean_text.upper()
    for sym in _global_leader_set():
        if sym in upper:
            return sym
    return None


def _build_analysis_dict(clean_text):
    """analysis 중첩 dict 생성.

    - DOMESTIC_STOCK: 본문 6자리 코드 추출.
    - OVERSEAS_STOCK: ai_logic.analyze_value_chain 호출로 국내 밸류체인 매핑.
    - OVERSEAS_MARKET: ai_logic.extract_transmission_path 호출로 3문장 전이 추론.
    - DOMESTIC_MARKET: 본문 6자리 코드만 추출.

    AI 호출 실패는 빈 값으로 폴백한다(예외 전파 없음, A-Type 격리).
    """
    category = _classify_category(clean_text)
    analysis_dict = {
        "category": category,
        "related_kr_tickers": [],
        "value_chain_type": None,
        "transmission_path": "",
    }

    try:
        kr_ticker_list = sorted(set(_KR_TICKER_PATTERN.findall(clean_text)))
        if kr_ticker_list:
            analysis_dict["related_kr_tickers"] = kr_ticker_list[:5]

        if category == "OVERSEAS_STOCK":
            symbol = _find_first_overseas_symbol(clean_text)
            if symbol:
                chain_result = _call_value_chain_helper(symbol, clean_text)
                # AI 매핑 결과를 본문 직접 추출분과 병합(중복 제거).
                merged_list = list(analysis_dict["related_kr_tickers"])
                for t in chain_result.get("related_kr_tickers", []):
                    if t not in merged_list:
                        merged_list.append(t)
                analysis_dict["related_kr_tickers"] = merged_list[:5]
                analysis_dict["value_chain_type"] = chain_result.get("value_chain_type")

        if category == "OVERSEAS_MARKET":
            analysis_dict["transmission_path"] = _call_transmission_path_helper(clean_text)
    except Exception as exc:
        print(f"Log: [TelegramPipeline] analysis 합성 캡슐화: {exc}")

    return analysis_dict


def _call_value_chain_helper(symbol, clean_text):
    """ai_logic.analyze_value_chain 호출 래퍼 (지연 import + 안전 폴백).

    관심사 분리 R3 예외: 정규화 보조용 stateless 헬퍼만 호출한다.
    """
    try:
        from src.strategy import ai_logic
        return ai_logic.analyze_value_chain(symbol, clean_text) or {}
    except Exception as exc:
        print(f"Log: [TelegramPipeline] value_chain 헬퍼 캡슐화: {exc}")
        return {}


def _call_transmission_path_helper(clean_text):
    """ai_logic.extract_transmission_path 호출 래퍼 (지연 import + 안전 폴백)."""
    try:
        from src.strategy import ai_logic
        return ai_logic.extract_transmission_path(clean_text) or ""
    except Exception as exc:
        print(f"Log: [TelegramPipeline] transmission_path 헬퍼 캡슐화: {exc}")
        return ""


def _load_default_channel_id_list():
    """운영 설정(TG_CHANNEL_ID_LIST)에서 기본 채널 목록을 로드."""
    raw = os.getenv("TG_CHANNEL_ID_LIST", "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _last_id_map_path():
    return os.path.join(project_root(), LAST_ID_MAP_FILENAME)


def _load_last_id_map():
    """채널별 last_message_id 영속화 맵을 로드."""
    data = read_local_json(_last_id_map_path(), default={})
    return data if isinstance(data, dict) else {}


def _save_last_id_map(last_id_map):
    """채널별 last_message_id 영속화 맵을 저장."""
    if not isinstance(last_id_map, dict):
        return
    write_local_json(_last_id_map_path(), last_id_map)


def _update_last_id_map(last_id_map, message_list):
    """정규화에 성공한 메시지 중 가장 큰 message_id 로 채널별 키를 갱신한다.

    Args:
        last_id_map: 이전 last_id_map (dict).
        message_list: 정규화에 성공한 telegram_message_dict 리스트.

    Returns:
        dict: 갱신된 last_id_map (원본 dict 는 변경하지 않는다).
    """
    updated_map = dict(last_id_map or {})
    for msg_dict in message_list or []:
        channel_id = msg_dict.get("source_channel")
        message_id = msg_dict.get("message_id")
        if channel_id is None or message_id is None:
            continue
        prev_id = int(updated_map.get(channel_id, 0) or 0)
        if int(message_id) > prev_id:
            updated_map[channel_id] = int(message_id)
    return updated_map
