## Context

BE-7 nằm sau runtime config/quota foundation và trước các sprint runtime sâu hơn sẽ gọi LLM thật. `project-spec/WISMO_MVP_Spec.md` đã chốt rằng mọi LLM call của MVP phải đi qua một `LLM Gateway` nội bộ, còn `project-spec/WISMO_BE_Implementation_Plan.md` đã xác định bộ `operation_key` tối thiểu, entity nền `LLMSupplier`/`LLMModel`/`LLMOperationConfig`/`LLMUsageEvent`, và nhu cầu query usage theo ngày, supplier, model, operation.

Hiện change này cần biến yêu cầu đó thành một capability canonical, đủ để các runtime step sau dùng lại mà không hard-code provider/model, và đủ để usage/cost có nguồn truth thống nhất cho quota accounting và debug vận hành.

## Spec References

- `project-spec/WISMO_MVP_Spec.md`
- `project-spec/WISMO_BE_Implementation_Plan.md`
- `openspec/specs/runtime-config-quota-foundation/spec.md`

## Goals / Non-Goals

**Goals:**
- Chốt `llm_ops` thành gateway duy nhất để route LLM call theo `operation_key`.
- Lưu config canonical cho supplier/model/params để admin hoặc vận hành có thể đổi mapping mà không sửa runtime code.
- Ghi usage event chuẩn cho từng call, đủ để aggregate theo ngày/supplier/model/operation.
- Giữ provider-specific details sau một adapter boundary để runtime consumers chỉ nhìn thấy contract normalized.

**Non-Goals:**
- Không migrate toàn bộ runtime step sang gateway trong cùng change này.
- Không xây dashboard vận hành đầy đủ.
- Không chốt retry/fallback strategy phức tạp ngoài boundary foundation.
- Không đổi frontend-backend contract nếu chưa có API/streaming surface mới.

## Decisions

### 1. Dùng DB-backed canonical config thay vì hard-code hoặc YAML-only

`LLMSupplier`, `LLMModel`, và `LLMOperationConfig` sẽ là nguồn truth canonical trong app DB. Cách này cho phép đổi supplier/model theo `operation_key` mà không cần sửa code runtime và vẫn query được lịch sử usage theo config thực tế.

**Alternatives considered**
- Hard-code trong runtime step: loại vì làm lệch behavior giữa các step và khó đổi model.
- Settings/env-only mapping: loại vì không đủ queryable và không phản ánh được config hoạt động theo thời gian.

### 2. Tách provider integration ra sau một adapter boundary mỏng

`llm_ops` sẽ gọi provider qua adapter interface normalized thay vì để từng runtime module gọi SDK riêng. Gateway chịu trách nhiệm chọn adapter theo `supplier`, còn caller chỉ nhận kết quả chuẩn hóa.

BE-7 sẽ dùng một canonical provider profile ở mức cấu hình, nhưng profile đó có thể được hiện thực qua nhiều wire mode khác nhau:
- `openai_compatible`: DeepInfra, Gemini OpenAI compatibility, các vendor OpenAI-compatible khác
- `anthropic_native`: Claude API native
- `azure_openai_v1`: Azure OpenAI API v1
- `openai_native`: OpenAI/ChatGPT API native

Profile canonical nên chứa một block duy nhất cho operator/admin nhìn vào, với các trường khái quát:
- `provider_kind`
- `endpoint` hoặc `base_url`
- `api_key_ref` hoặc credential reference
- `model_name` hoặc `deployment_name`
- `mode`: `single_message` hoặc `conversation`
- `params` cho provider-specific overrides

`local_stub` chỉ giữ vai trò deterministic dev/test adapter. Nó không phải provider production canonical.

**Alternatives considered**
- Cho runtime step gọi provider trực tiếp: loại vì phá contract `LLM Gateway` canonical.
- Viết adapter riêng trong từng module consumer: loại vì nhân bản logic và khó đồng bộ usage logging.

### 3. Persist usage event theo từng call, aggregate query ở lớp đọc

Mỗi call sẽ tạo một `LLMUsageEvent` riêng với các trường canonical đã chốt trong plan. Aggregate theo ngày/supplier/model/operation sẽ làm từ event table thay vì duy trì summary table sớm, để foundation đơn giản và dễ debug.

**Alternatives considered**
- Chỉ lưu summary per day: loại vì mất khả năng audit từng call.
- Event + summary song song ngay từ đầu: loại vì tăng complexity chưa cần thiết cho BE-7.

### 4. Fail closed khi thiếu config hoặc mapping không hợp lệ

