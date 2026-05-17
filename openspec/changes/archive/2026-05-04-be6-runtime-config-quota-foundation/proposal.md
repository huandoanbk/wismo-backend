## Why

BE-6 cần chốt lớp cấu hình runtime và nền quota tối thiểu trước khi Request Gate và Step 12 mở rộng thêm. Hiện repo đã có `RuntimeConfig` và `UsageQuotaWindow`, nhưng chưa có một capability/spec riêng xác định nguồn truth canonical cho limit, window, policy guest/user, và hành vi quota exhausted theo cách mà các sprint runtime sau có thể dùng lại mà không phải hardcode hoặc suy diễn từng nơi một.

## What Changes

- Xác lập capability canonical cho runtime config và quota foundation trước Request Gate.
- Chuẩn hóa nguồn cấu hình cho `max input length`, `payload size`, quota limit, quota window length, guest/user quota policy, và pending input limits.
- Chốt canonical key/value shape cho từng record `RuntimeConfig` để admin/config lookup không phải suy diễn schema tại runtime.
- Chuẩn hóa `UsageQuotaWindow` như state nền cho mỗi identity, bao gồm current window lookup, exhausted state, và pending input persistence khi quota đã hết.
- Đặt service boundary để Request Gate và Step 12 chỉ đọc quota/config qua lớp lookup chung, không query rời rạc hoặc hardcode limit trong runtime path.
- Giữ hành vi quota error đã có sẵn cho runtime phía sau sử dụng nhất quán, gồm `registration_required_by_quota` và `quota_exceeded`.
- Bổ sung regression coverage cho lookup/policy/exhaustion behavior để foundation này ổn định trước khi sang runtime sâu hơn.

## Capabilities

### New Capabilities
- `runtime-config-quota-foundation`: Cấu hình runtime canonical và nền quota token cho guest/user, gồm lookup policy, quota window state, và exhausted/pending-input behavior.

### Modified Capabilities
- None.

## Impact

- `runtime`, `admin_config`, `accounts`, `chat`: thêm service lookup/policy boundary và dùng lại quota window canonical.
- `project-spec/WISMO_BE_Implementation_Plan.md` và `project-spec/frontend-backend-contract.md`: chỉ cần cập nhật nếu cần làm rõ behavior exposed cho quota errors hoặc config-driven limits.
- Test suite: unit/regression coverage cho runtime config lookup, quota window resolution, quota exhaustion side effects, và gate/read path.
- Dependencies: không thêm external dependency mới; tiếp tục dùng Django ORM và PostgreSQL.
