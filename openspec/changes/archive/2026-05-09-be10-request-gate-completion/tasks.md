## 1. Doc update — Main-flow.md

- [x] 1.1 Bỏ `client_turn_id` khỏi Step 1 input list trong `project-spec/Main-flow.md`
- [x] 1.2 Xóa hoàn toàn node A.3 Idempotency check (bao gồm các sub-nodes A.3.1 và A.3.2) khỏi `project-spec/Main-flow.md`
- [x] 1.3 Cập nhật A.8 Chat ownership check trong `project-spec/Main-flow.md` để ghi rõ `turn_in_progress` là chat-level barrier (không còn là identity-level idempotency), và thêm note về việc A.3 đã được bỏ

## 2. Contract update — 2-layer SSE lifecycle

- [x] 2.1 Cập nhật section `POST /api/chat/message/` trong `project-spec/frontend-backend-contract.md` để phân biệt rõ Gate layer (HTTP 4xx + JSON, `res.ok === false`) và Stream layer (SSE events, `res.ok === true`); thêm FE connection pattern với `fetch()` + `res.body.getReader()`
- [x] 2.2 Thêm full gate error code table vào contract với đủ 16 error codes, HTTP status codes, và ý nghĩa ngắn cho từng code (theo bảng trong `specs/chat-request-gate/spec.md`)
- [x] 2.3 Thêm clarification về `session_expired` semantics: `session_expired` = registered user `is_active=False` hoặc `email_verified=False`; Django session TTL expiry → `identity_not_resolved`; FE redirect về login trong cả hai trường hợp
- [x] 2.4 Thêm SSE event shapes section (placeholder, sẽ chốt tại Sprint Step 11): `event: response`, `event: done` (với `turn_id`, `chat_id`, `response_method`, `status`, `quota_exhausted_after_turn`), `event: error`; thêm abrupt close behavior
- [x] 2.5 Thêm note FE KHÔNG dùng `EventSource` cho endpoint này vì EventSource chỉ hỗ trợ GET

## 3. Code comments — session_expired design decision

- [x] 3.1 Thêm comment vào `_check_session` trong `runtime/request_gate.py` giải thích tại sao registered users bypass check này: session validity cho registered users đã được xử lý bởi `resolve_for_gate` (trả `session_expired` khi `is_active=False`/`email_verified=False`)
- [x] 3.2 Thêm comment vào `resolve_for_gate` trong `accounts/services.py` làm rõ: `session_expired` = tài khoản inactive/unverified; Django TTL expiry → user trở thành AnonymousUser → `identity_not_resolved`; không cần phân biệt hai trường hợp này cho chat gate

## 4. Regression tests — full gate failure paths qua SSE endpoint

- [x] 4.1 Tạo file `tests/unit/test_request_gate_sse.py` với `pytest.mark.django_db` và helper để build authenticated/guest/anonymous request
- [x] 4.2 Test gate-fail: `invalid_request` (body không phải dict) → HTTP 400 JSON, không có streaming content
- [x] 4.3 Test gate-fail: `missing_required_field` (không có `message`) → HTTP 400 JSON
- [x] 4.4 Test gate-fail: `invalid_chat_id` (`chat_id` không phải UUID hợp lệ) → HTTP 400 JSON
- [x] 4.5 Test gate-fail: `identity_not_resolved` (không có session, không có guest cookie) → HTTP 401 JSON
- [x] 4.6 Test gate-fail: `session_expired` (user authenticated nhưng `is_active=False`) → HTTP 401 JSON
- [x] 4.7 Test gate-fail: `guest_session_expired` (guest `is_active=False`) → HTTP 401 JSON
- [x] 4.8 Test gate-fail: `consent_required` (guest có consent nhưng chưa accept) → HTTP 403 JSON
- [x] 4.9 Test gate-fail: `empty_message` (`message` chỉ whitespace) → HTTP 400 JSON
- [x] 4.10 Test gate-fail: `message_too_long` (`message` vượt max length) → HTTP 413 JSON
- [x] 4.11 Test gate-fail: `registration_required_by_quota` (guest quota exhausted) → HTTP 429 JSON và `pending_input_text` được update
- [x] 4.12 Test gate-fail: `quota_exceeded` (registered user quota exhausted) → HTTP 429 JSON và `pending_input_text` được update
- [x] 4.13 Test gate-fail: `chat_not_found` (`chat_id` tồn tại nhưng là của identity khác, hoặc không tồn tại) → HTTP 404 JSON
- [x] 4.14 Test gate-fail: `chat_access_denied` (chat tồn tại nhưng không thuộc identity hiện tại) → HTTP 403 JSON
- [x] 4.15 Test gate-fail: `turn_in_progress` (chat có turn ở trạng thái Step 12 pending) → HTTP 409 JSON
- [x] 4.16 Test gate-pass: gate pass → response là `StreamingHttpResponse` với `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`; mock `RuntimeOrchestrator.stream()` để tránh LLM call thật
- [x] 4.17 Test cookie clearing: registered identity + guest cookie còn trong request → gate pass → response có `Set-Cookie` xóa `wismo_guest`
- [x] 4.18 Chạy `pytest tests/unit/test_request_gate_sse.py -q` và xác nhận tất cả pass; chạy `ruff check runtime/request_gate.py accounts/services.py tests/unit/test_request_gate_sse.py`

## 5. Verification tổng thể

- [x] 5.1 Chạy full test suite `pytest -q` để xác nhận không có regression
- [x] 5.2 Chạy `python manage.py check` và `python manage.py makemigrations --check --dry-run` (expect no changes)
- [x] 5.3 Cập nhật `agent-progress.md` với BE-10 completion
