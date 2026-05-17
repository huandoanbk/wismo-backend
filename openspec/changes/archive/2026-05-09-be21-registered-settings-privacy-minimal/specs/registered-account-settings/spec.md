## ADDED Requirements

### Requirement: Profile read cho registered user

Hệ thống SHALL expose endpoint GET để registered user đọc profile đầy đủ của mình. Endpoint chỉ hoạt động khi có registered session hợp lệ.

#### Scenario: Đọc profile thành công

- **WHEN** registered user có session hợp lệ gọi `GET /api/accounts/me/`
- **THEN** hệ thống trả `200` với payload gồm `email`, `display_name`, `email_verified`, `date_joined` của user

#### Scenario: Unauthenticated không được đọc profile

- **WHEN** request không có registered session hợp lệ gọi `GET /api/accounts/me/`
- **THEN** hệ thống trả `401` với error code `identity_not_resolved`

### Requirement: Cập nhật display_name

Hệ thống SHALL cho phép registered user cập nhật `display_name` qua `PATCH /api/accounts/me/`. Chỉ field `display_name` được chấp nhận; các field khác bị bỏ qua hoặc trả error nếu payload sai shape.

#### Scenario: Cập nhật display_name thành công

- **WHEN** registered user gửi `PATCH /api/accounts/me/` với `display_name` hợp lệ (string, tối đa 255 ký tự)
- **THEN** hệ thống cập nhật `display_name` và trả `200` với profile đã cập nhật

#### Scenario: Xóa display_name bằng chuỗi rỗng

- **WHEN** registered user gửi `PATCH /api/accounts/me/` với `display_name = ""`
- **THEN** hệ thống set `display_name` về `""` và trả `200` với profile phản ánh tên rỗng

#### Scenario: display_name vượt giới hạn

- **WHEN** registered user gửi `display_name` dài hơn 255 ký tự
- **THEN** hệ thống trả `400` với error code `display_name_too_long`

#### Scenario: Payload sai shape

- **WHEN** request body không phải JSON hợp lệ hoặc `display_name` không phải string
- **THEN** hệ thống trả `400` với error code `invalid_request`

#### Scenario: Unauthenticated không được cập nhật

- **WHEN** request không có registered session hợp lệ gọi `PATCH /api/accounts/me/`
- **THEN** hệ thống trả `401` với error code `identity_not_resolved`

### Requirement: Đổi mật khẩu

Hệ thống SHALL cho phép registered user đổi mật khẩu bằng `POST /api/accounts/change-password/` với `current_password` và `new_password`. Endpoint chỉ dùng được khi có registered session hợp lệ.

#### Scenario: Đổi mật khẩu thành công

- **WHEN** registered user gửi `current_password` đúng và `new_password` hợp lệ theo Django password validation
- **THEN** hệ thống cập nhật password hash, update session auth hash để session không bị invalidated, và trả `200` với `{"password_changed": true}`

#### Scenario: current_password sai

- **WHEN** registered user gửi `current_password` không khớp password hiện tại
- **THEN** hệ thống trả `400` với error code `invalid_current_password`

#### Scenario: new_password không đáp ứng policy

- **WHEN** `new_password` vi phạm Django password validation (quá ngắn, quá phổ biến, toàn số, giống email)
- **THEN** hệ thống trả `400` với error code tương ứng theo policy validation đang dùng cho register flow

#### Scenario: Google-only account không có usable password

- **WHEN** registered user tạo account qua Google OAuth không có usable password gọi change-password
- **THEN** hệ thống trả `400` với error code `no_usable_password`

#### Scenario: Unauthenticated không được đổi mật khẩu

- **WHEN** request không có registered session hợp lệ gọi `POST /api/accounts/change-password/`
- **THEN** hệ thống trả `401` với error code `identity_not_resolved`

#### Scenario: Payload thiếu field

- **WHEN** request thiếu `current_password` hoặc `new_password`
- **THEN** hệ thống trả `400` với error code `invalid_request`

### Requirement: Anonymous Sentinel User

Hệ thống SHALL có một `User` record đặc biệt gọi là **Anonymous Sentinel** dùng để tiếp nhận ownership của tất cả data bị anonymize theo GDPR. Record này được seed một lần qua data migration và không thể bị xóa hay dùng để login.

Thuộc tính của Anonymous Sentinel:
- `id`: UUID cố định, hard-coded trong `accounts/constants.py` là `ANONYMOUS_USER_ID`
- `email`: `anonymous@system.internal`
- `display_name`: `Anonymous`
- `is_active`: `False` — không login được, không có session
- `email_verified`: `False`
- Không có usable password

#### Scenario: Sentinel không thể login

- **WHEN** bất kỳ auth endpoint nào nhận request với email `anonymous@system.internal`
- **THEN** hệ thống từ chối như user bình thường inactive (`email_verified=False` hoặc `is_active=False`) — không có path đặc biệt

#### Scenario: Sentinel không xuất hiện trong session status

- **WHEN** session status resolve user `is_active=False`
- **THEN** hệ thống trả `session_expired` — sentinel không thể có active session

### Requirement: Xóa toàn bộ chat history và profile data theo GDPR right to erasure

Hệ thống SHALL cho phép registered user xóa toàn bộ dữ liệu cá nhân trong lịch sử trò chuyện qua `POST /api/accounts/delete-all-chat/`. Operation này anonymize hoàn toàn và không thể phục hồi. Account của user vẫn còn active sau khi xóa.

`Case`, `Chat`, `ChatTurn` có DB constraint `exactly_one_owner` (bắt buộc có đúng một owner — user hoặc guest_identity, không được NULL cả hai). Vì vậy ownership không được NULL mà phải được reassign về Anonymous Sentinel. Toàn bộ content nhận dạng cá nhân được xóa trắng.

Các bảng xử lý trong một atomic transaction:
- `cases` thuộc user: `user = Anonymous Sentinel`, `guest_identity = NULL`, `context_summary = ""`, `topic = ""`
- `chats` thuộc user: `user = Anonymous Sentinel`, `guest_identity = NULL`, `is_archived = True`
- `chat_turns` thuộc user: `user = Anonymous Sentinel`, `guest_identity = NULL`, `user_message_text = ""`, `assistant_response_text = ""`
- `memory_items` thuộc user: `user = Anonymous Sentinel`, `case = NULL`

#### Scenario: Xóa toàn bộ data thành công

- **WHEN** registered user gọi `POST /api/accounts/delete-all-chat/` với session hợp lệ
- **THEN** hệ thống thực hiện anonymize toàn bộ cases, chats, turns, và xóa memory_items của user đó trong một atomic transaction, sau đó trả `200 {"erased": true}`

#### Scenario: User không có data nào

- **WHEN** registered user gọi `POST /api/accounts/delete-all-chat/` nhưng chưa có chat/case nào
- **THEN** hệ thống vẫn trả `200 {"erased": true}` (idempotent — không có gì để xóa cũng là thành công)

#### Scenario: Unauthenticated không được thực hiện

- **WHEN** request không có registered session hợp lệ gọi `POST /api/accounts/delete-all-chat/`
- **THEN** hệ thống trả `401` với error code `identity_not_resolved`

#### Scenario: Account vẫn active sau khi xóa

- **WHEN** operation xóa hoàn tất
- **THEN** user vẫn có thể login, consent, và bắt đầu chat mới với clean state
