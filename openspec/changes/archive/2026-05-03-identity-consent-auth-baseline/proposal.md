## Why

Foundation hiện có model và endpoint tối thiểu cho guest/consent/chat, nhưng chưa có auth flow đủ để frontend bắt đầu đúng product journey: guest vào sau consent, registered user đăng ký/đăng nhập bằng email/password, và email phải được verify bằng OTP trước khi dùng registered continuity.

Change này cần đi trước request gate hardening và runtime sâu hơn, vì request gate phụ thuộc trực tiếp vào identity/session/consent state ổn định và frontend cần contract canonical để không tự suy đoán trạng thái auth/consent.

## What Changes

- Hoàn thiện baseline cho guest identity lifecycle:
  - tạo guest identity;
  - set/đọc guest cookie;
  - trả session state canonical cho frontend/BFF;
  - giữ đường dùng `X-Guest-Token` cho test/BFF nếu cần.
- Hoàn thiện consent baseline:
  - accept consent cho guest hoặc registered user hiện tại;
  - expose consent status canonical;
  - hỗ trợ nền tảng `reconsent_required` cho attach flow sau này.
- Thêm email/password auth baseline cho registered user:
  - register bằng email/password;
  - tạo OTP verification state;
  - verify email bằng OTP;
  - login chỉ cho user active và email verified;
  - logout session hiện tại.
- Làm rõ guest-to-registered handoff:
  - guest cookie không được clear trước khi guest chat hiện tại được attach sang account;
  - login không được âm thầm làm mất quyền truy cập chat guest hiện tại;
  - thêm endpoint riêng để attach current guest chat sang account sau login;
  - sau attach thành công, account phải re-consent trước khi tiếp tục chat như registered account.
- Thêm session status endpoint để frontend/BFF biết identity/session/consent state:
  - `unauthenticated`;
  - `guest`;
  - `registered`;
  - `expired`;
  - consent `required` hoặc `accepted`.
- Cập nhật `project-spec/frontend-backend-contract.md` cho các endpoint và error/control code thuộc identity/consent/auth baseline.
- Bổ sung tests cho service/API behavior chính và request gate integration liên quan consent/session.
- Không triển khai Google OAuth trong change này.
- Triển khai attach tối thiểu cho current guest chat sau login:
  - attach qua endpoint riêng;
  - registered account dùng quota window mới, không transfer quota guest;
  - attach cả `Case` của current guest chat theo rule đơn giản nhất;
  - transfer ownership phải atomic và bám rule re-consent của MVP.
- Không triển khai email verification link; MVP dùng OTP theo quyết định Owner.

## Capabilities

### New Capabilities

- `identity-consent-auth`: Quản lý guest identity, consent state, session status, email/password registration/login/logout, và OTP email verification cho MVP baseline.

### Modified Capabilities

- None.

## Impact

- Code/API:
  - `accounts` app: auth services, serializers/views/urls cho register, OTP verify/resend nếu cần, login, logout, session status.
  - `accounts`/`chat` services: attach current guest chat/case sang registered user sau login.
  - `consents` app: consent status/accept behavior và contract ổn định.
  - `runtime.request_gate`: dùng identity/session/consent state đã chuẩn hóa, không tự suy đoán ngoài service boundary.
  - `chat.views.GuestInitView`: có thể chuyển ownership endpoint về `accounts` nếu cần, nhưng phải giữ compatibility route hoặc cập nhật contract rõ ràng.
- Data:
  - dùng các field foundation hiện có trên `User` cho OTP (`email_otp_hash`, `email_otp_expires_at`, `email_otp_sent_at`, `resend_count`);
  - có thể cần migration nhỏ nếu implementation phát hiện field thiếu cho correctness.
- Contract/docs:
  - cập nhật `project-spec/frontend-backend-contract.md` cho request/response, cookies, session state, consent state, OTP flow, login/logout, và error codes.
- Tests:
  - thêm pytest/DRF API tests cho guest, consent, register, OTP verify, login/logout, session status;
  - thêm regression tests cho các nhánh gate liên quan identity/session/consent.
- Dependencies:
  - không thêm external email provider trong change này nếu chưa có cấu hình; OTP delivery có thể dùng backend email interface/local console backend cho MVP dev, nhưng contract không được expose secret OTP.
