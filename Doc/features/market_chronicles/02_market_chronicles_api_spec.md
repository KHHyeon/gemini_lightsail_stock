Market Chronicles API Spec

1) Drive/Index API

drive_client.read_master_index(*, allow_auto_migrate=True) -> dict

  - 목적: master_index.json 로드 및 버전 가드.
  - 정상: {"version": 2, "entries": [...]} 반환.
  - 예외: 버전 불일치 시 DriveSchemaMismatchError (Pause 연계).

drive_client.append_index_entry(entry_dict) -> dict

  - 목적: v2 엔트리 append 후 전체 인덱스 저장.

drive_client.write_master_index(index_dict) -> None

  - 목적: 인덱스 전체 덮어쓰기(마이그레이션/정리용).

2) Chronicles 공통 헬퍼

chronicle_common.parse_action_preview(ai_text) -> str

  - 목적: 리포트에서 행동 지침 한 줄 추출/정규화.

chronicle_common.derive_market_state(phrases_list, *, vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None, regime_label_override=None) -> dict

  - 반환: {"regime","regime_label","main_actor","sentiment"}

chronicle_common.derive_context_tags(phrases_list, market_state_dict, max_tags=6) -> list[str]

  - 목적: 상황 태그 생성([주체_동사] 중심).

비고: 외부 인제스트(예: Telegram Pipeline) 결과를 entry_dict 로 변환하는 헬퍼는
오케스트레이터 위임 계층에서 다루며, Market Chronicles 모듈은 외부 수집기 모듈을
직접 import 하지 않는다(역방향 의존 금지).

3) Regime API

macro_triggers.resolve_regime(vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None) -> str

  - 목적: 표준 enum 8종 중 1개 결정.

macro_triggers.map_regime_from_text(free_text) -> str | None

- 목적: v1 자유형 문자열을 enum으로 1차 매핑.

4) 검색/주입 API

context_retriever.extract_market_context(macro, news_snippets=None) -> dict

  - 반환: context_tags_list, regime, main_actor_keyword, sentiment, phrases_list

context_retriever.search_similar_guidelines(..., top_n=3, min_score=3.0, query_dict=None) -> list[dict]

  - 목적: 유사 지침 검색(임계점 이하 배제).

context_retriever.build_context_injection_block(query, top_n=3) -> str

  - 목적: 3블록(헤더/태그/지침) 포맷으로 프롬프트 주입 문자열 생성.

5) 마이그레이션 API

scripts/migrate_master_index_v2.py:migrate_in_process(*, ai_enabled=True, delay_sec=3, limit=None, dry_run=False, emit=print_flush) -> dict