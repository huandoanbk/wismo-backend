## Context

BE-7 đã đưa gateway foundation vào trạng thái ổn định, nhưng mô hình config hiện chưa phân tách rõ giữa gateway config và operation registry. Người dùng muốn một cấu hình vận hành rõ ràng hơn: một bảng lưu gateway thật, một bảng lưu `LLMOperation`, và operation có thể được tạo dần theo tiến độ triển khai từng step LLM rồi gán gateway sau qua `/admin`.

Yêu cầu bổ sung quan trọng là provider prompt template/wire serialization không được giả định chung. OpenAI-compatible, Claude API, Azure OpenAI API và OpenAI/ChatGPT API có wire shape khác nhau ở tầng adapter; gateway chỉ giữ contract normalize cho caller.

## Goals / Non-Goals

**Goals:**
- Chốt một bảng gateway canonical để operator/admin khai báo provider thật trong `/admin`.
- Chốt một bảng `LLMOperation` canonical để dev tạo dần theo từng use case/step LLM.
- Cho phép operation chưa gán gateway tồn tại hợp lệ như một registry entry đang chờ cấu hình.
- Cho phép gateway/operation binding đổi trong admin mà không sửa runtime code.
- Giữ provider-specific serialization trong adapter boundary, không canonicalize prompt template ở mức một format chung cho mọi provider.
- Giữ runtime contract normalized ở gateway, không để caller phụ thuộc wire shape của vendor.
- Loại `local_stub` ra khỏi production canonical config.
- Giữ khả năng migrate từ BE-7 foundation hiện có sang model gateway/operation mới mà không phá toàn bộ runtime flow.

**Non-Goals:**
- Không đổi FE/API contract ngoài phần admin/runtime nội bộ nếu response của chat/runtime không đổi.
- Không xây dashboard provider riêng.
- Không thêm retry/fallback chiến lược phức tạp ngoài boundary adapter.
- Không mở rộng sang tool-calling/structured output đầy đủ cho mọi vendor nếu chưa có requirement riêng.

## Decisions

### 1. Dùng `LLMGatewayConfig` làm nguồn truth canonical cho provider runtime

Thay vì để operator khai báo provider config rời rạc hoặc gắn trực tiếp vào operation, hệ thống sẽ có một bảng gateway canonical chứa toàn bộ thông tin cần cho một gateway runtime:

- `name`
- `integration_kind`
- `endpoint` hoặc `base_url`
- `api_key_ref` hoặc credential reference
- `model_name` hoặc `deployment_name`
- `mode`
- `params`
- `is_active`

`LLMOperation` sẽ trỏ tới `LLMGatewayConfig` khi operation đã được bind.

**Alternatives considered**
- Giữ nguyên split supplier/model/config rồi thêm JSON phụ: loại vì vẫn khiến operator phải nghĩ theo nhiều record.
- Gộp tất cả vào `RuntimeConfig`: loại vì provider routing là boundary riêng của LLM gateway, không nên trộn vào runtime config tổng quát.

### 2. Dùng `LLMOperation` làm registry cho use case/step LLM

`LLMOperation` là registry canonical cho một loại LLM use case, ví dụ `LLM triage classifier light` hoặc `response_generation`. Dev có thể tạo operation này sớm trong quá trình phát triển, để `gateway` có thể để null cho tới lúc admin gán gateway phù hợp.

Đây là điểm quan trọng cho workflow thực tế: operation không phải một việc operator ngồi khai báo từ đầu cho mọi case, mà là một registry entry được bổ sung dần khi implementation từng step chạm tới LLM. Khi step mới cần LLM, dev sẽ thêm operation vào registry; sau đó operator/admin mới bind operation đó vào gateway tương ứng.

**Alternatives considered**
- Nhét mapping vào tên step trực tiếp: loại vì một step có thể có nhiều LLM operation.
- Chỉ lưu gateway, không có registry operation: loại vì làm mất chỗ admin/developer để khai báo use case trước khi bind provider.

### 3. Provider-specific prompt serialization nằm trong adapter, không trong gateway

Gateway chỉ giữ input normalized ở mức nội bộ, còn mỗi adapter sẽ tự render wire payload đúng với provider kind và mode. Điều này tránh việc dùng một template conversation kiểu OpenAI-compatible cho mọi vendor.

