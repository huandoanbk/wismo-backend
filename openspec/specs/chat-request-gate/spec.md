# chat-request-gate Specification

## Purpose
TBD - created by archiving change request-gate-be2-completion. Update Purpose after archive.
## Requirements
### Requirement: Chat request gate ordering
Hệ thống SHALL chạy request gate cho mọi `POST /api/chat/message/` theo đúng thứ tự canonical. Gate SHALL được gọi từ `ChatSendView` trước khi quyết định mở SSE stream. Nếu gate pass thì view mới tạo `StreamingHttpResponse`; nếu gate fail thì view trả JSON error trực tiếp mà không mở stream.

#### Scenario: All gate checks pass in canonical order
- **WHEN** client gửi chat request hợp lệ với identity, consent, quota và ownership đều hợp lệ
- **THEN** backend chạy lần lượt `validate payload -> resolve identity -> session validity check -> consent check -> quota check -> input basic guard -> chat ownership check` rồi view mở SSE stream và đi tiếp Step 3 của main flow

#### Scenario: Gate fail trước khi stream mở
- **WHEN** gate fail ở bất kỳ check nào
- **THEN** view trả JSON error với status code tương ứng và KHÔNG mở SSE stream

### Requirement: Chat request payload validation
Hệ thống SHALL validate payload chat request ở đầu gate và SHALL trả mã lỗi canonical khi payload không hợp lệ.

#### Scenario: Missing required field
- **WHEN** request thiếu `message`
- **THEN** backend dừng runtime và trả `missing_required_field`

#### Scenario: Invalid chat identifier
- **WHEN** request có `chat_id` nhưng không parse được thành UUID hợp lệ
- **THEN** backend dừng runtime và trả `invalid_chat_id`

#### Scenario: Invalid request shape
- **WHEN** request body không phải object hợp lệ hoặc `message` không phải text field
- **THEN** backend dừng runtime và trả `invalid_request`

#### Scenario: Empty or oversize message
- **WHEN** request có `message` rỗng, chỉ whitespace, vượt `MAX_MESSAGE_LENGTH`, hoặc payload vượt hard byte size
- **THEN** backend dừng runtime và trả lần lượt `empty_message`, `message_too_long`, hoặc `payload_too_large`

### Requirement: Chat request gate identity and session checks
Hệ thống SHALL resolve identity trước khi kiểm tra session và SHALL chặn runtime nếu identity hoặc session hiện tại không hợp lệ. Khi gate resolve được guest identity từ `POST /api/chat/message/`, hệ thống SHALL gọi `mark_seen()` để refresh sliding TTL, bất kể gate pass hay fail sau đó.

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

#### Scenario: Guest TTL refresh khi gửi message
- **WHEN** gate pipeline resolve được guest identity hợp lệ từ `POST /api/chat/message/` request
- **THEN** `mark_seen()` được gọi ngay tại bước `_resolve_identity()`, trước khi các gate checks tiếp theo chạy, bất kể gate có pass hay fail sau đó

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
