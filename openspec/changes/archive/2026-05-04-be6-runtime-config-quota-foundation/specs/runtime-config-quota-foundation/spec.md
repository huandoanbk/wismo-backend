## ADDED Requirements

### Requirement: Runtime config canonical lookup
Hệ thống SHALL cung cấp lớp lookup canonical cho `RuntimeConfig` active để runtime đọc cùng một nguồn truth cho limit và policy.

#### Scenario: Active config is returned
- **WHEN** hệ thống có `RuntimeConfig` active cho một key runtime hợp lệ
- **THEN** lookup SHALL trả giá trị đã parse cho key đó

#### Scenario: Missing config falls back to foundation default
- **WHEN** lookup request cho một key hợp lệ nhưng chưa có record active
- **THEN** hệ thống SHALL dùng foundation default deterministic cho key đó thay vì suy diễn ngẫu nhiên

### Requirement: Runtime config value shapes are canonical
Hệ thống SHALL lưu và parse `RuntimeConfig.value` theo shape canonical cho từng key runtime quota.

#### Scenario: Input limit shape
- **WHEN** lookup key là `runtime.input_limits`
- **THEN** hệ thống SHALL parse `value` thành object có `max_message_length_chars` và `max_payload_bytes`

#### Scenario: Guest quota policy shape
- **WHEN** lookup key là `quota.guest_policy`
- **THEN** hệ thống SHALL parse `value` thành object có `token_limit` và `window_seconds`

#### Scenario: User quota policy shape
- **WHEN** lookup key là `quota.user_policy`
- **THEN** hệ thống SHALL parse `value` thành object có `token_limit` và `window_seconds`

#### Scenario: Pending input limits shape
- **WHEN** lookup key là `quota.pending_input_limits`
- **THEN** hệ thống SHALL parse `value` thành object có `max_appends` và `max_chars`

### Requirement: Pending input limits are admin-configured
Hệ thống SHALL đọc `pending_input_limits` từ `RuntimeConfig` active để giới hạn state recovery khi quota đã exhausted.

#### Scenario: Pending input limits are returned
- **WHEN** hệ thống có `RuntimeConfig` active cho key `quota.pending_input_limits`
- **THEN** lookup SHALL trả giới hạn đã parse cho `max_appends` và `max_chars`

#### Scenario: Pending input limits fall back to foundation default
- **WHEN** key `quota.pending_input_limits` chưa có record active
- **THEN** hệ thống SHALL dùng foundation default deterministic cho `max_appends` và `max_chars`

### Requirement: Quota window lifecycle per identity
Hệ thống SHALL resolve current `UsageQuotaWindow` theo identity hiện tại và SHALL giữ guest/user quota tách biệt.

#### Scenario: Guest current window is resolved
- **WHEN** guest identity hợp lệ cần quota window hiện tại
- **THEN** hệ thống SHALL trả window mới nhất của guest hoặc tạo window foundation mới nếu chưa có

#### Scenario: Registered user current window is resolved
- **WHEN** registered user hợp lệ cần quota window hiện tại
- **THEN** hệ thống SHALL trả window mới nhất của user hoặc tạo window foundation mới nếu chưa có

#### Scenario: Expired window rolls to a new current window
- **WHEN** current quota window đã hết hạn theo runtime-configured window duration
- **THEN** hệ thống SHALL tạo current window mới với `window_started_at` và `window_ends_at` theo policy hiện tại

### Requirement: Quota consumption and exhausted state
Hệ thống SHALL cho phép cộng billable tokens vào quota window hiện tại và SHALL chốt trạng thái exhausted khi vượt quota.

#### Scenario: Consume tokens updates the current window
- **WHEN** billable tokens của một turn được cộng vào quota window hiện tại
- **THEN** hệ thống SHALL tăng `used_tokens` và đánh dấu `is_exhausted = true` khi tổng token đạt hoặc vượt `token_limit`

#### Scenario: Exhausted quota preserves blocked input
- **WHEN** identity hiện tại đã exhausted và request mới bị chặn ở quota gate
- **THEN** hệ thống SHALL lưu message bị chặn vào `pending_input_text` theo `quota.pending_input_limits` và cập nhật `pending_input_updated_at` để turn kế tiếp có thể xử lý recovery UX
