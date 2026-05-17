## ADDED Requirements

### Requirement: Gateway config is operator-managed
Hệ thống SHALL cho phép operator khai báo một `LLMGatewayConfig` canonical trong Django admin để đại diện cho một gateway/provider integration thật.

`LLMGatewayConfig` SHALL có đủ dữ liệu để route request mà không cần suy diễn ngầm:

- `name`
- `integration_kind`
- endpoint/base URL hoặc endpoint tương đương
- API key hoặc credential reference
- model name hoặc deployment name
- `mode`
- `params`
- `is_active`

#### Scenario: Gateway config is created in admin
- **WHEN** admin user tạo một `LLMGatewayConfig` mới
- **THEN** hệ thống SHALL lưu config đó như nguồn truth cho provider integration

#### Scenario: Missing gateway fields are rejected
- **WHEN** gateway config thiếu `integration_kind`, endpoint, auth reference, model/deployment, hoặc `mode`
- **THEN** hệ thống SHALL không coi config đó là hợp lệ để route LLM call

### Requirement: LLMOperation is a registry of LLM use cases
Hệ thống SHALL cho phép khai báo `LLMOperation` như registry cho một LLM use case hoặc step call cụ thể.

`LLMOperation` SHALL có ít nhất:

- `code` hoặc `name` canonical
- `description`
- `gateway` nullable
- `is_active`

#### Scenario: New operation can exist before gateway binding
- **WHEN** dev tạo một `LLMOperation` mới cho một step vừa bắt đầu dùng LLM
- **THEN** hệ thống SHALL cho phép operation đó tồn tại với `gateway = null` cho tới khi admin bind gateway

#### Scenario: Operation is introduced during implementation
- **WHEN** dev triển khai một runtime step mới và xác định step đó cần LLM
- **THEN** hệ thống SHALL cho phép dev thêm một `LLMOperation` registry entry mới cho use case đó, rồi để `gateway = null` cho tới khi admin bind gateway phù hợp

#### Scenario: Operation registry is unique by code
- **WHEN** operator tạo hai `LLMOperation` cùng code/name canonical
- **THEN** hệ thống SHALL reject duplicate entry để tránh mơ hồ khi routing

### Requirement: Operation binding to gateway is configurable
Hệ thống SHALL cho phép admin gán hoặc đổi `gateway` cho từng `LLMOperation` mà không sửa runtime code.

#### Scenario: Operation is bound to a gateway
- **WHEN** admin user gán một `LLMGatewayConfig` active vào `LLMOperation`
- **THEN** operation đó SHALL dùng gateway vừa gán cho các call tiếp theo

#### Scenario: Operation gateway can be changed later
- **WHEN** admin user đổi gateway đang bind cho một `LLMOperation`
- **THEN** hệ thống SHALL dùng gateway mới cho các call tiếp theo

### Requirement: Unbound operation fails closed
Hệ thống SHALL fail closed nếu một `LLMOperation` active chưa được gán gateway hợp lệ.

#### Scenario: Unbound operation is rejected at runtime
- **WHEN** runtime step gọi một `LLMOperation` còn `gateway = null` hoặc gateway inactive
- **THEN** gateway SHALL không gọi provider và SHALL trả lỗi canonical cho caller

#### Scenario: Inactive operation is rejected
- **WHEN** runtime step gọi một `LLMOperation` inactive
- **THEN** gateway SHALL không gọi provider và SHALL fail closed

### Requirement: Provider integration kinds are supported
Hệ thống SHALL hỗ trợ các `integration_kind` canonical sau:

- `openai_compatible`
- `anthropic_native`
- `azure_openai_v1`
- `openai_native`

#### Scenario: OpenAI-compatible integration is accepted
- **WHEN** `LLMGatewayConfig` có `integration_kind = openai_compatible`
- **THEN** gateway SHALL route qua wire contract OpenAI-compatible, ví dụ DeepInfra hoặc provider compatible tương tự

#### Scenario: Anthropic native integration is accepted
- **WHEN** `LLMGatewayConfig` có `integration_kind = anthropic_native`
- **THEN** gateway SHALL route qua Claude API native contract

#### Scenario: Azure OpenAI integration is accepted
- **WHEN** `LLMGatewayConfig` có `integration_kind = azure_openai_v1`
- **THEN** gateway SHALL route qua Azure OpenAI API v1 contract

#### Scenario: OpenAI native integration is accepted
- **WHEN** `LLMGatewayConfig` có `integration_kind = openai_native`
- **THEN** gateway SHALL route qua OpenAI/ChatGPT API native contract

### Requirement: Provider-specific prompt serialization is adapter-owned
Hệ thống SHALL không giả định một prompt template chung cho mọi provider.

Adapter boundary SHALL tự serialize input theo `integration_kind` và `mode` của gateway, để wire payload đúng với từng nhà cung cấp.

#### Scenario: Conversation payload is provider-specific
- **WHEN** gateway chạy ở `mode = conversation`
- **THEN** adapter SHALL serialize conversation theo wire contract phù hợp với provider kind thay vì copy nguyên một template OpenAI-compatible cho mọi provider

#### Scenario: Single message payload is provider-specific
- **WHEN** gateway chạy ở `mode = single_message`
- **THEN** adapter SHALL serialize input thành một prompt/message tối giản nhưng vẫn theo wire contract đúng của provider kind

#### Scenario: Azure/OpenAI/Anthropic wire shape differs
- **WHEN** adapter gọi Azure OpenAI, Anthropic native, hoặc OpenAI native
- **THEN** gateway SHALL dùng serializer riêng cho provider đó và SHALL không reuse máy móc một template conversation duy nhất cho tất cả

### Requirement: Local stub is not production canonical
Hệ thống SHALL không coi `local_stub` là gateway canonical cho production routing.

`local_stub` chỉ được dùng trong dev/test adapter hoặc fixture nội bộ nếu cần cho verification.

#### Scenario: Production config cannot use local stub
- **WHEN** operator cấu hình production gateway với `local_stub`
- **THEN** hệ thống SHALL reject cấu hình đó hoặc fail closed khi resolve routing

#### Scenario: Dev/test may still use a stub adapter
- **WHEN** môi trường dev/test cần deterministic adapter cho verification
- **THEN** hệ thống SHALL cho phép stub adapter nội bộ nhưng không đưa nó vào canonical production gateway set

### Requirement: Operation and gateway are visible in Django admin
Hệ thống SHALL expose `LLMGatewayConfig` và `LLMOperation` trong Django admin để operator tạo gateway, tạo operation, và gán operation vào gateway.

#### Scenario: Operator can create gateway and operation separately
- **WHEN** admin user tạo gateway trước, rồi tạo operation sau
- **THEN** hệ thống SHALL cho phép operation đó tồn tại cho tới khi admin bind gateway

#### Scenario: Operator can inspect unbound operations
- **WHEN** admin user mở danh sách `LLMOperation`
- **THEN** hệ thống SHALL hiển thị operation nào đang chưa có gateway để operator biết cần bind trước khi step runtime dùng nó
