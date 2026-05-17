## Context

Registered user đã có đầy đủ auth flow (register, verify, login, logout, Google OAuth). Tuy nhiên chưa có endpoint nào để user đọc profile đầy đủ hoặc thực hiện account controls (sửa tên, đổi mật khẩu, xóa data). BE-21 bổ sung các endpoint này trong phạm vi `accounts` app.

**Spec References:**
- `openspec/changes/be21-registered-settings-privacy-minimal/specs/registered-account-settings/spec.md`
- `openspec/changes/be21-registered-settings-privacy-minimal/specs/identity-consent-auth/spec.md`

## Goals / Non-Goals

**Goals:**
- `GET /api/accounts/me/` — trả profile đầy đủ.
- `PATCH /api/accounts/me/` — cập nhật `display_name`.
- `POST /api/accounts/change-password/` — đổi mật khẩu (email/password account).
- `POST /api/accounts/delete-all-chat/` — GDPR anonymize toàn bộ chat history.
- Cập nhật `project-spec/frontend-backend-contract.md`.
- Unit test đủ coverage cho service và view.

**Non-Goals:**
- Thay đổi `GET /api/accounts/session/` (contract đã chốt, FE phụ thuộc).
- GDPR data export.
- DELETE account.
- Change email.

## Decisions

### D1. Tách `AccountSettingsService` khỏi `AccountAuthService`

`AccountAuthService` đã đảm nhận register, verify, OTP, login, logout, Google. Tạo `AccountSettingsService` riêng trong `accounts/services.py` để mỗi service có cohesion rõ.

### D2. Authentication: `SessionAuthentication` + `IsAuthenticated` permission

Tất cả endpoints dùng `SessionAuthentication` và `IsAuthenticated` permission class của DRF. Session expired/account inactive → view override thành 401 với `session_expired` code để nhất quán với contract hiện tại.

### D3. Session không bị invalidated sau change-password

Dùng `django.contrib.auth.update_session_auth_hash(request, user)` sau khi cập nhật password để giữ session hiện tại hợp lệ.

**Thay thế cân nhắc:** Invalidate tất cả session — không cần cho MVP vì chưa có multi-device session management.

### D4. Response shape cho `GET /api/accounts/me/` và `PATCH /api/accounts/me/`

Cả hai trả cùng profile shape:
```json
{
  "email": "user@example.com",
  "display_name": "Tên hiển thị",
  "email_verified": true,
  "date_joined": "2026-05-09T10:00:00Z"
}
```

`email` và `email_verified` là read-only. `date_joined` là ISO 8601 UTC string.

### D5. Chỉ `display_name` được PATCH

`PATCH /api/accounts/me/` chỉ nhận `display_name`. Các field khác trong body bị bỏ qua hoàn toàn.

### D6. Delete All Chat: anonymize về Sentinel User, không hard delete

GDPR Article 17 cho phép anonymization thay thế erasure nếu re-identification không còn khả thi.

`Case`, `Chat`, `ChatTurn` có DB constraint `exactly_one_owner` — bắt buộc phải có đúng một owner (`user` hoặc `guest_identity`). Không thể NULL cả hai FK. Giải pháp: reassign ownership về một **sentinel `User`** — system account cố định (`email = anonymous@system.internal`, `is_active = False`, UUID hard-coded là constant `ANONYMOUS_USER_ID` trong `accounts/constants.py`). Sentinel được seed qua data migration một lần.

Chiến lược anonymize trong một `atomic()` transaction:
- `cases`: `user = sentinel`, `guest_identity = NULL`, `context_summary = ""`, `topic = ""`
- `chats`: `user = sentinel`, `guest_identity = NULL`, `is_archived = True`
- `chat_turns`: `user = sentinel`, `guest_identity = NULL`, `user_message_text = ""`, `assistant_response_text = ""`
- `memory_items`: `user = sentinel`, `case = NULL` (không có `exactly_one_owner` constraint nhưng reassign về sentinel để nhất quán)

**Thay thế cân nhắc:** Hard delete toàn bộ — GDPR chắc nhất nhưng mất operational metrics. Với MVP, anonymize về sentinel là đủ.

### D7. `erase_all_chat_data` đặt trong `AccountSettingsService`

Privacy control của account. `AccountSettingsService` import và query chat/memory models trực tiếp — không tạo service boundary mới giữa apps.

### D8. Error codes mới thêm vào `wismo/contracts/codes.py`

`no_usable_password`, `invalid_current_password`, `display_name_too_long` là codes mới, phải thêm vào `codes.py` để nhất quán với project convention.

## Risks / Trade-offs

- [Thiếu rate limit trên `change-password`] → Django session require authenticated user — không thể brute force mà không có session. Rate limit không cần thiết ở MVP.
- [Không invalidate session sau change-password] → Trade-off có chủ ý cho MVP. Tech debt khi có multi-device management.
- [delete-all-chat là operation nặng nếu user có nhiều chats] → Dùng `bulk_update` trong `atomic()`. Async job là option khi có Celery.
- [Sentinel user tập trung tất cả anonymized data dưới một FK] → Không thể re-identify cá nhân vì content đã scrubbed. Sentinel `is_active=False` nên không accessible qua auth. Chấp nhận cho MVP.

## Migration Plan

1. Tạo `accounts/constants.py` với `ANONYMOUS_USER_ID` (fixed UUID).
2. Tạo data migration seed sentinel `User` với UUID đó.
3. Deploy bình thường — không có schema migration.

## Open Questions

Không có.
