# -*- coding: utf-8 -*-
"""Telegram Ingestion Pipeline (스켈레톤).

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

본 파일은 스켈레톤이다. 실제 파싱/키워드 추출 로직은 추후 PR 로 채워넣는다.
"""

from __future__ import annotations

from src.core import telegram_client

MAX_TEXT_LENGTH = 1000


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


def normalize_message(raw_dict):
    """단일 raw 메시지를 telegram_message_dict 로 변환(스켈레톤).

    Args:
        raw_dict: telegram_client.fetch_new_messages 가 반환한 단일 원본 dict.

    Returns:
        dict | None: 정규화 결과(telegram_message_dict). 정규화 불가 시 None.
            반환 키: source_channel, message_id, posted_at, text, keyword_list.
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

        return {
            "source_channel": str(channel_id),
            "message_id": int(message_id),
            "posted_at": posted_at,
            "text": clean_text,
            "keyword_list": keyword_list,
        }
    except Exception as exc:
        print(f"Log: [TelegramPipeline] normalize_message 캡슐화: {exc}")
        return None


def _extract_keyword_list(clean_text):
    """텍스트에서 보조 키워드를 추출(스켈레톤).

    실제 키워드 추출 규칙(섹터/종목명/이슈 태그 등)은 후속 PR 에서 정의한다.
    현재는 빈 리스트를 반환하여 정규화 파이프라인 형태만 유지한다.
    """
    _ = clean_text
    return []


def _load_default_channel_id_list():
    """운영 설정에서 기본 채널 목록을 로드(스켈레톤).

    구체적인 환경 변수 이름·경로는 운영 매뉴얼에서 관리한다(아키텍처 문서에는
    운영 정책만 명시). 현재 스켈레톤에서는 빈 리스트만 반환한다.
    """
    return []


def _load_last_id_map():
    """채널별 last_message_id 영속화 맵을 로드(스켈레톤).

    저장 경로/포맷은 운영 매뉴얼에서 관리한다. 본 스켈레톤은 빈 맵만 반환한다.
    """
    return {}


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
