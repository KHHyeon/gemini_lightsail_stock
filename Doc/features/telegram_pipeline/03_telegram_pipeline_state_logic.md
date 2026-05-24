# Telegram Pipeline State & Logic

버전별 구현율: v0.3 (사양 100%, 밸류체인 및 전이 분석 스키마 추가).

1) 상태 모델
  - S0. Idle: 다음 폴링 주기 대기 중.
  - S1. Fetching: 클라이언트가 채널별 신규 메시지 조회.
  - S2. Normalizing & Analyzing (확장):
      - raw 메시지 리스트를 telegram_message_dict 로 변환.
      - 국내/해외 종목 맵핑(Supplier/Rival/Client) 및 해외 매크로 전이 분석(Transmission Path) 수행. 파싱 또는 분석 실패는 스킵.
  - S3. Returning: 결과 dict 를 오케스트레이터에 반환(적재/주입 없음).
  - SE. Transient Error: Rate Limit / 네트워크 일시 장애. 결과는 빈 리스트 + status="transient_error".

2) 데이터 스키마 (확장)

telegram_message_dict (정규화 결과)
  - source_channel: 발신 채널 식별자.
  - message_id: 채널 내 메시지 식별자.
  - posted_at: ISO8601 문자열(UTC 또는 KST 일관 유지).
  - text: 본문(길이 상한 적용 후).
  - keyword_list: 정제 단계 추출 키워드 리스트.
  - analysis: (신규) 
      - category: "DOMESTIC_STOCK" | "OVERSEAS_STOCK" | "DOMESTIC_MARKET" | "OVERSEAS_MARKET"
      - related_kr_tickers: list[str] (직접 언급 또는 밸류체인으로 맵핑된 국내 종목 코드)
      - value_chain_type: "SUPPLIER" | "RIVAL" | "CLIENT" | None (해외 종목일 경우)
      - transmission_path: str (해외 시황일 경우 3문장 이내의 전이 경로 추론)

telegram_ingestion_result_dict (파이프라인 반환)
  - status: "ok" | "disabled" | "transient_error".
  - message_list: list[telegram_message_dict].
  - last_id_map: 채널별 마지막 메시지 식별자 맵(갱신본).
  - skipped_count: 정규화/분석 단계 스킵 수.
  - note: 운영자 개입 안내가 필요한 경우의 간단 사유.

3) 분석 세부 로직 (S2)
  - 밸류체인 맵핑: 해외 종목(NVDA 등)이 식별되면, `ai_logic.analyze_value_chain` 헬퍼를 호출하여 연관된 국내 종목(related_kr_tickers)과 관계(value_chain_type)를 추출한다.
  - 전이 경로 분석: 메시지가 '해외 시황'으로 분류되면, 프롬프트 규칙에 따라 "현상 -> 전이 매개체(환율/금리) -> 내일 국내 섹터 수급 전망"의 3단계 논리를 3문장 이내로 강제 생성한다.

4) 영속화 키 (중복 방지)
  - 키 구조: {channel_id: last_message_id} 형태.
  - 갱신 규칙: 정규화/분석에 성공한 메시지 중 가장 큰 message_id 로 채널별 키를 갱신. 에러 시 갱신 안 함.

5) 에러 격리 로직 (관심사 분리)
  - 단일 메시지의 밸류체인 판단 불가, 전이 분석 타임아웃 등은 "단일 메시지 파싱 실패"에 준하여 A-Type 스킵 처리(skipped_count 증가)한다. 전체 파이프라인을 중단시키지 않는다.