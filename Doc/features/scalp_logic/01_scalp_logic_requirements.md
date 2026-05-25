# Scalp Logic Requirements

1. 기능 요구사항 (Functional)
R1. 투자 환경 및 자본 배분 (Budget & Allocation)
- 매주 첫번째 시장이 열리는 날(첫 거래일) 08:30 KST에 슬랙(Slack) 인터랙티브 파이프라인을 통해 사용자에게 이번 주 단타 예산 설정을 요청하는 Block Kit 메시지(버튼: '기본 5만원' / '직접 입력')를 발송한다.
- 09:00 KST까지 사용자가 응답을 하지 않거나 지연될 경우, 시스템의 중단(Blocking)을 막기 위해 A-Type 폴백(Fallback) 정책을 적용하여 자동으로 그 주의 단타 예산을 '기본(5만 원)'으로 강제 설정하고 매매 대기 상태(S0)로 진입한다.
- 장중 수동 시작(`!단타시작`) 후에도 예산 미응답 시 `SCALP_BUDGET_TIMEOUT_MIN`(기본 30분) 경과 후 동일 폴백을 적용한다.
- 확정된 주간 예산은 분할하지 않고, 조건에 부합하는 단 1개의 주도주에 전액(100%) 매수 진입한다.
- 동시 보유 단타 종목 수는 1개로 제한한다.

R2. 핵심 전략 및 수식 필터링 (Phase 1)
- 장 초반(09:00 이후) 3분봉 기준으로 직전 3분간 거래대금 5억 원 이상 폭발을 감지한다.
- 주가가 조정을 받으며 하락하다가 3분봉 기준 20일 이동평균선 부근에서 지지받는 '눌림목' 현상을 1차 조건으로 필터링한다.

R3. 패턴 인식 알고리즘 및 지속 학습 (Phase 2 확장)
- 가격 절대값의 일치가 아닌 캔들의 꼬리, 이평선 기울기, 거래량 감소 추세 등 기하학적 형태(Shape)의 유사도를 산출한다.
- 시스템 내부에 사전 검증된 '성공적인 20선 눌림목 프리셋 30종'을 내장하여, 실시간 종목과 프리셋 간의 상관계수(Correlation)를 계산한다.
- [패턴 학습 지원]: 매매 완료(청산) 후 결과 데이터(승/패 라벨링, 당시 OHLCV 벡터)를 scalp_training_data.json에 적재하여, 추후 프리셋을 자동 갱신하고 가중치를 미세 조정(Fine-tuning)할 수 있는 피드백 루프 구조를 갖춘다.

R4. 가변적 임계치 (Dynamic Threshold)
- 형태 유사도(Similarity) 통과 기본 기준은 85%로 설정한다.
- 실시간 뉴스 분석 결과 호재가 확인되면 80%로 하향(공격적 진입), 시장 공포지수(VIX)가 높을 때는 90%로 상향(보수적 진입) 조정한다.

R5. 3중 방어막 리스크 관리 (Risk Management)
- 칼손절: 매수 직후 주가가 하락하여 매수가 대비 -1.5% 도달 시 즉시 전량 시장가 매도.
- 추적 익절: 목표 수익률 +3% 도달 시 보유 물량의 50%를 시장가 매도하고, 잔여 물량은 최고점 대비 -1% 하락 시 전량 매도.
- 시간 제한 강제 청산: 수익/손실 여부와 무관하게 15:10 도달 시 보유 물량 전량 시장가 매도(오버나이트 리스크 원천 차단).

R6. 형태 기반 백테스트 게이트 (Pre-Schedule Validation)
- 실제 종목 가격·KIS API 없이 정규화 형태 벡터 + ratio 기반 경로로 백테스트를 수행한다(가격 절대값 무관).
- 게이트 통과 기준(기본): trades>=20, win_rate>=52%, avg_return>=0.2%/trade, total_return>=3%(ratio 합).
- 게이트 PASS 전에는 `!단타시작` 및 스케줄 실행(08:30/09:00/15:10)이 내부 가드에 의해 SKIP 된다.
- CLI: `scripts/run_scalp_backtest.py`, Slack: `!단타백테스트 [일수]`.

R7. 슬랙 단타 진행 제어 (Start / Stop / Status)
- Block Kit 버튼: `scalp_start`(단타 진행), `scalp_stop`(단타 멈춤), `scalp_status`(상태 확인).
- 텍스트 명령: `!단타시작`, `!단타멈춤`, `!단타상태`, `!단타백테스트`.
- **시작 게이트**: 백테스트 PASS + HTS 조건식 등록(`HTS_ID`, `SCALP_CONDITION_NAME`, `find_condition_seq`) 필수. 미충족 시 STOPPED 유지 및 Slack 오류 응답.
- **재시작 정책**: `!단타시작`/재시작 시 항상 예산 초기화 후 S_PRE 진입(이전 예산 재사용 금지). Block Kit 예산 메시지 재발송.
- 스케줄 활성 조건: 백테스트 PASS + 사용자 진행 ON(`is_user_running=True`).

R8. 실전 KIS 3분봉 연동 (S0~S5 Live Cycle)
- HTS 조건식(`SCALP_CONDITION_NAME`, 기본 `당일_주도주_발굴`) 후보 종목에 대해 KIS 분봉(FHKST03010200) -> 3분봉 리샘플 -> 일봉 20MA 눌림목 필터 -> 형태 유사도 검증 후 예산 100% 시장가 매수.
- 장중 3분 주기 `_scalp_intraday_job`: 포지션 없으면 `scalp_scan_cycle`, 있으면 `scalp_risk_monitor_cycle`.
- 청산 시 `scalp_trainer.record_trade_result` 학습 적재. 주문 모드 `TRADING_MODE_SCALP`(기본 PAPER).

R9. 단타 세션 영속화 (Service Restart Recovery)
- 모듈 메모리 `_scalp_session_dict` 를 `scalp_session.json`(Drive/로컬)에 동기화한다.
- 저장 대상: `is_user_running`, `lifecycle`, 예산, `budget_requested_at`, `hts_condition_name`, `backtest_passed`, `last_backtest`, `position`(half_sold/highest_price/shape_vector 포함).
- 기동 시 `load_scalp_session()` -> 메모리 복원 -> `paper_portfolio.json` SCALP 포지션과 reconcile.
- 매수/매도는 기존 `record_trade` 로 `paper_trades`/`paper_portfolio` 유지; 리스크 감시는 **세션 position** 우선, 없으면 portfolio SCALP 에서 복구.

2. 비기능 요구사항 (Non-Functional)
N1. 연산 효율성
- 복잡한 이미지 딥러닝(CNN) 대신 1D 수치 배열의 피어슨 상관계수 연산을 통해 AWS LightSail의 CPU 부하를 최소화한다.
N2. 에러 격리 및 인터랙션 폴백
- 사용자의 슬랙 응답 지연이 시스템의 아침 스캐닝 기동을 방해하지 않도록 Non-blocking 타임아웃 자가복구 구조를 보장한다.
- 15:10 강제 청산 시 KIS API 장애로 매도 실패 시 즉시 B-Type 에러를 발생시켜 슬랙 알람을 전송하고 시스템을 일시 중단(Pause)시킨다.