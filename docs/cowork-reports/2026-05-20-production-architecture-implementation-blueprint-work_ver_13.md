# Codex work_ver_13: review_ver_12 follow-up

작성: Codex
기준 리뷰: `2026-05-19-production-architecture-implementation-blueprint-review_ver_12.md`
상태: 2026-05-20 장후 `post-close`, live runtime 정지 확인 후 코드/문서 보강

## 1. 작업 요약

review_ver_12에서 코드로 바로 처리 가능한 WS reconnect metric 보강을 진행했다. Phase 1 진입 차단 P0 중 NAS 실제 dry-run과 reference clock 원천은 운영자 결정/실행 항목으로 분리해 기준 문서와 결정 템플릿에 반영했다.

## 2. 변경 전 / 변경 후 / 영향 범위 / 회귀 위험

| 항목 | 변경 전 | 변경 후 | 영향 범위 | 회귀 위험 |
|---|---|---|---|---|
| WS reconnect snapshot 시각 정보 | snapshot에는 reconnect/stable 발생 시각이 없어 dashboard의 "마지막 reconnect N분 전" 표시가 callback 수신 측 구현에만 의존했다. | `observed_at`, `last_reconnect_at`, `last_stable_at`, `storm_active_since`를 snapshot에 추가했다. | `app/brokers/kis_quote_ws.py`, `tests/test_kis_ws_reconnect_metrics.py` | snapshot dataclass 필드가 늘었다. 현재 외부 사용처는 없고, 기존 callback은 추가 필드를 무시할 수 있다. |
| WS reconnect snapshot 직렬화 | timestamp가 들어가면 dashboard/readiness JSON 저장 시 별도 변환이 필요했다. | `KisWebSocketReconnectSnapshot.to_dict()`를 추가해 ISO 8601 문자열로 직렬화한다. | `app/brokers/kis_quote_ws.py`, `tests/test_kis_ws_reconnect_metrics.py` | 없음. 순수 helper다. |
| callback 사용 원칙 | callback 예외는 흡수했지만 동기 callback이 무거운 작업을 하면 quote stream 지연 위험이 문서화되지 않았다. | `listen()` docstring에 callback은 동기 호출이며 DB/file/network I/O 대신 in-memory update 또는 worker queue를 쓰라고 명시했다. | `app/brokers/kis_quote_ws.py` | 없음. 문서화다. |
| Phase 1 P0 상태 | work report들에 흩어져 있었다. | `docs/Production-Implementation-Blueprint.md`에 P0 4개 진행표를 추가했다. | 기준 문서 | 없음. |
| Phase 2 1주 제한 문서화 | implementation blueprint 중심이었다. | `docs/Production-Architecture.md`에도 `max_order_qty=1`과 override 방법을 반영했다. | 기준 문서 | 없음. |
| reference clock/NAS dry-run 결정 | operator decision template에 항목이 없었다. | 결정 템플릿에 reference clock 원천과 NAS recovery 실제 dry-run 항목을 추가했다. | cowork decision template | 없음. |

## 3. Phase 1 진입 전 P0 잔여 상태

| P0 항목 | 상태 | 권장안 |
|---|---|---|
| WS reconnect metric | 코드 보강 완료. timestamp와 `to_dict()`까지 추가 | 다음 단계에서 readiness/dashboard read-only 노출 |
| KIS fixture mapper | 완료 | Phase 1 read-only 진입 직후 paper/live shape 비교 |
| NAS recovery drill | self-test만 완료, 실제 dry-run 미검증 | 장외 시간 dry-run 1회 완료 후 실제 NAS 강제 백업 여부 별도 승인 |
| reference clock 원천 | 미결정 | KIS REST 응답 `Date` 헤더 또는 KIS 응답 서버시각을 1차 reference, OS/NTP를 보조 reference |

## 4. 검증

실행 완료:

```bash
python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification
python -m py_compile app/brokers/kis_quote_ws.py tests/test_kis_ws_reconnect_metrics.py
python -m unittest tests.test_kis_ws_reconnect_metrics tests.test_kis_ws_parser tests.test_kis_ws_verification tests.test_live_order_manager tests.test_kis_http_clients tests.test_live_execution_sync tests.test_wsl_ops
git diff --check
```

결과:

- WS 관련 13개 테스트 통과.
- 대상 파일 `py_compile` 통과.
- review_ver_12 후속 전체 관련 묶음 62개 테스트 통과.
- `git diff --check` 통과. CRLF/LF warning만 있었고 whitespace error는 없었다.

## 5. cowork 검토 요청

이번 리뷰는 좁게 보면 충분하다.

1. `observed_at`/`last_reconnect_at`/`last_stable_at`/`storm_active_since`가 dashboard/readiness 표시용으로 충분한지.
2. reference clock 권장안이 Phase 1 read-only 진입 기준으로 적절한지.
3. NAS dry-run을 Phase 1 진입 차단 항목으로 계속 두는 판단이 적절한지.
