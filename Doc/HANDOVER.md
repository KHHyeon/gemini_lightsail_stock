# HANDOVER — 작업 인계 문서

> **최신 갱신**: 2026-06-07 (Phase 4 Step 2 코드 구현 완료 + 로컬 smoke 15/15 PASS 직후).
> **목적**: 다른 PC / 새 세션의 Cursor Agent 가 본 문서 1개만 먼저 읽으면 즉시 이질감 없이 작업을 이어받을 수 있도록 한다.

---

## 0. 새 PC 에서 작업 시작 체크리스트 (5분)

1. `git clone` 또는 `git pull` 후 브랜치 확인.
   - 운영 브랜치: **`my_bot`**.
   - 최근 push 기준 (2026-06-06): `cb2f1c9 docs(handover): 다중 PC 작업 인계용 HANDOVER.md 신설 + 우선 읽기 규약 반영`.
   - **로컬 commit (미push, 2026-06-07)**:
     - `7db5f52 docs(data_persistence): Phase 4 Step 1 - 백업 정책 사양 정의`.
     - Phase 4 Step 2 코드 구현 (신설 4 파일 + main.py + .gitignore).
2. `.env` 파일 확보 (보안 사유로 git 제외). 운영자가 별도 전달.
   - 필수 키: `APP_KEY / SECRET_KEY / ACCOUNT_NO / HTS_ID / SLACK_TOKEN / SLACK_CHANNEL / GOOGLE_API_KEY / GOOGLE_DRIVE_OAUTH_CLIENT_FILE / DART_API_KEY / TRADING_MODE_NORMAL / SCALP_CONDITION_NAME / TG_API_ID / TG_API_HASH`.
   - **Phase 2/3 신규 키**: `STATE_STORE_BACKEND` (값: `drive` 또는 `sqlite`, 기본 `drive`). 운영 서버는 `sqlite` 활성화 상태.
   - `STATE_STORE_DB_PATH` (기본 `data/sqlite/autostock.db`).
3. **첫 읽기 순서** (절대 깨지 말 것 — 워크스페이스 룰 `.cursor/rules/autostock.mdc` 와 동일):
   1. `Doc/HANDOVER.md` ← 본 문서.
   2. `Doc/system_architecture.md` (전체 골격).
   3. 작업 대상 기능의 `Doc/features/[기능명]/[기능명]_README.md` (인덱스).
   4. 필요 시 `01_*_requirements.md` / `02_*_api_spec.md` / `03_*_state_logic.md` 순.
4. 코딩 표준 (`.cursor/rules/autostock.mdc`) 재확인 — 한국어, 이모지 금지 (.py), DRY, B-Type 보고, 커밋 메시지 2~3줄.
5. 로컬 smoke 테스트 1회로 환경 검증:
   ```
   python tests/smoke_state_store_sqlite.py    # Phase 2 SQLite 라운드트립
   python tests/smoke_chronicle_repo.py        # Phase 3 Chronicle 라운드트립
   ```
   둘 다 `ALL OK` 로 끝나야 환경 OK.

---

## 1. 한 줄 요약 (현재 상태)

**Drive → SQLite 마이그레이션 3 단계(Phase 1~3) 모두 완료. Phase 4 Step 1+2 (백업 정책 사양 + 코드 구현) 모두 로컬 완료. 로컬 smoke 15/15 PASS. 다음 단계 = Step 3 운영자 검증 (LightSail 1회 실 백업 + 1주 운영 안정).**

상위 작업 컨테이너 (체크포인트):

| 영역 | 상태 | 진척 |
|---|---|---|
| Phase 1 — 추상화 레이어 (`state_store`) | 완료 | 38 호출 마이그레이션, commit `1652b24` + `dad168e` |
| Phase 2 — SQLite 백엔드 (A/B 도메인) | 완료 + 실 서버 이관 성공 | commit `e8e218f`/`c0aaef5`/`1d73773`/`4c5af9d` |
| Phase 3 — Chronicle SQLite (C/D + backfill_state) | 완료 + 실 서버 이관 성공 | commit `e608ad8`/`935203f`/`4204c9b`/`156c9d3` |
| M6 안정성 모니터링 | 진행 중 (Day 1~3 PASS) | commit `3591d75`/`74934a3`/`a73625b`/`3bcb6d1` |
| Phase 4 Step 1 — 백업 정책 사양 정의 | 완료 (로컬 commit, 미push) | commit `7db5f52` |
| Phase 4 Step 2 — 백업 코드 구현 | 완료 (로컬, 미commit) | 신설 4 파일 + main.py + .gitignore + smoke 15/15 PASS |
| Phase 4 Step 3 — 운영자 검증 (실 서버 1회 + 1주 안정) | 미착수 | Step 2 commit/push + 운영자 작업 |
| Phase 5 — Drive 코드 통째 정리 | 미착수 (Phase 4 + 안정 운영 후) | — |

