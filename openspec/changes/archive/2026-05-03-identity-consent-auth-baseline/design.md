## Spec References

- `project-spec/WISMO_MVP_Spec.md`
  - A.4.1 Guest user
  - A.4.2 Registered user
  - A.4.3 Đăng ký bằng email và mật khẩu
  - A.4.5 Flow attach guest
  - A.6.2.2 Flow chuẩn của một chat turn, Step 2 Request gate
- `project-spec/WISMO_BE_Implementation_Plan.md`
  - C.3 Backend module boundary tối thiểu
  - C.4.1 Identity và consent
  - C.6 Request gate tối thiểu
- `project-spec/WISMO_FE_Implementation_Plan.md`
  - D.3.1 Vai trò của Frontend-Backend Contract
  - D.7.1 SessionState
  - D.7.2 ConsentState
  - FE-4 Auth / guest / attach flow shell
- `project-spec/frontend-backend-contract.md`

## Context

Foundation hiện có `User`, `GuestIdentity`, `ConsentRecord`, session authentication, `GuestInitView`, `ConsentAcceptView`, và `RequestGatePipeline` skeleton. Tuy nhiên account endpoints chưa tồn tại, consent status chưa có contract, `frontend-backend-contract.md` đang trống, và OTP verification chưa được implement.

MVP spec yêu cầu guest có thể chat sau consent, registered user có continuity bền vững, và email/password registration phải verify email trước khi account trở thành registered chat identity hoạt động. Owner đã chốt dùng OTP cho MVP, không dùng verification link.

Request gate cần dựa trên trạng thái identity/session/consent đã chuẩn hóa. Vì vậy change này xây trước lớp identity/consent/auth contract để các sprint request gate và runtime sau không phải đoán trạng thái session từ endpoint rời rạc.

## Goals / Non-Goals

**Goals:**

- Cung cấp API baseline cho guest init, session status, consent accept/status, register, verify OTP, resend OTP, login, logout.
- Dùng Django session auth làm cơ chế registered session canonical.
- Dùng guest cookie `wismo_guest` làm guest identity canonical; tiếp tục hỗ trợ `X-Guest-Token` cho BFF/test request.
- Đảm bảo unverified email account không được login và không được dùng làm registered chat identity.
- Cập nhật `project-spec/frontend-backend-contract.md` để FE/BFF có source of truth cho payload, response, cookie, session state, consent state, và error codes.
- Thêm tests cho API/service behavior chính và các nhánh gate liên quan identity/session/consent.

**Non-Goals:**

- Không triển khai Google OAuth trong change này.
- Không tự động transfer guest chat trong login nếu chưa có explicit attach contract.
- Không triển khai full attach nâng cao cho toàn bộ guest history; scope attach của change này chỉ là current guest chat/case handoff tối thiểu.
- Không triển khai verification link.
- Không triển khai password reset, account deletion, privacy settings, hoặc profile settings.
- Không triển khai production email provider cụ thể ngoài Django email interface/config hiện có.
- Không triển khai request gate đầy đủ cho quota/idempotency/chat ownership ngoài phần integration cần để không lệch identity/consent.

## Decisions

### 1. Email verification dùng OTP, không dùng link

MVP sẽ dùng OTP numeric qua email vì Owner đã chốt hướng này và model foundation đã có các field `email_otp_hash`, `email_otp_expires_at`, `email_otp_sent_at`, `resend_count`.

Alternatives considered:
- Verification link: loại khỏi change này vì phức tạp hơn về signed token URL, redirect, BFF callback, và UX deep link.
- Lưu OTP plaintext: không dùng vì nếu DB bị đọc thì OTP còn hiệu lực bị lộ.

Implementation direction:
- Generate OTP bằng `secrets`.
- Store OTP bằng Django password hash (`make_password` / `check_password`) hoặc hash tương đương có salt.
- Không trả OTP trong API response.
- Send OTP bằng `django.core.mail.send_mail`.
- Dev/test dùng Django email backend cấu hình qua settings; tests dùng locmem/mail outbox.

