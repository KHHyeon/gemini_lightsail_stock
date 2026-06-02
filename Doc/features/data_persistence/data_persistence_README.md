# Data Persistence (Feature Index)

## 구현율
- v1.0 (Phase 1, 2026-06-02): 도메인 API(`state_store`) 추상화 레이어 신설. 백엔드는 Drive 그대로 위임 — **사양 정의 + 구현 100%**.
- v1.1~v1.4 (Phase 2~5, 예정): SQLite 백엔드 구현, Market Chronicles DB 전환, 백업 cron, Drive/OAuth 인프라 제거.

## 기능 요약
본 봇의 영속화 책임을 **단일 도메인 API (`src/storage/state_store.py`)** 로 일원화한다.
호출자(orchestrator/risk_monitor/slack_interface 등)는 Drive/SQLite/PG 같은 백엔드를 알 필요 없이
도메인 메서드(`get_portfolio`/`save_split_orders` 등) 만 호출한다.

## 설계 동기
- **OAuth 만료 반복 문제**: Drive Testing 모드의 7일 만료 + invalid_grant 자동 Pause 부담 누적.
- **거래 IO 성능**: 매분 Drive round-trip → SQLite 로컬 IO 마이크로초급 전환 여지 확보.
- **스키마 진화**: master_index v1→v2(v3.4) 같은 변화가 호출자 코드에 노출되지 않게 격리.
- **테스트 용이성**: 메모리 백엔드 주입으로 단위 테스트 단순화.

## 도메인 분류 (Phase 1 적용 대상)
| 도메인 | 데이터 | 메서드 |
|---|---|---|
| A. 운영 상태 | portfolio / split_orders / theme_context / scalp_session | `get_*` / `save_*` |
| B. 거래 이력 | trades (append-only) | `list_trades` / `replace_trades` |
| 일괄 초기화 | A+B 4개 reset | `reset_app_data` |

Market Chronicles 인덱스/본문(C/D 도메인) 은 Phase 3 에서 별도 진행.

## 문서 인덱스
- `./01_data_persistence_requirements.md`: 요구사항·제약·도메인 책임
- `./02_data_persistence_api_spec.md`: 공개 API 시그니처·반환 규약
- `./03_data_persistence_state_logic.md`: 백엔드 전환 로직·스키마 진화·마이그레이션 정책

## 연관 기능
- `../market_chronicles/`: C/D 도메인 (Phase 3)
- `../scalp_logic/`: scalp_session 영속화
- `../kis_token/`: 별개 도메인 (OAuth/KIS 토큰)

## Phase 로드맵 (참고)
1. **Phase 1 (완료)**: `state_store` 도메인 API + Drive 위임 백엔드. 호출자 26곳 교체. **봇 동작 100% 동일**.
2. **Phase 2 (예정)**: SQLite 백엔드 + `data/autostock.db` + 마이그레이션 러너 + Drive→SQLite 일괄 마이그레이션 스크립트.
3. **Phase 3 (예정)**: Market Chronicles C/D 도메인을 SQLite + FTS5 + `chronicle_report_sections` 정규화로 전환.
4. **Phase 4 (예정)**: 백업 cron (GitHub Private Repo 또는 S3) + Lightsail Snapshot 2차 안전망.
5. **Phase 5 (예정)**: Drive/OAuth 인프라 통째로 제거 + 문서 정리.
