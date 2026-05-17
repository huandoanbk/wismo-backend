## ADDED Requirements

### Requirement: Chat turn endpoint trả SSE stream
`POST /api/chat/message/` SHALL trả `StreamingHttpResponse` với `Content-Type: text/event-stream` khi gate pass. Gate fail SHALL trả JSON error response như hiện tại trước khi stream mở.

#### Scenario: Gate pass mở SSE stream
- **WHEN** client gửi `POST /api/chat/message/` hợp lệ và gate pass
- **THEN** backend trả HTTP 200 với `Content-Type: text/event-stream` và giữ connection open trong suốt turn lifecycle

#### Scenario: Gate fail trả JSON trước khi stream mở
- **WHEN** client gửi `POST /api/chat/message/` và gate fail ở bất kỳ check nào (validation, identity, quota, ownership)
- **THEN** backend trả JSON error response với HTTP status code tương ứng, không mở SSE stream

### Requirement: SSE placeholder event format
Trong BE-9, orchestrator SHALL yield tối thiểu hai SSE events theo thứ tự: `response` event chứa response text, tiếp theo là `done` event chứa metadata của turn.

#### Scenario: Normal response stream
- **WHEN** orchestrator xử lý thành công một chat turn
- **THEN** generator yield `event: response\ndata: {"text": "<response_text>"}\n\n` rồi yield `event: done\ndata: {"turn_id": "...", "chat_id": "...", "response_method": "...", "status": "..."}\n\n`

#### Scenario: Orchestrator error sau khi stream đã mở
- **WHEN** orchestrator gặp lỗi (LLM gateway fail, runtime error) sau khi SSE connection đã mở
- **THEN** generator yield `event: error\ndata: {"error": "<error_code>"}\n\n` và kết thúc stream

### Requirement: SSE response headers
Backend SHALL set đủ headers để SSE hoạt động đúng qua proxy.

#### Scenario: Headers bắt buộc trên SSE response
- **WHEN** backend mở SSE stream
- **THEN** response SHALL có `Content-Type: text/event-stream`, `Cache-Control: no-cache`, và `X-Accel-Buffering: no`

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
