## ADDED Requirements

### Requirement: Registered-only authentication gate cho account settings endpoints

Hệ thống SHALL yêu cầu registered session hợp lệ để truy cập tất cả account settings endpoints (`GET /api/accounts/me/`, `PATCH /api/accounts/me/`, `POST /api/accounts/change-password/`). Guest identity không được phép truy cập các endpoint này.

#### Scenario: Registered session hợp lệ pass authentication gate

- **WHEN** request đến account settings endpoint mang Django session của registered user active và email verified
- **THEN** hệ thống cho phép request tiếp tục xử lý business logic

#### Scenario: Guest identity bị từ chối

- **WHEN** request đến account settings endpoint chỉ mang guest cookie mà không có registered session
- **THEN** hệ thống trả `401` với error code `identity_not_resolved`

#### Scenario: Registered session hết hạn hoặc account bị deactivate

- **WHEN** request đến account settings endpoint với registered session của user `is_active=False` hoặc `email_verified=False`
- **THEN** hệ thống trả `401` với error code `session_expired`
