# Data Persistence Requirements

## 1. 범위
### 1.1 Phase 1 (완료)
- 도메인 API 모듈: `src/storage/state_store.py`
- 도메인 적용: A(운영 상태) + B(거래 이력)
- 백엔드: Drive 위임 (변경 없음).
- 호출자 영향: import 경로 변경 + 함수명 변경. 비즈니스 로직 변경 0.

### 1.2 Phase 2 (완료)
- SQLite 백엔드 신설: `src/storage/sqlite_backend.py`.
- 마이그레이션 러너: `src/storage/migrations/runner.py` + `v001_initial.py`.
- 이관 스크립트(수동): `scripts/migrate_drive_to_sqlite.py`.
- 환경변수 분기: `STATE_STORE_BACKEND`, `STATE_STORE_DB_PATH`.
- 도메인 적용: A/B 만. C/D(Chronicles) 는 Phase 3 에서 v2 스키마와 함께.
- `logger.record_trade` 의 `paper_trades.json` self-call 은 Phase 2 에서 변경하지 않는다 (Phase 2.5).

### 1.3 Phase 3 (본 PR 의 사양 정의 단계)
- Chronicle 전용 Repository 신설: `src/storage/chronicle_repo.py`.
- `state_store.py` 는 chronicle_repo 의 공개 API 를 **re-export** 만 수행 (모듈 비대 방지 + Repository 패턴 분리).
- SQLite 스키마 v2: `v002_chronicle.py` 마이그레이션.
- 이관 스크립트(수동): `scripts/migrate_chronicles_to_sqlite.py`.
- 도메인 적용: C(인덱스) + D(본문) + Chronicle 운영 상태(backfill_state).
- FTS5 풀텍스트 검색 활성. 단, `context_retriever` 의 8단계 점수화 로직은 **무변경** (위험 격리).
- `embedding_vector BLOB` 컬럼 사전 예약 (v3.5 에서 채움).
- `lifecycle.py` 의 Drive 임시 폴더 TTL 청소는 **Phase 3 비대상** (Phase 5 에서 통째 정리).
- `scripts/migrate_master_index_v2.py` 는 SQLite 모드에서 자동 비활성 (Drive 모드 호환성을 위해 코드는 유지).

### 1.4 Phase 4 (본 PR — 정책 SCP/Local 로 변경, 2026-06-07)
- **목적**: SQLite DB 파일이 LightSail 디스크 손실/실수 삭제 시 단일 장애점이 되지 않도록 자동 백업 체계를 수립한다.
- **정책 변경 이력**: 초기 안(commit `7db5f52` 사양 + `5b79cf0` 코드 + `6c7f9c6` E2E)은 **GitHub Private Repo + orphan 브랜치** 였으나, 외부 호스팅/PAT 의존 회피 및 단일 책임 원칙(봇 = 백업 파일 생성만, 외부 동기화 = 별도 채널)을 위해 **LightSail 로컬 디렉터리 백업** 으로 전환한다. 외부 동기화는 운영자 PC 의 별도 SCP/rsync 채널로 분리.
- **백업 채널**: LightSail 로컬 디렉터리 `BACKUP_LOCAL_DIR` (기본 `data/backup_local/`). 봇 본체 git 추적 대상 아님 (.gitignore 자동 차단). `git` 의존 0.
- **트리거**: 봇 내부 `schedule` 라이브러리 (`main.py` 의 기존 패턴 계승). daemon thread 에서 비차단 실행.
- **주기**: 일간 18:00 KST (장 마감 후) + 주간 일요일 22:00 KST + 월간 1일 00:30 KST 자동 승격 (daily 1개 → monthly/ 복사).
- **백업 파일 형식**: SQLite `VACUUM INTO` 로 단일 .db 추출 → gzip 압축 (`.db.gz`).
- **보관 정책**: 일간 30일 + 주간 12주 + 월간 12개월 계층형. 회전 알고리즘 (`os.remove` 단순 회전) 으로 디스크 사이즈 안정화.
- **슬랙 보고**: 성공/실패 모두 보고. 실패는 B-Type Pause + stacktrace.
- **복원**: 수동 스크립트만 (`scripts/restore_sqlite_from_local.py`). 자동 복원은 미지원.
- **외부 동기화**: 운영자 PC 의 별도 채널 (rsync 권장 / scp 가능). 본 봇 책임 외부 — 사양 부록(§02 §9.5) 의 명령 예시만 안내.
- **신설 모듈**: `src/storage/backup_scheduler.py` (스케줄러) + `scripts/backup_sqlite_local.py` (백업 실행) + `scripts/restore_sqlite_from_local.py` (복원).
- **인증**: 외부 인증 없음. `.env` PAT/repo URL 키 0개. 운영자 PC 의 SSH 접근만 별도 (LightSail 운영용 키 재사용).
- **본 Phase 4 비대상**: Lightsail Snapshot, S3 미러, 운영자 PC 의 자동 rsync 스케줄링, 자동 복원 — 후속 Phase 검토.

