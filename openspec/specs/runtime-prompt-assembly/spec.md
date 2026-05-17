# runtime-prompt-assembly Specification

## Purpose
TBD - created by archiving change be18-main-flow-step10-prompt-assembly. Update Purpose after archive.
## Requirements
### Requirement: Step 10 chỉ chạy cho conversational path sau Step 8/9
Runtime MUST chạy Step 10 chỉ khi turn đang ở continue-to-full-reasoning path và `response_method` thuộc nhóm conversational (`LISTEN`, `ASK`, `REFLECT`, `FOLLOWUP`, `TEACH`). Step 10 MUST NOT override lại `final_safety_state` hay `response_method` đã chốt ở Step 8.

#### Scenario: Conversational method đi vào Step 10
- **WHEN** Step 8 đã chốt `response_method` thuộc nhóm conversational
- **THEN** runtime MUST chạy Step 10 prompt assembly
- **AND** MUST giữ nguyên `response_method` và `final_safety_state`

#### Scenario: Terminal control path không vào Step 10
- **WHEN** turn đã short-circuit ở control branch trước Step 5+
- **THEN** Step 10 MUST NOT chạy

#### Scenario: Non-conversational method không vào Step 10
- **WHEN** runtime state có `response_method` ngoài conversational set
- **THEN** Step 10 MUST NOT assemble prompt mới

### Requirement: Step 10 chỉ dùng runtime state đã assemble
Step 10 MUST chỉ đọc dữ liệu từ `runtime_bundle`, output Step 8 (`normalized_reasoning_result`, `final_safety_state`, `response_method`, `retrieval_required`) và output Step 9 (`retrieval_result` nếu có). Step 10 MUST NOT fetch lại context nền hay memory từ DB.

#### Scenario: Runtime bundle usage boundary
- **WHEN** Step 10 build prompt
- **THEN** input context MUST đến từ runtime state hiện tại
- **AND** Step 10 MUST NOT query lại context nền Step 6

### Requirement: Output Step 10 phải theo contract cố định
Step 10 MUST append vào runtime state đúng 2 output: `prompt_messages` và `prompt_debug_meta`.

#### Scenario: Output contract completeness
- **WHEN** Step 10 hoàn tất
- **THEN** `prompt_messages` MUST có đúng 2 phần tử: 1 `system message` và 1 `user message`
- **AND** `prompt_debug_meta` MUST có `builder_name`, `used_fields`, `compact_applied`, `estimated_tokens`

### Requirement: Builder selection phải map 1-1 theo response_method
Step 10 MUST chọn builder theo mapping cố định:
- `LISTEN` -> `build_listen_prompt`
- `ASK` -> `build_ask_prompt`
- `REFLECT` -> `build_reflect_prompt`
- `FOLLOWUP` -> `build_followup_prompt`
- `TEACH` -> `build_teach_prompt`

#### Scenario: Builder dispatch đúng method
- **WHEN** `response_method` đã được chốt ở Step 8
- **THEN** Step 10 MUST dùng builder tương ứng theo mapping
- **AND** MUST NOT dispatch builder khác trừ khi fallback rule áp dụng

### Requirement: Shared composition rules phải áp dụng cho mọi builder
Mọi builder MUST tạo `system message` chứa boundary/style/output-goal constraint và `user message` chứa `current_message`, context tối thiểu cần thiết, cùng instruction để sinh response cuối cho user.

#### Scenario: Shared composition structure
- **WHEN** bất kỳ builder nào chạy thành công
- **THEN** `system message` MUST chứa constraints theo mode hiện tại
- **AND** `user message` MUST chứa `current_message` và context tối thiểu

### Requirement: LISTEN builder phải tuân thủ constraint mode LISTEN
LISTEN builder MUST dùng input `current_message`; MAY dùng `context_summary` ngắn và `recent_turns` rất ngắn khi có. Output instruction MUST giữ mode LISTEN: ngắn hoặc vừa, ấm/rõ/tự nhiên, không sermon, không bullet/checklist, không teaching/chẩn đoán, tối đa 1 câu hỏi mở nhẹ nếu cần.

#### Scenario: LISTEN normal contract
- **WHEN** `response_method = LISTEN` và input đủ
- **THEN** prompt LISTEN MUST chứa đầy đủ constraint mode LISTEN theo Main Flow

### Requirement: ASK builder phải tuân thủ constraint mode ASK
ASK builder MUST dùng `required_next_slots` và `case_slots` để hỏi đúng slot còn thiếu; MUST giới hạn tối đa 1-2 câu hỏi; MUST không mở topic mới, không teaching, không sermon, không interrogation.

#### Scenario: ASK normal contract
- **WHEN** `response_method = ASK`
- **THEN** prompt ASK MUST ràng buộc chỉ hỏi trong `required_next_slots`
- **AND** MUST giới hạn 1-2 câu hỏi trọng tâm

### Requirement: REFLECT builder phải tuân thủ constraint mode REFLECT
REFLECT builder MUST phản chiếu pattern/tension chính từ input hiện có; MUST không phán xét; MUST không chuyển sang teaching hoặc advice list; MAY kết bằng 1 câu mở nhẹ nếu phù hợp.

