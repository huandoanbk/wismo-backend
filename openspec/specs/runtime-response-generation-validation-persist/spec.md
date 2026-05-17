## ADDED Requirements

### Requirement: Step 11 chỉ chạy trên conversational continue path sau Step 10
Runtime MUST chạy Step 11 khi Step 10 đã tạo `prompt_messages` hợp lệ cho conversational turn và runtime đang ở continue-to-full-reasoning path.

#### Scenario: Step 11 entry condition satisfied
- **WHEN** `prompt_messages` đã có từ Step 10
- **AND** turn không thuộc terminal control response path
- **THEN** runtime MUST vào Step 11 pipeline

### Requirement: Step 11 phải gọi generation operation qua gateway registry
Runtime MUST gọi `OperationKey.RESPONSE_GENERATION` qua `LLMGateway` để sinh `candidate_response_text` và MUST NOT gọi provider trực tiếp.

#### Scenario: Generation routing
- **WHEN** Step 11 chạy generate
- **THEN** runtime MUST gọi `LLMGateway.complete(operation_key=response_generation, ...)`

### Requirement: Step 11 phải có logic validation trước validator LLM
Runtime MUST kiểm tra logic cơ bản (`candidate_response_text` rỗng/chỉ whitespace/lỗi coherence nặng) trước khi gọi validator LLM.

#### Scenario: Logic validation fail
- **WHEN** `candidate_response_text` rỗng hoặc chỉ whitespace
- **THEN** Step 11 MUST đi retry/fallback handling mà không cần validator LLM

#### Scenario: Logic validation pass
- **WHEN** `candidate_response_text` hợp lệ ở mức logic cơ bản
- **THEN** Step 11 MUST tiếp tục LLM validation

### Requirement: Step 11 phải gọi validation operation qua gateway registry
Runtime MUST gọi `OperationKey.RESPONSE_VALIDATION` qua `LLMGateway` để đánh giá `candidate_response_text` theo general + method-specific rules.

#### Scenario: Validation routing
- **WHEN** Step 11 chạy validator
- **THEN** runtime MUST gọi `LLMGateway.complete(operation_key=response_validation, ...)`

### Requirement: Validator input contract phải bám Step 11.4 của Main Flow
Validator payload MUST chứa đúng input contract Step 11.4: `candidate_response_text`, `response_method`, `final_safety_state`, `current_message`; kèm `normalized_reasoning_result` khi cần và `retrieval_result` khi `response_method = TEACH`.

#### Scenario: Validator input completeness
- **WHEN** Step 11 gọi validator
- **THEN** payload MUST có đủ `candidate_response_text`, `response_method`, `final_safety_state`, `current_message`
- **AND** nếu `response_method = TEACH` thì payload MUST có `retrieval_result` usable cho rule T1..T6

### Requirement: Validator output contract phải canonical
Step 11 MUST normalize validator output theo schema: `pass`, `severity`, `error_codes[]`, `rewrite_instruction`, `fallback_recommended`.

#### Scenario: Validator output parse/shape lệch
- **WHEN** validator trả payload sai shape hoặc thiếu field
- **THEN** Step 11 MUST normalize về schema canonical an toàn
- **AND** MUST tiếp tục retry/fallback flow mà không crash turn

### Requirement: Retry loop Step 11 phải giới hạn tối đa 2 lần corrective
Khi generation/validation fail, Step 11 MUST tăng `generation_retry_count`; nếu `generation_retry_count <= 2`, runtime MUST tạo `generation_validation_feedback`, gọi lại Step 10 để rebuild prompt, rồi generate lại.

#### Scenario: Retry within budget
- **WHEN** validation fail và `generation_retry_count <= 2`
- **THEN** Step 11 MUST tạo feedback gồm `error_codes`, `rewrite_instruction`, `keep_constraints`
- **AND** MUST gọi lại Step 10 trước lần generate kế tiếp

### Requirement: Exhausted retry phải đi safe fallback response
Khi `generation_retry_count > 2`, Step 11 MUST build safe fallback response thay vì retry thêm.

#### Scenario: Fallback ASK
- **WHEN** retry exhausted và `fallback_recommended = ASK`
- **THEN** Step 11 MUST build 1 clarify question ngắn, an toàn

#### Scenario: Fallback LISTEN default
- **WHEN** retry exhausted và fallback không phải ASK
- **THEN** Step 11 MUST build 1 LISTEN fallback ngắn, trung tính, an toàn

### Requirement: Persist and stream success/fallback phải cùng contract
Step 11 MUST persist final assistant response (generated hoặc fallback), persist runtime metadata tối thiểu, stream `response`, rồi stream `done`.

#### Scenario: Success persist and done
- **WHEN** candidate response pass validation
- **THEN** runtime MUST persist assistant response
- **AND** MUST stream `response` trước `done`

#### Scenario: Fallback persist and done
- **WHEN** Step 11 dùng safe fallback response
- **THEN** runtime MUST persist fallback response
- **AND** MUST stream `response` trước `done`

### Requirement: Step 11 metadata phải lưu retry/validation trace tối thiểu
Runtime MUST lưu metadata tối thiểu phục vụ audit/debug: generation retry count, validation outcome cuối, fallback used hay không.

#### Scenario: Metadata persisted
- **WHEN** Step 11 hoàn tất (success hoặc fallback)
- **THEN** runtime MUST có trace metadata tối thiểu trong persisted turn
