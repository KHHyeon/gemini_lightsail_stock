# GEMINI_DETAIL_CHRONICLES.md — Market Chronicles 상세 사양서

> 본 문서는 Market Chronicles(v3.0~v3.4) 의 비즈니스 로직, 데이터 스키마, 엣지 케이스 시나리오를 정의한다. 전역 시스템 사양(인프라/API/폴더 구조/전역 에러 정책)은 `GEMINI_SYS.md` 를 참조한다.
>
> **v3.4 (Master Index 구조 최적화) 진행 상태 (3단계 워크플로우)**:
> * **Step 1 (사양 정의)**: 완료. §1 헤더 / §4.3.2 / §4.4 / §5.1.2 / §5.1.3 / §6 v3.4 / §7 마이그레이션 4단계 / §9 임베딩 RAG → v3.5 격하 모두 반영.
> * **Step 2 (코드 구현)**: 완료. `macro_triggers.resolve_regime` + `REGIME_NEIGHBOR_MAP` 신설, `chronicle_common.{derive_market_state, derive_context_tags, parse_action_preview}` 신설, `drive_client.DriveSchemaMismatchError` + `read_master_index` 가드 + `AUTO_MIGRATE_V2` 분기, `chronicle_writer` / `backfill` v2 평탄화 적재로 갱신, `context_retriever._score_entry` 8단계 점수화 + `extract_market_context` dict 반환 + `build_context_injection_block` 3블록 압축 재설계, `scripts/migrate_master_index_v2.py` 신설.
> * **Step 3 (Post-Update)**: 완료. 본 문서 §8 (본 사이클 리팩토링 정합) 에 v3.4 변경 일람을 동기화.
>
> 본 문서의 변경 이력은 어떤 경우에도 이전 항목을 생략하지 않고 전체 보존한다(루트 워크스페이스 룰 1.4 준수).

---

## 목차

