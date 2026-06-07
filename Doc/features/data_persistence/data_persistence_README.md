# Data Persistence (Feature Index)

## 구현율
- v1.0 (Phase 1, 2026-06-02): 도메인 API(`state_store`) 추상화 레이어 신설. 백엔드는 Drive 그대로 위임 — **사양 정의 + 구현 100%**.
- v1.1 (Phase 2, 2026-06-02): A/B 도메인 SQLite 백엔드 + 마이그레이션 러너 + 1회성 이관 스크립트.
  - Step 1 (문서 사양 확정): **100%** (commit `e8e218f`).
  - Step 2 (백엔드+러너 구현): **100%** (commit `c0aaef5` + `1d73773` 보정).
  - Step 3 (이관 스크립트+검증): **100%** (이관 1회 성공, A/B 5 도메인 카운트 일치).
  - Step 4 (실 서버 활성화 — `.env` 의 `STATE_STORE_BACKEND=sqlite` 적용 + `s-restart`): **100%** (2026-06-02 15:58 KST, `Bolt app is running!` 정상 기동 확인).
  - Step 5 (M6 운영 안정성 검증 — 1~3일 모니터링): **Day 1~3 PASS (2026-06-02 ~ 06-05)** — 별도 agent 가 `scripts/m6_stability_check.py` 를 1일 단위로 순회. Day 1 기록은 `./03_data_persistence_state_logic.md §11.8.3.1`, Day 2/3 기록은 `§11.8.3.2` 참조. **Phase 2 SQLite 백엔드 안정성 검증 완료**(68h 무중단 + `PRAGMA integrity_check=ok` + 슬랙 응답성 + 도메인 write + Drive 폴백 누출 0건). 표면화된 점검 도구 보강 3건(S1 C08 윈도우/regex, S2 C09 since ISO, S3 C17~C19 헬퍼)은 `§11.8.4` 확정 명세로 함께 정리.
- v1.2 (Phase 3, 본 단계): Market Chronicles **C/D 도메인 SQLite 전환** + **FTS5 풀텍스트** + **섹션 정규화**.
  - Step 1 (문서 사양 확정): **100%** (commit `e608ad8`).
  - Step 2 (`chronicle_repo` + 스키마 v2 + 호출부 전환): **100%** (commit `935203f` — 신설 3 파일 + 수정 4 파일 + 라운드트립 검증 PASS).
  - Step 3 (`scripts/migrate_chronicles_to_sqlite.py` + smoke + 검증): **100%** (이관 스크립트 8단계 + tests/smoke_chronicle_repo.py 7/7 PASS + **실 서버 이관 1회 성공** — 2026-06-05, 40 entries / 160 sections / 160 FTS rows, skipped 0건, 카운트 100% 일치, 소요 63.34s).
- v1.3 (Phase 4, 본 단계 시작): **SQLite → GitHub Private Repo 자동 백업 + 수동 복원**.
  - Step 1 (문서 사양 확정): **100%** (본 PR — `01/02/03_data_persistence_*.md` 의 Phase 4 섹션 신설).
  - Step 2 (`backup_scheduler` + `scripts/backup_sqlite_to_github.py` + `scripts/restore_sqlite_from_github.py` 신설): **0%** (Step 1 컨펌 후).
  - Step 3 (smoke 테스트 + 복원 시뮬레이션 + 1주 운영 검증): **0%**.
- v1.4 (Phase 5, 예정): Drive/OAuth 인프라 제거 + 문서 정리. Phase 4 완료 + SQLite 4주 안정 운영 후 진행.

## 기능 요약
본 봇의 영속화 책임을 **단일 도메인 API (`src/storage/state_store.py`)** 로 일원화한다.
호출자(orchestrator/risk_monitor/slack_interface 등)는 Drive/SQLite/PG 같은 백엔드를 알 필요 없이
도메인 메서드(`get_portfolio`/`save_split_orders` 등) 만 호출한다.

## 설계 동기
- **OAuth 만료 반복 문제**: Drive Testing 모드의 7일 만료 + invalid_grant 자동 Pause 부담 누적.
- **거래 IO 성능**: 매분 Drive round-trip → SQLite 로컬 IO 마이크로초급 전환 여지 확보.
- **스키마 진화**: master_index v1→v2(v3.4) 같은 변화가 호출자 코드에 노출되지 않게 격리.
- **테스트 용이성**: 메모리 백엔드 주입으로 단위 테스트 단순화.