---

## 2. 완료된 작업 (시간 역순, 핵심만)

### 2.0a Phase 4 Step 2 — 백업 코드 구현 (2026-06-07, 로컬 미commit)
- **신설 4 파일**:
  - `src/storage/backup_scheduler.py` (~230 라인): `register_backup_jobs(scheduler, *, notify_fn=None) -> bool`. BACKUP_ENABLED=false 면 즉시 False 반환 (회귀 0 보장). 활성 시 daily/weekly/monthly 3 jobs 등록. 트리거 시 daemon thread 에서 `_safe_run_backup` 호출 → schedule 메인 thread 차단 0.
  - `scripts/backup_sqlite_to_github.py` (~530 라인): `run_backup_cycle(*, kind, db_path, repo_dir, notify_fn=None, dry_run=False) -> dict`. 10단계 흐름 (사양 §13.4 일치) + CLI 진입점. `_setup_repo_dir` 가 idempotent (.git 보존 / 부분 잔존 정리 / 빈 브랜치 시 init+orphan 자동 신설). PAT 노출 방지 `_redact_token`.
  - `scripts/restore_sqlite_from_github.py` (~430 라인): `run_restore(...)` 8단계 흐름 + CLI. 봇 실행 점검 `_is_db_in_use` (lsof / fuser / wal+shm 폴백). DRY 원칙으로 backup 모듈의 헬퍼 재사용.
  - `tests/smoke_backup_to_github.py` (~480 라인): 8 단계 시나리오. 자체 `_StubScheduler` (로컬 schedule 라이브러리 미설치 환경 대응) + file:// 베어 저장소 (외부 GitHub 없이 검증). 실행 결과 **15/15 PASS, elapsed ≈ 1.1s**.
- **수정 2 파일**:
  - `main.py`: `run_scheduler()` 의 risk_monitor 등록 직후 `register_backup_jobs(schedule, notify_fn=orchestrator.send_slack)` 호출 1 블록 추가 (예외 안전).
  - `.gitignore`: `data/backup_repo/`, `data/.smoke_workspace/`, `*.db.gz` 추가.
- **smoke 결과 요약 (15/15 PASS)**:
  - register_backup_jobs: BACKUP_ENABLED=false → 0 jobs / =true → 3 jobs (day 2 + sunday 1) 정확.
  - run_backup_cycle dry-run: VACUUM + gzip + 회전 시뮬레이션, git commit/push 미실행 확인.
  - run_backup_cycle 실 실행: orphan 브랜치 자동 신설 + commit_sha 7자 이상 + result.gz_size 와 실제 사이즈 일치.
  - 회전 알고리즘: seed 31일 전 1개 + 30일 이내 4개 + 신규 1개 → 31일 전 1개만 git rm, 5개 잔존.
  - run_restore: --list / dry-run / 실 install 모두 PASS. integrity_check=ok, schema_version + portfolio TEST row 무손실 복원.
- **검증**: py_compile 4 파일 PASS / ReadLints 0건 / smoke 15/15 PASS. macOS sandbox 가 git hooks 디렉터리 생성을 차단해서 smoke 실행 시 1회 sandbox 풀이 필요 (운영 LightSail 환경에서는 영향 없음).
- **다음 단계 (Step 3, 운영자 작업)**:
  1. GitHub Private Repo 의 `backup` orphan 브랜치 1회 초기화 (스크립트가 자동 신설하므로 운영자는 `BACKUP_REPO_URL` + PAT 발급만 수행).
  2. `.env` 에 13종 `BACKUP_*` 키 추가 + `BACKUP_ENABLED=true`.
  3. LightSail 에서 `python scripts/backup_sqlite_to_github.py --kind daily` 1회 수동 실행 → backup 브랜치 commit 1건 + 슬랙 `[Backup OK]` 수신 확인.
  4. 봇 재기동 (`s-restart`) 후 부팅 stdout `[BACKUP] backup jobs registered: ...` 매칭 확인.
  5. 1주 운영 (일간 7회 + 주간 1회) 안정 확인 후 Step 3 마킹.

