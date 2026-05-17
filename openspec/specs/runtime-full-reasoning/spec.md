## ADDED Requirements

### Requirement: Step 7 chỉ chạy trên continue-to-full-reasoning path
Runtime MUST chạy Step 7 chỉ khi Step 4 quyết định `continue_to_full_reasoning` và Step 6 đã assemble xong `runtime_bundle` cho turn hiện tại.

#### Scenario: Continue path vào Step 7
- **WHEN** `triage_decision = continue_to_full_reasoning`
- **AND** Step 6 đã tạo `runtime_bundle`
- **THEN** runtime MUST chạy Step 7 (Full reasoning)

### Requirement: Step 7 phải gọi LLM operation `full_reasoning` qua gateway registry
Step 7 MUST gọi `OperationKey.FULL_REASONING` qua `LLMGateway` và MUST NOT gọi provider trực tiếp hay hard-code model/supplier.

#### Scenario: Full reasoning routing
- **WHEN** Step 7 chạy
- **THEN** runtime MUST gọi `LLMGateway.complete(operation_key=full_reasoning, ...)`
- **AND** routing MUST đi qua operation registry hiện tại

### Requirement: Step 7 chỉ đọc từ runtime_bundle đã assemble ở Step 6
Step 7 MUST dùng `runtime_bundle` làm source of truth input và MUST NOT reload `current_message`, `recent_turns`, `context_summary`, `user_profile`, `user_preference`, `user_state`, `long_term_memory` từ DB.

#### Scenario: Runtime bundle read-only contract
- **WHEN** Step 7 xử lý reasoning
- **THEN** input runtime MUST lấy từ `runtime_bundle`
- **AND** Step 7 MUST NOT query lại các field core Step 6

### Requirement: Step 7 hỗ trợ corrective retry qua reasoning_control
Step 7 MUST chấp nhận `reasoning_control` optional để chạy corrective reasoning khi Step 8 callback.

#### Scenario: Normal reasoning
- **WHEN** `reasoning_control` không có
- **THEN** Step 7 MUST chạy normal reasoning và trả `reasoning_result` canonical

#### Scenario: Corrective retry reasoning
- **WHEN** `reasoning_control.is_corrective_retry = true`
- **THEN** Step 7 MUST đọc `validation_error_feedback`
- **AND** Step 7 MUST sửa các field trong `must_fix_fields`
- **AND** Step 7 MUST giữ các ràng buộc trong `must_preserve`
- **AND** output vẫn MUST theo schema `reasoning_result` chuẩn

### Requirement: Output Step 7 phải là reasoning_result schema đóng
Step 7 MUST chuẩn hóa output thành object `reasoning_result` gồm đúng các field canonical phục vụ Step 8+.

#### Scenario: Reasoning result completeness
- **WHEN** Step 7 hoàn tất
- **THEN** `reasoning_result` MUST có đủ field: `risk_flags`, `intent`, `action_recommended`, `is_context_sufficient`, `required_next_slots`, `case_slots`, `turn_strategy`, `explicit_profile_facts`, `style_signals`, `user_state_signals`, `suggested_chat_display_name`

### Requirement: Step 7 phải có fallback canonical khi output LLM không hợp lệ
Nếu output của `full_reasoning` parse/schema fail, Step 7 MUST tạo `reasoning_result` fallback canonical để runtime không vỡ flow trước Step 8.

#### Scenario: Invalid schema fallback
- **WHEN** output full reasoning thiếu field bắt buộc hoặc sai enum/shape
- **THEN** Step 7 MUST normalize về `reasoning_result` fallback an toàn
- **AND** runtime MUST vẫn đi tiếp Step 8

### Requirement: Gateway/provider fail ở Step 7 phải retry tối đa 2 lần rồi mới fail
Khi gọi `full_reasoning` gặp lỗi gateway/provider dạng transient, Step 7 MUST retry trong cùng turn tối đa 2 lần. Nếu vẫn thất bại sau 2 lần retry, runtime MUST trả lỗi cho FE và MUST NOT fallback sang `reasoning_result`.

#### Scenario: Retry thành công trong giới hạn
- **WHEN** lần gọi đầu lỗi transient nhưng retry thành công trong tối đa 2 lần
- **THEN** Step 7 MUST tiếp tục flow bình thường với output reasoning hợp lệ

#### Scenario: Retry thất bại quá giới hạn
- **WHEN** gọi `full_reasoning` vẫn lỗi sau tối đa 2 lần retry
- **THEN** runtime MUST đi exception/error path và trả lỗi cho FE
- **AND** runtime MUST NOT tạo fallback `reasoning_result` cho lỗi gateway/provider

### Requirement: Step 7 phải cập nhật runtime state cục bộ cho retry management
Step 7 MUST duy trì `reasoning_retry_count` trong runtime state cục bộ để Step 8/loop dùng cho corrective retry control.

#### Scenario: Retry state tracking
- **WHEN** Step 7 được gọi ở normal hoặc corrective path
- **THEN** runtime MUST có `reasoning_retry_count` trong runtime state
- **AND** giá trị này MUST được dùng nhất quán cho các vòng retry cùng turn
