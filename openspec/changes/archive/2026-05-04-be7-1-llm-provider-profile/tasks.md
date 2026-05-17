## 1. Schema và migration

- [x] 1.1 Thêm `LLMGatewayConfig` canonical và các field cần cho `integration_kind`, endpoint/base URL, auth reference, model/deployment, `mode`, `params`, `is_active`, và display name.
- [x] 1.2 Thêm `LLMOperation` registry với `gateway` nullable để dev có thể tạo operation dần theo tiến độ triển khai từng step.
- [x] 1.3 Bổ sung migration/backfill từ cấu hình split hiện có sang gateway/operation registry mới.
- [x] 1.4 Cập nhật index/constraint cần thiết để lookup operation và gateway binding vẫn deterministic.

## 2. Gateway và adapter

- [x] 2.1 Implement adapter registry theo `integration_kind` và dispatch tới `openai_compatible`, `anthropic_native`, `azure_openai_v1`, `openai_native`.
- [x] 2.2 Implement serialization theo `mode` canonical, với wire template riêng cho từng provider kind.
- [x] 2.3 Loại `local_stub` khỏi canonical production routing và giữ nó chỉ như dev/test adapter nếu còn cần.
- [x] 2.4 Bảo toàn normalized gateway contract và usage logging hiện có khi chuyển sang gateway/operation model mới.

## 3. Admin và bootstrap

- [x] 3.1 Expose `LLMGatewayConfig` và `LLMOperation` trong Django admin để operator tạo, sửa, bật/tắt, và gán operation vào gateway.
- [x] 3.2 Cập nhật bootstrap/seed/dev fixture để dùng gateway/operation registry mới thay cho cấu hình split cũ.
- [x] 3.3 Đảm bảo danh sách operation hiển thị rõ operation nào chưa bind gateway để admin biết cần cấu hình trước khi runtime dùng.

## 4. Regression và verification

- [x] 4.1 Bổ sung unit/regression tests cho routing theo `LLMGatewayConfig`/`LLMOperation`, wire mode `single_message`/`conversation`, provider-specific serialization, và reject `local_stub` production.
- [x] 4.2 Chạy `manage.py check`, `pytest`, `ruff check .`, và `makemigrations --check --dry-run` để xác nhận change apply được.