### 2.0 Phase 4 Step 1 — 백업 정책 사양 정의 (2026-06-07, commit `7db5f52`)
- **결정 사항 (사용자 컨펌)**:
  - 트리거: 봇 내부 `schedule` (별도 thread, 인프라 추가 0).
  - 주기: 일간 18:00 KST + 주간 일요일 22:00 KST + 월간 1일 00:30 KST (월간은 일간 백업 1개 승격).
  - 저장: 본 GitHub repo 의 `backup` orphan 브랜치 (별도 작업 디렉터리에 single-branch clone, main 영향 0).
  - 형식: SQLite `VACUUM INTO` + gzip (`.db.gz`).
  - 보관: 일간 30일 + 주간 12주 + 월간 12개월 계층형 (회전 알고리즘).
  - 슬랙 보고: 성공/실패 모두. 실패는 B-Type Pause + stacktrace.
  - 복원: 수동 스크립트만 (`scripts/restore_sqlite_from_github.py`).
- **사양서 갱신 (4 파일)**:
  - `Doc/features/data_persistence/data_persistence_README.md`: v1.3 (Phase 4) Step 1 100% 마킹 + 로드맵 갱신.
  - `01_data_persistence_requirements.md`: §1.4 Phase 4 범위 + §11 요구사항 (P4F1~F8 / P4N1~N4 / P4E1~E6 / P4T1~T5) + §12 회귀 안전망 (P4R1~R5).
  - `02_data_persistence_api_spec.md`: §9 Phase 4 API (환경변수 13종 + `register_backup_jobs` + `run_backup_cycle` + `run_restore` + 슬랙 메시지 4종 규약 + 의존성 그래프).
  - `03_data_persistence_state_logic.md`: §13 Phase 4 동작 흐름 (모듈 의존 그래프 + 디렉터리 명명 + 단일 백업 사이클 10단계 + 월간 승격 + 보관 정책 회전 + 복원 절차 8단계 + 에러 정책 + 검증 체크리스트 + 부트스트랩 순서 + 회귀 차단 + Step 2 Post-Update 예약).
- **본 PR 비대상 (Step 2 에서 처리)**:
  - 신설 코드 3 파일: `src/storage/backup_scheduler.py` / `scripts/backup_sqlite_to_github.py` / `scripts/restore_sqlite_from_github.py`.
  - `main.py` 의 `register_backup_jobs(...)` 1줄 통합.
  - `tests/smoke_backup_to_github.py` 8단계 검증 신설.
  - GitHub Private Repo 의 `backup` orphan 브랜치 초기화 (운영자 수동 1회).
- **다음 단계 권장 순서**: Step 1 컨펌 → Step 2 코드 구현 → 로컬 dry-run smoke → LightSail 1회 백업 실 실행 → 1주 운영 안정 확인 → Phase 5 진입.

### 2.1 Phase 3 — Chronicle SQLite 전환 (2026-06-02 ~ 2026-06-05)
- **Step 1 (문서 사양 확정, `e608ad8`)**: `Doc/features/data_persistence/*` 4 파일에 Chronicle 스키마 v2 (5 테이블 + FTS5) / API 16개 / 호출자 마이그레이션 매트릭스 / .md 파싱 룰 / 에러 정책 P3E1~E5 정의.
- **Step 2 (코드 구현, `935203f`)**:
  - 신설 3 파일: `src/storage/migrations/v002_chronicle.py` (5 테이블 + FTS5 가용성 자동 감지) / `src/storage/chronicle_sqlite_backend.py` (`_SQLiteChronicleBackend` + `parse_full_md` 5섹션 분류) / `src/storage/chronicle_repo.py` (`_DriveChronicleBackend` + 16 공개 API + 백엔드 분기).
  - 수정 4 파일: `state_store.py` (re-export) / `chronicle_writer.py` / `context_retriever.py` / `backfill.py`.
  - 핵심 버그 수정: `INSERT OR REPLACE` → `INSERT ... ON CONFLICT DO UPDATE` 패턴 전환 (PK 충돌 시 FK CASCADE 자식 row 손실 방지).
- **Step 3 (이관 스크립트 + smoke, `4204c9b` + `156c9d3`)**:
  - `scripts/migrate_chronicles_to_sqlite.py` (8단계, idempotent, CLI 4 옵션).
  - `tests/smoke_chronicle_repo.py` (7/7 PASS).
  - **실 서버 이관 1회 성공 (2026-06-05)**: 40 entries / 40 .md / 160 sections / 160 FTS rows / 1 backfill_state, **skipped 0건**, 카운트 100% 일치, 소요 63.34s. 평균 섹션 4.0 → 분류 룰이 운영 본문 100% 적용 검증.

