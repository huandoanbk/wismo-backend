## Context

BE-6 nằm ngay trước lớp Request Gate và quota-related runtime work, nên thay đổi này phải khóa nguồn truth cho config và quota trước khi runtime đi sâu hơn.

Hiện trạng liên quan trong repo:
- `admin_config.models.RuntimeConfig` đã tồn tại để lưu key/value config do admin quản lý.
- `runtime.models.UsageQuotaWindow` đã tồn tại để giữ token quota state theo identity.
- `runtime.request_gate` và `runtime.orchestrator` đã đọc quota window trực tiếp, nhưng chưa có service boundary riêng cho config/quota policy.
- `project-spec/WISMO_MVP_Spec.md` và `project-spec/WISMO_BE_Implementation_Plan.md` đã chốt quota theo token, quota window theo thời gian, và behavior `pending_input_text` khi quota exhausted.
- `pending_input_limits` cũng sẽ được quản lý bởi `RuntimeConfig`, vì giới hạn recovery UX vẫn nên có nguồn truth admin-controlled thay vì hardcode rải rác.

### Spec References

- `project-spec/WISMO_MVP_Spec.md`
- `project-spec/WISMO_BE_Implementation_Plan.md`
- `project-spec/frontend-backend-contract.md`
- `openspec/specs/chat-request-gate/spec.md`
- `openspec/specs/identity-consent-auth/spec.md`

### Canonical config shapes

- `runtime.input_limits`:
  - `max_message_length_chars: 8000`
  - `max_payload_bytes: 65536`
- `quota.guest_policy`:
  - `token_limit: 100000`
  - `window_seconds: 86400`
- `quota.user_policy`:
  - `token_limit: 1000000`
  - `window_seconds: 86400`
- `quota.pending_input_limits`:
  - `max_appends: 10`
  - `max_chars: 12000`

## Goals / Non-Goals

**Goals:**
- Có lớp lookup canonical cho runtime config để các runtime consumer dùng chung một nguồn truth cho limit/policy.
- Có lớp lookup canonical cho `pending_input_limits` để quota-exhausted path dùng cùng cơ chế admin-controlled như các limit khác.
- Có boundary quota window rõ ràng cho guest/user, bao gồm resolve current window, rollover theo thời gian, và exhausted state.
- Giữ `pending_input_text` và `pending_input_updated_at` như side effect tối thiểu khi quota bị chặn.
- Giảm hardcode trong Request Gate và Step 12 bằng cách đi qua service boundary thay vì query rời rạc.
- Giữ behavior deterministic cho môi trường mới cài đặt bằng foundation defaults rõ ràng.

**Non-Goals:**
- Không mở rộng sang LLM Gateway, model routing, hay usage finalization chi tiết của Step 12.
- Không thêm public API mới cho runtime config trong BE-6.
- Không thêm Redis/Celery/background job cho quota rollover.
- Không đổi semantics guest attach hay consent/auth flow.

## Decisions

1. **Giữ `RuntimeConfig` dạng generic key/value thay vì tách thành nhiều bảng cấu hình riêng.**
   - Lý do: model hiện có đã phù hợp cho admin-controlled limits, feature flags, và rollout rules; tách bảng riêng sẽ làm change nặng hơn mà chưa có nhu cầu rõ ràng.
   - Alternatives considered:
     - Tạo bảng chuyên biệt cho quota limits: loại này mạnh về schema nhưng cứng và khó mở rộng.
     - Hardcode trong `settings.py`: nhanh nhưng không đáp ứng nhu cầu admin-controlled trong MVP.

2. **Đặt consumer-facing service boundary trong `runtime`, còn `admin_config` chỉ giữ storage/admin cho config records.**
   - Lý do: runtime là nơi cần đọc config/quota để gate request và chốt usage. Một boundary ở runtime giúp `request_gate` và `orchestrator` dùng cùng contract.
   - Alternatives considered:
     - Đặt service trong `admin_config`: hợp với storage nhưng không tự nhiên với runtime consumers.
     - Để các caller query ORM trực tiếp: dễ gây lệch logic và hardcode policy ở nhiều nơi.

3. **Dùng deterministic foundation defaults khi config active chưa có hoặc chưa được seed.**
   - Lý do: fresh environment vẫn phải chạy được gate/quota path mà không phụ thuộc dữ liệu thủ công.
   - Alternatives considered:
     - Fail hard khi thiếu config: an toàn về mặt strictness nhưng kém thực dụng cho MVP foundation.
     - Suy diễn default từ caller: dẫn tới behavior phân mảnh.
   - Áp dụng cho cả `pending_input_limits`, không chỉ quota limit/window.

4. **Resolve current quota window lazily theo identity và roll forward khi window cũ đã hết hạn.**
   - Lý do: không cần job nền chỉ để rotate window; read path đủ để giữ state đúng cho MVP.
   - Alternatives considered:
     - Cron/background rotation: tạo thêm operational surface không cần thiết ở giai đoạn này.
     - Chỉ reset khi Step 12 chạy: quá muộn cho gate path.

5. **Giữ quota update atomic bằng transaction và row-level lock tại service layer.**
   - Lý do: quota accounting là state nhạy cảm; cần tránh race giữa nhiều turn/song song request.
   - Alternatives considered:
     - Optimistic update không lock: dễ đơn giản hơn nhưng có rủi ro double-consume hoặc stale exhaustion state.

6. **Không tạo schema mới trong BE-6 nếu `RuntimeConfig` và `UsageQuotaWindow` hiện tại đã đủ trường.**
   - Lý do: hiện tại model đã có `token_limit`, `used_tokens`, `is_exhausted`, `window_started_at`, `window_ends_at`, và pending input fields cần thiết cho foundation.
   - Alternatives considered:
     - Thêm bảng policy riêng: chỉ cần thiết nếu runtime config generic không đủ, hiện chưa có dấu hiệu đó.

## Risks / Trade-offs

- [Risk] Default runtime config có thể lệch với giá trị admin mong muốn → Mitigation: seed tests rõ ràng và giữ defaults trong một service duy nhất.
- [Risk] Query config/quota trên request path tăng số lần đọc DB → Mitigation: chấp nhận cho MVP foundation, tối ưu sau khi behavior đã ổn định.
- [Risk] Window rollover theo thời gian dễ lệch timezone → Mitigation: dùng timezone-aware datetime và so sánh nhất quán trên server.
- [Risk] `pending_input_text` phình to nếu quota bị chặn nhiều lần → Mitigation: quản lý bounds bằng `RuntimeConfig` và giữ append behavior bounded.

## Migration Plan

1. Giữ nguyên schema hiện tại nếu không cần thêm field mới.
2. Thêm service boundary cho runtime config lookup và quota window lifecycle.
3. Wire Request Gate và Step 12 sang service boundary đó thay vì gọi ORM rời rạc.
4. Thêm regression tests cho lookup/default/rollover/exhaustion behavior.
5. Nếu cần rollback, revert service wiring và test changes; dữ liệu quota/config hiện có vẫn giữ nguyên.

## Open Questions

- BE-6 có cần một admin-only endpoint để xem runtime config/quota policy, hay Django admin là đủ cho MVP?