MVP đề xuất:
- OTP length: 6 chữ số.
- OTP TTL: 30 phút.
- Resend cooldown: 60 giây.
- Resend cap: tối đa 5 lần cho một unverified account trước khi cần Owner/operator reset hoặc register flow tạo lại theo policy.

Các giá trị này đã được Owner chốt cho MVP và implement nên đặt thành settings để có thể chỉnh mà không đổi schema.

### 2. Register và verify OTP không tạo registered chat session

`POST /api/accounts/register/` tạo hoặc cập nhật account chưa verified và gửi OTP, nhưng không login user vào Django session. Account chỉ trở thành registered chat identity sau khi `email_verified = true` và login thành công.

Rationale:
- Bám spec: email verification là bắt buộc trước khi account trở thành registered chat identity hoạt động.
- Tránh trạng thái authenticated-but-not-chat-eligible trong request gate.

Alternatives considered:
- Auto-login ngay sau register với state `pending_email_verification`: tăng complexity vì request gate/session status phải xử lý thêm authenticated unverified state.
- Auto-login sau verify OTP: UX mượt hơn nhưng cần chốt thêm session handoff với guest cookie và CSRF behavior. Change này ưu tiên contract đơn giản: verify xong thì FE gọi login.

Owner đã chốt: sau verify OTP, FE sẽ gọi login riêng.

### 3. Login chỉ cho user active và email verified

`POST /api/accounts/login/` dùng email/password. Nếu password đúng nhưng email chưa verified, backend trả `email_verification_required` và không tạo session.

Rationale:
- Giữ invariant registered session là chat-eligible identity.
- Request gate có thể xem authenticated user là registered identity hợp lệ mà không cần branch phức tạp.

### 4. Session status là endpoint canonical cho FE/BFF

`GET /api/accounts/session/` trả canonical state:
- `session_state`: `unauthenticated`, `guest`, `registered`, hoặc `expired`;
- `identity_type`: `none`, `guest`, hoặc `user`;
- `consent_state`: `unknown`, `required`, hoặc `accepted`;
- identity metadata tối thiểu.

Rationale:
- FE plan yêu cầu FE không tự suy đoán session/consent từ local state.
- Request gate error không phải endpoint duy nhất để FE biết trạng thái UI ban đầu.

### 5. Guest identity thuộc `accounts`, không thuộc `chat`

Canonical route mới nên đặt trong `accounts`, ví dụ `POST /api/accounts/guest/init/`. Route cũ `POST /api/chat/guest/init/` có thể giữ tạm như compatibility alias trong implementation nếu thấy cần tránh phá foundation tests/dev usage.

Rationale:
- Guest identity là domain của `accounts`, không phải chat persistence.
- Route rõ domain giúp FE/BFF và request gate dùng cùng identity boundary.

### 6. Guest cookie không được clear trước khi attach thành công

Guest cookie cũ liên quan trực tiếp tới dữ liệu chat guest: nó là bằng chứng để backend resolve guest identity đang sở hữu `chat_id` hiện tại. Nếu user login registered trong khi vẫn có guest chat hiện tại, backend có hai identity:

- registered user session: account vừa login;
- guest cookie: owner hiện tại của chat/case/turn guest.

Vì vậy login thành công không tự làm `chat_id` guest thuộc account. Muốn account mới tiếp tục đúng chat đó thì phải có attach flow atomic:

```text
guest cookie + registered session + current chat_id
  -> verify chat belongs to guest
  -> transfer allowed current conversation to user
  -> mark account requires re-consent if MVP policy requires
  -> clear guest cookie only after transfer succeeds
```

Nếu clear guest cookie ngay khi login nhưng chưa transfer ownership, account sẽ không pass chat ownership check cho `chat_id` guest. Nếu giữ guest cookie sau login nhưng không có attach contract, hệ thống có dual identity ambiguity.

Rationale:
- Bám MVP spec: attach phải atomic, chỉ attach cuộc trò chuyện guest hiện tại, nếu attach fail thì conversation vẫn thuộc guest, và sau attach thành công account phải re-consent trước khi chat tiếp.
- Không tự suy diễn rằng login đồng nghĩa ownership transfer.

