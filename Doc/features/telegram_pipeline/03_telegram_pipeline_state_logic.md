# Telegram Pipeline State & Logic

버전별 구현율: v0.2 (사양 100%, Telethon 클라이언트 연동 100%, 키워드 추출 0%).

## 1) 상태 모델

- S0. Idle
    - 다음 폴링 주기 대기 중.
- S1. Fetching
    - 클라이언트가 채널별 신규 메시지 조회.
- S2. Normalizing
    - raw 메시지 리스트를 `telegram_message_dict` 로 변환(파싱 실패는 스킵).
- S3. Returning
    - 결과 dict 를 오케스트레이터에 반환(적재/주입 없음).
- SE. Transient Error
    - Rate Limit / 네트워크 일시 장애. 결과는 빈 리스트 + `status="transient_error"`.

상태 전이 규칙:
- 어떤 상태에서도 예외를 호출자에게 전파하지 않는다.
- 모든 외부 장애는 `status` / `note` 필드로만 표현한다.

## 2) 데이터 스키마

### `telegram_message_dict` (정규화 결과)
- `source_channel`: 발신 채널 식별자.
- `message_id`: 채널 내 메시지 식별자.
- `posted_at`: ISO8601 문자열(UTC 또는 KST 일관 유지).
- `text`: 본문(길이 상한 적용 후).
- `keyword_list`: 정제 단계 추출 키워드 리스트.

### `telegram_ingestion_result_dict` (파이프라인 반환)
- `status`: `"ok" | "disabled" | "transient_error"`.
- `message_list`: list[`telegram_message_dict`].
- `last_id_map`: 채널별 마지막 메시지 식별자 맵(갱신본).
- `skipped_count`: 정규화 단계 스킵 수.
- `note`: 운영자 개입 안내가 필요한 경우의 간단 사유.

## 3) 영속화 키 (중복 방지)
- 저장 위치: 운영 환경의 로컬 영속화 영역(파일 경로는 운영 매뉴얼에서 관리).
- 키 구조: `{channel_id: last_message_id}` 형태.
- 갱신 규칙:
    - 정규화에 성공한 메시지 중 가장 큰 `message_id` 로 채널별 키를 갱신.
    - 빈 결과(`transient_error`) 인 경우 키를 갱신하지 않는다.

## 4) 에러 격리 로직 (관심사 분리)

| 상황 | 분류 | 동작 |
|------|------|------|
| 채널/인증 미구성 | A-Type 격리 | `status="disabled"`, `message_list=[]`, `note` 에 안내 |
| Rate Limit / 네트워크 일시 장애 | A-Type 격리 | `status="transient_error"`, 부분 결과 또는 빈 결과 반환 |
| 단일 메시지 파싱 실패 | A-Type 스킵 | 해당 메시지만 제외, `skipped_count` 증가 |
| 인증 정보 자체가 잘못 구성 | B-Type 신호 | `status="disabled"`, `note` 에 운영자 조치 사유. Pause 결정은 오케스트레이터 |

핵심 원칙:
- 본 파이프라인은 절대 호출자에게 예외를 던지지 않는다.
- 트레이딩 코어(KIS 주문/리스크 감시)의 실행 흐름은 텔레그램 장애와 무관하게 진행된다.

## 5) 책임 경계
- **수집/정제까지**: 본 파이프라인 책임.
- **인덱스 적재**: Market Chronicles 책임(오케스트레이터가 데이터만 전달).
- **AI 프롬프트 주입**: ai_investment_decision 책임(오케스트레이터가 데이터만 전달).
- 본 파이프라인은 후속 도메인 모듈을 import 하지 않는다.
