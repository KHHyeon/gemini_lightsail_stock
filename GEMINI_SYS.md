# GEMINI_SYS.md — 시스템 골격 명세서

> 본 문서는 프로젝트의 **전역 시스템 사양** — 인프라, 외부 API 규격, 폴더/모듈 구조, 코딩 가이드라인, 전역 에러 정책 — 을 정의한다. 개별 기능의 비즈니스 로직과 데이터 스키마는 `GEMINI_DETAIL_[FUNCTION].md` 를 참조한다. 전체 변경 히스토리(레거시 통합 기록)는 `GEMINI.md` 가 보존한다(수정·삭제 금지).
>
> 본 문서의 변경 이력은 어떤 경우에도 이전 항목을 생략하지 않고 전체 보존한다(루트 워크스페이스 룰 1.4 준수).

---

## 목차

- [1. 문서 관리 워크플로우 (Strict MD Management)](#1-문서-관리-워크플로우-strict-md-management)
- [2. 코딩 가이드라인 (Coding Standards)](#2-코딩-가이드라인-coding-standards)
- [3. 프로젝트 목적 및 주요 기능](#3-프로젝트-목적-및-주요-기능)
- [4. 전체 파일 구조](#4-전체-파일-구조)
- [5. 변경 이력 — v1.0 ~ v2.9 (시스템 골격 진화)](#5-변경-이력--v10--v29-시스템-골격-진화)
- [6. 외부 API 명세](#6-외부-api-명세)
  - [6.1 KIS Open API](#61-kis-open-api)
  - [6.2 Gemini API](#62-gemini-api)
  - [6.3 Google Drive API](#63-google-drive-api)
  - [6.4 보조 데이터 소스](#64-보조-데이터-소스)
- [7. 인프라 (LightSail / Python 환경)](#7-인프라-lightsail--python-환경)
- [8. 전역 에러 정책 (Pause / Resume / B-Type 보고)](#8-전역-에러-정책-pause--resume--b-type-보고)
- [9. 본 사이클 리팩토링 정합 (선 설계)](#9-본-사이클-리팩토링-정합-선-설계)
- [10. 향후 추진 과제 — 시스템 골격](#10-향후-추진-과제--시스템-골격)

---

## 1. 문서 관리 워크플로우 (Strict MD Management)

본 프로젝트는 다음 3단 문서 체계를 유지한다.


| 문서                   | 역할                                           | 변경 정책                |
| -------------------- | -------------------------------------------- | -------------------- |
| `GEMINI.md`          | 레거시 통합 기록 (전체 히스토리)                          | **수정·삭제 금지** (열람 전용) |
| `GEMINI_SYS.md`      | 전역 시스템 골격                                    | 시스템 골격 변경 시 갱신       |
| `GEMINI_DETAIL_*.md` | 기능별 상세 사양 (예: `GEMINI_DETAIL_CHRONICLES.md`) | 기능 변경 시 갱신           |


### 1.1 참조 우선순위

모든 작업의 시작은 `GEMINI_SYS.md` 와 관련 `GEMINI_DETAIL_*.md` 를 분석하는 것이다. `GEMINI.md` 는 히스토리 확인용으로만 참조한다.

### 1.2 선(先) 설계 후(後) 개발

요구사항 변경 시 반드시 관련 SYS/DETAIL 사양서를 먼저 업데이트하여 **설계 컨펌**을 받은 후 코드를 수정한다. 코드를 먼저 작성하고 사양서를 뒤따라 작성하는 흐름은 금지한다.

### 1.3 Post-Update 동기화

코드 작성 완료 후, 실제 구현된 세부 로직(변수명, 함수 구조, 시그니처 등)을 확인하여 관련 MD 파일에 최종 반영하고 사용자에게 보고한다.

### 1.4 버전 관리

기능이 업데이트·변경·분리될 때마다 버전별 구현율(%)을 재계산하여 문서에 표기한다. **업데이트 시 이전 내용을 생략하지 않고 전체를 유지한다**. 변경 이력은 append-only.

### 1.5 섹션 순서 고정

"향후 추진 과제(Next Steps)" 섹션은 각 MD 파일의 **최하단(마지막 섹션)** 에 위치한다. 신규 버전·기능 상세 섹션을 추가할 경우 향후 추진 과제 **앞**에 삽입한다.

### 1.6 커밋 메시지 정책

변경 사항의 상세 내역(배경·설계·영향)은 SYS/DETAIL 문서에 기록되므로, git 커밋 메시지는 핵심만 담아 **2~3줄 이내**로 간결하게 작성한다. 상세 설명이 필요하면 본문 대신 "자세한 내역은 `GEMINI_SYS.md §N` 또는 `GEMINI_DETAIL_*.md §N` 참조" 한 줄로 대체한다.

---

## 2. 코딩 가이드라인 (Coding Standards)

본 프로젝트의 모든 코드 작성 및 수정 시 다음 규칙을 반드시 준수한다.

### 2.1 변수 명명 (Variable Naming)

- 시스템 전역에서 유니크하고 직관적이어야 하며, 불필요하게 길지 않은(Concise) 이름을 사용한다.
- 구조체 변수는 접미사로 성격을 명시한다.


| 접미사      | 타입                    | 예시                                              |
| -------- | --------------------- | ----------------------------------------------- |
| `_list`  | `list`                | `event_list`, `phrase_list`, `keyword_list`     |
| `_map`   | `dict` (key→value 룩업) | `track_map`, `portfolio_map`, `split_order_map` |
| `_dict`  | `dict` (일반 레코드/구조체)   | `entry_dict`, `state_dict`, `result_dict`       |
| `_set`   | `set`                 | `processed_set`, `skipped_date_set`             |
| `_tuple` | `tuple` (의미 있는 묶음일 때) | `range_tuple`                                   |


기존 코드의 위반 사례는 **본 사이클 리팩토링으로 손이 닿는 파일에 한해 점진 정정**한다(전수 일괄 변경은 별건 PR).

### 2.2 함수 정의 (Function Definition)

- **DRY 원칙**: '동일 로직 - 동일 결과' 인 경우 적극적으로 함수를 재사용한다. 동일 로직 중복은 발견 즉시 공통 헬퍼로 추출한다.
- **논리적 분리**: 동작이 유사하더라도 결과값의 도메인이 다르거나 목적이 다르면 별도의 함수로 정의한다.
- **인자 수 제한**: 단일 함수의 위치 인자가 5개 이상이면 dataclass / config dict 로 묶는 것을 검토한다.

### 2.3 언어 및 주석

- 모든 대화, 설명, 코드 내 주석은 **한국어**로 작성한다.
- docstring 도 한국어를 기본으로 한다.

### 2.4 인코딩 및 특수 문자

- 모든 `.py` 파일은 **UTF-8 인코딩**을 준수한다.
- `# -*- coding: utf-8 -*-` 선언은 1줄만 사용한다 (중복 금지).
- 코드 본문·변수명·주석 내에 **이모지 삽입을 엄격히 금지**한다.
- 비-ASCII 특수기호(`±`, `≥`, `·` 등)는 docstring/주석에서 ASCII 대체(`+/-`, `>=`, `,` 또는 `-`)를 우선한다.
- **슬랙 메시지용** 이모지는 사용 가능하되, 코드 내 하드코딩 대신 유니코드 이스케이프(`"\U0001F600"`) 표기를 사용한다.

### 2.5 파일 분석 제한

- 프로젝트 내의 모든 `.json` 및 `.env` 파일의 내용을 직접 읽거나 분석에 활용하지 않는다(보안).

---

## 3. 프로젝트 목적 및 주요 기능

### 3.1 프로젝트 목적

인간의 감정(두려움, 탐욕)을 배제하고 오직 차가운 데이터와 정교한 알고리즘에 기반하여 주식을 스크리닝하고 운용하는 **AI 기반 퀀트 트레이딩 시스템**이다. 증권사 HTS 조건검색, KIS API 재무 데이터, 거시경제 지표를 결합하여 종목의 기초 체력을 검증하고, 최신 인공지능(LLM)을 통해 정성적 리스크를 팩트체크한다. 기계적인 분할 매수와 3중 철통 방어막을 통해 원금 보호와 수익 극대화를 동시에 추구한다.

### 3.2 주요 기능

- **슬랙(Slack) 기반 챗봇 인터페이스**: `!발굴`, `!ai매수`, `!수동등록`, `!잔고`, `!HTS스캔`, `!타점분석`, `!크로니클`, `!백필스캔` 등 직관적인 명령어로 시스템을 제어하고 리포트를 수신.
- **2단계 매크로 셧다운 (Macro Safety)**:
  - **Level 1 (Shutdown)**: VIX >= 30, WTI >= 95, 미 국채 10년물 >= 4.8% 시 신규 매수 전면 중단.
  - **Level 2 (Half-Buy)**: VIX >= 25, WTI >= 90, 미 국채 10년물 >= 4.5% 시 신규 매수 예산 50% 축소.
  - 임계값 상수는 `src/utils/macro_triggers.py` 에 단일 정의(본 사이클 리팩토링).
- **4단계 하이브리드 스크리닝**: 거시경제 셧다운 → HTS 3대 트랙(기대주/배당주/낙폭과대) 기반 필터링 → 트랙별 특화 펀더멘털 스코어링 → AI 팩트체크(리스크 마이닝) 및 최종 승인.
- **전략별 3-Track 심사 체계**:
  - **기대주(성장)**: ROE 10%+, 영업이익 성장 10%+, 정배열 눌림목 타점.
  - **배당주(가치)**: 시가배당률 3.5%+, 저PER/저PBR, 장기 바닥권 탈피.
  - **낙폭과대(역발상)**:
    - (1차 HTS) 시총 5천억+, 당기순이익 흑자유지, RSI(14) 35 이하 또는 20일 이격도 90% 이하, 5일 이격도 95~105%, 거래대금 30억+.
    - (2차 검증) 하락 진정 변곡점 확인(도지 캔들 또는 거래량 급감), 실시간 뉴스/공시 악재 텍스트 마이닝.
- **AI 리스크 마이닝**: 뉴스/공시에서 횡령, 배임, 감사의견 거절, 임상 실패 등 치명적 악재 키워드 자동 필터링.
- **정밀 변곡점 매수 (Technical Pivot)**:
  - **도지(Doji) 판정**: 당일 캔들의 몸통(Open-Close)이 고가-저가 변동폭의 **1.5% 이하**일 때 추세 반전 신호로 간주.
  - **거래량 급감**: 최근 5거래일 평균 거래량의 50% 이하 또는 전일 대비 50% 이하 기록 시 하락 에너지 소멸로 판단.
- **지능형 포트폴리오 관리 (Portfolio Intelligence)**:
  - **전략 태깅**: '기대주(TRACK_A)', '배당주(TRACK_B)', '낙폭과대(TRACK_C)' 로 출처를 명확히 구분.
  - **상대 강도(RS) 산출**: `(종목 수익률) / (매수 시점 대비 지수 수익률)` 을 계산하여 RS > 1.0 인 종목은 시장 주도주로 분류하여 손절 라인 완화(-17%).
  - **20일 무반등 교체**: 매수 후 20거래일 경과 시점에 수익률이 3% 미만일 경우 슬랙을 통해 '종목 교체(Opportunity Cost)' 검토 알림 발송.
  - **ETF 보호망**: 레버리지/인버스 등 변동성 ETF 의 AI 자동 매수 진입을 원천 차단.
  - **성과 비교**: TRACK 별 AI 자동 매수와 유저 수동 매수의 승률/수익률 교차 분석 리포트 생성.
- **기계적 분할 매수 및 High-Pass 룰**: 예산을 10등분하여 5~10일간 분할 매수. 단, 85점 이상 초우량주는 매수 타점을 유연하게 적용.
- **3중 철통 방어막 및 스마트 익절**: 하드스탑(-10%), 지수 연동형 유연 손절, 수익 발생 시 본전 손절 상향 및 고점 대비 추적 익절(Trailing Stop).
- **확증편향 제거 AI 분석**: 상승 시나리오와 동등한 비중의 '반대 근거(Worst Case)' 분석 및 글로벌 벤치마킹을 통한 주도 세력 변화 감지.
- **스마트 스케줄러**: 시황 보고(08:45), 심층 진단(10:00), 정오 긴급 악재 스캔(11:45), 오후 펀더멘털 진단 및 매수 집행(14:30), Market Chronicles 작성(15:35), 매 30분 실시간 방어막 가동.
- **HTS 3-Track 통합 스캔 (`!HTS스캔`)**: 증권사 HTS 조건식을 통해 추출된 후보군을 파이썬 엔진이 3대 전략(성장/가치/역발상)별로 교차 검증하여 최적의 진입 후보를 선별.
- **기술적 정밀 타점 진단 (`!타점분석`)**: 캔들 몸통 비중(1.5% 이하 도지 판정) 및 거래량(5일 평균 대비 50% 이하)을 분석하여 하락 진정 및 반등 변곡점을 수치화하여 제공.
- **Market Chronicles (v3.x)**: 상세 사양은 `GEMINI_DETAIL_CHRONICLES.md` 참조. 요약하면 — Google Drive 외장 메모리, T-Day 자동 작성, Context Injection 으로 AI 단기 기억 보완, 백필로 과거 60일 행동 지침 DB 사전 확보.

---

## 4. 전체 파일 구조

시스템의 유지보수성과 확장성을 위해 기능을 계층적으로 분리한다. 모든 핵심 소스코드는 `src/` 디렉터리에 위치한다.

### 4.1 디렉터리 트리

```
gemini_lightsail_stock/
  main.py                          # Entry Point. 슬랙 봇 + 스케줄러 통합 실행
  backtester.py                    # 테마 백테스트 스크립트
  GEMINI.md                        # 레거시 통합 기록 (수정 금지)
  GEMINI_SYS.md                    # 본 문서 (시스템 골격)
  GEMINI_DETAIL_CHRONICLES.md      # Market Chronicles 상세 사양
  scripts/
    backfill_chronicles.py         # 백필 CLI 진입점
    drive_oauth_setup.py           # OAuth 토큰 발급/검증
    drive_oauth_refresh.py         # OAuth 토큰 상태 점검 및 refresh
    drive_folder_bootstrap.py      # Quant_Logs 폴더 트리 자동 생성
    _common.py                     # 스크립트 공통 부트스트랩 (본 사이클 신설, §9)
  src/
    core/                          # 증권사 API 통신 및 인증
      kis_api.py                   # KIS API 호출 (본 사이클: _call_kis 래퍼 도입)
      token_manager.py             # KIS API 토큰 생명주기
      account_info.py              # 실계좌 잔고/수익률 조회
    data/                          # 외부 데이터 수집
      collector.py                 # 매크로 지표(VIX, 금리 등) 수집
      chart.py                     # OHLCV 데이터 가공
      crawler/
        news_crawler.py            # 구글 뉴스 RSS 크롤링
        theme_crawler.py           # 네이버 테마 + 소속 종목
        research_crawler.py        # 네이버 산업 분석 리포트
        stock_info_crawler.py      # 네이버 종목 기본 정보
    strategy/                      # 투자 판단 두뇌
      ai_logic.py                  # LLM(Gemini) 정성 분석 + Context Injection
      screener.py                  # 100점 만점 펀더멘털 스코어링
      finder.py                    # 시총 기반 대장주 유니버스
    execution/                     # 자산 운용/보호
      order.py                     # 분할 매수 + 실제 주문 집행
      risk_monitor.py              # 3중 철통 방어막 (실시간 리스크)
      orchestrator.py              # 스케줄러 루틴 통합 제어 (도메인 게이트웨이)
    utils/                         # 공통 유틸리티
      logger.py                    # 가상 장부 JSON 기록
      helpers.py                   # 장 개장 시간 등 공통 도구
      slack_interface.py           # 슬랙 명령어 라우팅
      timekit.py                   # KST/시간 단일 정의 (본 사이클 신설, §9)
      paths.py                     # project_root 단일 정의 (본 사이클 신설, §9)
      jsonio.py                    # 로컬 JSON 읽기/쓰기 (본 사이클 신설, §9)
      macro_triggers.py            # VIX/등락률 임계값 상수 + 트리거 평가 (본 사이클 신설, §9)
    memory/                        # Market Chronicles 외장 메모리 레이어
      __init__.py
      drive_client.py              # Google Drive API + Pause/Resume + manifest
      oauth_token.py               # OAuth 토큰 상태/갱신
      chronicle_writer.py          # T-Day 크로니클 작성
      context_retriever.py         # 유사 행동 지침 Top-3 검색
      lifecycle.py                 # temp/tech 30일 TTL 정리
      backfill.py                  # 과거 60일 소급 구축 (스캔/실행/진단/정리)
      keyphrase_extractor.py       # AI + 정규식 폴백 keyphrase 추출
      chronicle_common.py          # Chronicles 공통 헬퍼 (본 사이클 신설, §9)
```

### 4.2 모듈별 책임 요약

- `**main.py**` — Entry Point. 슬랙 봇 실행, 명령어 라우팅, 스케줄러(루틴) 통합 관리.
- `**src/core/**` — 증권사 API 통신 및 인증. 시스템의 근간.
- `**src/data/**` — 시황 분석에 필요한 외부 데이터 수집(매크로/차트/뉴스/테마/리포트).
- `**src/strategy/**` — 투자 판단(스코어링, AI 정성 분석, 종목 유니버스).
- `**src/execution/**` — 실제 자산 운용/보호(주문, 리스크, 스케줄).
- `**src/utils/**` — 공통 편의 기능 및 유틸리티.
- `**src/memory/**` — Market Chronicles 전용 외장 메모리 레이어.
- `**scripts/**` — 운영용 일회성/주기성 스크립트.

### 4.3 모듈 간 의존성 원칙

- `src/utils/` 는 다른 어떤 `src/*` 모듈도 import 하지 않는다(최하위 레이어).
- `src/core/`, `src/data/` 는 `src/utils/` 만 import 한다.
- `src/strategy/` 는 `src/utils/`, `src/core/`, `src/data/` 를 import 할 수 있다.
- `src/memory/` 는 `src/utils/`, `src/strategy/ai_logic.py`, `src/data/crawler/news_crawler.py` 를 import 한다.
- `src/execution/` 은 모든 상위 모듈을 import 할 수 있는 최상위 레이어(orchestrator 가 게이트웨이 역할).
- `scripts/` 는 `src/*` 를 import 하되, `src/*` 가 `scripts/` 를 import 하는 것은 금지.

---

## 5. 변경 이력 (전 버전 통합 보존, 시스템 설계 레벨 요약)

> 본 절은 시스템 골격(아키텍처/모듈 경계/인터페이스 계약/매크로 정책)의 변천만 한두 줄로 요약한다. 각 버전의 비즈니스 로직·데이터 스키마·엣지 케이스 등 **상세 설계 레벨은 `GEMINI_DETAIL_CHRONICLES.md §6` 또는 GEMINI.md §3 (레거시 원문)** 을 참조한다. 이전 항목은 어떤 경우에도 생략하지 않는다(룰 1.4).

- **초기 단계**: KIS API 연동 기반 마련, 슬랙 봇 뼈대 구축, DART API 를 활용한 100점 만점 펀더멘털 채점표 및 5일선 눌림목 분할 매수 로직 구현.
- **v1.1 업데이트**: VIX(공포지수) 데이터 수집 누락 해결. AI 키워드 반환 시 언패킹(Unpacking) 에러 방지를 위한 쉼표 분리 예외 처리 적용.
- **v1.2 업데이트**: `!수동등록` 명령어 사용 시 발생하는 KIS API 실계좌 보유 수량 조회 에러 해결 (`get_real_holding_qty` 복구). AI 리포트 200자 제한 및 전 구간 이모지 사용 전면 금지 규칙 적용.
- **v1.3 업데이트**: 추적 익절 기준을 -5% 로 좁혔다가 잦은 청산 리스크를 고려하여 절대 원칙인 **-10%** 로 최종 원복. 토큰 발급 로직을 휴일 무조건 차단에서 24시간 캐시 기반 온디맨드 발급으로 유연화.
- **v1.4 업데이트**: 10:00 심층 시황 리포트에서 AI 가 실시간 데이터를 분석하지 못하던 버그 수정 (데이터 바인딩 누락 해결) 및 전반적인 시장 흐름 파악 섹션 추가.
- **v1.5 업데이트 (타협안 및 최적화 일괄 적용)**:
  - 금융주 Two-Track 분리: 금융주 판별 시 ROE 8%, PBR 1.0 이하 기준 적용 및 80점 커트라인 상향. AI 프롬프트에 주주환원 지속성 확인 강제.
  - High-Pass 룰: 채점 85점 이상 초우량주는 5일선 + 5% 까지 매수 타점 완화.
  - 2단계 매크로 셧다운: VIX 25~30 등 노란불 구간에서 신규 매수 예산 50% 축소 로직 신설.
  - 정오의 보초: 11:45 자동 매수 직전 AI 를 통한 보유 종목 돌발 악재 긴급 뉴스 스캔 절차 추가.
- **v1.6 업데이트 (프롬프트 고도화 및 방어막 완성)**:
  - 행동 지침 강화: 일일 시황 및 종목 리포트 AI 프롬프트에 구체적인 투자 의견(5단계: 매수적극찬성~매수적극반대)과 행동 근거(원리 설명)를 명시하도록 업데이트.
  - 3중 철통 방어막 구축: 실시간 리스크 매니저(하드스탑/추적매도 -10%) 와 오후 14:30 AI 펀더멘털 진단을 결합하여 원금 보호 시스템 체계화.
  - AI 전용 규칙 강화: 모바일 가독성을 위한 200자 제한 및 개조식 출력 규칙을 모든 전략 모듈(`ai_strategy.py`)에 전역 적용.
- **v1.7 업데이트 (구조적 리팩토링)**:
  - 단일 디렉토리에 산재해 있던 모듈들을 `src/` 하위의 5개 핵심 레이어(`core`, `data`, `strategy`, `execution`, `utils`)로 재배치.
  - `main.py` 에서 비즈니스 로직을 분리하여 각 모듈의 응집도를 높이고 결합도를 낮춤.
  - 파일 구조 명세 표준화 및 모듈 간 참조 관계 정립.
- **v1.8 업데이트 (Main 모듈 경량화)**:
  - `main.py` 에 집중된 비즈니스 로직을 `orchestrator`(루틴 제어), `slack_interface`(이벤트 핸들링), `stock_info_crawler`(데이터 수집)로 분리 완료.
  - 스케줄러와 슬랙 핸들러 간의 역할 분담을 통해 유지보수성 극대화.
- **v1.9 업데이트 (코딩 규정 통합 및 KIS 가치지표 API 연동)**:
  - `.continue/rules/autostock.md` 의 코딩 규정을 시스템 명세서에 통합.
  - DART API 의존도를 낮추고 정확한 재무 데이터를 위해 KIS 가치지표 API(`FHKST03010300`) 연동 작업 완료.
- **v2.0 업데이트**: 11:45 정오 루틴에 당일 주도주 실시간 스캔 및 자동 매수 로직 추가, 슬랙 핸들러 정규식 최적화.
- **v2.1 업데이트**: `OpenDartReader` 제거, KIS 성장성지표 API(`FHKST03010400`)로 매출/영업이익 증가율 수집 일원화.
- **v2.2 업데이트**: 멀티 에이전트 도입 및 6단계 심층 분석 리포트 체계 구축.
- **v2.3 업데이트**: RSI 과매도/도지/거래량 급감 기반 역발상 전략 정교화 및 `!역발상` 명령어 연동.
- **v2.4 업데이트 (전략 정교화 및 리스크 관리 고도화)**:
  - 저평가 공식 명문화: PBR-ROE 관계식을 이용한 가치 평가 가산점 로직 및 배당 성향(30~40%) 검토 조건 추가.
  - 지수 연동형 손절: 시장 지수 대비 강세 종목에 대해 손절 라인을 최대 -17% 까지 하향 조정하여 노이즈 차단.
  - 8주 타임아웃: 매수 후 40거래일간 무반등 시 기회비용 보호를 위한 자동 매도 룰 신설.
  - AI 비판적 분석: 리포트에 반대 논리(Counter-argument) 비중을 대폭 강화하여 확증편향 방지 및 글로벌 벤치마킹 분석 추가.
- **v2.5 업데이트 (HTS 3-Track 및 정밀 타점 로직, 구현율 98%)**:
  - 전략 다각화: '기대주(성장)', '배당주(가치)', '낙폭과대(역발상)' 3대 트랙별 맞춤형 재무/수급/기술적 지표 적용.
  - 치명적 리스크 필터: AI 텍스트 마이닝을 통해 상장폐지 사유, 횡령, 임상 실패 등 뉴스/공시의 정성적 악재를 선제적으로 배제.
  - 변곡점 타점 정밀화: RSI 과매도 구간에서 도지(Doji) 캔들 혹은 거래량 급감 패턴 확인 시 매수 집행하여 하락 진정 확인 후 진입.
  - 운용 효율화: 종목 성격에 따른 5~10일 유연 분할 매수 및 수익 보존을 위한 트레일링 스탑 로직 고도화.
- **v2.6 업데이트**: HTS 1차 필터(시총/재무/과매도)와 파이썬 2차 검증(도지/거래량/뉴스 마이닝) 역할 분리, 낙폭과대 트랙 리스크 관리 고도화.
- **v2.7 업데이트 (구현율 95%)**: TRACK_A/B/C 태깅, RS 기반 유연 손절(-17%), 20일 무반등 교체 알림, Manual vs AI 성과 비교.
- **v2.8 업데이트 (구현율 99%)**: 슬랙 핸들러 중첩 오류 수정, 매크로 셧다운 임계치 구체화, ETF 필터링, 지수 연동형 RS 계산 정밀화.
- **v2.9 업데이트**: `!HTS스캔`(3-Track 동시 검증) / `!타점분석`(도지·거래량 변곡점) 인터페이스 구축.

### 5.x v3.x — Market Chronicles 외장 메모리 (시스템 설계 레벨 요약)

> 각 항목의 비즈니스 로직·데이터 스키마·운영 명령 인터페이스 등 상세 설계는 `GEMINI_DETAIL_CHRONICLES.md §6` 참조.

- **v3.0** (Drive 실연동, 구현율 85%) — Google Drive 외장 메모리 아키텍처 확정. OAuth 데스크톱 앱 + 인증 모드 자동 감지, Cloud-Only 저장, T-Day 트리거 자동 작성, Context Injection. 신규 레이어 `src/memory/`.
- **v3.1** (Back-filling, 구현율 98%) — 최근 60일 변동성 장세 사후 분석으로 Context Injection 풀 선제 확보. 2단계 동의 흐름 + Drive 상태 보존 + 이어쓰기. 운영 검증 32건(2026-05-20).
- **v3.2** (Semantic Keyphrase, 구현율 92%) — [주체+동사] 구문 단위 의미 매칭. AI 1차 + 정규식 폴백 2차 추출, 5단계 가중 합 점수, 기존 keywords 엔트리 무중단 호환.
- **v3.2.1** (백필 운영 도구, 구현율 95%) — `reset_backfill` / `reindex_keyphrases` 두 모드 + T-Day 엔트리 절대 보호. CLI/슬랙/Orchestrator 3채널 동일 진입점.
- **v3.2.3** (운영 핫픽스, 구현율 97%) — `--reset --purge-reports` 의 `HttpError 404` 버그 idempotent 처리. 잔여(leftover) 정리·진단 명령 신설. 명칭 정정(고아→잔여, 구 명칭 deprecated alias 유지).

### 5.x v3.3 — 문서 체계 전환 + 시스템 골격 리팩토링 (구현율 96%)

> 시스템 골격에 미치는 영향만 한두 줄로 요약. 신설 모듈의 상세 시그니처·통합 대상·변경 파일 일람은 본 문서 **§9 (본 사이클 리팩토링 정합)** 을, Chronicles 영역의 비즈니스 로직 영향은 `GEMINI_DETAIL_CHRONICLES.md §6 v3.3` 을 참조한다.

- **v3.3 업데이트 (문서 체계 전환 + 시스템 골격 리팩토링, 구현율 96%)** — `GEMINI.md` 레거시 보존 + SYS/DETAIL 분할 체계 도입(`master_index.json` 구조 개편 제외). 인프라 5종(`timekit`/`paths`/`jsonio`/`macro_triggers`/`chronicle_common`) + `scripts/_common.py` 신설로 7파일 KST 중복·매직 넘버 6곳·Chronicles 헬퍼 5건·scripts 4종 부트스트랩을 단일 진입점으로 통합. KIS REST 호출 13곳을 `_call_kis` 단일 래퍼(모듈 함수형 + 인스턴스 메서드형)로 일원화. `drive_client` 공개 헬퍼 4종(`delete_file_relative`/`read_master_index`/`append_index_entry`/`write_master_index`) 추가로 캡슐화 강화. 슬랙 라우팅을 `orchestrator` 게이트웨이 경유로 복원 + `messenger.py` 폐기 + `risk_monitor` 시그니처 3-인자로 축소. 변수명 점진 정정 + 코드 위생 (backtester import / orchestrator 주간·월간·분기 routine 통합 / helpers 인코딩 1줄). 잔여 항목(`OrderRequest` dataclass / `record_trade` 명시 인자 / KIS 재시도 정책)은 v3.3.1 패치로 분리 진행.
- **v3.3.1 패치 (이연 항목 정리, 시그니처 정돈 + KIS 재시도 정책)** — `OrderRequest(frozen=True)` dataclass + `OrderManager.submit(request)` 신규 진입점 도입. 위치 인자형 `execute_order(...)` 는 호환 wrapper 로 유지. 호출부 3곳(`orchestrator.py` SELL/BUY, `risk_monitor.py` 장중 손절) 마이그레이션 완료. `record_trade(..., *, mode_type=None, ...)` 키워드 인자 추가 — `None` 폴백으로 하위 호환 유지하면서 `order.submit` / `slack_interface` 호출은 명시 전달. `_call_kis` 재시도·백오프 정책 — GET 만 `max_retries=2`(0.5s→1.0s 지수 백오프, Timeout/ConnectionError/5xx/429 한정), POST 는 강제 0회(중복 주문 방지).

### 5.x v3.4 — Master Index 구조 최적화 (사양 정의 + 코드 구현 완료, 구현율 100%)

> 본 항목은 데이터 스키마 개편 사양 + 코드 구현을 단일 PR 로 일괄 적용한다. 시스템 골격에 미치는 영향은 본 문서 §6.3.4 / §7.5 / §8.1 / §10 에 분산 명시하고, Chronicles 영역의 데이터 스키마·검색 로직·마이그레이션 절차의 상세 사양은 `GEMINI_DETAIL_CHRONICLES.md §5.1 / §6 v3.4 / §7 / §8.6` 을 참조한다.
>
> - 신규/갱신 항목: `macro_triggers.resolve_regime` + `REGIME_NEIGHBOR_MAP`, `chronicle_common.{derive_market_state, derive_context_tags, parse_action_preview}`, `drive_client.DriveSchemaMismatchError` + `read_master_index` 가드 + `AUTO_MIGRATE_V2` 분기, `chronicle_writer` / `backfill` v2 평탄화 적재, `context_retriever._score_entry` 8단계 점수화 + `extract_market_context` dict 반환 + `build_context_injection_block` 3블록 압축, `scripts/migrate_master_index_v2.py` 4단계 진입점.

- **v3.4 업데이트 (Master Index 구조 최적화 — 사양 정의 완료, 구현 0%)** — `master_index.json` 스키마를 `version=1` → `version=2` 로 개편한다. `keyphrases` + `keywords` 두 필드를 단일 `semantic_context` dict 로 통합(필드 `phrases` / `dominant_tone` / `top_subjects` / `summary_kw` / `embedding_vector(reserved=null, v3.5 선행)`). `regime` 자유형 문자열을 표준 enum 8종(`PANIC_SELL` / `FEAR_EXTREME` / `FEAR_RISING` / `TECH_REBOUND` / `BULLISH_RALLY` / `GREED_EXTREME` / `SIDEWAYS` / `SHOCK_OPEN`)으로 표준화하고, 자유형 라벨은 `regime_label` 보조 필드로 보존. `guideline_summary` 는 기존 유지하되 300자 룰을 v3.4 에서 명문화. v1 → v2 마이그레이션은 운영 스크립트 `scripts/migrate_master_index_v2.py`(별건 PR)로 수동 실행. 기동 시 `version=1` 감지하면 신규 B-Type 시나리오로 즉시 Pause + 슬랙 안내(§8.1).

---

## 6. 외부 API 명세

### 6.1 KIS Open API


| 항목       | 값                                                                                                    |
| -------- | ---------------------------------------------------------------------------------------------------- |
| Base URL | `https://openapi.koreainvestment.com:9443` (실전), `https://openapivts.koreainvestment.com:29443` (모의) |
| 인증       | OAuth 2.0 (`AppKey` + `SecretKey` → 24h access token)                                                |
| 토큰 모듈    | `src/core/token_manager.py` — 24h 캐시 기반 온디맨드 발급                                                      |
| 호출 래퍼    | `src/core/kis_api.py:KISClient._call_kis(tr_id, endpoint, params, *, method="GET")` (본 사이클 신설)       |


#### 6.1.1 주요 TR_ID


| TR_ID                     | 용도                                  |
| ------------------------- | ----------------------------------- |
| `FHKST01010100`           | 주식 현재가 시세                           |
| `FHKST01010400`           | 주식 일/주/월/년 차트                       |
| `FHKST03010100`           | 주식 기간별 시세                           |
| `FHKST03010300`           | 주식 가치지표 (PER/PBR/EPS/BPS) — DART 대체 |
| `FHKST03010400`           | 주식 성장성지표 (매출/영업이익 증가율) — DART 대체    |
| `TTTC0802U`               | 주식 현금 매수 주문 (실전)                    |
| `TTTC0801U`               | 주식 현금 매도 주문 (실전)                    |
| `VTTC0802U` / `VTTC0801U` | 모의 매수/매도                            |
| `TTTC8434R`               | 주식 잔고 조회                            |
| `TTTC8001R`               | 매수 가능 조회                            |


#### 6.1.2 호출 공통 규칙

- 모든 호출은 `_call_kis` 단일 래퍼를 경유한다 (본 사이클 B-4 리팩토링).
- HTTP 4xx/5xx 응답에 대해 2회 재시도 후 예외 발생.
- 토큰 만료(401) 감지 시 `token_manager` 가 자동 재발급 후 재시도.
- 일별 호출 한도: 실전 20 TPS / 모의 2 TPS — 본 시스템은 30분 주기 + 슬랙 트리거 기반이므로 한도 충돌 없음.

### 6.2 Gemini API


| 항목    | 값                                                                                                                                          |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 모델    | `gemini-2.0-flash` (기본), `gemini-2.0-pro` (심층 분석)                                                                                          |
| 인증    | API Key (env: `GEMINI_API_KEY`)                                                                                                            |
| 호출 모듈 | `src/strategy/ai_logic.py` — `generate_text(prompt, model_name)`, `generate_text_with_chronicle(prompt, macro, news_snippets, model_name)` |


#### 6.2.1 호출 정책

- **호출 전제**: 모든 매매 판단(매수/매도/시황) AI 호출은 `generate_text_with_chronicle` 를 우선 사용하여 Context Injection 을 활성화한다.
- **Chronicles 작성 자체**: `chronicle_writer.write_chronicle_for_today` 와 `backfill._write_chronicle_for_event` 는 `generate_text`(injection 없는 버전)를 사용 — 자기 자신을 인용하는 순환 편향 방지.
- **응답 길이 제한**: 모바일 가독성을 위해 일반 리포트는 200자 제한, 심층 리포트는 1000자 내외.
- **출력 원칙**: 금융 전문 용어 배제, 일상 언어 사용.
- **반대 논거 강제**: 모든 매매 판단 리포트에 Worst Case 분석 비중을 동등하게 포함하도록 프롬프트 강제.
- **JSON 응답 파싱**: keyphrase 추출 등 구조화 응답은 `_try_parse_json_array` 로 파싱하며, 실패 시 정규식 폴백 활용.

### 6.3 Google Drive API


| 항목     | 값                                                                                              |
| ------ | ---------------------------------------------------------------------------------------------- |
| Scopes | `https://www.googleapis.com/auth/drive.file`, `https://www.googleapis.com/auth/drive.metadata` |
| 인증 모드  | OAuth (데스크톱 앱) — 기본 / Service Account / Domain-wide Delegation / Shared Drive (자동 감지)          |
| 모듈     | `src/memory/drive_client.py`, `src/memory/oauth_token.py`                                      |


#### 6.3.1 인증 모드 자동 감지 (`get_auth_mode()`)


| 모드             | 조건                                      | 비고                        |
| -------------- | --------------------------------------- | ------------------------- |
| `oauth`        | `drive_oauth_token.json` 존재 + 유효        | 가장 권장. storage quota 우회   |
| `delegation`   | SA + `GOOGLE_DRIVE_DELEGATED_USER` env  | Workspace 도메인 한정          |
| `shared_drive` | SA + `GOOGLE_DRIVE_SHARED_DRIVE_ID` env | 공유 드라이브 활용                |
| `sa_plain`     | SA 만 존재                                 | storage quota 한계로 권장하지 않음 |


#### 6.3.2 헤드리스 OAuth 발급

서버(Ubuntu SSH, 브라우저 없음) 환경에서는 다음 절차로 토큰을 발급한다.

```bash
python scripts/drive_oauth_setup.py --check-client    # client_secret JSON 유형 검증
python scripts/drive_oauth_setup.py --no-browser      # 콘솔 인증 (URL 출력 → 인증 코드 입력)
```

`drive_oauth_token.json` 이 생성되면 시스템 가동 시 자동으로 access token 을 refresh 한다. Testing 모드(7일 만료) 감지 시 `invalid_grant` 예외와 함께 슬랙 재발급 안내가 발송된다.

#### 6.3.3 폴더 구조

상세 폴더 구조는 `GEMINI_DETAIL_CHRONICLES.md §1.2` 참조. 최상위는 `Quant_Logs/`, 하위 `MarketChronicles/` 와 `app_data/` 로 구성된다.

#### 6.3.4 공개 API 진입점 (Drive I/O)

본 사이클 리팩토링(B-5) 후 `drive_client.py` 는 다음 공개 함수만 export 한다.


| 함수                                                                                 | 용도                                                                                                                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `init_drive_or_pause(notify_fn=None)`                                              | 봇 기동 시 초기화 또는 Pause                                                                                                                                                                                                                                                                                         |
| `is_ready()` / `is_paused()` / `get_pause_state()`                                 | 상태 조회                                                                                                                                                                                                                                                                                                       |
| `pause(reason, action_required)` / `clear_pause()` / `try_resume_after_user_ack()` | Pause 제어                                                                                                                                                                                                                                                                                                    |
| `read_text_relative(rel_path)` / `write_text_relative(rel_path, text, mime_type)`  | 텍스트 I/O                                                                                                                                                                                                                                                                                                     |
| `read_json_relative(rel_path)` / `write_json_relative(rel_path, data)`             | JSON I/O                                                                                                                                                                                                                                                                                                    |
| `read_app_json(filename)` / `write_app_json(filename, data)`                       | `app_data/` JSON I/O                                                                                                                                                                                                                                                                                        |
| `read_master_index()` / `append_index_entry(entry_dict)`                           | master_index 전용 헬퍼 (v3.3 신설). **v3.4 사양**: default fallback dict 가 `{"version": 2, "entries": []}` 로 갱신되며, `entry_dict` 는 v2 스키마(`semantic_context` / `regime`(enum) / `regime_label` / `guideline_summary` / `report_rel_path` / `trigger` / `source` 등)를 따른다. v3.4 구현 시점에는 코드 갱신 + 마이그레이션 스크립트 실행이 함께 필요. |
| `file_exists_relative(rel_path)` / `delete_file_relative(rel_path)`                | 파일 존재/삭제 (`delete_file_relative` 본 사이클 신설)                                                                                                                                                                                                                                                                  |
| `list_files_under(relative_folder_prefix)`                                         | 폴더 하위 목록                                                                                                                                                                                                                                                                                                    |


`_` prefix 함수는 모듈 외부에서 호출 금지. 본 사이클 리팩토링 시 `backfill._delete_file_at_rel_path` 가 private 함수를 직접 호출하던 위반을 `delete_file_relative` 사용으로 해소.

### 6.4 보조 데이터 소스


| 소스         | 모듈                                                                                  | 용도                                                |
| ---------- | ----------------------------------------------------------------------------------- | ------------------------------------------------- |
| `yfinance` | `src/data/collector.py`, `src/memory/backfill.py`                                   | VIX, WTI, 미 국채, KOSPI/KOSDAQ 일봉 (백필 이벤트 데이 추출 포함) |
| 구글 뉴스 RSS  | `src/data/crawler/news_crawler.py`                                                  | 국내외 종목/시황 뉴스                                      |
| 네이버 금융     | `src/data/crawler/theme_crawler.py`, `research_crawler.py`, `stock_info_crawler.py` | 테마/리포트/기본정보                                       |


---

## 7. 인프라 (LightSail / Python 환경)

### 7.1 호스팅


| 항목    | 값                                     |
| ----- | ------------------------------------- |
| 클라우드  | AWS LightSail                         |
| OS    | Ubuntu 22.04 LTS                      |
| 접근    | SSH 키 기반                              |
| 항상 가동 | systemd 또는 `nohup` 으로 `main.py` 상시 실행 |


### 7.2 Python 환경


| 항목       | 값                                                                                                                                                                                                                                |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python   | 3.10+                                                                                                                                                                                                                            |
| 가상환경     | `venv/`                                                                                                                                                                                                                          |
| 의존성 관리   | `requirements.txt`                                                                                                                                                                                                               |
| 주요 라이브러리 | `slack-bolt`, `schedule`, `requests`, `beautifulsoup4`, `yfinance`, `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`, `google-generativeai`, `python-dotenv`, `pytz` (점진 폐기 예정, §9), `pandas`, `numpy` |


### 7.3 환경 변수 (`.env`)


| 변수                                    | 용도                           |
| ------------------------------------- | ---------------------------- |
| `KIS_APP_KEY` / `KIS_SECRET_KEY`      | KIS API 인증                   |
| `KIS_ACC_NO`                          | 계좌번호                         |
| `KIS_BASE_URL`                        | API Base URL (실전/모의)         |
| `TRADING_MODE`                        | `NORMAL` / `SMALL` / `PAPER` |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Slack 봇 인증                   |
| `SLACK_CHANNEL_ID`                    | 알림 채널                        |
| `GEMINI_API_KEY`                      | Gemini API                   |
| `GEMINI_MODEL`                        | 기본 모델명                       |
| `GOOGLE_DRIVE_ENABLED`                | Drive 사용 플래그                 |
| `GOOGLE_SERVICE_ACCOUNT_PATH`         | SA JSON 경로                   |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID`         | Drive 루트 폴더 ID               |
| `GOOGLE_DRIVE_SHARED_DRIVE_ID`        | 공유 드라이브 ID (선택)              |
| `GOOGLE_DRIVE_DELEGATED_USER`         | DWD 위임 사용자 (선택)              |
| `GOOGLE_OAUTH_CLIENT_SECRET_PATH`     | OAuth client_secret JSON 경로  |
| `GOOGLE_OAUTH_TOKEN_PATH`             | OAuth token JSON 저장 경로       |


### 7.4 로컬 캐시 경로


| 파일                        | 용도                              |
| ------------------------- | ------------------------------- |
| `drive_oauth_token.json`  | OAuth refresh token (사용자 수정 금지) |
| `.drive_pause_local.json` | Drive Pause 로컬 플래그 (시스템 자동)     |
| `gcp_key.json`            | (선택) Service Account 키          |
| `logs/*.log`              | 일별 로그                           |
| `docs_cache/`             | 임시 캐시                           |


**보안**: 위 파일들은 `.gitignore` 에 포함되어 있으며, 본 시스템 규칙상 직접 읽기/분석 대상에서도 제외된다.

### 7.5 Master Index 스키마 마이그레이션 절차 (v3.4 사양)

> 본 절은 v3.4 (`master_index.json` 구조 최적화) 적용 시 운영 절차를 명세한다. 데이터 스키마의 필드별 정의는 `GEMINI_DETAIL_CHRONICLES.md §5.1` 을, 검색 로직 변경은 동 문서 §4.4 / §6 v3.4 를 참조한다.


| 단계             | 절차                                                                                                                                            | 비고         |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 1. 사양 정의       | 본 사이클(v3.4) — SYS / DETAIL 명세 갱신만 진행                                                                                                          | 본 PR 범위    |
| 2. 코드 갱신       | 별건 PR — `drive_client.read_master_index()` default fallback, `chronicle_writer` / `backfill` 색인 적재 로직, `context_retriever` 점수화 로직 갱신          | v3.4 구현 PR |
| 3. 마이그레이션 스크립트 | `scripts/migrate_master_index_v2.py` 신설 — v1 엔트리를 v2 로 변환 (AI 1회 호출로 `semantic_context.summary_kw` 보강, `regime` 자유형 → enum 매핑, `keywords` 폐기) | v3.4 구현 PR |
| 4. 백업          | 마이그레이션 직전 `master_index.json` 을 Drive `_system/backups/master_index_v1_<KST_YYYYMMDD_HHMMSS>.json` 으로 복사                                      | 스크립트 내장    |
| 5. 검증          | `--dry-run` 모드로 v2 변환 결과를 stdout 보고 → 사용자 검토 후 `--apply` 로 실제 덮어쓰기                                                                            | 안전장치       |
| 6. 가동 재개       | v3.4 코드 + v2 인덱스 모두 준비된 상태에서 봇 재기동. 기동 시 `read_master_index()` 가 `version=2` 확인 후 정상 진행                                                       | —          |


**무 마이그레이션 가동 시도**: v3.4 코드가 `version=1` 인덱스를 감지하면 §8.1 의 신규 B-Type 시나리오로 즉시 Pause 한다. 자동 마이그레이션 없이 명시적 운영 절차를 요구하여 데이터 손실을 방지한다.

**선택적 자동 마이그레이션 (`AUTO_MIGRATE_V2`)**: 운영자가 데이터 변경 위험을 명시적으로 수용한 경우에 한해, `.env` 에 `AUTO_MIGRATE_V2=1` 을 설정하면 `drive_client.read_master_index()` 가 `version=1` 감지 시 Pause 대신 `scripts.migrate_master_index_v2.migrate_in_process(ai_enabled=True, delay_sec=3)` 를 즉시 호출하여 변환을 자동 수행한다. 자동 모드도 §7.5 4단계(Scan → Backup → AI 보강 → Apply)를 동일하게 거치며, 백업은 Drive `_system/backups/master_index_v1_<KST_YYYYMMDD_HHMMSS>.json` 으로 생성된다. 자동 실행 종료 후에는 변환 결과 요약(처리 건수 / regime 분포 / AI 호출 횟수)을 슬랙으로 발송한다. 기본값은 `AUTO_MIGRATE_V2=0` (= Pause). 본 옵션은 단발 운영 자동화용이며, 정상 운영 중 상시 활성화는 권장하지 않는다.

---

## 8. 전역 에러 정책 (Pause / Resume / B-Type 보고)

### 8.1 에러 분류


| 분류                     | 정의                                                                          | 응답                                                           |
| ---------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **A-Type (자가 복구)**     | 일시적 네트워크 오류, 일자별 처리 단위 예외 등                                                 | 재시도 또는 해당 단위 스킵 후 다음 진행. 슬랙 통지는 요약만.                         |
| **B-Type (사용자 개입 필요)** | OAuth 토큰 만료, Drive 권한/용량 부족, 폴더 누락, **master_index 스키마 버전 불일치 (v3.4 신규)** 등 | 즉시 **Pause 전환** + 슬랙 B-Type 보고. 사용자 조치 후 `완료` 응답까지 작업 일시 정지. |
| **C-Type (치명적)**       | KIS 계좌 인증 실패, 시스템 설정 오류 등                                                   | 즉시 셧다운 + 슬랙 알람. 운영자 직접 점검 필요.                                |


**v3.4 신규 B-Type 시나리오**: 봇 기동 또는 `read_master_index()` 호출 시 `version=1` 감지 → `DriveSchemaMismatchError` (B-Type) → 슬랙 안내: "`master_index.json` v1 감지. v3.4 가동을 위해 마이그레이션이 필요합니다. `python scripts/migrate_master_index_v2.py --dry-run` 으로 결과 검토 후 `--apply` 실행, 완료 후 `완료` 응답." 기본 정책은 자동 마이그레이션을 수행하지 않는다(데이터 손실 방지). **선택적 자동화 옵션** — `.env` 의 `AUTO_MIGRATE_V2=1` 이면 `read_master_index()` 가 Pause 대신 마이그레이션 스크립트의 `migrate_in_process(...)` 진입점을 즉시 호출하여 변환을 수행한다 (운영자가 데이터 변경 위험을 명시적으로 수용한 경우에 한정). 기본값은 `AUTO_MIGRATE_V2=0` (= Pause).

### 8.2 B-Type Pause/Resume 흐름

```text
[예외 감지]
    |
    v
drive_client.pause(reason, action_required)
    - 로컬 .drive_pause_local.json 기록
    - Drive _system/pause_state.json 동기화 (실패해도 로컬 플래그가 보호)
    |
    v
orchestrator.send_slack("[System Pause] {reason} | 필요 조치: {action_required}")
    |
    v
[사용자 슬랙에 '완료' 입력]
    |
    v
drive_client.try_resume_after_user_ack()
    - Drive 상태 재검증
    - 정상이면 clear_pause()
    - 비정상이면 Pause 유지 + 추가 안내
    |
    v
[작업 재개 또는 추가 대기]
```

`완료` 응답은 Pause 해제 전용 명령이다. 백필 동의를 위한 응답은 `확인` 또는 `!백필실행` 으로 분리한다.

### 8.3 무한 재귀 방지

Pause 가 활성화된 동안 공개 I/O 진입점(`read_*_relative`, `write_*_relative`, `read_app_json`, `write_app_json`, `delete_file_relative`, `read_master_index`, `append_index_entry`)은 `_check_pause_guard()` 에서 즉시 `DrivePausedError` 를 발생시킨다. 이는 Pause 상태에서 또 다른 Drive 호출이 발생해 무한 재귀가 일어나는 것을 차단하기 위함이다.

단, `_read_text_direct`, `_read_json_direct` 같은 내부용 직접 읽기 함수는 pause 점검을 우회한다 — 사용자 조치 후 재검증 단계에서 인덱스를 다시 읽어야 하기 때문이다. 이러한 함수는 모듈 외부에서 직접 호출하지 않는다.

### 8.4 Gatekeeping (사양 단계 보고)

코드 작성 시점에서 구현 로직이 모호하거나 사용자의 지시보다 더 효율적인 대안(토큰 절약, 비용 절감, 안전성 향상 등)이 있다면, AI 에이전트는 작업을 진행하기 전에 **근거와 함께 대안을 먼저 제시**하고 사용자 컨펌을 받는다. 임의 판단으로 진행하지 않는다.

### 8.5 슬랙 메시지 게이트웨이 단일화

본 사이클 리팩토링(B-6, q2=remove)으로 `messenger.py` 는 폐기된다. 모든 슬랙 송출은 `src/execution/orchestrator.py:MarketOrchestrator.send_slack(text)` 단일 게이트웨이를 경유한다.

- `src/execution/risk_monitor.py` 의 `app.client.chat_postMessage` 직접 호출도 `orchestrator.send_slack` 경유로 변경.
- 슬랙 핸들러(`slack_interface.py`)는 Bolt 의 `say()` 콜백을 사용하되, 비동기 알림이 필요할 때는 `orchestrator.send_slack` 을 호출.

---

## 9. 본 사이클 리팩토링 정합 (Post-Update 반영, 구현율 96%)

본 작업 사이클에서 적용된 리팩토링이 시스템 골격에 미치는 영향을 명시한다. 실제 코드 작성을 완료한 후 Post-Update 단계에서 실제 시그니처·통합 범위·변경 파일 일람을 본 절에 반영하였다. 본 사이클에서 별건 PR 로 이연된 항목은 §10 (향후 추진 과제) 에 명시한다.

### 9.1 신규 인프라 모듈


| 모듈                               | 책임                                                                                                                                                                    | 통합 대상                                                                                                                                                                                                                                   |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/utils/timekit.py`           | `KST` 상수 + `now_kst()`/`today_kst()`/`kst_iso_now()`/`kst_strftime(fmt)` 단일 정의                                                                                        | 7개 파일 재선언 (main.py:20, logger.py:6, drive_client.py:12, chronicle_writer.py:9, oauth_token.py:12, lifecycle.py:7, backfill.py:22)                                                                                                       |
| `src/utils/paths.py`             | `project_root()` 단일 정의                                                                                                                                                | `drive_client._project_root` + `oauth_token._project_root`                                                                                                                                                                              |
| `src/utils/jsonio.py`            | `read_local_json(path)` / `write_local_json(path, data)`                                                                                                              | `token_manager`, `oauth_token`, `drive_client`, `scripts/drive_oauth_setup` 의 5+곳 직접 `open()+json.load/dump`                                                                                                                            |
| `src/utils/macro_triggers.py`    | `VIX_CRITICAL`/`VIX_WARN`/`INDEX_SHOCK_PCT` 상수 + `evaluate_chronicle_trigger(vix, kospi_chg, kosdaq_chg)` + `evaluate_macro_shutdown_level(vix, wti, treasury_yield)` | 5개 함수 6곳 분산 매직 넘버 (`chronicle_writer.should_write_chronicle`, `backfill._trigger_reason`, `chronicle_writer._build_keyphrases`, `backfill._build_keyphrases`, `context_retriever.extract_market_context`, `orchestrator.daily_routine`) |
| `src/memory/chronicle_common.py` | Chronicles 공통 헬퍼 (`report_rel_path`, `parse_guideline_summary`, `build_keyphrases`, `append_phrase_unique`, `make_emitter`)                                           | `DETAIL §8.1` 참조                                                                                                                                                                                                                        |
| `scripts/_common.py`             | `setup_script_path()` / `load_env_file(path=None)` / `print_flush(msg)`                                                                                               | scripts/ 4개 파일의 ROOT/sys.path/`_load_env` 부트스트랩 중복                                                                                                                                                                                      |


### 9.2 KIS API 호출 래퍼 (B-4, 구현 완료)

`src/core/kis_api.py` 에 **모듈 함수형 + 인스턴스 메서드형** 두 진입점을 도입하여 KIS REST 호출 패턴 13곳을 단일 래퍼로 통합하였다.

```python
def _call_kis(base_url, app_key, secret_key, token, tr_id, endpoint,
              params=None, *, method="GET", custtype=None,
              timeout=DEFAULT_TIMEOUT_SEC, json_body=None):
    """KIS API 단일 호출 헬퍼 (모듈 함수형). 외부 함수형 호출자가 KISClient
    인스턴스 없이도 동일 헬퍼를 재사용할 수 있도록 한 thin 함수."""

class KISClient:
    def _call_kis(self, tr_id, endpoint, params=None, *, method="GET",
                  custtype=None, timeout=DEFAULT_TIMEOUT_SEC, json_body=None):
        """인스턴스 컨텍스트(base_url/keys/token)를 자동 주입한다."""
```

- `kis_api.py` 7개 메서드 + `account_info.get_detailed_balance` + `chart.get_daily_ohlcv` + `screener.{get_market_cap,get_basic_valuation,get_smart_money_accumulation,get_kis_growth_metrics}` 4종 + `order.execute_order` 의 LIVE POST 분기 — 총 13개 호출이 본 래퍼로 일원화.
- 헤더(Content-Type/authorization/appkey/appsecret/tr_id/[custtype]) 구성·요청 실행·예외 처리·응답 JSON 파싱이 단일 진입점으로 통합되어 약 200 LOC 절감.
- 본 사이클에서는 단순 재시도 정책을 도입하지 않고 `None` 반환을 통한 호출부의 명시적 분기를 유지(과도한 재시도로 인한 API 한도 충돌 방지). 재시도/백오프는 §10 의 별건 추후 과제로 분리.

### 9.3 슬랙 라우팅 복원 (B-6, q1=route, 구현 완료)

- `slack_interface.register_slack_handlers(app, kis, config, orchestrator)` 시그니처에 `orchestrator` 인자를 추가하고, 6개 `cmd_backfill_*` 핸들러 + `cmd_backfill_confirm` 모두 `src.memory.backfill` 직접 import 를 중단. `orchestrator.backfill_*` 게이트웨이만 호출.
- `orchestrator` 에 게이트웨이 메서드 7종(`backfill_scan` / `backfill_run` / `backfill_reset` / `backfill_reindex` / `backfill_diagnose` / `backfill_purge_leftover` / `**backfill_get_state` 신설**)이 확정. `backfill_purge_orphans = backfill_purge_leftover` alias 는 외부 호환을 위해 유지.

### 9.4 messenger.py 폐기 (B-6, q2=remove_msger, 구현 완료)

- `src/utils/messenger.py` 삭제 (호출 0건 dead module 확인 후).
- 모든 슬랙 송출은 `orchestrator.send_slack` 단일 게이트웨이 경유 (`§8.5` 참조).
- `risk_monitor.run_risk_monitor` 의 `app.client.chat_postMessage` 직접 호출도 함수 인자 `send_slack` 콜백 경유로 전환 (main.py 에서 `orchestrator.send_slack` 주입).

### 9.5 코드 위생 (B-9, 본 사이클 적용 결과)


| 위치                                                     | 조치 결과                                                                                                                                                                  |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backtester.py:11`                                     | `from trade_logger import ...` → `from src.utils.logger import load_json_from_gdrive` 로 정정. 완료.                                                                        |
| `src/utils/helpers.py`                                 | `pytz` 의존 제거 + 인코딩 선언 3중 → 1줄 + `timekit` 위임으로 thin wrapper 화. 완료.                                                                                                     |
| `orchestrator.py`                                      | `weekly_routine`/`monthly_routine`/`quarterly_routine` → `_run_portfolio_report(period, news_limit, header_label, *, require_market_open=False, intro=None)` 로 통합. 완료. |
| `risk_monitor.run_risk_monitor` 인자 8개                  | `kis_client + config + send_slack` 3-인자로 축소 + 내부에서 `token_manager.get_access_token` 자동 호출. 완료.                                                                         |
| `order.execute_order` 인자 8개 → `OrderRequest` dataclass | **v3.3.1 패치 완료**. `OrderManager.submit(OrderRequest)` 신규 진입점 + `execute_order(...)` 호환 wrapper. 호출부 3곳(`orchestrator.py:306,376`, `risk_monitor.py:114`) 마이그레이션 완료.    |
| `logger.record_trade` `mode_type` 명시 인자                | **v3.3.1 패치 완료**. `record_trade(..., *, mode_type=None, ...)` 추가. `None` 폴백으로 하위 호환 보장. `order.submit` / `slack_interface` 의 record_trade 호출은 모두 명시 전달.                |
| `backfill.py` docstring 비-ASCII                        | 모듈 docstring 에는 해당 기호 없음. 슬랙 메시지 본문(`±` / `≥`)은 사용자 가독성 유지 위해 보존 (사용자 가이드 위반 없음).                                                                                      |
| `main.py`                                              | `KST` `timekit` 이관 + 사용하지 않는 `token_manager` import 제거.                                                                                                                |
| `token_manager.py`                                     | `read_local_json` / `write_local_json` / `project_root()` 사용으로 정리. 완료.                                                                                                 |


### 9.6 변수명 점진 정정 (B-8, q3=touched_only)

본 사이클로 손이 닿는 파일에 한해 `_list`/`_map`/`_dict`/`_set` 접미사를 정정한다. 전수 일괄 변경은 별건 PR.

### 9.7 변경 영향 정합 매트릭스 (Post-Update 확정본)


| 모듈                                                                                                    | 영향                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/memory/chronicle_common.py` (신설)                                                                 | `report_rel_path` / `parse_guideline_summary` / `build_keyphrases(*, vix, kospi_chg, kosdaq_chg)` / `append_phrase_unique` / `make_emitter(notify_fn)` 5종 헬퍼 단일화.                                                                                                                                                                         |
| `src/memory/chronicle_writer.py`                                                                      | 헬퍼 5종 → `chronicle_common` 호출 + `derive_tokens` 직접 사용. 트리거 → `macro_triggers.evaluate_chronicle_trigger`. KST → `timekit.now_kst`. master_index append → `drive_client.append_index_entry`.                                                                                                                                               |
| `src/memory/backfill.py`                                                                              | 위와 동일 + `_emit` 6회 → `chronicle_common.make_emitter` 통합. `_delete_file_at_rel_path` 는 `drive_client.delete_file_relative` 의 호환 wrapper 로 축소. `_legacy_keyword_view` 제거. `_safe_float` → `macro_triggers._safe_float`. master_index read/append/write 6곳 → `drive_client.read_master_index` / `append_index_entry` / `write_master_index`. |
| `src/memory/context_retriever.py`                                                                     | `_append` → `chronicle_common.append_phrase_unique`. 매크로 트리거 임계값 → `macro_triggers.{VIX_WARN,VIX_CRITICAL,INDEX_SHOCK_PCT,_safe_float}`. master_index read → `drive_client.read_master_index`.                                                                                                                                            |
| `src/memory/drive_client.py`                                                                          | KST → `timekit`, `_project_root` → `paths.project_root`. **공개 헬퍼 4종** 추가: `delete_file_relative` / `read_master_index` / `append_index_entry` / `write_master_index`.                                                                                                                                                                     |
| `src/memory/oauth_token.py`                                                                           | `_project_root` → `paths.project_root`. 로컬 JSON I/O → `jsonio.read_local_json`. KST → `timekit`.                                                                                                                                                                                                                                          |
| `src/memory/lifecycle.py`                                                                             | KST → `timekit`. 변수명 `_list` / `_count` 접미사 정정.                                                                                                                                                                                                                                                                                           |
| `src/core/kis_api.py`                                                                                 | 모듈 함수 `_call_kis` + 인스턴스 메서드 `KISClient._call_kis` 두 진입점 도입. 7개 메서드 모두 본 래퍼 경유.                                                                                                                                                                                                                                                           |
| `src/core/account_info.py`, `src/data/chart.py`, `src/strategy/screener.py`, `src/execution/order.py` | KIS 호출을 모듈 함수 `_call_kis` 경유로 변경 (6 함수 + LIVE 주문 1곳, 총 7곳). `chart.py` 는 `timekit.now_kst` 도 사용.                                                                                                                                                                                                                                          |
| `src/core/token_manager.py`                                                                           | 로컬 JSON I/O → `jsonio`, `project_root` → `paths`. 변수명·예외 처리 정돈.                                                                                                                                                                                                                                                                           |
| `src/execution/orchestrator.py`                                                                       | `send_slack` 단일 게이트웨이. `weekly/monthly/quarterly_routine` → `_run_portfolio_report` 로 통합. `backfill_get_state` 게이트웨이 신설. `backfill_purge_orphans` alias 유지.                                                                                                                                                                               |
| `src/execution/risk_monitor.py`                                                                       | 인자 8개 → 3-인자(`kis_client, config, send_slack`) 축소. `chat_postMessage` 직접 호출 제거. `timekit.now_kst` 사용.                                                                                                                                                                                                                                     |
| `src/execution/order.py`                                                                              | `_call_kis` 사용 + `timekit.kst_strftime` 사용. **v3.3.1**: `OrderRequest` dataclass + `OrderManager.submit(request)` 신규 진입점 도입, `execute_order(...)` 는 호환 wrapper 로 유지.                                                                                                                                                                      |
| `src/utils/slack_interface.py`                                                                        | `register_slack_handlers(..., orchestrator)` 시그니처 확장. 7개 백필 핸들러 모두 `orchestrator.backfill`_* 경유로 복원.                                                                                                                                                                                                                                      |
| `src/utils/logger.py`                                                                                 | KST → `timekit.now_kst`. 로컬 JSON I/O → `jsonio`. 경로 → `paths.project_root`. **v3.3.1**: `record_trade(..., *, mode_type=None, ...)` 키워드 인자 추가 (None 폴백으로 하위 호환 유지).                                                                                                                                                                       |
| `src/utils/helpers.py`                                                                                | `pytz` 의존 제거. 인코딩 선언 3중 → 1줄. `timekit` 위임 thin wrapper 화.                                                                                                                                                                                                                                                                                |
| `src/utils/messenger.py`                                                                              | **파일 삭제** (dead module).                                                                                                                                                                                                                                                                                                                  |
| `src/utils/{paths,timekit,jsonio,macro_triggers}.py` (신설)                                             | §9.1 표 참조.                                                                                                                                                                                                                                                                                                                                |
| `main.py`                                                                                             | `KST` `timekit` 이관, 미사용 `token_manager` import 제거, `slack_interface.register_slack_handlers` 호출 시 `orchestrator` 주입, `risk_manager.run_risk_monitor` 3-인자 호출.                                                                                                                                                                             |
| `backtester.py`                                                                                       | `from trade_logger import ...` → `from src.utils.logger import load_json_from_gdrive` 정정.                                                                                                                                                                                                                                                 |
| `scripts/_common.py` (신설)                                                                             | `setup_script_path` / `load_env_file` / `print_flush` 단일화.                                                                                                                                                                                                                                                                                |
| `scripts/{backfill_chronicles,drive_oauth_setup,drive_oauth_refresh,drive_folder_bootstrap}.py`       | `_common.py` 사용으로 부트스트랩 일원화.                                                                                                                                                                                                                                                                                                              |


---

## 10. 향후 추진 과제 — 시스템 골격

> 본 절은 본 문서(`GEMINI_SYS.md`)의 최하단에 위치한다. 신규 시스템 골격 관련 섹션 추가 시 본 절 **앞**에 삽입한다. Chronicles 전용 후속 과제는 `GEMINI_DETAIL_CHRONICLES.md §9` 를 참조.

1. **전문가 인사이트 엔진 (Expert Insight Engine)**
  - 증권사 RSS 피드 또는 리포트 요약 채널 기반의 정성적 데이터 수집.
  - 리포트 내 목표 주가(TP), 투자의견(Rating), 핵심 논거(Thesis) 구조화 추출 및 AI 교차 검증 활용.
2. **섹터별 특화 HTS 조건식 확장**
  - 금융주 외 제약/바이오(R&D 투자 비율), 조선/기계(수주 잔고) 등 섹터별 핵심 지표를 반영한 HTS 조건식 추가.
  - 트랙 D/E/F 신설 가능성 검토.
3. **실전(Live) 환경 전환 테스트**
  - Paper(모의) 모드에서 충분한 안정성이 검증된 후, `TRADING_MODE_NORMAL` 환경변수를 조정하여 실제 KIS 계좌 매수/매도 체결 딜레이 및 슬랙 알림 응답 속도 최적화.
4. **변수명 일괄 정정 별건 PR**
  - 본 사이클의 점진 정정에서 빠진 파일들에 대한 일괄 정정 PR. 큰 diff 를 단일 변경으로 처리하여 본 사이클의 핵심 변경과 리뷰 비용을 분리.
5. **시그니처 정돈 (OrderRequest dataclass / record_trade `mode_type` 명시 인자)** — **v3.3.1 패치 완료**
  - `OrderManager.submit(request: OrderRequest)` 신규 진입점 + 위치 인자형 `execute_order(...)` 호환 wrapper 유지. 호출부 3곳(`orchestrator.py:306,376`, `risk_monitor.py:114`) 모두 `OrderRequest` + `submit` 으로 마이그레이션.
  - `logger.record_trade(..., *, mode_type=None, ...)` 키워드 인자 추가. `None` 이면 `reason` 인퍼런스 폴백을 유지하여 하위 호환 보장. `order.submit` / `slack_interface.action_approve_buy` 의 record_trade 호출은 모두 명시 전달.

5-A. **Master Index v2 코드 구현 (v3.4 사양 적용 PR)** — **사양 정의 완료, 구현 완료 (100%)**

- 본 사이클(v3.4)에서는 사양(SYS §7.5 / §8.1 / DETAIL §4.3.2 / §4.4 / §5.1.2 / §5.1.3 / §6 v3.4 / §7)만 정의했으며, 코드 변경은 별건 PR 로 분리한다.
- 적용 범위 (7개 항목):
  1. `drive_client.read_master_index()` default fallback `{"version": 2, "entries": []}` 갱신 + `version` 검증 가드 + 신규 예외 `DriveSchemaMismatchError`(B-Type, SYS §8.1) 발생.
  2. `chronicle_writer` / `backfill` 색인 적재 — entry 최상위 평탄화 4필드 산출: `market_state`(`regime`/`regime_label`/`main_actor`/`sentiment`) + `context_tags_list` + `action_preview` + `phrases_list` 보조 보존.
  3. `chronicle_common` 신규 헬퍼 3종 — `derive_market_state(phrases_list, *, vix, kospi_chg, kosdaq_chg)` / `derive_context_tags(phrases_list, market_state_dict)` / `parse_action_preview(ai_text)` (v3.3 의 `parse_guideline_summary` 갱신, `[:200]` 슬라이싱).
  4. `macro_triggers.resolve_regime(vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None) -> str` 신설 + 인접 그룹 상수 `REGIME_NEIGHBOR_MAP`(dict[str, list[str]]).
  5. `context_retriever._score_entry` 재설계 — 8단계 가중치(DETAIL §4.3.2: `context_tags_list` 자카드 1순위 +10/+6/+3, `market_state.regime` 정확/인접 +5/+2, `main_actor`/`sentiment` 보너스 +1.5 각, `phrases_list` 보조 폴백 +4/+2, 최근성, `embedding_vector` v3.5 예약). `keywords` 폴백 완전 제거.
  6. `context_retriever.extract_market_context` 산출 필드 갱신 — `query_context_tags_list` / `query_regime`(enum) / `query_main_actor_keyword` / `query_sentiment` 4종. `build_context_injection_block` 출력을 3블록(헤더/태그/지침)으로 압축, `phrases_list`/`embedding_vector` 비노출.
  7. 운영 스크립트 `scripts/migrate_master_index_v2.py` (4단계: Scan → Backup → AI 보강 → Apply, `--dry-run`/`--apply`/`--delay-sec`/`--no-ai`/`--limit` 인자, DETAIL §7 표 명세).
- DRY 원칙 준수: §9.1 의 `chronicle_common.build_keyphrases` / `macro_triggers.evaluate_chronicle_trigger` / `jsonio.{read,write}_local_json` / `scripts/_common.{setup_script_path, load_env_file, print_flush}` 헬퍼를 가능한 한 그대로 재사용 (마이그레이션 스크립트도 본 헬퍼 경유).

1. **KIS `_call_kis` 재시도/백오프 정책** — **v3.3.1 패치 완료**
  - `GET`: `max_retries=2` (총 시도 3회), `backoff_base=0.5`s 지수 백오프(0.5→1.0). 재시도 조건은 `Timeout` / `ConnectionError` / HTTP 5xx / HTTP 429. 그 외 4xx 는 즉시 `None`.
  - `POST`: **항상 0회 재시도** (중복 주문 방지). `max_retries` 인자가 들어와도 강제 0.
  - 인터페이스: `_call_kis(..., *, max_retries=None, backoff_base=0.5)` (모듈 함수 + `KISClient` 메서드 동일).
2. **로깅 표준화**
  - `print` 직접 호출(현재 `logger.py`, `main.py` 등) 을 `logging` 모듈 기반 표준 로거로 통합.
  - 일별 로그 로테이션 + 로그 레벨 환경변수 제어.
3. **테스트 인프라 도입**
  - 현재 코드베이스는 단위 테스트가 부재. `pytest` 도입 및 핵심 모듈(`chronicle_common`, `macro_triggers`, `KISClient._call_kis`)부터 점진 테스트 작성.
4. **CI/CD 파이프라인**
  - GitHub Actions 로 lint(`ruff`) + 인코딩/이모지 검사 + import 정합성 검사 자동화.

