# Market Chronicles (Feature Index)

## 구현율
- v1.1 (2026-05-25): KST 시간대 고정 + write_chronicle_for_today 거래일 가드 — 구현 완료
- v1.0: master_index v2 + 의미 기반 검색 + 백필/마이그레이션

## 기능 요약
Market Chronicles는 장세 이벤트를 기록/색인하고, 현재 시장과 유사한 과거 대응 지침을 AI 프롬프트에 주입하는 외장 메모리 기능이다.
**모든 시각 기준은 한국 표준시(KST) 고정이며, T-Day 리포트는 KST 거래일에만 작성된다 (주말/공휴일 절대 차단).**

## 목표
- 단어 매칭 오판 방지(의미 기반 매칭).
- 0.1초 판단 가능한 압축 스키마 유지.
- 운영 중단 없는 백필/마이그레이션/재개 흐름 보장.

## 문서 인덱스
- `01_requirements.md`: 기능 요구사항, 제약, 운영 규칙
- `02_api_spec.md`: 공개 API/시그니처/입출력 규약
- `03_state_logic.md`: 상태 전이, 스키마, 점수화/매칭 로직

## 핵심 흐름
1. 트리거 감지(VIX/지수 변동)  
2. 리포트 생성(T-Day 또는 Backfill)  
3. 인덱스 적재(master_index v2)  
4. 검색/점수화 후 컨텍스트 주입  
5. Pause/Resume 및 마이그레이션 운영