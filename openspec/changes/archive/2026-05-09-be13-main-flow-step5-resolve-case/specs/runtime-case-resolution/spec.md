## ADDED Requirements

### Requirement: Step 5 chỉ chạy khi triage cho phép continue
Runtime MUST chỉ vào Step 5 khi `triage_decision = continue_to_full_reasoning` và MUST bỏ qua Step 5 cho các control branches Step 4.

#### Scenario: Continue branch vào Step 5
- **WHEN** Step 4 trả `triage_decision = continue_to_full_reasoning`
- **THEN** runtime MUST chạy Step 5 để resolve case cho turn hiện tại

#### Scenario: Control branch không vào Step 5
- **WHEN** Step 4 trả một trong `crisis_hotline_immediate`, `blocked_minor`, `hard_redirect`, `policy_bypass_refusal`, `spam_or_non_conversational`
- **THEN** runtime MUST NOT chạy Step 5

### Requirement: Existing chat flow phải ưu tiên case đã resolve
Step 5 MUST ưu tiên dùng case context sẵn có của chat trước khi chạy detector hoặc tạo case mới.

#### Scenario: Chat đã có case_id chính thức
- **WHEN** chat hiện tại đã có `case_id`
- **THEN** runtime MUST dùng `case_id` đó làm `resolved case_id`
- **AND** runtime MUST đi tiếp Step 6 mà không gọi detector

#### Scenario: Chat đang pending confirmation
- **WHEN** chat có `is_pending_case_confirmation = true`
- **THEN** runtime MUST đi vào pending case resolution flow
- **AND** runtime MUST NOT đi nhánh new chat detector trực tiếp

### Requirement: New chat flow với identity chưa có case
Khi chat mới chưa có `case_id` và identity chưa có case history, Step 5 MUST tạo case mới ngay.

#### Scenario: Identity chưa có case nào trước đó
- **WHEN** chat hiện tại chưa có `case_id` và identity không có case trước đó
- **THEN** runtime MUST create new case
- **AND** runtime MUST gắn `chat.case_id` bằng case mới
- **AND** runtime MUST trả `resolved case_id` để đi Step 6

### Requirement: New chat flow với identity đã có case dùng case_detector
Khi identity đã có case history, Step 5 MUST chạy `case_detector` với input chuẩn từ Main Flow.

#### Scenario: Input của case_detector
- **WHEN** chat mới chưa có `case_id` và identity đã có case trước đó
- **THEN** runtime MUST gọi `case_detector` qua LLM Gateway
- **AND** input MUST gồm `opening_input_text` của chat hiện tại và tối đa 10 recent case summaries cần nhất

#### Scenario: Detector trả matched_existing_case
- **WHEN** `case_detector` trả `matched_existing_case`
- **THEN** runtime MUST gắn chat vào case cũ được chọn
- **AND** runtime MUST trả `resolved case_id`

#### Scenario: Detector trả new_case
- **WHEN** `case_detector` trả `new_case`
- **THEN** runtime MUST create new case
- **AND** runtime MUST gắn `chat.case_id` bằng case mới
- **AND** runtime MUST trả `resolved case_id`

#### Scenario: Detector trả confirm_required
- **WHEN** `case_detector` trả `confirm_required`
- **THEN** runtime MUST bật `is_pending_case_confirmation = true`
- **AND** runtime MUST đặt `pending_confirm_turn_count = 0`
- **AND** `Chat.case_id` MUST giữ `null` cho tới khi resolve được case chính thức

### Requirement: Pending case resolution bằng re-resolution classifier
Khi chat ở trạng thái pending confirmation, mỗi message mới MUST đi qua re-resolution classifier trước khi quyết định case chính thức.

#### Scenario: Input của re-resolution classifier
- **WHEN** chat đang pending và có message mới
- **THEN** runtime MUST gọi `case_reresolution_classifier` qua LLM Gateway
- **AND** input MUST gồm message mới, opening input của chat, và recent case summaries theo recency-only

#### Scenario: Re-resolution trả use_existing_case
- **WHEN** classifier trả `use_existing_case`
- **THEN** runtime MUST gắn chat vào case cũ mục tiêu
- **AND** runtime MUST clear toàn bộ pending state
- **AND** runtime MUST đi Step 6 với `resolved case_id`

#### Scenario: Re-resolution trả create_new_case
- **WHEN** classifier trả `create_new_case`
- **THEN** runtime MUST create new case
- **AND** runtime MUST gắn `chat.case_id` bằng case mới
- **AND** runtime MUST clear toàn bộ pending state
- **AND** runtime MUST đi Step 6 với `resolved case_id`

#### Scenario: Re-resolution trả still_ambiguous
- **WHEN** classifier trả `still_ambiguous`
- **THEN** runtime MUST tăng `pending_confirm_turn_count` thêm 1
- **AND** runtime MUST giữ pending state nếu chưa đạt ngưỡng auto-resolve

### Requirement: Auto-resolve sau tối đa 3 pending turns
Nếu pending vẫn ambiguous sau 3 message, Step 5 MUST auto-create case mới để đảm bảo runtime tiến tiếp được.

#### Scenario: Pending turn 1 hoặc 2 vẫn ambiguous
- **WHEN** pending counter sau update là 1 hoặc 2
- **THEN** runtime MUST giữ pending state và chờ message kế tiếp

#### Scenario: Pending turn 3 vẫn ambiguous
- **WHEN** pending counter sau update đạt 3 và trạng thái vẫn `still_ambiguous`
- **THEN** runtime MUST create new case
- **AND** runtime MUST gắn `chat.case_id` bằng case mới
- **AND** runtime MUST clear pending state
- **AND** runtime MUST đi Step 6 với `resolved case_id`

### Requirement: Operation routing và fallback cho detector/re-resolution
Step 5 MUST dùng operation registry qua LLM Gateway cho `case_detector` và `case_reresolution_classifier`, không gọi provider trực tiếp.

#### Scenario: Operation thiếu hoặc mapping invalid
- **WHEN** operation Step 5 thiếu, inactive, hoặc mapping gateway invalid
- **THEN** runtime MUST giữ `Chat.case_id = null`
- **AND** runtime MUST ghi metadata lỗi classifier để downstream xử lý theo policy runtime

### Requirement: Output Step 5 phải trả trạng thái case resolution minh bạch
Step 5 MUST trả rõ trạng thái resolution để downstream biết `case_id` đã resolve hay vẫn `null`.

#### Scenario: Handoff sang Step 6
- **WHEN** Step 5 hoàn tất
- **THEN** output nội bộ MUST chứa `resolved chat_id` và `case_id` hiện tại (có thể `null`)
- **AND** output nội bộ MUST chứa `case_resolution_status` để điều phối bước kế tiếp
