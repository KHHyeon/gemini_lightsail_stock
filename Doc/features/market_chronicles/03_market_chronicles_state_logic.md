Market Chronicles State & Logic

1) 상태 모델

S0. Idle

  - 평시 대기 상태.

S1. Triggered

  - 트리거 조건 충족(T-Day), 백필 큐 존재, 또는 오케스트레이터가 위임한 외부
    인제스트 결과 수신(예: Telegram Pipeline). Market Chronicles 는 외부 수집기를
    직접 호출하지 않는다.
  - **거래일 가드 (v1.1, 2026-05-25)**: T-Day 트리거 평가 이전에
    `market_calendar.is_trading_day(now_kst())` 를 먼저 확인. KST 주말/공휴일이면
    S1 자체를 거부하고 `(False, "T-Day 크로니클은 KST 거래일에만 작성합니다 ...")` 로 즉시 종료.
    백필(S1-B) 은 별도 경로(`backfill._write_chronicle_for_event`) 에서 처리하며 본 가드의 영향을 받지 않는다.

S1-K. 시간대 기준

  - 모든 날짜/시각 처리는 **KST (Asia/Seoul)** 고정.
  - `write_chronicle_for_today` 의 `today` 문자열: `now_kst().strftime("%Y-%m-%d")`.
  - `context_retriever._recency_bonus` 의 age 계산: `now_kst().date() - d` (서버 로컬·UTC 영향 차단).

S2. Generated

  - 리포트 본문 생성 완료.

S3. Indexed(v2)

  - master_index에 v2 엔트리 적재 완료.

S4. Retrieved

  - 현재 시장 컨텍스트 기반으로 유사 지침 검색 완료.

S5. Injected

  - 3블록 컨텍스트를 AI 프롬프트에 주입.

SP. Paused(B-Type)

  - 사용자 개입 필요 상태. 완료 확인 후 복귀.

2) 데이터 스키마 로직 (master_index v2)

Root

  - version: 2
  - entries: list[entry_dict]

entry_dict (핵심)

  - 식별/메타: id, date, trigger, report_rel_path, source
    - source 필드는 인제스트 출처를 구분하기 위한 자유 문자열이며, 외부 인제스트
      파이프라인이 추가될 때마다 본 문서에 허용값을 별도 추가한다(예: "telegram").
      값 정의 자체는 Market Chronicles 책임으로 유지하고, 외부 모듈에 의존하지 않는다.
  - 노출(가독성): market_state, context_tags_list, action_preview
  - 보조(내부): phrases_list, embedding_vector
  - 운영 타임스탬프: reindexed_at?, migrated_at?

market_state

  - regime (enum 8종)
  - regime_label (자유형 라벨)
  - main_actor
  - sentiment

3) 검색 점수화 로직 (v2)

단계 1. context_tags_list 자카드

  - High/Mid/Low 구간 가점(최우선).

단계 2~3. market_state.regime

  - 정확 일치 가점 + 인접 그룹 가점(REGIME_NEIGHBOR_MAP).

단계 4~5. 보강 비교

  - main_actor 부분 일치.
  - sentiment 일치(동의어 맵 포함).

단계 6. phrases_list 보조 자카드

  - 태그 매칭이 약할 때만 발동.

단계 7. 최근성 보너스

  - 30/90/180일 구간 가점.

단계 8. 임베딩 보너스(예약)

  - v3.4에서는 비활성, v3.5에서 활성 예정.

4) 마이그레이션 상태 전이

M1. Scan

  - v1 엔트리 분류(즉시 매핑 가능/AI 보강 필요).

M2. Backup

  - 적용 직전 원본 인덱스 백업.

M3. AI Enrichment

  - 부족 필드 보강(phrases_list, market_state, context_tags_list).

M4. Apply

  - v2 전체 쓰기(단일 적용), 결과 요약 출력.

5) 예외/폴백 로직

E1. v1 감지

  - 기본: DriveSchemaMismatchError -> Pause.
  - 옵션: AUTO_MIGRATE_V2=1일 때 in-process 자동 변환.

E2. AI 실패

  - 정규식/기본값 폴백으로 필드 채움.
  - regime 결정 불가 시 SIDEWAYS 안전 폴백 + 원문 라벨 보존.

E3. Drive 일시 장애

  - 부분 적용 금지(백업 후 단일 apply).
  - 실패 시 재실행 가능한 idempotent 흐름 유지.

E4. OAuth 토큰 만료/취소 (invalid_grant, B-Type)

  - 트리거: 런타임 Drive 호출 중 `invalid_grant` / `Token has been expired or revoked` 감지.
  - 처리: `drive_client._handle_oauth_expiry_if_needed` 가 자동 Pause + 슬랙 알림 + `_DRIVE_SERVICE` 캐시 무효화.
  - 진입점: `read_json_relative` / `write_json_relative` (L1), `logger.{load,save}_json_from_gdrive` 의 fallback (L2 안전망).
  - 재개: `python scripts/drive_oauth_setup.py --no-browser` 로 재발급 후 슬랙 `완료` 입력 시 `try_resume_after_user_ack` 가 재검증.
  - 사전 회피: Google Cloud Console 의 OAuth 동의 화면을 Production 으로 승격하여 7일 refresh_token 만료를 제거 권장.

6) 저장소 백엔드 분기 (v3.5 / Phase 3)

  Market Chronicles 의 모든 R/W 는 `src.storage.chronicle_repo` 를 단일 진입점으로 사용한다.
  chronicle_repo 는 import 시점에 환경변수 `STATE_STORE_BACKEND` (기본 `drive`) 를 읽어 다음 두 백엔드 중 하나를 선택한다.

  - **Drive 모드** (`STATE_STORE_BACKEND=drive` 또는 미설정):
    - `_DriveChronicleBackend` 가 `src.memory.drive_client.*` 를 호출.
    - master_index.json + reports/.md + backfill_state.json 모두 Google Drive 에 저장.
    - 기존 v3.4 동작과 100% 동일 (회귀 보장).

  - **SQLite 모드** (`STATE_STORE_BACKEND=sqlite`):
    - `_SQLiteChronicleBackend` 가 `data/sqlite/autostock.db` 의 chronicle_entries / chronicle_reports / chronicle_report_sections / chronicle_search(FTS5) / chronicle_backfill_state 5 테이블을 사용.
    - .md 본문은 헤딩 단위로 5 섹션 정규화되어 저장. FTS5 풀텍스트 인덱싱 동시 수행.
    - context_retriever 의 8단계 점수화 로직은 변경하지 않는다 (위험 격리).
    - 검색 효율 강화는 별도 API `chronicle_search_fulltext(query, ...)` 로 노출 (v3.5+ 활용).

  본 분기는 chronicle_writer / backfill / context_retriever 의 호출부에 노출되지 않는다 (Repository 패턴).
  자세한 스키마·매핑·마이그레이션 절차는 `Doc/features/data_persistence/03_data_persistence_state_logic.md §11` 참조.