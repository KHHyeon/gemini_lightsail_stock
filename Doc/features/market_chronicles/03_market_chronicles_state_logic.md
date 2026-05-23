Market Chronicles State & Logic

1) 상태 모델

S0. Idle

  - 평시 대기 상태.

S1. Triggered

  - 트리거 조건 충족(T-Day), 백필 큐 존재, 또는 [추가] 텔레그램 증권 리서치 이벤트 수신.

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
    - [추가 제약] source 필드는 기존 소스 외에 "telegram_research" 값을 허용한다.
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