## Why

Sprint BE-10 "Main Flow Step 2: Request Gate" chưa thực sự tròn vẹn: logic gate đã có đủ 8 checks từ foundation sprints trước, nhưng còn 3 gaps cụ thể cần fill để sprint đạt đúng kết quả theo BE Implementation Plan — bao gồm doc drift trong Main-flow.md (vẫn còn `client_turn_id` đã bị xóa), contract chưa phân biệt rõ 2 tầng Gate layer vs Stream layer cho FE (fetch + ReadableStream), và regression tests chưa cover đủ tất cả gate failure paths qua SSE endpoint.

## What Changes

- **Doc update** `project-spec/Main-flow.md`: Bỏ `client_turn_id` khỏi Step 1 input, bỏ A.3 Idempotency check (client_turn_id-based), cập nhật A.8 ghi rõ `turn_in_progress` là chat-level barrier (không còn là identity-level idempotency). Không thay đổi code.
- **Contract update** `project-spec/frontend-backend-contract.md`: Phân biệt rõ Gate layer (HTTP 4xx/5xx + JSON body, `res.ok === false`) và Stream layer (SSE events, chỉ khi `res.ok === true`). Bổ sung đủ toàn bộ gate error code mapping với HTTP status codes và FE behavior. Clarify semantics `session_expired` vs `identity_not_resolved`.
- **Regression tests** `tests/unit/test_request_gate_sse.py`: Cover tất cả gate failure paths qua `POST /api/chat/message/` endpoint, xác nhận gate-fail trả HTTP JSON (không phải SSE), gate-pass trả `StreamingHttpResponse` với SSE headers.
- **Code comment** `runtime/request_gate.py` + `accounts/services.py`: Thêm comment ngắn giải thích design decision `session_expired` = inactive/unverified registered account, không phải Django TTL expiry.

## Capabilities

### New Capabilities

Không có capability mới — BE-10 là completion sprint, không thêm behavior mới.

### Modified Capabilities

- `chat-request-gate`: Bổ sung gate error code listing đầy đủ, làm rõ `session_expired` semantics, bỏ `client_turn_id`/idempotency khỏi spec.
- `chat-sse-transport`: Bổ sung 2-layer connection lifecycle contract (Gate layer vs Stream layer) cho FE fetch + ReadableStream pattern.

## Impact

- `project-spec/Main-flow.md` — doc only, no code change.
- `project-spec/frontend-backend-contract.md` — contract update.
- `runtime/request_gate.py` — comment only, no logic change.
- `accounts/services.py` — comment only, no logic change.
- `tests/unit/test_request_gate_sse.py` — new test file.
- Không có migration, không có schema change, không có behavior change.
