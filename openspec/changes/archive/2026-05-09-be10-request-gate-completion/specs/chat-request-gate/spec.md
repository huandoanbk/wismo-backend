## MODIFIED Requirements

### Requirement: Chat request gate identity and session checks
Hệ thống SHALL resolve identity trước khi kiểm tra session và SHALL chặn runtime nếu identity hoặc session hiện tại không hợp lệ.

#### Scenario: Identity cannot be resolved
- **WHEN** request không có registered session hợp lệ và cũng không có guest identity hợp lệ
- **THEN** backend dừng runtime và trả `identity_not_resolved` (401)

#### Scenario: Django session TTL expired — treated as identity_not_resolved
- **WHEN** registered user Django session TTL hết hạn khiến `request.user` trở thành AnonymousUser, và request không có guest cookie
- **THEN** backend dừng runtime và trả `identity_not_resolved` (401) — FE phải check session status qua `GET /api/accounts/session/` trước khi enter chat flow

#### Scenario: Guest session expired
- **WHEN** request resolve được guest record nhưng guest `is_active=False` hoặc `expires_at` đã qua
- **THEN** backend dừng runtime và trả `guest_session_expired` (401)

#### Scenario: Registered session expired — inactive or unverified
- **WHEN** `request.user.is_authenticated=True` nhưng `is_active=False` hoặc `email_verified=False`
- **THEN** backend dừng runtime và trả `session_expired` (401)

#### Scenario: Registered identity becomes canonical
- **WHEN** request resolve được registered user hợp lệ và request vẫn mang `wismo_guest` cookie cũ
- **THEN** backend coi registered user là identity canonical cho runtime path hiện tại và response path SHALL clear guest cookie cũ

### Requirement: Chat ownership và turn barrier là gate bước cuối
Hệ thống SHALL chỉ cho request đi tiếp khi `chat_id` thuộc identity hiện tại và turn trước của chat không còn ở trạng thái finalization pending. `turn_in_progress` là chat-level barrier được kiểm tra bên trong ownership check — không còn là identity-level idempotency.

#### Scenario: New chat bypasses ownership lookup
- **WHEN** request không có `chat_id`
- **THEN** backend bypass ownership lookup và cho gate đi tiếp nếu các bước trước đều pass

#### Scenario: Chat not found or unavailable
- **WHEN** request có `chat_id` nhưng chat không tồn tại, đã archived, hoặc đã disabled
- **THEN** backend dừng runtime và trả `chat_not_found` (404)

#### Scenario: Chat belongs to another identity
- **WHEN** request có `chat_id` nhưng chat không thuộc owner identity hiện tại
- **THEN** backend dừng runtime và trả `chat_access_denied` (403)

#### Scenario: Previous turn finalization still pending
- **WHEN** request có `chat_id` hợp lệ với ownership đúng nhưng turn gần nhất của chat vẫn đang ở trạng thái Step 12 pending hoặc processing
- **THEN** backend dừng runtime và trả `turn_in_progress` (409) — đây là chat-level barrier, không phải idempotency

## ADDED Requirements

### Requirement: Gate error HTTP status code canonical mapping
Hệ thống SHALL trả đúng HTTP status code cho từng gate error code. Toàn bộ gate errors SHALL được trả dưới dạng JSON response `{"error": "<code>"}` trước khi stream mở.

| HTTP Status | Error Code | Ý nghĩa |
|---|---|---|
| 400 | `invalid_request` | Payload không phải object hoặc `message` sai type |
| 400 | `missing_required_field` | Thiếu `message` |
| 400 | `invalid_chat_id` | `chat_id` không parse được thành UUID hợp lệ |
| 400 | `empty_message` | `message` rỗng hoặc chỉ whitespace |
| 401 | `identity_not_resolved` | Không xác định được identity (kể cả Django TTL expiry) |
| 401 | `guest_identity_not_resolved` | Guest token có nhưng không tìm được record |
| 401 | `guest_session_expired` | Guest identity inactive hoặc expires_at đã qua |
| 401 | `session_expired` | Registered user is_active=False hoặc email_verified=False |
| 403 | `consent_required` | Identity chưa có active consent |
| 403 | `chat_access_denied` | chat_id không thuộc identity hiện tại |
| 404 | `chat_not_found` | chat_id không tồn tại, archived, hoặc disabled |
| 409 | `turn_in_progress` | Turn trước của chat vẫn đang finalize |
| 413 | `message_too_long` | `message` vượt max character limit |
| 413 | `payload_too_large` | Request body vượt hard byte size limit |
| 429 | `quota_exceeded` | Registered user quota đã exhausted |
| 429 | `registration_required_by_quota` | Guest quota đã exhausted |

#### Scenario: Gate error luôn là JSON với đúng status code
- **WHEN** gate fail ở bất kỳ check nào
- **THEN** backend trả HTTP response với status code theo bảng trên và body `{"error": "<code>"}`, không mở SSE stream

#### Scenario: Gate pass không trả JSON
- **WHEN** tất cả gate checks pass
- **THEN** backend trả HTTP 200 với `Content-Type: text/event-stream` và bắt đầu SSE stream, không có JSON body

## REMOVED Requirements

### Requirement: Client-turn idempotency gate
**Reason**: `client_turn_id` đã bị xóa khỏi API contract theo owner decision. Idempotency identity-level (replay previous result, turn_in_progress theo client_turn_id) không còn áp dụng trong MVP. `turn_in_progress` được giữ lại dưới dạng chat-level barrier trong ownership check.
**Migration**: `turn_in_progress` vẫn được trả nhưng dựa trên chat-level Step 12 pending state, không phải `client_turn_id`. FE không cần gửi `client_turn_id`.