## 2. 기능 요구사항
- F1. 호출자는 백엔드 종류(Drive/SQLite/PG)를 알 수 없어야 한다.
- F2. 도메인 메서드는 의미 단위로 분리한다 (`get_portfolio`, `save_split_orders` 등). 파일명·확장자·경로를 호출자가 알 필요 없다.
- F3. `state_store` 는 백엔드 객체를 모듈 레벨 단일 인스턴스로 보유한다. Phase 2 에서 환경변수(`STATE_STORE_BACKEND`)로 교체 가능.
- F4. 반환 타입은 Python 기본 자료형(`dict`/`list`)으로 통일한다. Phase 3 에서 dataclass 도입 시에도 호환성 유지.
- F5. Phase 1 단계에서 `src/utils/logger.py` 의 `load_json_from_gdrive`/`save_json_to_gdrive`/`record_trade` 는 하위 호환을 위해 유지한다. 테스트 monkeypatch 와 logger 내부 self-call 보호.

## 3. 비기능 요구사항
- N1. 외부 의존성 0 (Phase 1 은 stdlib 만 사용. Phase 2 의 `sqlite3` 도 stdlib).
- N2. 동일 프로세스 내 호출 빈도 100/sec 까지 지연 무시 가능 수준.
- N3. 백엔드 교체 시 호출자 코드 0건 변경 (Repository 패턴).
- N4. 모듈 import 사이클 없음. `state_store` 는 `logger` 만 의존, 반대 방향 금지.

## 4. 제약
- C1. 룰(`.cursor/rules/autostock.mdc` §2) 의 변수 명명 규칙 준수: 구조체는 `_dict`/`_list` 접미사.
- C2. UTF-8 + .py 이모지 금지.
- C3. `.json`/`.env` 파일 직접 분석 금지 (룰 §3).
- C4. 도메인 메서드 시그니처는 Phase 2/3 진행 시에도 **추가만 가능, 기존 메서드 시그니처 변경 금지**.

## 5. 도메인 책임 정의
### A. 운영 상태 (mutable snapshot)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| portfolio | 보유 종목 잔고/평단/모드 | 매 거래 시 |
| split_orders | 분할 매수 큐 (티커별 잔여 차수) | 매분 ~ 매 거래 |
| theme_context | AI 테마 기억 (수동등록 / 발굴) | 매 등록 시 |
| scalp_session | 단타 세션 상태 (예산/lifecycle/position) | 매 lifecycle 전이 |

### B. 거래 이력 (append-only)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| trades | 모든 매수/매도 기록 (시계열) | 매 체결 시 |

### C. Chronicle 인덱스 (Phase 3 적용)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| chronicle_entries | master_index v2 entries (regime/regime_label/main_actor/sentiment/action_preview/context_tags_list/phrases_list/embedding_vector 평탄화) | T-Day 1건/일 + 백필 일괄 |

### D. Chronicle 본문 (Phase 3 적용)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| chronicle_reports | reports/.md 본문 (header_md + body_md + full_md) | entry 1건당 1행 |
| chronicle_report_sections | 본문 5섹션 정규화 (Intraday Flow / 사건과 원인 / 미래 행동 지침 / 한 줄 요약 / unknown) | entry 1건당 N행 |
| chronicle_search | FTS5 풀텍스트 (`unicode61 remove_diacritics 2` 토크나이저) | entry 1건당 N행 (섹션 단위 인덱싱) |