### 2.2 Phase 2 — SQLite 백엔드 (A/B 도메인) (2026-05-30 ~ 2026-06-02)
- **Step 1 (문서, `e8e218f`)**: 02 API Spec + 03 State Logic 에 Phase 2 사양 정의.
- **Step 2 (코드, `c0aaef5`)**: `src/storage/sqlite_backend.py` (`_SQLiteBackend`) / `src/storage/migrations/runner.py` (마이그레이션 러너) / `v001_initial.py` (5 테이블 + schema_version 메타).
- **부트스트랩 버그 수정 (`1d73773`)**: `main.py` 의 `load_dotenv()` 를 `from src.*` import 보다 먼저 호출하도록 정정. state_store 가 import 시점에 `STATE_STORE_BACKEND` 를 읽기 때문.
- **Step 3 (이관 스크립트, `4c5af9d`)**: `scripts/migrate_drive_to_sqlite.py` (5단계, idempotent, dry-run 지원). 실 서버에서 portfolio/split_orders/theme_context/scalp_session/trades 5 도메인 이관 성공.
- **부팅 print 보강 (`74934a3`)**: M6 C05 점검 대상 — `_DriveBackend` / `_SQLiteBackend` / `_DriveChronicleBackend` / `_SQLiteChronicleBackend` 4 케이스 모두 로드 시 stdout 에 백엔드 정보 출력.

### 2.3 Phase 1 — 추상화 레이어 (`state_store`) (2026-05-29 이전)
- `src/storage/state_store.py` 신설 — `_DriveBackend` + 도메인 API 11개 (A/B 도메인).
- **38 호출 마이그레이션**: `orchestrator / risk_monitor / slack_interface / backtester / ai_logic / scalp_session_store / scalp_trainer` 의 `logger.{load,save}_json_from_gdrive` 직접 호출을 `state_store.*` 도메인 API 로 치환.
- commit `1652b24` + 호출 매트릭스 실측 보정 `dad168e`.

### 2.4 부수 작업
- **OAuth invalid_grant 런타임 자동 처리 (`88a3a01`)**: `drive_client.py` 의 3-Layer 안전망 + `oauth_token.py` datetime 타임존 수정 + `main.py` 의 OAuth notifier 등록. `[Drive Read Fallback] invalid_grant` 반복 에러 해결.
- **M6 안정성 점검 도구 (`3591d75` + `a73625b` + `3bcb6d1`)**: `scripts/m6_stability_check.py` — 자동 점검 매트릭스 (C01~C18) + Day 1~3 PASS 동기화 + C17/C18 오탐 제거. **본 작업은 별도 agent 가 담당** — 본 핸드오버에서는 컨텍스트만 인지하고 직접 수정하지 않도록 주의.
- **Atomic Doc 구조 정리**: 기존 `GEMINI_SYS.md` / `GEMINI_DETAIL_*.md` 를 `Doc/system_architecture.md` + `Doc/features/[기능명]/*.md` 원자적 구조로 분리. `.cursor/rules/autostock.mdc` 의 파일명 규칙 정정.

---

## 3. 보류 / 진행 예정 작업

### 3.1 M6 안정성 모니터링 (🟡 진행 중, 별도 agent 담당)
- **대상**: SQLite 전환된 봇이 1~3일 운영 환경에서 안정 동작하는지 검증.
- **도구**: `scripts/m6_stability_check.py` (자동 점검 매트릭스 C01~C18).
- **진척**: Day 1~3 PASS 동기화 완료. Day 4 이후 계속 진행 또는 Phase 4 로 전환 가능.
- **본 작업 영역**: 별도 agent 가 작업 중이므로 본 핸드오버 agent 는 직접 수정 금지. 컨텍스트만 인지.

### 3.2 Phase 3 운영 활성 결정 (사용자 의사결정 대기)
- 서버 `.env` 의 `STATE_STORE_BACKEND=sqlite` 가 이미 활성 상태인지 확인 필요.
  - **A/B 도메인** (Phase 2) 은 이미 SQLite 운영 중 (M6 Day 1~3 PASS 가 이를 검증).
  - **C/D 도메인** (Phase 3) 은 이관은 성공했으나 **봇 운영에서 SQLite 경유로 read/write 가 실제 발생하는지** 는 사용자가 결정.
- 활성 시 확인 사항:
  1. 봇 재기동 시 `[STATE_STORE] backend=sqlite db_path=...` + `[CHRONICLE_REPO] backend=sqlite db_path=...` 둘 다 출력.
  2. Chronicle 작성 (장 마감 트리거) 시 `chronicle_entries` 1 row 증가, `chronicle_reports` 1 row 증가, `chronicle_report_sections` ≈ 4 row 증가, `chronicle_search` ≈ 4 row 증가.
  3. `context_retriever.search_similar_guidelines(...)` 호출 시 SQLite 경유로 정상 작동.

