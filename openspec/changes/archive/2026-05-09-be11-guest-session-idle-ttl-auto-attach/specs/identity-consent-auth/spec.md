## MODIFIED Requirements

### Requirement: Guest identity session

Hệ thống SHALL cho phép client tạo guest identity trước khi chat và SHALL expose guest identity qua cookie/session contract rõ ràng.

#### Scenario: Create guest identity

- **WHEN** client gọi endpoint guest init khi chưa authenticated
- **THEN** hệ thống tạo `GuestIdentity` active với `expires_at` được set theo `WISMO_GUEST_IDLE_TTL_HOURS`, set cookie `wismo_guest`, và trả `session_state = "guest"` với `consent_state = "required"`

#### Scenario: Resolve guest by cookie or header

- **WHEN** request có cookie `wismo_guest` hợp lệ hoặc header `X-Guest-Token` hợp lệ
- **THEN** hệ thống resolve identity là guest; `last_seen_at` và `expires_at` chỉ được refresh khi đây là `POST /api/chat/message/` request

#### Scenario: Expired guest identity

- **WHEN** request/session status dùng guest identity inactive hoặc đã hết hạn
- **THEN** hệ thống không cho guest đi tiếp như identity hợp lệ và trả trạng thái/code expired phù hợp với contract

### Requirement: OTP verification với silent guest auto-attach

Hệ thống SHALL verify email bằng OTP còn hiệu lực trước khi user được login như registered identity. Nếu request mang guest cookie hợp lệ có eligible chat, hệ thống SHALL silently attach guest chat sang user đó trong cùng transaction.

#### Scenario: Verify correct OTP

- **WHEN** client gửi email và OTP đúng, còn hạn, thuộc user chưa verified
- **THEN** hệ thống set `email_verified = true`, clear OTP verification state, và trả trạng thái verify thành công theo contract

#### Scenario: Verify invalid OTP

- **WHEN** client gửi OTP sai hoặc không khớp hash
- **THEN** hệ thống không verify email và trả `invalid_otp`

#### Scenario: Verify expired OTP

- **WHEN** client gửi OTP đã hết hạn
- **THEN** hệ thống không verify email và trả `otp_expired`

#### Scenario: Silent auto-attach sau verify OTP thành công

- **WHEN** OTP verify thành công và request mang `wismo_guest` cookie trỏ đến guest identity hợp lệ có ít nhất một active chat chưa archived
- **THEN** hệ thống tự động attach guest chat sang user mới verified (transfer ownership atomically), clear `wismo_guest` cookie trong response, và không thay đổi response shape của verify endpoint

#### Scenario: Verify thành công dù auto-attach không thể thực hiện

- **WHEN** OTP verify thành công nhưng guest không có eligible chat (không có chat, chat đã archived, guest inactive/expired, không có cookie)
- **THEN** hệ thống vẫn trả verify success; không attach, không clear guest cookie, không báo lỗi

#### Scenario: Verify không bị block bởi attach failure

- **WHEN** OTP verify thành công nhưng attach gặp lỗi nội bộ (IntegrityError, conflict)
- **THEN** hệ thống log warning nội bộ, trả verify success bình thường, không expose attach error ra response

#### Scenario: Resend OTP

- **WHEN** client yêu cầu resend OTP cho user chưa verified và request đạt cooldown/cap policy
- **THEN** hệ thống tạo OTP mới, cập nhật OTP state, gửi email, và không expose OTP plaintext trong response

### Requirement: Google sign-in via BFF

Hệ thống SHALL hỗ trợ Google sign-in trên web bằng cả `Sign in with Google` button và Google One Tap trên cùng một login surface, với browser gửi Google `credential` / `ID token` tới BFF public login surface và BFF relay credential đó tới backend nội bộ để verify.

#### Scenario: Button is always available

- **WHEN** user mở trang login/auth surface của app
- **THEN** giao diện SHALL hiển thị `Sign in with Google` button như fallback bắt buộc

#### Scenario: One Tap is optional enhancement

- **WHEN** browser và trạng thái Google session cho phép hiển thị One Tap
- **THEN** giao diện SHALL có thể hiển thị One Tap prompt song song với button

#### Scenario: One Tap is unavailable

- **WHEN** browser không hỗ trợ One Tap hoặc người dùng đã dismiss prompt
- **THEN** button vẫn phải hoạt động như đường sign-in chính

#### Scenario: Google credential submitted to BFF

- **WHEN** Google Identity Services trả về `credential` cho browser
- **THEN** browser gửi credential đó tới BFF public login endpoint, không gửi trực tiếp vào backend public API

#### Scenario: BFF forwards credential to backend

- **WHEN** BFF nhận Google credential hợp lệ ở public login surface
- **THEN** BFF SHALL gọi backend nội bộ để verify token và lấy canonical login result

#### Scenario: No Google secret in browser

- **WHEN** FE/BFF render button hoặc One Tap
- **THEN** `client_secret` và toàn bộ logic verify token SHALL chỉ nằm ở server side

#### Scenario: Verify signed token

- **WHEN** backend nhận Google credential từ BFF
- **THEN** backend SHALL verify chữ ký, `aud`, `iss`, `exp`, và trạng thái email đã verified trước khi chấp nhận login

#### Scenario: Verify canonical identity claims

- **WHEN** token verify thành công
- **THEN** backend SHALL dùng claim `sub` làm định danh Google canonical và không dựa vào giá trị user id không thể verify

#### Scenario: Invalid or expired token

- **WHEN** credential không verify được hoặc token đã hết hạn
- **THEN** backend SHALL từ chối login và trả lỗi canonical cho BFF

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

#### Scenario: Successful Google login

- **WHEN** backend verify thành công và map được user
- **THEN** backend SHALL trả `session_state = "registered"`, `identity_type = "user"`, và `consent_state` canonical theo cùng contract với login email/password

#### Scenario: Guest continuity stays separate from Google login

- **WHEN** user Google-login thành công nhưng còn guest cookie hợp lệ
- **THEN** Google login SHALL không tự động attach guest data; guest attach chỉ xảy ra qua OTP verify flow

#### Scenario: Logout does not revoke Google account

- **WHEN** user logout khỏi WISMO
- **THEN** backend chỉ xóa session WISMO; việc logout Google account bên ngoài phạm vi change này

## REMOVED Requirements

### Requirement: Attach current guest chat to registered account

**Reason**: Attach flow được thay thế bởi silent auto-attach trong OTP verify flow. FE không còn cần gọi endpoint attach thủ công sau khi verify OTP.

**Migration**: Endpoint `POST /api/accounts/guest/attach/` bị xóa. FE không gọi endpoint này nữa. Attach xảy ra tự động trong `POST /api/accounts/verify-email/` nếu đủ điều kiện.
