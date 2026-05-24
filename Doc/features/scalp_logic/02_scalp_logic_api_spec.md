# Scalp Logic API Spec

1. 슬랙 인터랙티브 및 예산 관리 API (src/utils/slack_interface.py)

request_weekly_budget_via_slack(app=None, channel_id=None, *, reset_budget=True) -> dict
- 목적: 단타 예산 결정 Block Kit 메시지 발송. `reset_budget=False` 는 `start_scalp_trading` 직후 재요청용.
- 슬랙 페이로드 구조: '기본 5만원(action_id: budget_default)' / '직접 입력(action_id: budget_custom)' 버튼.
- 반환: `{"sent": bool, "blocks": list, "channel": str|None, "reason": str}` (단위 테스트 검증용으로 blocks 항상 반환).

handle_budget_slack_interaction(payload_dict) -> dict
- 목적: 슬랙 버튼/모달/메시지 페이로드를 단일 진입점에서 파싱하여 예산 세션 갱신.
- 처리 대상:
  - actions[0].action_id == "budget_default" -> 기본 50,000 KRW 적재.
  - actions[0].action_id == "budget_custom" -> `is_pending_custom=True` 플래그만 켜고 모달/텍스트 대기.
  - view.callback_id == "budget_custom_modal_submit" -> 모달 제출 금액 적재.
  - event.text 숫자(pending 상태) -> 채팅 후속 금액 적재.
- 반환: `{"status": "ok"|"pending"|"ignored"|"error", "amount": int|None, "via": str}`.

set_weekly_budget(amount_int, *, via="default") -> int|None
- 목적: 확정 예산을 모듈 전역 세션에 적재. via 라벨: "default" | "custom" | "fallback_timeout".

get_weekly_budget() -> int|None
- 목적: 적재된 주간 단타 예산 조회. 매수 수량 산정 인자로 활용.

reset_weekly_budget_session() -> None
- 목적: 매주 첫 거래일 진입 시 세션 초기화.

force_default_budget_if_idle(*, mode="timeout"|"open_0900") -> dict
- 목적: S_PRE 무응답 폴백. `open_0900`=월 09:00 스케줄, `timeout`=요청 후 N분(기본 30).
- 반환: `{"applied": bool, "amount": int|None, "via": str}`.

try_budget_fallback_during_intraday() -> dict
- 목적: 장중 3분 job에서 `mode="timeout"` 폴백 위임.

get_scalp_condition_name() -> str
check_hts_condition_registered(kis_client) -> dict
- 목적: HTS 조건식 등록 여부 사전 검증.

start_scalp_trading(*, via="slack", kis_client=None, app=None, channel_id=None) -> dict
- 목적: 단타 진행 ON. 백테스트 미통과 또는 HTS 미등록 시 `{"ok": False, "reason": ...}`.
- 성공 시 항상 lifecycle S_PRE + 예산 Block Kit 발송(재시작 포함).

stop_scalp_trading(*, via="slack") -> dict
- 목적: 단타 진행 OFF. lifecycle STOPPED.

handle_scalp_control_interaction(payload_dict, *, kis_client=None, app=None, channel_id=None) -> dict
- 처리 action_id: `scalp_start` | `scalp_stop` | `scalp_status`.

format_scalp_status_text() -> str
- 목적: 진행 ON/OFF, lifecycle, 예산, 백테스트, 스케줄 활성 여부 요약.

is_scalp_schedule_enabled() -> bool
- 목적: `backtest_passed AND is_user_running` 스케줄 실행 게이트.

set_backtest_gate_result(result_dict) / is_backtest_passed() -> bool
- 목적: 백테스트 결과 세션 반영 및 조회.

Slack 명령/버튼:
- Block Kit: `budget_default`, `budget_custom`, `scalp_start`, `scalp_stop`, `scalp_status`
- 텍스트: `!단타시작`, `!단타멈춤`, `!단타상태`, `!단타백테스트 [일수]`

2. 형태 백테스트 API (src/strategy/scalp_backtest.py)

run_shape_backtest(*, n_days=60, seed=20260524) -> dict
- 목적: 가격 무관(정규화 형태 + ratio 경로) 백테스트 1회 실행.
- 반환: total_trades, win_rate, avg_return, total_return, passes_gate, gate_reason, trades(샘플).

run_and_persist(*, n_days=60) -> dict
- 목적: 실행 후 `scalp_backtest_result.json` 저장.

load_persisted_result() / is_backtest_gate_passed() -> bool

simulate_trade_pnl_ratio(price_path_list) -> float
- 목적: ratio tick 경로에 3중 방어막 적용 후 손익 ratio 산출.

게이트 기본값: trades>=20, win_rate>=0.52, avg_return>=0.002, total_return>=0.03

3. 패턴 인식 및 유사도 API (src/strategy/scalp_logic.py)

calculate_shape_similarity(realtime_vector_list, preset_matrix) -> float
- 목적: 실시간 1D 형태 벡터와 프리셋 매트릭스 각 행 간의 피어슨 상관계수 최대값 산출.
- 반환: 0.0 ~ 1.0 사이의 float. 입력 부적합/분산 0 시 0.0.

