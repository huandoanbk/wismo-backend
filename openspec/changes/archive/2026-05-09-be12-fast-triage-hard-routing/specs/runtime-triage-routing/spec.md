## ADDED Requirements

### Requirement: Step 4 triage quyết định theo 6 outputs canonical
Runtime SHALL chạy Fast triage ngay sau Step 3 và SHALL trả đúng một `triage_decision` trong tập canonical của Main Flow.

#### Scenario: Canonical triage output set
- **WHEN** runtime xử lý một gate-pass request tại Step 4
- **THEN** `triage_decision` chỉ có thể là một trong: `crisis_hotline_immediate`, `blocked_minor`, `hard_redirect`, `policy_bypass_refusal`, `spam_or_non_conversational`, `continue_to_full_reasoning`

### Requirement: Rule-based detector chạy trước LLM classifier fallback
Step 4 SHALL chạy rule-based detector trước; chỉ khi rule không đủ chắc mới gọi `triage_classifier` qua LLM Gateway.

#### Scenario: Rule đủ chắc
- **WHEN** rule-based detector trả confidence đạt ngưỡng cho một nhánh control
- **THEN** runtime dùng kết quả rule trực tiếp và không gọi LLM triage classifier

#### Scenario: Rule chưa đủ chắc
- **WHEN** rule-based detector không đạt ngưỡng quyết định
- **THEN** runtime gọi `triage_classifier` qua LLM Gateway với input chỉ gồm current message + 1-3 recent user turns

#### Scenario: LLM classifier lỗi
- **WHEN** LLM triage classifier fail hoặc unavailable
- **THEN** runtime fallback an toàn về `continue_to_full_reasoning`

### Requirement: Triage classifier operation phải được cấu hình qua LLM operation registry
Runtime SHALL dùng operation key `triage_classifier` trong LLM operation registry để route gateway/model. Hệ thống MUST NOT hard-code supplier/model trong Step 4.

#### Scenario: Rule không chắc và operation đã cấu hình
- **WHEN** rule-based detector không đủ chắc và operation `triage_classifier` đang active, map tới gateway hợp lệ
- **THEN** runtime gọi LLM Gateway qua operation đó để lấy quyết định triage

#### Scenario: Operation thiếu hoặc invalid
- **WHEN** rule-based detector không đủ chắc nhưng operation `triage_classifier` thiếu, inactive, hoặc map gateway invalid
- **THEN** runtime không gọi provider trực tiếp và fallback `continue_to_full_reasoning`

### Requirement: Crisis branch persist và short-circuit
Khi `triage_decision = crisis_hotline_immediate`, runtime SHALL trả `CRISIS_SAFE_ONLY`, persist turn, và SHALL không đi Step 5 trở đi.

#### Scenario: Crisis immediate flow
- **WHEN** Step 4 quyết định `crisis_hotline_immediate`
- **THEN** runtime persist turn với `response_method = CRISIS_SAFE_ONLY`
- **AND** runtime kết thúc flow tại control branch không chạy Step 5+

#### Scenario: Crisis persisted turn được đánh dấu safety-control
- **WHEN** crisis branch persist turn thành công
- **THEN** turn MUST được đánh dấu `safety_control` (ví dụ `turn_type = safety_control` hoặc field tương đương)
- **AND** turn này MUST NOT được dùng làm nguồn update cho `context_summary`, `long_term_memory`, `user_profile`, `user_preference`

### Requirement: Non-crisis control branches là non-persist
Khi `triage_decision` là `blocked_minor`, `hard_redirect`, `policy_bypass_refusal`, hoặc `spam_or_non_conversational`, runtime SHALL trả control response và SHALL không persist turn.

#### Scenario: Blocked minor non-persist
- **WHEN** Step 4 quyết định `blocked_minor`
- **THEN** runtime trả control response `BLOCKED_MINOR` và không persist turn

#### Scenario: Hard redirect non-persist
- **WHEN** Step 4 quyết định `hard_redirect`
- **THEN** runtime trả control response `REDIRECT` và không persist turn

#### Scenario: Policy bypass non-persist
- **WHEN** Step 4 quyết định `policy_bypass_refusal`
- **THEN** runtime trả control response `REFUSAL` và không persist turn

#### Scenario: Spam branch non-persist
- **WHEN** Step 4 quyết định `spam_or_non_conversational`
- **THEN** runtime trả control response `SPAM_REPLY` (hoặc nhắc nhập lại canonical) và không persist turn

### Requirement: Continue branch đi Step 5
Khi `triage_decision = continue_to_full_reasoning`, runtime SHALL đi tiếp Step 5 case resolution.

#### Scenario: Continue flow
- **WHEN** Step 4 quyết định `continue_to_full_reasoning`
- **THEN** runtime vào Step 5 và giữ flow normal path

### Requirement: Triage provenance phải audit được
Runtime SHALL lưu metadata tối thiểu cho nguồn quyết định triage để phục vụ debug và regression audit.

#### Scenario: Provenance metadata
- **WHEN** Step 4 hoàn tất quyết định
- **THEN** runtime metadata chứa ít nhất `triage_source` (`rule|llm|fallback`) và `triage_decision`
