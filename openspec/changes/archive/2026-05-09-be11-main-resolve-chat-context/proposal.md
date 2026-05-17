## Why

Sprint kế tiếp sau BE-10 là Main Flow Step 3, nhưng repo chưa có OpenSpec change đúng scope cho bước này. Đồng thời BE plan vừa đổi tên mốc thành `BE-11-main`, nên cần change riêng để chốt rõ behavior resolve chat context theo `WISMO_MVP_Spec.md` và `Main-flow.md`, tránh lệch sang guest idle TTL hoặc auto-attach.

## What Changes

- Tạo OpenSpec change chuẩn cho `BE-11-main` tập trung duy nhất vào Main Flow Step 3: resolve chat context sau gate pass.
- Định nghĩa rõ hai nhánh runtime:
  - Có `chat_id`: load chat hiện có đã qua gate ownership.
  - Không có `chat_id`: tạo chat mới với `case_id = null` và lưu `opening_input_text`.
- Chuẩn hóa turn intake: tạo `ChatTurn` canonical với `user_message_text`, `status` khởi tạo phù hợp stream lifecycle, và `turn_id` do backend tự sinh.
- Chốt contract FE/BE cho implicit chat creation trong endpoint `POST /api/chat/message/`: trả `chat_id`/`turn_id` trong luồng SSE (đặc biệt ở `done` event) để FE cập nhật thread state.
- Bổ sung regression coverage cho create-vs-load path, opening input persistence, turn intake persistence, và dữ liệu context downstream Step 4 dùng được.

## Capabilities

### New Capabilities
- `chat-context-resolution`: Resolve hoặc tạo chat context tối thiểu sau Request Gate pass, đồng thời tạo turn intake record canonical cho downstream runtime steps.

### Modified Capabilities
- `chat-sse-transport`: Làm rõ contract implicit chat creation của chat turn endpoint khi request không có `chat_id`, và cách FE nhận `chat_id`/`turn_id` từ `done` event.

## Impact

- OpenSpec artifacts mới:
  - `openspec/changes/be11-main-resolve-chat-context/proposal.md`
  - `openspec/changes/be11-main-resolve-chat-context/design.md`
  - `openspec/changes/be11-main-resolve-chat-context/specs/chat-context-resolution/spec.md`
  - `openspec/changes/be11-main-resolve-chat-context/specs/chat-sse-transport/spec.md`
  - `openspec/changes/be11-main-resolve-chat-context/tasks.md`
- Ảnh hưởng code dự kiến khi apply: `runtime/orchestrator.py`, `chat/services.py`, `chat/models.py` (nếu cần field/status alignment), `chat/views.py`, `project-spec/frontend-backend-contract.md`, và tests runtime/chat liên quan.
- Không thêm dependency ngoài; migration chỉ tạo nếu implementation phát sinh schema gap thật sự.
