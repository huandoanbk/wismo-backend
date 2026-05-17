## Context

Hiện tại `ChatSendView.post()` gọi `RuntimeOrchestrator.handle()` — orchestrator chạy gate + toàn bộ 12 steps rồi trả về `RuntimeReply` object — view format thành `Response` JSON. Pattern này không hỗ trợ SSE vì:

1. `StreamingHttpResponse` phải được tạo **trước** khi orchestrator bắt đầu chạy, nhưng gate phải chạy xong **trước** khi quyết định mở SSE hay trả JSON error.
2. Main Flow có nhiều exit point (Step 4 triage, Step 8 safety, Step 11 response, Step 12 quota notification) đều cần yield vào **cùng SSE connection** — không thể wrap response cuối thành SSE sau khi orchestrator chạy xong.

**Spec References:**
- `project-spec/Main-flow.md` — Step 11.6, Step 12.4
- `project-spec/WISMO_BE_Implementation_Plan.md` — BE-9, section 1.5
- `openspec/specs/chat-request-gate/spec.md`

## Goals / Non-Goals

**Goals:**
- Tách gate ra khỏi orchestrator để view quyết định JSON error vs. SSE trước khi stream mở
- Refactor orchestrator thành generator pattern — `stream(gate_result)` yield SSE events
- `ChatSendView` trả `StreamingHttpResponse` khi gate pass, JSON error khi gate fail
- Establish SSE infrastructure đúng architecture để Step 4/8/11/12 plug in real events sau
- Cập nhật contract SSE transport section và tests

**Non-Goals:**
- Định nghĩa SSE event format thật sự (Step 11 sprint)
- Token streaming (không phải stage events)
- Control branch events (Step 4 sprint)
- Quota notification event (Step 12 sprint)
- Async Django / ASGI migration

## Decisions

### D1: Gate chạy trong view, không trong orchestrator

**Quyết định:** `ChatSendView.post()` gọi `RequestGatePipeline.run()` trực tiếp. Nếu fail → trả `Response` JSON ngay. Nếu pass → tạo `StreamingHttpResponse` wrapping `orchestrator.stream(gate_result)`.

**Lý do:** `StreamingHttpResponse` phải được tạo và trả về trước khi generator chạy. Nếu gate nằm trong generator, HTTP headers đã gửi rồi mới biết gate fail → không thể trả HTTP status code lỗi đúng cách.

**Thay thế đã xét:** Giữ gate trong orchestrator và dùng exception để signal gate fail trong generator — bị loại vì không thể thay đổi HTTP status sau khi `StreamingHttpResponse` headers đã flush.

### D2: Orchestrator có thêm method `stream(gate_result)` generator

**Quyết định:** Thêm `stream(gate_result: GateResult) -> Iterator[str]` vào `RuntimeOrchestrator`. Method `handle()` cũ được giữ lại và wrap `stream()` — chạy generator đến hết rồi trả `RuntimeReply` — để existing tests không break.

**Lý do:** Tests hiện tại dùng `orchestrator.handle()` và assert JSON payload. Giữ `handle()` tránh phải refactor toàn bộ test suite trong BE-9. `stream()` là entry point mới cho view.

**Thay thế đã xét:** Xóa `handle()` hoàn toàn, refactor tests dùng SSE — phạm vi quá rộng cho BE-9.

### D3: Placeholder SSE events trong BE-9

**Quyết định:** Generator yield hai event placeholder:
- `event: response\ndata: {"text": "<response_text>"}\n\n`
- `event: done\ndata: {"turn_id": "...", "chat_id": "...", "response_method": "...", "status": "..."}\n\n`

Nếu orchestrator gặp lỗi sau khi stream đã mở:
- `event: error\ndata: {"error": "<error_code>"}\n\n`

**Lý do:** Cần ít nhất một event shape để tests có thể validate SSE response. Event names và data fields này là placeholder — Step 11 sprint sẽ define chính xác. Prefix `event:` theo SSE spec (RFC 8895).

**Thay thế đã xét:** Yield raw JSON không có `event:` type — bị loại vì FE cần event type để dispatch đúng handler.

### D4: Django `StreamingHttpResponse` với sync generator, WSGI

**Quyết định:** Dùng `django.http.StreamingHttpResponse` với sync generator và WSGI. Set headers:
- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no` (tắt nginx buffering)

**Lý do:** MVP dùng Django WSGI synchronous. `StreamingHttpResponse` với sync generator block worker thread trong suốt turn — acceptable cho MVP vì turn duration ngắn và concurrency thấp. ASGI/async là upgrade path sau.

**Rủi ro chấp nhận:** Mỗi concurrent chat turn chiếm 1 Django worker thread trong suốt thời gian LLM call (vài giây). Với worker pool nhỏ có thể block. Acceptable ở MVP scale.

## Risks / Trade-offs

**[Risk] Django worker thread bị block trong turn duration** → Mitigation: Giới hạn worker pool size phù hợp với expected concurrency của MVP. Document limitation. Upgrade path: ASGI sau khi cần.

**[Risk] `handle()` backward compat wrapper consume toàn bộ generator** → Mitigation: `handle()` collect tất cả yielded events rồi build `RuntimeReply` từ event cuối cùng. Nếu generator yield `error` event thì `handle()` trả `RuntimeReply.error()`. Tests không thấy thay đổi.

**[Risk] Nginx/proxy buffer SSE events** → Mitigation: Set `X-Accel-Buffering: no` header. Document trong deployment notes.

## Migration Plan

1. Tách gate call từ `RuntimeOrchestrator.handle()` ra `ChatSendView.post()`
2. Thêm `orchestrator.stream(gate_result)` generator
3. Wrap `handle()` dùng `stream()` để giữ backward compat
4. Cập nhật `ChatSendView` trả `StreamingHttpResponse`
5. Cập nhật tests — success path assert SSE stream thay vì JSON
6. Cập nhật `project-spec/frontend-backend-contract.md` — thêm SSE transport section

Không cần migration data. Không cần migration. Rollback: revert view và orchestrator về commit trước.

## Open Questions

Không có — scope và approach đã chốt với Owner.
