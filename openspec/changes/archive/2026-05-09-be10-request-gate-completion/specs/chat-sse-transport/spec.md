## ADDED Requirements

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
Orchestrator SHALL yield SSE events theo thứ tự canonical trong stream layer. Event shapes hiện tại là placeholder — Sprint Step 11 sẽ chốt final format.

**Các event types hiện tại (placeholder):**
- `event: response\ndata: {"text": "<response_text>"}\n\n` — partial hoặc final response text.
- `event: done\ndata: {"turn_id": "...", "chat_id": "...", "response_method": "...", "status": "...", "quota_exhausted_after_turn": bool}\n\n` — final signal, turn đã persist xong.
- `event: error\ndata: {"error": "<error_code>", "status_code": <int>}\n\n` — runtime error sau khi stream đã mở.

#### Scenario: Happy path — response rồi done
- **WHEN** orchestrator xử lý thành công một chat turn
- **THEN** generator yield `event: response` trước, rồi yield `event: done` sau; FE hiển thị response text và coi turn là complete khi nhận done

#### Scenario: Runtime error trong stream — error event
- **WHEN** orchestrator gặp lỗi (LLM gateway fail, internal error) sau khi stream đã mở
- **THEN** generator yield `event: error` với error code và status_code, rồi kết thúc stream; FE không nhận done event

#### Scenario: done event báo turn đã persist
- **WHEN** FE nhận `event: done`
- **THEN** FE coi turn là officially complete — response đã persist, turn_id và chat_id hợp lệ để dùng tiếp

## MODIFIED Requirements

### Requirement: Chat turn endpoint trả SSE stream
`POST /api/chat/message/` SHALL trả `StreamingHttpResponse` với `Content-Type: text/event-stream` khi gate pass. Gate fail SHALL trả JSON error response với HTTP status code tương ứng trước khi stream mở. FE SHALL dùng `fetch()` + `res.body.getReader()` — KHÔNG dùng `EventSource`.

#### Scenario: Gate pass mở SSE stream
- **WHEN** client gửi `POST /api/chat/message/` hợp lệ và gate pass
- **THEN** backend trả HTTP 200 với `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` và giữ connection open trong suốt turn lifecycle

#### Scenario: Gate fail trả JSON trước khi stream mở
- **WHEN** client gửi `POST /api/chat/message/` và gate fail ở bất kỳ check nào
- **THEN** backend trả JSON error response `{"error": "<code>"}` với HTTP status code tương ứng, không mở SSE stream, FE đọc response body như JSON thông thường