### Chronicle 운영 상태 (Phase 3 적용)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| chronicle_backfill_state | backfill 스캔 결과 큐 / processed / skipped (단일 row payload_json) | 백필 사이클 시 |

## 6. 호환성/회귀 안전망
- R1. Phase 1 PR 적용 후 봇 기동/매수/매도/risk_monitor/scalp_session 모든 흐름이 동일하게 동작해야 한다.
- R2. 테스트 monkeypatch 코드(`tests/temp_test_scalp_logic.py:277,311`, `tests/temp_test_market_calendar_and_token.py:196-197`) 는 `orchestrator.load_json_from_gdrive` 를 패치하므로, **orchestrator 의 `load_json_from_gdrive` import 는 유지**한다 (state_store 와 별개로 보존).
- R3. Phase 2 진입 전 단위 테스트(`tests/test_state_store.py`) 추가 권장.

## 7. Phase 2 요구사항
### 7.1 기능
- P2F1. SQLite 백엔드는 `_StateStoreBackend` 인터페이스를 동일하게 구현한다 (`read_json`/`write_json`). 호출자 코드 0 변경.
- P2F2. `state_store` 모듈 로드 시 환경변수 `STATE_STORE_BACKEND` 값(소문자 trim)으로 백엔드를 결정한다. 기본값 `"drive"`. `"sqlite"` 만 허용 추가 키워드.
- P2F3. SQLite 파일 경로는 환경변수 `STATE_STORE_DB_PATH` (기본 `data/sqlite/autostock.db`). 파일이 없으면 자동 생성하고 `apply_pending` 으로 스키마 부트스트랩.
- P2F4. 마이그레이션 러너는 `src/storage/migrations/` 의 `vNNN_*.py` 파일을 버전 오름차순으로 적용한다. `schema_version` 테이블이 적용 이력을 기록한다.
- P2F5. 이관 스크립트는 명시적 사용자 실행. `--db-path`/`--dry-run` 옵션. 단계: ① Drive 5 도메인 로드 → ② SQLite 스키마 생성 → ③ INSERT → ④ 카운트 비교 → ⑤ 결과 출력/슬랙.
- P2F6. 이관 후 Drive 의 원본 JSON 5개는 그대로 보존한다 (Phase 5 까지).

### 7.2 비기능
- P2N1. 외부 의존성 0 (`sqlite3` 은 stdlib).
- P2N2. SQLite 연결은 모듈 단일 인스턴스. `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`.
- P2N3. 모든 write 는 트랜잭션 1건으로 묶는다 (자동 rollback 보장).
- P2N4. read latency 는 동일 프로세스 기준 1ms 이하 목표 (paper_trades.json 1MB 가정).

### 7.3 폴백/에러 정책
- P2E1. SQLite 에러는 그대로 상위로 전파한다 (Drive 폴백 금지). 상위(`drive_client` Pause 라인과 동일 위치)에서 B-Type 으로 처리하도록 일관성 유지.
- P2E2. DB 파일 디렉터리 부재 시 자동 생성 (`os.makedirs(exist_ok=True)`).
- P2E3. 스키마 마이그레이션 실패 시 부분 적용 방지 — `BEGIN`/`COMMIT` 묶음 + 실패 시 ROLLBACK.

### 7.4 비고
- P2T1. trades 테이블은 Phase 2 시작점에서 `payload_json` 단일 컬럼만 둔다. `mode_type`/`strategy_tag`/`price`/`qty` 등 검색 키는 Phase 3+ 에서 점진적으로 외부 컬럼화한다 (2-phase migration 패턴).
- P2T2. `replace_trades` 는 Phase 2 에서도 전체 교체 시맨틱을 유지한다. Phase 2.5 에서 `append_trade` 추가 검토.

## 8. Phase 2 회귀 안전망
- P2R1. `STATE_STORE_BACKEND` 미설정 → 기존 Drive 백엔드 100% 동일 동작. Phase 1 회귀 0.
- P2R2. SQLite 백엔드 전환 후 `state_store` 의 모든 공개 함수 시그니처/반환 타입은 Phase 1 과 동일하다.
- P2R3. 이관 스크립트의 dry-run 모드에서 INSERT 미실행 + 카운트만 출력. 사용자가 결과 확인 후 실제 적용 명령 별도 실행.

