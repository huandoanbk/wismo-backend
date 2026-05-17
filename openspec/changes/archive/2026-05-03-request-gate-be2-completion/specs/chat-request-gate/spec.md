## ADDED Requirements

### Requirement: Chat request gate ordering
Hệ thống SHALL chạy request gate cho mọi `POST /api/chat/message/` theo đúng thứ tự canonical trước khi vào runtime core.

#### Scenario: All gate checks pass in canonical order
- **WHEN** client gửi chat request hợp lệ với identity, consent, quota và ownership đều hợp lệ
- **THEN** backend chạy lần lượt `validate payload -> resolve identity -> idempotency check -> session validity check -> consent check -> quota check -> input basic guard -> chat ownership check` trước khi đi tiếp Step 3 của main flow

### Requirement: Chat request payload validation
Hệ thống SHALL validate payload chat request ở đầu gate và SHALL trả mã lỗi canonical khi payload không hợp lệ.

#### Scenario: Missing required field
- **WHEN** request thiếu `message` hoặc thiếu `client_turn_id`
- **THEN** backend dừng runtime và trả `missing_required_field`

#### Scenario: Invalid chat identifier
- **WHEN** request có `chat_id` nhưng không parse được thành UUID hợp lệ
- **THEN** backend dừng runtime và trả `invalid_chat_id`

#### Scenario: Invalid client turn identifier
- **WHEN** request có `client_turn_id` không phải string hợp lệ hoặc chỉ gồm whitespace
- **THEN** backend dừng runtime và trả `invalid_client_turn_id`

#### Scenario: Invalid request shape
- **WHEN** request body không phải object hợp lệ hoặc `message` không phải text field
- **THEN** backend dừng runtime và trả `invalid_request`

#### Scenario: Empty or oversize message
- **WHEN** request có `message` rỗng, chỉ whitespace, vượt `MAX_MESSAGE_LENGTH`, hoặc payload vượt hard byte size
- **THEN** backend dừng runtime và trả lần lượt `empty_message`, `message_too_long`, hoặc `payload_too_large`

### Requirement: Chat request gate identity and session checks
Hệ thống SHALL resolve identity trước idempotency và SHALL chặn runtime nếu identity hoặc session hiện tại không hợp lệ.

#### Scenario: Identity cannot be resolved
- **WHEN** request không có registered session hợp lệ và cũng không có guest identity hợp lệ
- **THEN** backend dừng runtime và trả `identity_not_resolved`

#### Scenario: Guest session expired
- **WHEN** request resolve được guest record nhưng guest inactive hoặc expired
- **THEN** backend dừng runtime và trả `guest_session_expired`

#### Scenario: Registered session expired
- **WHEN** request mang registered session nhưng user không còn active hoặc chưa còn là registered chat identity hợp lệ
- **THEN** backend dừng runtime và trả `session_expired`

#### Scenario: Registered identity becomes canonical
- **WHEN** request resolve được registered user hợp lệ và request vẫn mang `wismo_guest` cookie cũ
- **THEN** backend coi registered user là identity canonical cho runtime path hiện tại và response path SHALL clear guest cookie cũ

### Requirement: Chat request idempotency
Hệ thống SHALL enforce idempotency tối thiểu theo `client_turn_id` trên owner identity hiện tại.

#### Scenario: Duplicate completed turn
- **WHEN** owner hiện tại đã có `ChatTurn` cùng `client_turn_id` với trạng thái completed
- **THEN** backend dừng runtime và trả `replay_previous_result`

#### Scenario: Duplicate in-progress turn
- **WHEN** owner hiện tại đã có `ChatTurn` cùng `client_turn_id` nhưng turn đó chưa hoàn tất bình thường
- **THEN** backend dừng runtime và trả `turn_in_progress`

### Requirement: Chat request consent and quota gate
Hệ thống SHALL chặn runtime core nếu consent chưa accepted hoặc quota hiện tại đã exhausted, và quota fail SHALL áp dụng side effect tối thiểu cho pending input.

#### Scenario: Consent required
- **WHEN** identity hiện tại chưa có active consent current version
- **THEN** backend dừng runtime và trả `consent_required`

#### Scenario: Guest quota exhausted
- **WHEN** guest quota window hiện tại đã exhausted
- **THEN** backend append message hiện tại vào `pending_input_text` theo policy hiện tại, cập nhật pending input state, dừng runtime, và trả `registration_required_by_quota`

#### Scenario: Registered user quota exhausted
- **WHEN** registered user quota window hiện tại đã exhausted
- **THEN** backend append message hiện tại vào `pending_input_text` theo policy hiện tại, cập nhật pending input state, dừng runtime, và trả `quota_exceeded`

### Requirement: Chat ownership and previous-turn barrier
Hệ thống SHALL chỉ cho request đi tiếp khi `chat_id` thuộc identity hiện tại và turn trước của chat không còn ở trạng thái finalization pending.

#### Scenario: New chat bypasses ownership lookup
- **WHEN** request không có `chat_id`
- **THEN** backend bypass ownership lookup và cho gate đi tiếp nếu các bước trước đều pass

#### Scenario: Chat not found or unavailable
- **WHEN** request có `chat_id` nhưng chat không tồn tại, đã archived, hoặc đã disabled
- **THEN** backend dừng runtime và trả `chat_not_found`

#### Scenario: Chat belongs to another identity
- **WHEN** request có `chat_id` nhưng chat không thuộc owner identity hiện tại
- **THEN** backend dừng runtime và trả `chat_access_denied`

#### Scenario: Previous turn finalization still pending
- **WHEN** request có `chat_id` hợp lệ nhưng turn gần nhất của chat vẫn đang ở trạng thái Step 12 pending hoặc processing
- **THEN** backend dừng runtime và trả `turn_in_progress`
