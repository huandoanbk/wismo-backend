## Context

`runtime/orchestrator.py::_load_runtime_bundle()` hiện mới là placeholder: `user_profile/user_preference/user_state` rỗng cứng, `long_term_memory` rỗng cứng, và chưa có service boundary rõ cho data loading Step 6. Trong khi đó Main Flow + MVP spec yêu cầu Step 6 load/retrieve dữ liệu canonical và vẫn chạy ổn khi `case_id = null`.

Spec References:
- `project-spec/Main-flow.md` (Step 6 D.1 → D.9)
- `project-spec/WISMO_MVP_Spec.md` (A.6.2.2 Step 6)
- `openspec/specs/runtime-case-resolution/spec.md`
- `openspec/specs/runtime-config-quota-foundation/spec.md`

## Goals / Non-Goals

**Goals:**
- Implement Step 6 đúng contract với bundle fields canonical.
- Cho phép Step 6 chạy với cả `case_id` resolved và `case_id = null`.
- Chuẩn hóa fallback behavior: retrieval/load lỗi thì về rỗng, không crash runtime.
- Cố định ownership rule: bundle assemble một lần, downstream không reload core fields.

**Non-Goals:**
- Không thay đổi endpoint/API response shape public.
- Không redesign Step 7 reasoning logic trong BE-14.
- Không xây thêm telemetry path riêng cho null-case ở sprint này.

## Decisions

1. Tạo service chuyên trách Step 6 data loading
- Thêm service runtime-level (ví dụ `RuntimeBundleService`) chịu trách nhiệm load/retrieve tất cả fields Step 6.
- Orchestrator chỉ gọi service và set `state.runtime_bundle`.
- Lý do: giữ `orchestrator` mỏng, testable, tránh query rải rác.

2. Context summary/long-term memory theo `case_id`
- Nếu `case_id` có giá trị: load summary + retrieve memory active/enabled.
- Nếu `case_id = null`: set `context_summary = ""`, `long_term_memory = []`.
- Lý do: đúng chốt BE-13 và tránh hard-fail khi case chưa resolve.

3. Identity-level fields dùng fallback object rỗng chuẩn hóa
- `user_profile`, `user_preference`, `user_state` trả `{}` nếu chưa có nguồn dữ liệu.
- Lý do: giữ schema ổn định cho Step 7 input contract.

4. Enforce ownership rule bằng test regression
- Step 6 assemble một lần; Step 7+ không được reload core fields từ DB.
- Lý do: bám Main Flow D.9 và ngăn drift logic giữa các step.

## Risks / Trade-offs

- [Risk] Bundle thiếu case-level context khi `case_id = null` làm reasoning yếu hơn → Mitigation: giữ schema đầy đủ, để Step 7 xử lý bằng context còn lại.
- [Risk] Retrieval layer fail gây noisy logs hoặc runtime branch khó debug → Mitigation: fallback deterministic (`[]`) + metadata nguồn fallback.
- [Risk] Thêm service mới dễ trùng với logic rải rác hiện có → Mitigation: gom hết Step 6 loading vào một service boundary duy nhất.

## Migration Plan

1. Implement service + wiring orchestrator.
2. Thêm/điều chỉnh tests Step 6 contract (resolved-case + null-case + fallback).
3. Chạy `manage.py check`, `pytest`, `ruff check .`, `makemigrations --check --dry-run`.
4. Không cần migration DB mới nếu không thêm model/field.

Rollback:
- Revert code Step 6 service/wiring về bản trước nếu cần; không rollback schema vì không đổi DB model.

## Open Questions

- Không còn open question cho BE-14 sau khi chốt rule: Step 6 vẫn chạy khi `case_id = null` và fields case-level để rỗng.
