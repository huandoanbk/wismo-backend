## Context

BE-10 "Main Flow Step 2: Request Gate" có các foundation đã hoàn chỉnh từ các sprint trước:
- `runtime/request_gate.py`: `RequestGatePipeline` với 8 checks đúng thứ tự theo Main-flow.md (validate → identity → session → consent → quota → input_guard → ownership + turn_barrier).
- `chat/views.py` `ChatSendView`: gate-fail → `Response` JSON; gate-pass → `StreamingHttpResponse` SSE (done trong BE-9).
- `wismo/contracts/codes.py`: Tất cả canonical error codes.
- `project-spec/frontend-backend-contract.md`: Đã có section SSE placeholder từ BE-9.

Tuy nhiên còn 3 gaps cụ thể cần fill trước khi đánh dấu BE-10 tròn vẹn:

1. **Doc drift**: `project-spec/Main-flow.md` vẫn còn `client_turn_id` trong Step 1 input và A.3 Idempotency check section, trong khi `client_turn_id` đã bị xóa khỏi codebase theo owner decision.
2. **Contract chưa đủ**: Contract SSE của `POST /api/chat/message/` chưa phân biệt rõ Gate layer (HTTP response) vs Stream layer (SSE events), chưa có full status code table cho tất cả gate error codes, và chưa clarify semantics `session_expired` vs `identity_not_resolved`.
3. **Test gap**: `test_sse_transport.py` hiện chỉ có 4 tests, chưa cover đủ tất cả 13+ gate failure paths qua SSE endpoint.

**Owner decisions đã chốt:**
- `session_expired`: chỉ trả khi registered user `is_active=False` hoặc `email_verified=False`. Django session TTL expiry → `identity_not_resolved`. FE check session status trước khi chat.
- FE dùng `fetch()` + `res.body.getReader()` (ReadableStream), không dùng EventSource.
- `turn_in_progress` là chat-level barrier ở A.8 (ownership check), không phải identity-level idempotency.

**Spec references:**
- `openspec/specs/chat-request-gate/spec.md`
- `openspec/specs/chat-sse-transport/spec.md`
- `project-spec/Main-flow.md`
- `project-spec/frontend-backend-contract.md`

## Goals / Non-Goals

**Goals:**
- Cập nhật `project-spec/Main-flow.md` để đồng bộ với codebase: bỏ `client_turn_id`, bỏ A.3 idempotency, làm rõ `turn_in_progress` là chat-level barrier.
- Cập nhật `project-spec/frontend-backend-contract.md` để phân biệt Gate layer (HTTP 4xx + JSON) vs Stream layer (SSE events) cho `POST /api/chat/message/`, với full error code table.
- Thêm regression tests cover toàn bộ gate failure paths qua `ChatSendView`.
- Thêm comment giải thích `session_expired` semantics vào code.

**Non-Goals:**
- Không thay đổi bất kỳ logic gate nào — gate đã hoàn chỉnh.
- Không thêm detection `session_expired` cho Django TTL expiry (Option A đã chốt).
- Không thêm `client_turn_id` hay idempotency mechanism mới.
- Không thay đổi SSE event shapes (chốt tại Sprint Step 11).
- Không thay đổi database schema, không tạo migration.

## Decisions

### Decision 1: Gate layer vs Stream layer — phân biệt ở contract level

**Quyết định:** Contract phân biệt 2 tầng rõ ràng:
- **Gate layer**: `res.ok === false` → FE đọc JSON body `{"error": "<code>"}`. HTTP status codes xác định loại lỗi. Xảy ra trước khi stream mở.
- **Stream layer**: `res.ok === true` (HTTP 200) → FE pipe qua `res.body.getReader()`. SSE events `event: response`, `event: done`, `event: error` được emit trong stream.

**Lý do:** FE dùng `fetch()` + ReadableStream (không phải EventSource). Với pattern này, FE có thể đọc JSON body từ non-200 response trước khi chạm stream, nên Gate layer hoàn toàn tách biệt với Stream layer. Đây là thiết kế chính xác cho MVP.

**Thay thế đã xem xét:** Luôn trả HTTP 200 + SSE error event cho mọi lỗi (kể cả gate fail). Bị loại vì phức tạp hơn, không cần thiết cho MVP, và FE phải xử lý thêm một tầng event decode trước khi biết có lỗi gate.

### Decision 2: `session_expired` semantics — Option A

**Quyết định:** `session_expired` (401) chỉ xảy ra khi `request.user.is_authenticated=True` nhưng `is_active=False` hoặc `email_verified=False` (handled trong `resolve_for_gate`). Django session TTL expiry → user trở thành AnonymousUser không có guest cookie → `identity_not_resolved` (401).

**Lý do:** Django không để lại readable token khi session TTL hết hạn. Không thể phân biệt "registered user TTL expired" với "brand new anonymous visitor" mà không thêm middleware phức tạp. Cho MVP, FE xử lý session expiry qua `GET /api/accounts/session/` (session status API) trước khi enter chat flow, không cần BE phân biệt.

**Contract ghi rõ:** `identity_not_resolved` = không thể xác định danh tính (kể cả Django TTL expiry cho registered user). FE xử lý giống nhau — redirect về login.

### Decision 3: `turn_in_progress` — chat-level barrier ở A.8

**Quyết định:** `turn_in_progress` (409) được check bên trong `_check_chat_ownership` (A.8), không phải ở A.3.

**Lý do:** Sau khi xóa `client_turn_id`, không còn identity-level idempotency check (A.3 cũ). `turn_in_progress` bây giờ là chat-level barrier: chỉ có nghĩa khi có `chat_id` cụ thể và đã xác nhận ownership. Vị trí A.8 là đúng — không thể check chat-level barrier trước khi biết ownership.

Main-flow.md cần update A.3 → bỏ hoàn toàn, A.8 ghi rõ `turn_in_progress`.

### Decision 4: Test file mới thay vì extend file cũ

**Quyết định:** Tạo `tests/unit/test_request_gate_sse.py` riêng thay vì thêm vào `test_sse_transport.py`.

**Lý do:** `test_sse_transport.py` có mục đích khác — test SSE transport layer (headers, event ordering, streaming_content format). BE-10 tests tập trung vào gate failure paths qua SSE endpoint. Tách file giữ concern rõ ràng và dễ maintain.

## Risks / Trade-offs

**[Risk] Main-flow.md update có thể gây mâu thuẫn với FE đang đọc spec** → Mitigation: Chỉ bỏ `client_turn_id` và A.3 — FE đã không còn gửi `client_turn_id` theo owner decision trước. Update doc chỉ sync lại thực tế, không thay đổi behavior.

**[Risk] Contract 2-layer chưa cover các edge cases của abrupt stream close** → Mitigation: Ghi rõ trong contract rằng abrupt close (stream ends without `event: done`) = FE treat as error, retry/refresh. Không cần handle ở BE — stream close tự nhiên khi Django view kết thúc generator.

**[Risk] Tests mới cần real DB** → Mitigation: Dùng `@pytest.mark.django_db` và `--reuse-db` pattern như toàn bộ test suite hiện tại. Gate tests chủ yếu mock LLM gateway để tránh external calls trong gate-pass test.

## Open Questions

Không còn open question — tất cả đã được Owner chốt trước khi propose.
