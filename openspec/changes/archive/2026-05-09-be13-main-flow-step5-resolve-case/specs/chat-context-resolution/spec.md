## MODIFIED Requirements

### Requirement: Bind case cho turn sau khi Step 5 resolve case
Hệ thống MUST giữ `ChatTurn` đã tạo ở Step 3 và MUST cập nhật `case_id` của turn này sau khi Step 5 resolve case hoàn tất, trước khi runtime đi Step 6.

#### Scenario: Update turn case_id sau case resolution
- **WHEN** Step 5 đã resolve được case cho turn hiện tại
- **THEN** hệ thống MUST cập nhật `ChatTurn.case_id` của turn đã tạo từ Step 3 bằng case vừa resolve
- **AND** downstream steps (Step 6+) MUST dùng cùng `turn_id` đã tạo ở Step 3

#### Scenario: Step 5 chưa resolve được case và giữ null
- **WHEN** Step 5 trả trạng thái chưa resolve case (`Chat.case_id = null`)
- **THEN** hệ thống MUST giữ `ChatTurn.case_id = null` cho turn hiện tại
- **AND** hệ thống MUST không tự gán case tạm không có quyết định rõ từ flow Step 5

#### Scenario: Pending resolution không tạo turn mới
- **WHEN** chat đang ở `is_pending_case_confirmation = true` và Step 5 đang xử lý pending/re-resolution
- **THEN** hệ thống MUST tiếp tục dùng turn hiện tại đã tạo ở Step 3
- **AND** hệ thống MUST NOT tạo thêm turn khác chỉ để xử lý pending case resolution

#### Scenario: Auto-resolve vẫn bind vào đúng turn hiện tại
- **WHEN** Step 5 auto-resolve do pending ambiguous đạt ngưỡng tối đa
- **THEN** hệ thống MUST gắn `resolved case_id` vào `ChatTurn` hiện tại
- **AND** Step 6+ MUST nhận đúng `turn_id`/`case_id` đã bind, không rebind sang turn khác