## 9. Phase 3 요구사항
### 9.1 기능
- P3F1. 신규 모듈 `src/storage/chronicle_repo.py` 는 Chronicle 도메인(C/D + backfill_state) 전용 Repository 다.
- P3F2. `state_store.py` 는 chronicle_repo 의 공개 함수를 **re-export** 만 수행한다. 호출자는 `state_store` 하나만 import 하면 된다 (Phase 1/2 인터페이스 일관성 유지).
- P3F3. 동일한 환경변수 `STATE_STORE_BACKEND` 가 A/B/C/D 모두에 적용된다. SQLite 모드에서는 chronicle_repo 도 SQLite 로, Drive 모드에서는 chronicle_repo 도 Drive 로 라우팅된다.
- P3F4. 인덱스 단일 시맨틱: 한 chronicle 작성 = `chronicle_entries` 1 row + `chronicle_reports` 1 row + `chronicle_report_sections` N row + `chronicle_search` N row. **단일 트랜잭션**으로 묶어 부분 실패 방지.
- P3F5. .md 본문 5섹션 파싱:
  1. `## 헤딩` 단위로 분리.
  2. 헤딩 텍스트에 따라 `section_key` 분류 (정확 일치 우선, 부분 일치 폴백).
     - "Intraday Flow" / "장중 흐름" → `intraday_flow`
     - "사건과 원인" → `event_and_cause`
     - "미래 행동 지침" → `action_guideline`
     - "한 줄 요약" → `one_line_summary`
     - 그 외 → `unknown`
  3. 헤딩 매칭 실패 시에도 본문은 손실 없이 `unknown` 으로 보존.
- P3F6. FTS5 인덱싱은 섹션 단위로 한다 (`body_md` 컬럼). `section_key` 필터 가능.
- P3F7. 마이그레이션 스크립트 `scripts/migrate_chronicles_to_sqlite.py` 는 명시적 실행. `--db-path` / `--dry-run` / `--no-slack` / `--reports-only` / `--entries-limit N` 옵션.
- P3F8. 마이그레이션은 idempotent (DELETE+INSERT). 단, FTS5 도 함께 재구축.

### 9.2 비기능
- P3N1. 외부 의존성 0 (FTS5 는 sqlite3 stdlib 컴파일 옵션. 표준 Python 3.7+ 빌드에 포함).
- P3N2. chronicle_repo 의 read 는 평균 1ms 이하 목표.
- P3N3. FTS5 검색은 entries 1000건 기준 50ms 이하 목표.
- P3N4. v002 마이그레이션은 entries 100건 기준 1초 이내 적용.

### 9.3 폴백/에러 정책
- P3E1. .md 헤딩 매칭 실패 → `section_key=unknown` 으로 본문 보존 (예외 미발생).
- P3E2. FTS5 빌드 미지원 (구형 sqlite 빌드) → 시작 시점 1회 stderr 경고 + FTS 비활성 모드 (`search_fulltext` 가 정규식 폴백). 봇 운영은 정상 계속.
- P3E3. Drive 측 .md 본문 누락 (`report_rel_path` 가 가리키는 파일 부재) → 해당 entry 는 마이그레이션 스크립트에서 `skipped` 로 격리 + 슬랙 보고. 인덱스는 그대로 진행.
- P3E4. SQLite IO 실패 정책은 Phase 2 와 동일 (예외 전파, 상위에서 B-Type).

### 9.4 비고
- P3T1. `chronicle_entries.payload_json` 은 두지 않는다 (Phase 2 의 A/B 패턴과 다름). 사유: regime/regime_label/main_actor/sentiment/action_preview/context_tags_list/phrases_list 가 **검색 키**여야 하므로 모두 외부화. v3.5 부터 임베딩 cosine + FTS5 결합 시 인덱스 활용 가능성 확보.
- P3T2. `chronicle_reports.full_md` 는 호환·내보내기·디버그용으로 보존. body_md 와 합쳐 ~2×N 의 스토리지 비용이 있으나, 100 entries × 4KB 가정 시 800KB 수준 — 무시 가능.
- P3T3. embedding_vector 채움은 v3.5 별도 PR. Phase 3 에서는 컬럼만 예약하고 모두 NULL.

