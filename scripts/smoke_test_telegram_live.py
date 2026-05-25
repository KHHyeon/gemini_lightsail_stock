#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram Pipeline 실전 Smoke Test.

실제 운영 채널 1개에서 메시지 1건을 수집하고 telegram_message_dict 스키마를 검증한다.
Mocking 없음 - .env 에 TG_* 설정 및 Telethon 세션 파일이 필요하다.

실행 (프로젝트 루트):
    python scripts/smoke_test_telegram_live.py

선택 환경 변수:
    TG_SMOKE_CHANNEL_ID - 테스트 대상 채널 1개 (미설정 시 TG_CHANNEL_ID_LIST 첫 항목)
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv()

REQUIRED_MSG_KEY_SET = {
    "source_channel",
    "message_id",
    "posted_at",
    "text",
    "keyword_list",
}


def _resolve_smoke_channel_id():
    explicit = os.getenv("TG_SMOKE_CHANNEL_ID", "").strip()
    if explicit:
        return explicit
    raw_list = os.getenv("TG_CHANNEL_ID_LIST", "").strip()
    if not raw_list:
        return ""
    parts = [p.strip() for p in raw_list.split(",") if p.strip()]
    return parts[0] if parts else ""


def _print_header(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    from src.core import telegram_client
    from src.pipeline import telegram_pipeline as tp

    _print_header("Telegram Pipeline 실전 Smoke Test")

    if not telegram_client.is_configured():
        print("[FAIL] Telethon 설정 누락 (TG_API_ID, TG_API_HASH, TG_SESSION_NAME)")
        print("       .env 및 세션 파일을 확인하세요.")
        sys.exit(1)

    channel_id = _resolve_smoke_channel_id()
    if not channel_id:
        print("[FAIL] 테스트 채널 미설정 (TG_SMOKE_CHANNEL_ID 또는 TG_CHANNEL_ID_LIST)")
        sys.exit(1)

    print(f"[INFO] 대상 채널: {channel_id}")
    print("[INFO] 최근 메시지 1건 수집 중...")

    raw_list = telegram_client.fetch_new_messages(
        [channel_id],
        {channel_id: 0},
        limit_per_channel=1,
    )

    if not raw_list:
        print("[FAIL] 수집 결과 없음 (채널 접근 권한, 세션 인증, FloodWait 등 확인)")
        sys.exit(1)

    raw_dict = raw_list[0]
    print(f"[INFO] raw 수집 성공: message_id={raw_dict.get('message_id')}")

    normalized = tp.normalize_message(raw_dict)
    if normalized is None:
        print("[FAIL] normalize_message 반환 None (미디어 전용 또는 본문 없음)")
        sys.exit(1)

    missing_key_set = REQUIRED_MSG_KEY_SET - set(normalized.keys())
    if missing_key_set:
        print(f"[FAIL] telegram_message_dict 누락 키: {sorted(missing_key_set)}")
        sys.exit(1)

    if not isinstance(normalized["keyword_list"], list):
        print("[FAIL] keyword_list 가 list 타입이 아님")
        sys.exit(1)

    print("[PASS] telegram_message_dict 스키마 검증 완료")
    print(f"  - source_channel : {normalized['source_channel']}")
    print(f"  - message_id     : {normalized['message_id']}")
    print(f"  - posted_at      : {normalized['posted_at']}")
    print(f"  - text (앞 120자): {normalized['text'][:120]}")
    print(f"  - keyword_list   : {normalized['keyword_list']}")
    print("\n[OK] 실전 Smoke Test 통과")
    sys.exit(0)


if __name__ == "__main__":
    main()
