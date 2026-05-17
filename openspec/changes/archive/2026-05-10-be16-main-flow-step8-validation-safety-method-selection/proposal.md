## Why
Main Flow Step 8 (Validation / safety gate / method selection) hiện mới là stub trong runtime (`_validate_and_select_response_method` luôn ép `ASK`, `retrieval_required=false`). Sau BE-15, Step 7 đã có `reasoning_result` chuẩn nên cần Step 8 để validate, normalize, consistency-check và chốt decision an toàn theo đúng MVP/Main Flow.

## What Changes
- Implement Step 8 pipeline trong runtime:
  - schema validation + normalization cho `reasoning_result`;
  - inconsistency mapping theo rule set Step 8 (A→G);
  - safety hard override;
  - context/intent-based safe override;
  - chốt output: `normalized_reasoning_result`, `final_safety_state`, `response_method`, `retrieval_required`.
- Implement corrective retry loop Step 8 -> Step 7:
  - chỉ cho inconsistency nặng không phải hard-safety;
  - tách riêng counter với gateway retry của Step 7;
  - truyền `reasoning_control` (`is_corrective_retry`, `retry_count`, `validation_error_feedback`);
  - corrective retry tối đa 2 lần; fail nặng sau đó thì fallback an toàn `ASK`, `retrieval_required=false`, `final_safety_state=normal`.
- Cover đầy đủ các consistency rules cốt lõi của Main Flow Step 8:
  - `required_next_slots` consistency,
  - `case_slots` vs `required_next_slots`,
  - `intent` vs `action_recommended`.
- Bổ sung test coverage cho safety override, corrective retry, và retrieval rule.

## Scope
- Trong scope:
  - `runtime/orchestrator.py` Step 8 logic và state fields liên quan;
  - helper validator/normalizer cho Step 8;
  - unit tests runtime Step 8.
- Ngoài scope:
  - thay đổi Step 9 retrieval pipeline chi tiết;
  - thay đổi Step 10 prompt templates;
  - thay đổi payload SSE Step 11.

## Impact
- Step 8 sẽ phản ánh đúng Main Flow/MVP thay vì stub.
- Giữ runtime fail-safe cho safety branch và fallback ASK khi corrective không giải được inconsistency nặng.
- Tạo contract ổn định cho Step 9 (`retrieval_required`) và Step 10 (`normalized_reasoning_result`).