## 도메인 분류
| 도메인 | 데이터 | 메서드 | 적용 Phase |
|---|---|---|---|
| A. 운영 상태 | portfolio / split_orders / theme_context / scalp_session | `get_*` / `save_*` | Phase 1/2 |
| B. 거래 이력 | trades (append-only) | `list_trades` / `replace_trades` | Phase 1/2 |
| 일괄 초기화 | A+B 4개 reset | `reset_app_data` | Phase 1/2 |
| C. Chronicle 인덱스 | master_index.entries (v2) | `chronicle_repo.list_entries / append_entry / replace_entries / ...` | **Phase 3** |
| D. Chronicle 본문 | reports/.md (5섹션 정규화 + FTS5) | `chronicle_repo.save_report / get_report / list_sections / search_fulltext` | **Phase 3** |
| 운영 상태 (Chronicle) | backfill_state (단일 row) | `chronicle_repo.get_backfill_state / save_backfill_state` | **Phase 3** |

## 문서 인덱스
- `./01_data_persistence_requirements.md`: 요구사항·제약·도메인 책임
- `./02_data_persistence_api_spec.md`: 공개 API 시그니처·반환 규약
- `./03_data_persistence_state_logic.md`: 백엔드 전환 로직·스키마 진화·마이그레이션 정책

## 연관 기능
- `../market_chronicles/`: C/D 도메인 (Phase 3)
- `../scalp_logic/`: scalp_session 영속화
- `../kis_token/`: 별개 도메인 (OAuth/KIS 토큰)

## Phase 로드맵 (참고)
1. **Phase 1 (완료, commit `1652b24` + `dad168e`)**: `state_store` 도메인 API + Drive 위임 백엔드. 호출자 6 파일 교체 (32 호출 + 6 import). **봇 동작 100% 동일**.
2. **Phase 2 (완료)**: SQLite 백엔드 + `data/sqlite/autostock.db` + 마이그레이션 러너 + 수동 이관 스크립트. A/B 도메인만.
   - 환경변수 `STATE_STORE_BACKEND` (기본 `drive`, `sqlite` 명시 시 전환).
   - 환경변수 `STATE_STORE_DB_PATH` (기본 `data/sqlite/autostock.db`).
   - 이관 후 Drive 데이터는 그대로 보존 (Phase 5 에서 일괄 정리).
   - `logger.record_trade` 의 self-call 은 Phase 2.5 에서 별도 처리.
3. **Phase 3 (완료)**: Market Chronicles C/D 도메인을 SQLite + FTS5 + `chronicle_report_sections` 정규화로 전환.
   - 신규 모듈 `src/storage/chronicle_repo.py` 도입. `state_store` 는 chronicle 메서드를 re-export.
   - SQLite 스키마 v2: `chronicle_entries` / `chronicle_reports` / `chronicle_report_sections` / `chronicle_search`(FTS5) / `chronicle_backfill_state`.
   - `embedding_vector BLOB` 컬럼은 사전 예약 (v3.5 활성).
   - 호출부 전환: `chronicle_writer` / `backfill` / `context_retriever` (3 파일, 20 호출).
   - `lifecycle.py` (Drive 임시 파일 TTL 청소) 와 `migrate_master_index_v2.py` 는 Phase 3 비대상 (Phase 5 에서 통째 정리/제거).
   - 동일 환경변수 `STATE_STORE_BACKEND=sqlite` 로 A/B + C/D 모두 활성. Phase 2 와 같은 백엔드 분기 정책 계승.
4. **Phase 4 (본 단계, Step 1 시작)**: SQLite → GitHub Private Repo (`backup` orphan 브랜치) 자동 백업 + 수동 복원.
   - **트리거**: 봇 내부 `schedule` (별도 thread). cron / systemd timer 미사용.
   - **주기**: 일간 18:00 KST (장 마감 후) + 주간 일요일 22:00 KST.
   - **저장**: 본 repo 의 `backup` orphan 브랜치 (별도 작업 디렉터리 single-branch clone). main 영향 0.
   - **형식**: `VACUUM INTO` + gzip (`.db.gz`). WAL 통합 일관성 보장 + 즉시 sqlite3 복원 가능.
   - **보관**: 일간 30일 + 주간 12주 + 월간 12개월 계층형. 회전 알고리즘으로 repo 사이즈 안정화.
   - **슬랙 보고**: 성공/실패 모두 보고. 실패 시 B-Type Pause.
   - **복원**: 수동만 (`scripts/restore_sqlite_from_github.py`). 자동 복원 미지원.
5. **Phase 5 (예정)**: Drive/OAuth 인프라 통째로 제거 + 문서 정리. Phase 4 완료 + SQLite 4주 안정 운영 후 진행.
