## ADDED Requirements

### Requirement: Step 8 chỉ chạy trên continue path sau Step 7
Runtime MUST chạy Step 8 chỉ khi request đi continue-to-full-reasoning path, Step 6 đã có `runtime_bundle`, và Step 7 đã tạo `reasoning_result`.

#### Scenario: Continue path vào Step 8
- **WHEN** `triage_decision = continue_to_full_reasoning`
- **AND** `runtime_bundle` đã assemble ở Step 6
- **AND** `reasoning_result` đã có từ Step 7
- **THEN** runtime MUST thực thi Step 8

### Requirement: Step 8 chỉ dùng runtime state, không reload DB context nền
Step 8 MUST chỉ đọc `runtime_bundle` + `reasoning_result` và MUST NOT reload `current_message`, `recent_turns`, `context_summary`, `user_profile`, `user_preference`, `user_state`, `long_term_memory` từ DB.

#### Scenario: Read-only bundle contract
- **WHEN** Step 8 xử lý validation/safety/method selection
- **THEN** Step 8 MUST dùng dữ liệu từ runtime state hiện tại
- **AND** MUST NOT query lại context nền Step 6

### Requirement: Step 8 phải validate + normalize reasoning_result trước khi chọn method
Step 8 MUST validate required fields, normalize enum/list/object fields, và tạo `normalized_reasoning_result` làm nguồn decision duy nhất cho Step 8 output.

#### Scenario: Light schema issues
- **WHEN** output Step 7 có enum lệch nhẹ/list trùng/optional thiếu
- **THEN** Step 8 MUST auto-normalize trực tiếp
- **AND** MUST tiếp tục flow không cần corrective retry

#### Scenario: Heavy schema issues
- **WHEN** output Step 7 thiếu field lõi hoặc sai shape không convert an toàn
- **THEN** Step 8 MUST classify là heavy inconsistency
- **AND** MUST đi corrective retry path (trừ khi safety override cứng đã áp dụng)

### Requirement: Step 8 phải áp dụng hard safety override với ưu tiên cao nhất
Nếu `risk_flags` chứa hard-safety signals, Step 8 MUST override `response_method` theo mapping safety và chốt `final_safety_state` tương ứng.

#### Scenario: Crisis override
- **WHEN** `risk_flags` chứa `crisis_self_harm` hoặc `crisis_harm_others`
- **THEN** Step 8 MUST set `response_method = CRISIS_SAFE_ONLY`
- **AND** `final_safety_state = crisis_only`

#### Scenario: Minor override
- **WHEN** `risk_flags` chứa `minor_age_block`
- **THEN** Step 8 MUST set `response_method = BLOCKED_MINOR`
- **AND** `final_safety_state = blocked`

#### Scenario: Redirect override
- **WHEN** `risk_flags` chứa `medical_out_of_scope` hoặc `legal_out_of_scope`
- **THEN** Step 8 MUST set `response_method = REDIRECT`
- **AND** `final_safety_state = redirect`

#### Scenario: Refusal override
- **WHEN** `risk_flags` chứa `policy_bypass`
- **THEN** Step 8 MUST set `response_method = REFUSAL`
- **AND** `final_safety_state = refusal`

#### Scenario: Spam override
- **WHEN** `risk_flags` chứa `spam_or_nonsense`
- **THEN** Step 8 MUST set `response_method = SPAM_REPLY`
- **AND** `final_safety_state = spam`

### Requirement: Step 8 phải chốt retrieval_required theo response_method cuối cùng
Step 8 MUST set `retrieval_required` chỉ khi `response_method = TEACH`; các method khác MUST là `false`.

#### Scenario: TEACH requires retrieval
- **WHEN** final `response_method = TEACH`
- **THEN** `retrieval_required = true`

#### Scenario: Non-TEACH disables retrieval
- **WHEN** final `response_method != TEACH`
- **THEN** `retrieval_required = false`

### Requirement: Step 8 phải hỗ trợ corrective retry cho heavy non-safety inconsistencies
Với heavy inconsistency không thuộc hard-safety, Step 8 MUST callback Step 7 với `reasoning_control` rồi re-validate Step 8.

#### Scenario: Corrective retry call
- **WHEN** Step 8 phát hiện heavy non-safety inconsistency
- **THEN** Step 8 MUST tăng `reasoning_corrective_retry_count`
- **AND** MUST gọi lại Step 7 với `reasoning_control` gồm `is_corrective_retry`, `retry_count`, `validation_error_feedback`
- **AND** MUST chạy lại Step 8 sau khi có output Step 7 mới

### Requirement: Exhausted corrective retry phải fallback an toàn cho non-hard-safety path
Nếu heavy non-safety inconsistencies vẫn còn sau 2 corrective retries, Step 8 MUST fallback method an toàn và không mở retrieval.

#### Scenario: Retry exhausted fallback
- **WHEN** corrective retry đã vượt giới hạn 2 lần và không có hard safety flags
- **THEN** Step 8 MUST set `response_method = ASK`
- **AND** `retrieval_required = false`
- **AND** `final_safety_state = normal`

### Requirement: Retry counters phải tách riêng giữa gateway retry và corrective retry
Runtime MUST tách riêng counter retry của Step 7 gateway/provider và counter corrective loop Step 8.

#### Scenario: Counter isolation
- **WHEN** Step 7 gặp lỗi transient provider và thực hiện gateway retry
- **THEN** runtime MUST chỉ cập nhật `reasoning_gateway_retry_count`
- **AND** MUST NOT tăng `reasoning_corrective_retry_count`

#### Scenario: Corrective loop counter
- **WHEN** Step 8 gọi lại Step 7 qua `reasoning_control`
- **THEN** runtime MUST chỉ cập nhật `reasoning_corrective_retry_count`
- **AND** MUST NOT dùng counter gateway retry để quyết định exhausted corrective fallback

### Requirement: Step 8 phải cover consistency rules cốt lõi cho slots và intent-action
Step 8 MUST thực thi đầy đủ các consistency rules cốt lõi của Main Flow cho `required_next_slots`, `case_slots`, và `intent` vs `action_recommended`.

#### Scenario: ASK requires non-empty required_next_slots
- **WHEN** final candidate `action_recommended = ASK` nhưng `required_next_slots = []`
- **THEN** Step 8 MUST classify heavy inconsistency và đi corrective retry

#### Scenario: Non-ASK clears required_next_slots
- **WHEN** final candidate `action_recommended != ASK` và `required_next_slots` còn giá trị
- **THEN** Step 8 MUST clear `required_next_slots`

#### Scenario: Fulfilled slots removed from required list
- **WHEN** một slot đã có giá trị rõ trong `case_slots` nhưng vẫn tồn tại trong `required_next_slots`
- **THEN** Step 8 MUST remove slot đó khỏi `required_next_slots`

#### Scenario: Intent unclear forces ASK
- **WHEN** `intent = unclear` và action hiện tại khác `ASK`
- **THEN** Step 8 MUST override về `ASK`