Nếu `operation_key` chưa có active config hoặc config trỏ tới supplier/model không hợp lệ, gateway sẽ không tự suy diễn default ngầm. Thay vào đó, gateway nên raise một domain error canonical kiểu `LLMGatewayError`/`LLMGatewayConfigurationError` với `code` ổn định để tầng caller map sang response/error envelope của runtime. Bộ code canonical nên được khóa sớm để test và caller không phải đoán:

- `llm_gateway_config_missing`
- `llm_gateway_config_invalid`
- `llm_gateway_provider_unavailable`
- `llm_gateway_provider_error`

**Alternatives considered**
- Fallback sang model mặc định: loại vì có thể che lỗi cấu hình và làm sai routing/cost accounting.

### 5. Django admin là surface vận hành mặc định cho usage

Vì user muốn quan sát trực tiếp trong `/admin`, usage query initial nên được lộ qua Django admin changelist cho `LLMUsageEvent` thay vì tạo một API mới trong cùng change. Điều này giữ scope nhỏ, tận dụng admin đã có, và vẫn đủ cho vận hành xem theo event, lọc theo `operation_key`, supplier, model, và ngày.

Admin changelist nên khóa tối thiểu:
- `list_display`: `created_at`, `turn`, `operation_key`, `supplier_name`, `model_name`, `status`, `total_billable_tokens`, `latency_ms`
- `list_filter`: `operation_key`, `status`, `supplier_name`, `model_name`, `created_at`
- `search_fields`: `turn__id`, `supplier_name`, `model_name`, `operation_key`
- `date_hierarchy`: `created_at`

**Alternatives considered**
- Tạo custom admin API/report riêng: loại vì tăng surface không cần thiết cho BE-7.

### 6. Giữ scope BE-7 ở foundation, không kéo caller migration vào cùng change

Change này sẽ chốt foundation và contract nội bộ trước. Việc đổi từng runtime step sang gateway sẽ là work follow-up theo sprint/runtime step tương ứng để giảm rủi ro và giữ review nhỏ.

**Alternatives considered**
- Làm luôn migration toàn bộ callers: loại vì scope lớn, dễ trộn nền tảng với feature runtime.

## Risks / Trade-offs

- [Rủi ro] Config drift hoặc thiếu seed data có thể làm gateway fail closed khi caller đã chuyển qua sử dụng. → [Giảm thiểu] Seed bộ config tối thiểu, thêm regression test cho missing config, và giữ caller migration tách bước.
- [Rủi ro] Event logging thêm write overhead cho mọi LLM call. → [Giảm thiểu] Giữ schema event nhỏ, index đúng các cột query chính, và tránh summary table sớm.
- [Rủi ro] Provider-specific response differences bị normalize mất một phần chi tiết. → [Giảm thiểu] Chỉ chuẩn hóa những trường runtime cần, còn phần vendor-specific chi tiết sẽ chỉ mở rộng khi có requirement thật.
- [Rủi ro] Nếu sau này muốn xuất usage theo dashboard, query event-only có thể cần tối ưu thêm. → [Giảm thiểu] Đặt index theo `created_at`, `supplier`, `model`, và `operation_key` để đủ đường nâng cấp.
- [Rủi ro] Không có fallback mặc định có thể làm dev/test fail nếu quên seed config. → [Giảm thiểu] Bắt buộc seed/fixture dev/test rõ ràng và fail fast ngay từ sớm.

## Migration Plan

1. Thêm schema/migration cho `LLMSupplier`, `LLMModel`, `LLMOperationConfig`, và `LLMUsageEvent` nếu bản code hiện tại chưa đủ hoàn chỉnh.
2. Implement gateway service và provider adapter boundary trong `llm_ops`.
3. Thêm query service/manager để aggregate usage theo ngày/supplier/model/operation.
4. Seed config tối thiểu cho môi trường dev/test để gateway foundation có thể chạy deterministically.
5. Expose `LLMUsageEvent` trong Django admin changelist với filter/search/date hierarchy phù hợp.
6. Giữ runtime consumers ở trạng thái chưa migrate cho tới khi sprint follow-up đổi từng caller sang gateway canonical.

Rollback:
- Nếu gateway foundation gây lỗi, revert phần caller switch ở sprint sau mà không cần phá schema foundation.
- Vì change này chủ yếu là foundation nội bộ, rollback logic chủ yếu nằm ở code path mới và seed config; schema có thể giữ lại nếu đã migrate an toàn.

## Open Questions

- Có cần lưu thêm raw provider metadata hay provider request id trong `LLMUsageEvent` ngay từ BE-7 không, hay giữ schema tối thiểu rồi mở rộng sau?
- Dev/test có cần seed một supplier/model mặc định cụ thể, hay chỉ cần schema và service boundary để test tự inject config?