determine_dynamic_threshold(vix_score, has_good_news) -> float
- 목적: 시장/뉴스에 따른 동적 통과 임계치 결정. VIX 과열 > 호재 뉴스 > 기본 우선순위.
- 반환: 0.80(공격) | 0.85(기본) | 0.90(보수).

detect_pullback_signal(ohlcv_3min_list, ma20) -> dict
- 목적: 1차 필터(거래대금 5억 + 20MA 근접 ±1%) 도달 여부.
- 반환: `{"is_signal": bool, "reason": str}`.

monitor_scalp_risk(ticker, current_price, avg_buy_price, highest_price, *, half_sold=False) -> str
- 목적: 3중 방어막 틱 단위 판정.
- 반환: "HOLD" | "STOP_LOSS_1_5" | "TAKE_PROFIT_HALF" | "TRAILING_STOP".

is_force_liquidation_time(now=None) -> bool
- 목적: 15:10 KST 강제 청산 시각 도달 여부.

build_default_preset_matrix(seed, count=30, length=20) -> np.ndarray
- 목적: 결정론적 '20선 눌림목 프리셋' 매트릭스 생성(테스트 재현성 보장).

extract_shape_vector_from_ohlcv(ohlcv_list, length=20) -> list[float]
- 목적: OHLCV 리스트에서 [0, 1] 정규화 형태 벡터 추출(학습 데이터/실시간 비교 공용 포맷).

evaluate_entry_candidate(ohlcv_3min_list, ma20, *, preset_matrix, vix_score, has_good_news) -> dict
- 목적: S0->S3 단일 종목 진입 평가 (pullback + similarity + threshold).
- 반환: `{"state": "S0|S1|S2|S3", "enter": bool, "reason", "similarity", "threshold", "shape_vector"}`.

calc_market_buy_qty(budget_int, market_price) -> int
- 목적: 예산 100% 시장가 매수 수량(floor).

3-b. KIS 3분봉 데이터 API (src/data/chart.py)

get_intraday_minute_ohlcv(...) -> list[dict]|None
- TR: FHKST03010200 당일 1분봉.

resample_minute_to_3min(minute_ohlcv_list) -> list[dict]
- 1분봉 -> 3분봉 집계.

get_3min_ohlcv_for_ticker(...) -> list[dict]|None
- 분봉 조회 + 3분봉 변환 편의 함수.

compute_daily_ma20(daily_ohlcv_list) -> float|None
- 일봉 20MA (20선 눌림목 기준선).

3. 실행 및 리스크 관리 API (src/execution/orchestrator.py)

MarketOrchestrator.scalp_pre_routine() -> dict
- 목적: 월요일 08:30 KST. `is_scalp_schedule_enabled()` False 시 SKIP.
- 반환: `{"state": "S_PRE"|"SKIP", ...}`.

MarketOrchestrator.scalp_force_default_at_open() -> dict
- 목적: 월요일 09:00 KST 폴백. `is_scalp_user_running()` False 시 SKIP.

MarketOrchestrator.scalp_force_liquidation(sell_fn=None) -> dict
- 목적: 매일 15:10 KST. 진행 OFF 시 SKIP. 청산 후 scalp_trainer 적재 + S5.

MarketOrchestrator.scalp_scan_cycle(*, candidate_provider=None, chart_provider=None) -> dict
- 목적: S0->S3 장중 스캔. HTS 조건식(`SCALP_CONDITION_NAME`, 기본 `당일_주도주_발굴`) 후보 -> 3분봉 -> 진입 -> 예산 100% 매수.

MarketOrchestrator.scalp_risk_monitor_cycle(*, price_provider=None, sell_fn=None) -> dict
- 목적: S4 3중 방어막 틱 감시. STOP_LOSS/TAKE_PROFIT_HALF/TRAILING_STOP 시 매도 + S5 학습 적재.

main.py 스케줄 (항상 job 등록, 실행은 내부 가드):
- 월 08:30 `_scalp_pre_job`, 월 09:00 `_scalp_open_fallback_job`, 매일 15:10 `scalp_force_liquidation`
- **매 3분** `_scalp_intraday_job` (포지션 없음: scan / 있음: risk monitor)
- 기동 시 `_bootstrap_scalp_backtest()` 1회 실행

환경 변수:
- `SCALP_CONDITION_NAME`: HTS 조건식 이름 (기본 `당일_주도주_발굴`)
- `HTS_ID`: KIS HTS ID (조건식 조회 필수)
- `SCALP_BUDGET_TIMEOUT_MIN`: 예산 무응답 폴백 분 (기본 30)
- `TRADING_MODE_SCALP`: `PAPER`|`LIVE` (기본 PAPER)

4. 학습 데이터 적재 API (src/memory/scalp_trainer.py)

record_trade_result(ticker, is_win, ohlcv_vector, *, extra=None) -> dict
- 목적: 청산 직후 결과를 scalp_training_data.json 에 누적. metadata(total_trades/win_rate/last_updated) 자동 재계산.
- 반환: 적재된 trade_dict.

get_training_metadata() -> dict
- 목적: 누적 메타데이터 조회.

get_recent_trade_list(limit=20) -> list[dict]
- 목적: 최근 trade 리스트 역순 조회.
