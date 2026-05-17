## ADDED Requirements

### Requirement: Google sign-in surfaces
Hệ thống SHALL hỗ trợ Google sign-in trên web bằng cả `Sign in with Google` button và Google One Tap trên cùng một login surface.

#### Scenario: Button is always available
- **WHEN** user mở trang login/auth surface của app
- **THEN** giao diện SHALL hiển thị `Sign in with Google` button như fallback bắt buộc

#### Scenario: One Tap is optional enhancement
- **WHEN** browser và trạng thái Google session cho phép hiển thị One Tap
- **THEN** giao diện SHALL có thể hiển thị One Tap prompt song song với button

#### Scenario: One Tap is unavailable
- **WHEN** browser không hỗ trợ One Tap hoặc người dùng đã dismiss prompt
- **THEN** button vẫn phải hoạt động như đường sign-in chính

### Requirement: Google credential relay through BFF
Hệ thống SHALL cho phép browser gửi Google `credential` hoặc `ID token` tới BFF public login surface, và BFF SHALL chuyển tiếp credential đó tới backend nội bộ để verify.

#### Scenario: Google credential submitted to BFF
- **WHEN** Google Identity Services trả về `credential` cho browser
- **THEN** browser gửi credential đó tới BFF public login endpoint, không gửi trực tiếp vào backend public API

#### Scenario: BFF forwards credential to backend
- **WHEN** BFF nhận Google credential hợp lệ ở public login surface
- **THEN** BFF SHALL gọi backend nội bộ để verify token và lấy canonical login result

#### Scenario: No Google secret in browser
- **WHEN** FE/BFF render button hoặc One Tap
- **THEN** `client_secret` và toàn bộ logic verify token SHALL chỉ nằm ở server side

### Requirement: Google token verification
Hệ thống SHALL verify Google credential ở server side trước khi tạo registered session canonical.

#### Scenario: Verify signed token
- **WHEN** backend nhận Google credential từ BFF
- **THEN** backend SHALL verify chữ ký, `aud`, `iss`, `exp`, và trạng thái email đã verified trước khi chấp nhận login

#### Scenario: Verify canonical identity claims
- **WHEN** token verify thành công
- **THEN** backend SHALL dùng claim `sub` làm định danh Google canonical và không dựa vào giá trị user id không thể verify

#### Scenario: Invalid or expired token
- **WHEN** credential không verify được hoặc token đã hết hạn
- **THEN** backend SHALL từ chối login và trả lỗi canonical cho BFF

### Requirement: Google account mapping
Hệ thống SHALL map Google identity vào registered user theo policy canonical của MVP.

#### Scenario: Existing linked Google account
- **WHEN** token `sub` khớp với một user đã có `google_id`
- **THEN** backend SHALL login đúng user đó và tạo Django session canonical

#### Scenario: Existing user matched by verified email
- **WHEN** token đã verify và email Google khớp một user hiện có nhưng user đó chưa được link `google_id`
- **THEN** backend SHALL link `google_id` vào user đó, giữ email verified, và login user đó

#### Scenario: New Google user
- **WHEN** token đã verify nhưng không có user nào phù hợp để link
- **THEN** backend SHALL tạo user mới với `email_verified = true`, gán `google_id`, và login user mới

#### Scenario: Account conflict
- **WHEN** token đã verify nhưng policy link account không hợp lệ vì xung đột định danh
- **THEN** backend SHALL từ chối login và trả lỗi canonical cho BFF thay vì tự merge mơ hồ

### Requirement: Google login canonical session
Hệ thống SHALL trả canonical registered session state sau khi Google login thành công.

#### Scenario: Successful Google login
- **WHEN** backend verify thành công và map được user
- **THEN** backend SHALL trả `session_state = "registered"`, `identity_type = "user"`, và `consent_state` canonical theo cùng contract với login email/password

#### Scenario: Guest continuity stays separate
- **WHEN** user Google-login thành công nhưng còn guest cookie hợp lệ
- **THEN** Google login SHALL không tự động attach guest data và guest attach vẫn là endpoint riêng

#### Scenario: Logout does not revoke Google account
- **WHEN** user logout khỏi WISMO
- **THEN** backend chỉ xóa session WISMO; việc logout Google account bên ngoài phạm vi change này
