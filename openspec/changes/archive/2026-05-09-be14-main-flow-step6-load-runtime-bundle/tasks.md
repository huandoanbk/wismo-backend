## 1. Spec Alignment và Runtime Contract

- [x] 1.1 Chốt Step 6 contract theo Main Flow + MVP spec với 2 path `case_id` resolved/null.
- [x] 1.2 Cập nhật capability specs (`runtime-bundle-loading`, `runtime-case-resolution`) cho handoff Step 5 -> Step 6.
- [x] 1.3 Xác nhận runtime bundle canonical fields dùng chung cho Step 7+.

## 2. Runtime Bundle Service

- [x] 2.1 Tạo service chuyên trách load Step 6 bundle data từ DB/retrieval.
- [x] 2.2 Implement load `recent_turns` max 5 theo chat và chuẩn hóa thứ tự cũ -> mới.
- [x] 2.3 Implement load `context_summary` theo case khi `case_id` có giá trị.
- [x] 2.4 Implement load `user_profile`, `user_preference`, `user_state` với fallback `{}`.
- [x] 2.5 Implement retrieve `long_term_memory` theo case và chỉ lấy item active/enabled.

## 3. Null-case và Fallback Behavior

- [x] 3.1 Implement null-case path: `case_id = null` vẫn assemble bundle, `context_summary = ""`, `long_term_memory = []`.
- [x] 3.2 Implement retrieval-fail fallback: không crash Step 6, trả memory rỗng.
- [x] 3.3 Giữ contract bundle ổn định giữa resolved/null path mà không thêm flag/telemetry phụ.

## 4. Orchestrator Wiring

- [x] 4.1 Refactor `_load_runtime_bundle()` để dùng service Step 6 thay vì placeholder cứng.
- [x] 4.2 Đảm bảo Step 7+ chỉ đọc từ `state.runtime_bundle` đã assemble.
- [x] 4.3 Đảm bảo không có step downstream reload lại core fields từ DB trong cùng turn.

## 5. Tests và Verification

- [x] 5.1 Thêm unit tests cho Step 6 resolved-case path.
- [x] 5.2 Thêm unit tests cho Step 6 null-case path.
- [x] 5.3 Thêm unit tests cho retrieval-fail fallback path.
- [x] 5.4 Thêm regression test cho ownership rule của runtime bundle.
- [x] 5.5 Chạy `manage.py check`, `pytest`, `ruff check .`, `makemigrations --check --dry-run` và xử lý failures.
