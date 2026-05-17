## Why

MVP cần hỗ trợ Google sign-in theo cách an toàn với kiến trúc BFF hiện có: browser chỉ nhìn thấy BFF và Google Identity Services, còn `client_secret` và logic verify phải nằm ở server. Change này là của repo BE, mục tiêu là chốt backend contract và behavior canonical để FE/BFF wire đúng mà không phải đổi kiến trúc ở phía client.

## What Changes

- Thêm support Google sign-in ở BE theo contract BFF-facing, để web có thể dùng Google Identity Services qua BFF.
- Hỗ trợ cả `Sign in with Google` button và Google One Tap trên cùng một login surface.
- Cho phép browser nhận Google `credential` / `ID token` rồi gửi về BFF, sau đó BFF chuyển tiếp sang BE nội bộ để verify.
- BE verify chữ ký và claims của Google token, map user theo `google_id` hoặc verified email, rồi tạo Django session canonical.
- Giữ nguyên nguyên tắc: BE không lộ `client_secret` ra FE, FE không gọi BE public trực tiếp cho Google auth.
- Cập nhật `project-spec/frontend-backend-contract.md` để FE/BFF biết cách render, gọi và xử lý success/error của Google sign-in.

## Capabilities

### New Capabilities
- `google-signin-bff`: Google sign-in cho web qua BFF, gồm button/One Tap UX, credential relay, và backend verification boundary.

### Modified Capabilities
- `identity-consent-auth`: mở rộng auth surface để chấp nhận Google login như một đường đăng nhập hợp lệ bên cạnh email/password, cùng canonical session response và account-linking policy.

## Impact

- Affected code: `accounts/services.py`, `accounts/views.py`, `accounts/urls.py`, model/session linking logic trong `accounts.models.User`, và test suite auth/session.
- Affected API: thêm Google sign-in login surface cho BE/BFF contract và internal BE verify path, đồng thời giữ session/consent response canonical.
- Affected docs: `project-spec/frontend-backend-contract.md` phải ghi rõ FE/BFF flow cho `Sign in with Google` button, Google One Tap, credential relay, và error behavior.
- Security: token verification phải thực hiện ở server side; FE/BFF không được giữ Google secret hoặc tự chấp nhận claim chưa verify.
