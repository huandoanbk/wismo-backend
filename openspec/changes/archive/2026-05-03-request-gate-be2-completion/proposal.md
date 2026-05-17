## Why

Request gate hiện đã có skeleton nhưng chưa khóa đủ hành vi của Sprint BE-2 theo `project-spec/Main-flow.md` và `project-spec/WISMO_BE_Implementation_Plan.md`. Nếu tiếp tục sang runtime shell khi gate còn hở ở payload validation, idempotency và contract chặn sớm, backend sẽ dễ lệch spec và khó kiểm soát các turn lỗi ngay từ đầu.

## What Changes

- Hoàn thiện request gate cho `POST /api/chat/message/` theo đúng thứ tự gate đã chốt trong spec: payload validation, identity resolve, idempotency, session validity, consent, quota, input basic guard, chat ownership.
- Chốt contract control response tối thiểu cho các lỗi gate thuộc phạm vi BE-2, gồm các mã lỗi và HTTP status cần trả ổn định ở API layer.
- Bổ sung idempotency behavior tối thiểu theo `client_turn_id`, bao gồm phân biệt `replay_previous_result` và `turn_in_progress`.
- Rà lại quota gate side effects cho `pending_input_text` và hành vi khác nhau giữa guest với registered user khi quota đã exhausted.
- Chốt behavior khi request resolve thành registered user nhưng vẫn còn guest cookie cũ, để request gate không giữ identity phụ trái với `Main-flow`.
- Bổ sung regression tests cho các nhánh gate chính để BE-2 có thể được verify độc lập trước khi sang runtime shell.

## Capabilities

### New Capabilities
- `chat-request-gate`: contract và behavior của request gate ở đầu mọi chat turn, bao gồm validation, gate ordering, idempotency, quota side effects và ownership checks.

### Modified Capabilities
None.

## Impact

- Affected code: `runtime/request_gate.py`, `chat/views.py`, `runtime/orchestrator.py`, request/response contracts trong `wismo/contracts/`, và test suite liên quan.
- Affected API: `POST /api/chat/message/` control responses ở giai đoạn request gate.
- Affected docs: `project-spec/frontend-backend-contract.md` cần mở rộng phần chat request gate nếu change chốt thêm payload hoặc error behavior.
- Verification: regression tests DB-backed cho request gate và `manage.py check`; pytest full suite vẫn phụ thuộc cấu hình Postgres local có password hợp lệ.