Owner decisions:
- Attach dùng endpoint riêng sau login, ví dụ `POST /api/accounts/guest/attach/` với `chat_id`.
- Registered account dùng quota window mới; không transfer/copy quota guest đã dùng.
- Attach cả `Case` của current guest chat theo rule đơn giản nhất.

Boundary clarification:
- `Case` không được share qua nhiều guest identity. Một `Case` luôn thuộc đúng một owner identity theo schema foundation.
- Trong change này, "attach cả `Case`" nghĩa là transfer `Case` đang gắn với current guest `chat_id`, cùng các `Chat`/`ChatTurn` thuộc `Case` đó trong guest identity hiện tại, sang registered user hiện tại.
- Implementation không được transfer dữ liệu thuộc guest identity khác.

Attach endpoint behavior:
- Requires authenticated verified registered session.
- Requires valid guest cookie/header resolving the guest owner.
- Requires `chat_id` that belongs to that guest identity.
- Runs in a DB transaction.
- Transfers the attached `Case`, its guest-owned `Chat` rows, and related `ChatTurn` rows from the current guest identity to the registered user.
- Clears guest ownership fields from transferred rows and keeps owner fields consistent across transferred chat/case/turn rows.
- Marks registered user consent as required after attach, because MVP spec requires re-consent before continuing chat as registered account after attach.
- Clears `wismo_guest` cookie only after transaction succeeds.
- If attach fails, leaves conversation owned by guest and does not clear guest cookie.

### 7. Consent status/accept dùng service boundary

`ConsentService` sẽ expose read/write behavior cho consent state. `RequestGatePipeline` không tự query sâu ngoài boundary nếu service đã có method phù hợp.

Rationale:
- Consent logic có `CURRENT_VERSION`, `revoked_at`, `reconsent_required`; dùng service giúp endpoint và gate không lệch.

## Risks / Trade-offs

- [Risk] OTP email delivery ở dev/prod chưa có provider chắc chắn -> Mitigation: dùng Django email backend, không thêm provider dependency; cấu hình SMTP/console/locmem qua settings và test bằng locmem.
- [Risk] Resend cap/cooldown chưa được product spec khóa -> Mitigation: đặt giá trị trong settings, ghi rõ trong contract/design để Owner có thể đổi trước apply.
- [Risk] Register không auto-login có thể thêm một bước UX -> Mitigation: contract nêu rõ `next_action = "verify_email"` sau register và `next_action = "login"` sau verify; FE có flow rõ ràng.
- [Risk] Guest cookie bị clear trước attach khiến account không truy cập được `chat_id` guest hiện tại -> Mitigation: không clear guest cookie trong login nếu attach chưa chạy; chỉ clear sau attach atomic thành công.
- [Risk] Giữ guest cookie sau login nhưng chưa có attach contract gây dual identity ambiguity -> Mitigation: session resolve vẫn ưu tiên registered user cho runtime, còn attach endpoint/flow dùng explicit guest cookie + `chat_id` để transfer current conversation.
- [Risk] Attach logic nhầm owner boundary -> Mitigation: tests phải chứng minh attach chỉ nhận `chat_id` thuộc guest identity hiện tại, không transfer dữ liệu thuộc guest identity khác, và sau attach không còn owner state lệch giữa chat/case/turn được transfer.
- [Risk] Duplicate unverified account có thể gây account enumeration -> Mitigation: register/resend responses phải cân bằng giữa UX và enumeration risk; error chi tiết chỉ dùng khi cần cho FE flow, không trả OTP hoặc auth secret.

## Migration Plan

1. Dùng schema hiện có nếu đủ: `User` OTP fields, `GuestIdentity`, `ConsentRecord`.
2. Nếu thiếu field correctness khi implement, tạo migration nhỏ, không sửa migration cũ đã áp dụng.
3. Thêm endpoints dưới `accounts` và `consents`; giữ hoặc alias route cũ nếu cần.
4. Cập nhật `project-spec/frontend-backend-contract.md` cùng lúc với code.
5. Chạy migration check, pytest, ruff.
6. Rollback dev: revert code/migration của change; không cần data migration phức tạp vì foundation/dev schema còn mới.

## Open Questions

- None for this change before implementation.
