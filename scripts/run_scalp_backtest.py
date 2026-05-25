#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""형태 기반 단타 백테스트 CLI (가격 무관).

실행:
    venv/bin/python3 scripts/run_scalp_backtest.py
    venv/bin/python3 scripts/run_scalp_backtest.py --days 90
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.strategy import scalp_backtest


def main():
    parser = argparse.ArgumentParser(description="Scalp shape backtest (price-agnostic)")
    parser.add_argument("--days", type=int, default=60, help="simulated trading days")
    parser.add_argument("--seed", type=int, default=20260524, help="random seed")
    args = parser.parse_args()

    result = scalp_backtest.run_and_persist(n_days=args.days, seed=args.seed)
    status = "PASS" if result.get("passes_gate") else "FAIL"
    print("=" * 60)
    print("Scalp Shape Backtest (price-agnostic)")
    print("=" * 60)
    print(f"Status       : {status}")
    print(f"Gate reason  : {result.get('gate_reason')}")
    print(f"Total trades : {result.get('total_trades')}")
    print(f"Skipped      : {result.get('skipped')}")
    print(f"Win rate     : {result.get('win_rate', 0):.2%}")
    print(f"Avg return   : {float(result.get('avg_return') or 0):.4f} (ratio/trade)")
    print(f"Total return : {float(result.get('total_return') or 0):.4f} (ratio sum)")
    print(f"Saved to     : scalp_backtest_result.json")
    print("=" * 60)
    if result.get("passes_gate"):
        print("Next: Slack에서 !단타시작 으로 진행 ON -> 스케줄 활성화")
    else:
        print("Gate FAIL: 스케줄 미등록. 파라미터/프리셋 조정 후 재실행")
    return 0 if result.get("passes_gate") else 1


if __name__ == "__main__":
    raise SystemExit(main())
