## MODIFIED Requirements

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
