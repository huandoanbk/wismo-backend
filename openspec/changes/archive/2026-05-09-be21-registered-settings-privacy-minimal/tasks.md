## 1. Foundation

- [x] 1.1 Tạo `accounts/constants.py` — định nghĩa `ANONYMOUS_USER_ID: uuid.UUID` với một UUID cố định (hard-coded), dùng làm sentinel identity cho anonymized data
- [x] 1.2 Thêm error codes mới vào `wismo/contracts/codes.py`: `NO_USABLE_PASSWORD = "no_usable_password"`, `INVALID_CURRENT_PASSWORD = "invalid_current_password"`, `DISPLAY_NAME_TOO_LONG = "display_name_too_long"`
- [x] 1.3 Tạo data migration trong `accounts/migrations/` — seed sentinel `User` với `id = ANONYMOUS_USER_ID`, `email = "anonymous@system.internal"`, `is_active = False`, `email_verified = False`, `display_name = "Anonymous"`

## 2. AccountSettingsService

- [x] 2.1 Tạo class `AccountSettingsService` trong `accounts/services.py` với method `get_profile(user)` — trả dict `{email, display_name, email_verified, date_joined}`, `date_joined` format ISO 8601 UTC
- [x] 2.2 Thêm method `update_display_name(user, display_name)` — validate `display_name` là string, max 255 ký tự; raise `AccountServiceError(DISPLAY_NAME_TOO_LONG, 400)` nếu vi phạm; save và trả profile dict đã cập nhật
- [x] 2.3 Thêm method `change_password(request, user, current_password, new_password)` — kiểm tra `user.has_usable_password()` (raise `AccountServiceError(NO_USABLE_PASSWORD, 400)` nếu false); verify bằng `user.check_password()` (raise `AccountServiceError(INVALID_CURRENT_PASSWORD, 400)` nếu sai); validate `new_password` qua Django password validators (map `ValidationError` sang error codes đang dùng cho register flow); đặt password mới; gọi `update_session_auth_hash(request, user)`
- [x] 2.4 Thêm method `erase_all_chat_data(user)` — trong `atomic()` transaction: resolve sentinel = `User.objects.get(id=ANONYMOUS_USER_ID)`; bulk update `Case.objects.filter(user=user)` → `user=sentinel, guest_identity=None, context_summary="", topic=""`; bulk update `Chat.objects.filter(user=user)` → `user=sentinel, guest_identity=None, is_archived=True`; bulk update `ChatTurn.objects.filter(user=user)` → `user=sentinel, guest_identity=None, user_message_text="", assistant_response_text=""`; bulk update `MemoryItem.objects.filter(user=user)` → `user=sentinel, case=None`

## 3. Views

- [x] 3.1 Tạo `AccountMeView(APIView)` trong `accounts/views.py` — `authentication_classes = [SessionAuthentication]`, `permission_classes = [IsAuthenticated]`; `GET` gọi `get_profile`, trả `200`; `PATCH` đọc `display_name` từ body, gọi `update_display_name`, trả `200`; bắt `AccountServiceError`
- [x] 3.2 Tạo `ChangePasswordView(APIView)` — `POST` đọc `current_password` và `new_password` (thiếu field → `INVALID_REQUEST`), gọi `change_password`, trả `200 {"password_changed": true}`; bắt `AccountServiceError`
- [x] 3.3 Tạo `DeleteAllChatView(APIView)` — `POST` gọi `erase_all_chat_data(request.user)`, trả `200 {"erased": true}`

## 4. URL Routing

- [x] 4.1 Thêm URL patterns vào `accounts/urls.py`: `accounts/me/` → `AccountMeView`, `accounts/change-password/` → `ChangePasswordView`, `accounts/delete-all-chat/` → `DeleteAllChatView`

## 5. Tests

- [x] 5.1 Unit tests cho `AccountSettingsService.get_profile` — đủ fields, `date_joined` ISO 8601 UTC
- [x] 5.2 Unit tests cho `update_display_name` — happy path, empty string, vượt 255 ký tự, non-string
- [x] 5.3 Unit tests cho `change_password` — happy path, sai `current_password`, `new_password` yếu, Google-only account (no usable password)
- [x] 5.4 Unit tests cho `erase_all_chat_data` — happy path (verify sentinel được gán đúng, content scrubbed), user không có data (idempotent), atomicity (rollback khi lỗi giữa chừng)
- [x] 5.5 Integration tests cho `GET /api/accounts/me/` — authenticated trả 200 đúng shape; unauthenticated 401
- [x] 5.6 Integration tests cho `PATCH /api/accounts/me/` — update thành công; empty string; vượt 255; payload sai shape; unauthenticated
- [x] 5.7 Integration tests cho `POST /api/accounts/change-password/` — thành công; sai current; new yếu; Google-only; thiếu field; unauthenticated
- [x] 5.8 Integration tests cho `POST /api/accounts/delete-all-chat/` — thành công và verify cases/chats/turns có `user = sentinel` và content scrubbed; user không có data → 200; unauthenticated → 401

## 6. Contract và Documentation

- [x] 6.1 Cập nhật `project-spec/frontend-backend-contract.md` — thêm Section "Account Settings Endpoints" với `GET /api/accounts/me/`, `PATCH /api/accounts/me/`, `POST /api/accounts/change-password/`, `POST /api/accounts/delete-all-chat/`: request/response shape, error codes, FE behavior (confirm dialog bắt buộc trước `delete-all-chat`, account vẫn active sau)
- [x] 6.2 Cập nhật `agent-progress.md` sau khi hoàn thành change