- [1. v3.0 Market Chronicles 아키텍처](#1-v30-market-chronicles-아키텍처)
  - [1.1 설계 원칙 (Cloud-Only, External Memory)](#11-설계-원칙-cloud-only-external-memory)
  - [1.2 폴더 구조 및 파일 역할](#12-폴더-구조-및-파일-역할)
  - [1.3 Pause/Resume 상호작용](#13-pauseresume-상호작용)
  - [1.4 T-Day 크로니클 작성 흐름](#14-t-day-크로니클-작성-흐름)
  - [1.5 Context Injection (유사 지침 주입)](#15-context-injection-유사-지침-주입)
  - [1.6 v3.0 구현 체크리스트](#16-v30-구현-체크리스트)
- [2. v3.1 Back-filling (과거 데이터 소급 구축)](#2-v31-back-filling-과거-데이터-소급-구축)
  - [2.1 목적 및 트리거](#21-목적-및-트리거)
  - [2.2 처리 단계 (Scan → Confirm → Backfill → Index)](#22-처리-단계-scan--confirm--backfill--index)
  - [2.3 진행 상태 보존 및 예외 처리](#23-진행-상태-보존-및-예외-처리)
  - [2.4 사용 인터페이스 (Slack / CLI / Orchestrator)](#24-사용-인터페이스-slack--cli--orchestrator)
  - [2.5 v3.1 구현 체크리스트](#25-v31-구현-체크리스트)
- [3. v3.2.1 / v3.2.3 운영 도구 (reset / reindex / diagnose / purge-leftover)](#3-v321--v323-운영-도구-reset--reindex--diagnose--purge-leftover)
  - [3.1 운영 시나리오와 모드 선택](#31-운영-시나리오와-모드-선택)
  - [3.2 잔여(leftover) 정의와 진단·정리 흐름](#32-잔여leftover-정의와-진단정리-흐름)
  - [3.3 호환성 (deprecated alias)](#33-호환성-deprecated-alias)
- [4. v3.2 Semantic Keyphrase Indexing & Retrieval](#4-v32-semantic-keyphrase-indexing--retrieval)
  - [4.1 문제 정의 — 단어 매칭의 한계](#41-문제-정의--단어-매칭의-한계)
  - [4.2 인덱싱 — 주체+동사 구문 추출](#42-인덱싱--주체동사-구문-추출)
  - [4.3 검색 — 의미적 유사도 우선 가중치](#43-검색--의미적-유사도-우선-가중치)
  - [4.4 호환성 (기존 keywords 엔트리)](#44-호환성-기존-keywords-엔트리)
  - [4.5 v3.2 구현 체크리스트](#45-v32-구현-체크리스트)
- [5. 데이터 스키마](#5-데이터-스키마)
  - [5.1 master_index.json](#51-master_indexjson)
  - [5.2 backfill_state.json](#52-backfill_statejson)
  - [5.3 pause_state.json / 로컬 pause flag](#53-pause_statejson--로컬-pause-flag)
- [6. 변경 이력 (v3.0 ~ v3.2.3)](#6-변경-이력-v30--v323)
- [7. 엣지 케이스 시나리오](#7-엣지-케이스-시나리오)
- [8. 본 사이클 리팩토링 정합 (선 설계)](#8-본-사이클-리팩토링-정합-선-설계)
- [9. 향후 추진 과제 — Chronicles 전용](#9-향후-추진-과제--chronicles-전용)

---

## 1. v3.0 Market Chronicles 아키텍처

### 1.1 설계 원칙 (Cloud-Only, External Memory)

Gemini API 는 매 호출마다 맥락이 초기화되는 단기 기억 모델이다. Market Chronicles 는 이를 보완하기 위해 **Google Drive 를 외장 메모리**로 사용하여 "당시 시장 상황에서 시스템이 확정한 행동 지침" 을 영구 보존하고, 차후 유사 국면에서 자동으로 인용한다.

| 항목 | 결정 |
|---|---|
| 저장소 | Google Drive 만 사용 (로컬 디스크 비저장) |
| 인증 | OAuth 데스크톱 앱 우선, fallback 으로 Service Account / Domain-wide Delegation / Shared Drive (자동 감지) |
| 단기 캐시 | 매니페스트(`folder_manifest.json`) 만 로컬 메모리에 핫 캐시 |
| Pause 신호 | 로컬 플래그 파일 `.drive_pause_local.json` + Drive `_system/pause_state.json` 이중화 |
| 산출물 | (1) 영구 보존 — `master_index.json`, `reports/YYYY/MM/*.md` (2) 30일 TTL — `temp/tech/` |

### 1.2 폴더 구조 및 파일 역할

```
[Drive Root]/Quant_Logs/
  app_data/                           # 일반 로그/포트폴리오 JSON (logger.py)
  MarketChronicles/
    index/
      master_index.json               # 상황 keyphrase + 행동 지침 요약 색인 (영구)
      folder_manifest.json            # 폴더/파일 ID 캐시 (drive_client 내부용)
    reports/
      YYYY/
        MM/
          YYYY-MM-DD_chronicle.md     # T-Day 또는 백필 리포트 (영구)
    temp/
      tech/                           # OHLCV/원시 뉴스 등 대용량 (30일 TTL)
    _system/
      pause_state.json                # Pause/Resume 상태 동기화 보조
      backfill_state.json             # 백필 진행 큐/processed/skipped
```

* 연/월 폴더 분할은 단일 폴더 누적으로 인한 Drive 검색 속도 저하를 차단하기 위한 의도된 분할이다.
* `temp/tech/` 는 `src/memory/lifecycle.py:purge_expired_temp_files` 가 매일 15:35 루틴에서 30일 경과 항목을 자동 삭제한다.
* `_system/` 의 상태 파일은 사용자 수정 금지(시스템 자동 갱신).

### 1.3 Pause/Resume 상호작용

Drive 권한 승인, 폴더 생성 누락, storage quota 초과 등 **사용자 개입이 필요한 예외**가 발생하면 시스템은 즉시 **Pause 상태**로 전환한다.

1. 예외 감지 → `drive_client.pause(reason, action_required)` 호출
   * 로컬 `.drive_pause_local.json` 기록 (다음 부팅에서도 인지)
   * Drive `_system/pause_state.json` 동기화 시도(실패 시에도 로컬 플래그가 보호)
2. 슬랙 안내 발송 — 건조하고 명확한 텍스트로 필요 조치 설명
3. 사용자가 슬랙에 `완료` 입력 → `try_resume_after_user_ack()` 가 Drive 상태 재검증
4. 정상이면 Pause 해제, 비정상이면 Pause 유지 + 추가 안내

> Pause 가 활성화된 동안 `read_*_relative`, `write_*_relative` 등 일반 I/O 진입점은 `_check_pause_guard()` 에서 즉시 `DrivePausedError` 를 발생시켜 무한 재귀 호출을 차단한다. 단, `_read_text_direct`, `_read_json_direct` 같은 내부용 직접 읽기 함수는 pause 점검을 우회한다 — 사용자 조치 후 재검증 단계에서 인덱스를 다시 읽어야 하기 때문이다.

전역 에러 정책 상세(B-Type 보고 룰)는 `GEMINI_SYS.md §8` 을 참조.

### 1.4 T-Day 크로니클 작성 흐름

| 단계 | 처리 |
|---|---|
| 트리거 판정 | `macro_triggers.evaluate_chronicle_trigger(vix, kospi_chg, kosdaq_chg)` — VIX ≥ 25 또는 KOSPI/KOSDAQ 등락률 절댓값 ≥ 1.5% (※ 본 사이클 리팩토링으로 상수화, §8 참조) |
| 뉴스 수집 | US 뉴스(`news_crawler.crawl_us_news`) + KR 뉴스(`news_crawler.crawl_kr_news`) |
| AI 프롬프트 빌드 | `chronicle_writer._build_chronicle_prompt(macro, us_news, kr_news, today_date)` |
| AI 호출 | `ai_logic.generate_text(prompt)` (단, `generate_text_with_chronicle` 는 사용 금지 — 자기 자신 인용 회피) |
| keyphrase 추출 | `chronicle_common.build_keyphrases(ai_text, vix=..., kospi_chg=..., kosdaq_chg=...)` (B-1 리팩토링 적용 후) |
| 리포트 저장 | `drive_client.write_text_relative(rel_path, full_md)` |
| 인덱스 갱신 | `drive_client.append_index_entry(entry_dict)` (B-5 리팩토링 적용 후) |
| 슬랙 알림 | `orchestrator.send_slack(...)` (메시지 게이트웨이 단일화 — `messenger.py` 제거) |

리포트 헤더 표식:

```text
# Market Chronicle YYYY-MM-DD

트리거: VIX 27.4
```

### 1.5 Context Injection (유사 지침 주입)

매수/매도 판단 직전, AI 호출 측은 다음 순서로 과거 지침을 주입한다.

```text
[현재 매크로 + 최신 뉴스 스니펫]
        |
        v
context_retriever.extract_market_context(macro, news_snippets)
        --> query_phrases (list[dict]) + regime (str)
        |
        v
context_retriever.search_similar_guidelines(query_phrases, regime, top_n=3, min_score=2.0)
        --> 점수 정렬된 entry 목록
        |
        v
context_retriever.build_context_injection_block(query_phrases, regime, top_n=3)
        --> [필수 준수 배경 지식] 텍스트 블록
        |
        v
ai_logic.generate_text_with_chronicle(prompt, macro, news_snippets, model_name)
        --> 블록을 프롬프트 상단에 강제 삽입 후 Gemini 호출
```

* `min_score=2.0` 미만 항목은 잡음으로 간주하여 주입 풀에서 배제.
* 컨텍스트 블록에는 각 사례의 매칭 점수와 keyphrase 목록을 함께 표기하여 AI 의 메타 인지를 돕는다.

### 1.6 v3.0 구현 체크리스트

| 단계 | 상태 | 비고 |
|---|---|---|
| 1. `drive_client.py` (인증/폴더/Pause) | 완료 | OAuth/SA/Delegation/SharedDrive 자동 감지 |
| 2. Drive 폴더 + `master_index.json` 초기화 | 완료 | `Quant_Logs/MarketChronicles/` 실서버 생성 검증 |
| 3. `chronicle_writer.py` | 완료 | T-Day 트리거 → AI → 리포트 + 인덱스 |
| 4. `context_retriever.py` + `ai_logic.generate_text_with_chronicle` | 완료 | (v3.2 에서 구문 단위 의미 매칭으로 고도화, §4 참조) |
| 5. `lifecycle.py` 30일 TTL | 완료 | 15:35 루틴에 포함 |
| 6. `orchestrator` 15:35 스케줄 | 완료 | |
| 7. `logger.py` Drive 연동 | 완료 | 미설정 시 로컬 폴백 |
| 8. OAuth 인증 체계 | 완료 | headless `--no-browser`, 자동 토큰 갱신 |
| 9. 셋업 스크립트 3종 | 완료 | `scripts/drive_oauth_setup.py`, `drive_oauth_refresh.py`, `drive_folder_bootstrap.py` |
| 10. T-Day 크로니클 실전 검증 | 대기 | 트리거 충족 일자 발생 시 |
| 11. 색인·검색 의미 매칭 강화 | v3.2 적용 완료 | 구문(keyphrases) 단위 인덱싱·검색 가중치 (§4) |
| 12. 임베딩 RAG / temp 자동 업로드 | 미완 | v3.3 후보 (§9) |

구현율: **85%** (v3.0 시점 기준 동일).

---

## 2. v3.1 Back-filling (과거 데이터 소급 구축)

### 2.1 목적 및 트리거

| 항목 | 내용 |
|---|---|
| 목적 | 봇 첫 가동 즉시 Context Injection 풀을 충분히 확보 |
| 소급 기간 | 기본 60일 (CLI/슬랙에서 조정 가능) |
| 이벤트 데이 조건 | 코스피(`^KS11`) 또는 코스닥(`^KQ11`) 일간 등락률 절댓값 1.5% 이상, 또는 VIX(`^VIX`) 종가 25 이상 |
| 데이터 소스 | `yfinance` 일봉(`history(period="3mo")`) — 한국 거래소 영업일 자동 정렬 |
| 출력 규격 | `.md` 리포트(연/월 폴더 분할) + `master_index.json` 엔트리(`source="backfill"` 표식) |

### 2.2 처리 단계 (Scan → Confirm → Backfill → Index)

```text
[1단계 Scan]
  yfinance 일봉 -> 트리거 충족 일자 추출 -> 슬랙 보고
  Drive: MarketChronicles/_system/backfill_state.json 초기화 (queue 등록)
                |
                v (사용자가 '확인' 또는 '!백필실행' 입력)
[2단계 Backfill 1건씩]
  for 날짜 in queue:
    - 이미 reports/YYYY/MM/YYYY-MM-DD_chronicle.md 존재? -> 스킵
    - 뉴스 키워드 수집(news_crawler) + 당시 매크로 추정치 합성
    - AI 프롬프트(사후 통찰 포함) -> [장중 흐름 / 사건 원인 / 미래 행동 지침]
    - Drive 에 .md 저장 + master_index.json 색인 추가(source="backfill")
    - 기본 3초 대기 (API Rate Limit 보호)
                |
                v
[3단계 결과 보고]
  슬랙: 완료 N건 / 스킵 M건 / 실패 K건 + 평균 소요시간
```

* **사후 통찰 프롬프트**: 백필 리포트는 "오늘 시점에서 돌이켜 본 교훈" 을 포함하도록 프롬프트를 보강하여, 단순 사후 요약이 아닌 **현재 시점의 학습 가능한 행동 지침**으로 가공한다.
* **트리거 판정 정합**: T-Day 와 동일한 임계값(VIX 25 / 등락률 1.5%) 적용. B-2 리팩토링으로 `macro_triggers.evaluate_chronicle_trigger` 단일 함수로 통합.
* **리포트 헤더 표식**: 백필은 `# Market Chronicle (Backfill) YYYY-MM-DD` — T-Day(`# Market Chronicle YYYY-MM-DD`)와 헤더 첫 줄로 명확히 구분.

### 2.3 진행 상태 보존 및 예외 처리

| 메커니즘 | 위치 | 동작 |
|---|---|---|
| 상태 파일 | Drive `MarketChronicles/_system/backfill_state.json` | `{lookback_days, scanned_at, queue[], processed[], skipped[], updated_at}` |
| 중복 방지 | 작업 전 `reports/YYYY/MM/YYYY-MM-DD_chronicle.md` 존재 확인 | 존재 시 `skipped(reason="exists")` |
| 건당 대기 | `time.sleep(delay_sec)` (기본 3초) | API 호출량 제어 |
| 에러 격리 | `try/except` 로 1일자 처리 단위 보호 | 실패 시 `skipped(reason="error:<msg>")` |
| 이어쓰기 | 재실행 시 `queue` 중 `processed`/`skipped` 가 아닌 항목만 처리 | 중단/재개 안전 |
| Drive Pause | 작업 중 `DrivePausedError` 발생 시 즉시 중단 + 슬랙 안내 | 사용자 `완료` 응답 후 재실행 |

### 2.4 사용 인터페이스 (Slack / CLI / Orchestrator)

본 사이클 리팩토링(q1=Path B)으로 **모든 슬랙 핸들러는 `orchestrator.backfill_*` 게이트웨이를 경유**한다. 슬랙 핸들러가 `src.memory.backfill` 을 직접 import 하던 기존 구조는 제거된다.

| 채널 | 입력 | 동작 (호출 경로) |
|---|---|---|
| Slack | `!백필스캔` 또는 `!백필스캔 60` | `orchestrator.backfill_scan(lookback_days)` → `backfill.scan_and_save` |
| Slack | `확인` | 직전 스캔에 대해 `orchestrator.backfill_run()` 실행 (`완료` 는 Drive Pause 해제 전용으로 분리) |
| Slack | `!백필실행` | `orchestrator.backfill_run()` |
| Slack | `!백필초기화 [purge]` | `orchestrator.backfill_reset(delete_reports=True if "purge" else False)` |
| Slack | `!백필재인덱싱 [건당대기초]` | `orchestrator.backfill_reindex(delay_sec)` |
| Slack | `!백필상태` | `orchestrator.backfill_diagnose()` (읽기 전용) |
| Slack | `!백필잔여정리 [dry]` | `orchestrator.backfill_purge_leftover(dry_run=True if "dry" else False)` |
| CLI | `python scripts/backfill_chronicles.py --scan-only --lookback 60` | 스캔만 수행 |
| CLI | `python scripts/backfill_chronicles.py --run --delay 3` | 저장된 queue 실행 |
| CLI | `python scripts/backfill_chronicles.py --lookback 60 --run` | 스캔 + 즉시 실행 |
| CLI | `python scripts/backfill_chronicles.py --reset [--purge-reports]` | 백필 결과 초기화 |
| CLI | `python scripts/backfill_chronicles.py --reset --purge-reports --run` | 완전 재구축 |
| CLI | `python scripts/backfill_chronicles.py --reindex --delay 3` | `.md` 보존, keyphrases 재추출 |
| CLI | `python scripts/backfill_chronicles.py --diagnose-reports` | 정합 진단 |
| CLI | `python scripts/backfill_chronicles.py --purge-leftover-reports [--dry-run]` | 잔여 백필 `.md` 정리 |
| Orchestrator | `backfill_scan / backfill_run / backfill_reset / backfill_reindex / backfill_diagnose / backfill_purge_leftover` | 슬랙·스케줄 통합 진입점 (게이트웨이) |

### 2.5 v3.1 구현 체크리스트

| 단계 | 상태 | 비고 |
|---|---|---|
| 1. `src/memory/backfill.py` (스캔/리포트/인덱싱/상태보존) | 완료 | yfinance 기반 이벤트 데이 추출, 3초 대기, 스킵 로그 |
| 2. `scripts/backfill_chronicles.py` CLI | 완료 | `--scan-only` / `--run` / `--lookback` / `--delay` |
| 3. 슬랙 `!백필스캔` / `!백필실행` / `확인` 처리 | 완료 | `slack_interface.py` 핸들러 |
| 4. `MarketOrchestrator.backfill_scan` / `backfill_run` | 완료 | 슬랙 통합 진입점 |
| 5. 사후 통찰 프롬프트 (과거 분석 강화) | 완료 | "현재 시점에서 돌이켜 본 교훈" 포함 |
| 6. Drive `backfill_state.json` 상태 저장·이어쓰기 | 완료 | 중단 후 재개 안전 |
| 7. T-Day 본 크로니클과 동일 색인 규격(`master_index.json`) | 완료 | `source="backfill"` 표식만 추가 |
| 8. 실전 운영 검증 | 완료 (2026-05-20) | lookback 60일, 완료 32 / 스킵 0 / 실패 0 (terminal 수동 실행) |
| 9. 백필 초기화·재인덱싱 운영 도구 | v3.2.1 완료 | `--reset` / `--reindex` / 슬랙 명령 (§3) |
| 10. 슬랙 라우팅 정합 (Path B) | **본 사이클 적용** | 모든 슬랙 핸들러가 orchestrator 게이트웨이 경유 (§8) |
| 11. 임베딩 기반 유사도 검색·실시간 매크로 스냅샷 통합 | 미완 | v3.x 향후 (§9) |

구현율: **98%** (실전 검증 완료 + 라우팅 정합 적용 예정).

---

## 3. v3.2.1 / v3.2.3 운영 도구 (reset / reindex / diagnose / purge-leftover)

### 3.1 운영 시나리오와 모드 선택

| 모드 | 시나리오 | AI 호출 | `.md` 리포트 | `master_index` | 추천 |
|---|---|---|---|---|---|
| `reset_backfill(delete_reports=False)` | 엔트리만 비우고 다시 채움 | 재실행 시 N회 (백필 전체) | 보존 | `source="backfill"` 엔트리 제거 | 빠른 재구축 |
| `reset_backfill(delete_reports=True)` | 처음부터 완전 재구축 | 재실행 시 N회 (백필 전체) | 삭제 | 엔트리 + 파일 모두 제거 | 깨끗한 재시작 |
| `reindex_keyphrases()` | `.md` 살리고 `keyphrases` 만 재추출 | N회 (구문 추출만) | 보존 | 엔트리에 `keyphrases`/`reindexed_at` 추가 | **권장 (비용 최소)** |

권장 마이그레이션 절차 (v3.1 → v3.2 전환, 32건 기준):

```bash
# .md 와 인덱스를 모두 살리면서 v3.2 keyphrases 만 채워 넣는다 (약 32회 AI 호출, 약 100초)
python scripts/backfill_chronicles.py --reindex --delay 3
```

완전 재구축이 필요한 경우:

```bash
# 백필 1회당 AI 2~3회 호출 + 3초 대기
python scripts/backfill_chronicles.py --reset --purge-reports --lookback 60 --run --delay 3
```

**T-Day 엔트리 보호**: 위 세 함수는 모두 `source != "backfill"` 엔트리(T-Day 자동 작성분)를 절대 건드리지 않는다. 슬랙·CLI 양쪽에서 강제 적용.

### 3.2 잔여(leftover) 정의와 진단·정리 흐름

`--reset --purge-reports` 도중 `.md` 가 정상 삭제되지 못해 `master_index` 외부에 남은 상태를 **잔여(leftover)** 로 정의한다.

#### 진단 (`!백필상태` / `--diagnose-reports`)

읽기 전용으로 다음 6개 수치를 한 번에 보고한다.

| 항목 | 의미 |
|---|---|
| `reports/*.md` 총 N건 | 트리 전체의 `.md` 갯수 |
| 인덱스 등록 / 미등록 | `master_index.json` 의 `report_rel_path` 와 일치 여부별 분포 |
| 백필 헤더 표식 / T-Day 헤더 표식 | 헤더 첫 200자에서 `Market Chronicle (Backfill)` / `Market Chronicle ` 매칭 분포 |
| master_index 엔트리 (백필 / T-Day) | `source` 필드 기준 분포 |
| **잔여 정리 대상** | "인덱스 미등록 + 백필 표식" 동시 충족 갯수 |

#### 정리 (`!백필잔여정리 [dry]` / `--purge-leftover-reports [--dry-run]`)

| 잔여 판정 기준 | 동작 |
|---|---|
| `MarketChronicles/reports/YYYY/MM/*.md` 재귀 스캔 | reports 트리 전체를 BFS |
| 헤더 첫 200자에 `Market Chronicle (Backfill)` 포함 | 백필 표식 보유 파일만 식별 |
| `master_index.json` 의 어떤 `report_rel_path` 와도 일치하지 않음 | "잔여" 로 판정 |
| 위 세 조건 동시 충족 시에만 삭제 | T-Day 자동 작성 리포트(`# Market Chronicle YYYY-MM-DD`) 는 표식 불일치로 자동 보호 |

#### 잔여 정리 vs 전체 재구축

| 명령 | 효과 |
|---|---|
| `--purge-leftover-reports` | `master_index` 외부의 백필 `.md` "만" 삭제. 인덱스 등록된 엔트리는 절대 미변경. 잔여 0건이 곧 정상 상태 보고 |
| `--reset --purge-reports --run` | 인덱스 + `.md` 모두 비우고 새로 채우는 완전 재구축 |

#### v3.2.3 핫픽스 (2026-05-20)

`drive_client._find_file_in_parent` 가 file ID 문자열이 아닌 메타데이터 dict 전체를 반환하던 동작에 의해 `--reset --purge-reports` 가 `HttpError 404 File not found` 로 실패하던 버그를 수정.

* `backfill._delete_file_at_rel_path` 가 반환값을 dict 로 인지하여 `.get("id")` 만 추출하도록 정정
* 404/notFound 응답은 "이미 삭제됨" 으로 간주 → idempotent 동작 보장

본 사이클 리팩토링(B-5)으로 `drive_client.delete_file_relative(rel_path)` 공개 헬퍼가 추가되면, `backfill._delete_file_at_rel_path` 는 단순 호출로 축소되고 위 버그 패턴이 구조적으로 재발 불가능해진다.

### 3.3 호환성 (deprecated alias)

| 신 명칭 | 구 명칭 (deprecated alias, 동일 동작 유지) |
|---|---|
| `purge_leftover_backfill_reports()` | `purge_orphan_backfill_reports()` |
| CLI `--purge-leftover-reports` | `--purge-orphan-reports` |
| Slack `!백필잔여정리` | `!백필고아청소` |
| `MarketOrchestrator.backfill_purge_leftover()` | `backfill_purge_orphans()` |

"고아(orphan)" 표현은 사용자 피드백에 따라 "잔여(leftover)" 로 변경되었다. 구 명칭은 외부 자동화 호환을 위해 함수 alias 형태로 보존하되, 신규 문서·UI 는 신 명칭만 사용한다.

---

## 4. v3.2 Semantic Keyphrase Indexing & Retrieval

### 4.1 문제 정의 — 단어 매칭의 한계

v3.0/v3.1 의 외장 메모리는 색인 키가 단순 `[가-힣]{2,}` 단어 집합이라 정반대 의미 사건이 같은 사례로 묶일 위험이 있었다.

| 예시 (과거 엔트리 vs 현재 국면) | 단어 일치만 보면 | 실제 의미 |
|---|---|---|
| 과거 "외국인 매도" / 현재 "외국인 매수" | 토큰 "외국인" 일치 → 유사 | 정반대 (수급 방향 반대) |
| 과거 "Fed 금리 인상" / 현재 "Fed 금리 인하" | 토큰 3개 일치 → 매우 유사 | 정반대 (정책 신호 반대) |
| 과거 "코스피 급락" / 현재 "코스피 반등" | 토큰 "코스피" 일치 → 유사 | 반대 흐름 |

→ AI 가 "과거에 이렇게 했으니 지금도 그렇게 하자" 라는 행동 지침을 **정반대**로 적용할 수 있는 치명적 결함.

### 4.2 인덱싱 — 주체+동사 구문 추출

`src/memory/keyphrase_extractor.py` 가 두 단계로 추출한다.

1. **1차 (AI)**: 리포트 본문을 Gemini 에게 주고 JSON 배열로 5~12개의 핵심 구문을 받는다. 각 항목은 `phrase` 외에 `subject`, `action`(정규형), `tone` (`positive` / `negative` / `neutral`) 을 포함.
2. **2차 (정규식 폴백)**: AI 실패·타임아웃·JSON 파싱 실패 시 `SUBJECTS x MODIFIER x ACTION` 사전 매칭으로 직접 구문 추출. 운영 단절 방지.

본 사이클 리팩토링(B-1)으로 `chronicle_common.build_keyphrases(ai_text, *, vix, kospi_chg, kosdaq_chg)` 단일 함수가 신설되어, `chronicle_writer._build_keyphrases` 와 `backfill._build_keyphrases` 양쪽에서 호출된다. 입력 키(`VIX/KOSPI_CHG/KOSDAQ_CHG` vs `vix_close/kospi_chg/kosdaq_chg`)는 호출부에서 정규화하여 전달한다.

본 함수는 추출된 keyphrase 목록에 매크로 트리거(VIX 25 이상 경계, 코스피 1.5% 급등/급락 등)를 동일 포맷의 phrase 로 덧붙여 저장한다.

### 4.3 검색 — 의미적 유사도 우선 가중치

#### 4.3.1 v3.2 가중치 (v3.0~v3.3.1 운영, v1 스키마 기준)

`context_retriever._score_entry` 는 점수를 다음 5단계 합으로 산출한다.

| 단계 | 가중치 | 매칭 기준 |
|---|---|---|
| 1. 구문 자카드 (Exact >= 0.95) | +12.0 | 동일 또는 거의 동일 phrase |
| 1. 구문 자카드 (High >= 0.6) | +8.0 | 토큰 자카드 + subject/action 보너스 |
| 1. 구문 자카드 (Mid >= 0.35) | +4.0 | 부분 의미 일치 |
| 1. 구문 자카드 (Low >= 0.15) | +2.0 | 약한 부분 일치 |
| 2. subject 또는 action 만 일치 | +1.5 (각) | 자카드 낮을 때 보강 |
| 3. tone 다수결 일치 | +2.0 | 쿼리·엔트리 모두 negative/positive 다수일 때 |
| 4. regime 그룹 일치 | +5.0 | "VIX 25 이상", "급락", "급등" 등 사전 정의 그룹 |
| 5. 단어 토큰 폴백 | +0.5 x overlap | 구문 매칭 점수 0 일 때만 발동 |
| 6. 최근성 보너스 | +2.0 / +1.0 / +0.3 | 30 / 90 / 180일 이내 |

`search_similar_guidelines(query_phrases, regime, top_n=3, min_score=2.0)` 는 `min_score` 미만 항목을 무관 항목으로 배제하여 잡음 주입을 방지한다.

`build_context_injection_block` 은 컨텍스트 블록에 **매칭 점수와 핵심 구문 목록**을 함께 표기해 Gemini 가 어떤 과거 사례를 왜 참고하는지 명시한다.

#### 4.3.2 v3.4 가중치 (사양 정의, v2 스키마 기준 — 0.1초 판단 우선)

v2 스키마(`market_state` + `context_tags_list` + `action_preview` + `phrases_list` + `embedding_vector`)에 맞춰 점수 합을 재설계한다. 변경 핵심:

* (1) **`context_tags_list` 자카드를 1순위(+10)로 격상** — 이미지 §5.1.2 의 "0.1초 판단" 원칙을 점수화 비용에도 반영. 짧은 [주체_동사] 결합 태그가 가장 빠른 매칭 단위.
* (2) **`market_state.regime` enum 정확/인접 매칭** — 자유형 자카드 비교 폐기.
* (3) **`market_state.main_actor` 부분 일치 + `market_state.sentiment` 일치 보너스** — v3.2 의 subject·action·tone 분산 계산 비용을 1회 비교로 감소.
* (4) **`phrases_list` 자카드는 보조 의미 매칭** — `context_tags_list` 매칭이 임계 이하일 때만 점수 기여 (가독성 영역에는 노출 안 함).
* (5) **`keywords` 폴백 완전 폐기**.
* (6) **`embedding_vector` 코사인 보너스 슬롯 예약(v3.5 활성)**.

| 단계 | 가중치 | v2 매칭 기준 | 비고 |
|---|---|---|---|
| 1-A. `context_tags_list` 자카드 (High >= 0.5) | +10.0 | 쿼리 태그 set 과 엔트리 `context_tags_list` set 의 자카드 유사도 | **0.1초 판단 핵심**. 짧은 [주체_동사] 토큰 매칭은 phrase 토큰 자카드보다 약 5배 빠르다. |
| 1-B. `context_tags_list` 자카드 (Mid >= 0.3) | +6.0 | 동상 | |
| 1-C. `context_tags_list` 자카드 (Low >= 0.15) | +3.0 | 동상 | |
| 2. `market_state.regime` **정확 일치** | +5.0 | 쿼리 추정 enum 과 엔트리 `market_state.regime` 이 동일 | 8종 enum |
| 3. `market_state.regime` **인접 그룹** | +2.0 | `REGIME_NEIGHBOR_MAP` 동일 강도 계열 (예: `FEAR_EXTREME` ↔ `FEAR_RISING`) | 코드 PR 시 `context_retriever.REGIME_NEIGHBOR_MAP` 신설 |
| 4. `market_state.main_actor` 부분 일치 | +1.5 | 쿼리 측 최빈 subject 가 엔트리 `main_actor` 문자열에 포함되거나 동일 토큰 공유 | v3.2 의 subject 단독 일치(+1.5) 와 동일 가중치 |
| 5. `market_state.sentiment` 일치 | +1.5 | 쿼리 측 추정 sentiment 와 엔트리 `sentiment` 가 동일 또는 동의어 매핑 일치 | v3.2 의 tone 다수결(+2.0) 보다 약간 낮은 비용 (단일 비교) |
| 6-A. `phrases_list` 자카드 (High >= 0.6) | +4.0 | `context_tags_list` 매칭이 단계 1-A 임계 미달일 때만 발동 | 의미 매칭 보조 폴백 |
| 6-B. `phrases_list` 자카드 (Mid >= 0.35) | +2.0 | 동상 | |
| 7. 최근성 보너스 | +2.0 / +1.0 / +0.3 | 30 / 90 / 180일 이내 | 동일 |
| 8. `embedding_vector` 코사인 (v3.5 예약) | +0.0 (v3.4) / +α (v3.5) | `embedding_vector is not None` 이고 쿼리 측 임베딩이 준비된 경우만 활성 | v3.4 단계에서는 항상 0 가산. v3.5 도입 시 본 단계만 추가하여 하이브리드화 |

##### 쿼리 측 추정 산출 (`extract_market_context`)

검색 진입점인 `context_retriever.extract_market_context(macro_dict, news_snippets)` 는 v3.4 에서 다음 4개 필드를 산출한다 (코드 PR 시 재설계).

| 산출 필드 | 산출 방법 |
|---|---|
| `query_context_tags_list` | 매크로 트리거 (VIX 25+/등락률 1.5%+ 등) + 뉴스 본문 정규식 폴백으로 [주체_동사] 결합 태그 생성. |
| `query_regime` (enum) | `macro_triggers.resolve_regime(vix, kospi_chg, kosdaq_chg)` 호출. |
| `query_main_actor_keyword` | 뉴스 본문 정규식으로 최빈 subject 추출 (예: `"외국인"`, `"기관"`). 점수화 단계 4 의 부분 일치에 사용. |
| `query_sentiment` | `macro_triggers` 임계와 매크로 강도로 결정 (예: VIX >= 27 → `"위험 회피 극대화"`, VIX < 15 → `"낙관 우위"`). 점수화 단계 5 의 일치 비교에 사용. |

##### `search_similar_guidelines` 시그니처 (v3.4)

```python
def search_similar_guidelines(
    query_context_tags_list,    # list[str]
    query_regime,               # str (enum) | None
    *,
    query_main_actor_keyword="",
    query_sentiment="",
    query_phrases_list=None,    # list[dict] | None (보조 의미 매칭용)
    top_n=3,
    min_score=3.0,
):
    ...
```

`min_score` 기본값을 v3.2 의 2.0 → **3.0** 으로 상향 — 1순위 `context_tags_list` 자카드가 Low 임계만 충족해도 3.0 점이 가산되므로, 그 미만은 정말로 무관한 사례로 판단하여 잡음을 차단한다.

##### `build_context_injection_block` 출력 형식 (v3.4)

`phrases_list` / `embedding_vector` 는 **AI 가독성 영역에 노출하지 않는다**. 출력은 다음 3블록 구조로 압축한다.

```text
--- 지침 1 (2026-05-20) | 점수 18.5 | 시장 상태: 강한 하락장 (Panic) | 외국인 대규모 매도 | 위험 회피 극대화 ---
태그: 코스닥_급락 / 성장주_동반하락 / 디스카운트_지속 / 정부_대응_미흡
지침: 성장주 신규 매수 전면 금지 및 현금 비중 70% 확보 지침
```

* 1행 헤더: 날짜 / 점수 / `market_state.regime_label` / `main_actor` / `sentiment`
* 2행 태그: `context_tags_list` 를 ` / ` 로 join (최대 6개)
* 3행 지침: `action_preview` (최대 200자)

##### v1 엔트리 호환 (마이그레이션 진행 중 한정)

v3.4 코드는 기본적으로 `version=2` 만 처리한다. 만약 마이그레이션이 완료되지 않은 상태에서 봇이 기동되면 `DriveSchemaMismatchError` (B-Type) 가 즉시 발생하여 검색 자체가 시도되지 않는다 (SYS §8.1). 따라서 v3.4 운영 중에는 `keywords` 폴백 경로가 코드 상에서 완전히 제거된다.

```text
--- 지침 1 (2026-04-02) | 점수 18.5 | 구문: 외국인 대량 매도 / Fed 금리 인상 신호 / VIX 27 경계 ---
요약: ...
{본문 발췌}
```

### 4.4 호환성 (기존 keywords 엔트리)

기존 v3.0/v3.1 엔트리는 `keyphrases` 필드 없이 `keywords` 만 보유한다. v3.2~v3.3.1 까지는 검색 시 가중치 단계 5(단어 토큰 폴백)로 자연스럽게 매칭하여 **무중단 업그레이드**를 유지했다. v3.2~v3.3.1 의 신규 T-Day/백필 엔트리는 `keyphrases` 와 `keywords` 둘 다 저장하여 점진 전환을 지원했다.

**v3.4 정책 (사양 정의 완료, 코드 미반영)**: `master_index.json` 스키마를 `version=2` 로 개편하여 v1 의 `keyphrases` + `keywords` + 자유형 `regime` + `guideline_summary` 4개 분산 필드를 **entry 최상위에서 평탄화** 한다 — `market_state`(dict) + `context_tags_list`(list[str]) + `action_preview`(str) + `phrases_list`(보조). v2 엔트리에서는 `keywords` 가 **완전히 제거**되며, v1 엔트리의 `keywords` 폴백 경로(`context_retriever._score_entry` 의 +0.5×overlap)는 v3.4 코드 가동 시점에 폐기된다. 마이그레이션 시 v1 의 `keywords` 는 `chronicle_common.derive_context_tags(phrases_list, market_state_dict)` 의 산출 입력으로 활용되어 `context_tags_list` 의 [주체_동사] 결합 태그 형태로 손실 없이 이관된다. v3.4 의 엔트리 스키마 정의는 **§5.1.2 v2** 를, 마이그레이션 절차는 **`GEMINI_SYS.md §7.5`** 와 본 문서 **§7** 을 참조한다.

### 4.5 v3.2 구현 체크리스트

| 단계 | 상태 | 비고 |
|---|---|---|
| 1. `src/memory/keyphrase_extractor.py` 신규 | 완료 | AI 1차 + 정규식 폴백 |
| 2. `chronicle_writer._build_keyphrases` 적용 | 완료 | T-Day 엔트리에 `keyphrases` 저장 |
| 3. `backfill._build_keyphrases` 적용 | 완료 | 백필 엔트리도 동일 포맷 |
| 4. `context_retriever._score_entry` 재설계 | 완료 | 구문 자카드 + tone + regime 그룹 + recency |
| 5. `build_context_injection_block` 점수·구문 노출 | 완료 | AI 메타 인지 향상 |
| 6. `ai_logic.generate_text_with_chronicle` 시그니처 호환 | 완료 | 변수명 `query_phrases` 정정 |
| 7. 기존 엔트리 무중단 호환(토큰 폴백) | 완료 | `keywords` 단독 엔트리도 검색 가능 |
| 8. v3.1 백필 32건 재색인 | 완료 (v3.2.1 `--reindex`) | AI 1회 호출만으로 v3.2 포맷 전환 |
| 9. `_build_keyphrases` 중복 제거 (chronicle_common 통합) | **본 사이클 적용** | B-1 (§8) |
| 10. 임베딩 기반 RAG (text-embedding 모델) | 미완 | v3.3 후보 (§9) |

구현율: **94%** (B-1 통합 후 기준).

---

## 5. 데이터 스키마

### 5.1 master_index.json

본 절은 v1 (v3.0~v3.3.1 운영 스키마) 과 v2 (v3.4 사양 정의) 두 버전을 모두 보존한다(룰 1.4 append-only). v3.4 코드 가동 시점 이후 v1 은 마이그레이션 대상으로만 의미를 가지며, 실제 운영 스키마는 v2 이다.

#### 5.1.1 v1 (v3.0~v3.3.1 운영 스키마)

```json
{
  "version": 1,
  "entries": [
    {
      "id": "a1b2c3d4",
      "date": "2026-04-02",
      "keyphrases": [
        {"phrase": "외국인 대량 매도",   "subject": "외국인", "action": "매도", "tone": "negative"},
        {"phrase": "Fed 금리 인상 신호", "subject": "Fed",   "action": "긴축", "tone": "negative"},
        {"phrase": "VIX 27 경계",       "subject": "VIX",    "action": "경계", "tone": "negative"}
      ],
      "keywords": ["외국인", "대량", "매도", "Fed", "금리", "인상", "VIX", "27"],
      "regime": "공포 확대 (VIX 27 이상)",
      "guideline_summary": "...",
      "report_rel_path": "MarketChronicles/reports/2026/04/2026-04-02_chronicle.md",
      "trigger": "VIX 27.4",
      "source": "backfill",
      "reindexed_at": "2026-05-20T09:30:00+09:00"
    }
  ]
}
```

| 필드 | 타입 | 비고 |
|---|---|---|
| `version` | int | v1 운영 스키마. v3.4 코드 가동 시점에 deprecated. 감지 시 B-Type Pause (`GEMINI_SYS.md §8.1`). |
| `entries` | list[dict] | 추가 전용 (append-only) |
| `id` | str | 8자 hex (날짜+해시) |
| `date` | str | `YYYY-MM-DD` |
| `keyphrases` | list[dict] | v3.2 메인 색인 키. v3.4 에서 `semantic_context.phrases` 로 흡수. |
| `keywords` | list[str] | 폴백용 토큰 (keyphrases 에서 자동 파생). v3.4 에서 폐기, 마이그레이션 시 `semantic_context.summary_kw` 로 이관. |
| `regime` | str | 자유형 시장 국면 라벨 (예: `"공포 확대 (VIX 27 이상)"`). v3.4 에서 enum + `regime_label` 보조 필드로 분리. |
| `guideline_summary` | str | 행동 지침 한 줄 요약 (최대 300자) — v3.4 에서도 동일 유지. |
| `report_rel_path` | str | Drive 상대경로 — v3.4 에서도 동일 유지. |
| `trigger` | str | "VIX 27.4", "KOSPI -1.8%" 등 트리거 사유 — v3.4 에서도 동일 유지. |
| `source` | str | `"chronicle"` (T-Day) 또는 `"backfill"` (소급) — v3.4 에서도 동일 유지. |
| `reindexed_at` | str (옵션) | v3.2.1 `reindex_keyphrases` 적용 시점 — v3.4 에서도 동일 유지(마이그레이션 적용 시점은 별도 `migrated_at`). |

#### 5.1.2 v2 (v3.4 사양 정의 — 상황 매칭형 0.1초 판단 압축 구조)

본 스키마는 v1 의 나열형(`keyphrases` + `keywords` 두 필드 + 자유형 `regime` 문자열) 구조를 **상황 매칭형(Scenario Matching) 0.1초 판단 압축 구조** 로 재설계한다. 핵심 원칙은 "**AI 가 검색할 때 `context_tags_list` 와 `market_state` 만 보고도 현재 상황과 일치하는지 0.1초 만에 판단할 수 있어야 한다**" 이다. 모든 list 필드는 SYS §2.1 명명 규칙(`_list` 접미사)을 준수한다.

```json
{
  "version": 2,
  "entries": [
    {
      "id": "b432d18a",
      "date": "2026-05-20",
      "trigger": "KOSDAQ -2.61%",
      "market_state": {
        "regime": "PANIC_SELL",
        "regime_label": "강한 하락장 (Panic)",
        "main_actor": "외국인 대규모 매도",
        "sentiment": "위험 회피 극대화"
      },
      "context_tags_list": [
        "코스닥_급락", "성장주_동반하락", "디스카운트_지속", "정부_대응_미흡"
      ],
      "action_preview": "성장주 신규 매수 전면 금지 및 현금 비중 70% 확보 지침",
      "phrases_list": [
        {"phrase": "외국인 대량 매도",        "subject": "외국인", "action": "매도", "tone": "negative"},
        {"phrase": "코스닥 급락 -2.61%",      "subject": "코스닥", "action": "하락", "tone": "negative"},
        {"phrase": "성장주 디스카운트 지속",  "subject": "성장주", "action": "하락", "tone": "negative"}
      ],
      "embedding_vector": null,
      "report_rel_path": "MarketChronicles/reports/2026/05/2026-05-20_chronicle.md",
      "source": "backfill",
      "reindexed_at": "2026-05-20T09:30:00+09:00",
      "migrated_at": "2026-05-21T17:00:00+09:00"
    }
  ]
}
```

##### (1) 최상위 필드 (entry_dict)

| 필드 | 타입 | AI 가독성 영역 | 비고 |
|---|---|---|---|
| `version` | int (root) | — | **2** — v3.4 운영 스키마. `drive_client.read_master_index()` 가 다른 버전 감지 시 `DriveSchemaMismatchError` (B-Type Pause, SYS §8.1). |
| `entries` | list[dict] (root) | — | 추가 전용 (append-only). 코드 변수는 `entry_dict_list` (SYS §2.1 `_list` 룰). |
| `id` | str | — | 8자 hex (날짜+해시) — v1 과 동일. |
| `date` | str | — | `YYYY-MM-DD` — v1 과 동일. |
| `trigger` | str | — | "VIX 27.4", "KOSDAQ -2.61%" 등 — v1 과 동일. |
| `market_state` | dict | **노출 (0.1초 판단)** | 시장 상태 압축 dict. 코드 변수는 `market_state_dict`. 하위 필드는 §5.1.2(2). |
| `context_tags_list` | list[str] | **노출 (0.1초 판단)** | 짧은 [주체_동사] 결합 태그 4~6개 (예: `"코스닥_급락"`, `"성장주_동반하락"`). 검색 점수화 1순위 (§4.3.2 단계 1). `chronicle_common.derive_context_tags(phrases_list, market_state_dict)` 헬퍼로 산출 (코드 PR 시 신설). |
| `action_preview` | str | **노출 (0.1초 판단)** | 행동 지침 한 줄 미리보기 — **최대 200자**. AI 가 본문 `.md` 를 열기 전 본 1줄만 보고 적합성을 판단한다. v1 의 `guideline_summary` 를 의미·역할상 대체하며, 마이그레이션 시 v1 `guideline_summary` 가 본 필드로 이관된다. `chronicle_common.parse_action_preview(ai_text)` 헬퍼가 본 룰을 강제 (코드 PR 시 v3.3 의 `parse_guideline_summary` 를 본 명으로 갱신, 슬라이싱 `[:200]`). |
| `phrases_list` | list[dict] | **내부 키 (보조)** | v3.2 의 `keyphrases` 와 동형 (`phrase` / `subject` / `action` / `tone`). **AI 가독성 영역에는 노출하지 않고**, `context_retriever._score_entry` 의 내부 의미 매칭 보조 키로만 사용 (§4.3.2 단계 6). |
| `embedding_vector` | list[float] \| null | **내부 키 (보조)** | **v3.5 선행 예약 필드**. v3.4 단계에서는 항상 `null`. v3.5 임베딩 RAG 도입 시 `text-embedding` 벡터를 채워 §4.3.2 단계 8 의 코사인 보너스를 활성화. v3.4 스키마 자체는 v3.5 에서 재변경하지 않는다. |
| `report_rel_path` | str | — | Drive 상대경로 — v1 과 동일. |
| `source` | str | — | `"chronicle"` (T-Day) 또는 `"backfill"` (소급) — v1 과 동일. |
| `reindexed_at` | str (옵션) | — | 기존 의미 유지 (재추출 시점). v3.4 코드 가동 후 신규 엔트리에는 미설정. |
| `migrated_at` | str (옵션) | — | v3.4 신설. `migrate_master_index_v2.py` 가 v1→v2 변환 시점을 KST ISO8601 로 기록. T-Day 신규 엔트리는 미설정. |

##### (2) `market_state_dict` 하위 필드 (0.1초 판단 영역)

| 필드 | 타입 | 비고 |
|---|---|---|
| `regime` | str (enum) | 표준 enum 8종 중 하나 — `PANIC_SELL` / `FEAR_EXTREME` / `FEAR_RISING` / `SHOCK_OPEN` / `BULLISH_RALLY` / `GREED_EXTREME` / `TECH_REBOUND` / `SIDEWAYS`. 정의는 §5.1.3. 검색 점수화 2~3순위 (§4.3.2 단계 2/3). |
| `regime_label` | str | 자유형 한국어 라벨 (예: `"강한 하락장 (Panic)"`). 슬랙·리포트 노출 + AI 가독성 보강. 매칭 점수에는 사용하지 않는다 (enum 만 점수화). |
| `main_actor` | str | 시장을 가장 강하게 움직인 주체 1문장 (예: `"외국인 대규모 매도"`). `chronicle_common.derive_main_actor(phrases_list)` 가 `phrases_list` 의 최빈 `subject` + 가장 강한 `action` 을 결합하여 산출 (코드 PR 시 신설). 검색 점수화 4순위 (§4.3.2 단계 4). |
| `sentiment` | str | 시장 심리 1문장 (예: `"위험 회피 극대화"`). `chronicle_common.derive_sentiment(phrases_list, dominant_tone)` 가 `phrases_list` 의 `dominant_tone` 과 매크로 강도를 결합한 사전형 라벨로 산출 (코드 PR 시 신설). 검색 점수화 5순위 (§4.3.2 단계 5). |

##### (3) AI 가독성 영역의 평탄화 (v1 → v2 비교)

v1 의 entry 는 `keyphrases` (구조체 list) + `keywords` (토큰 list) + `regime` (자유형) + `guideline_summary` 의 4개 필드가 평탄하게 나열되어 있어, AI 가 본문을 열기 전 검토해야 할 표면 정보가 분산되어 있었다. v2 는 다음과 같이 **AI 가독성 영역을 3개로 압축**한다.

| AI 가독 순서 | v2 필드 | 의도 |
|---|---|---|
| 1차 (필수) | `market_state.regime_label` + `main_actor` + `sentiment` | 시장 성격 / 주도 세력 / 심리를 한눈에 파악 |
| 2차 (자카드 매칭 핵심) | `context_tags_list` | 짧은 [주체_동사] 태그로 0.1초 매칭 |
| 3차 (지침 확정) | `action_preview` | 본문 열기 전 행동 결론 |

`phrases_list` / `embedding_vector` 는 **내부 검색 점수화에만 사용** 하며 컨텍스트 블록(`build_context_injection_block`) 출력에는 노출하지 않는다.

#### 5.1.3 표준 `market_state.regime` enum (8종, v3.4) — 매핑 규칙 및 인접 그룹

본 절은 `entry_dict.market_state.regime` 필드의 값을 정의한다. 자유형 한국어 라벨은 `market_state.regime_label` 에 별도 보존하여 슬랙·리포트 노출에 사용한다.

##### (1) enum 정의 및 1차 매크로 트리거

매크로 입력값은 `src/utils/macro_triggers.py` 의 임계값 상수와 정합한다 (SYS §9.1).

| 태그 | 의미 | 1차 매크로 트리거 (`macro_triggers` 임계값 기준) |
|---|---|---|
| `PANIC_SELL` | 패닉셀 (투매) | `vix >= VIX_CRITICAL`(30) **또는** `kospi_chg <= -3.0` **또는** `kosdaq_chg <= -3.0` |
| `FEAR_EXTREME` | 극단적 공포 | `vix >= 27` (`VIX_CRITICAL` 미만이고 `VIX_WARN` 초과 구간) |
| `FEAR_RISING` | 공포 확대 (경계) | `vix >= VIX_WARN`(25) 이고 `vix < 27` |
| `SHOCK_OPEN` | 갭 충격 (시초가 쇼크) | 시가 기준 `\|open_chg\| >= 2.0` (T-Day 전용 필드, 백필 입력에는 미적용) |
| `BULLISH_RALLY` | 상승 랠리 | `\|kospi_chg\| >= INDEX_SHOCK_PCT`(1.5) **이고** `kospi_chg > 0` **이고** `vix < 20` |
| `GREED_EXTREME` | 과열·탐욕 | `vix < 15` **이고** 5일 연속 양봉 또는 RSI 70+ 분포 다수 (보조 입력 필요) |
| `TECH_REBOUND` | 기술적 반등 | 직전 일자 `PANIC_SELL`/`FEAR_EXTREME`/`FEAR_RISING` 이후 `kospi_chg >= INDEX_SHOCK_PCT` 회복 |
| `SIDEWAYS` | 횡보 | 위 어느 조건도 충족하지 않는 평상 국면 (default) |

##### (2) 우선순위 (가장 강한 조건이 우선)

`PANIC_SELL` > `FEAR_EXTREME` > `FEAR_RISING` > `SHOCK_OPEN` > `BULLISH_RALLY` > `GREED_EXTREME` > `TECH_REBOUND` > `SIDEWAYS`

##### (3) 인접 그룹 매핑 (`REGIME_NEIGHBOR_MAP`, §4.3.2 단계 4-B 활용)

같은 강도 계열 내에서 검색 결과 부족 시 약한 가산점(+2.0)을 부여하기 위한 인접 매핑.

| 강도 계열 | 멤버 |
|---|---|
| 공포 계열 | `PANIC_SELL` / `FEAR_EXTREME` / `FEAR_RISING` |
| 회복 계열 | `TECH_REBOUND` / `BULLISH_RALLY` |
| 평상·과열 계열 | `SIDEWAYS` / `GREED_EXTREME` |
| 충격 계열 (방향 무관) | `SHOCK_OPEN` (자기 자신만 — 인접 없음) |

##### (4) 마이그레이션 시 v1 자유형 → enum 1차 매핑

`scripts/migrate_master_index_v2.py` 의 Scan 단계에서 v1 의 자유형 `regime` 문자열에 다음 키워드 사전을 순회 적용하여 1차 매핑한다 (가장 강한 매칭 1건만 채택). 매핑 결과는 v2 의 `market_state.regime` 에 채우고, v1 의 원본 자유형 문자열은 `market_state.regime_label` 에 손실 없이 보존한다.

| 키워드 (대소문자 무시, 공백 정규화 후 부분 일치) | 매핑 enum |
|---|---|
| `"극단"`, `"패닉"`, `"투매"`, `vix.*3\d` | `PANIC_SELL` |
| `"극단적 공포"`, `vix.*2[7-9]` | `FEAR_EXTREME` |
| `"공포 확대"`, `"경계"`, `vix.*25`, `vix.*26` | `FEAR_RISING` |
| `"기술적 반등"`, `"반등"` | `TECH_REBOUND` |
| `"랠리"`, `"상승"`, `"급등"` | `BULLISH_RALLY` |
| `"과열"`, `"탐욕"` | `GREED_EXTREME` |
| `"갭"`, `"시초가"`, `"쇼크"` | `SHOCK_OPEN` |
| `"보통"`, `"평상"`, `"횡보"`, (또는 매칭 실패) | `SIDEWAYS` |

결정 불가(다중 매칭 또는 0건) 항목은 AI 1회 호출로 보강한다 (§7 마이그레이션 4단계 표 참조).

### 5.2 backfill_state.json

```json
{
  "lookback_days": 60,
  "scanned_at": "2026-05-20T10:00:00+09:00",
  "queue": ["2026-03-12", "2026-03-18", "..."],
  "processed": ["2026-03-12"],
  "skipped": [
    {"date": "2026-03-15", "reason": "exists"},
    {"date": "2026-03-20", "reason": "error:Timeout"}
  ],
  "updated_at": "2026-05-20T10:32:11+09:00"
}
```

* `queue` 는 스캔 시점에 1회 등록, 이후 `processed`/`skipped` 로 이동.
* `reset_backfill` 호출 시 빈 상태(`{"lookback_days": 60, "queue": [], "processed": [], "skipped": []}`)로 덮어쓴다.
* 재실행 시 `queue` 중 `processed`/`skipped` 가 아닌 항목만 처리 → 중단/재개 안전.

### 5.3 pause_state.json / 로컬 pause flag

Drive `_system/pause_state.json` (참고용, 정상 상태에서는 비어 있음):

```json
{
  "paused": true,
  "reason": "Drive storage quota exceeded",
  "action_required": "공유 드라이브로 전환하거나 용량 확보 후 '완료' 입력",
  "since": "2026-05-19T08:42:11+09:00"
}
```

로컬 `.drive_pause_local.json` 도 동일 스키마. Drive 가 일시적으로 응답 불가일 때도 로컬 플래그가 보호한다.

---

## 6. 변경 이력 (v3.0 ~ v3.2.3)

> 본 절은 GEMINI.md (레거시 통합 기록) §3 의 v3.x 항목을 Chronicles 영역만 발췌하여 보존한다. 이전 항목은 어떤 경우에도 생략하지 않는다.

* **v3.0 업데이트 (Market Chronicles — Drive 실연동 완료, 구현율 85%):**
  * 목적: Gemini API 호출 단위 맥락 초기화 한계를 극복하는 **Google Drive 전용 외장 메모리** 아키텍처 확정 및 실서버 연결.
  * Cloud-Only: 로컬 저장소 미사용, 모든 크로니클/인덱스/임시 데이터를 Drive API 로만 관리.
  * 인증 체계 확립: 서비스 계정 storage quota 403 한계 발견 → **OAuth 데스크톱 앱** 방식으로 전환. 인증 모드(`oauth` / `delegation` / `shared_drive` / `sa_plain`) 자동 감지.
  * Headless OAuth: 서버(Ubuntu SSH, 브라우저 없음)에서 `--no-browser` 콘솔 인증으로 토큰 발급. JSON 유형(데스크톱 앱 vs 웹 앱) 사전 검증.
  * 자동 토큰 갱신: `oauth_token.py` 가 access token 만료 시 refresh, Testing 모드 만료(`invalid_grant`) 감지 및 재발급 안내. 봇 기동 시 자동 점검.
  * 폴더 구조 자동 생성: `Quant_Logs/MarketChronicles/{index, reports/YYYY/MM, temp/tech, _system}`, `app_data/` 자동 생성. `master_index.json` 초기화 완료.
  * Pause/Resume: 폴더 생성/OAuth 승인/용량 부족 등 사용자 개입 필요 시 로컬 플래그(`.drive_pause_local.json`)로 일시 정지 후 슬랙 안내 및 "완료" 응답 시 재검증/재개. Drive 재호출 무한 재귀 방지 로직 적용.
  * T-Day 크로니클: 코스피/코스닥 ±1.5% 또는 VIX 25 이상 시 장 마감 후 인과 분석/미래 행동 지침 도출 및 인덱스 색인.
  * Context Injection: AI 매매 판단 직전 유사 행동 지침 Top-3 를 [필수 준수 배경 지식] 으로 프롬프트 강제 주입 (`ai_logic.generate_text_with_chronicle`).
  * 출력 원칙: 금융 전문 용어 배제, 초보자용 일상 언어 리포트.
  * 구현 모듈: `src/memory/{drive_client, oauth_token, chronicle_writer, context_retriever, lifecycle}.py`; `scripts/{drive_oauth_setup, drive_oauth_refresh, drive_folder_bootstrap}.py`; 스케줄 15:35; 슬랙 `!크로니클`, `완료`.
  * 미완: 실제 T-Day 크로니클 작성 검증(트리거 충족 일자 대기), 키워드 검색 고도화(임베딩), `temp/tech` 자동 업로드 파이프라인.

* **v3.1 업데이트 (Market Chronicles 과거 데이터 소급 구축 — 실전 검증 완료, 구현율 98%):**
  * 목적: 가동 즉시 AI 판단에 주입 가능한 **'과거 대응 지침 DB'** 확보. T-Day 트리거 발생만을 기다리지 않고, 최근 60일치 변동성 장세를 사전 분석하여 마스터 인덱스를 두텁게 만든다.
  * 이벤트 데이 추출: `yfinance` 로 ^KS11/^KQ11/^VIX 일봉을 받아 등락률 ±1.5% 이상 또는 VIX 25 이상인 거래일 식별.
  * 2단계 동의 흐름: (1) `!백필스캔`(또는 `scripts/backfill_chronicles.py --scan-only`)로 후보 N건을 슬랙에 보고하고 대기. (2) 사용자가 `확인` 또는 `!백필실행` 입력 시 (3) 과거 시점 뉴스 수집·AI 사후 분석·리포트 저장·인덱스 색인 일괄 실행.
  * 사후 통찰 프롬프트: 과거 데이터 분석 시 '당시에는 몰랐지만 지금은 알게 된 사실' 을 포함하도록 프롬프트를 보강해 더욱 정교한 행동 지침 도출.
  * API Rate Limit 보호: 리포트 1건 생성마다 기본 3초 대기(설정 가능).
  * 상태 보존(중단 대비): 진행 상황을 Drive `MarketChronicles/_system/backfill_state.json` 에 기록(processed/skipped/queue). 중단되어도 다음 실행 시 미처리 일자만 이어서 처리.
  * 예외 처리: 한 일자 처리 중 오류 발생 시 해당 날짜를 `skipped` 로 기록하고 다음 날짜로 진행. 이미 같은 날짜의 크로니클이 존재하면 자동 스킵.
  * 구현 모듈: `src/memory/backfill.py`, `scripts/backfill_chronicles.py`, 슬랙 `!백필스캔`/`!백필실행`/`확인`, `MarketOrchestrator.backfill_scan`/`backfill_run`.
  * 운영 검증(2026-05-20, terminal 수동 실행): lookback=60, delay=3s, 결과 **완료 32 / 스킵 0 / 실패 0**. `master_index.json` 누적 엔트리 +32(`source="backfill"`). 향후 모든 AI 매매/시황 판단에 Context Injection 즉시 가동.

* **v3.2 업데이트 (Semantic Keyphrase Indexing & Retrieval — 적용 완료, 구현율 92%):**
  * 문제: 기존 `keywords` 는 정규식 `[가-힣]{2,}` 단순 추출이라 "외국인 매수" vs "외국인 매도", "금리 인상" vs "금리 인하" 같은 정반대 의미를 같다고 점수화하는 문맥 왜곡 위험.
  * 인덱싱 개선: `chronicle_writer._build_keyphrases` / `backfill._build_keyphrases` 가 Gemini 로 [주체+동사] 결합 구문(`subject`/`action`/`tone` 포함)을 1차 추출, 실패 시 `keyphrase_extractor._regex_extract` 가 사전 기반 폴백.
  * 검색 개선: `context_retriever._score_entry` 가 (1) 구문 자카드(+subject/action) (2) tone 다수결 일치 (3) regime 그룹 일치 (4) 최근성(30/90/180일) 의 5단계 가중치 합으로 점수화. 단어 토큰 매칭은 `min_score` 미달일 때만 폴백.
  * 결과 노출: `build_context_injection_block` 의 컨텍스트 블록에 매칭 점수와 핵심 구문 목록을 함께 표기하여 AI 가 어떤 과거 사례를 왜 참고하는지 명확히 인지.
  * 호환: 신규 엔트리는 `keyphrases` 와 `keywords` 둘 다 저장. 기존 v3.0/v3.1 엔트리(keywords 만 있음)는 폴백 경로로 그대로 검색됨 → 무중단 업그레이드.
  * 신규 모듈: `src/memory/keyphrase_extractor.py`.
  * 변경 파일: `src/memory/chronicle_writer.py`, `src/memory/backfill.py`, `src/memory/context_retriever.py`, `src/strategy/ai_logic.py`.

* **v3.2.1 업데이트 (Backfill 초기화·재인덱싱 운영 도구 — 적용 완료, 구현율 95%):**
  * 배경: v3.1 에서 이미 32건의 백필이 적재된 상태로 v3.2 의미 색인이 도입되었기 때문에, 기존 엔트리를 v3.2 포맷으로 안전하게 마이그레이션하거나 통째로 재구축할 운영 절차가 필요.
  * `reset_backfill(delete_reports=False)`: `master_index.json` 에서 `source="backfill"` 엔트리만 골라 제거하고 `backfill_state.json` 을 빈 상태로 덮어쓴다. `delete_reports=True` 이면 해당 엔트리들의 `.md` 리포트 파일까지 Drive 에서 삭제.
  * `reindex_keyphrases(delay_sec=3)`: 기존 `.md` 리포트를 읽어 `keyphrase_extractor.extract_keyphrases` 로 새 구문을 추출하고, 엔트리에 `keyphrases` + 파생 `keywords` + `reindexed_at` 을 채워넣는다. `.md` 보존 + AI 1회 호출만으로 v3.2 의미 색인 풀 적용.
  * 안전장치: T-Day 자동 작성 엔트리(`source != "backfill"`)는 두 함수 모두 절대 건드리지 않는다.
  * 인터페이스:
    - CLI: `python scripts/backfill_chronicles.py --reset [--purge-reports] [--run]` / `--reindex --delay N`
    - 슬랙: `!백필초기화 [purge]` / `!백필재인덱싱 [건당대기초]`
    - Orchestrator: `MarketOrchestrator.backfill_reset(delete_reports=False)` / `backfill_reindex(delay_sec=3)`
  * 변경 파일: `src/memory/backfill.py`, `scripts/backfill_chronicles.py`, `src/utils/slack_interface.py`, `src/execution/orchestrator.py`.

* **v3.2.3 업데이트 (Backfill 운영 핫픽스 + 잔여 정리·진단 명령 — 적용 완료, 구현율 97%):**
  * 운영 보고된 버그(2026-05-20): `--reset --purge-reports` 실행 중 `HttpError 404 File not found: {'mimeType': ..., 'id': ..., 'name': ...}` 발생. 원인은 `drive_client._find_file_in_parent` 가 file ID **문자열** 이 아닌 메타데이터 **dict 전체** 를 반환하는데, `backfill._delete_file_at_rel_path` 가 그 dict 를 그대로 `delete_file_by_id` 에 전달하여 요청 URL 이 깨진 것.
  * 수정: `_delete_file_at_rel_path` 가 반환값을 dict 로 인지하여 `.get("id")` 만 추출하도록 정정. 404/notFound 응답은 "이미 삭제됨" 으로 간주하여 idempotent 동작.
  * 신규 `purge_leftover_backfill_reports(dry_run=False)` (이전 명칭: `purge_orphan_backfill_reports`): 위 버그로 인덱스는 비워졌지만 `.md` 파일이 남아 있는 잔여(leftover) 상태를 정리하기 위한 보조 명령. `MarketChronicles/reports/` 트리를 재귀 스캔하여 헤더 첫 줄에 `Market Chronicle (Backfill)` 표식이 있는 `.md` 만 식별하고, master_index 의 어떤 엔트리에도 등록되지 않은 항목만 실제 삭제. T-Day 자동 리포트(헤더 `# Market Chronicle YYYY-MM-DD`)는 표식 불일치로 자동 보호.
  * 신규 `diagnose_reports()` (읽기 전용 진단): "잔여 정리 명령이 왜 0건만 보고하나" 류의 운영 의문을 즉답한다. reports 트리의 .md 총 갯수 / 인덱스 등록·미등록 분포 / 헤더 표식별 분포(백필 vs T-Day) / 잔여 정리 대상 갯수 / master_index 의 백필·T-Day 분포를 한 번에 출력. 파일을 절대 수정·삭제하지 않는다.
  * 명칭 정정: 사용자 피드백에 따라 "고아(orphan)" 표현을 "잔여(leftover)" 로 변경. 기존 명칭은 deprecated alias 로 호환 유지(`purge_orphan_backfill_reports` 함수, `--purge-orphan-reports` 플래그, `!백필고아청소` 슬랙 명령, `backfill_purge_orphans()` 오케스트레이터 메서드 모두 새 명칭과 동일 동작).
  * 인터페이스:
    - CLI: `python scripts/backfill_chronicles.py --diagnose-reports` (진단) / `--purge-leftover-reports [--dry-run]` (정리)
    - 슬랙: `!백필상태` (진단) / `!백필잔여정리 [dry]` (정리)
    - Orchestrator: `MarketOrchestrator.backfill_diagnose()` / `backfill_purge_leftover(dry_run=False)`
  * 변경 파일: `src/memory/backfill.py`, `scripts/backfill_chronicles.py`, `src/utils/slack_interface.py`, `src/execution/orchestrator.py`.

* **v3.3 업데이트 (Chronicles 영역 — 문서 분할 + 공통 헬퍼 통합, 구현율 96%)**:
  * **문서 분할 적용**: v3.0~v3.2.3 의 비즈니스 로직·데이터 스키마·엣지 케이스를 본 `GEMINI_DETAIL_CHRONICLES.md` 로 이관. 시스템 골격·API 명세·인프라·전역 에러 정책은 `GEMINI_SYS.md` 로 이관. `master_index.json` 구조 개편은 본 사이클 작업 범위에서 제외 (기존 스키마 유지).
  * **`chronicle_common.py` 신설 (구현 완료)**: `report_rel_path` / `parse_guideline_summary` / `build_keyphrases(ai_text, *, vix=0, kospi_chg=0, kosdaq_chg=0, max_phrases=12, ai_enabled=True, hard_limit=15)` / `append_phrase_unique(phrase_list, phrase, subject, action, tone)` / `make_emitter(notify_fn)` 5종 헬퍼 단일화. `chronicle_writer._report_rel_path` + `backfill._report_rel_path`, `chronicle_writer._parse_guideline_summary` + `backfill._parse_guideline_summary`, `chronicle_writer._build_keyphrases` + `backfill._build_keyphrases` (입력 키 정규화 후), 양 모듈의 `_append` 클로저, `backfill.py` 내 `_emit` 클로저 6회, `context_retriever._append` 모두 단일 진입점으로 통합.
  * **`macro_triggers.py` 신설 + 트리거 통합 (구현 완료)**: `chronicle_writer.should_write_chronicle` 와 `backfill._trigger_reason` 의 임계값(VIX>=25, 등락률±1.5%)을 `evaluate_chronicle_trigger(vix, kospi_chg, kosdaq_chg) -> (bool, str)` 단일 함수로 일원화. 호출부(`chronicle_writer`, `backfill.scan_event_days`, `context_retriever.extract_market_context`)는 정규화된 키워드 인자만 전달. `_safe_float` 도 단일 위치로 통합.
  * **`drive_client` 캡슐화 강화 (구현 완료)**: 공개 헬퍼 4종 신설 — `delete_file_relative(rel_path)`, `read_master_index()`, `append_index_entry(entry_dict)`, `write_master_index(index_dict)`. `backfill._delete_file_at_rel_path` 는 `delete_file_relative` 의 호환 wrapper 로 축소(private 함수 직접 호출 제거). master_index read 패턴 6곳 + append 2곳 + full overwrite 2곳을 모두 신규 헬퍼로 단일화. v3.2.3 핫픽스로 처리되던 `HttpError 404` 버그 패턴이 구조적으로 재발 불가능.
  * **`_legacy_keyword_view` wrapper 폐기 (구현 완료)**: `chronicle_writer._legacy_keyword_view` 와 `backfill._legacy_keyword_view` 의 wrapper 자체를 폐기. 호출부는 `keyphrase_extractor.derive_tokens(phrases)[:20]` 를 직접 사용.
  * **슬랙 라우팅 정합 (Path B 복원, 구현 완료)**: 모든 백필 슬랙 핸들러(`cmd_backfill_scan`/`run`/`reset`/`diagnose`/`purge_leftover`/`reindex`/`confirm`)가 `orchestrator.backfill_*` 게이트웨이를 반드시 경유하도록 복원. `slack_interface.register_slack_handlers(app, kis, config, orchestrator)` 시그니처에 `orchestrator` 추가. `cmd_backfill_confirm` 을 위해 `orchestrator.backfill_get_state` 게이트웨이 신설.
  * **변경 파일**: `src/memory/chronicle_common.py`(신설), `src/memory/{chronicle_writer,backfill,context_retriever,drive_client,oauth_token,lifecycle}.py`, `src/utils/slack_interface.py`, `src/execution/orchestrator.py`, `main.py`.
  * **이연**: keyphrases·기존 keywords 필드 호환은 유지하면서, `record_trade` 의 mode_type 명시 인자화 / `OrderRequest` dataclass 도입 / KIS `_call_kis` 백오프 정책은 §9 의 별건 PR 로 분리.

* **v3.4 업데이트 (Master Index 구조 최적화 — 사양 정의 완료, 구현 0%)**:
  * **목적**: 단순 나열형 구조(`keyphrases` + `keywords` 두 필드 + 자유형 `regime`)를 **상황 매칭형(Scenario Matching) 0.1초 판단 압축 구조** 로 재설계하여 (1) AI 가 리포트 본문 `.md` 를 열기 전 `market_state` + `context_tags_list` + `action_preview` 만 보고 0.1초 만에 적합성을 판단하고 (2) v3.5 임베딩 RAG 의 벡터 컨테이너(`embedding_vector`)를 미리 예약하며 (3) `keywords` 폐기로 노이즈 매칭을 제거한다.
  * **스키마 v1 → v2 개편 (SYS §2.1 명명 규칙 준수)**: 본 문서 §5.1.2 정의. `master_index.json` 의 `version` 키를 `1` → `2` 로 증가. v1 의 `keyphrases` + `keywords` + 자유형 `regime` + `guideline_summary` 4개 분산 필드를 **entry 최상위에서 평탄화** — `market_state`(dict) + `context_tags_list`(list[str]) + `action_preview`(str) + `phrases_list`(list[dict], 보조) + `embedding_vector`(예약). 이미지 §5.1.2 의 "0.1초 판단" 원칙을 충실히 반영.
  * **`market_state` dict 도입 (4-필드)**: `regime`(enum) + `regime_label`(자유형 한국어) + `main_actor`(주도 세력 1문장) + `sentiment`(시장 심리 1문장). AI 가독성 영역의 1차 노출 정보를 시장 성격·주도 세력·심리 3축으로 압축. 본 문서 §5.1.2(2) 정의.
  * **`context_tags_list` 도입 ([주체_동사] 결합 태그)**: 짧은 결합 태그 4~6개 (예: `"코스닥_급락"`, `"성장주_동반하락"`, `"디스카운트_지속"`, `"정부_대응_미흡"`). 검색 점수화 1순위(§4.3.2 단계 1-A, +10.0). 짧은 토큰 set 자카드는 phrase 토큰 자카드 대비 약 5배 빠른 매칭 단위로 "0.1초 판단" 의 핵심.
  * **`action_preview` 도입 (200자 룰)**: v1 의 `guideline_summary` 를 의미·역할상 대체. AI 가 본문 `.md` 를 열기 전 본 한 줄만 보고 행동 결론을 확인. `chronicle_common.parse_action_preview(ai_text)` 가 본 룰(`[:200]`)을 강제 (코드 PR 시 v3.3 의 `parse_guideline_summary` 를 본 명으로 갱신). 마이그레이션 시 v1 `guideline_summary` 가 그대로 본 필드로 이관.
  * **표준 `market_state.regime` enum 8종 도입**: 본 문서 §5.1.3 정의 — `PANIC_SELL` / `FEAR_EXTREME` / `FEAR_RISING` / `SHOCK_OPEN` / `BULLISH_RALLY` / `GREED_EXTREME` / `TECH_REBOUND` / `SIDEWAYS`. 자유형 한국어 라벨은 `market_state.regime_label` 에 보존. 매칭 점수(§4.3.2 단계 2/3)는 enum 정확 일치(+5.0) / 인접 그룹 매핑(+2.0, `REGIME_NEIGHBOR_MAP`) 으로만 계산.
  * **`phrases_list` 보조 보존**: v3.2 의 4튜플(`phrase`/`subject`/`action`/`tone`) 구조를 entry 최상위에 보존하되, **AI 가독성 영역에는 노출하지 않고** `context_retriever._score_entry` 의 내부 의미 매칭 보조 키로만 사용 (§4.3.2 단계 6-A/6-B, `context_tags_list` 매칭 임계 미달 시에만 발동). 의미 매칭 정확도는 유지하면서 표면 가독성은 압축.
  * **`keywords` 폐기**: v2 엔트리에서 완전 제거. v1 엔트리의 `keywords` 폴백 경로(`context_retriever._score_entry` 의 단어 토큰 폴백 +0.5×overlap)는 v3.4 코드 가동 시점에 함께 폐기. 마이그레이션 시 v1 엔트리의 `keywords` 는 손실 없이 `context_tags_list` 산출 입력으로 활용된다.
  * **`embedding_vector` 선행 예약**: v3.4 단계에서는 항상 `null`. v3.5 임베딩 RAG 도입 시 `text-embedding` 모델의 벡터를 채워 §4.3.2 단계 8 에서 하이브리드 결합. v3.4 스키마 자체는 v3.5 에서 재변경하지 않는다(`version=2` 유지).
  * **검색 로직 갱신 (§4.3.2)**: `context_retriever._score_entry` 를 8단계 가중치로 재설계. 단계 1(`context_tags_list` 자카드, +10/+6/+3) → 단계 2(`regime` 정확, +5) → 단계 3(`regime` 인접, +2) → 단계 4(`main_actor` 부분 일치, +1.5) → 단계 5(`sentiment` 일치, +1.5) → 단계 6(`phrases_list` 자카드 보조, +4/+2) → 단계 7(최근성, +2/+1/+0.3) → 단계 8(`embedding_vector` 코사인, v3.5 예약). `min_score` 기본값 2.0 → 3.0 상향.
  * **DRY 활용 (SYS §9.1 공통 헬퍼 재사용)**:
    - `chronicle_common.parse_action_preview(ai_text)` → `action_preview` 200자 룰 강제 (v3.3 의 `parse_guideline_summary` 갱신)
    - `chronicle_common.build_keyphrases(ai_text, *, vix, kospi_chg, kosdaq_chg)` → `phrases_list` 산출 (기존 헬퍼 그대로 재사용)
    - `chronicle_common.derive_context_tags(phrases_list, market_state_dict)` → `context_tags_list` 산출 (코드 PR 시 신설, `keyphrase_extractor.derive_tokens` 결과를 [subject_action] 결합 형태로 압축)
    - `chronicle_common.derive_market_state(phrases_list, *, vix, kospi_chg, kosdaq_chg)` → `market_state` dict 산출 (코드 PR 시 신설, 내부에서 `macro_triggers.resolve_regime` 호출 + `phrases_list` 의 최빈 subject 로 `main_actor` 도출 + `dominant_tone` 으로 `sentiment` 라벨 도출)
    - `macro_triggers.evaluate_chronicle_trigger(vix, kospi_chg, kosdaq_chg)` → 트리거 사유 산출 (기존)
    - `macro_triggers.resolve_regime(vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None)` → 표준 `regime` enum 산출 (코드 PR 시 신설) + 인접 그룹 상수 `REGIME_NEIGHBOR_MAP`
    - `jsonio.read_local_json` / `write_local_json` → 마이그레이션 스크립트의 로컬 백업 I/O (기존)
    - `scripts/_common.setup_script_path` / `load_env_file` / `print_flush` → 마이그레이션 스크립트 부트스트랩 (기존)
  * **운영 마이그레이션 (`scripts/migrate_master_index_v2.py`)**: 본 문서 §7 신규 엣지 케이스 표 참조. 4단계 (**Scan → Backup → AI 보강 → Apply**). `--dry-run` 으로 변환 결과 stdout 출력 → 사용자 검토 → `--apply` 로 실제 덮어쓰기. `master_index.json` 직전 백업을 `MarketChronicles/_system/backups/master_index_v1_<KST_YYYYMMDD_HHMMSS>.json` 으로 저장.
  * **B-Type Pause 신규 시나리오 (SYS §8.1 명시)**: 봇 기동 또는 `drive_client.read_master_index()` 호출 시 `version=1` 감지 → `DriveSchemaMismatchError` (B-Type) → 슬랙 안내 ("`master_index.json` v1 감지. `python scripts/migrate_master_index_v2.py --dry-run` 으로 변환 결과 검토 후 `--apply` 실행, 완료 후 `완료` 응답."). 기본 정책은 자동 마이그레이션을 수행하지 않는다 (데이터 손실 방지). **선택적 자동화 옵션** — `.env AUTO_MIGRATE_V2=1` 이면 Pause 대신 `scripts.migrate_master_index_v2.migrate_in_process(ai_enabled=True, delay_sec=3)` 진입점을 자동 호출 (운영자가 데이터 변경 위험을 명시적으로 수용한 경우 한정). 자동 모드도 §7 의 4단계(Scan/Backup/AI 보강/Apply)를 동일하게 거치며 종료 후 결과 요약을 슬랙으로 발송한다.
  * **본 사이클 산출물 (Step 1, 사양 정의)**: SYS `§5 v3.4 / §6.3.4 / §7.5 / §8.1 / §10 #5-A`, DETAIL `§1 헤더 / §4.3.2 / §4.4 / §5.1.2 / §5.1.3 / §6 v3.4 / §7 신규 엣지 / §9 임베딩 RAG → v3.5 격하`. **코드 변경 없음**.
  * **이연 (Step 2, 코드 PR)**: (1) `drive_client.read_master_index()` default fallback `{"version": 2, "entries": []}` 갱신 + 신규 예외 `DriveSchemaMismatchError`(B-Type) 발생 로직 + `version` 검증 가드. (2) `chronicle_writer` / `backfill` 의 색인 적재 로직 — `market_state` + `context_tags_list` + `action_preview` 산출 + 표준 `regime` enum 산출(`macro_triggers.resolve_regime`) + `phrases_list` 보조 보존. (3) `chronicle_common.{derive_context_tags, derive_market_state, parse_action_preview}` 신설. (4) `macro_triggers.resolve_regime(...)` + `REGIME_NEIGHBOR_MAP` 신설. (5) `context_retriever._score_entry` 점수화 8단계 재설계(§4.3.2) + `extract_market_context` 산출 필드 4종 갱신 + `build_context_injection_block` 출력 3블록 압축. (6) 신규 운영 스크립트 `scripts/migrate_master_index_v2.py` (4단계 Scan/Backup/AI 보강/Apply). (7) Step 3: 구현 완료 후 본 문서 §8 (본 사이클 리팩토링 정합) 에 실제 시그니처·변경 파일 일람을 Post-Update 반영.

---

## 7. 엣지 케이스 시나리오

본 절은 운영 중 실제 발생 가능한 시나리오와 시스템 응답을 명문화한다.

| 시나리오 | 트리거 | 시스템 응답 |
|---|---|---|
| **OAuth 토큰 만료 (Testing 모드 7일)** | `invalid_grant` 응답 | `oauth_token.refresh_oauth_token` 가 즉시 감지 → 슬랙 "토큰 재발급 필요" 안내 → Pause 전환. 사용자는 `python scripts/drive_oauth_setup.py --no-browser` 로 재발급 후 `완료` 입력. |
| **Drive storage quota 초과** | API 403 (`storageQuotaExceeded`) | `drive_client._raise_storage_quota_help` 발생 → Pause 전환 + 슬랙 안내 (공유 드라이브 전환 또는 용량 확보). |
| **폴더 누락 (사용자 수동 삭제 등)** | `_ensure_chronicle_structure` 실패 | 폴더 재생성 시도 → 실패 시 Pause. |
| **백필 도중 네트워크 끊김** | yfinance/news_crawler 예외 | 해당 일자 `skipped(reason="error:<msg>")` 기록 후 다음 일자로 진행. 재실행 시 `queue` 잔여만 처리. |
| **백필 도중 Drive Pause 발생** | `DrivePausedError` | `run_backfill` 즉시 중단, 슬랙 안내. 사용자 `완료` 응답 후 재실행. |
| **AI 응답 JSON 파싱 실패** | `_try_parse_json_array` 실패 | `_regex_extract` 폴백 — 운영 단절 없이 keyphrase 추출 계속. |
| **`--reset --purge-reports` 일부 .md 삭제 실패** | `HttpError 404` 등 | v3.2.3 핫픽스로 idempotent 처리. 잔여(leftover) 가 남으면 `!백필잔여정리` 로 후처리. |
| **동일 날짜 중복 작성 시도** | `reports/YYYY/MM/YYYY-MM-DD_chronicle.md` 이미 존재 | `skipped(reason="exists")` 기록 후 다음. |
| **T-Day 엔트리에 잘못된 `--reset` 호출** | `reset_backfill(...)` | `source != "backfill"` 엔트리는 자동 보호 — 어떤 모드에서도 삭제·수정 불가. |
| **유사 지침 검색 결과 0건 (`min_score` 미달)** | `search_similar_guidelines` 결과 빈 리스트 | `build_context_injection_block` 이 빈 문자열 반환 → AI 호출은 정상 진행 (Chronicles 미주입). |
| **백필 32건 적재 후 v3.2 도입** | v3.1 → v3.2 마이그레이션 시점 | `--reindex` 로 AI 1회 호출씩 keyphrases 만 추가. `.md` 와 인덱스 모두 보존. |
| **v3.4 코드 가동 시 v1 인덱스 감지** | `read_master_index()` 가 `version=1` 인지 | 기본 정책: `DriveSchemaMismatchError` (B-Type, SYS §8.1) → Pause + 슬랙 안내. 사용자가 `python scripts/migrate_master_index_v2.py --dry-run` 으로 변환 결과 검토 후 `--apply` 실행, 완료 후 `완료` 응답. **선택적 자동화**: `.env AUTO_MIGRATE_V2=1` 이면 `read_master_index()` 가 Pause 대신 `migrate_master_index_v2.migrate_in_process(...)` 진입점을 즉시 호출하여 자동 변환 수행 + 결과 요약을 슬랙으로 발송 (운영자가 데이터 변경 위험을 명시적으로 수용한 경우 한정). |
| **마이그레이션 도중 AI 호출 실패** | `context_tags_list` / `main_actor` / `sentiment` 보강용 AI 호출 타임아웃·할당량 초과 | 해당 엔트리는 정규식 폴백으로 산출: `context_tags_list` 는 v1 `keywords` 를 `_` 결합 토큰으로 단순 변환, `main_actor` 는 v1 `keyphrases` 의 최빈 `subject` 1건, `sentiment` 는 v1 `regime` 자유형에서 추출. `market_state.regime` enum 매핑은 §5.1.3(4) 의 키워드 1차 매핑 결과를 사용하고, 결정 불가 시 `SIDEWAYS` 로 안전 폴백 후 `regime_label` 에 원본 자유형 문자열 보존. 운영 보고 후 수동 보정 가능. |
| **마이그레이션 도중 Drive 일시 장애** | `_apply_with_retry` 또는 `write_master_index` 호출 시 5xx/Timeout | `--apply` 단계는 in-memory 변환을 완료한 뒤 백업 → 단일 `write_master_index(new_index_dict)` 한 번만 호출하므로 부분 적용이 발생하지 않는다. write 실패 시 백업 파일은 그대로 보존되며, 사용자는 동일 명령을 재실행하기만 하면 된다 (Idempotent). |
| **`--dry-run` 결과 검토 거부** | 사용자가 `--apply` 미실행 | v3.4 코드 가동은 계속 B-Type Pause 상태 유지. v1 인덱스는 그대로 보존되어 데이터 손실 0. v3.4 코드를 임시 비활성화하고 v3.3.1 로 롤백하려면 `git checkout v3.3.1` 후 봇 재기동. |
| **표준 enum 매핑 충돌 (다중 매칭)** | v1 자유형 `regime` 에 여러 키워드 동시 포함 (예: `"공포 확대 + 갭 충격"`) | §5.1.3(2) 우선순위에 따라 가장 강한 enum 채택 (예: `FEAR_RISING` > `SHOCK_OPEN` → `FEAR_RISING`). 다중 매칭 사례는 `--dry-run` 보고에 별도 섹션으로 노출하여 사용자가 검토할 수 있도록 한다. |

##### 마이그레이션 스크립트 4단계 작동 명세 (`scripts/migrate_master_index_v2.py`)

| 단계 | 입력 | 처리 | 출력 |
|---|---|---|---|
| **1. Scan** | `drive_client.read_master_index()` (현재 `version=1`) | 모든 엔트리의 `id` / `date` / `keyphrases` / `keywords` / `regime`(자유형) / `guideline_summary` / `report_rel_path` / `trigger` / `source` 추출. §5.1.3(4) 키워드 사전을 적용해 `market_state.regime` enum 1차 매핑 시도. 다중 매칭·매핑 실패 항목은 별도 큐로 분리. 동시에 v1 `keyphrases` 가 보유된 엔트리는 정규식 폴백으로 `context_tags_list`/`main_actor`/`sentiment` 도 1차 산출. | 보고: 전체 엔트리 수, 1차 매핑 성공 수, 다중 매칭 수, 매핑 실패 수, AI 보강 대상 수. `--dry-run` 이면 본 단계까지의 결과를 stdout 에 출력하고 종료. |
| **2. Backup** | `--apply` 진입 시 현재 `master_index.json` 의 전체 dict | KST 타임스탬프 (`kst_strftime("%Y%m%d_%H%M%S")`) 를 사용해 `MarketChronicles/_system/backups/master_index_v1_<TS>.json` 으로 복사. Drive 쓰기는 `drive_client.write_json_relative` 한 번. | 백업 파일 생성 확인 + 백업 경로 stdout 보고. 실패 시 즉시 `OperationalError` 발생 후 중단. |
| **3. AI 보강** | 1차 매핑 결정 불가 항목 + `keywords` 만 보유한 v3.0/v3.1 엔트리 (v3.2 `keyphrases` 미보유) | 각 엔트리에 대해 AI 1회 호출 (`gemini-pro` 기본 모델, max_phrases=12, ai_enabled=True). `chronicle_common.build_keyphrases(...)` 를 재사용하여 `phrases_list` 생성. 이어서 `chronicle_common.derive_market_state(phrases_list, *, vix, kospi_chg, kosdaq_chg)` 로 `market_state` 4필드(`regime`/`regime_label`/`main_actor`/`sentiment`) 산출 + `chronicle_common.derive_context_tags(phrases_list, market_state_dict)` 로 `context_tags_list` 산출. `regime` 결정 불가 항목은 본 단계에서 AI 에게 "다음 본문은 §5.1.3(1) 의 8종 enum 중 어디에 해당하는가?" 단답형으로 추론. AI 호출 실패 시 §7 표의 정규식 폴백. 모든 AI 호출 사이 `delay_sec=3` 기본 (인자 override). | 보강된 v2 엔트리 in-memory dict 목록. 진행률 stdout 출력. |
| **4. Apply** | Scan + AI 보강 결과 + 변경 없는 엔트리(이미 v3.2 `keyphrases` 보유 시 본 헬퍼만 재실행) | 모든 엔트리를 v2 스키마로 변환 — entry 최상위 평탄화: `market_state` / `context_tags_list` / `action_preview` (v1 `guideline_summary` 200자 슬라이싱 + `parse_action_preview`) / `phrases_list` (보조) / `embedding_vector=null` / `report_rel_path` / `source` / `migrated_at = kst_iso_now()`. 최종 `{"version": 2, "entries": new_entry_dict_list}` 를 `drive_client.write_master_index(...)` 단일 호출로 덮어쓰기. | 적용 결과 보고 — 처리 건수, AI 호출 횟수, `regime` 분포 카운트, `context_tags_list` 평균 태그 수. 종료 코드 0. |

스크립트 시그니처:

```python
python scripts/migrate_master_index_v2.py [--dry-run | --apply]
                                          [--delay-sec N (default 3)]
                                          [--no-ai (AI 보강 단계 스킵)]
                                          [--limit N (테스트용, 상위 N건만 처리)]
```

`--dry-run` 과 `--apply` 는 상호 배타. 둘 다 없으면 안전을 위해 `--dry-run` 으로 강제 (사용자가 명시적으로 `--apply` 를 지정해야 실 적용).

---

## 8. 본 사이클 리팩토링 정합 (Post-Update 반영, 구현율 100%)

본 작업 사이클에서 적용된 리팩토링이 Chronicles 영역에 미치는 영향을 명시한다. 실제 코드 작성을 완료한 후 Post-Update 단계에서 실제 시그니처·통합 범위·변경 파일 일람을 본 절에 반영하였다. v3.4 적용 PR 의 변경 일람은 §8.6 참조.

### 8.1 신규 모듈: `src/memory/chronicle_common.py` (B-1)

| 함수 | 시그니처 | 통합 대상 |
|---|---|---|
| `report_rel_path(date_str)` | `(str) -> str` | `chronicle_writer._report_rel_path`, `backfill._report_rel_path` |
| `parse_guideline_summary(ai_text)` | `(str) -> str` | `chronicle_writer._parse_guideline_summary`, `backfill._parse_guideline_summary` |
| `build_keyphrases(ai_text, *, vix, kospi_chg, kosdaq_chg)` | `(str, **float) -> list[dict]` | `chronicle_writer._build_keyphrases`, `backfill._build_keyphrases` (입력 키 정규화) |
| `append_phrase_unique(phrase_list, phrase, subject, action, tone)` | `(list, str, str, str, str) -> None` | 양 모듈의 `_append` 클로저 |
| `make_emitter(notify_fn)` | `(callable | None) -> callable` | `backfill.py` 내 `_emit` 클로저 6회 |

`_legacy_keyword_view` wrapper 는 폐기하고, 호출부에서 `keyphrase_extractor.derive_tokens(phrases)[:20]` 을 직접 호출한다.

### 8.2 신규 모듈: `src/utils/macro_triggers.py` (B-2)

| 상수 / 함수 | 정의 |
|---|---|
| `VIX_CRITICAL` | `30` (매크로 셧다운 Level 1) |
| `VIX_WARN` | `25` (T-Day 트리거, 매크로 셧다운 Level 2) |
| `INDEX_SHOCK_PCT` | `1.5` (T-Day 트리거 등락률 임계값) |
| `evaluate_chronicle_trigger(vix, kospi_chg, kosdaq_chg)` | `-> (bool, reason_str)` — `chronicle_writer.should_write_chronicle` + `backfill._trigger_reason` 통합 |
| `evaluate_macro_shutdown_level(vix, wti, treasury_yield)` | `-> int (0/1/2)` — 매크로 셧다운 단계 (시스템 골격, SYS 에서도 참조) |

### 8.3 `drive_client.py` 캡슐화 강화 (B-5)

| 신규 공개 헬퍼 | 흡수 대상 |
|---|---|
| `delete_file_relative(rel_path)` | `backfill._delete_file_at_rel_path` (private 함수 직접 호출 제거) |
| `read_master_index()` | `chronicle_writer`, `backfill` 6곳의 read 패턴 |
| `append_index_entry(entry_dict)` | 동상의 read→append→write 패턴 |

### 8.4 슬랙 라우팅 복원 (B-6, q1=Path B)

`slack_interface.cmd_backfill_*` 모든 핸들러가 `src.memory.backfill` 직접 import 를 중단하고 `orchestrator.backfill_*` 게이트웨이만 호출하도록 변경. 게이트웨이 메서드 7종 모두 호출 경로 복원.

### 8.5 영향받는 기존 구현

| 파일 | 변경 요약 |
|---|---|
| `src/memory/chronicle_writer.py` | `_report_rel_path`, `_parse_guideline_summary`, `_build_keyphrases`, `_legacy_keyword_view` 제거 → `chronicle_common` 호출 |
| `src/memory/backfill.py` | 위와 동일 + `_emit` 6회 통합 + `_delete_file_at_rel_path` 단순화 + 매크로 트리거 통합 + `_legacy_keyword_view` 제거 |
| `src/memory/context_retriever.py` | `_append` 클로저 통합, 매크로 트리거 임계값을 `macro_triggers` 에서 참조 |
| `src/utils/slack_interface.py` | `cmd_backfill_*` 핸들러가 `orchestrator.backfill_*` 호출로 일원화 |
| `src/execution/orchestrator.py` | `backfill_purge_orphans` alias 유지 (외부 호환), 본체는 `backfill_purge_leftover` |

### 8.6 v3.4 Master Index v2 적용 PR (Post-Update 동기화)

본 절은 v3.4 코드 적용 PR (SYS §10 #5-A) 의 실제 구현 결과를 명시한다.

#### (1) 신규/갱신 헬퍼 시그니처

| 모듈 | 항목 | 시그니처 / 정의 |
|---|---|---|
| `src/utils/macro_triggers.py` | `REGIME_PANIC_SELL` ~ `REGIME_SIDEWAYS` 상수 + `REGIME_ENUM_SET` (set) + `REGIME_NEIGHBOR_MAP` (dict[str, list[str]]) | DETAIL §5.1.3(1)/(3) 정의를 코드 상수화 |
| `src/utils/macro_triggers.py` | `resolve_regime(vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None) -> str` | DETAIL §5.1.3(2) 우선순위로 enum 1종 결정 |
| `src/utils/macro_triggers.py` | `map_regime_from_text(free_text) -> str \| None` | v1 자유형 → enum 1차 매핑 (`REGIME_KEYWORD_PRIORITY_LIST` 사전) |
| `src/memory/chronicle_common.py` | `parse_action_preview(ai_text) -> str` | v1 의 `parse_guideline_summary` 갱신, `[:200]` 슬라이싱 (호환 alias 유지) |
| `src/memory/chronicle_common.py` | `derive_market_state(phrases_list, *, vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None, regime_label_override=None) -> dict` | `market_state` dict (regime/regime_label/main_actor/sentiment) 산출 |
| `src/memory/chronicle_common.py` | `derive_context_tags(phrases_list, market_state_dict, max_tags=6) -> list[str]` | [주체_동사] 결합 짧은 태그 산출 (regime 표면 태그 1개 자동 추가) |
| `src/memory/drive_client.py` | `class DriveSchemaMismatchError(Exception)` | B-Type 예외 (SYS §8.1 v3.4 신규). `detected_version` / `expected_version` / `action_required` 보유 |
| `src/memory/drive_client.py` | `MASTER_INDEX_EXPECTED_VERSION = 2`, `_is_auto_migrate_enabled()` 모듈 함수 | v3.4 기대 버전 상수 + `AUTO_MIGRATE_V2` 평가 |
| `src/memory/drive_client.py` | `read_master_index(*, allow_auto_migrate=True) -> dict` | version != 2 감지 시 자동 마이그레이션 또는 `pause(...) + raise` |
| `src/memory/context_retriever.py` | `extract_market_context(macro, news_snippets=None) -> dict` | v2 쿼리 dict 반환 (`context_tags_list` / `regime` / `main_actor_keyword` / `sentiment` / `phrases_list`) |
| `src/memory/context_retriever.py` | `_score_entry(entry, query) -> float` | DETAIL §4.3.2 의 8단계 가중치 합 |
| `src/memory/context_retriever.py` | `search_similar_guidelines(query_context_tags_list=None, query_regime=None, *, query_main_actor_keyword="", query_sentiment="", query_phrases_list=None, top_n=3, min_score=3.0, query_dict=None) -> list[dict]` | `min_score` 기본 2.0 → 3.0 상향 |
| `src/memory/context_retriever.py` | `build_context_injection_block(query, top_n=3) -> str` | 3블록(헤더/태그/지침) 압축 출력. dict 또는 (phrases, regime) 튜플 모두 수용 |
| `scripts/migrate_master_index_v2.py` | `migrate_in_process(*, ai_enabled=True, delay_sec=3, limit=None, dry_run=False, emit=print_flush) -> dict` | 4단계(Scan/Backup/AI 보강/Apply) 진입점 |
| `scripts/migrate_master_index_v2.py` | `main()` CLI | `--dry-run` / `--apply` / `--no-ai` / `--limit` / `--delay-sec` |

#### (2) Master Index v2 entry_dict 적재 키 (chronicle_writer / backfill 공통)

`drive_client.append_index_entry(...)` 에 전달되는 entry_dict 의 최상위 키:

```text
id / date / trigger / market_state(dict) / context_tags_list(list[str]) /
action_preview(str) / phrases_list(list[dict]) / embedding_vector(null) /
report_rel_path / source ("chronicle" | "backfill") /
[reindexed_at] / [migrated_at]
```

#### (3) 영향받는 기존 호출부

| 파일 | 변경 요약 |
|---|---|
| `src/memory/chronicle_writer.py` | v2 entry 평탄화 4필드 산출 (`market_state` + `context_tags_list` + `action_preview` + `phrases_list` 보조). 기존 `keyphrases`/`keywords`/`regime`/`guideline_summary` 적재 코드 제거. `record_index_entry` 의 `source="chronicle"` 명시. |
| `src/memory/backfill.py` | `_write_chronicle_for_event` v2 적재로 갱신 + `reindex_keyphrases` 가 v2 4필드 전체를 재산출 + 진단/정리 함수의 fallback `version=2` 로 정합 + 기존 `_build_regime` 제거 (macro_triggers + chronicle_common 으로 위임) |
| `src/memory/context_retriever.py` | `_score_entry` 8단계 + `extract_market_context` dict 반환 + `build_context_injection_block` 3블록 압축. `keywords` 폴백 / `REGIME_GROUPS` 자유형 매칭 / phrase 별 다수결 tone 합산 등 v3.2 잔여 코드 제거 |
| `src/memory/drive_client.py` | `_ensure_chronicle_structure` 의 초기 `master_index.json` 작성 시 `version=2` 로 갱신 |
| `src/strategy/ai_logic.py` | `generate_text_with_chronicle` 의 컨텍스트 주입 경로를 (phrases, regime) 튜플 → `extract_market_context(...)` dict 그대로 전달로 갱신 |
| `scripts/migrate_master_index_v2.py` | 신설. `_common.setup_script_path` + `load_env_file` + `print_flush` 부트스트랩, `drive_client.{read_master_index, write_master_index, _read_json_direct, write_json_relative}` 호출 |

#### (4) 비호환 변경 / 주의사항

* `extract_market_context(macro, news_snippets)` 의 반환 타입이 **튜플 → dict** 로 변경되었다. 외부 호출부는 `ai_logic.generate_text_with_chronicle` 외에 없으며 본 PR 에서 함께 마이그레이션되었다.
* `search_similar_guidelines` 의 1번째 위치 인자가 `query_phrases` → `query_context_tags_list` 로 의미가 바뀌었다. 기존 v3.2 호출부가 직접 본 함수를 사용한 코드는 없었으므로 비호환 영향은 0건이지만, 외부 확장 코드가 있을 경우 `query_dict=extract_market_context(...)` 인자로 호출하면 안전하다.
* `build_context_injection_block(query, top_n=3)` 은 1번째 인자가 **dict 우선**, 옛 튜플 형태도 수용하지만 옛 튜플 호출 시 `regime` enum 매핑이 SIDEWAYS 로 폴백되어 점수화 단계 2/3 가 비활성될 수 있다 (정확도 저하). 신규 호출부는 dict 사용 권장.
* `chronicle_common.parse_guideline_summary` 는 호환 alias 로 유지되지만 내부적으로 `parse_action_preview`(200자) 를 호출한다. 300자 컷이 필요한 외부 코드는 호출 후 추가 슬라이싱이 필요할 수 있으나, 현 프로젝트 내 모든 사용처가 한 줄 요약만 사용하므로 영향 없음.

---

## 9. 향후 추진 과제 — Chronicles 전용

> 본 절은 본 문서(`GEMINI_DETAIL_CHRONICLES.md`)의 최하단에 위치한다. 신규 Chronicles 버전·기능 상세 섹션을 추가할 경우 본 절 **앞**에 삽입한다.

1. **v3.4 코드 적용 PR (Master Index v2)**
   * 본 사이클(v3.4) 명세된 스키마·마이그레이션 절차의 실제 코드 구현. SYS §10 #5-A 와 동일 항목.
   * 적용 대상: `drive_client.read_master_index()` default fallback `version=2` + 신규 `DriveSchemaMismatchError` 예외; `chronicle_writer` / `backfill` 의 색인 적재 로직 (`semantic_context` 산출 + 표준 `regime` enum 매핑 + `regime_label` 보존); `context_retriever._score_entry` 재설계 (`semantic_context.phrases` 자카드 + `dominant_tone` 단일 비교 + `regime` enum 정확 일치 가산); `keywords` 폴백 제거.
   * 운영 스크립트 신설: `scripts/migrate_master_index_v2.py` (`--dry-run` / `--apply`, 백업 자동화, AI 1회 호출로 `summary_kw` 보강).

2. **임베딩 기반 RAG (v3.5 후보)**
   * `text-embedding` 모델로 phrase·리포트 벡터화 후 코사인 유사도로 v3.4 phrases 자카드 가중치와 결합(하이브리드 검색).
   * v3.4 스키마 단계에서 `semantic_context.embedding_vector` 가 `null` 예약 필드로 이미 정의되어 있어, v3.5 도입 시 **스키마 재변경 불필요**. `version=2` 를 유지한 채 벡터만 채워 넣는 점진 도입.

3. **temp/tech 자동 업로드 파이프라인**
   * OHLCV·원시 뉴스 자동 업로드 → 추후 분석을 위한 raw layer 확보. 30일 TTL 와 결합.

4. **T-Day 크로니클 실전 작성 검증**
   * 트리거 충족 일자 발생 시 자동 작성 흐름 end-to-end 검증.

5. **백필 데이터 소스 다중화**
   * yfinance 외 한국거래소 KRX 정식 일봉 교차 검증.
   * 소급 시점의 실제 매크로 스냅샷(VIX/WTI/금리) 동시 보존 및 리포트 명시.

6. **Context Injection 효과 측정 메트릭**
   * 주입 사례와 미주입 사례의 매매 판단 결과 비교 → AI 교정 효과 정량화.
