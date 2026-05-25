# Scalp Logic State & Logic

1. 상태 모델 (State Model)
- STOPPED: 사용자 `!단타멈춤` 또는 초기 상태. 스케줄 job 은 등록되나 내부 가드로 SKIP.
- S_PRE. Budget Allocation: **주간 첫 거래일** 08:30 KST (`is_first_trading_day_of_week`). `is_scalp_schedule_enabled()` 일 때만 활성.
- S0. Scanning: 주간 예산이 확정(사용자 입력 완료 또는 09:00 KST 타임아웃 폴백 자동 적용)된 후, KIS API를 통해 거래대금 급등 종목 3분봉 폴링 개시.
- S1. Filtered: 3분간 거래대금 5억 돌파 및 20선 눌림목 근접 포착.
- S2. Validating: 30종 프리셋과 상관계수 비교 및 Dynamic Threshold 검사 수행.
- S3. Executed: 조건 부합 시 확정된 예산 100%를 시장가 매수 진입.
- S4. Risk Monitoring: 3중 방어막(칼손절/추적익절/강제청산) 틱 단위 감시.
- S5. Liquidated: 청산 완료 후 승패 라벨링하여 학습 데이터(JSON)에 적재.

2. 슬랙 상호작용 및 폴백 전이 상세 로직
- [08:30 KST 트리거]: `scalp_pre_routine()` -> HTS 조건식 확인 -> `request_weekly_budget_via_slack(reset_budget=True)` 송신, S_PRE 진입.
- [경로 A - 기본 선택]: 사용자가 '기본 5만원' 버튼 클릭 -> `set_weekly_budget(50000, via="default")` 적재 후 S0 전이.
- [경로 B - 직접 입력]: 모달/채팅 숫자 -> `set_weekly_budget(parsed, via="custom")` 후 S0 전이.
- [경로 C - 09:00 폴백]: 월 09:00 `scalp_force_default_at_open()` -> `force_default_budget_if_idle(mode="open_0900")`.
- [경로 D - 타임아웃 폴백]: 장중 `_scalp_intraday_job` -> S_PRE + 무응답 시 `try_budget_fallback_during_intraday()` (기본 30분).
- [진행 제어]: `scalp_start`/`!단타시작` -> `start_scalp_trading(kis_client, app, channel_id)` (백테스트 PASS + HTS 등록 필수). 성공 시 **항상** 예산 초기화 + S_PRE + Block Kit 재발송. `scalp_stop`/`!단타멈춤` -> STOPPED.
- [백테스트 게이트]: 기동 시 및 `!단타백테스트` 로 `run_and_persist()` 실행 -> `set_backtest_gate_result()`. PASS 전 `!단타시작` 거부.

3. 백테스트 결과 구조 (scalp_backtest_result.json)
- passes_gate, win_rate, avg_return, total_return, total_trades, gate_reason, run_at, mode("shape_ratio_only")

4. 패턴 학습 데이터 구조 (scalp_training_data.json)
- root
  - metadata: {"total_trades": int, "win_rate": float, "last_updated": str}
  - trades: list[trade_dict]
    - trade_dict: {"id": uuid, "ticker": str, "timestamp": ISO8601, "result_label": "WIN"|"LOSS", "shape_vector": list[float]}

4. 리스크 관리 상세 로직 (S4)
- 현재가 <= 평균단가 * 0.985: 즉각 전량 매도 (`monitor_scalp_risk` -> "STOP_LOSS_1_5")
- 현재가 >= 평균단가 * 1.03: 보유 수량의 50% 매도 플래그 활성화 ("TAKE_PROFIT_HALF"). 이후 최고가 갱신 추적.
- (50% 매도 이후 `half_sold=True`) 현재가 <= 최고가 * 0.99: 잔여 50% 전량 매도 ("TRAILING_STOP")
- 시각 >= "15:10:00" KST (`is_force_liquidation_time`): `MarketOrchestrator.scalp_force_liquidation()` 가 SCALP 포지션 전량 시장가 매도. 매도 실패 시 즉시 B-Type 알림 발행(`HALT_B_TYPE`).

5. 단타 세션 영속화 (scalp_session.json)
- schema_version: 1
- 필드: is_user_running, lifecycle, amount, set_via, set_at, is_pending_custom, backtest_passed, last_backtest, started_at, stopped_at, budget_requested_at, hts_condition_name, position|null
- 기동: load -> `_scalp_session_dict` merge -> portfolio SCALP 와 position reconcile
- position 세션 없고 portfolio SCALP qty>0 이면 S4 복구용 최소 position 생성 (half_sold=False, highest=avg)

6. 파일 매핑 (구현 동기화)
- 슬랙/세션: `src/utils/slack_interface.py` (예산+진행+position, start/stop/status)
- **세션 영속화**: `src/memory/scalp_session_store.py`, `scalp_session.json`
- KIS 3분봉: `src/data/chart.py` (분봉/3분봉/MA20)
- 백테스트: `src/strategy/scalp_backtest.py`, CLI `scripts/run_scalp_backtest.py`
- 형태/리스크/진입평가: `src/strategy/scalp_logic.py`
- 오케스트레이션: `src/execution/orchestrator.py` (scan_cycle, risk_monitor_cycle), 스케줄 `main.py`
- 주문: `src/execution/order.py` (`TRADING_MODE_SCALP`)
- 학습 데이터: `src/memory/scalp_trainer.py`
- 테스트: `tests/temp_test_scalp_logic.py` (31), `tests/temp_test_market_calendar_and_token.py` (11)