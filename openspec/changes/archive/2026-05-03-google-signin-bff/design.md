## Context

### Spec References
- `project-spec/WISMO_MVP_Spec.md` mục `A.4.4. Đăng nhập Google`
- `project-spec/WISMO_BE_Implementation_Plan.md` mục `C.4.1. Identity và consent` và `C.9.1. Sprint BE-1 — Foundation`
- `project-spec/frontend-backend-contract.md` hiện tại cho auth/session/guest attach
- `openspec/specs/identity-consent-auth/spec.md` để mở rộng auth surface hiện có

Repo hiện tại đã có `google_id` trên `User`, nhưng chưa có flow Google sign-in thật. Yêu cầu product là dùng Google One Tap và `Sign in with Google` button, trong khi FE nằm sau BFF nên không được để browser chạm vào backend nội bộ hoặc mang secret xuống client.
Change này thuộc repo BE: chỉ chốt backend behavior, BFF-facing contract, và nội bộ verify flow. Không triển khai FE/BFF code trong change này.

Google Identity Services có hai UX chính phù hợp với MVP:
- button sign-in, luôn hiển thị như fallback;
- One Tap, hiển thị khi browser/user đủ điều kiện.

Cả hai nên dùng chung một login surface và cùng trả về một Google `credential` / `ID token` để BFF chuyển nội bộ sang BE.

## Goals / Non-Goals

**Goals:**
- Hỗ trợ Google sign-in cho web với cả button và One Tap.
- Giữ `client_secret` và logic verify token ở server side.
- Để FE chỉ làm việc qua BFF public surface, không gọi BE public trực tiếp cho Google auth.
- Chốt backend contract để FE/BFF wire đúng mà không cần đổi kiến trúc client.
- Chốt policy account mapping: login theo `google_id`, link theo verified email khi phù hợp, và tạo user mới khi chưa có account.
- Cập nhật contract để FE/BFF biết rõ credential flow, cookie/session behavior, và error states.

**Non-Goals:**
- Không triển khai Google API access / Google Drive / Gmail scopes.
- Không triển khai OAuth authorization code flow cho mục tiêu gọi Google APIs.
- Không thay đổi guest attach thành auto-attach khi Google sign-in.
- Không thay đổi consent policy ngoài việc Google login phải đi qua cùng canonical session state.

## Decisions

### 1. Chọn Google Identity Services ID token flow cho sign-in

FE/BFF sẽ dùng Google Identity Services để render `Sign in with Google` button và One Tap prompt. Cả hai đường sẽ gửi `credential` / `ID token` đến một login endpoint của BFF.

Lý do:
- phù hợp với “đăng nhập” hơn là cấp quyền Google API;
- đơn giản hơn authorization code flow khi MVP không cần gọi Google APIs;
- BFF nhận token rồi chuyển nội bộ sang BE, nên không lộ secret.

Alternatives considered:
- Authorization Code Flow. Không chọn vì phức tạp hơn, chỉ phù hợp khi cần access token/refresh token để gọi Google APIs từ server.

### 2. BFF là public login surface, BE là internal verification surface

Browser chỉ gọi BFF public endpoint. BFF gọi BE nội bộ để verify token và tạo session canonical. Trong change này, BE chỉ cần cung cấp behavior/contract tương ứng; BFF implementation nằm ngoài scope repo này.

Lý do:
- giữ BE không exposed ra browser;
- phù hợp kiến trúc hiện có của repo là FE nằm sau BFF;
- cho phép FE triển khai Google UI mà không biết secret hoặc BE internals.

Alternatives considered:
- Để browser post thẳng vào BE public login endpoint. Không chọn vì user đã yêu cầu không lộ BE API ra ngoài FE/BFF surface.

### 3. Một token verification path cho cả button và One Tap

Cả button và One Tap sẽ submit cùng một dạng credential về cùng một login endpoint. Không tách hai flow ở BE.

Lý do:
- giảm số endpoint và giảm drift contract;
- FE/BFF chỉ cần render khác nhau, backend xử lý cùng một payload.

Alternatives considered:
- Tách riêng button flow và One Tap flow. Không chọn vì không có lợi cho backend và làm contract phức tạp hơn.

### 4. Account mapping policy ưu tiên `google_id`, sau đó verified email

Khi token đã verify:
- nếu `google_id` đã tồn tại, login user đó;
- nếu chưa có `google_id` nhưng email verified khớp một user hiện có, link `google_id` vào user đó rồi login;
- nếu chưa có user phù hợp, tạo user mới với `email_verified = true` và `google_id` từ Google;
- nếu token/email dẫn tới xung đột với một account đã được link khác, trả lỗi rõ ràng thay vì tự đoán.

Lý do:
- đây là policy MVP đơn giản nhưng vẫn đủ an toàn;
- tận dụng `google_id` unique hiện có trong schema;
- không bắt user phải tạo tài khoản riêng nếu đã có Google identity hợp lệ.

Alternatives considered:
- Chỉ login nếu đã có `google_id` khớp. Không chọn vì UX quá hẹp cho MVP.
- Tạo account mới mọi lần. Không chọn vì phá continuity và không tận dụng email verified.

### 5. Google sign-in không auto-attach guest

Google login chỉ tạo/đăng nhập registered session canonical. Nếu còn guest cookie, guest attach vẫn là bước riêng.

Lý do:
- giữ invariant hiện có của MVP: attach là endpoint riêng, ownership transfer phải explicit;
- tránh surprise data movement.

Alternatives considered:
- Tự động attach guest sau Google login. Không chọn vì sẽ phá contract attach hiện tại và tăng rủi ro ownership mismatch.

## Risks / Trade-offs

- [Risk] FE/BFF có thể triển khai One Tap nhưng không render button fallback. → Mitigation: contract phải ghi rõ button là bắt buộc, One Tap là enhancement.
- [Risk] Token verification sai audience/issuer có thể nhận nhầm credential. → Mitigation: verify signature, `aud`, `iss`, `exp`, và email verification state ở server.
- [Risk] Link theo verified email có thể xung đột với account email/password cũ. → Mitigation: chốt policy rõ trong spec và trả `google_account_conflict` thay vì tự merge mơ hồ.
- [Risk] Nếu BFF tự xử lý token mà không forward BE, secret/logic phân mảnh. → Mitigation: contract yêu cầu BFF chỉ là relay public surface, BE mới là canonical verifier.
- [Risk] Product có thể muốn auto-link guest sau Google login sau này. → Mitigation: giữ attach là flow riêng để có đường mở rộng an toàn, nhưng không làm trong change này.
