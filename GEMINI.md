# AI 퀀트 트레이딩 시스템 명세서 (GEMINI.md)

**[현재 구현 현황]**
*   **v1.8 리팩토링 완료:** main.py 비즈니스 로직 완전 분리 및 파일 구조 최적화 완료.
*   **v1.9 KIS 가치지표 API 연동 완료:** DART 의존도를 낮추고 KIS 공식 API(`FHKST03010300`)를 통한 실시간 재무 데이터 수집 및 펀더멘털 스코어링 고도화 완료.
*   **v2.0 주도주 스캐너 및 핸들러 최적화 완료:** 11:45 정오 루틴에 '당일 주도주' 실시간 스캔 및 자동 매수 로직 추가, 슬랙 핸들러 정규식 최적화 완료.
*   **v2.1 DART 완전 대체 및 KIS API 전면 전환 완료:** `OpenDartReader` 의존성을 제거하고 KIS 성장성지표 API(`FHKST03010400`)로 매출/영업이익 증가율 수집 로직 일원화 완료.
*   **v2.2 AI 교차 검증 및 리포트 체계 개편 완료:** 멀티 에이전트 도입 및 6단계 심층 분석 리포트 체계 구축 완료.
*   **v2.3 역발상 저가 매수 전략 정교화 완료:** RSI 과매도 및 하락 진정 패턴(도지, 거래량 급감) 감지 로직 구현 및 `!역발상` 명령어 연동 완료.
*   **v2.4 가치 평가 공식 명문화 및 리스크 대응 로직 고도화 완료:** PBR-ROE 산식 기반 저평가 판별, 지수 연동형 변동성 손절 및 8주 타임아웃 룰 도입, AI 확증편향 제거를 위한 반대 논리 분석 강화.
*  **v2.5 HTS 3-Track 전략 및 정밀 타점 로직 도입 완료 (구현율 98%):** '기대주(성장)', '배당주(가치)', '낙폭과대(역발상)'의 3대 트랙별 특화 심사 체계 구축, AI 텍스트 마이닝 기반 치명적 악재 필터링, 도지(Doji) 캔들 및 거래량 분석을 통한 정밀 변곡점 매수 로직 구현 및 HTS 연동 최적화.
*  **v2.6 2차 검증 로직 정교화 (낙폭과대 트랙 집중):** HTS 1차 필터링 조건(시총, 재무, 과매도)과 파이썬 2차 검증(도지/거래량 정밀 타점, 뉴스/공시 텍스트 마이닝)의 역할을 명확히 분리하고 리스크 관리 로직을 고도화.
*  **v2.7 지능형 포트폴리오 관리 및 상대 강도(RS) 손절 도입 (구현율 95%):** '기대주(TRACK_A)', '배당주(TRACK_B)', '낙폭과대(TRACK_C)' 태깅 시스템 도입, 지수 대비 상대 강도(RS) 기반 유연 손절(-17%) 및 20일 무반등 종목 교체 알림 로직 구현, Manual vs AI 성과 비교 체계 구축.
*   **v2.8 시스템 안정화 및 명세 고도화 완료 (구현율 99%):** 슬랙 인터페이스 핸들러 중첩 오류 수정, 거시경제(유가, 금리) 셧다운 임계치 구체화, ETF 자동 필터링 및 매수 시점 지수 연동형 RS(Relative Strength) 계산 로직 정밀화 완료.
*   **v2.9 HTS 통합 스캔 및 정밀 타점 진단 인터페이스 구축 완료:** `!HTS스캔` 명령어를 통한 3-Track 동시 검증 및 `!타점분석` 명령어를 통한 개별 종목 도지/거래량 변곡점 판별 로직 연동 완료.
*   **v3.0 Market Chronicles (지능형 메모리 아키텍처) — Drive 실연동 완료 (구현율 85%):** OAuth(데스크톱 앱, headless `--no-browser`) 인증·자동 토큰 갱신·storage quota 우회 적용. 실서버(`Quant_Logs/MarketChronicles/{index,reports,temp,_system}`, `app_data/`) 폴더 구조 자동 생성 및 `master_index.json` 초기화 완료. `src/memory/` 4모듈, AI Context Injection, 15:35 스케줄, `!크로니클`/`완료` 슬랙 명령 동작. (설정: `MARKET_CHRONICLES_SETUP.md`, 상세: **§4**)
*   **v3.1 Market Chronicles 과거 데이터 소급 구축 (Back-filling) — 실전 검증 완료 (구현율 98%):** 최근 60일 KOSPI/KOSDAQ/VIX(yfinance) 일봉 스캔으로 트리거($\pm 1.5\%$ 또는 VIX$\ge$25) '이벤트 데이' 추출 → 과거 시점 뉴스 + AI 사후 분석 → `.md` 리포트 + `master_index.json` 색인. **신규 모듈** `src/memory/backfill.py`, **CLI** `scripts/backfill_chronicles.py`, **슬랙** `!백필스캔`/`!백필실행`/`확인`. **운영 검증(2026-05-20):** 60일 윈도우에서 **완료 32 / 스킵 0 / 실패 0** 으로 첫 회 백필 종결. 가동 즉시 Context Injection 가능한 32건의 과거 행동 지침 DB 확보. (상세: **§5**)
*   **v3.2 Semantic Keyphrase Indexing & Retrieval — 적용 완료 (구현율 92%):** "외국인 매수"와 "외국인 매도" 같은 정반대 의미를 단순 단어 매칭이 같은 항목으로 오인하는 문제를 해결. 인덱싱 단계는 **[주체 + 동사] 결합 핵심 구문(keyphrases)** 을 Gemini로 추출(실패 시 정규식 사전 폴백) 후 `subject/action/tone` 메타데이터까지 함께 보존. 검색 단계는 **구문 자카드 유사도 + subject·action 정규형 일치 + tone 일치 + regime 그룹 매칭 + 최근성(recency)** 의 5단계 가중 합으로 의미적 유사도를 우선 적용하고, 단어 토큰 매칭은 폴백으로만 사용. **신규 모듈** `src/memory/keyphrase_extractor.py`. **호환:** 기존 엔트리는 `keywords` 만으로도 토큰 폴백으로 검색되어 무중단 전환. (상세: **§6**)
*   **v3.2.1 Backfill 초기화·재인덱싱 운영 도구 — 적용 완료 (구현율 95%):** v3.1 백필이 이미 진행된 상태에서도 v3.2 의미 색인으로 안전하게 전환·재구축할 수 있도록 두 가지 모드 제공. **`--reset`/`!백필초기화`:** `master_index.json` 의 `source="backfill"` 엔트리와 `backfill_state.json` 을 비우고(옵션으로 `.md` 리포트까지 삭제) 처음부터 다시 채울 수 있는 상태 복원. **`--reindex`/`!백필재인덱싱`:** 기존 `.md` 리포트는 보존한 채 AI 1회 호출로 `keyphrases` 만 v3.2 포맷으로 재추출(비용·시간 최소 경로). T-Day(`source != "backfill"`) 엔트리는 어떤 경우에도 보호. (상세: **§5.6**)
*   **v3.2.3 Backfill 운영 핫픽스 + 잔여 정리·진단 명령 — 적용 완료 (구현율 97%):** v3.2.1 `--reset --purge-reports` 시 `drive_client._find_file_in_parent` 가 file ID 문자열이 아닌 메타데이터 dict 를 반환하여 `delete_file_by_id` 호출 URL 이 깨지는 버그(`HttpError 404`) 수정. 인덱스는 비워졌지만 일부 `.md` 가 인덱스 외부에 남는 "잔여(leftover)" 상태를 위해 **`--purge-leftover-reports`/`!백필잔여정리`** 보조 명령 신설(헤더 표식 + 인덱스 미등록 조건 동시 충족만 삭제, T-Day 자동 보호, `--dry-run` 지원). 또한 "왜 잔여가 0건만 보고되는가" 와 같은 운영 의문을 즉답하기 위해 **`--diagnose-reports`/`!백필상태`** 진단 명령 신설 — reports 트리와 master_index 정합 상태를 읽기 전용으로 보고. 기존 `--purge-orphan-reports`/`!백필고아청소` 는 deprecated alias 로 호환 유지. (상세: **§5.6**)


# 목차