### 3.3 Phase 4 — 백업 정책 (Step 1+2 완료, Step 3 대기)
- **Step 1 (사양 정의)**: 완료 (2026-06-07, commit `7db5f52`). 4 사양서 + HANDOVER 갱신.
- **Step 2 (코드 구현)**: 완료 (2026-06-07, 로컬 미commit). 신설 4 파일 + main.py + .gitignore + smoke 15/15 PASS. 상세는 §2.0a 참조.
- **Step 3 (운영자 검증)**: 미착수. 다음 작업 단위:
  1. **GitHub PAT 발급** (`repo` scope) + Private Repo URL 결정 (별도 repo 또는 본 repo 의 backup orphan 브랜치 — 본 PR 은 후자 가정).
  2. **`.env` 갱신**: 13종 `BACKUP_*` 키 추가 (사양 §02 §9.1):
     - `BACKUP_ENABLED=true`
     - `BACKUP_REPO_URL=https://github.com/<owner>/<repo>.git`
     - `BACKUP_GITHUB_TOKEN=<PAT>`
     - 나머지는 기본값 사용 가능.
  3. **LightSail 에서 1회 수동 백업**: `python scripts/backup_sqlite_to_github.py --kind daily` → backup 브랜치 자동 신설 + commit 1건 + 슬랙 `[Backup OK]` 수신.
  4. **봇 재기동** (`s-restart`) → 부팅 stdout `[BACKUP] backup jobs registered: daily=18:00, weekly=sunday 22:00, monthly=day01 00:30` 매칭 확인.
  5. **복원 시뮬레이션** (다른 PC 또는 동일 PC `/tmp` 대상): `python scripts/restore_sqlite_from_github.py --latest --kind daily --target-path /tmp/test.db --no-slack` → integrity_check ok 확인.
  6. **1주 운영 안정**: 일간 백업 7회 + 주간 백업 1회 모두 슬랙 `[Backup OK]` 수신.
- **회귀 안전망 (Phase 1~3 무영향 보장)**: 기본값 `BACKUP_ENABLED=false` 로 운영자 명시 활성화 전까지 schedule 등록 0건. smoke 1번 단계로 이미 검증됨.

### 3.4 Phase 5 — Drive 코드 통째 정리 (⏳ 미착수, 최후 단계)
- **대상 (모두 Drive 모드 전용으로 잔존)**:
  - `src/storage/state_store.py` 의 `_DriveBackend`.
  - `src/storage/chronicle_repo.py` 의 `_DriveChronicleBackend`.
  - `src/memory/drive_client.py` 의 chronicle 관련 함수들 (`read_master_index`, `write_master_index`, `append_index_entry`, `read_text_relative`, `write_text_relative`, `file_exists_relative`, `list_files_under`, `delete_file_relative`, `read_json_relative`, `write_json_relative`, `MASTER_INDEX_REL`, `CHRONICLES_ROOT`).
  - `src/memory/backfill.py` 의 Drive 모드 분기 헬퍼 (`_collect_md_files_recursive`, `_list_folder_items`, `_classify_md`, `_is_sqlite_backend` 의 else 절).
  - `src/memory/lifecycle.py` (Drive 임시 파일 TTL 청소).
  - `scripts/migrate_master_index_v2.py` (v1→v2 Drive 호환 스크립트).
- **선결 조건**:
  1. Phase 4 백업 정책 완료 (Drive 의존 0 로 갈 수 있는 안전망).
  2. SQLite 모드 운영 4주 이상 무사고.
  3. 운영자가 "Drive 백업 채널은 영구 폐기" 결정.
- **주의**: 본 작업은 큰 회귀 위험. 단일 PR 로 진행하되 사전에 사양서 (Phase 5 섹션) 작성 + 컨펌 후 진행.

### 3.5 기타 검토 사항
- **FTS5 한국어 토크나이저 개선** (P3.5 후보): `unicode61 remove_diacritics 2` 토크나이저는 한국어 단어 분할이 약함 ('패닉' 단독 검색 실패 사례 발견). `icu` 토크나이저 또는 ngram tokenizer 도입 검토. 운영 사용 빈도가 낮으면 보류.
- **임베딩 활성** (v3.5 후보): `chronicle_entries.embedding_vector` BLOB 컬럼은 이미 예약됨. 실제 임베딩 생성/검색 활성은 별도 Phase.

---

## 4. 핵심 파일 위치 매트릭스

