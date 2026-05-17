## ADDED Requirements

### Requirement: Guest identity session

Hệ thống SHALL cho phép client tạo guest identity trước khi chat và SHALL expose guest identity qua cookie/session contract rõ ràng.

#### Scenario: Create guest identity

- **WHEN** client gọi endpoint guest init khi chưa authenticated
- **THEN** hệ thống tạo `GuestIdentity` active, set cookie `wismo_guest`, và trả `session_state = "guest"` với `consent_state = "required"`

#### Scenario: Resolve guest by cookie or header

- **WHEN** request có cookie `wismo_guest` hợp lệ hoặc header `X-Guest-Token` hợp lệ
- **THEN** hệ thống resolve identity là guest và refresh `last_seen_at`

#### Scenario: Expired guest identity

- **WHEN** request/session status dùng guest identity inactive hoặc đã hết hạn
- **THEN** hệ thống không cho guest đi tiếp như identity hợp lệ và trả trạng thái/code expired phù hợp với contract

### Requirement: Consent state

Hệ thống SHALL yêu cầu consent active trước khi guest hoặc registered user bắt đầu chat runtime.

#### Scenario: Accept consent for guest

- **WHEN** guest identity hợp lệ gọi consent accept
- **THEN** hệ thống tạo `ConsentRecord` current version cho guest và trả `consent_state = "accepted"`

#### Scenario: Accept consent for registered user

- **WHEN** registered session hợp lệ gọi consent accept
- **THEN** hệ thống tạo `ConsentRecord` current version cho user và trả `consent_state = "accepted"`

#### Scenario: Consent required before chat

- **WHEN** identity hợp lệ chưa có active consent current version
- **THEN** request gate dừng trước runtime core flow và trả `consent_required`

#### Scenario: Re-consent required record

- **WHEN** consent record mới nhất bị revoke hoặc có `reconsent_required = true`
- **THEN** hệ thống coi consent state là `required` cho tới khi identity accept consent current version mới

### Requirement: Session status contract

Hệ thống SHALL expose endpoint session status canonical để frontend/BFF không tự suy đoán identity hoặc consent state.

#### Scenario: Unauthenticated session

- **WHEN** client không có authenticated user session và không có guest identity hợp lệ
- **THEN** session status trả `session_state = "unauthenticated"`, `identity_type = "none"`, và `consent_state = "unknown"`

#### Scenario: Guest session status

- **WHEN** client có guest identity hợp lệ nhưng chưa login registered user
- **THEN** session status trả `session_state = "guest"`, `identity_type = "guest"`, guest id, và consent state canonical

#### Scenario: Registered session status

- **WHEN** client có authenticated verified active user session
- **THEN** session status trả `session_state = "registered"`, `identity_type = "user"`, user metadata tối thiểu, và consent state canonical

#### Scenario: Expired session status

- **WHEN** client gửi guest cookie không còn active hoặc expired
- **THEN** session status trả `session_state = "expired"` và không coi identity đó là chat-eligible

### Requirement: Email/password registration with OTP

Hệ thống SHALL cho phép đăng ký bằng email/password và SHALL yêu cầu OTP email verification trước khi user trở thành registered chat identity hoạt động.

#### Scenario: Register new user

- **WHEN** client gửi email/password hợp lệ tới register endpoint
- **THEN** hệ thống tạo user chưa verified, lưu password hash, tạo OTP verification state, gửi OTP qua email backend, và trả `email_verification_required`

#### Scenario: Register existing verified email

- **WHEN** client đăng ký bằng email đã thuộc user verified
- **THEN** hệ thống không tạo user mới và trả error code theo contract cho email đã tồn tại

#### Scenario: Register existing unverified email

- **WHEN** client đăng ký lại bằng email thuộc user chưa verified
- **THEN** hệ thống xử lý như resend/regenerate OTP theo policy và không tạo duplicate user

#### Scenario: OTP is not exposed

- **WHEN** register hoặc resend OTP thành công
- **THEN** response API không chứa OTP plaintext, OTP hash, hoặc secret verification material

### Requirement: OTP verification

Hệ thống SHALL verify email bằng OTP còn hiệu lực trước khi user được login như registered identity.

#### Scenario: Verify correct OTP

- **WHEN** client gửi email và OTP đúng, còn hạn, thuộc user chưa verified
- **THEN** hệ thống set `email_verified = true`, clear OTP verification state, và trả trạng thái verify thành công theo contract

