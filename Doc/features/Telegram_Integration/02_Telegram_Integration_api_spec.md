Telegram Integration API Spec

1) 텔레그램 수집 API (src/core/telegram_client.py)

fetch_new_messages(channel_id_list, last_message_id_dict) -> list[dict]
  - 목적: 지정된 채널 목록에서 최신 메시지 조회.
  - 반환: 원본 텍스트와 메타데이터가 포함된 메시지 딕셔너리 리스트. Rate Limit 발생 시 빈 리스트 반환(A-Type).

2) 파싱 및 정규화 API (src/core/telegram_parser.py)

parse_research_message(raw_text) -> dict | None
  - 목적: 비정형 리서치 메시지를 정규화된 스키마로 파싱.
  - 반환 (telegram_insight_dict):
      - source_channel: str
      - target_ticker: str | None
      - target_sector: str | None
      - sentiment: str
      - summary: str
      - extracted_tags_list: list[str]
  - 파싱 불가 시 None 반환 (A-Type 스킵).

3) 연계 헬퍼 API

dispatch_to_pipelines(telegram_insight_dict) -> bool
  - 목적: 정규화된 인사이트를 Market Chronicles 및 AI 단기 메모리 큐로 전달.