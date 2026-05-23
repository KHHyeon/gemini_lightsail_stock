Telegram Integration State Logic

1) 상태 모델

S0. Idle
  - 다음 폴링 주기 대기.

S1. Fetching
  - 텔레그램 API를 호출하여 채널별 신규 메시지 수집.

S2. Parsing
  - 메시지를 순회하며 parse_research_message를 통해 telegram_insight_dict로 변환.

S3. Dispatching
  - 정규화된 데이터를 Market Chronicles 인덱스 적재 파이프라인 및 매매 근거 활용 큐에 분배.

2) 데이터 영속화 로직

  - 로컬 캐시 (last_message_id_dict): {"channel_name": 12345} 형태로 저장되어 중복 수집 방지 및 추적.