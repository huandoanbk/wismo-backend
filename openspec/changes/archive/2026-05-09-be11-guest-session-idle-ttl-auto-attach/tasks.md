## 1. Settings — WISMO_GUEST_IDLE_TTL_HOURS

- [x] 1.1 Thêm `WISMO_GUEST_IDLE_TTL_HOURS` vào `.env.example` với value `6`
- [x] 1.2 Đọc `WISMO_GUEST_IDLE_TTL_HOURS` từ `.env` trong `settings.py` (int, default=6)

## 2. Model — GuestIdentity.mark_seen() refresh expires_at

- [x] 2.1 Sửa `GuestIdentity.mark_seen()` trong `accounts/models.py` để update cả `last_seen_at = now` và `expires_at = now + timedelta(hours=settings.WISMO_GUEST_IDLE_TTL_HOURS)` trong cùng một `save(update_fields=[...])`

## 3. Service — create_guest() set expires_at

- [x] 3.1 Sửa `IdentityService.create_guest()` trong `accounts/services.py` để set `expires_at = now + timedelta(hours=settings.WISMO_GUEST_IDLE_TTL_HOURS)` khi tạo `GuestIdentity`

## 4. Service — bỏ mark_seen() sai chỗ

- [x] 4.1 Xóa `guest.mark_seen()` khỏi `IdentityService.resolve_for_gate()` trong `accounts/services.py` (gate pipeline sẽ gọi trực tiếp)
- [x] 4.2 Xóa `guest.mark_seen()` khỏi `IdentityService.session_status()` trong `accounts/services.py`
- [x] 4.3 Xóa `guest.mark_seen()` khỏi `ChatContextService.resolve_bootstrap_identity()` trong `chat/services.py`

## 5. Gate — mark_seen() tại _check_session() pass

- [x] 5.1 Sửa `RequestGatePipeline.run()` trong `runtime/request_gate.py`: sau khi `_check_session()` pass với guest hợp lệ, gọi `identity.guest_identity.mark_seen()` trước khi tiếp tục. Note: đặt sau session check (không trước) để tránh refresh TTL của guest đã expired.

## 6. View — VerifyEmailView silent auto-attach

- [x] 6.1 Sửa `VerifyEmailView.post()` trong `accounts/views.py`: sau khi `verify_email()` thành công, kiểm tra `wismo_guest` cookie trong request; nếu có guest hợp lệ với eligible chat, gọi `GuestAttachService().attach_current_case()` và clear `wismo_guest` cookie trong response; wrap trong try/except để không block verify nếu attach fail; log warning nếu fail
- [x] 6.2 Xóa `GuestAttachView` class khỏi `accounts/views.py`
- [x] 6.3 Xóa import dead sau khi `GuestAttachView` bị xóa khỏi `accounts/views.py`: xóa `GUEST_IDENTITY_NOT_RESOLVED` và `SESSION_REQUIRED` khỏi dòng import `wismo.contracts.codes` (chỉ giữ lại `INVALID_REQUEST`)
- [x] 6.4 Sửa module docstring dòng 1 của `accounts/views.py`: bỏ "and attach" khỏi `"""Account, guest, OTP auth, session, and attach API views."""`

## 7. URLs — xóa guest/attach/ route

- [x] 7.1 Xóa `path("guest/attach/", GuestAttachView.as_view(), name="guest-attach")` khỏi `accounts/urls.py`
- [x] 7.2 Xóa import `GuestAttachView` khỏi `accounts/urls.py`

## 8. Contract — frontend-backend-contract.md

- [x] 8.1 Replace toàn bộ section `POST /api/accounts/verify-email/` trong `project-spec/frontend-backend-contract.md` với nội dung mới ghi rõ silent auto-attach behavior: nếu guest cookie hợp lệ có eligible chat, BE tự động attach và clear cookie trong cùng response; response shape không đổi
- [x] 8.2 Xóa hoàn toàn section `POST /api/accounts/guest/attach/` khỏi `project-spec/frontend-backend-contract.md`
- [x] 8.3 Replace section `POST /api/accounts/guest/init/` trong `project-spec/frontend-backend-contract.md` để ghi rõ guest được tạo với `expires_at = now + WISMO_GUEST_IDLE_TTL_HOURS` (không còn nullable mặc định)

## 9. Tests — guest lifecycle

- [x] 9.1 Cập nhật test `create_guest` trong `tests/unit/test_identity_consent_auth.py`: xác nhận `guest.expires_at` không phải `None` sau khi tạo
- [x] 9.2 Thêm test: `mark_seen()` update cả `last_seen_at` và `expires_at`
- [x] 9.3 Thêm test: `session_status()` không gọi `mark_seen()` (verify `last_seen_at` và `expires_at` không thay đổi sau khi gọi `session_status`)
- [x] 9.4 Thêm test: `resolve_bootstrap_identity()` không gọi `mark_seen()`

## 10. Tests — gate mark_seen

- [x] 10.1 Thêm test trong `tests/unit/test_identity_consent_auth.py`: gate pipeline gọi `mark_seen()` khi guest resolve được từ `POST /api/chat/message/`, kể cả khi gate fail ở bước tiếp theo (ví dụ: `consent_required`)
- [x] 10.2 Xác nhận `expires_at` của guest được update sau khi gate pipeline chạy dù gate fail

## 11. Tests — verify OTP auto-attach

- [x] 11.1 Thêm test: `VerifyEmailView` auto-attach guest chat khi guest cookie hợp lệ có eligible chat, xác nhận chat chuyển sang user và cookie được clear
- [x] 11.2 Thêm test: `VerifyEmailView` vẫn trả 200 khi guest không có eligible chat (không attach, không clear cookie)
- [x] 11.3 Thêm test: `VerifyEmailView` vẫn trả 200 khi `GuestAttachService.attach_current_case()` raise exception (attach fail không block verify)

## 12. Tests — xóa guest/attach/ endpoint

- [x] 12.1 Xóa `test_attach_success_transfers_guest_case_and_requires_reconsent` và `test_attach_failure_preserves_guest_ownership_and_cookie` khỏi `tests/unit/test_identity_consent_auth.py` (2 test này dùng URL `guest/attach/` đã bị xóa)
- [x] 12.2 Xác nhận `GuestAttachService.attach_current_case()` vẫn hoạt động đúng như internal service thông qua test auto-attach trong task 11.1

## 13. Verification tổng thể

- [x] 13.1 Chạy `pytest tests/unit/test_identity_consent_auth.py tests/unit/test_request_gate_sse.py -q` và xác nhận tất cả pass
- [x] 13.2 Chạy `pytest -q` để xác nhận không có regression (103 passed)
- [x] 13.3 Chạy `ruff check accounts/models.py accounts/services.py accounts/views.py accounts/urls.py chat/services.py runtime/request_gate.py`
- [x] 13.4 Chạy `python manage.py check` và `python manage.py makemigrations --check --dry-run` (expect no changes)
- [x] 13.5 Cập nhật `agent-progress.md` với BE-11 completion
