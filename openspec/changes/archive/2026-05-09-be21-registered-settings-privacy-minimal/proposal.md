## Why

Registered user đã có identity bền vững nhưng chưa có endpoint để đọc profile, thực hiện account controls tối thiểu (sửa display name, đổi mật khẩu), hoặc xóa toàn bộ dữ liệu cá nhân trong lịch sử trò chuyện theo chuẩn GDPR. BE-21 cung cấp các controls này theo MVP Spec §A.4.2 trước khi integration regression (BE-22).

## What Changes

- **Thêm** `GET /api/accounts/me/` — trả profile đầy đủ của registered user (email, display_name, email_verified, date_joined).
- **Thêm** `PATCH /api/accounts/me/` — cho phép registered user cập nhật `display_name`.
- **Thêm** `POST /api/accounts/change-password/` — cho phép registered user đổi mật khẩu. Chỉ áp dụng cho email/password account; Google-only account trả error rõ.
- **Thêm** `POST /api/accounts/delete-all-chat/` — xóa toàn bộ chat history và profile data của registered user theo GDPR right to erasure. Anonymize toàn bộ: chats, cases, turns, memory items. Không phục hồi được. Account vẫn còn active.
- **Cập nhật** `project-spec/frontend-backend-contract.md` — bổ sung các endpoints mới.

## Capabilities

### New Capabilities

- `registered-account-settings`: Profile read, display_name update, change-password, và delete-all-chat (GDPR anonymize) cho registered user.

### Modified Capabilities

- `identity-consent-auth`: Bổ sung authentication rules cho các endpoint mới (registered-only, session required).

## Impact

- **Code mới:** `accounts/views.py` — thêm `AccountMeView`, `ChangePasswordView`, `DeleteAllChatView`; `accounts/services.py` — thêm `AccountSettingsService`; `chat/services.py` hoặc `accounts/services.py` — thêm `erase_all_chat_data(user)` logic.
- **Không có migration** — không thêm field mới vào model (tất cả FKs đã nullable, `is_archived` đã tồn tại).
- **Contract:** Cập nhật `project-spec/frontend-backend-contract.md`.
- **Không có tech debt** về memory — `memory_items` được DELETE trong cùng operation.
