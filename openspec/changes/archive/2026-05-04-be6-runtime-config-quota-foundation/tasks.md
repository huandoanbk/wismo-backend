## 1. Runtime config boundary

- [x] 1.1 Tạo service canonical để đọc `RuntimeConfig` active với default fallback cho các key limit và policy của runtime.
- [x] 1.2 Chuẩn hóa map cấu hình nền cho `runtime.input_limits`, `quota.guest_policy`, `quota.user_policy`, và `quota.pending_input_limits` để runtime consumers đọc cùng một nguồn truth.

## 2. Quota window lifecycle

- [x] 2.1 Tách helper resolve current `UsageQuotaWindow` theo guest/user, gồm current window lookup, tạo window khi thiếu, và rollover khi window hết hạn.
- [x] 2.2 Bảo đảm cập nhật quota window là atomic bằng transaction/row-level lock và giữ side effect `pending_input_text` / `pending_input_updated_at` theo bounds config trong cùng boundary.

## 3. Runtime wiring

- [x] 3.1 Update `runtime.request_gate` để đọc quota/current-window qua service mới thay vì logic rời rạc hoặc hardcode limit.
- [x] 3.2 Update `runtime.orchestrator` Step 12 để consume quota và chốt exhausted state qua service boundary thống nhất.

## 4. Tests and verification

- [x] 4.1 Thêm unit tests cho runtime config lookup, default fallback, `pending_input_limits`, và quota window rollover.
- [x] 4.2 Thêm regression tests cho quota exhausted path, pending input persistence theo config bounds, và Step 12 quota update.
- [x] 4.3 Chạy `./.venv/bin/python manage.py check`, `./.venv/bin/pytest`, và `./.venv/bin/ruff check .` để xác nhận change.
