## 1. Quyết định trước khi code

- [x] 1.1 Chốt với Owner các giá trị OTP MVP: 6 chữ số, TTL 30 phút, resend cooldown 60 giây, resend cap 5 lần.
- [x] 1.2 Chốt với Owner verify OTP xong FE sẽ gọi login riêng, không auto-login.
- [x] 1.3 Chốt với Owner attach guest chat sang account là endpoint riêng sau login.
- [x] 1.4 Chốt với Owner registered account dùng quota window mới, không transfer/copy quota guest.
- [x] 1.5 Chốt với Owner attach cả `Case` của current guest chat theo rule đơn giản nhất.

## 2. Contract và API surface

- [x] 2.1 Cập nhật `project-spec/frontend-backend-contract.md` cho session state, consent state, identity metadata, cookie/header behavior, và error envelope.
- [x] 2.2 Ghi contract cho `POST /api/accounts/guest/init/` và compatibility route nếu giữ `POST /api/chat/guest/init/`.
- [x] 2.3 Ghi contract cho `GET /api/accounts/session/`.
- [x] 2.4 Ghi contract cho `POST /api/consents/accept/` và `GET /api/consents/status/`.
- [x] 2.5 Ghi contract cho `POST /api/accounts/register/`, `POST /api/accounts/verify-email/`, `POST /api/accounts/resend-otp/`, `POST /api/accounts/login/`, và `POST /api/accounts/logout/`.
- [x] 2.6 Ghi contract cho `POST /api/accounts/guest/attach/`, gồm success response, clear cookie behavior, re-consent requirement, và failure behavior.

## 3. Accounts service layer

- [x] 3.1 Thêm `accounts.services` cho guest init/resolve, session status, register, OTP generation/hash/check, resend OTP, login, logout.
- [x] 3.2 Thêm settings cho OTP length, TTL, resend cooldown, resend cap, và email subject/from behavior nếu cần.
- [x] 3.3 Dùng Django email backend để gửi OTP, không trả OTP hoặc secret material trong API response.
- [x] 3.4 Đảm bảo unverified user không tạo registered session và login unverified trả `email_verification_required`.
- [x] 3.5 Thêm attach service atomic để transfer attached case, guest-owned chats trong case đó, và related turns từ guest identity hiện tại sang registered user, không cross guest identity boundary.
- [x] 3.6 Đảm bảo attach không transfer/copy quota guest và tạo/đọc quota window registered mới theo policy khi user chat tiếp.
- [x] 3.7 Nếu schema hiện có thiếu field correctness, tạo migration nhỏ tương ứng và không sửa migration cũ.

## 4. Consent service layer

- [x] 4.1 Mở rộng `ConsentService` để trả consent state canonical: `unknown`, `required`, `accepted`.
- [x] 4.2 Thêm consent status behavior cho guest/user hiện tại.
- [x] 4.3 Đảm bảo revoked hoặc `reconsent_required = true` được coi là `required`.

## 5. Views, URLs, serializers/contracts trong code

- [x] 5.1 Thêm DRF serializers cho request/response auth, OTP, session, consent nếu project pattern yêu cầu.
- [x] 5.2 Thêm accounts endpoints và URL routes theo contract.
- [x] 5.3 Di chuyển hoặc alias guest init về accounts domain mà không phá route foundation hiện có nếu cần.
- [x] 5.4 Thêm consent status endpoint và chuẩn hóa response/error shape của consent accept.
- [x] 5.5 Thêm attach endpoint riêng sau login và chỉ clear guest cookie sau transaction attach thành công.
- [x] 5.6 Cập nhật `RequestGatePipeline` để dùng service boundary cho resolve identity/session/consent nếu cần và giữ đúng thứ tự gate hiện tại.

## 6. Tests

- [x] 6.1 Thêm API tests cho guest init và session status guest/unauthenticated/expired.
- [x] 6.2 Thêm API tests cho consent accept/status của guest và registered user.
- [x] 6.3 Thêm service/API tests cho register tạo OTP hash, không expose OTP, và duplicate verified/unverified email behavior.
- [x] 6.4 Thêm tests cho verify OTP success, invalid OTP, expired OTP, và resend OTP cooldown/cap.
- [x] 6.5 Thêm tests cho login verified, login unverified, invalid credentials, và logout.
- [x] 6.6 Thêm tests cho attach success, attach failure không đổi ownership, attach từ chối `chat_id` không thuộc guest identity hiện tại, clear cookie sau success, re-consent required sau attach, và quota registered mới.
- [x] 6.7 Thêm regression tests request gate cho identity not resolved, guest expired, consent required, và accepted consent pass-through.

## 7. Verification và handoff

- [x] 7.1 Chạy `./.venv/bin/python manage.py makemigrations --check --dry-run` hoặc tạo migration nếu có model change.
- [x] 7.2 Chạy `./.venv/bin/python manage.py migrate --database=default` nếu có migration mới và DB local sẵn sàng.
- [x] 7.3 Chạy test liên quan và toàn bộ `./.venv/bin/pytest`.
- [x] 7.4 Chạy `ruff` theo project tooling nếu có cấu hình/lệnh khả dụng.
- [x] 7.5 Cập nhật `agent-progress.md` với phần hoàn thành của change.
- [x] 7.6 Cập nhật `tech-debt.md` nếu phát hiện vấn đề ngoài scope; nếu không, báo rõ không cập nhật.