### 4.1 저장 백엔드 (Phase 1~3)
| 역할 | 파일 | 비고 |
|---|---|---|
| 도메인 API (A/B/C/D 통합) | `src/storage/state_store.py` | 외부 호출자가 import 하는 유일한 진입점 |
| A/B SQLite 백엔드 | `src/storage/sqlite_backend.py` | `_SQLiteBackend` |
| C/D Chronicle Repository (분기) | `src/storage/chronicle_repo.py` | `_DriveChronicleBackend` 내부 구현 포함 |
| C/D SQLite 백엔드 | `src/storage/chronicle_sqlite_backend.py` | `_SQLiteChronicleBackend` + `parse_full_md` |
| 마이그레이션 러너 | `src/storage/migrations/runner.py` | `apply_pending(conn)` |
| 스키마 v1 (A/B) | `src/storage/migrations/v001_initial.py` | 5 테이블 + schema_version |
| 스키마 v2 (C/D) | `src/storage/migrations/v002_chronicle.py` | 4 테이블 + FTS5 (옵션) |
| Drive→SQLite 이관 (A/B) | `scripts/migrate_drive_to_sqlite.py` | 5단계 |
| Drive→SQLite 이관 (C/D + backfill_state) | `scripts/migrate_chronicles_to_sqlite.py` | 8단계 |
| smoke 테스트 (A/B) | `tests/smoke_state_store_sqlite.py` | 4 단계 |
| smoke 테스트 (C/D) | `tests/smoke_chronicle_repo.py` | 7 단계 |

### 4.2 호출자 (state_store 만 사용)
| 파일 | 도메인 | 비고 |
|---|---|---|
| `src/execution/orchestrator.py` | A (portfolio / split_orders / theme_context) | Phase 1 마이그레이션 완료 |
| `src/execution/risk_monitor.py` | A | Phase 1 마이그레이션 완료 |
| `src/utils/slack_interface.py` | A (trades) | Phase 1 마이그레이션 완료 |
| `src/strategy/ai_logic.py` | A (theme_context) | Phase 1 마이그레이션 완료 |
| `src/memory/scalp_session_store.py` | A (scalp_session / portfolio) | Phase 1 마이그레이션 완료 |
| `backtester.py` | A (portfolio) | Phase 1 마이그레이션 완료 |
| `src/memory/chronicle_writer.py` | C/D | Phase 3 마이그레이션 완료 |
| `src/memory/context_retriever.py` | C | Phase 3 마이그레이션 완료 |
| `src/memory/backfill.py` | C/D + backfill_state | Phase 3 마이그레이션 완료. **Drive 모드 분기 잔존** (Phase 5 정리 대상) |

### 4.3 문서 트리
```
Doc/
├── HANDOVER.md                                    ← 본 문서
├── system_architecture.md                          ← 시스템 골격 / 환경변수 / B-Type 에러 정책
└── features/
    ├── ai_investment_decision/
    │   ├── ai_investment_decision_README.md       ← 인덱스
    │   ├── 01_ai_investment_decision_requirements.md
    │   ├── 02_ai_investment_decision_api_spec.md
    │   └── 03_ai_investment_decision_state_logic.md
    ├── data_persistence/                          ← Phase 1~3 핵심 사양
    │   ├── data_persistence_README.md
    │   ├── 01_data_persistence_requirements.md
    │   ├── 02_data_persistence_api_spec.md         (Phase 2/3 API)
    │   └── 03_data_persistence_state_logic.md      (Phase 2/3 동작 로직 + 실 서버 이관 결과)
    ├── kis_token/
    ├── market_calendar/
    ├── market_chronicles/                         ← Chronicle 도메인 자체 사양
    │   └── (README + 01/02/03)
    ├── scalp_logic/
    └── telegram_pipeline/
```

원자적 구조 규칙 (`.cursor/rules/autostock.mdc`):
- 파일명 패턴: `[기능명]_README.md` / `01_[기능명]_requirements.md` / `02_[기능명]_api_spec.md` / `03_[기능명]_state_logic.md`.
- `[기능명]` 접두사 필수 (예: `01_data_persistence_requirements.md`).