## 10. Phase 3 회귀 안전망
- P3R1. `STATE_STORE_BACKEND=drive` (기본/롤백) → chronicle_repo 는 기존 `drive_client.*` 호출 그대로 위임. 호출부 동작 100% 동일.
- P3R2. `context_retriever.search_similar_guidelines` 의 점수화 로직은 변경하지 않는다. FTS5 는 별도 API (`search_fulltext`) 로만 노출.
- P3R3. 마이그레이션 스크립트 dry-run 에서 INSERT 미실행 + 카운트만 비교 + exit 0.
- P3R4. v002 마이그레이션은 v001 적용된 DB 위에 add-on 으로만 동작 (drop 없음).
- P3R5. 호출부 마이그레이션은 동일 import (`from src.storage import state_store`) 만 사용. 신규 import 0 (chronicle_repo 직접 import 금지).

## 11. Phase 4 요구사항 (정책 SCP/Local, 2026-06-07 갱신)
### 11.1 기능
- P4F1. 기존 모듈 `src/storage/backup_scheduler.py` 는 봇 프로세스 내부에서 백업 사이클을 등록하는 진입점이다. `main.py` 가 부팅 시 1회 호출하여 `schedule.every().day.at("18:00").do(...)` / `schedule.every().sunday.at("22:00").do(...)` / `schedule.every().day.at("00:30").do(_run_in_thread_if_first_of_month)` 3 jobs 등록.
- P4F2. 실제 백업 작업은 **`scripts/backup_sqlite_local.py`** (정책 변경, GitHub 버전 폐기) 의 공개 함수 `run_backup_cycle(kind: Literal["daily","weekly","monthly"], *, db_path: str, backup_dir: str, notify_fn=None, dry_run: bool=False) -> dict` 가 수행한다. 동일 함수는 운영자가 CLI 로도 직접 호출할 수 있다 (예: `python scripts/backup_sqlite_local.py --kind daily --no-slack`).
- P4F3. 백업 사이클 단계 (Atomic, 7단계로 단순화 — git 의존 0):
  1. 사전 점검 (`db_path` 존재). 미존재 시 슬랙 FAIL + early return.
  2. `BACKUP_LOCAL_DIR/{daily,weekly,monthly,staging}/` 디렉터리 보장 (`os.makedirs(exist_ok=True)`).
  3. SQLite 라이브 DB 에 대해 `VACUUM INTO '{BACKUP_LOCAL_DIR}/staging/autostock-{stamp}.db'` 실행. WAL/SHM 통합 일관성 보장. 실패 시 60초 후 1회 재시도 (P4E1).
  4. staging .db 를 gzip 압축 → `{BACKUP_LOCAL_DIR}/{kind}/autostock-{stamp}.db.gz` 로 이동. staging 정리 (P4E2).
  5. (kind=='monthly' 특수): daily/ 의 최신 1개를 `{BACKUP_LOCAL_DIR}/monthly/autostock-{stamp}.db.gz` 로 복사 (Step 3~4 미실행). 일간 미존재 시 skip + 슬랙 INFO.
  6. 보관 정책 회전 알고리즘 적용: `daily/` 30일 초과 / `weekly/` 12주 초과 / `monthly/` 12개월 초과 파일을 `os.remove` (P4E4 — 회전 실패는 WARN, 백업 자체 성공으로 간주).
  7. 슬랙 보고 (`[Backup OK] {kind} {stamp} | gz={N}KB | rotated={N} | elapsed={N}s`).
- P4F4. **타임스탬프 형식**: KST 기준 `YYYYMMDD-HHMM` (`autostock-20260606-1800.db.gz`). UTC 가 아닌 KST 사용 — 운영자가 슬랙/파일명에서 즉시 인지 가능.
- P4F5. 보관 정책 분류:
  - 일간 (`daily/`): 매 18:00 KST 실행 → 30일 보존 (`BACKUP_RETENTION_DAILY`, 기본 30).
  - 주간 (`weekly/`): 매 일요일 22:00 KST 실행 → 12주 보존 (`BACKUP_RETENTION_WEEKLY`, 기본 12).
  - 월간 (`monthly/`): 매월 1일 00:30 KST 자동 승격 (일간 백업 1개를 monthly 로 복사) → 12개월 보존 (`BACKUP_RETENTION_MONTHLY`, 기본 12).
