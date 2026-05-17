## 1. Contract và shape chat

- [x] 1.1 Cập nhật `project-spec/frontend-backend-contract.md` cho `POST /api/chat/`, `GET /api/chat/`, và `GET /api/chat/<chat_id>/`, gồm request/response shape, `chat_display_name`, `opening_input_text`, `case_id`, và `turns` history.
- [x] 1.2 Khóa canonical error codes cho chat bootstrap: `identity_not_resolved`, `chat_not_found`, `chat_access_denied`, và các validation lỗi của `chat_id` nếu contract cần nhắc rõ.
- [x] 1.3 Chốt list/detail response shape trong contract sao cho list chỉ trả summary, còn detail trả summary + turn history theo thứ tự ổn định.

## 2. Chat service boundary

- [x] 2.1 Mở rộng `chat/services.py` để có boundary cho create/list/detail chat và ownership check, tái sử dụng cùng identity owner rule cho guest và registered user.
- [x] 2.2 Giữ `ChatContextService` là điểm dùng chung cho context/ownership thay vì tách thêm service trùng chức năng.
- [x] 2.3 Bảo đảm create chat và bootstrap detail/list dùng đúng model hiện có (`Chat`, `Case`, `ChatTurn`) và không phát sinh schema mới.

## 3. Views và URLs

- [x] 3.1 Thêm `POST /api/chat/` trong `chat/views.py` và `chat/urls.py` để tạo chat shell canonical cho FE/BFF.
- [x] 3.2 Thêm `GET /api/chat/` để list chat thuộc identity hiện tại theo thứ tự `last_activity_at` giảm dần.
- [x] 3.3 Thêm `GET /api/chat/<chat_id>/` để trả chat detail và turn history inline, ordered từ cũ đến mới.
- [x] 3.4 Map domain errors sang error envelope canonical bằng field `error` trong API layer.

## 4. Tests và verification

- [x] 4.1 Thêm regression tests cho create chat, list chat rỗng, list chat có dữ liệu, và detail chat với history rỗng/không rỗng.
- [x] 4.2 Thêm regression tests cho ownership deny: chat không tồn tại, chat thuộc identity khác, và identity không resolve được.
- [x] 4.3 Thêm regression tests cho ordering của list và turn history, cộng với `chat_display_name` fallback và `opening_input_text` preservation.
- [x] 4.4 Chạy `./.venv/bin/python manage.py check`, `./.venv/bin/pytest`, `./.venv/bin/ruff check .`, và `./.venv/bin/python manage.py makemigrations --check --dry-run`; nếu không có migration thì xác nhận check vẫn sạch.

## 5. Handoff

- [x] 5.1 Cập nhật `agent-progress.md` với phần hoàn thành của BE-5 sau khi code, contract, và tests đã xong.
- [x] 5.2 Cập nhật `tech-debt.md` nếu phát hiện vấn đề ngoài scope; nếu không có thì ghi rõ không phát sinh tech debt mới.
