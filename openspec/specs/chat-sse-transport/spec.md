# chat-sse-transport Specification

## Purpose
TBD - created by archiving change be9-sse-transport-layer. Update Purpose after archive.
## Requirements
### Requirement: Chat turn endpoint trả SSE stream
`POST /api/chat/message/` SHALL trả `StreamingHttpResponse` với `Content-Type: text/event-stream` khi gate pass. Gate fail SHALL trả JSON error response với HTTP status code tương ứng trước khi stream mở. FE SHALL dùng `fetch()` + `res.body.getReader()` — KHÔNG dùng `EventSource`.

#### Scenario: Gate pass mở SSE stream
- **WHEN** client gửi `POST /api/chat/message/` hợp lệ và gate pass
- **THEN** backend trả HTTP 200 với `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` và giữ connection open trong suốt turn lifecycle

#### Scenario: Gate fail trả JSON trước khi stream mở
- **WHEN** client gửi `POST /api/chat/message/` và gate fail ở bất kỳ check nào
- **THEN** backend trả JSON error response `{"error": "<code>"}` với HTTP status code tương ứng, không mở SSE stream, FE đọc response body như JSON thông thường

### Requirement: Chat message API SHALL expose SSE lifecycle rõ ràng cho FE
`POST /api/chat/message/` SHALL có 2 lớp response tách biệt:
- Gate layer: HTTP status + JSON error khi gate fail
- Stream layer: SSE events khi gate pass

#### Scenario: Gate fail trả JSON error
- **WHEN** request fail ở Request Gate
- **THEN** API MUST trả HTTP non-2xx và JSON body keyword-only
- **AND** API MUST NOT mở SSE stream

#### Scenario: Gate pass mở SSE stream
- **WHEN** request pass toàn bộ Request Gate
- **THEN** API MUST trả `StreamingHttpResponse` với `Content-Type: text/event-stream`
- **AND** runtime MUST stream event lifecycle theo contract

#### Scenario: done event chốt final response đã persist
- **WHEN** runtime hoàn tất response path của turn
- **THEN** API MUST phát `done` event như tín hiệu final assistant response đã được persist chính thức

#### Scenario: Implicit chat creation trả canonical ids
- **WHEN** request không có `chat_id` và backend tạo chat mới trong Step 3
- **THEN** SSE lifecycle MUST cung cấp `chat_id` canonical và `turn_id` canonical để FE cập nhật thread state
- **AND** FE MUST có đủ dữ liệu để map local pending message vào persisted turn khi nhận `done`

### Requirement: Chat message API SHALL expose control responses via SSE after gate pass
Sau khi gate pass và stream đã mở, mọi control response ở Step 4 SHALL được trả qua SSE lifecycle thay vì JSON.

#### Scenario: Crisis control response qua SSE
- **WHEN** Step 4 quyết định `crisis_hotline_immediate`
- **THEN** stream phát control response tương ứng `CRISIS_SAFE_ONLY` và phát `done` event để chốt turn lifecycle

#### Scenario: Non-persist control response qua SSE
- **WHEN** Step 4 quyết định `blocked_minor`, `hard_redirect`, `policy_bypass_refusal`, hoặc `spam_or_non_conversational`
- **THEN** stream phát control response tương ứng và kết thúc lifecycle theo contract SSE của control path

#### Scenario: Mọi control path đều phát done event
- **WHEN** Step 4 trả bất kỳ control response nào (`CRISIS_SAFE_ONLY`, `BLOCKED_MINOR`, `REDIRECT`, `REFUSAL`, `SPAM_REPLY`)
- **THEN** stream MUST phát `done` event sau control response để FE chốt lifecycle

#### Scenario: done contract cho non-persist control path
- **WHEN** control response thuộc non-persist paths (`BLOCKED_MINOR`, `REDIRECT`, `REFUSAL`, `SPAM_REPLY`)
- **THEN** `done` event MUST có `status = "completed"`, `response_method` đúng method control
- **AND** `done.turn_id` MUST là `null`
- **AND** `done.chat_id` MUST luôn có để FE giữ canonical thread state

#### Scenario: Continue path giữ SSE normal flow
- **WHEN** Step 4 quyết định `continue_to_full_reasoning`
- **THEN** stream tiếp tục flow normal hiện tại (response + done) sau các step downstream

### Requirement: 2-layer connection lifecycle cho chat turn endpoint
`POST /api/chat/message/` SHALL được FE xử lý theo 2 tầng rõ ràng dựa trên `res.ok`. FE KHÔNG dùng `EventSource` cho endpoint này — FE dùng `fetch()` + `res.body.getReader()` (ReadableStream) vì EventSource chỉ hỗ trợ GET.