#### Scenario: Verify invalid OTP

- **WHEN** client gửi OTP sai hoặc không khớp hash
- **THEN** hệ thống không verify email và trả `invalid_otp`

#### Scenario: Verify expired OTP

- **WHEN** client gửi OTP đã hết hạn
- **THEN** hệ thống không verify email và trả `otp_expired`

#### Scenario: Resend OTP

- **WHEN** client yêu cầu resend OTP cho user chưa verified và request đạt cooldown/cap policy
- **THEN** hệ thống tạo OTP mới, cập nhật OTP state, gửi email, và không expose OTP plaintext trong response

### Requirement: Registered login and logout

Hệ thống SHALL chỉ tạo registered session cho user active, password đúng, và email đã verified.

#### Scenario: Login verified user

- **WHEN** client gửi email/password đúng cho user active và verified
- **THEN** hệ thống tạo Django session registered, trả `session_state = "registered"`, và consent state canonical

#### Scenario: Login unverified user

- **WHEN** client gửi email/password đúng nhưng user chưa verified
- **THEN** hệ thống không tạo registered session và trả `email_verification_required`

#### Scenario: Login invalid credentials

- **WHEN** client gửi email/password sai hoặc user không active
- **THEN** hệ thống không tạo session và trả `invalid_credentials`

#### Scenario: Logout current session

- **WHEN** client gọi logout với registered session hiện tại
- **THEN** hệ thống xóa Django session hiện tại và trả `session_state = "unauthenticated"` hoặc guest state nếu contract giữ guest cookie hợp lệ

### Requirement: Attach current guest chat to registered account

Hệ thống SHALL cho phép registered user đã login attach current guest chat sang account bằng endpoint riêng, và SHALL thực hiện transfer ownership một cách atomic.

#### Scenario: Attach current guest chat successfully

- **WHEN** verified registered user đã login gọi attach endpoint với `chat_id` thuộc guest identity hiện tại
- **THEN** hệ thống transfer `Case` gắn với chat đó, các `Chat` thuộc case đó trong guest identity hiện tại, và các `ChatTurn` liên quan sang user trong một transaction

#### Scenario: Attach does not cross guest identity boundary

- **WHEN** verified registered user đã login gọi attach endpoint với `chat_id` không thuộc guest identity hiện tại
- **THEN** hệ thống từ chối attach, không transfer dữ liệu, và không clear guest cookie

#### Scenario: Attach uses new registered quota

- **WHEN** current guest chat được attach sang registered user
- **THEN** hệ thống không transfer hoặc copy quota window guest sang user, và registered user dùng quota window mới theo policy registered

#### Scenario: Attach requires re-consent

- **WHEN** attach current guest chat thành công
- **THEN** hệ thống đánh dấu registered account cần consent lại trước khi tiếp tục chat như registered account

#### Scenario: Attach clears guest cookie after success

- **WHEN** attach current guest chat thành công
- **THEN** response clear cookie `wismo_guest` để registered session trở thành identity canonical

#### Scenario: Attach failure preserves guest ownership

- **WHEN** attach endpoint fail vì thiếu registered session, guest token invalid, hoặc `chat_id` không thuộc guest hiện tại
- **THEN** hệ thống không transfer ownership, không clear guest cookie, và conversation vẫn thuộc guest

### Requirement: Frontend-backend contract for identity and consent

Hệ thống SHALL cập nhật `project-spec/frontend-backend-contract.md` cho toàn bộ API và control behavior thuộc identity, guest, consent, register, OTP verify, login, logout, attach current guest chat, và session status.

#### Scenario: Contract describes endpoint payloads

- **WHEN** change thêm hoặc sửa identity/consent/auth endpoint
- **THEN** contract mô tả method, path, request body, response body, cookie behavior, status codes, và FE behavior tương ứng

#### Scenario: Contract describes error codes

- **WHEN** endpoint có thể trả validation/auth/consent/session error
- **THEN** contract liệt kê error code, ý nghĩa nghiệp vụ, và frontend behavior tương ứng

#### Scenario: FE does not infer consent locally

- **WHEN** FE cần biết consent state cho UI
- **THEN** FE dùng session/consent response theo contract thay vì tự suy đoán từ local storage hoặc previous UI state
