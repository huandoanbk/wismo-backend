## Context

Hiện tại `GuestIdentity.expires_at` là nullable và không được set khi tạo — guest không bao giờ tự hết hạn qua application logic. `mark_seen()` chỉ update `last_seen_at`, không extend `expires_at`. Hệ quả: một guest tồn tại vô thời hạn cho đến khi bị deactivate thủ công.

`mark_seen()` đang được gọi sai chỗ — tại `session_status()` và `resolve_bootstrap_identity()` (list/detail chat), là những action không được tính là guest activity theo spec.

Attach flow hiện tại là thủ công: sau khi verify OTP, FE phải gọi riêng `POST /api/accounts/guest/attach/` để transfer chat. Change này loại bỏ bước đó.

## Goals / Non-Goals

**Goals:**
- Guest có idle TTL 6h cố định, set khi tạo, sliding — extend mỗi khi guest gửi message
- `mark_seen()` là điểm duy nhất extend TTL, chỉ được trigger từ `POST /api/chat/message/` gate pipeline
- Verify OTP tự động attach guest chat (silent, không block verify nếu attach fail)
- Loại bỏ `GuestAttachView`, URL `guest/attach/`, không còn attach endpoint public

**Non-Goals:**
- Không thay đổi registered user session expiry
- Không trigger auto-attach khi login / Google login (chỉ OTP verify)
- Không thay đổi response shape của `VerifyEmailView` (attach là silent, không trả kết quả attach)
- Không thay đổi guest expiry khi accept consent, tạo chat shell, list chat, get detail, v.v.

## Decisions

### 1. Sliding TTL implement bằng cách sửa `mark_seen()`

`mark_seen()` được mở rộng để cập nhật cả `expires_at = now + WISMO_GUEST_IDLE_TTL_HOURS`. Không tạo method mới, vì `mark_seen()` đã là điểm duy nhất cần gọi — chỉ cần bổ sung semantics.

Thay thế cân nhắc: tạo method `refresh_ttl()` riêng. Loại bỏ vì không có lý do domain nào cần tách — `last_seen_at` và `expires_at` luôn được update cùng nhau trong sliding TTL logic.

### 2. `mark_seen()` chỉ được gọi từ gate `_resolve_identity()`

Gate pipeline `_resolve_identity()` là nơi duy nhất trong `POST /api/chat/message/` flow resolve guest identity. Gọi `mark_seen()` tại đây đảm bảo TTL được refresh đúng khi user gửi message, bất kể gate pass hay fail.

Loại bỏ `mark_seen()` khỏi:
- `IdentityService.resolve_for_gate()` — vì được gọi từ nhiều nơi khác nhau, không chỉ chat gate
- `IdentityService.session_status()` — page load, không phải guest activity
- `ChatContextService.resolve_bootstrap_identity()` — list/detail chat, không phải guest activity

### 3. Auto-attach trong `VerifyEmailView` là best-effort, không block verify

Nếu attach fail (guest không còn eligible, IntegrityError, v.v.), verify vẫn thành công. Attach failure chỉ được log, không raise ra FE. Lý do: verify email là critical path — không để attach side effect làm hỏng verify flow.

`GuestAttachService.attach_current_case()` được dùng lại nội bộ. View không expose result attach — response shape không đổi.

### 4. Clear `wismo_guest` cookie trong verify response khi attach thành công

Chỉ clear khi attach thực sự xảy ra (guest có eligible chat và attach không raise). Nếu guest không có eligible chat (không có chat, chat đã archived, v.v.), không clear cookie — guest session vẫn valid và user vẫn là guest cho đến khi login.

### 5. `WISMO_GUEST_IDLE_TTL_HOURS` trong `.env`, đọc qua `settings`

Consistent với pattern hiện tại của project (`WISMO_OTP_TTL_MINUTES`, v.v.). Default = 6.

## Risks / Trade-offs

**[Risk] Attach fail silently có thể làm mất chat guest nếu guest expire trước khi user login** → Mitigation: log warning rõ khi attach fail để monitor; guest TTL 6h đủ dài cho user hoàn tất flow verify → login trong cùng session.

**[Risk] `mark_seen()` gọi trong gate `_resolve_identity()` kể cả khi gate fail** → Accepted: owner đã confirm — khi user gửi prompt là tính activity, bất kể gate pass hay fail.

**[Risk] Xóa `guest/attach/` endpoint breaking change cho FE đang dùng** → Mitigation: cập nhật `frontend-backend-contract.md` rõ endpoint bị xóa; FE không cần gọi nữa vì BE tự attach.

## Migration Plan

1. Deploy BE với `WISMO_GUEST_IDLE_TTL_HOURS=6` trong `.env`
2. Guest cũ không có `expires_at` vẫn hoạt động bình thường (`is_guest_valid()` kiểm tra `expires_at is None` → valid)
3. Guest mới tạo từ đây sẽ có `expires_at` — sliding TTL active
4. Không cần data migration — guest cũ với `expires_at=None` dần tự deactivate theo policy hoặc cleanup job (ngoài scope change này)
5. FE phải bỏ call `POST /api/accounts/guest/attach/` trước khi BE deploy (hoặc chấp nhận 404 tạm thời)