**Layer 1 — Gate layer** (`res.ok === false`):
- Xảy ra khi gate fail, trước khi stream mở.
- FE đọc JSON body: `{"error": "<code>"}` với HTTP status code tương ứng.
- FE không chạm stream, không cần setup reader.
- FE xử lý lỗi theo code và redirect/hiển thị thông báo.

**Layer 2 — Stream layer** (`res.ok === true`, HTTP 200):
- Xảy ra khi gate pass.
- FE pipe stream qua `res.body.getReader()`.
- FE decode `Uint8Array` → `TextDecoder` → parse SSE lines.
- FE nhận các SSE events theo thứ tự: `event: response` → `event: done` (happy path), hoặc `event: error` (runtime error sau khi stream đã mở).
- Khi stream kết thúc mà không có `event: done` (abrupt close) — FE treat as error, hiển thị thông báo retry.

#### Scenario: FE nhận gate-fail JSON trước khi stream mở
- **WHEN** backend trả HTTP 4xx do gate fail
- **THEN** `res.ok === false`, FE gọi `res.json()` để đọc `{"error": "<code>"}`, không khởi tạo reader

#### Scenario: FE mở stream sau khi gate pass
- **WHEN** backend trả HTTP 200 với `Content-Type: text/event-stream`
- **THEN** `res.ok === true`, FE gọi `res.body.getReader()` và bắt đầu đọc stream chunks

#### Scenario: Abrupt stream close không có done event
- **WHEN** stream kết thúc (reader.done === true) trước khi FE nhận `event: done`
- **THEN** FE treat as unexpected error và hiển thị thông báo cho user

### Requirement: SSE event shapes trong stream layer
Orchestrator SHALL yield SSE events theo thứ tự canonical trong stream layer; `done` giữ nghĩa response final đã persist, không thay thế trạng thái hoàn tất Step 12.

**Các event types hiện tại (canonical):**
- `event: response\ndata: {"text": "<response_text>"}\n\n` — final response text đã chọn ở Step 11.
- `event: done\ndata: {"turn_id": "...", "chat_id": "...", "response_method": "...", "status": "...", "quota_exhausted_after_turn": bool}\n\n` — final signal cho response lifecycle đã persist.
- `event: error\ndata: {"error": "<error_code>", "status_code": <int>}\n\n` — runtime error sau khi stream đã mở.

#### Scenario: Happy path — response rồi done
- **WHEN** orchestrator xử lý thành công một chat turn
- **THEN** generator MUST yield `event: response` trước, rồi yield `event: done` sau
- **AND** `done` MUST giữ semantics là response persisted, không đồng nghĩa Step 12 đã finalized

#### Scenario: Runtime error trong stream — error event
- **WHEN** orchestrator gặp lỗi (LLM gateway fail, internal error) sau khi stream đã mở
- **THEN** generator yield `event: error` với error code và status_code, rồi kết thúc stream; FE không nhận done event

#### Scenario: done event báo turn đã persist
- **WHEN** FE nhận `event: done`
- **THEN** FE coi turn là officially complete
- **AND** FE MUST NOT suy diễn rằng Step 12 chắc chắn đã hoàn tất chỉ từ `done`

### Requirement: Orchestrator generator pattern
`RuntimeOrchestrator` SHALL có method `stream(gate_result)` là generator yield SSE event strings. Method `handle()` SHALL được giữ lại wrapping `stream()` để backward compatibility với tests.

#### Scenario: stream() nhận gate_result và yield events
- **WHEN** view gọi `orchestrator.stream(gate_result)` sau khi gate pass
- **THEN** generator chạy các runtime steps và yield SSE events tương ứng

#### Scenario: handle() backward compat với tests
- **WHEN** test hoặc caller cũ gọi `orchestrator.handle(request, data)`
- **THEN** `handle()` chạy gate nội bộ như cũ, consume generator từ `stream()`, và trả `RuntimeReply` như trước

### Requirement: Gate tách ra view layer
`ChatSendView` SHALL chạy `RequestGatePipeline.run()` trực tiếp. Kết quả gate SHALL quyết định response type trước khi tạo `StreamingHttpResponse`.

#### Scenario: View chạy gate trước khi quyết định response type
- **WHEN** `ChatSendView.post()` nhận request
- **THEN** view chạy gate sync, nếu fail trả `Response` JSON, nếu pass tạo `StreamingHttpResponse(orchestrator.stream(gate_result))`
