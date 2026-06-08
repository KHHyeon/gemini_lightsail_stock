# Scalp Logic Handover (TopK -> VolTarget -> Meta)

최종 갱신: 2026-06-08

## 1) 목표/진행 순서 (고정)
1. Top-K 랭킹+컷 적용
2. 변동성 타깃 사이징 적용
3. 메타라벨링은 데이터 적재 파이프라인 먼저 구축 후, 표본 누적 뒤 학습/추론 도입

본 문서는 위 순서를 지키며 작업한 내용과 다음 작업을 인계한다.

## 2) 이번 변경 요약

### Step 1 완료: Top-K 랭킹+컷
- 파일: `src/execution/orchestrator.py` (`scalp_scan_cycle`)
- 변경:
  - 기존 하드 AND 필터 기반 "첫 통과 즉시 매수" -> 후보 랭킹 방식으로 변경
  - `SCALP_TOP_K` (기본 3) 기반 shortlist 구성
  - 유사도 완화 폭 `SCALP_SIMILARITY_SOFT_MARGIN` (기본 0.02) 도입
  - 랭킹 기준: `(similarity - threshold) margin`, 동률 시 similarity

### Step 2 완료: 변동성 타깃 사이징
- 파일: `src/strategy/scalp_logic.py`
- 신규 함수:
  - `estimate_realized_volatility_ratio()` : 최근 3분봉 수익률 표준편차 추정
  - `calc_vol_targeted_buy_qty()` : 변동성 높을수록 수량 축소
- 파일: `src/execution/orchestrator.py`
- 변경:
  - 매수 수량 계산을 `calc_market_buy_qty` -> `calc_vol_targeted_buy_qty`로 전환
  - 슬랙 매수 메시지에 `vol_scale` 포함

### Step 3 준비 완료: 메타라벨링 데이터 수집 파이프라인
- 신규 파일: `src/memory/scalp_meta_dataset.py`
  - `record_entry_signal()` : 진입 직전 feature 저장 (label=PENDING)
  - `finalize_signal_label()` : 청산 시 WIN/LOSS 라벨 확정
- 연동:
  - `src/execution/orchestrator.py`
    - 진입 시 signal feature 적재 + `signal_id`를 scalp position에 저장
    - 청산(`scalp_risk_monitor_cycle`, `scalp_force_liquidation`) 시 label finalize

## 3) 신규/변경 환경변수

- `SCALP_TOP_K` (int, 기본 3)
  - Top-K shortlist 크기
- `SCALP_SIMILARITY_SOFT_MARGIN` (float, 기본 0.02)
  - `similarity >= threshold - margin` 후보까지 랭킹 대상 확장

참고: 변동성 타깃은 현재 코드 상수(`target_vol_ratio=0.012`, `min_scale=0.35`, `max_scale=1.0`)로 동작.
후속에서 env로 외부화 권장.

## 4) 설계 의도와 운영 메모

- 형태 중심 의존성은 유지:
  - 여전히 shape similarity + threshold가 핵심 점수
  - 차이는 "하드 탈락" 대신 "후보 랭킹"으로 완화한 것
- 단일 종목 보유 정책 유지:
  - 여전히 1종목 보유/진입 구조
- 메타라벨링은 아직 미적용:
  - 현재는 데이터셋만 쌓고, 매매 의사결정에는 사용하지 않음

## 5) 다음 작업 (다른 PC에서 이어서)

### A. 검증/안정화 (필수)
1. 실서버 로그로 Top-K/vol_scale 노출 확인
2. 1주 운영 후 아래 지표 비교
   - 후보 수, shortlist 수, 실제 진입 수
   - 평균 `margin`, 평균 `vol_scale`
   - 승률/평균손익/최대손실
3. 변동성 타깃 파라미터 외부화
   - `SCALP_TARGET_VOL_RATIO`
   - `SCALP_VOL_SCALE_MIN`
   - `SCALP_VOL_SCALE_MAX`

### B. 메타라벨링 본 구현 (표본 누적 후)
1. 최소 표본 기준 정의 (권장: labeled 50~100+)
2. 학습 피처셋 확정
   - similarity, margin, vix, tr_amount, ma_gap, realized_vol, news flag 등
3. 오프라인 학습/검증 스크립트 추가
   - walk-forward OOS 기준으로 precision 우선 평가
4. 실시간 추론 게이트 추가
   - base signal(현재 Top-K) 후 meta 확률로 pass/skip 또는 size 조정

## 6) 빠른 점검 체크리스트

- 단타 시작 후 `!단타 상태`가 ON/S0인지 확인
- 스캔 로그에서 Screener 후 Top-K 매수 로그 또는 no_entry_signal 흐름 확인
- 청산 후 `scalp_meta_signals.json`의 pending 감소/label 증가 확인

## 7) Lightsail 테스트 절차

아래 절차는 운영 서버(예: `stock-lightsail`)에서 동일하게 실행 가능하다.

1. 코드 반영
   - `cd ~/my_bot && git pull`
2. 문법 점검
   - `python -m py_compile src/strategy/scalp_logic.py src/execution/orchestrator.py src/memory/scalp_meta_dataset.py`
3. 단위 테스트
   - `python -m tests.temp_test_scalp_phase_upgrade`
4. 런타임 로그 점검(장중)
   - Screener/News 이후 매수 로그 확인
   - 기대 로그 예시:
     - `[Scalp 매수] ... TopK: ...`
     - `vol_scale ...`
5. 메타 데이터 파일 점검
   - `scalp_meta_signals.json` 생성 여부
   - pending/labeled 카운트 증가 여부

실패 시 우선 확인:
- `SCALP_TOP_K`, `SCALP_SIMILARITY_SOFT_MARGIN` 값 형식(int/float)
- KIS 토큰 및 HTS 조건식 등록 상태
- 장중(09:00~15:10) 실행 여부
