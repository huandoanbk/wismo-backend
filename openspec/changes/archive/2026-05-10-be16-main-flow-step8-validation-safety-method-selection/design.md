## Overview
BE-16 thay Step 8 từ stub sang policy engine nhẹ dựa trên `reasoning_result` của Step 7 và `runtime_bundle` của Step 6. Step này không gọi provider mới ngoài corrective callback về Step 7 khi cần.

## Runtime Placement and Inputs
- Placement: sau Step 7, trước Step 9.
- Inputs read-only:
  - `runtime_bundle` (Step 6)
  - `reasoning_result` (Step 7)
- Không reload context nền từ DB.

## Runtime State Outputs
Step 8 append vào runtime state:
- `normalized_reasoning_result`
- `final_safety_state` (internal string: `normal|crisis_only|blocked|redirect|refusal|spam`)
- `response_method` (enum existing `ResponseMethod`)
- `retrieval_required` (bool)

## Step 8 Processing Order
1. Schema validation + normalization
2. Consistency checks + inconsistency classification (light/medium/heavy)
3. Safety hard override
4. Non-safety safe override (context, intent, slots)
5. Retrieval rule
6. Corrective retry (nếu heavy non-safety)

## Corrective Retry Strategy
- Trigger: heavy inconsistency không thuộc hard-safety override.
- Action:
  - tăng `reasoning_corrective_retry_count` runtime state;
  - set `reasoning_control` với payload:
    - `is_corrective_retry=true`
    - `retry_count`
    - `validation_error_feedback`: `error_type`, `error_codes`, `must_fix_fields`, `must_preserve`
  - gọi lại `_full_reasoning`;
  - chạy lại Step 8 từ đầu.
- Retry limit:
  - dùng `reasoning_corrective_retry_count`;
  - corrective retry tối đa 2 lần;
  - sau khi vượt giới hạn corrective retry của Step 8: fallback `ASK`, `retrieval_required=false`, `final_safety_state=normal` nếu không có hard safety flags.

## Retry Counter Separation
- `reasoning_gateway_retry_count`: chỉ dùng cho retry provider/transient trong Step 7 gateway call.
- `reasoning_corrective_retry_count`: chỉ dùng cho loop Step 8 -> Step 7 corrective.
- Hai counter MUST tách riêng để tránh lẫn ngưỡng và sai fallback path.

## Safety Hard Override Mapping
- `crisis_self_harm` hoặc `crisis_harm_others` -> `CRISIS_SAFE_ONLY`, `final_safety_state=crisis_only`
- `minor_age_block` -> `BLOCKED_MINOR`, `final_safety_state=blocked`
- `medical_out_of_scope` hoặc `legal_out_of_scope` -> `REDIRECT`, `final_safety_state=redirect`
- `policy_bypass` -> `REFUSAL`, `final_safety_state=refusal`
- `spam_or_nonsense` -> `SPAM_REPLY`, `final_safety_state=spam`

## Conversational Method Selection
Khi không có hard safety flags:
- start từ `action_recommended` sau normalize;
- apply context sufficiency overrides về `ASK` theo Main Flow rules;
- apply `required_next_slots` consistency:
  - `action=ASK` mà slots rỗng -> heavy inconsistency -> corrective retry;
  - `action!=ASK` mà slots có giá trị -> clear slots;
- apply `case_slots` consistency:
  - slot đã có value rõ thì remove khỏi `required_next_slots`;
  - `case_slots` quá rỗng nhưng `action=TEACH` -> ưu tiên `ASK` hoặc corrective retry nếu mâu thuẫn lõi nhiều;
- apply intent/action consistency overrides theo mapping đã chốt;
- default safe fallback: `ASK`.

## Retrieval Rule
- `response_method == TEACH` -> `retrieval_required = true`
- method khác -> `retrieval_required = false`

## Testing
- Schema/normalization tests.
- Safety hard override tests (5 nhánh).
- Corrective retry tests (heavy non-safety -> callback Step 7).
- Exhausted corrective retry -> safe ASK fallback.
- `TEACH` vs non-`TEACH` retrieval flag tests.
