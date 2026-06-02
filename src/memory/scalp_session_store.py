# -*- coding: utf-8 -*-
"""단타 세션 영속화 (scalp_session.json).

상세: Doc/features/scalp_logic/02_scalp_logic_api_spec.md §5
"""
from __future__ import annotations

from src.storage import state_store

SESSION_SCHEMA_VERSION = 1

_PERSIST_KEYS = (
    "amount",
    "is_pending_custom",
    "set_via",
    "set_at",
    "lifecycle",
    "is_user_running",
    "backtest_passed",
    "last_backtest",
    "started_at",
    "stopped_at",
    "position",
    "budget_requested_at",
    "hts_condition_name",
)


def _export_session_dict(source_dict):
    payload = {"schema_version": SESSION_SCHEMA_VERSION}
    for key in _PERSIST_KEYS:
        if key in source_dict:
            payload[key] = source_dict.get(key)
    return payload


def load_scalp_session():
    """단타 세션 페이로드 로드 (없으면 None)."""
    return state_store.get_scalp_session()


def save_scalp_session(session_dict):
    """단타 세션 페이로드 저장."""
    if not isinstance(session_dict, dict):
        return False
    state_store.save_scalp_session(session_dict)
    return True


def persist_scalp_session_from_module():
    """slack_interface._scalp_session_dict -> 파일."""
    from src.utils import slack_interface as si

    payload = _export_session_dict(si._scalp_session_dict)
    return save_scalp_session(payload)


def restore_scalp_session_to_module():
    """파일 -> slack_interface._scalp_session_dict (키 merge)."""
    from src.utils import slack_interface as si

    stored = load_scalp_session()
    if not isinstance(stored, dict):
        return {"restored": False, "reason": "empty"}
    for key in _PERSIST_KEYS:
        if key in stored:
            si._scalp_session_dict[key] = stored.get(key)
    return {"restored": True, "lifecycle": si.get_scalp_lifecycle()}


def reconcile_scalp_position_with_portfolio():
    """세션 position 없고 paper_portfolio SCALP 보유 시 최소 position 복구."""
    from src.utils import slack_interface as si

    if si.has_scalp_position():
        return {"reconciled": False, "reason": "session_has_position"}

    portfolio = state_store.get_portfolio()
    scalp_entry = None
    for ticker, info in portfolio.items():
        if not isinstance(info, dict):
            continue
        if info.get("mode_type") != "SCALP":
            continue
        qty = int(info.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        scalp_entry = (ticker, info)
        break

    if not scalp_entry:
        return {"reconciled": False, "reason": "no_portfolio_scalp"}

    ticker, info = scalp_entry
    avg_price = float(info.get("avg_price", 0) or 0)
    high = float(info.get("high_water_mark", avg_price) or avg_price)
    qty = int(info.get("quantity", 0) or 0)
    si.set_scalp_position({
        "ticker": ticker,
        "name": info.get("name", ticker),
        "qty": qty,
        "remaining_qty": qty,
        "avg_price": avg_price,
        "highest_price": high,
        "half_sold": False,
        "shape_vector": [],
    })
    if si.is_scalp_user_running():
        si.set_scalp_lifecycle(si.SCALP_LIFECYCLE_RISK)
    persist_scalp_session_from_module()
    return {"reconciled": True, "ticker": ticker, "qty": qty}


def bootstrap_scalp_session():
    """기동 시 load + portfolio reconcile + persist."""
    result = restore_scalp_session_to_module()
    recon = reconcile_scalp_position_with_portfolio()
    persist_scalp_session_from_module()
    return {"restore": result, "reconcile": recon}
