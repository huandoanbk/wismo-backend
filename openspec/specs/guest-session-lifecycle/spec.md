# guest-session-lifecycle Specification

## Purpose
TBD - created by archiving change be11-guest-session-idle-ttl-auto-attach. Update Purpose after archive.

## Requirements
### Requirement: Guest idle TTL được set khi tạo

Hệ thống SHALL set `expires_at = now + WISMO_GUEST_IDLE_TTL_HOURS` cho mọi `GuestIdentity` mới tạo. `expires_at` SHALL không được để `None` sau change này.

#### Scenario: Guest mới có expires_at

- **WHEN** client gọi `POST /api/accounts/guest/init/` để tạo guest identity
- **THEN** `GuestIdentity` được tạo với `expires_at = created_at + WISMO_GUEST_IDLE_TTL_HOURS`, không phải `None`

#### Scenario: WISMO_GUEST_IDLE_TTL_HOURS từ settings

- **WHEN** hệ thống tạo guest identity
- **THEN** TTL SHALL đọc từ `settings.WISMO_GUEST_IDLE_TTL_HOURS` và `WISMO_GUEST_IDLE_TTL_HOURS` SHALL được configure trong `.env` với default = 6

### Requirement: Guest TTL là sliding idle TTL

Hệ thống SHALL extend `expires_at` của guest mỗi khi guest gửi message hợp lệ qua chat endpoint. Chỉ action gửi message mới tính là guest activity.

#### Scenario: mark_seen() refresh cả expires_at

- **WHEN** `GuestIdentity.mark_seen()` được gọi
- **THEN** hệ thống update cả `last_seen_at = now` và `expires_at = now + WISMO_GUEST_IDLE_TTL_HOURS` trong cùng một `save()`

#### Scenario: Chỉ gửi message mới refresh TTL

- **WHEN** guest thực hiện bất kỳ action nào khác ngoài `POST /api/chat/message/` — bao gồm page load, `GET /api/accounts/session/`, accept consent, tạo chat shell, list chat, get chat detail, verify OTP, login, logout, Google login
- **THEN** `mark_seen()` SHALL không được gọi và `expires_at` SHALL không thay đổi

#### Scenario: TTL refresh khi guest resolve từ chat message endpoint

- **WHEN** `POST /api/chat/message/` nhận request và gate pipeline resolve được guest identity hợp lệ từ cookie/header
- **THEN** `mark_seen()` được gọi cho guest đó, bất kể gate pass hay fail sau đó

#### Scenario: Guest cũ không có expires_at vẫn valid

- **WHEN** `GuestIdentity` hiện có được tạo trước change này có `expires_at = None`
- **THEN** `is_guest_valid()` vẫn coi guest đó là hợp lệ (existing behavior — `expires_at is None` → valid)
