## 1. Scope lock và contract prep

- [x] 1.1 Đối chiếu `project-spec/WISMO_MVP_Spec.md`, `project-spec/Main-flow.md`, và `project-spec/frontend-backend-contract.md` để khóa phạm vi BE-11-main chỉ cho Step 3.
- [x] 1.2 Cập nhật `project-spec/frontend-backend-contract.md` cho implicit chat creation trong `POST /api/chat/message/` (no `chat_id` path), bao gồm cách FE nhận `chat_id`/`turn_id` canonical từ SSE lifecycle.

## 2. Step 3 runtime implementation

- [x] 2.1 Implement service/boundary resolve chat context: load existing chat khi có `chat_id`, create chat mới khi không có `chat_id` với `case_id = null` và `opening_input_text`.
- [x] 2.2 Tạo `ChatTurn` intake record ngay sau khi resolve chat, lưu `user_message_text`, set initial processing status phù hợp runtime stream lifecycle, sinh `turn_id` server-side, và để `case_id = null` tại Step 3.
- [x] 2.3 Cập nhật Step 5 path để bind `ChatTurn.case_id` sau khi resolve case xong, giữ nguyên `turn_id` đã tạo ở Step 3.
- [x] 2.4 Cập nhật orchestrator output/internal context để bàn giao `chat_id`, `turn_id`, chat object, turn record cho Step 4 mà không re-resolve.

## 3. Regression coverage và verification

- [x] 3.1 Thêm/cập nhật unit tests cho create-vs-load chat context path, opening input persistence, và turn intake persistence.
- [x] 3.2 Thêm/cập nhật test cho nhánh Step 5 cập nhật `ChatTurn.case_id` (turn tạo từ Step 3) và đảm bảo không tạo turn thứ hai.
- [x] 3.3 Thêm/cập nhật SSE contract tests xác nhận nhánh implicit chat creation trả `chat_id`/`turn_id` canonical trong lifecycle event phù hợp.
- [x] 3.4 Chạy verification: `manage.py check`, `ruff check .`, `pytest -q`, `manage.py makemigrations --check --dry-run`.
