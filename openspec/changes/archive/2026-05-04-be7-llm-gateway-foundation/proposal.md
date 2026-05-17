## Why

BE-7 cần chốt một LLM Gateway canonical trước khi các sprint runtime sâu hơn bắt đầu gọi model thật. Nếu mỗi step tự chọn provider/model hoặc tự ghi usage riêng, backend sẽ nhanh chóng lệch contract, khó đổi model theo `operation_key`, và quota/cost accounting sẽ không có một nguồn truth thống nhất.

## What Changes

- Xác lập `llm_ops` là lớp gateway duy nhất cho mọi LLM call trong MVP.
- Chuẩn hóa routing theo `operation_key` để mỗi operation map được sang supplier/model/params từ config thay vì hard-code trong runtime step.
- Thêm persisted usage logging cho từng LLM call, đủ để phục vụ quota accounting, cost debug, và truy vấn vận hành theo ngày/supplier/model/operation.
- Chốt boundary cho provider abstraction, gateway call interface, và structured result/usage shape để các runtime step sau dùng lại mà không phải viết adapter riêng.
- Chốt provider adapter boundary theo hướng một canonical provider profile duy nhất, nhưng gateway sẽ hỗ trợ nhiều wire modes: OpenAI-compatible, native Anthropic, Azure OpenAI v1, và native OpenAI/ChatGPT API.
- Chốt các entity nền `LLMSupplier`, `LLMModel`, `LLMOperationConfig`, và `LLMUsageEvent` làm schema canonical cho gateway foundation.
- Khóa bộ gateway error codes canonical cho missing/invalid config và provider failure để caller map lỗi nhất quán.
- Hiển thị `LLMUsageEvent` trực tiếp trong Django admin mặc định để vận hành xem usage ngay trong `/admin`.
- Giữ change này ở mức foundation nội bộ; chưa mở rộng sang dashboard vận hành đầy đủ hoặc tối ưu retry/fallback phức tạp ngoài nhu cầu nền tảng.

## Capabilities

### New Capabilities
- `llm-gateway-foundation`: Lớp LLM Gateway canonical cho MVP, gồm provider abstraction, operation-based routing, usage logging, và query nền theo ngày/supplier/model/operation.

### Modified Capabilities
- None.

## Impact

- `llm_ops`: thêm schema, service boundary, gateway interface, và usage query nền.
- `llm_ops.admin` / `/admin`: thêm changelist cho usage event với filter/search/date navigation hữu ích.
- `runtime`, `memory`, `knowledge`, `admin_config`: các consumer tương lai sẽ phải đi qua gateway này thay vì gọi provider trực tiếp.
- `project-spec/WISMO_BE_Implementation_Plan.md` và `project-spec/WISMO_MVP_Spec.md`: đây là source behavior chính cho BE-7; change/spec delta sẽ bám các requirement này.
- Django admin `/admin`: hiển thị `LLMUsageEvent` trực tiếp để xem usage theo event và lọc theo supplier/model/operation.
- Tests: cần regression coverage cho routing, usage persistence, và usage query.
- Dependencies: ưu tiên Django ORM/PostgreSQL hiện có; không mở rộng thêm external integration nếu chưa cần cho foundation.
