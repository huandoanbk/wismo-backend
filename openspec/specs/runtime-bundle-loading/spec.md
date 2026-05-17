## ADDED Requirements

### Requirement: Step 6 chỉ chạy trên continue-to-full-reasoning path
Runtime MUST chạy Step 6 chỉ khi Step 4 đã quyết định `continue_to_full_reasoning` và Step 5 đã trả trạng thái case resolution cho turn hiện tại.

#### Scenario: Continue path vào Step 6
- **WHEN** Step 4 trả `triage_decision = continue_to_full_reasoning`
- **AND** Step 5 đã hoàn tất xử lý case cho turn hiện tại
- **THEN** runtime MUST chạy Step 6 để assemble `runtime_bundle`

### Requirement: Step 6 phải load recent turns theo chat_id với thứ tự canonical
Step 6 MUST load tối đa 5 recent turns của chat hiện tại và MUST chuẩn hóa thứ tự từ cũ đến mới trong `runtime_bundle.recent_turns`.

#### Scenario: Recent turns loading
- **WHEN** Step 6 chạy cho một `chat_id`
- **THEN** runtime MUST lấy tối đa 5 turn gần nhất theo `chat_id`
- **AND** runtime MUST chuẩn hóa thứ tự output từ cũ đến mới

### Requirement: Step 6 phải load context_summary theo case_id khi có case
Nếu `case_id` đã resolve, Step 6 MUST load `context_summary` active/latest của case đó.

#### Scenario: case_id đã resolve
- **WHEN** Step 5 trả `case_id` hợp lệ
- **THEN** Step 6 MUST load `context_summary` từ case tương ứng
- **AND** nếu chưa có summary thì MUST dùng empty summary canonical

### Requirement: Step 6 phải chấp nhận case_id null
Nếu Step 5 chưa resolve được case (`case_id = null`), Step 6 MUST vẫn assemble bundle và MUST set các field case-level về giá trị rỗng canonical.

#### Scenario: case_id null path
- **WHEN** Step 5 trả `case_id = null`
- **THEN** Step 6 MUST vẫn assemble `runtime_bundle`
- **AND** `context_summary` MUST là empty summary canonical
- **AND** `long_term_memory` MUST là list rỗng

### Requirement: Step 6 phải load identity-level runtime context với fallback rỗng
Step 6 MUST load `user_profile`, `user_preference`, `user_state` theo identity hiện tại từ persistence store canonical; nếu chưa có dữ liệu thì MUST trả object rỗng chuẩn hóa.

#### Scenario: Identity context thiếu dữ liệu
- **WHEN** identity chưa có dữ liệu profile/preference/state
- **THEN** Step 6 MUST set `user_profile = {}`
- **AND** Step 6 MUST set `user_preference = {}`
- **AND** Step 6 MUST set `user_state = {}`

#### Scenario: Identity context có dữ liệu persisted
- **WHEN** identity đã có record profile/preference/state hợp lệ
- **THEN** Step 6 MUST đưa dữ liệu persisted vào `runtime_bundle`
- **AND** MUST không fallback về stub rỗng

### Requirement: Step 6 retrieve long_term_memory theo case_id và fail-safe
Khi `case_id` có giá trị, Step 6 MUST retrieve `long_term_memory` từ `memory.MemoryItem` theo case đó và chỉ lấy records có `is_active = true`; nếu retrieve fail thì MUST fallback list rỗng.

#### Scenario: Retrieve memory thành công
- **WHEN** `case_id` đã resolve và memory retrieval thành công
- **THEN** Step 6 MUST đưa các `memory.MemoryItem` có `is_active = true` vào `runtime_bundle.long_term_memory`

#### Scenario: Retrieve memory lỗi
- **WHEN** memory retrieval phát sinh lỗi
- **THEN** Step 6 MUST không làm runtime fail ở Step 6
- **AND** Step 6 MUST set `runtime_bundle.long_term_memory = []`

### Requirement: Runtime bundle schema phải canonical cho Step 7
Step 6 MUST assemble `runtime_bundle` với đúng bộ field canonical mà Step 7/8/9/10/11/12 dùng chung.

#### Scenario: Bundle field completeness
- **WHEN** Step 6 hoàn tất
- **THEN** `runtime_bundle` MUST có tối thiểu các field: `current_message`, `recent_turns`, `context_summary`, `user_profile`, `user_preference`, `user_state`, `long_term_memory`

### Requirement: Runtime bundle ownership rule
`runtime_bundle` MUST được assemble đúng một lần ở Step 6 và MUST là source of truth cho downstream steps trong cùng turn.

#### Scenario: Downstream read-only core fields
- **WHEN** Step 7-12 chạy trong cùng turn
- **THEN** các step downstream MUST chỉ đọc các field core của `runtime_bundle`
- **AND** MUST NOT tự reload lại `current_message`, `recent_turns`, `context_summary`, `user_profile`, `user_preference`, `user_state`, `long_term_memory` từ DB
