# -*- coding: utf-8 -*-
"""텔레그램 API 캡슐화 레이어 (Telethon).

본 모듈의 단일 책임은 텔레그램 외부 API 호출과 그에 수반되는 인증/Rate Limit/예외
처리를 본 모듈 내부로 완전히 격리하는 것이다. 메시지 정제·정규화·후속 라우팅은
src/pipeline/telegram_pipeline.py 가 담당하며, 본 모듈은 market_chronicles 등
후속 도메인 모듈을 import 하지 않는다.

의존성 방향성 (역방향 import 금지):
    telegram_client -> (호출됨) telegram_pipeline -> (호출됨) orchestrator

에러 정책 (A-Type 캡슐화):
    - FloodWaitError / 인증 오류 / 네트워크 장애는 본 모듈에서 흡수하고
      호출자에게는 빈 리스트(_list)만 반환한다(C-Type 중단 금지).
    - 단일 메시지 파싱 실패는 해당 항목만 스킵한다.
    - is_configured() 로 설정 상태만 보고한다.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from src.utils.paths import project_root

load_dotenv()

_DEFAULT_FETCH_LIMIT = 50


def is_configured() -> bool:
    """텔레그램 Telethon 인증 설정의 최소 구성 여부를 반환한다.

    환경 변수: TG_API_ID, TG_API_HASH, TG_SESSION_NAME (.env 주입).

    Returns:
        bool: 세 항목이 모두 유효할 때 True. 누락/오구성 시 False(예외 미발생).
    """
    cfg = _load_env_config()
    return bool(cfg.get("api_id")) and bool(cfg.get("api_hash")) and bool(cfg.get("session_name"))


def fetch_new_messages(channel_id_list, last_id_map, *, limit_per_channel=None):
    """채널별 신규 메시지를 조회하여 raw 메시지 리스트를 반환한다.

    last_id_map 의 각 채널 last_id 를 min_id 로 사용하여 그 이후 메시지만 수집한다.

    Args:
        channel_id_list: 수집 대상 채널 식별자 리스트(@username, -100... id 등).
        last_id_map: {channel_id: last_message_id} 영속화 맵.
        limit_per_channel: 채널당 최대 수집 건수. None 이면 기본값(50).

    Returns:
        list[dict]: 단일 dict 키 (channel_id, message_id, posted_at, raw_text).
            외부 장애 시 빈 리스트 반환(A-Type 격리).
    """
    if not is_configured():
        return []
    if not channel_id_list:
        return []

    limit = int(limit_per_channel or _DEFAULT_FETCH_LIMIT)
    try:
        return asyncio.run(
            _fetch_new_messages_async(channel_id_list, last_id_map or {}, limit)
        )
    except Exception as exc:
        print(f"Log: [TelegramClient] fetch_new_messages 캡슐화: {exc}")
        return []


def _load_env_config():
    """환경 변수에서 Telethon 설정을 로드한다."""
    api_id_raw = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    session_name = os.getenv("TG_SESSION_NAME", "").strip()
    api_id = None
    if api_id_raw.isdigit():
        api_id = int(api_id_raw)
    return {
        "api_id": api_id,
        "api_hash": api_hash,
        "session_name": session_name,
    }


def _session_file_path(session_name):
    """Telethon 세션 파일 절대 경로."""
    base = session_name
    if base.endswith(".session"):
        base = base[: -len(".session")]
    return os.path.join(project_root(), base)


async def _fetch_new_messages_async(channel_id_list, last_id_map, limit_per_channel):
    """비동기 수집 본체."""
    cfg = _load_env_config()
    session_path = _session_file_path(cfg["session_name"])

    try:
        from telethon import TelegramClient
        from telethon.errors import (
            ApiIdInvalidError,
            AuthKeyError,
            AuthKeyUnregisteredError,
            ChannelInvalidError,
            ChannelPrivateError,
            FloodWaitError,
            RPCError,
            SessionPasswordNeededError,
            UserDeactivatedError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
        )
    except ImportError:
        print("Log: [TelegramClient] telethon 미설치 - pip install telethon 필요")
        return []

    raw_message_list = []
    client = TelegramClient(session_path, cfg["api_id"], cfg["api_hash"])

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Log: [TelegramClient] 세션 미인증 - Telethon 로그인 필요")
            return []

        for channel_id in channel_id_list:
            last_id = int(last_id_map.get(channel_id, 0) or 0)
            channel_raw_list = await _fetch_single_channel_async(
                client,
                channel_id,
                last_id,
                limit_per_channel,
                error_cls_map={
                    "FloodWaitError": FloodWaitError,
                    "ChannelPrivateError": ChannelPrivateError,
                    "ChannelInvalidError": ChannelInvalidError,
                    "UsernameInvalidError": UsernameInvalidError,
                    "UsernameNotOccupiedError": UsernameNotOccupiedError,
                    "AuthKeyError": AuthKeyError,
                    "AuthKeyUnregisteredError": AuthKeyUnregisteredError,
                    "ApiIdInvalidError": ApiIdInvalidError,
                    "SessionPasswordNeededError": SessionPasswordNeededError,
                    "UserDeactivatedError": UserDeactivatedError,
                    "RPCError": RPCError,
                },
            )
            raw_message_list.extend(channel_raw_list)
    except FloodWaitError as exc:
        print(f"Log: [TelegramClient] FloodWaitError {exc.seconds}초 - A-Type 격리")
    except (
        AuthKeyError,
        AuthKeyUnregisteredError,
        ApiIdInvalidError,
        SessionPasswordNeededError,
        UserDeactivatedError,
    ) as exc:
        print(f"Log: [TelegramClient] 인증 오류 A-Type 격리: {type(exc).__name__}")
    except Exception as exc:
        print(f"Log: [TelegramClient] 클라이언트 연결 캡슐화: {exc}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    return raw_message_list


async def _fetch_single_channel_async(
    client,
    channel_id,
    last_id,
    limit_per_channel,
    error_cls_map,
):
    """단일 채널 신규 메시지 조회 (min_id=last_id)."""
    FloodWaitError = error_cls_map["FloodWaitError"]
    ChannelPrivateError = error_cls_map["ChannelPrivateError"]
    ChannelInvalidError = error_cls_map["ChannelInvalidError"]
    UsernameInvalidError = error_cls_map["UsernameInvalidError"]
    UsernameNotOccupiedError = error_cls_map["UsernameNotOccupiedError"]
    RPCError = error_cls_map["RPCError"]

    raw_list = []
    try:
        entity = await client.get_entity(channel_id)
        async for msg in client.iter_messages(
            entity,
            min_id=last_id,
            limit=limit_per_channel,
        ):
            text = _extract_message_text(msg)
            if not text:
                continue
            posted_at = msg.date.isoformat() if getattr(msg, "date", None) else ""
            raw_list.append({
                "channel_id": str(channel_id),
                "message_id": int(msg.id),
                "posted_at": posted_at,
                "raw_text": text,
            })
    except FloodWaitError as exc:
        print(
            f"Log: [TelegramClient] {channel_id} FloodWaitError "
            f"{exc.seconds}초 - A-Type 격리"
        )
    except ChannelPrivateError:
        print(f"Log: [TelegramClient] {channel_id} 비공개/접근 불가 - A-Type 격리")
    except (ChannelInvalidError, UsernameInvalidError, UsernameNotOccupiedError) as exc:
        print(f"Log: [TelegramClient] {channel_id} 채널 식별 오류 - A-Type 격리: {exc}")
    except RPCError as exc:
        print(f"Log: [TelegramClient] {channel_id} RPC 오류 - A-Type 격리: {exc}")
    except Exception as exc:
        print(f"Log: [TelegramClient] {channel_id} 채널 조회 캡슐화: {exc}")

    return raw_list


def _extract_message_text(msg):
    """메시지에서 텍스트 본문을 추출. 미디어 전용(본문 없음)은 None."""
    text = getattr(msg, "message", None) or getattr(msg, "text", None)
    if text is None:
        return None
    text = str(text).strip()
    return text if text else None