#### Scenario: REFLECT normal contract
- **WHEN** `response_method = REFLECT`
- **THEN** prompt REFLECT MUST giữ đúng boundary phản chiếu, không teaching

### Requirement: FOLLOWUP builder phải tuân thủ constraint mode FOLLOWUP
FOLLOWUP builder MUST giữ continuity case hiện tại, ưu tiên update mới của user, nhắc mạch cũ thật ngắn khi cần, không lặp dài context cũ và không tự chuyển sang TEACH.

#### Scenario: FOLLOWUP normal contract
- **WHEN** `response_method = FOLLOWUP`
- **THEN** prompt FOLLOWUP MUST ràng buộc continuity rõ với case hiện tại

### Requirement: TEACH builder phải tuân thủ constraint mode TEACH
TEACH builder MUST bám đúng 1 retrieval unit đã cung cấp; MUST không bịa thêm nguồn; MUST không nhắc source/tác giả/yếu tố tôn giáo trong phản hồi; MUST tránh sermon dài; MUST gắn teaching trực tiếp với vấn đề hiện tại của user.

#### Scenario: TEACH normal contract
- **WHEN** `response_method = TEACH` và retrieval usable
- **THEN** prompt TEACH MUST chứa đầy đủ ràng buộc mode TEACH

### Requirement: LISTEN builder fallback phải non-fatal
Nếu thiếu `style_signals` hoặc `user_state_signals`, LISTEN builder MUST fallback về tone trung tính, nhẹ, ngắn. Nếu thiếu context phụ, builder MUST chỉ bám `current_message`.

#### Scenario: LISTEN thiếu signals/context phụ
- **WHEN** LISTEN input thiếu một phần signals hoặc context phụ
- **THEN** builder MUST vẫn tạo prompt hợp lệ
- **AND** MUST không fail Step 10

### Requirement: REFLECT builder fallback phải non-fatal
Nếu thiếu `context_summary` hoặc `case_slots`, REFLECT builder MUST reflect dựa trên `current_message`. Nếu thiếu `intent`, builder MUST bỏ field đó khỏi payload thay vì fail.

#### Scenario: REFLECT thiếu context hoặc intent
- **WHEN** REFLECT input thiếu context hoặc intent
- **THEN** builder MUST degrade về payload tối thiểu
- **AND** MUST tiếp tục Step 11

### Requirement: FOLLOWUP builder fallback không được bịa continuity
FOLLOWUP builder MUST dùng `turn_strategy` khi có; nếu thiếu `turn_strategy` thì fallback theo `context_summary`, và nếu thiếu cả hai thì followup-lite từ `current_message` + `recent_turns` ngắn (nếu có). Builder MUST NOT bịa continuity khi context cũ không còn.

#### Scenario: FOLLOWUP thiếu turn_strategy/context_summary
- **WHEN** FOLLOWUP input thiếu dữ liệu continuity chính
- **THEN** builder MUST hạ cấp sang followup-lite hợp lệ
- **AND** MUST không phát minh continuity không có trong input

### Requirement: TEACH builder phải bám retrieval unit và có fallback bắt buộc
TEACH builder MUST chỉ dùng retrieval unit đã chọn trong `retrieval_result` để assemble prompt. Nếu `retrieval_result = null` hoặc `retrieval_unit_text` rỗng/lỗi, Step 10 MUST fallback sang LISTEN builder.

#### Scenario: TEACH retrieval usable
- **WHEN** `response_method = TEACH` và `retrieval_result.retrieval_unit_text` hợp lệ
- **THEN** Step 10 MUST build TEACH prompt
- **AND** prompt MUST ràng buộc "không bịa thêm nguồn"

#### Scenario: TEACH retrieval unusable fallback
- **WHEN** `response_method = TEACH` nhưng `retrieval_result` null hoặc `retrieval_unit_text` rỗng/lỗi
- **THEN** Step 10 MUST fallback sang LISTEN builder
- **AND** MUST vẫn tạo output contract hợp lệ cho Step 11

### Requirement: Compact/token-control phải đúng thứ tự ưu tiên
Khi prompt vượt ngưỡng token nội bộ, Step 10 MUST compact `recent_turns` trước, rồi `context_summary`, và MUST NOT cắt `current_message`. Với TEACH path, Step 10 MUST ưu tiên giữ `retrieval_unit_text` hơn context phụ.

#### Scenario: Compact được áp dụng
- **WHEN** token estimate vượt ngưỡng compact
- **THEN** Step 10 MUST compact theo đúng thứ tự ưu tiên
- **AND** `prompt_debug_meta.compact_applied` MUST là `true`

#### Scenario: Không cần compact
- **WHEN** token estimate trong ngưỡng
- **THEN** Step 10 MUST giữ payload đầy đủ theo builder
- **AND** `prompt_debug_meta.compact_applied` MUST là `false`

### Requirement: Builder input shape fallback phải chịu lỗi nhẹ
Nếu field không lõi bị lỗi shape, Step 10 MUST drop field đó và tiếp tục build với input tối thiểu; Step 10 MUST NOT fail turn vì non-core malformed field.

#### Scenario: Non-core field malformed
- **WHEN** một field phụ (không lõi) sai shape
- **THEN** Step 10 MUST bỏ field sai shape
- **AND** MUST vẫn tạo prompt_messages hợp lệ

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
