## MODIFIED Requirements

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
