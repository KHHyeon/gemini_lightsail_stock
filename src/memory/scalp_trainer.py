# -*- coding: utf-8 -*-
"""단타 패턴 학습 데이터 적재기.

매매 청산 직후 호출되어 ``scalp_training_data.json`` 에 trade 결과를 누적한다.
누적 데이터는 추후 PR 에서 프리셋 매트릭스 자동 갱신/Fine-tuning 의 입력으로
사용된다. 본 모듈은 데이터 적재 인터페이스만 제공하며, 학습/모델 갱신 로직은
포함하지 않는다(관심사 분리).

스키마: Doc/features/scalp_logic/03_scalp_logic_api_state_logic.md §3 참조.
"""

from __future__ import annotations

import os
import uuid

from src.utils.jsonio import read_local_json, write_local_json
from src.utils.paths import project_root
from src.utils.timekit import kst_iso_now

TRAINING_DATA_FILENAME = "scalp_training_data.json"
RESULT_LABEL_SET = {"WIN", "LOSS"}


def _training_data_path():
    return os.path.join(project_root(), TRAINING_DATA_FILENAME)


def _empty_root():
    return {
        "metadata": {
            "total_trades": 0,
            "win_rate": 0.0,
            "last_updated": "",
        },
        "trades": [],
    }


def _load_root():
    data = read_local_json(_training_data_path(), default=None)
    if not isinstance(data, dict) or "trades" not in data:
        return _empty_root()
    return data


def record_trade_result(ticker, is_win, ohlcv_vector, *, extra=None):
    """청산 직후 단일 trade 결과를 적재한다.

    Args:
        ticker: 종목코드.
        is_win: 승패 (bool).
        ohlcv_vector: 진입 시점의 정규화된 1D 형태 벡터(list[float]).
        extra: 부가 메타(dict|None). 예: {"shape_similarity": 0.86, "threshold": 0.85}

    Returns:
        dict: 적재된 trade_dict.
    """
    if not ticker:
        return {}

    result_label = "WIN" if bool(is_win) else "LOSS"
    if result_label not in RESULT_LABEL_SET:
        return {}

    shape_vector = list(ohlcv_vector) if ohlcv_vector else []
    trade_dict = {
        "id": str(uuid.uuid4()),
        "ticker": str(ticker),
        "timestamp": kst_iso_now(),
        "result_label": result_label,
        "shape_vector": shape_vector,
    }
    if isinstance(extra, dict) and extra:
        trade_dict["extra"] = extra

    root = _load_root()
    trade_list = root.setdefault("trades", [])
    trade_list.append(trade_dict)

    # metadata 재계산
    total = len(trade_list)
    win_count = sum(1 for t in trade_list if t.get("result_label") == "WIN")
    root["metadata"] = {
        "total_trades": total,
        "win_rate": round(win_count / total, 4) if total else 0.0,
        "last_updated": kst_iso_now(),
    }

    write_local_json(_training_data_path(), root)
    return trade_dict


def get_training_metadata():
    """메타데이터(`total_trades`, `win_rate`, `last_updated`) 조회."""
    root = _load_root()
    return dict(root.get("metadata") or {})


def get_recent_trade_list(limit=20):
    """최근 trade 리스트를 limit 건까지 반환(역순)."""
    root = _load_root()
    trade_list = root.get("trades") or []
    if limit <= 0:
        return []
    return list(reversed(trade_list))[:limit]