- P4F6. 복원 스크립트 `scripts/restore_sqlite_from_local.py` (정책 변경, GitHub 버전 폐기) 는 운영자가 명시적으로 실행한다. 옵션:
  - `--list`: `BACKUP_LOCAL_DIR` 내 사용 가능한 백업 파일 나열 (kind/stamp/size 기준).
  - `--stamp <YYYYMMDD-HHMM>` + `--kind {daily,weekly,monthly}`: 특정 시점으로 복원.
  - `--latest [--kind ...]`: 가장 최신 백업으로 복원 (기본 `daily`).
  - `--target-path PATH`: 복원 대상 DB 경로 (기본 `STATE_STORE_DB_PATH`).
  - `--backup-dir PATH`: 백업 소스 디렉터리 (기본 `BACKUP_LOCAL_DIR`).
  - `--dry-run`: 압축 풀이 + integrity_check + 시뮬레이션 보고 + INSTALL 미실행.
  - `--force`: 봇 실행 점검 우회 (위험, 운영자 명시 책임).
- P4F7. 복원 절차의 안전 보장:
  1. 봇이 실행 중이면 운영자가 먼저 `s-stop`. 스크립트는 `lsof`/`fuser` 로 DB 파일 사용 중 여부 점검 → 사용 중이면 즉시 중단 + 안내. `--force` 미지정 시.
  2. 기존 DB 파일은 `{db_path}.bak-{stamp}` 로 rename (덮어쓰기 직전 1회).
  3. 압축 풀이 → `PRAGMA integrity_check` 통과 시에만 `os.replace` 로 `{db_path}` 로 atomic 이동.
  4. 실패 시 `.bak` 파일 자동 복원 후 종료 코드 ≠ 0.
- P4F8. 백업 작업이 봇의 거래/orchestrator 사이클에 영향을 주지 않도록 별도 daemon thread 에서 실행 (`threading.Thread(target=..., daemon=True)`). schedule 의 메인 thread blocking 방지.
- P4F9. **외부 동기화는 본 봇 책임 외부**. 운영자 PC 가 별도 채널로 LightSail 의 `BACKUP_LOCAL_DIR` 를 주기적으로 가져온다. 권장: `rsync -avz --delete ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/ ~/autostock_backup/`. 사양 §02 §9.5 부록.

### 11.2 비기능
- P4N1. 외부 의존성 0 추가 — `gzip` (LightSail Ubuntu 기본 설치) + Python stdlib (`sqlite3`, `gzip`, `shutil`, `subprocess` for `lsof/fuser`) 만 사용. `git` 의존 0. PAT/외부 인증 0.
- P4N2. 백업 1회 소요 시간 목표: DB 100MB 기준 45초 이내 (VACUUM INTO 30s + gzip 10s + 회전 5s 가정 — git push 20s 가 사라져 단축).
- P4N3. 백업 실행 중 봇의 SQLite read/write latency 영향 ≤ 50ms (VACUUM INTO 는 read-only snapshot 이므로 write 차단 ≤ 100ms 수준 예상).
- P4N4. `BACKUP_LOCAL_DIR` 의 디스크 사용량 목표: 30 daily × 5MB + 12 weekly × 5MB + 12 monthly × 5MB ≈ 270MB 이하 (DB 100MB / gzip 비율 1:20 가정 시 더 작음). LightSail 32GB free 대비 무시 가능.

