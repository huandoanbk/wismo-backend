## 1. Schema nền

- [x] 1.1 Rà soát và hoàn thiện model/migration cho `LLMSupplier`, `LLMModel`, `LLMOperationConfig`, `LLMUsageEvent`, cùng index cần cho query theo `created_at`, `supplier`, `model`, và `operation_key`.
- [x] 1.2 Thêm seed/fixture/dev bootstrap tối thiểu cho canonical `operation_key` để môi trường local và test có thể resolve config deterministically.

## 2. Gateway boundary

- [x] 2.1 Implement provider adapter interface chuẩn hóa trong `llm_ops` và một gateway service duy nhất để caller chỉ làm việc với contract normalized.
- [x] 2.2 Implement resolve flow theo `operation_key` -> config -> `supplier`/`model`/params, fail closed khi config thiếu hoặc invalid bằng domain error canonical.
- [x] 2.3 Loại bỏ fallback auto-create provider/model mặc định trong gateway foundation.
- [x] 2.4 Persist `LLMUsageEvent` cho mọi call thành công/thất bại, mang đầy đủ field canonical từ spec.
- [x] 2.5 Khóa canonical gateway error codes và test chúng qua missing config, invalid config, provider unavailable, và provider error.

## 3. Usage query

- [x] 3.1 Implement query/aggregation service cho usage theo ngày với filter `supplier`, `model`, và `operation_key`.
- [x] 3.2 Expose `LLMUsageEvent` trong Django admin mặc định với filter/search/date hierarchy phù hợp.
- [x] 3.3 Bổ sung unit/regression tests cho routing, fail-closed behavior, usage event persistence, aggregate query, và admin visibility.

## 4. Verification

- [x] 4.1 Chạy `manage.py check`, `pytest`, `ruff check .`, và `makemigrations --check --dry-run` để xác nhận change apply được.
