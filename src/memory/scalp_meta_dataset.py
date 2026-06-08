# -*- coding: utf-8 -*-
"""단타 메타라벨링 학습 데이터 저장소 (Phase 3 준비).

목적:
    - 진입 시점의 신호 특징(feature)을 누적 저장한다.
    - 청산 시점에 승패 라벨을 확정하여 supervised 학습 데이터로 전환한다.

주의:
    - 본 모듈은 "데이터 수집"만 담당한다.
    - 실제 메타모델 학습/추론 로직은 후속 단계에서 구현한다.
"""

from __future__ import annotations

import os
import uuid

from src.utils.jsonio import read_local_json, write_local_json
from src.utils.paths import project_root
from src.utils.timekit import kst_iso_now

META_DATASET_FILENAME = "scalp_meta_signals.json"


def _dataset_path():
    return os.path.join(project_root(), META_DATASET_FILENAME)


def _empty_root():
    return {
        "metadata": {
            "total_signals": 0,
            "pending_signals": 0,
            "labeled_signals": 0,
            "win_rate": 0.0,
            "last_updated": "",
        },
        "signals": [],
    }


def _load_root():
    data = read_local_json(_dataset_path(), default=None)
    if not isinstance(data, dict) or "signals" not in data:
        return _empty_root()
    return data


def _update_metadata(root):
    signal_list = root.get("signals") or []
    total = len(signal_list)
    pending = sum(1 for s in signal_list if s.get("label") == "PENDING")
    labeled = total - pending
    win_count = sum(1 for s in signal_list if s.get("label") == "WIN")
    root["metadata"] = {
        "total_signals": total,
        "pending_signals": pending,
        "labeled_signals": labeled,
        "win_rate": round(win_count / labeled, 4) if labeled else 0.0,
        "last_updated": kst_iso_now(),
    }


def record_entry_signal(ticker, feature_dict):
    """진입 직전 메타 신호를 기록하고 signal_id를 반환한다."""
    if not ticker or not isinstance(feature_dict, dict):
        return None
    signal_id = str(uuid.uuid4())
    row = {
        "signal_id": signal_id,
        "ticker": str(ticker),
        "created_at": kst_iso_now(),
        "label": "PENDING",
        "features": dict(feature_dict),
        "outcome": {},
    }
    root = _load_root()
    root.setdefault("signals", []).append(row)
    _update_metadata(root)
    write_local_json(_dataset_path(), root)
    return signal_id


def finalize_signal_label(signal_id, *, is_win, pnl_ratio, exit_reason):
    """청산 시점 라벨 확정 (PENDING -> WIN/LOSS)."""
    if not signal_id:
        return False
    root = _load_root()
    signal_list = root.get("signals") or []
    updated = False
    for row in reversed(signal_list):
        if row.get("signal_id") != signal_id:
            continue
        if row.get("label") != "PENDING":
            return True
        row["label"] = "WIN" if bool(is_win) else "LOSS"
        row["outcome"] = {
            "finalized_at": kst_iso_now(),
            "pnl_ratio": float(pnl_ratio or 0.0),
            "exit_reason": str(exit_reason or ""),
        }
        updated = True
        break
    if not updated:
        return False
    _update_metadata(root)
    write_local_json(_dataset_path(), root)
    return True


def get_meta_dataset_metadata():
    root = _load_root()
    return dict(root.get("metadata") or {})
