## ADDED Requirements

### Requirement: Chat bootstrap endpoints

Hệ thống SHALL expose chat bootstrap APIs để FE/BFF có thể tạo, liệt kê, và mở chat theo `chat_id` canonical.

#### Scenario: Create chat shell
- **WHEN** client gọi `POST /api/chat/` với identity hiện tại hợp lệ
- **THEN** backend tạo `Chat` mới thuộc identity hiện tại, giữ `case_id = null` nếu chưa resolve case, gán `chat_display_name` fallback canonical, và trả summary chat theo contract

#### Scenario: Create chat with opening input
- **WHEN** client tạo chat với `opening_input_text` hợp lệ hoặc runtime bootstrap tạo chat từ first turn
- **THEN** backend lưu `opening_input_text` vào chat và trả lại giá trị đó trong response detail/list theo contract

#### Scenario: List owned chats
- **WHEN** client gọi `GET /api/chat/` với identity hiện tại hợp lệ
- **THEN** backend trả danh sách chat chỉ thuộc identity đó, sắp xếp theo `last_activity_at` giảm dần, và mỗi item chỉ là summary của chat

#### Scenario: Get chat detail with history
- **WHEN** client gọi `GET /api/chat/<chat_id>/` với chat thuộc identity hiện tại
- **THEN** backend trả chat summary và `turns` history theo thứ tự từ cũ đến mới

#### Scenario: Empty turn history
- **WHEN** chat chưa có turn nào
- **THEN** detail response vẫn trả `turns: []`

### Requirement: Chat ownership boundary

Hệ thống SHALL chỉ cho current identity đọc chat thuộc chính identity đó và SHALL từ chối truy cập chat của identity khác.

#### Scenario: Guest ownership is canonical
- **WHEN** request resolve thành guest identity hợp lệ
- **THEN** list/detail chỉ trả chat có owner guest identity đó

#### Scenario: Registered ownership is canonical
- **WHEN** request resolve thành registered user session hợp lệ
- **THEN** list/detail chỉ trả chat có owner user đó

#### Scenario: Foreign chat is denied
- **WHEN** client gọi detail cho chat thuộc identity khác
- **THEN** backend trả `chat_access_denied`

#### Scenario: Missing chat is denied
- **WHEN** client gọi detail cho chat không tồn tại hoặc chat không còn available
- **THEN** backend trả `chat_not_found`

#### Scenario: Identity cannot be resolved
- **WHEN** request không có registered session hợp lệ và không có guest identity hợp lệ
- **THEN** backend trả `identity_not_resolved`

### Requirement: Chat metadata canonical

Hệ thống SHALL expose chat metadata canonical cho UI gồm `chat_id`, `chat_display_name`, `case_id`, `opening_input_text`, `created_at`, và `last_activity_at`.

#### Scenario: Fallback display name is returned
- **WHEN** chat chưa có display name riêng
- **THEN** backend trả fallback `chat_display_name` canonical trong create/list/detail response

#### Scenario: Case id can be null
- **WHEN** chat chưa resolve case
- **THEN** backend vẫn trả detail/list với `case_id = null`

#### Scenario: List response is summary only
- **WHEN** client gọi `GET /api/chat/`
- **THEN** response item của list chỉ chứa summary fields của chat và không chứa `turns` history

#### Scenario: Turn history item shape is stable
- **WHEN** detail response có turn history
- **THEN** mỗi turn item SHALL expose các field cần thiết để FE render chronology và replay trạng thái turn, gồm `turn_id`, `client_turn_id`, `user_message_text`, `assistant_response_text`, `response_method`, `status`, `created_at`, `finalized_at`, và `case_id`

#### Scenario: Chat detail preserves ordering
- **WHEN** detail response có nhiều turn
- **THEN** `turns` được trả theo thứ tự tăng dần theo thời gian tạo để FE render chronology ổn định
