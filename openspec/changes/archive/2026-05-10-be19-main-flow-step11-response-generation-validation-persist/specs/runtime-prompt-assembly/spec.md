## ADDED Requirements

### Requirement: Step 10 phải hỗ trợ feedback-aware rebuild cho Step 11 retry loop
Step 10 MUST chấp nhận `generation_validation_feedback` từ Step 11 để rebuild `prompt_messages` cho lần generation retry tiếp theo, đồng thời giữ nguyên builder constraints cốt lõi của mode hiện tại.

#### Scenario: Rebuild prompt with generation feedback
- **WHEN** Step 11 truyền `generation_validation_feedback` hợp lệ
- **THEN** Step 10 MUST rebuild prompt có `rewrite_instruction` và `error_codes`
- **AND** MUST giữ `keep_constraints` để không lệch boundary/style rules

### Requirement: Feedback injection không được override response method/safety
Khi nhận `generation_validation_feedback`, Step 10 MUST NOT override `response_method` hoặc `final_safety_state` đã chốt từ Step 8.

#### Scenario: Preserve method and safety under feedback
- **WHEN** Step 10 rebuild prompt trong retry loop
- **THEN** `response_method` và `final_safety_state` MUST giữ nguyên

### Requirement: Step 10 cleanup metadata phải bám strict Main Flow/MVP
Step 10 MUST loại bỏ `effective_builder_name` khỏi output contract/debug metadata vì field này không nằm trong source-of-truth Main Flow/MVP cho Step 10/11.

#### Scenario: Prompt debug metadata cleanup
- **WHEN** Step 10 hoàn tất prompt assembly
- **THEN** `prompt_debug_meta` MUST không chứa `effective_builder_name`
- **AND** output debug chỉ giữ các field nằm trong contract Main Flow hiện hành