### 4.4 운영 / 스크립트
| 파일 | 역할 |
|---|---|
| `main.py` | 봇 진입점. `load_dotenv()` 가 `from src.*` import 보다 먼저 호출되어야 함 (Phase 2 부트스트랩 정정) |
| `scripts/_common.py` | scripts/*.py 공통 부트스트랩 (sys.path / .env / print_flush) |
| `scripts/m6_stability_check.py` | M6 안정성 자동 점검 (별도 agent 작업 영역) |
| `scripts/migrate_master_index_v2.py` | Master Index v1→v2 변환 (Drive 모드 호환 잔존) |

---

## 5. 운영 정책 / 결정사항 (반드시 준수)

### 5.1 코딩 표준 (`.cursor/rules/autostock.mdc` 발췌)
- 모든 대화, 설명, 코드 주석은 **한국어**.
- `.py` 파일은 **UTF-8 인코딩**, 코드 본문 / 변수명 / 주석에 **이모지 금지** (단, 슬랙 메시지는 허용).
- 변수: 시스템 전역 유니크 + 직관적 + 간결. 구조체는 접미사 (`_list`, `_dict`, `_map`).
- 함수: DRY (동일 로직-동일 결과는 재사용). 결과 도메인 / 목적 다르면 별도 정의.
- `.json` / `.env` 파일 내용은 **직접 분석 / 활용 금지** (보안). 단, 키 이름만 참조 가능.

### 5.2 작업 워크플로우 (Strict MD Management)
1. 작업 시작 = `Doc/HANDOVER.md` + 관련 `Doc/features/[기능명]/*.md` 분석.
2. **요구사항 변경 시 = 선(先) 설계 후(後) 개발**. 사양서 먼저 업데이트 후 컨펌, 그 다음 코드 수정.
3. 코드 완료 후 = 실제 구현된 로직을 사양서에 **Post-Update** 반영 (변수명 / 함수 시그니처 / 매트릭스 / 카운트 등).
4. 기능 업데이트 / 변경 / 분리 시 = 버전별 구현율 (%) 재계산하여 사양서 반영. 이전 내용 삭제 금지, 누적 보존.

### 5.3 Git 커밋 메시지 정책
- **핵심만 2~3줄**. 상세 설명은 본문 대신 `자세한 내역은 Doc/features/[기능명]/03_*_state_logic.md §N 참조` 1줄로 대체.
- 단일 작업 단위 = 단일 PR / 단일 커밋. 멀티 영역 묶음 금지.
- HEREDOC 사용 (`git commit -m "$(cat <<'EOF' ... EOF\n)"`).

### 5.4 Gatekeeping (B-Type 보고)
- 사용자 개입 필요 에러 (Drive 권한 / 용량 부족 / OAuth invalid_grant) 발생 시 즉시 **Pause** + 슬랙 보고 + 대기.
- 구현 모호 / 더 효율적 대안 (토큰 절약 등) 발견 시 근거와 함께 제안 먼저, 사용자 컨펌 후 수정.

### 5.5 환경변수 (`.env`, 본 작업 영역 관련)
| 키 | 값 | 효과 |
|---|---|---|
| `STATE_STORE_BACKEND` | `drive` (기본) / `sqlite` / 그 외 (→ drive 폴백) | A/B/C/D 모두 SQLite 경유로 read/write. 모듈 import 시 1회 결정 |
| `STATE_STORE_DB_PATH` | 기본 `data/sqlite/autostock.db` | SQLite 파일 경로 |
| `AUTO_MIGRATE_V2` | `1` / `true` / `yes` 시 활성 | Master Index v1→v2 자동 변환 (Drive 모드 전용 호환 옵션) |

부팅 시 다음 메시지 출력 (M6 C05 점검 대상):
```
[STATE_STORE] backend=drive          또는  backend=sqlite db_path=...
[CHRONICLE_REPO] backend=drive       또는  backend=sqlite db_path=...
```

### 5.6 에러 정책 분류 (확정)
- **A-Type**: 자동 복구 가능 (재시도 / 폴백). 로그만.
- **B-Type**: 사용자 개입 필요. 즉시 Pause + 슬랙 보고.
- **C-Type**: 봇 종료급 (회복 불가). 슬랙 + systemd 재기동.
- **P3E1**: .md 헤딩 매칭 실패 → `section_key=unknown` 으로 본문 보존.
- **P3E2**: FTS5 빌드 미지원 → stderr 경고 + 정규식 폴백.
- **P3E3**: .md 본문 누락 → `skipped_list` 격리 후 인덱스는 계속.
- **P3E4**: FK CASCADE 안전장치 → `chronicle_delete_entry(delete_report=False)` 옵션 제공.
- **P3E5**: SQLite IO 실패 → 예외 전파 → 상위에서 B-Type Pause.

---

## 6. 다음 세션의 우선순위 (권장)

순서대로:

1. **(즉시)** Phase 4 Step 2 commit + push (사용자 결정):
   - 본 §2.0a 의 신설 4 파일 + main.py + .gitignore 변경을 단일 commit 으로 묶기.
   - 추천 메시지: `feat(data_persistence): Phase 4 Step 2 - 백업/복원 코드 구현 + smoke 15/15 PASS`.
2. **(commit 후)** Phase 4 Step 3 운영자 검증 (§3.3 Step 3 의 6단계).
   - 핵심: `.env` 13종 키 추가 + LightSail 1회 수동 백업 + 봇 재기동 부팅 로그 확인 + 복원 시뮬레이션 + 1주 운영 안정.
3. **(병행 가능)** Phase 3 운영 활성 여부 확인 (서버 `.env` `STATE_STORE_BACKEND=sqlite` 상태 + Chronicle write 1회 SQLite row 증가).
4. **(Phase 4 완료 + 4주 안정)** Phase 5 Drive 코드 통째 정리. 큰 회귀 위험이므로 사전 사양 작성 + 컨펌 필수.
5. **(여유 시)** FTS5 한국어 토크나이저 / 임베딩 활성 검토 (Phase 3.5).

M6 안정성 모니터링 (`scripts/m6_stability_check.py`) 은 별도 agent 영역으로 본 핸드오버 agent 는 직접 수정 금지 (§7.1 참조).

---

## 7. 알려진 이슈 / 주의사항

1. **`scripts/m6_stability_check.py` 는 별도 agent 작업 영역**. 본 핸드오버 agent 는 컨텍스트만 인지하고 직접 수정 금지. M6 관련 변경 필요 시 사용자에게 보고 후 별도 agent 작업으로 이관.
2. **`backfill.py` 의 Drive 모드 분기**는 Phase 5 정리 대상으로 의도적 잔존. 검색 시 잔존 호출이 나와도 정상 (docstring 에 `[Drive 모드 전용]` 표기됨).
3. **FTS5 한국어 단일 토큰 검색 한계**: `'패닉'` 단독은 매칭 실패, `'패닉셀'` 은 매칭 성공 (운영 본문에 따라 다름). 운영 사용 시 prefix 매칭 (`'패닉*'`) 또는 복합 키워드 권장.
4. **`INSERT OR REPLACE` 금지** (chronicle 영역). PK 충돌 시 자식 row CASCADE 손실 위험. `INSERT ... ON CONFLICT DO UPDATE` 패턴 사용. 새 코드 작성 시 주의.
5. **`main.py` 의 `load_dotenv()` 위치 고정**: `from src.*` import 전에 호출되어야 함. 재배치 금지.
6. **외부 의존성 (`yfinance` / `google.genai`) 로컬 미설치**: 로컬 개발 PC 에서 봇 전체 import 가 실패할 수 있음. storage 모듈 단독 + smoke 테스트는 동작. 실 서버 (LightSail) 에서는 모두 설치됨.

---

## 8. 빠른 참조 — 자주 쓰는 명령

```bash
# 환경 검증
python tests/smoke_state_store_sqlite.py
python tests/smoke_chronicle_repo.py

# 마이그레이션 (운영 서버, 1회성)
python scripts/migrate_drive_to_sqlite.py --dry-run
python scripts/migrate_drive_to_sqlite.py --no-slack
python scripts/migrate_chronicles_to_sqlite.py --dry-run
python scripts/migrate_chronicles_to_sqlite.py --no-slack

# 코드 검증
python -m py_compile src/storage/*.py src/storage/migrations/*.py

# M6 안정성 점검 (별도 agent 영역, 참조용)
python scripts/m6_stability_check.py

# Master Index v1→v2 (Drive 모드 환경 한정)
python scripts/migrate_master_index_v2.py --dry-run
```

---

## 9. 변경 이력

| 일자 | 갱신 사유 | 작성자 (agent) |
|---|---|---|
| 2026-06-05 | Phase 3 Step 3 실 서버 이관 성공 직후 초안 작성. Phase 1~3 완료 + Phase 4/5 보류 정리. | Cursor Agent (Opus 4.7) |
| 2026-06-07 | Phase 4 Step 1 사양 정의 완료. `Doc/features/data_persistence/*` 4 파일 갱신 (README v1.3 + §1.4/§11/§12 요구사항 + §9 API + §13 동작 흐름). 사용자 결정 5건 컨펌 후 반영 (트리거=봇 내부 schedule / 주기=일간+주간+월간 / 저장=본 repo backup orphan 브랜치 / 형식=VACUUM INTO+gzip / 보관=계층형 30일+12주+12개월). 본 HANDOVER §1/§2.0/§3.3/§6 갱신. commit `7db5f52`. | Cursor Agent (Opus 4.7) |
| 2026-06-07 | Phase 4 Step 2 코드 구현 완료. 신설 4 파일 (`backup_scheduler.py` + `backup_sqlite_to_github.py` + `restore_sqlite_from_github.py` + `smoke_backup_to_github.py`) + 수정 2 파일 (`main.py` + `.gitignore`). 로컬 smoke **15/15 PASS, elapsed 1.1s**. py_compile + ReadLints 0건. macOS sandbox 가 git hooks 차단하지만 운영 LightSail 영향 없음. 03 §13.9 체크리스트 [x] 전환 + §13.12 Step 2 Post-Update 작성. README v1.3 Step 2 100% 마킹. 본 HANDOVER §1/§2.0a/§3.3/§6 갱신. (commit 대기) | Cursor Agent (Opus 4.7) |

> 다음 작업이 끝날 때마다 본 §9 에 한 줄 추가 + 영향 받은 섹션 갱신. 그래야 다음 PC 의 agent 가 이질감 없이 받음.
