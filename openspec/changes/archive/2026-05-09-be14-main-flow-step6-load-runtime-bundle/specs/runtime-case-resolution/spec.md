## MODIFIED Requirements

### Requirement: Output Step 5 phải trả trạng thái case resolution minh bạch
Step 5 MUST trả rõ trạng thái resolution để downstream biết `case_id` đã resolve hay vẫn `null`, và Step 6 MUST được phép chạy với cả hai trạng thái.

#### Scenario: Handoff sang Step 6
- **WHEN** Step 5 hoàn tất
- **THEN** output nội bộ MUST chứa `resolved chat_id` và `case_id` hiện tại (có thể `null`)
- **AND** output nội bộ MUST chứa `case_resolution_status` để điều phối bước kế tiếp
- **AND** Step 6 MUST dùng context này để assemble `runtime_bundle` mà không yêu cầu bắt buộc phải có `case_id`
