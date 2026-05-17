## Why

`POST /api/chat/message/` hiện trả JSON synchronous — không phù hợp với Main Flow spec yêu cầu SSE làm canonical transport cho chat turn. Main flow có nhiều exit point (Step 4 triage, Step 8 safety, Step 11 response, Step 12 quota notification) đều phải yield vào cùng SSE connection, nên cần establish generator pattern ngay ở Step 1 để các sprint sau plug in đúng chỗ.

## What Changes

- `POST /api/chat/message/` chuyển từ trả `Response` JSON sang `StreamingHttpResponse` SSE khi gate pass
- Gate vẫn chạy sync **trước** khi stream mở; gate fail tiếp tục trả JSON error như hiện tại — **không breaking với FE error handling**
- `RuntimeOrchestrator` refactor thành generator pattern: thêm method `stream(gate_result)` yield SSE events; method `handle()` hiện tại được giữ lại hoặc wrap để tests không bị break
- `ChatSendView` refactor để chạy gate trước, sau đó return `StreamingHttpResponse` wrapping orchestrator generator
- Orchestrator generator yield placeholder SSE events tạm thời (turn processing, response text, done) — event definitions thật sẽ được hoàn thiện ở sprint Step 11
- Contract cập nhật: SSE transport cho chat turn endpoint, `Content-Type: text/event-stream`, connection lifecycle cơ bản, placeholder event shapes

## Capabilities

### New Capabilities

- `chat-sse-transport`: SSE transport layer cho `POST /api/chat/message/` — gate-before-stream pattern, orchestrator generator, placeholder SSE events, contract SSE section

### Modified Capabilities

- `chat-request-gate`: gate execution point dịch chuyển từ bên trong orchestrator ra view layer để view có thể quyết định mở SSE hay trả JSON trước khi stream bắt đầu

## Impact

- `chat/views.py`: `ChatSendView.post()` refactor — chạy gate, nếu pass trả `StreamingHttpResponse`
- `runtime/orchestrator.py`: thêm `stream(gate_result)` generator; tách gate call ra khỏi `handle()`
- `runtime/request_gate.py`: không đổi logic, nhưng được gọi từ view thay vì orchestrator
- `project-spec/frontend-backend-contract.md`: thêm SSE transport section cho chat turn endpoint
- Tests: cập nhật để validate SSE response thay vì JSON cho success path
