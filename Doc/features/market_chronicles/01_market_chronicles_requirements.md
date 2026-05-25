# Market Chronicles Requirements

1. 기능 요구사항 (Functional)
R1. 트리거 기반 작성 (확장)
  - T-Day 작성 조건: **KST 거래일 + VIX 경계 또는 지수 변동 임계 충족 시 작성**.
  - **시간대 고정 (v1.1, 2026-05-25)**: Market Chronicles 의 모든 날짜·시각 기준은 **대한민국 표준시(KST, Asia/Seoul)** 로 고정한다. T-Day 판정, `report_rel_path` 의 `YYYY-MM-DD`, `_recency_bonus` 의 age 계산 등 모든 시각 비교는 `now_kst()` 또는 `now_kst().date()` 를 통해 수행하며, 서버의 로컬 타임존(특히 UTC)에 의존하지 않는다.
  - **거래일 가드 (v1.1, 2026-05-25)**: `chronicle_writer.write_chronicle_for_today` 는 어떤 진입점(스케줄러 `chronicle_routine`, 슬랙 `!크로니클`, 기타 자동 트리거)에서 호출되든 KST 기준 거래일이 아니면 즉시 거부한다 (반환: `False, "T-Day 크로니클은 KST 거래일에만 작성합니다 (오늘: <라벨>)"`). 주말·공휴일·임시휴장에는 절대 T-Day 리포트를 작성하지 않는다. 과거 임의 날짜의 백필 작성은 `backfill._write_chronicle_for_event` 가 별도 담당한다.
  - 외부 인제스트 위임 수용: 오케스트레이터가 Telegram Pipeline에서 추출된 시황 데이터를 전달할 경우, 이를 Chronicles 적재 및 T-Day 기록의 핵심 요소로 수용한다.
  - 시황 데이터 편입 규칙:
    1. 국내 시황: 당일 수급(기관/외인), 섹터 로테이션, 정책 이슈를 우선적으로 T-Day 기록의 `context_tags_list` 및 `phrases_list`에 편입한다.
    2. 해외 시황 전이 분석: 텔레그램에서 분석된 "해외 매크로 트리거 전이 분석(Transmission Path, 3문장 이내)" 데이터가 수신되면, 이를 리포트의 행동 지침(action_preview) 또는 시장 상태(market_state) 산출의 직접적 인자로 주입하여 기록한다.
R2. 의미 기반 검색
  - 단순 단어 겹침이 아닌 상황/행동 중심 매칭을 사용.
R3. 인덱스 스키마 v2 강제
  - 운영 스키마는 version=2.
R4. 행동 지침 미리보기
  - 본문 열기 전 판단 가능한 action_preview를 유지.

2. 비기능 요구사항 (Non-Functional)
N1. 토큰/속도 최적화
  - AI 가독성 핵심 필드만 노출. 외부 전이 분석 데이터는 원문 전체가 아닌 3문장 요약본만 인덱스에 적재한다.
N2. 안정성
  - AI 실패/네트워크 장애 시 정규식/기본값 폴백.
N3. 무중단 운영
  - Pause 상태에서 재귀 호출 방지.

3. 운영 제약
  - Drive를 단일 소스 오브 트루스로 사용. Market Chronicles는 외부 수집 모듈(Telegram Pipeline)을 절대 직접 import하지 않는다.