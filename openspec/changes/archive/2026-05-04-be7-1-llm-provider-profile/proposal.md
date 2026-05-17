## Why

BE-7 đã chốt gateway foundation và usage logging, nhưng cấu hình vẫn chưa tách rõ giữa “gateway config” và “LLM operation registry”. Điều này khiến operator chưa có một chỗ duy nhất để khai báo một gateway thật, rồi gán dần các `LLMOperation` vào gateway đó khi từng step LLM được triển khai. Change này chốt lại mô hình 2 bảng rõ ràng để việc khai báo, gán gateway, và mở rộng provider về sau không phải suy diễn ngầm.

## What Changes

- **BREAKING**: thêm bảng `LLMGatewayConfig` để operator khai báo gateway thật trong `/admin`, ví dụ `DeepInfra-Deepseek v3.1`, với integration kind, endpoint, model name, API key, params, và mode.
- **BREAKING**: thêm bảng `LLMOperation` để lưu các LLM use case/step operation, cho phép tạo dần trong quá trình phát triển và để `gateway` rỗng cho tới khi admin gán gateway phù hợp.
- **BREAKING**: `LLMOperation` được sinh dần theo tiến độ phát triển từng step có dùng LLM; runtime step chỉ cần refer registry entry, còn admin sẽ bind gateway sau.
- Gắn `LLMOperation` vào `LLMGatewayConfig` qua admin, để một operation có thể được đổi gateway mà không phải sửa runtime code.
- Buộc provider adapter phải tự serialize prompt theo wire contract của từng nhà cung cấp, thay vì giả định một prompt template chung cho mọi provider.
- **BREAKING**: `local_stub` không còn là gateway canonical cho production; nếu còn dùng thì chỉ ở dev/test adapter hoặc fixture.
- Giữ gateway contract normalized ở runtime layer, nhưng mapping provider sẽ đi qua `LLMGatewayConfig` và `LLMOperation` thay vì logic rải rác trong step code.
- Cập nhật admin/operator workflow để có thể khai báo gateway trước, rồi gán operation vào gateway sau.

## Capabilities

### New Capabilities
- `llm-gateway-routing`: Canonical gateway config và LLM operation registry cho LLM Gateway, gồm admin-managed gateway table, operation table, binding giữa operation và gateway, và provider-specific serialization boundary.

## Impact

- `llm_ops`: thay đổi model/config boundary, adapter registry, bootstrap/seed, admin forms, validation, và binding giữa gateway/operation.
- `runtime`: vẫn dùng gateway normalized, nhưng resolve qua `LLMOperation` rồi mới đi tới `LLMGatewayConfig`.
- `tests`: cần regression coverage cho gateway registration, operation registry, unbound operation fail-closed, provider-specific serialization, và removal của `local_stub` ở production config.
- `project-spec/frontend-backend-contract.md`: không cần thay đổi nếu runtime response/error contract không đổi.
