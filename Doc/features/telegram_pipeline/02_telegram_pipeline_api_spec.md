# Telegram Pipeline API Spec

## 1) 텔레그램 클라이언트 (src/core/telegram_client.py)

### `is_configured() -> bool`
- 목적: 텔레그램 인증/채널 설정의 최소 구성 여부 확인.
- 반환: 구성 완료 시 True. 누락/잘못 구성 시 False(예외 던지지 않음).

### `fetch_new_messages(channel_id_list, last_id_map) -> list[dict]`
- 목적: 채널별 신규 메시지 조회.
- 인자:
    - `channel_id_list`: 수집 대상 채널 식별자 리스트.
    - `last_id_map`: `{channel_id: last_message_id}` 형태의 영속화 맵.
- 반환: 정규화 전 메시지 dict 리스트.
    - 단일 메시지 dict 키: `channel_id`, `message_id`, `posted_at`, `raw_text`.
- 에러 격리:
    - 인증/네트워크/Rate Limit 예외는 내부 캡슐화 후 빈 리스트 반환(A-Type).
    - 단일 메시지 파싱 실패는 해당 항목만 스킵(전체는 부분 결과 반환).
- 외부 도메인 모듈을 import 하지 않는다.

## 2) 인제스트 파이프라인 (src/pipeline/telegram_pipeline.py)

### `run_ingestion(channel_id_list=None) -> dict`
- 목적: 클라이언트 호출 → 정규화 → 결과 반환(적재 없음).
- 인자:
    - `channel_id_list`: 명시되지 않으면 운영 설정 기본값 사용.
- 반환 (`telegram_ingestion_result_dict`):
    - `status`: `"ok" | "disabled" | "transient_error"`
    - `message_list`: list[`telegram_message_dict`]
    - `last_id_map`: 갱신된 채널별 last_message_id 맵
    - `skipped_count`: 정규화 스킵 수(파싱 실패/필터 탈락 합계)
    - `note`: 운영자 안내가 필요한 경우의 간단 사유 문자열(없으면 빈 문자열)
- 에러 정책: 본 함수는 예외를 던지지 않는다. 모든 외부 장애는 status 와 note 로 표현.

### `normalize_message(raw_dict) -> dict | None`
- 목적: 단일 raw 메시지를 `telegram_message_dict` 로 변환.
- 반환 (`telegram_message_dict`):
    - `source_channel`: str
    - `message_id`: int
    - `posted_at`: ISO8601 문자열
    - `text`: str (길이 상한 적용 후 본문)
    - `keyword_list`: list[str] (정제 단계에서 추출한 보조 키워드)
- 정규화 불가 시 None 반환(A-Type 스킵).

## 3) 오케스트레이터 연계 규약 (src/execution/orchestrator.py)

- 오케스트레이터는 `telegram_pipeline.run_ingestion()` 결과를 받아
  필요한 후속 파이프라인(Market Chronicles 적재 등)에 **데이터만 전달**한다.
- 본 파이프라인은 오케스트레이터에게서만 호출된다.
- Market Chronicles 모듈(`src/memory/chronicle_writer` 등)은 본 파이프라인을
  import 하지 않는다(역방향 의존 금지).
