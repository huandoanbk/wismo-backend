## Why

BE-11 đã chốt Step 3 (resolve chat context + turn intake). Runtime hiện tại vẫn stub ở Step 4: luôn `continue_to_full_reasoning`, chưa có hard routing control branches theo `project-spec/Main-flow.md`.

Để bám đúng source of truth (`Main-flow.md` + `WISMO_MVP_Spec.md`), sprint kế tiếp cần triển khai BE-12 cho Fast triage/hard routing với 6 outputs canonical, control-path SSE behavior, và persist policy rõ ràng.

## What Changes

- Triển khai Step 4 decision layer với 2 tầng:
  - Rule-based detector (deterministic, chi phí thấp)
  - LLM triage classifier fallback qua Gateway khi rule chưa đủ chắc
- Chỉ dùng đúng 6 `triage_decision` từ Main Flow:
  - `crisis_hotline_immediate`
  - `blocked_minor`
  - `hard_redirect`
  - `policy_bypass_refusal`
  - `spam_or_non_conversational`
  - `continue_to_full_reasoning`
- Branch behavior:
  - `crisis_hotline_immediate`: persist turn, trả `CRISIS_SAFE_ONLY`, short-circuit không đi Step 5+
  - `blocked_minor` / `hard_redirect` / `policy_bypass_refusal` / `spam_or_non_conversational`: non-persist control response, short-circuit không đi Step 5+
  - `continue_to_full_reasoning`: đi Step 5 như hiện tại
- Control-path transport dùng SSE sau gate pass, không trả JSON control post-gate.
- Thêm runtime metadata/telemetry tối thiểu để audit nguồn quyết định (`rule|llm|fallback`).

## Capabilities

### New Capabilities
- `runtime-triage-routing`: Fast triage và hard routing theo Main Flow Step 4 với rule-first + LLM fallback.

### Modified Capabilities
- `chat-sse-transport`: Mở rộng SSE lifecycle cho control responses ở Step 4 khi gate đã pass.

## Impact

- OpenSpec artifacts mới:
  - `openspec/changes/be12-fast-triage-hard-routing/proposal.md`
  - `openspec/changes/be12-fast-triage-hard-routing/design.md`
  - `openspec/changes/be12-fast-triage-hard-routing/specs/runtime-triage-routing/spec.md`
  - `openspec/changes/be12-fast-triage-hard-routing/specs/chat-sse-transport/spec.md`
  - `openspec/changes/be12-fast-triage-hard-routing/tasks.md`
- Ảnh hưởng code dự kiến:
  - `runtime/orchestrator.py`
  - `runtime/*` (triage service/rules)
  - `llm_ops/*` (operation config usage cho `triage_classifier` nếu cần)
  - `project-spec/frontend-backend-contract.md`
  - tests runtime/SSE liên quan
- Không mở rộng sang Step 5 case resolution hoặc Step 8 safety override trong sprint này.
