## 1. Payload và contract gate

- [x] 1.1 Rà lại `POST /api/chat/message/` payload validation trong `runtime/request_gate.py` để khớp đúng các mã lỗi canonical của spec: `invalid_request`, `missing_required_field`, `invalid_chat_id`, `invalid_client_turn_id`, `empty_message`, `message_too_long`, `payload_too_large`.
- [x] 1.2 Chuẩn hóa mapping status code / error payload của các gate fail trong `chat/views.py` hoặc lớp orchestration liên quan để control response của request gate ổn định ở API layer.
- [x] 1.3 Cập nhật `project-spec/frontend-backend-contract.md` cho phần request gate errors của `POST /api/chat/message/` nếu payload/error behavior thay đổi hoặc đang thiếu.

## 2. Identity, idempotency và quota gate

- [x] 2.1 Rà lại `resolve identity` và `session validity check` để registered path, guest path, và expired path khớp đúng `Main-flow`.
- [x] 2.2 Hoàn thiện idempotency tối thiểu theo `client_turn_id` + owner hiện tại, phân biệt rõ `replay_previous_result` với `turn_in_progress`.
- [x] 2.3 Chốt quota gate side effects cho `pending_input_text`, `pending_input_append_count`, và `pending_input_updated_at` trên `UsageQuotaWindow` hiện tại theo policy guest/user khi quota đã exhausted.

## 3. Ownership barrier và regression coverage

- [x] 3.1 Rà lại `chat ownership check` cho các case chat không tồn tại, archived/disabled, không thuộc owner hiện tại, và previous-turn Step 12 còn pending.
- [x] 3.2 Bổ sung hoặc cập nhật regression tests DB-backed cho toàn bộ các nhánh gate chính: validation fail, identity/session fail, idempotency, consent fail, quota fail, ownership fail, và previous-turn barrier.
- [x] 3.3 Chạy `./.venv/bin/python manage.py check` và test request gate liên quan; nếu local Postgres credentials chưa sẵn sàng thì ghi rõ blocker cùng pattern chạy test cần thiết trong báo cáo cuối.
