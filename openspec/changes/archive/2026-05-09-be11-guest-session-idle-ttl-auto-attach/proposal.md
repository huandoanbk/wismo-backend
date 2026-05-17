## Why

Guest identity hiện không có cơ chế expiry thực sự — `expires_at` không được set khi tạo, `mark_seen()` không refresh TTL, và guest attach vẫn là flow thủ công riêng biệt sau OTP verify. Change này chốt idle TTL 6h cho guest, làm cho auto-attach trở thành một bước silent trong OTP verify flow, và loại bỏ endpoint attach thủ công không còn cần thiết.

## What Changes

- `GuestIdentity` được set `expires_at = now + WISMO_GUEST_IDLE_TTL_HOURS` khi tạo (không còn nullable mặc định là không hết hạn)
- `mark_seen()` refresh cả `last_seen_at` và `expires_at` (sliding TTL)
- `mark_seen()` chỉ được gọi từ `POST /api/chat/message/` (khi guest resolve được từ request), bất kể gate pass hay fail — bỏ khỏi `session_status()` và `resolve_bootstrap_identity()`
- `VerifyEmailView` tự động attach guest chat hiện tại (silent) nếu guest cookie có mặt và guest có eligible chat, đồng thời clear `wismo_guest` cookie trong response
- **BREAKING**: `DELETE /api/accounts/guest/attach/` — endpoint bị xóa; `GuestAttachView` và URL bị remove; `GuestAttachService` được giữ lại như internal service

## Capabilities

### New Capabilities

- `guest-session-lifecycle`: Guest identity idle TTL mechanics — set `expires_at` khi tạo, sliding refresh chỉ khi gửi message, `mark_seen()` cập nhật `expires_at`

### Modified Capabilities

- `identity-consent-auth`: `VerifyEmailView` bổ sung silent auto-attach guest chat; `GuestAttachView` và URL route bị xóa; `GuestInitView` bắt buộc set `expires_at`
- `chat-request-gate`: `_resolve_identity()` trong gate là nơi duy nhất gọi `mark_seen()` cho guest trong chat message flow

## Impact

- **accounts/models.py**: `mark_seen()` update cả `expires_at`
- **accounts/services.py**: `create_guest()` set `expires_at`; bỏ `mark_seen()` khỏi `session_status()` và `resolve_for_gate()`; xóa `GuestAttachView`-facing exposure (giữ `GuestAttachService` internal)
- **accounts/views.py**: `VerifyEmailView` thêm silent attach logic; xóa `GuestAttachView`
- **accounts/urls.py**: xóa `guest/attach/` route
- **chat/services.py**: bỏ `mark_seen()` khỏi `resolve_bootstrap_identity()`
- **runtime/request_gate.py**: `_resolve_identity()` gọi `mark_seen()` khi guest resolve được
- **settings / .env**: thêm `WISMO_GUEST_IDLE_TTL_HOURS=6`
- **frontend-backend-contract.md**: ghi rõ `/api/accounts/guest/attach/` bị xóa; cập nhật verify-email response (không thay đổi shape nhưng ghi rõ silent attach behavior)
- **Migration**: không cần migration mới (field `expires_at` đã nullable, không đổi schema; chỉ thay đổi application-level behavior khi set giá trị)
- **Tests**: cập nhật unit tests liên quan đến guest lifecycle, verify flow, gate identity resolution
