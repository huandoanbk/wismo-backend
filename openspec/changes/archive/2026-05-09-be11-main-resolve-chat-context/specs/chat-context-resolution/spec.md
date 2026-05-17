## ADDED Requirements

### Requirement: Resolve chat context tối thiểu sau gate pass
Hệ thống MUST chạy Step 3 ngay sau khi Request Gate pass và MUST kết thúc step này với chat context khả dụng cho downstream runtime.

#### Scenario: Request có chat_id hợp lệ
- **WHEN** runtime nhận request đã gate-pass và payload có `chat_id`
- **THEN** hệ thống MUST load chat hiện có theo `chat_id` đó và dùng chat này làm context cho turn hiện tại

#### Scenario: Request không có chat_id
- **WHEN** runtime nhận request đã gate-pass và payload không có `chat_id`
- **THEN** hệ thống MUST tạo chat mới thuộc identity hiện tại với `case_id = null`
- **AND** hệ thống MUST lưu `opening_input_text` bằng message đầu tiên của request

### Requirement: Tạo turn intake record canonical tại Step 3
Hệ thống MUST tạo `ChatTurn` record ngay tại Step 3 để downstream steps dùng chung một turn anchor.

#### Scenario: Turn intake cho mọi gate-pass request
- **WHEN** Step 3 resolve xong chat context
- **THEN** hệ thống MUST tạo một `ChatTurn` mới gắn với chat đã resolve
- **AND** hệ thống MUST lưu `user_message_text` bằng message hiện tại
- **AND** hệ thống MUST gán `turn_id` do backend tự sinh
- **AND** `ChatTurn.case_id` MUST khởi tạo là `null` tại Step 3

#### Scenario: Không nhận client_turn_id
- **WHEN** request chat message đi qua Step 3
- **THEN** hệ thống MUST NOT yêu cầu hoặc map `client_turn_id` vào `ChatTurn`
- **AND** turn identity duy nhất cho downstream MUST là `turn_id` do backend sinh

### Requirement: Bàn giao context chuẩn cho Step 4
Step 3 MUST bàn giao đầy đủ dữ liệu context tối thiểu để Step 4 (Fast triage) chạy không cần re-resolve chat.

#### Scenario: Output Step 3 cho downstream runtime
- **WHEN** Step 3 hoàn tất
- **THEN** output nội bộ MUST chứa tối thiểu `chat_id`, `turn_id`, chat object đã resolve, và turn record đã persist

#### Scenario: Contract cho implicit chat creation
- **WHEN** request không có `chat_id` và backend đã tạo chat mới
- **THEN** contract FE/BE MUST mô tả rõ rằng FE nhận `chat_id` và `turn_id` canonical từ SSE lifecycle (bao gồm `done` event) để đồng bộ thread state

### Requirement: Bind case cho turn sau khi Step 5 resolve case
Hệ thống MUST giữ `ChatTurn` đã tạo ở Step 3 và MUST cập nhật `case_id` của turn này sau khi Step 5 resolve case hoàn tất.

#### Scenario: Update turn case_id sau case resolution
- **WHEN** Step 5 đã resolve được case cho turn hiện tại
- **THEN** hệ thống MUST cập nhật `ChatTurn.case_id` của turn đã tạo từ Step 3 bằng case vừa resolve
- **AND** downstream steps (Step 6+) MUST dùng cùng `turn_id` đã tạo ở Step 3
