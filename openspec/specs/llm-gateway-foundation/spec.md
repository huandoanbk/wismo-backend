## ADDED Requirements

### Requirement: Operation key canonical set
Hệ thống SHALL định nghĩa và hỗ trợ bộ `operation_key` canonical tối thiểu sau đây cho MVP:

- `triage_classifier`
- `case_detector`
- `case_reresolution_classifier`
- `full_reasoning`
- `response_generation`
- `response_validation`
- `retrieval_query_builder`
- `retrieval_query_embedding`
- `retrieval_stitch_validator`
- `context_summary_updater`
- `long_term_memory_extractor`

#### Scenario: Supported canonical operation key is accepted
- **WHEN** gateway nhận một request với `operation_key` nằm trong bộ canonical tối thiểu
- **THEN** hệ thống SHALL coi key đó là hợp lệ để tiếp tục bước resolve config và usage logging

#### Scenario: Unsupported operation key is rejected
- **WHEN** gateway nhận một request với `operation_key` ngoài bộ canonical tối thiểu
- **THEN** hệ thống SHALL không route request đó sang provider và SHALL fail closed

### Requirement: Gateway resolves operation config canonically
Hệ thống SHALL resolve active `LLMOperation` theo `operation_key` và SHALL dùng gateway binding `LLMGatewayConfig` tương ứng khi thực hiện call.

#### Scenario: Active config is used for routing
- **WHEN** `operation_key` có một `LLMOperation` active với `LLMGatewayConfig` active hợp lệ
- **THEN** gateway SHALL chọn đúng gateway binding từ registry thay vì suy diễn default ngầm

#### Scenario: Missing config fails closed
- **WHEN** `operation_key` không có `LLMOperation` active hợp lệ hoặc operation không được bind gateway hợp lệ
- **THEN** gateway SHALL không gọi provider và SHALL raise lỗi domain canonical `llm_gateway_config_missing` để caller map sang error envelope của runtime

#### Scenario: Inactive or malformed config is rejected
- **WHEN** `operation_key` có registry entry nhưng gateway inactive, thiếu, hoặc không hợp lệ
- **THEN** gateway SHALL không gọi provider và SHALL raise lỗi domain canonical `llm_gateway_config_invalid`

### Requirement: Provider calls use a normalized adapter boundary
Hệ thống SHALL gọi provider qua một adapter boundary chuẩn hóa để runtime callers không phụ thuộc vào payload shape riêng của từng supplier.

Adapter boundary này SHALL hỗ trợ một canonical provider profile duy nhất ở mức cấu hình, nhưng profile đó có thể map sang nhiều wire mode:

- `openai_compatible` cho DeepInfra, Gemini compatibility endpoint, và các vendor OpenAI-compatible khác
- `anthropic_native` cho Claude API native
- `azure_openai_v1` cho Azure OpenAI API v1
- `openai_native` cho OpenAI/ChatGPT API native

Canonical profile SHALL allow operator/admin to declare:

- endpoint/base URL hoặc endpoint tương đương
- API key hoặc secret reference tương đương
- model name hoặc deployment name tương đương
- `mode` / `input_mode` để chọn `single_message` hoặc `conversation`
- provider-specific request params trong `params`

#### Scenario: Different suppliers share the same gateway contract
- **WHEN** gateway chuyển `operation_key` sang supplier khác nhau theo config
- **THEN** caller SHALL nhận cùng một normalized gateway result contract thay vì payload vendor-specific

#### Scenario: Provider-specific details do not leak to callers
- **WHEN** provider trả về response shape khác nhau theo supplier
- **THEN** gateway SHALL normalize response đó trước khi trả cho caller

#### Scenario: Canonical provider profile can represent different wire modes
- **WHEN** admin cấu hình một canonical provider profile cho DeepInfra, Claude API, Azure OpenAI API, hoặc OpenAI/ChatGPT API
- **THEN** gateway SHALL route qua adapter mode tương ứng và SHALL dùng endpoint, auth, model/deployment name, and input mode từ profile đó

### Requirement: Every LLM call persists a usage event
Hệ thống SHALL persist một `LLMUsageEvent` cho mỗi LLM call đi qua gateway, và event đó SHALL mang `turn_id`, `operation_key`, `supplier_name`, `model_name`, `input_tokens`, `cached_input_tokens`, `output_tokens`, `cache_write_tokens`, `total_billable_tokens`, `latency_ms`, `status`, `error_code`, và `created_at`.

#### Scenario: Successful call stores usage data
- **WHEN** provider trả response thành công kèm usage tokens
- **THEN** hệ thống SHALL lưu một `LLMUsageEvent` với các trường canonical tương ứng cho turn hiện tại

#### Scenario: Failed call still stores usage event
- **WHEN** provider call thất bại sau khi gateway đã bắt đầu xử lý
- **THEN** hệ thống SHALL vẫn lưu một `LLMUsageEvent` với `status` thất bại và `error_code` phù hợp

### Requirement: Gateway provider failures use canonical error codes
Hệ thống SHALL dùng error code canonical cho provider failure path để runtime caller có thể map lỗi nhất quán.

#### Scenario: Provider unavailable is canonical
- **WHEN** provider không sẵn sàng hoặc request tới adapter/provider thất bại trước khi có response hợp lệ
- **THEN** gateway SHALL raise lỗi domain canonical `llm_gateway_provider_unavailable`

#### Scenario: Provider call failed is canonical
- **WHEN** provider trả lỗi trong lúc xử lý request LLM hợp lệ
- **THEN** gateway SHALL raise lỗi domain canonical `llm_gateway_provider_error`

### Requirement: Usage can be queried by day, supplier, model, and operation
Hệ thống SHALL hỗ trợ query aggregate usage từ `LLMUsageEvent` theo ngày và lọc theo `supplier_name`, `model_name`, và `operation_key`.

#### Scenario: Daily aggregate query returns grouped totals
- **WHEN** admin/dev query usage cho một ngày cụ thể
- **THEN** hệ thống SHALL trả aggregate theo ngày với tổng event count và token totals cho các event khớp

#### Scenario: Filtered query narrows the result set
- **WHEN** admin/dev query usage theo ngày kèm `supplier_name`, `model_name`, hoặc `operation_key`
- **THEN** hệ thống SHALL chỉ trả aggregate của các event khớp với toàn bộ bộ lọc đã cung cấp

### Requirement: LLM usage is visible in Django admin
Hệ thống SHALL hiển thị `LLMUsageEvent` trong Django admin mặc định để vận hành có thể xem event usage trực tiếp trong `/admin` mà không cần custom report endpoint.

#### Scenario: Admin can inspect usage events
- **WHEN** admin user mở changelist của `LLMUsageEvent` trong `/admin`
- **THEN** hệ thống SHALL hiển thị event usage theo từng dòng và cho phép lọc theo `operation_key`, `status`, `supplier_name`, `model_name`, và ngày tạo

#### Scenario: Admin changelist exposes useful search and date navigation
- **WHEN** admin user cần tìm một usage event cụ thể
- **THEN** changelist SHALL hỗ trợ search theo `turn`, `supplier_name`, `model_name`, và `operation_key`, đồng thời SHALL có `date_hierarchy` theo `created_at`
