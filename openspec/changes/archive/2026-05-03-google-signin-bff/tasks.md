## 1. Chốt contract BE/BFF và boundary nội bộ

- [x] 1.1 Cập nhật `project-spec/frontend-backend-contract.md` để ghi rõ FE chỉ làm việc qua BFF, button `Sign in with Google` là fallback bắt buộc, One Tap là enhancement, và cả hai đều gửi cùng một dạng `credential` / `ID token`.
- [x] 1.2 Chốt payload và error canonical cho luồng Google sign-in trong contract, bao gồm success session shape, token invalid/expired, và account conflict.
- [x] 1.3 Chốt boundary nội bộ của BE cho luồng Google verify để không để browser gọi trực tiếp vào backend public API.

## 2. Xây dựng Google token verification ở BE

- [x] 2.1 Thêm service/adapter để verify Google `ID token` ở server side, kiểm tra tối thiểu `sub`, chữ ký, `aud`, `iss`, `exp`, và `email_verified`.
- [x] 2.2 Thêm policy map account theo thứ tự canonical: match theo `google_id`, link theo verified email khi phù hợp, hoặc tạo user mới khi chưa có account.
- [x] 2.3 Trả lỗi rõ ràng khi credential không hợp lệ hoặc policy link account bị xung đột, không tự merge mơ hồ.

## 3. Gắn vào flow đăng nhập và session canonical

- [x] 3.1 Thêm route/view/service cho luồng Google login của BE để nhận credential từ BFF và trả kết quả đăng nhập canonical.
- [x] 3.2 Tạo/đồng bộ Django session canonical cho user đăng nhập Google, giữ `session_state`, `identity_type`, và `consent_state` cùng contract với login email/password.
- [x] 3.3 Giữ guest attach là flow riêng; Google login không tự động attach guest data hoặc chuyển ownership ngầm.

## 4. Test và kiểm chứng

- [x] 4.1 Thêm unit/regression tests cho token hợp lệ, token hết hạn, `aud` sai, `iss` sai, `google_id` đã link, link theo email verified, và conflict account.
- [x] 4.2 Thêm test cho contract error/status và canonical session response để FE/BFF có thể implement đúng từ spec.
- [x] 4.3 Chạy `manage.py check`, `ruff check`, và `pytest` cho phạm vi auth liên quan sau khi implementation xong.