### 11.3 폴백/에러 정책
- P4E1. **VACUUM INTO 실패** (`sqlite3.OperationalError: database is locked` 등): 60초 후 1회 재시도 → 그래도 실패 시 슬랙 보고 + B-Type Pause. SQLite 에러는 Phase 2/3 정책 (`§9.7 E1 / §11.7 E5`) 와 일관.
- P4E2. **gzip 실패** (디스크 부족 등): staging 파일 정리 + 슬랙 보고 + B-Type Pause.
- P4E3. **(미사용)** GitHub 정책 폐기로 git push 에러 분기 삭제. 본 정책에서는 외부 네트워크 의존 0 — 외부 통신 실패 분기 없음.
- P4E4. **보관 정책 회전 중 실패** (`os.remove` 실패 — 권한/잠금): 백업 자체는 성공으로 간주. 회전 실패만 별도 슬랙 WARN 보고. 다음 회차에 재시도.
- P4E5. **복원 시 integrity_check 실패**: 압축 풀이된 .db 즉시 폐기 + `.bak` 자동 복원 + exit 4. 운영자에게 백업 파일 손상 안내.
- P4E6. **백업 thread 예외**: thread 가 죽어도 봇 본체에는 영향 없음 (`daemon=True`). 다음 schedule tick 에 재시도. 슬랙 1회 보고.

### 11.4 비고
- P4T1. `BACKUP_LOCAL_DIR` 는 봇 본체 repo 작업 디렉터리(`/home/ubuntu/my_bot`) **내부**에 있어도 무방하다 (.gitignore 에서 자동 차단). 외부 디스크/Volume 마운트도 환경변수로 임의 변경 가능.
- P4T2. 슬랙 메시지 형식: `[Backup OK] {kind} {stamp} | gz={N}KB | rotated={N} | elapsed={N}s` / `[Backup FAIL] {kind} {stamp} | step={vacuum_into|gzip|preflight} | err=...` (git step 분기 삭제).
- P4T3. 월간 승격은 일간 백업이 적어도 1개 존재할 때만 실행. 첫 달 실행 시 일간 백업이 없으면 skip + 슬랙 INFO.
- P4T4. **외부 인증 0**. PAT/repo URL/branch/git user 키 일체 없음. 운영자 PC ↔ LightSail 의 SSH 접근만 별도 (LightSail 운영용 키 재사용).
- P4T5. 본 Phase 4 는 Drive 의존을 0 으로 만들지 않는다 (Drive 코드는 Phase 5 에서 일괄 제거). Phase 4 완료 후에도 Drive 백엔드는 폴백용으로 코드 보존.
- P4T6. **외부 동기화 안내** (사양 §02 §9.5 부록): 운영자 PC 의 macOS 에서 1회 수동 또는 launchd 자동 — `rsync -avz --delete ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/ ~/autostock_backup/`. 본 봇은 안내 외 책임 없음.

## 12. Phase 4 회귀 안전망 (정책 SCP/Local, 2026-06-07 갱신)
- P4R1. 기본값 `BACKUP_ENABLED=false` (`.env` 미설정 시 백업 미실행). Phase 1~3 회귀 0 보장.
- P4R2. 백업 thread 가 SQLite write transaction 을 갖지 않으므로 봇의 거래/Chronicle 흐름에 영향 0.
- P4R3. 복원 스크립트는 봇이 실행 중이면 자동 차단 (P4F7-1, `--force` 미사용 시). 사용자 실수로 라이브 DB 덮어쓰기 사고 차단.
- P4R4. 회전은 단순 `os.remove`. git history / commit 추적 없음 (정책 변경) — 회전된 파일은 이전 사이클의 슬랙 로그(`rotated={N}`)로만 추적 가능.
- P4R5. `BACKUP_LOCAL_DIR` 는 .gitignore 에 `data/backup_local/` 패턴으로 자동 차단되어 봇 본체 repo 의 `git add` 에 절대 포함되지 않는다. 즉, .db.gz 파일이 main 브랜치로 누출되는 사고 차단.
- P4R6. **GitHub 안의 `GIT_CEILING_DIRECTORIES` 가드는 본 정책에서 불필요**. git subprocess 호출 0 → 봇 본체 repo 오염 위험 0 (origin 차단). 단, 정책 변경 이력은 본 §1.4 에서 고지.
- P4R7. **외부 호스팅 의존 0**. PAT 만료/외부 권한 차단/외부 네트워크 장애 등 외부 요인에 의한 백업 실패 분기 없음. 봇 측 백업 사이클은 LightSail 디스크 IO 만 의존.