- [리팩토링 및 사양서 동기화 규칙](#리팩토링-및-사양서-동기화-규칙)
- [코딩 가이드라인 (Coding Guidelines)](#코딩-가이드라인-coding-guidelines)
- [1. 프로젝트 목적 및 주요 기능](#1-프로젝트-목적-및-주요-기능)
- [2. 프로젝트 구조 및 파일 설명](#2-프로젝트-구조-및-파일-설명-v31-기준-market-chronicles--back-filling-포함)
- [3. 변경 이력 (Change Log)](#3-변경-이력-change-log)
- [4. v3.0 Market Chronicles (지능형 메모리 아키텍처)](#4-v30-market-chronicles-지능형-메모리-아키텍처)
    - [4.1 시스템 핵심 아키텍처 (Cloud-Only & Interaction)](#41-시스템-핵심-아키텍처-cloud-only--interaction)
    - [4.2 분석 로직: 인과 관계 분석 및 행동 지침 도출](#42-분석-로직-인과-관계-분석-및-행동-지침-도출)
    - [4.3 인공지능(AI) 적용 및 실질적 교정 방안](#43-인공지능ai-적용-및-실질적-교정-방안)
    - [4.4 v2.x 대비 구현 갭 (현재 코드베이스)](#44-v2x-대비-구현-갭-현재-코드베이스)
    - [4.5 v3.0 구현 체크리스트](#45-v30-구현-체크리스트)
- [5. v3.1 과거 데이터 소급 구축 (Back-filling)](#5-v31-과거-데이터-소급-구축-back-filling)
    - [5.1 목적 및 트리거](#51-목적-및-트리거)
    - [5.2 처리 단계 (Scan → Confirm → Backfill → Index)](#52-처리-단계-scan--confirm--backfill--index)
    - [5.3 진행 상태 보존 및 예외 처리](#53-진행-상태-보존-및-예외-처리)
    - [5.4 사용 인터페이스 (Slack / CLI / Orchestrator)](#54-사용-인터페이스-slack--cli--orchestrator)
    - [5.5 v3.1 구현 체크리스트](#55-v31-구현-체크리스트)
    - [5.6 v3.2.1 초기화·재인덱싱 운영 도구](#56-v321-초기화재인덱싱-운영-도구)
- [6. v3.2 Semantic Keyphrase Indexing & Retrieval](#6-v32-semantic-keyphrase-indexing--retrieval)
    - [6.1 문제 정의 — 단어 매칭의 한계](#61-문제-정의--단어-매칭의-한계)
    - [6.2 인덱싱 — [주체 + 동사] 구문 추출](#62-인덱싱--주체--동사-구문-추출)
    - [6.3 검색 — 의미적 유사도 우선 가중치](#63-검색--의미적-유사도-우선-가중치)
    - [6.4 master_index.json 엔트리 스키마 변경](#64-master_indexjson-엔트리-스키마-변경)
    - [6.5 v3.2 구현 체크리스트](#65-v32-구현-체크리스트)
- [7. 향후 추진 과제 (Next Steps)](#7-향후-추진-과제-next-steps) (항상 문서 마지막)


# 리팩토링 및 사양서 동기화 규칙
1. **동시 업데이트**: 코드를 파일 단위로 분리하거나 수정할 때, 반드시 `GEMINI.md`의 [현재 구현 현황] 및 [파일 구조] 섹션을 해당 변경 사항에 맞게 즉시 업데이트한다.
2. **반영률 갱신**: 기능이 업데이트, 변경, 분리되거나 최적화될 때마다 버전 별 구현율(%)을 재계산하여 버전과 함께 표기한다.
3. **출력 형식**: 코드 파일 생성이 끝나면, 이어서 `GEMINI.md`에 추가/수정해야 할 마크다운 텍스트 블록을 별도로 제공한다.
4. **섹션 순서 고정**: **향후 추진 과제(Next Steps) 섹션은 항상 `GEMINI.md`의 최하단(마지막 섹션)에 위치한다.** 신규 버전·기능 상세 섹션을 추가할 경우 향후 추진 과제 **앞**에 삽입한다.
5. **커밋 메시지 정책**: 변경 사항의 상세 내역(배경·설계·영향)은 본 `GEMINI.md`에 기록되므로, git 커밋 메시지는 핵심만 담아 **2~3줄 이내**로 간결하게 작성한다. 상세 설명이 필요하면 본문 대신 "자세한 내역은 `GEMINI.md` §N 참조" 한 줄로 대체한다.

# 코딩 가이드라인 (Coding Guidelines)
본 프로젝트의 모든 코드 작성 및 수정 시 다음 규칙을 반드시 준수한다.

1. **언어 및 주석**: 모든 대화, 설명, 코드 내 주석은 **한국어**로 작성한다.
2. **코드 내 이모지 절대 금지**: 소스 코드 파일(`.py`) 내부(주석, 변수명 포함)에는 이모지를 삽입하지 않는다.
3. **슬랙 메시지 이모지**: 가독성을 위해 슬랙으로 전송되는 메시지에는 이모지를 사용할 수 있으나, 코드 내 하드코딩 대신 유니코드 대피 문자(예: `\U0001F600`)를 사용한다.
4. **파일 분석 제한**: `.json` 및 `.env` 파일의 내용을 직접 읽거나 분석에 활용하지 않는다.
5. **선 수정 후 개발**: 요구사항 변경 시 반드시 `GEMINI.md`의 변경 이력을 먼저 업데이트한 후 코드를 수정한다.
6. **UTF-8 준수**: 모든 코드 파일은 UTF-8 인코딩을 준수하며 특수 문자열 삽입을 금지한다.

## 1. 프로젝트 목적 및 주요 기능
**[프로젝트 목적]**
인간의 감정(두려움, 탐욕)을 배제하고 오직 차가운 데이터와 정교한 알고리즘에 기반하여 주식을 스크리닝하고 운용하는 AI 기반 퀀트 트레이딩 시스템입니다. 증권사 HTS 조건검색, DART 재무 데이터, 거시경제 지표를 결합하여 종목의 기초 체력을 검증하고, 최신 인공지능(LLM)을 통해 정성적 리스크를 팩트체크합니다. 기계적인 10일 분할 매수와 3중 철통 방어막을 통해 원금 보호와 수익 극대화를 동시에 추구합니다.

**[주요 기능]**
* **슬랙(Slack) 기반 챗봇 인터페이스:** `!발굴`, `!ai매수`, `!수동등록`, `!잔고` 등 직관적인 명령어로 시스템을 제어하고 리포트를 수신.
* **2단계 매크로 셧다운 (Macro Safety):**
    * **Level 1 (Shutdown):** VIX >= 30, WTI >= 95, 미 국채 10년물 >= 4.8% 시 신규 매수 전면 중단.
    * **Level 2 (Half-Buy):** VIX >= 25, WTI >= 90, 미 국채 10년물 >= 4.5% 시 신규 매수 예산 50% 축소.
* **4단계 하이브리드 스크리닝:** 거시경제 셧다운 -> HTS 3대 트랙(기대주/배당주/낙폭과대) 기반 필터링 -> 트랙별 특화 펀더멘털 스코어링 -> AI 팩트체크(리스크 마이닝) 및 최종 승인.
* **전략별 3-Track 심사 체계:** 
    * **기대주(성장):** ROE 10%+, 영업이익 성장 10%+, 정배열 눌림목 타점.
    * **배당주(가치):** 시가배당률 3.5%+, 저PER/저PBR, 장기 바닥권 탈피.
        * **낙폭과대(역발상):** 
        * (1차 HTS) 시총 5천억+, 당기순이익 흑자유지, RSI(14) 35 이하 또는 20일 이격도 90% 이하, 5일 이격도 95~105%, 거래대금 30억+.
        * (2차 검증) 하락 진정 변곡점 확인(도지 캔들 또는 거래량 급감), 실시간 뉴스/공시 악재 텍스트 마이닝.
* **AI 리스크 마이닝:** 뉴스/공시에서 횡령, 배임, 감사의견 거절, 임상 실패 등 치명적 악재 키워드 자동 필터링.
* **정밀 변곡점 매수 (Technical Pivot):**
    * **도지(Doji) 판정:** 당일 캔들의 몸통(Open-Close)이 고가-저가 변동폭의 **1.5% 이하**일 때 추세 반전 신호로 간주.
    * **거래량 급감:** 최근 5거래일 평균 거래량의 50% 이하 또는 전일 대비 50% 이하 기록 시 하락 에너지 소멸로 판단.

* **지능형 포트폴리오 관리 (Portfolio Intelligence):**
    * **전략 태깅:** '기대주(TRACK_A)', '배당주(TRACK_B)', '낙폭과대(TRACK_C)'로 출처를 명확히 구분.
    * **상대 강도(RS) 산출:** `(종목 수익률) / (매수 시점 대비 지수 수익률)`을 계산하여 RS > 1.0인 종목은 시장 주도주로 분류하여 손절 라인 완화(-17%).
    * **20일 무반등 교체:** 매수 후 20거래일 경과 시점에 수익률이 3% 미만일 경우 슬랙을 통해 '종목 교체(Opportunity Cost)' 검토 알림 발송.
    * **ETF 보호망:** 레버리지/인버스 등 변동성 ETF의 AI 자동 매수 진입을 원천 차단.
    * **성과 비교:** TRACK별 AI 자동 매수와 유저 수동 매수의 승률/수익률 교차 분석 리포트 생성.

* **기계적 분할 매수 및 High-Pass 룰:** 예산을 10등분하여 5~10일간 분할 매수. 단, 85점 이상 초우량주는 매수 타점을 유연하게 적용.

* **3중 철통 방어막 및 스마트 익절:** 하드스탑(-10%), 지수 연동형 유연 손절, 수익 발생 시 본전 손절 상향 및 고점 대비 추적 익절(Trailing Stop).

* **확증편향 제거 AI 분석:** 상승 시나리오와 동등한 비중의 '반대 근거(Worst Case)' 분석 및 글로벌 벤치마킹을 통한 주도 세력 변화 감지.

* **스마트 스케줄러:** 시황 보고(08:45), 심층 진단(10:00), 정오 긴급 악재 스캔(11:45), 오후 펀더멘털 진단 및 매수 집행(14:30), 매 30분 실시간 방어막 가동.

* **HTS 3-Track 통합 스캔 (!HTS스캔):** 
    * 증권사 HTS 조건식을 통해 추출된 후보군을 파이썬 엔진이 3대 전략(성장/가치/역발상)별로 교차 검증하여 최적의 진입 후보를 선별.
    
* **기술적 정밀 타점 진단 (!타점분석):**
    * 캔들 몸통 비중(1.5% 이하 도지 판정) 및 거래량(5일 평균 대비 50% 이하)을 분석하여 하락 진정 및 반등 변곡점을 수치화하여 제공.

* **Market Chronicles (v3.0, 실연동 완료):**
    * **Cloud-Only 저장:** 로컬 디스크에 시장 지침·크로니클을 저장하지 않고 Google Drive API로만 관리. 실서버(`Quant_Logs`) 연결 검증 완료.
    * **OAuth 인증:** 서비스 계정 storage quota 한계를 극복하기 위해 **OAuth 데스크톱 앱** 방식 채택. headless 서버용 `--no-browser` 인증, refresh token 자동 갱신, Testing 모드 만료 감지·재발급 안내.
    * **T-Day 크로니클:** 코스피/코스닥 $\pm 1.5\%$ 이상 또는 VIX $\ge 25$ 시 장 마감 후 인과 분석 리포트 및 **미래 행동 지침** 자동 작성.
    * **Context Injection:** 매수/매도 AI 판단 직전, 고속 마스터 인덱스에서 유사 상황 **행동 지침 3건**을 검색·주입하여 단기 기억 상실을 보완.
    * **쉬운 언어 출력:** 금융 전문 용어를 배제하고 초보자도 이해 가능한 일상 언어로 리포트·분석 결과 제공.


---

## 2. 프로젝트 구조 및 파일 설명 (v3.1 기준, Market Chronicles + Back-filling 포함)

시스템의 유지보수성과 확장성을 위해 기능을 계층적으로 분리하였습니다. 모든 핵심 소스코드는 `src/` 디렉토리에 위치합니다.

### [파일 구조 및 역할]
*   **`main.py`**: 시스템의 **Entry Point**. 슬랙 봇 실행, 명령어 라우팅, 스케줄러(루틴) 통합 관리.
*   **`src/core/`**: 증권사 API 통신 및 인증 등 시스템의 근간을 담당.
    *   `kis_api.py`: KIS API 호출 및 데이터 파싱 전문.
    *   `token_manager.py`: API 접근 토큰의 생명주기 관리.
    *   `account_info.py`: 실계좌 상세 잔고 및 수익률 조회.
*   **`src/data/`**: 시황 분석에 필요한 외부 데이터의 수집을 담당.
    *   `collector.py`: 매크로 지표(VIX, 금리 등) 수집 (구 macro_collector.py).
    *   `chart.py`: 기술적 분석을 위한 OHLCV 데이터 가공 (구 chart_data.py).
    *   **`src/data/crawler/`**:
        *   `news_crawler.py`: 구글 뉴스 RSS 기반 크롤링.
        *   `theme_crawler.py`: 네이버 테마 및 소속 종목 크롤링.
        *   `research_crawler.py`: 네이버 산업 분석 리포트 크롤링.
*   **`src/strategy/`**: 시스템의 '두뇌' 역할. 수집된 데이터를 바탕으로 투자 판단.
    *   `ai_logic.py`: LLM(Gemini)을 활용한 정성적 분석 및 리포트 생성 (구 ai_strategy.py).
    *   `screener.py`: 100점 만점 펀더멘털 스코어링 및 Two-Track 심사 (구 quant_screener.py).
    *   `finder.py`: 시가총액 기반 대장주 유니iverse 추출 (구 stock_finder.py).
*   **`src/execution/`**: 실제 자산의 운용 및 보호를 담당.
    *   `order.py`: 분할 매수 로직 및 실제 주문 집행 (구 order_manager.py).
    *   `risk_monitor.py`: 3중 철통 방어막(실시간 리스크 감시) 구동 (구 risk_manager.py).
    *   `orchestrator.py`: 스케줄러 루틴(시황·매수·리스크) 통합 제어.
*   **`src/utils/`**: 공통 편의 기능 및 유틸리티.
    *   `logger.py`: 가상 장부(JSON) 기록 및 트레이딩 로그 관리 (구 trade_logger.py). *(v3.0 이전: 프로젝트 루트 로컬 JSON; v3.0 목표: Google Drive API 전면 전환)*
    *   `helpers.py`: 장 개장 시간 체크 등 공통 계산 도구 (구 market_hours.py).
    *   `messenger.py`: 슬랙 메시지 전송 및 이모지 포맷팅 관리 (구 slack_notifier.py).
    *   `slack_interface.py`: 슬랙 명령어 라우팅 및 이벤트 핸들링.
*   **`src/memory/` (v3.0 신설 완료, v3.1 백필 모듈 추가)** — Market Chronicles 전용 레이어:
    *   `drive_client.py`: Google Drive API 인증(OAuth/SA/위임/공유 드라이브 자동 감지), 폴더·파일 CRUD, Pause/Resume 상태 관리, manifest 캐시.
    *   `oauth_token.py`: OAuth 토큰(`drive_oauth_token.json`) 상태 점검·자동 갱신, Testing 모드 만료 감지.
    *   `chronicle_writer.py`: T-Day 트리거 판정, 크로니클 리포트(.md) 작성, 마스터 인덱스 색인 갱신.
    *   `context_retriever.py`: [뉴스 키워드 + 시장 국면] 기반 유사 행동 지침 Top-3 검색 및 AI 프롬프트 주입.
    *   `lifecycle.py`: 임시 기술 데이터 30일 자동 삭제, 연월별 리포트 폴더 분할 관리.
    *   **`backfill.py` (v3.1 신설):** 최근 N일(기본 60일) KOSPI/KOSDAQ/VIX 일봉 스캔, 트리거 충족 '이벤트 데이' 추출, 과거 시점 뉴스 수집 + AI 사후 분석 리포트 생성, 마스터 인덱스 색인. Drive 기반 `backfill_state.json` 진행 상태 보존(중단 후 이어쓰기), 1건당 3초 대기, 실패 일자 자동 스킵+로그.
    *   **`keyphrase_extractor.py` (v3.2 신설):** AI 1차 + 정규식 사전 2차 폴백으로 [주체 + 동사] 결합 핵심 구문 추출. `subject`·`action`(정규형: 매수/매도/상승/하락/긴축/완화 등)·`tone`(positive/negative/neutral) 메타데이터를 함께 산출하여 `chronicle_writer` / `backfill` 양쪽 색인 일관성과 `context_retriever` 의미 매칭 정확도를 동시에 끌어올린다.
*   **`scripts/` (운영용 스크립트)** — Market Chronicles 초기 셋업/운영 도구:
    *   `drive_oauth_setup.py`: OAuth 클라이언트 JSON 유형 검증(`--check-client`), headless 토큰 발급(`--no-browser`).
    *   `drive_oauth_refresh.py`: 토큰 상태 확인 및 access token refresh.
    *   `drive_folder_bootstrap.py`: `Quant_Logs` 하위 `MarketChronicles/` 폴더 구조 자동 생성·검증.
    *   **`backfill_chronicles.py` (v3.1 신설):** 백필 CLI 진입점. `--scan-only`(스캔/보고만), `--run`(즉시 실행), `--lookback N`(소급 일수, 기본 60), `--delay N`(건당 대기 초, 기본 3).
---

## 3. 변경 이력 (Change Log)

* **초기 단계:** KIS API 연동 기반 마련, 슬랙 봇 뼈대 구축, DART API를 활용한 100점 만점 펀더멘털 채점표 및 5일선 눌림목 분할 매수 로직 구현.
* **v1.1 업데이트:** VIX(공포지수) 데이터 수집 누락 해결. AI 키워드 반환 시 언패킹(Unpacking) 에러 방지를 위한 쉼표 분리 예외 처리 적용.
* **v1.2 업데이트:** `!수동등록` 명령어 사용 시 발생하는 KIS API 실계좌 보유 수량 조회 에러 해결 (`get_real_holding_qty` 복구). AI 리포트 200자 제한 및 전 구간 이모지 사용 전면 금지 규칙 적용.
* **v1.3 업데이트:** 추적 익절 기준을 -5%로 좁혔다가 잦은 청산 리스크를 고려하여 절대 원칙인 **-10%**로 최종 원복. 토큰 발급 로직을 휴일 무조건 차단에서 24시간 캐시 기반 온디맨드 발급으로 유연화.
* **v1.4 업데이트:** 10:00 심층 시황 리포트에서 AI가 실시간 데이터를 분석하지 못하던 버그 수정 (데이터 바인딩 누락 해결) 및 전반적인 시장 흐름 파악 섹션 추가.
* **v1.5 업데이트 (타협안 및 최적화 일괄 적용):**
    * **금융주 Two-Track 분리:** 금융주 판별 시 ROE 8%, PBR 1.0 이하 기준 적용 및 80점 커트라인 상향. AI 프롬프트에 주주환원 지속성 확인 강제.
    * **High-Pass 룰:** 채점 85점 이상 초우량주는 5일선 + 5%까지 매수 타점 완화.
    * **2단계 매크로 셧다운:** VIX 25~30 등 노란불 구간에서 신규 매수 예산 50% 축소 로직 신설.
    * **정오의 보초:** 11:45 자동 매수 직전 AI를 통한 보유 종목 돌발 악재 긴급 뉴스 스캔 절차 추가.
* **v1.6 업데이트 (프롬프트 고도화 및 방어막 완성):**
    * **행동 지침 강화:** 일일 시황 및 종목 리포트 AI 프롬프트에 구체적인 투자 의견(5단계: 매수적극찬성~매수적극반대)과 행동 근거(원리 설명)를 명시하도록 업데이트.
    * **3중 철통 방어막 구축:** 실시간 리스크 매니저(하드스탑/추적매도 -10%)와 오후 14:30 AI 펀더멘털 진단을 결합하여 원금 보호 시스템 체계화.
    * **AI 전용 규칙 강화:** 모바일 가독성을 위한 200자 제한 및 개조식 출력 규칙을 모든 전략 모듈(`ai_strategy.py`)에 전역 적용.
*   **v1.7 업데이트 (구조적 리팩토링):**
    *   단일 디렉토리에 산재해 있던 모듈들을 `src/` 하위의 5개 핵심 레이어(`core`, `data`, `strategy`, `execution`, `utils`)로 재배치.
    *   `main.py`에서 비즈니스 로직을 분리하여 각 모듈의 응집도를 높이고 결합도를 낮춤.
    *   파일 구조 명세 표준화 및 모듈 간 참조 관계 정립.
*  **v1.8 업데이트 (Main 모듈 경량화):**
    *   `main.py`에 집중된 비즈니스 로직을 `orchestrator`(루틴 제어), `slack_interface`(이벤트 핸들링), `stock_info_crawler`(데이터 수집)로 분리 완료.
    *   스케줄러와 슬랙 핸들러 간의 역할 분담을 통해 유지보수성 극대화.
*  **v1.9 업데이트 (코딩 규정 통합 및 KIS 가치지표 API 연동):**
    *   `.continue/rules/autostock.md`의 코딩 규정을 시스템 명세서에 통합.
    *   DART API 의존도를 낮추고 정확한 재무 데이터를 위해 KIS 가치지표 API(`FHKST03010300`) 연동 작업 완료.
*  **v2.0 업데이트:** 11:45 정오 루틴에 당일 주도주 실시간 스캔 및 자동 매수 로직 추가, 슬랙 핸들러 정규식 최적화.
*  **v2.1 업데이트:** `OpenDartReader` 제거, KIS 성장성지표 API(`FHKST03010400`)로 매출/영업이익 증가율 수집 일원화.
*  **v2.2 업데이트:** 멀티 에이전트 도입 및 6단계 심층 분석 리포트 체계 구축.
*  **v2.3 업데이트:** RSI 과매도·도지·거래량 급감 기반 역발상 전략 정교화 및 `!역발상` 명령어 연동.
*  **v2.4 업데이트 (전략 정교화 및 리스크 관리 고도화):**
    *   **저평가 공식 명문화:** PBR-ROE 관계식을 이용한 가치 평가 가산점 로직 및 배당 성향(30~40%) 검토 조건 추가.
    *   **지수 연동형 손절:** 시장 지수 대비 강세 종목에 대해 손절 라인을 최대 -17%까지 하향 조정하여 노이즈 차단.
    *   **8주 타임아웃:** 매수 후 40거래일간 무반등 시 기회비용 보호를 위한 자동 매도 룰 신설.
    *   **AI 비판적 분석:** 리포트에 반대 논리(Counter-argument) 비중을 대폭 강화하여 확증편향 방지 및 글로벌 벤치마킹 분석 추가.
*  **v2.5 업데이트 (HTS 3-Track 및 정밀 타점 로직):**
    *   **전략 다각화:** '기대주(성장)', '배당주(가치)', '낙폭과대(역발상)' 3대 트랙별 맞춤형 재무/수급/기술적 지표 적용.
    *   **치명적 리스크 필터:** AI 텍스트 마이닝을 통해 상장폐지 사유, 횡령, 임상 실패 등 뉴스/공시의 정성적 악재를 선제적으로 배제.
    *   **변곡점 타점 정밀화:** RSI 과매도 구간에서 도지(Doji) 캔들 혹은 거래량 급감 패턴 확인 시 매수 집행하여 하락 진정 확인 후 진입.
    *   **운용 효율화:** 종목 성격에 따른 5~10일 유연 분할 매수 및 수익 보존을 위한 트레일링 스탑 로직 고도화.
*  **v2.6 업데이트:** HTS 1차 필터(시총·재무·과매도)와 파이썬 2차 검증(도지/거래량·뉴스 마이닝) 역할 분리, 낙폭과대 트랙 리스크 관리 고도화.
*  **v2.7 업데이트:** TRACK_A/B/C 태깅, RS 기반 유연 손절(-17%), 20일 무반등 교체 알림, Manual vs AI 성과 비교.
*  **v2.8 업데이트:** 슬랙 핸들러 중첩 오류 수정, 매크로 셧다운 임계치 구체화, ETF 필터링, 지수 연동형 RS 계산 정밀화.
*  **v2.9 업데이트:** `!HTS스캔`(3-Track 동시 검증), `!타점분석`(도지/거래량 변곡점) 인터페이스 구축.
*  **v3.0 업데이트 (Market Chronicles — Drive 실연동 완료, 구현율 85%):**
    *   **목적:** Gemini API의 호출 단위 맥락 초기화 한계를 극복하는 **Google Drive 전용 외장 메모리** 아키텍처 확정 및 실서버 연결.
    *   **Cloud-Only:** 로컬 저장소 미사용, 모든 크로니클·인덱스·임시 데이터를 Drive API로만 관리.
    *   **인증 체계 확립:** 서비스 계정 storage quota 403 한계 발견 → **OAuth 데스크톱 앱** 방식으로 전환. 인증 모드(`oauth` / `delegation` / `shared_drive` / `sa_plain`) 자동 감지.
    *   **Headless OAuth:** 서버(Ubuntu SSH, 브라우저 없음)에서 `--no-browser` 콘솔 인증으로 토큰 발급. JSON 유형(데스크톱 앱 vs 웹 앱) 사전 검증.
    *   **자동 토큰 갱신:** `oauth_token.py`가 access token 만료 시 refresh, Testing 모드 만료(`invalid_grant`) 감지 및 재발급 안내. 봇 기동 시 자동 점검.
    *   **폴더 구조 자동 생성:** `Quant_Logs/MarketChronicles/{index, reports/YYYY/MM, temp/tech, _system}`, `app_data/` 자동 생성. `master_index.json` 초기화 완료.
    *   **Pause/Resume:** 폴더 생성·OAuth 승인·용량 부족 등 사용자 개입 필요 시 로컬 플래그(`.drive_pause_local.json`)로 일시 정지 후 슬랙 안내 및 "완료" 응답 시 재검증·재개. Drive 재호출 무한 재귀 방지 로직 적용.
    *   **T-Day 크로니클:** 코스피/코스닥 $\pm 1.5\%$ 또는 VIX $\ge 25$ 시 장 마감 후 인과 분석·**미래 행동 지침** 도출 및 인덱스 색인.
    *   **Context Injection:** AI 매매 판단 직전 유사 행동 지침 Top-3를 [필수 준수 배경 지식]으로 프롬프트 강제 주입 (`ai_logic.generate_text_with_chronicle`).
    *   **출력 원칙:** 금융 전문 용어 배제, 초보자용 일상 언어 리포트.
    *   **구현 모듈:** `src/memory/{drive_client, oauth_token, chronicle_writer, context_retriever, lifecycle}.py`; `scripts/{drive_oauth_setup, drive_oauth_refresh, drive_folder_bootstrap}.py`; 스케줄 15:35; 슬랙 `!크로니클`, `완료`.
    *   **미완:** 실제 T-Day 크로니클 작성 검증(트리거 충족 일자 대기), 키워드 검색 고도화(임베딩), `temp/tech` 자동 업로드 파이프라인.
*  **v3.1 업데이트 (Market Chronicles 과거 데이터 소급 구축 — 실전 검증 완료, 구현율 98%):**
    *   **목적:** 가동 즉시 AI 판단에 주입 가능한 **'과거 대응 지침 DB'** 확보. T-Day 트리거 발생만을 기다리지 않고, 최근 60일치 변동성 장세를 사전 분석하여 마스터 인덱스를 두텁게 만든다.
    *   **이벤트 데이 추출:** `yfinance`로 ^KS11/^KQ11/^VIX 일봉을 받아 등락률 $\pm 1.5\%$ 이상 또는 VIX $\ge 25$ 인 거래일을 식별.
    *   **2단계 동의 흐름:** ① `!백필스캔`(또는 `scripts/backfill_chronicles.py --scan-only`)로 후보 N건을 슬랙에 보고하고 대기. ② 사용자가 `확인` 또는 `!백필실행`을 입력하면 ③ 과거 시점 뉴스 수집·AI 사후 분석·리포트 저장·인덱스 색인 일괄 실행.
    *   **사후 통찰 프롬프트:** 과거 데이터 분석 시 '당시에는 몰랐지만 지금은 알게 된 사실'을 포함하도록 프롬프트를 보강해 더욱 정교한 행동 지침 도출.
    *   **API Rate Limit 보호:** 리포트 1건 생성마다 기본 3초 대기(설정 가능).
    *   **상태 보존(중단 대비):** 진행 상황을 Drive `MarketChronicles/_system/backfill_state.json`에 기록(processed/skipped/queue). 중단되어도 다음 실행 시 미처리 일자만 이어서 처리.
    *   **예외 처리:** 한 일자 처리 중 오류 발생 시 해당 날짜를 `skipped`로 기록하고 다음 날짜로 진행. 이미 같은 날짜의 크로니클이 존재하면 자동 스킵.
    *   **구현 모듈:** `src/memory/backfill.py`, `scripts/backfill_chronicles.py`, 슬랙 `!백필스캔`/`!백필실행`/`확인`, `MarketOrchestrator.backfill_scan`/`backfill_run`.
    *   **운영 검증(2026-05-20, terminal 수동 실행):** lookback=60, delay=3s, 결과 **완료 32 / 스킵 0 / 실패 0**. `master_index.json` 누적 엔트리 +32(`source="backfill"`). 향후 모든 AI 매매·시황 판단에 Context Injection 즉시 가동.
*  **v3.2 업데이트 (Semantic Keyphrase Indexing & Retrieval — 적용 완료, 구현율 92%):**
    *   **문제:** 기존 `keywords` 는 정규식 `[가-힣]{2,}` 단순 추출이라 "외국인 매수" vs "외국인 매도", "금리 인상" vs "금리 인하" 같은 정반대 의미를 같다고 점수화하는 문맥 왜곡 위험.
    *   **인덱싱 개선:** `chronicle_writer._build_keyphrases` / `backfill._build_keyphrases` 가 Gemini로 [주체+동사] 결합 구문(`subject`/`action`/`tone` 포함)을 1차 추출, 실패 시 `keyphrase_extractor._regex_extract` 가 사전 기반 폴백.
    *   **검색 개선:** `context_retriever._score_entry` 가 ① 구문 자카드(±subject/action) ② tone 다수결 일치 ③ regime 그룹 일치 ④ 최근성(30/90/180일) 의 5단계 가중치 합으로 점수화. 단어 토큰 매칭은 `min_score` 미달일 때만 폴백.
    *   **결과 노출:** `build_context_injection_block` 의 컨텍스트 블록에 매칭 점수와 핵심 구문 목록을 함께 표기하여 AI 가 어떤 과거 사례를 왜 참고하는지 명확히 인지.
    *   **호환:** 신규 엔트리는 `keyphrases` 와 `keywords` 둘 다 저장. 기존 v3.0/v3.1 엔트리(keywords 만 있음)는 폴백 경로로 그대로 검색됨 → 무중단 업그레이드.
    *   **신규 모듈:** `src/memory/keyphrase_extractor.py`.
    *   **변경 파일:** `src/memory/chronicle_writer.py`, `src/memory/backfill.py`, `src/memory/context_retriever.py`, `src/strategy/ai_logic.py`.
*  **v3.2.1 업데이트 (Backfill 초기화·재인덱싱 운영 도구 — 적용 완료, 구현율 95%):**
    *   **배경:** v3.1 에서 이미 32건의 백필이 적재된 상태로 v3.2 의미 색인이 도입되었기 때문에, 기존 엔트리를 v3.2 포맷으로 안전하게 마이그레이션하거나 통째로 재구축할 운영 절차가 필요.
    *   **`reset_backfill(delete_reports=False)`:** `master_index.json` 에서 `source="backfill"` 엔트리만 골라 제거하고 `backfill_state.json` 을 빈 상태로 덮어쓴다. `delete_reports=True` 이면 해당 엔트리들의 `.md` 리포트 파일까지 Drive 에서 삭제.
    *   **`reindex_keyphrases(delay_sec=3)`:** 기존 `.md` 리포트를 읽어 `keyphrase_extractor.extract_keyphrases` 로 새 구문을 추출하고, 엔트리에 `keyphrases` + 파생 `keywords` + `reindexed_at` 을 채워넣는다. `.md` 보존 + AI 1회 호출만으로 v3.2 의미 색인 풀 적용.
    *   **안전장치:** T-Day 자동 작성 엔트리(`source != "backfill"`)는 두 함수 모두 절대 건드리지 않는다.
    *   **인터페이스:**
        - CLI: `python scripts/backfill_chronicles.py --reset [--purge-reports] [--run]` / `--reindex --delay N`
        - 슬랙: `!백필초기화 [purge]` / `!백필재인덱싱 [건당대기초]`
        - Orchestrator: `MarketOrchestrator.backfill_reset(delete_reports=False)` / `backfill_reindex(delay_sec=3)`
    *   **변경 파일:** `src/memory/backfill.py`, `scripts/backfill_chronicles.py`, `src/utils/slack_interface.py`, `src/execution/orchestrator.py`.
*  **v3.2.3 업데이트 (Backfill 운영 핫픽스 + 잔여 정리·진단 명령 — 적용 완료, 구현율 97%):**
    *   **운영 보고된 버그(2026-05-20):** `--reset --purge-reports` 실행 중 `HttpError 404 File not found: {'mimeType': ..., 'id': ..., 'name': ...}` 발생. 원인은 `drive_client._find_file_in_parent` 가 file ID **문자열** 이 아닌 메타데이터 **dict 전체** 를 반환하는데, `backfill._delete_file_at_rel_path` 가 그 dict 를 그대로 `delete_file_by_id` 에 전달하여 요청 URL 이 깨진 것.
    *   **수정:** `_delete_file_at_rel_path` 가 반환값을 dict 로 인지하여 `.get("id")` 만 추출하도록 정정. 404/notFound 응답은 "이미 삭제됨"으로 간주하여 idempotent 동작.
    *   **신규 `purge_leftover_backfill_reports(dry_run=False)` (이전 명칭: `purge_orphan_backfill_reports`):** 위 버그로 인덱스는 비워졌지만 `.md` 파일이 남아 있는 잔여(leftover) 상태를 정리하기 위한 보조 명령. `MarketChronicles/reports/` 트리를 재귀 스캔하여 헤더 첫 줄에 `Market Chronicle (Backfill)` 표식이 있는 `.md` 만 식별하고, master_index 의 어떤 엔트리에도 등록되지 않은 항목만 실제 삭제. T-Day 자동 리포트(헤더 `# Market Chronicle YYYY-MM-DD`)는 표식 불일치로 자동 보호.
    *   **신규 `diagnose_reports()` (읽기 전용 진단):** "잔여 정리 명령이 왜 0건만 보고하나" 류의 운영 의문을 즉답한다. reports 트리의 .md 총 갯수 / 인덱스 등록·미등록 분포 / 헤더 표식별 분포(백필 vs T-Day) / 잔여 정리 대상 갯수 / master_index 의 백필·T-Day 분포를 한 번에 출력. 파일을 절대 수정·삭제하지 않는다.
    *   **명칭 정정:** 사용자 피드백에 따라 "고아(orphan)" 표현을 **"잔여(leftover)"** 로 변경. 기존 명칭은 deprecated alias 로 호환 유지(`purge_orphan_backfill_reports` 함수, `--purge-orphan-reports` 플래그, `!백필고아청소` 슬랙 명령, `backfill_purge_orphans()` 오케스트레이터 메서드 모두 새 명칭과 동일 동작).
    *   **인터페이스:**
        - CLI: `python scripts/backfill_chronicles.py --diagnose-reports` (진단) / `--purge-leftover-reports [--dry-run]` (정리)
        - 슬랙: `!백필상태` (진단) / `!백필잔여정리 [dry]` (정리)
        - Orchestrator: `MarketOrchestrator.backfill_diagnose()` / `backfill_purge_leftover(dry_run=False)`
    *   **변경 파일:** `src/memory/backfill.py`, `scripts/backfill_chronicles.py`, `src/utils/slack_interface.py`, `src/execution/orchestrator.py`.

---

## 4. v3.0 Market Chronicles (지능형 메모리 아키텍처)

본 섹션은 v3.0 지능형 메모리 아키텍처를 기반으로, 호출 시마다 맥락이 초기화되는 인공지능(Gemini API)의 기술적 한계를 극복하기 위해 작성되었다. 당일 시장의 **인과 관계**를 분석하여 **행동 지침(가이드라인)** 을 축적하고, 향후 유사 국면 발생 시 이를 주입하여 인공지능의 판단을 실질적으로 교정하는 **외장형 메모리 시스템** 구축을 목표로 한다.

### 4.1 시스템 핵심 아키텍처 (Cloud-Only & Interaction)

모든 데이터와 로그는 **로컬 저장소를 사용하지 않으며**, 오직 **Google Drive API**로 관리한다.

#### 4.1.1 파일 구조 설계 가이드라인 (Code Agent 위임)

구체적인 폴더 경로와 파일명은 Code Agent가 현재 Google Drive의 실제 사용 현황을 파악한 뒤 최종 설계하도록 위임한다. 단, 안정적인 지침 축적과 고속 사례 검색을 위해 설계 시 다음 **최소 가이드라인**을 반드시 준수해야 한다.

| 구분 | 요구 사항 |
|------|-----------|
| **용도별 분리** | 고속 검색용 **마스터 인덱스** 파일, 날짜별 **시황/행동 지침 리포트(.md)**, **임시 기술 데이터** 영역이 논리적으로 분리 |
| **누적 부하 방지** | 날짜별 리포트는 단일 폴더 내 파일 누적으로 인한 Drive 검색 속도 저하를 막기 위해 **연월 단위** 등으로 분할 관리 |
| **영구 보존 vs 자동 삭제** | 축적된 **시장 지침 인덱스**는 영구 보존; **대용량 기술 데이터**는 **30일 후** 자동 삭제 영역에 두어 Drive 용량 관리 |

**권장 논리 구조 (최종 경로는 구현 시 Drive 실사 후 확정):**

```
[Drive Root]/MarketChronicles/
  index/
    master_index.json          # [상황 키워드 + 행동 지침 요약] 색인 (영구)
  reports/
    YYYY/
      MM/
        YYYY-MM-DD_chronicle.md  # T-Day 상세 리포트 (영구)
  temp/
    tech/                      # OHLCV·원시 뉴스 등 대용량 임시 데이터 (30일 TTL)
  _system/
    pause_state.json           # Pause/Resume 및 OAuth·용량 이슈 상태
```

#### 4.1.2 사용자 개입 및 대기 프로세스 (Pause / Resume)

시스템 제어 중 사용자의 직접적인 조작(최초 폴더 생성, Google 권한 승인, Drive 용량 부족 등)이 필요한 예외 상황이 발생하면, 시스템은 독단적으로 작업을 진행하거나 에러를 내지 않고 **대기 상태(Pause)** 로 전환한다.

1. **상황 보고:** 예외 발생 시 필요 조치 사항을 건조하고 명확한 텍스트로 슬랙(또는 콘솔)에 안내한다.
2. **작업 대기:** 사용자가 조작을 완료하고 확인 답변을 줄 때까지 프로세스를 일시 정지한다.
3. **검증 및 재개:** 사용자가 `"완료"` 등의 응답을 하면 Google Drive 상태를 재검사한 후 안전하게 다음 작업을 수행한다.

### 4.2 분석 로직: 인과 관계 분석 및 행동 지침 도출

매일 장이 끝나면 당일 발생한 뉴스 등의 정보를 수집하여 시장의 움직임을 해부하고, 미래를 위한 **오답 노트**를 작성한다.

#### 4.2.1 크로니클 리포트 작성 (T-Day, 장 마감 후)

| 항목 | 내용 |
|------|------|
| **기록 트리거** | 코스피/코스닥 지수 변동률 **$\pm 1.5\%$ 이상** 또는 **VIX $\ge 25$** 발생 시 **무조건** 실행 |
| **Intraday Flow** | 아침–점심–장마감의 지수 경로 및 시장 참여자 심리 변화 추이 |
| **사건과 원인 분석** | 당일 핵심 뉴스·지표 발표와 시장 실제 반응의 연계 분석 |
| **미래 행동 지침 (핵심)** | "오늘 장은 A 뉴스 때문에 B처럼 움직였다. 향후 유사 뉴스·국면이 재발하면 C 포지션/대응을 취한다"는 **기계적 대응 룰**을 명문화 |
| **저장** | Code Agent가 확정한 리포트 경로에 `.md` 저장 후, `master_index.json`에 **[상황 키워드 + 행동 지침 요약]** 색인 추가 |

### 4.3 인공지능(AI) 적용 및 실질적 교정 방안

Gemini API는 매 호출마다 과거를 망각하므로, Google Drive에 저장된 행동 지침을 실시간으로 주입하여 인공지능의 판단을 **물리적으로 교정**한다.

#### 4.3.1 유사 상황 검색 및 외장 메모리 주입 (Context Injection)

```
[매수/매도 판단 요청]
        |
        v
[현재 뉴스 키워드 + 시장 국면 추출]
        |
        v
[master_index.json 고속 검색 -> 유사 행동 지침 Top-3]
        |
        v
[해당 .md 리포트 Drive에서 즉시 로드]
        |
        v
[Gemini API: 프롬프트 [필수 준수 배경 지식] 블록에 과거 지침 주입]
        |
        v
[일관된 매매/시황 판단 출력]
```

1. **매수/매도 판단 시점:** AI에게 현재 시장 대응·종목 매매 판단을 요청하기 **직전**, [뉴스 키워드 + 시장 국면]을 추출한다.
2. **행동 지침 검색:** 추출 키워드로 마스터 인덱스를 검색하여, 과거 **가장 유사한 상황의 행동 지침 리포트 3개**를 Drive에서 즉시 호출한다.
3. **실질적 AI 교정:** 호출된 과거 행동 지침을 현재 매매 요청 프롬프트의 **[필수 준수 배경 지식]** 으로 묶어 API에 전송한다. 단기 기억 상실이 있어도 과거 기록을 읽고 **일관된 결론**을 내리도록 한다.

**프롬프트 주입 템플릿 (개념):**

```text
[필수 준수 배경 지식 - Market Chronicles]
아래는 과거 유사 시장 국면에서 시스템이 확정한 행동 지침이다. 현재 판단 시 반드시 참고하라.
--- 지침 1 (YYYY-MM-DD): {요약} ---
{상세 발췌}
--- 지침 2 ...
--- 지침 3 ...
[현재 판단 요청]
{기존 매매/시황 프롬프트}
```

#### 4.3.2 출력 및 인터페이스 원칙

* **쉬운 언어 사용:** 금융 전문 용어를 최대한 배제하고, 주식 초보자도 단번에 이해할 수 있는 **일상 언어**로 모든 리포트·분석 결과를 출력한다.
* **슬랙 연동:** Pause 상태 안내·크로니클 작성 완료 알림은 기존 `messenger.py` 경로를 사용한다.

### 4.4 v2.x 대비 구현 갭 (현재 코드베이스)

| 항목 | v2.x 현황 | v3.0 목표 |
|------|-----------|-----------|
| 저장소 | `logger.py`의 `load/save_json_from_gdrive`가 **프로젝트 루트 로컬 JSON** 사용 | **실제 Google Drive API** 전면 전환 |
| 시장 기억 | 없음 (매 호출 독립) | T-Day 크로니클 + 마스터 인덱스 |
| AI 판단 | `ai_logic.py` 단발 프롬프트 | Context Injection Top-3 주입 |

### 4.5 v3.0 구현 체크리스트

| 단계 | 상태 | 비고 |
|------|------|------|
| 1. `drive_client.py` (Pause/Resume) | 완료 | OAuth/SA/위임/공유 드라이브 자동 감지 |
| 2. Drive 폴더·`master_index.json` | **실연동 완료** | `Quant_Logs/MarketChronicles/` 실제 생성 |
| 3. `chronicle_writer.py` | 완료 | T-Day 트리거, AI 리포트 |
| 4. `context_retriever.py` + `ai_logic` | 완료 | Top-3 유사 지침 검색·프롬프트 주입 (※ v3.2 에서 구문 단위 의미 매칭으로 고도화, §6 참조) |
| 5. `lifecycle.py` TTL | 완료 | 15:35 루틴에 포함 |
| 6. `orchestrator` 15:35 스케줄 | 완료 | |
| 7. `logger.py` Drive 연동 | 완료 | 미설정 시 로컬 폴백 |
| 8. OAuth 인증 체계 | **실연동 완료** | headless `--no-browser`, 자동 토큰 갱신 |
| 9. 셋업 스크립트 | 완료 | `scripts/drive_*` 3종 |
| 10. T-Day 크로니클 실전 검증 | 대기 | 트리거(±1.5% / VIX≥25) 충족 시 |
| 11. 색인·검색 의미 매칭 강화 | **v3.2 적용 완료** | 구문(keyphrases) 단위 인덱싱·검색 가중치 (§6) |
| 12. 임베딩 RAG / temp 자동 업로드 | 미완 | v3.3 후보 (§7 향후 추진 과제 4번 참고) |

---

## 5. v3.1 과거 데이터 소급 구축 (Back-filling)

본 섹션은 v3.0의 **외장 메모리(Market Chronicles)** 가 가동 첫날부터 비어 있지 않도록, **최근 2개월(기본 60일) 변동성 장세를 사후 분석**하여 마스터 인덱스를 선제 구축하는 절차를 정의한다. v3.0 § 4의 T-Day 실시간 작성 로직과 동일한 산출물 규격(.md 리포트 + `master_index.json` 색인)을 사용한다.

### 5.1 목적 및 트리거

| 항목 | 내용 |
|------|------|
| **목적** | 봇 첫 가동 시 곧바로 Context Injection이 가능하도록 과거 사례 DB를 확보 |
| **소급 기간** | 기본 **60일**(약 2개월), CLI/슬랙에서 조정 가능 |
| **이벤트 데이 조건** | 코스피(`^KS11`) 또는 코스닥(`^KQ11`) 일간 등락률 **$\pm 1.5\%$ 이상** **또는** VIX(`^VIX`) 종가 **$\ge 25$** |
| **데이터 소스** | `yfinance` 일봉(`history(period="3mo")`) — 한국 거래소 영업일 기준 자동 정렬 |
| **출력 규격** | `.md` 리포트(연/월 폴더 분할) + `master_index.json` 엔트리(키워드/요약/regime/trigger/`source: backfill`) |

### 5.2 처리 단계 (Scan → Confirm → Backfill → Index)

```
[1단계 Scan]
  yfinance 일봉 -> 트리거 충족 일자 리스트 + (지수변동·VIX) 요약 -> 슬랙 보고
  Drive: MarketChronicles/_system/backfill_state.json 초기화(queue 등록)
                |
                v (사용자가 '확인' 또는 '!백필실행' 입력)
[2단계 Backfill 1건씩]
  for 날짜 in queue:
    - 이미 reports/YYYY/MM/YYYY-MM-DD_chronicle.md 존재? -> 스킵
    - 뉴스 키워드 수집(news_crawler) + 당시 매크로 추정치 합성
    - AI 프롬프트(사후 통찰 포함) -> [장중 흐름 / 사건 원인 / 미래 행동 지침]
    - Drive에 .md 저장 + master_index.json 색인 추가(source="backfill")
    - 3초 대기 (Rate Limit 보호)
                |
                v
[3단계 결과 보고]
  슬랙: 완료 N건 / 스킵 M건 / 실패 K건 + 평균 소요시간
```

**프롬프트 보강(사후 통찰):** 백필 리포트는 *"오늘 시점에서 돌이켜 보면 그 사건의 원인·여파가 어떻게 전개됐는지"* 를 포함하도록 지시하여, 단순 사후 요약이 아닌 **현재 시점의 학습 가능한 행동 지침**으로 가공한다.

### 5.3 진행 상태 보존 및 예외 처리

| 메커니즘 | 위치 | 동작 |
|----------|------|------|
| **상태 파일** | Drive `MarketChronicles/_system/backfill_state.json` | `{lookback_days, scanned_at, queue[], processed[], skipped[], updated_at}` |
| **중복 방지** | 작업 전 `reports/YYYY/MM/YYYY-MM-DD_chronicle.md` 존재 여부 사전 검사 | 존재 시 `skipped(reason=exists)`로 기록 후 다음 |
| **건당 대기** | `time.sleep(delay_sec)` (기본 3초) | API 호출량 제어 |
| **에러 격리** | `try/except`로 1일자 처리 단위 보호 | 실패 시 `skipped(reason=error:<msg>)` 기록 후 다음 |
| **이어쓰기** | 재실행 시 `queue` 중 `processed`/`skipped`가 아닌 항목만 처리 | 중단/재개 안전 |
| **Drive Pause** | 작업 중 `DrivePausedError` 발생 시 즉시 중단 + 슬랙 안내 | 사용자 `완료` 응답 후 재실행 가능 |

### 5.4 사용 인터페이스 (Slack / CLI / Orchestrator)

| 채널 | 입력 | 동작 |
|------|------|------|
| Slack | `!백필스캔` 또는 `!백필스캔 60` | 최근 N일 스캔 후 후보 리스트 보고, `backfill_state.json`에 queue 저장, 대기 안내 |
| Slack | `확인` | 직전 스캔에 대해 `run_backfill` 실행 (단, `완료`는 Drive Pause 해제 전용으로 분리 유지) |
| Slack | `!백필실행` | 저장된 queue에 대해 즉시 `run_backfill` 실행 |
| Slack | `!백필초기화 [purge]` | 기존 백필 엔트리·state 초기화 (`purge` 입력 시 `.md` 까지 삭제) |
| Slack | `!백필재인덱싱 [건당대기초]` | `.md` 보존, `keyphrases` 만 v3.2 포맷으로 재추출 |
| Slack | `!백필상태` | reports 트리와 master_index 정합 상태 진단 (읽기 전용) |
| Slack | `!백필잔여정리 [dry]` | master_index 외부의 백필 `.md` 잔여 정리 (`dry` 입력 시 미실행 보고) |
| CLI | `python scripts/backfill_chronicles.py --scan-only --lookback 60` | 스캔만 수행하고 콘솔/Drive에 저장 |
| CLI | `python scripts/backfill_chronicles.py --run --delay 3` | 저장된 queue를 1건씩 실행 |
| CLI | `python scripts/backfill_chronicles.py --lookback 60 --run` | 스캔 후 즉시 실행 |
| CLI | `python scripts/backfill_chronicles.py --reset [--purge-reports]` | 기존 백필 결과 초기화 |
| CLI | `python scripts/backfill_chronicles.py --reset --purge-reports --run` | 완전 재구축 |
| CLI | `python scripts/backfill_chronicles.py --reindex --delay 3` | `.md` 보존, keyphrases만 v3.2 재추출 |
| CLI | `python scripts/backfill_chronicles.py --diagnose-reports` | reports 트리/master_index 정합 진단 (읽기 전용) |
| CLI | `python scripts/backfill_chronicles.py --purge-leftover-reports [--dry-run]` | reports 트리의 잔여 백필 `.md` 정리 |
| Orchestrator | `MarketOrchestrator.backfill_scan()` / `backfill_run()` / `backfill_reset()` / `backfill_reindex()` / `backfill_diagnose()` / `backfill_purge_leftover()` | 슬랙·스케줄 통합 진입점 |

### 5.5 v3.1 구현 체크리스트

| 단계 | 상태 | 비고 |
|------|------|------|
| 1. `src/memory/backfill.py` (스캔/리포트/인덱싱/상태보존) | **완료** | yfinance 기반 이벤트 데이 추출, 3초 대기, 스킵 로그 |
| 2. `scripts/backfill_chronicles.py` CLI | **완료** | `--scan-only` / `--run` / `--lookback` / `--delay` |
| 3. 슬랙 `!백필스캔` / `!백필실행` / `확인` 처리 | **완료** | `slack_interface.py` 핸들러 추가 |
| 4. `MarketOrchestrator.backfill_scan` / `backfill_run` | **완료** | 슬랙 통합 진입점 |
| 5. 사후 통찰 프롬프트(과거 분석 강화) | **완료** | "현재 시점에서 돌이켜 본 교훈" 포함 |
| 6. Drive `backfill_state.json` 상태 저장·이어쓰기 | **완료** | 중단 후 재개 안전 |
| 7. T-Day 본 크로니클과 동일 색인 규격(`master_index.json`) | **완료** | `source="backfill"` 표식만 추가 |
| 8. **실전 운영 검증** | **완료 (2026-05-20)** | lookback 60일, **완료 32 / 스킵 0 / 실패 0** (terminal 수동 실행) |
| 9. **백필 초기화·재인덱싱 운영 도구** | **v3.2.1 완료** | `--reset` / `--reindex` / 슬랙 명령 (§5.6) |
| 10. 임베딩 기반 유사도 검색·실시간 매크로 스냅샷 통합 | 미완 | v3.x 향후 고도화 (§7 향후 추진 과제 4번 참고) |

### 5.6 v3.2.1 초기화·재인덱싱 운영 도구

v3.1 에서 이미 적재된 32건의 백필 엔트리를 v3.2 의미 색인으로 마이그레이션하거나 통째로 재구축할 수 있도록 두 가지 모드를 제공한다.

| 모드 | 시나리오 | AI 호출 | `.md` 리포트 | `master_index` | 추천 |
|---|---|---|---|---|---|
| **`reset_backfill(delete_reports=False)`** | 엔트리만 비우고 다시 채움 | 재실행 시 N회(전체) | 보존 | `source="backfill"` 엔트리 제거 | 빠른 재구축 |
| **`reset_backfill(delete_reports=True)`** | 처음부터 완전 재구축 | 재실행 시 N회(전체) | **삭제** | 엔트리 + 파일 모두 제거 | 깨끗한 재시작 |
| **`reindex_keyphrases()`** | `.md` 살리고 `keyphrases` 만 새로 추출 | **N회(구문 추출만)** | 보존 | 엔트리에 `keyphrases`/`reindexed_at` 추가 | **권장 (비용 최소)** |

권장 마이그레이션 절차 (v3.1 → v3.2 전환):

```bash
# .md 와 인덱스를 모두 살리면서 v3.2 keyphrases 만 채워 넣는다 (32회 AI 호출, 약 100초)
python scripts/backfill_chronicles.py --reindex --delay 3
```

전체 재구축이 필요한 경우:

```bash
# 완전 초기화 후 새로 스캔/실행 (백필 1회당 AI 2~3회 호출 + 3초 대기)
python scripts/backfill_chronicles.py --reset --purge-reports --lookback 60 --run --delay 3
```

**잔여 정리(leftover purge) 의 정의와 사용 흐름**

`--reset` 도중 일부 `.md` 가 정상 삭제되지 못해 master_index 외부에 남은 상태를 **잔여(leftover)** 로 정의한다. 무엇이 잔여이고 무엇이 정상인지는 진단 명령으로 먼저 확인한다.

```bash
# 1) 현재 상태 진단 (읽기 전용)
python scripts/backfill_chronicles.py --diagnose-reports
```

진단 출력은 다음 6개 수치를 한 번에 보고한다.

| 항목 | 의미 |
|---|---|
| `reports/*.md` 총 N건 | 트리 전체의 `.md` 갯수 |
| 인덱스 등록 / 미등록 | `master_index.json` 의 `report_rel_path` 와 일치 여부별 분포 |
| 백필 헤더 표식 / T-Day 헤더 표식 | 헤더 첫 200자의 `Market Chronicle (Backfill)` / `Market Chronicle ` 매칭 별 분포 |
| master_index 엔트리 (백필 / T-Day) | `source` 필드 기준 분포 |
| **잔여 정리 대상** | "인덱스 미등록 + 백필 표식" 동시 충족 갯수 |

```bash
# 2) 잔여가 있다면 먼저 dry-run 으로 대상 확인
python scripts/backfill_chronicles.py --purge-leftover-reports --dry-run

# 3) 실삭제
python scripts/backfill_chronicles.py --purge-leftover-reports
```

| 잔여 판정 기준 | 동작 |
|---|---|
| `MarketChronicles/reports/YYYY/MM/*.md` 재귀 스캔 | reports 트리 전체를 BFS |
| 헤더 첫 200자에 `Market Chronicle (Backfill)` 포함 | 백필 표식 보유 파일만 식별 |
| `master_index.json` 의 어떤 `report_rel_path` 와도 일치하지 않음 | "잔여" 로 판정 |
| 위 세 조건 동시 충족 시에만 삭제 | T-Day 자동 작성 리포트(`# Market Chronicle YYYY-MM-DD`)는 자동 제외 |

**잔여 정리 vs 전체 재구축 — 명확한 구분**

- **잔여 정리(`--purge-leftover-reports`)**: master_index 외부의 백필 `.md` "만" 삭제. 인덱스 등록된 32건은 절대 건드리지 않음. 잔여 0건이 곧 "정상 상태" 보고임.
- **전체 재구축(`--reset --purge-reports --run`)**: 32건 모두 인덱스에서 제거하고 `.md` 까지 삭제 후 새로 채우는 완전 재구축. 인덱스에 정상 등록된 32건을 통째로 비우고 싶다면 잔여 정리가 아니라 이 명령을 사용해야 한다.

안전장치: T-Day 자동 작성 엔트리(`source != "backfill"`)와 그 리포트 파일은 본 섹션의 모든 함수에서 보호된다.

호환성: 기존 `--purge-orphan-reports` / `!백필고아청소` / `purge_orphan_backfill_reports()` / `backfill_purge_orphans()` 명칭은 deprecated alias 로 새 명칭과 동일 동작.

---

## 6. v3.2 Semantic Keyphrase Indexing & Retrieval

v3.0/v3.1 의 외장 메모리는 색인 키가 단순 `[가-힣]{2,}` 단어 집합이라, 정반대 의미의 사건도 같은 사례로 묶일 위험이 있었다. v3.2 는 색인과 검색을 **구문(phrase) 단위 의미적 유사도** 로 끌어올린다.

### 6.1 문제 정의 — 단어 매칭의 한계

| 예시 (과거 엔트리 vs 현재 국면) | 단어 일치만 보면 | 실제 의미 |
|---|---|---|
| 과거: "외국인 **매도**" / 현재: "외국인 **매수**" | 토큰 "외국인" 1개 일치 → **유사** | **정반대** 국면 (수급 방향 반대) |
| 과거: "Fed 금리 **인상**" / 현재: "Fed 금리 **인하**" | 토큰 3개 일치 → **매우 유사** | **정반대** 정책 신호 |
| 과거: "코스피 **급락**" / 현재: "코스피 **반등**" | 토큰 "코스피" 1개 일치 → **유사** | 반대 흐름 |

→ AI 가 "과거에 이렇게 했으니 지금도 그렇게 하자" 라는 행동 지침을 **정반대** 로 적용할 수 있는 치명적 결함.

### 6.2 인덱싱 — [주체 + 동사] 구문 추출

`src/memory/keyphrase_extractor.py` (신규) 가 두 단계로 추출한다.

1. **1차 (AI):** 리포트 본문을 Gemini 에게 주고 JSON 배열로 5~12개의 핵심 구문을 받는다. 각 항목은 `phrase` 외에 `subject`, `action`(정규형), `tone` (`positive`/`negative`/`neutral`) 을 포함.
2. **2차 (정규식 폴백):** AI 실패·타임아웃·JSON 파싱 실패 시 `SUBJECTS × MODIFIER × ACTION` 사전 매칭으로 직접 구문 추출. 운영 단절을 방지.

`chronicle_writer._build_keyphrases` 와 `backfill._build_keyphrases` 는 위 추출 결과에 매크로 트리거(예: VIX≥25, 코스피 ±1.5%)를 같은 포맷의 phrase 로 덧붙여 저장한다.

```python
# master_index.json entries[] 예시 (v3.2)
{
  "id": "a1b2c3d4",
  "date": "2026-04-02",
  "keyphrases": [
    {"phrase": "외국인 대량 매도",   "subject": "외국인", "action": "매도", "tone": "negative"},
    {"phrase": "Fed 금리 인상 신호", "subject": "Fed",   "action": "긴축", "tone": "negative"},
    {"phrase": "VIX 27 경계",       "subject": "VIX",    "action": "경계", "tone": "negative"}
  ],
  "keywords": ["외국인", "대량", "매도", "Fed", "금리", "인상", "VIX", "27"],
  "regime": "공포 확대 (VIX 27+)",
  "guideline_summary": "...",
  "report_rel_path": "MarketChronicles/reports/2026/04/2026-04-02_chronicle.md",
  "trigger": "VIX 27.4",
  "source": "backfill"
}
```

### 6.3 검색 — 의미적 유사도 우선 가중치

`context_retriever._score_entry` 는 점수를 다음 5단계 합으로 산출한다.

| 단계 | 가중치 | 매칭 기준 |
|---|---|---|
| ① 구문 자카드 (Exact ≥ 0.95) | **+12.0** | 동일 또는 거의 동일 phrase |
| ① 구문 자카드 (High ≥ 0.6) | **+8.0** | 토큰 자카드 + subject/action 보너스 |
| ① 구문 자카드 (Mid ≥ 0.35) | +4.0 | 부분 의미 일치 |
| ① 구문 자카드 (Low ≥ 0.15) | +2.0 | 약한 부분 일치 |
| ② subject 또는 action 만 일치 | +1.5 각 | 자카드 낮을 때 보강 |
| ③ tone 다수결 일치 | +2.0 | 쿼리·엔트리 모두 negative/positive 다수일 때 |
| ④ regime 그룹 일치 | +5.0 | "VIX 25↑", "급락", "급등" 등 사전 정의 그룹 |
| ⑤ 단어 토큰 폴백 | +0.5 × overlap | 구문 매칭 점수 0 일 때만 발동 |
| ⑥ 최근성 보너스 | +2.0 / +1.0 / +0.3 | 30 / 90 / 180일 이내 |

검색 함수 `search_similar_guidelines(query_phrases, regime, top_n=3, min_score=2.0)` 는 `min_score` 미만 항목을 무관 항목으로 배제하여 잡음 주입을 방지한다.

`build_context_injection_block` 이 출력하는 컨텍스트 블록에 **매칭 점수와 핵심 구문 목록** 을 함께 표기해, Gemini 가 어떤 과거 사례를 어떤 이유로 참고하는지 메타 인지하도록 돕는다.

```
--- 지침 1 (2026-04-02) | 점수 18.5 | 구문: 외국인 대량 매도 / Fed 금리 인상 신호 / VIX 27 경계 ---
요약: ...
{본문 발췌}
```

### 6.4 master_index.json 엔트리 스키마 변경

| 필드 | v3.0/v3.1 | v3.2 | 비고 |
|---|---|---|---|
| `keywords` | **메인 색인 키** | 폴백용 단어 토큰 (자동 파생) | 하위 호환 유지 |
| `keyphrases` | (없음) | **메인 색인 키** (list[dict]) | `phrase/subject/action/tone` |
| `regime` | 문자열 라벨 | 동일 | 그룹 매칭에 사용 |
| 기타 (`id`/`date`/`guideline_summary`/`report_rel_path`/`trigger`/`source`) | 동일 | 동일 | 변경 없음 |

기존 엔트리는 `keyphrases` 가 없으므로 점수 ⑤ 토큰 폴백 경로로 검색된다. 향후 새로 작성되는 T-Day/백필 엔트리부터 자연스럽게 의미 매칭 풀에 합류한다.

### 6.5 v3.2 구현 체크리스트

| 단계 | 상태 | 비고 |
|------|------|------|
| 1. `src/memory/keyphrase_extractor.py` 신규 | **완료** | AI 1차 + 정규식 폴백 |
| 2. `chronicle_writer._build_keyphrases` 적용 | **완료** | T-Day 엔트리에 `keyphrases` 저장 |
| 3. `backfill._build_keyphrases` 적용 | **완료** | 백필 엔트리도 동일 포맷 |
| 4. `context_retriever._score_entry` 재설계 | **완료** | 구문 자카드 + tone + regime 그룹 + recency |
| 5. `build_context_injection_block` 점수·구문 노출 | **완료** | AI 메타 인지 향상 |
| 6. `ai_logic.generate_text_with_chronicle` 시그니처 호환 | **완료** | 변수명 `query_phrases` 로 정정 |
| 7. 기존 엔트리 무중단 호환(토큰 폴백) | **완료** | `keywords` 단독 엔트리도 검색 가능 |
| 8. v3.1 백필 32건 재색인(임베딩 도입 시 일괄) | 미완 | `keyphrases` 추가는 v3.x 추후 마이그레이션 스크립트로 |
| 9. 임베딩 기반 RAG (text-embedding 모델) | 미완 | v3.3 후보 |

---

## 7. 향후 추진 과제 (Next Steps)

> 본 섹션은 `GEMINI.md`의 **최하단(마지막 섹션)** 에 위치해야 한다. 신규 버전·기능 상세 섹션 추가 시 본 섹션 **앞**에 삽입한다.

1.  **v3.0 Market Chronicles 고도화:**
    *   임베딩 기반 유사도 검색, temp/tech 자동 업로드, T-Day 크로니클 실전 작성 검증.
2.  **v3.1 Back-fill 후속 강화:**
    *   yfinance 외 다중 데이터 소스(예: 한국거래소 KRX 정식 일봉) 교차 검증.
    *   소급 시점의 실제 매크로 스냅샷(VIX·WTI·금리) 동시 보존 및 리포트에 명시.
    *   임베딩 RAG 도입 시 백필 리포트도 자동 재색인.
3.  **v3.2 후속 — 기존 엔트리 재색인 마이그레이션:**
    *   v3.1 백필 32건 등 `keywords` 만 보유한 엔트리를 일괄 재처리하여 `keyphrases` 까지 채우는 `scripts/reindex_keyphrases.py` 신설 검토.
    *   AI 호출 비용 절감을 위해 캐싱·배치 처리 도입.
4.  **v3.3 후보 — 임베딩 기반 RAG:**
    *   `text-embedding` 모델로 phrase·리포트 벡터화 후 코사인 유사도로 v3.2 가중치와 결합(하이브리드 검색).
5.  **전문가 인사이트 엔진 (Expert Insight Engine):**
    *   증권사 RSS 피드 또는 리포트 요약 채널 기반의 정성적 데이터 수집.
    *   리포트 내 목표 주가(TP), 투자의견(Rating), 핵심 논거(Thesis) 구조화 추출 및 AI 교차 검증 활용.
6.  **섹터별 특화 HTS 조건식 확장:**
    *   금융주 외 제약/바이오(R&D 투자 비율), 조선/기계(수주 잔고) 등 섹터별 핵심 지표를 반영한 HTS 조건식을 추가하여 AI 분석 후보군의 질적 향상.
7.  **실전(Live) 환경 전환 테스트:**
    *   Paper(모의) 모드에서 충분한 안정성이 검증된 후, `TRADING_MODE_NORMAL` 환경변수를 조정하여 실제 KIS 계좌 매수/매도 체결 딜레이 및 슬랙 알림 응답 속도 최적화.