Các adapter phải cover ít nhất:
- OpenAI-compatible
- Anthropic native
- Azure OpenAI v1
- OpenAI native

**Alternatives considered**
- Ép tất cả provider về OpenAI-compatible wire format: loại vì Claude native và Azure không luôn parity hoàn toàn.
- Viết adapter riêng cho từng operation: loại vì tạo nhân bản logic và phá mục tiêu canonical profile.

### 4. Loại `local_stub` khỏi production canonical config

`local_stub` không còn là provider production canonical. Nếu cần dùng để test hoặc dev, nó chỉ tồn tại như adapter giả lập/fixture nội bộ, không phải profile operator sẽ chọn trong production.

Điều này tránh việc operator vô tình chọn một provider không thật khi đang cấu hình environment thật.

**Alternatives considered**
- Giữ `local_stub` như một provider bình thường: loại vì nó chỉ có giá trị deterministic cho dev/test.
- Xoá hẳn stub khỏi code ngay: loại vì test suite và local development vẫn cần một đường giả lập dễ kiểm soát.

### 5. Migration giữ hướng tiến dần, không yêu cầu rewrite runtime caller

Runtime callers vẫn gọi gateway normalized như hiện tại. Chỉ boundary config/adapter bên trong `llm_ops` thay đổi. Flow sẽ là: `step -> LLMOperation -> LLMGatewayConfig -> provider adapter`.

Migrations nên backfill gateway và operation registry từ cấu hình split hiện có để không bắt operator nhập lại toàn bộ bằng tay nếu không cần.

**Alternatives considered**
- Rewrite caller runtime để hiểu provider kind: loại vì caller không cần biết wire mode.
- Xoá sạch schema cũ và buộc nhập lại từ đầu: loại vì rủi ro vận hành cao hơn mức cần thiết.

## Risks / Trade-offs

- [Rủi ro] Migration từ split config sang gateway/operation registry có thể làm mất mapping nếu dữ liệu cũ không đầy đủ. → [Giảm thiểu] Backfill có kiểm tra tính hợp lệ và fail closed với record lỗi.
- [Rủi ro] Wire mode khác nhau giữa vendor có thể làm mất một số parameter riêng. → [Giảm thiểu] Giữ `params` mở rộng cho provider-specific overrides, chỉ normalize phần runtime cần.
- [Rủi ro] Một operation chưa bind gateway có thể bị quên và làm runtime fail. → [Giảm thiểu] Fail closed rõ ràng, và admin phải hiển thị operation chưa bind để operator xử lý.
- [Rủi ro] `local_stub` bị nhầm là production profile nếu không tách rõ. → [Giảm thiểu] Chỉ giữ nó như dev/test fixture hoặc adapter giả lập, không expose trong operator canonical path.

## Migration Plan

1. Thêm `LLMGatewayConfig` với các field canonical cho integration kind, endpoint, auth ref, model/deployment, mode, params, active state.
2. Thêm `LLMOperation` registry với `gateway` nullable để dev có thể tạo operation trước khi bind gateway.
3. Backfill gateway/operation từ cấu hình `LLMSupplier`/`LLMModel`/`LLMOperationConfig` hiện có.
4. Cập nhật gateway adapter registry để dispatch theo `integration_kind` và render wire payload theo provider kind.
5. Cập nhật admin/seed/dev bootstrap để operator thấy gateway và operation là hai bảng riêng.
6. Giữ compatibility tests cho runtime path, operation binding, và provider-specific serialization.

Rollback:
- Nếu migration profile mới gây lỗi, có thể quay lại adapter/config cũ bằng cách giữ data cũ và revert logic dispatch mới.
- Dữ liệu backfill nên được tạo theo cách reversible hoặc ít nhất là audit được record trước/sau.

## Open Questions

- `LLMOperation` nên được đặt tên theo step nội bộ hay theo semantic use case dùng cho reporting/admin?
- `single_message` có nên serialize system/developer instructions thành một prompt string hay vẫn giữ structured message list tối thiểu cho provider compatible?
- `local_stub` có cần tồn tại như một adapter test-only lâu dài hay chỉ là helper migration/dev tạm thời?
