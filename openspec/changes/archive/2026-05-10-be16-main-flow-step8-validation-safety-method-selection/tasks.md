## 1. Step 8 runtime engine
- [x] 1.1 Thay stub `_validate_and_select_response_method` bằng pipeline Step 8 đầy đủ.
- [x] 1.2 Bổ sung state fields Step 8: `normalized_reasoning_result`, `final_safety_state`, `retrieval_required`.
- [x] 1.3 Đảm bảo Step 8 chỉ đọc `runtime_bundle` + `reasoning_result`, không reload DB context nền.
- [x] 1.4 Tách runtime counters: `reasoning_gateway_retry_count` (Step 7) và `reasoning_corrective_retry_count` (Step 8 loop).

## 2. Validation + normalization
- [x] 2.1 Implement schema validation cho các field bắt buộc của `reasoning_result`.
- [x] 2.2 Implement normalization enum/list/object theo allowlist và shape cố định.
- [x] 2.3 Chuẩn hóa `turn_strategy`, `case_slots`, `required_next_slots` theo contract Main Flow/MVP.

## 3. Safety gate + method selection
- [x] 3.1 Implement hard safety override mapping (crisis/minor/redirect/refusal/spam).
- [x] 3.2 Implement context-sufficiency overrides về `ASK`.
- [x] 3.3 Implement intent/action consistency overrides và default safe fallback.
- [x] 3.4 Implement `retrieval_required` rule (`TEACH` only).

## 4. Corrective retry loop
- [x] 4.1 Implement heavy inconsistency detection và feedback payload `validation_error_feedback`.
- [x] 4.2 Implement Step 8 -> Step 7 corrective callback qua `reasoning_control`.
- [x] 4.3 Implement corrective retry limit = 2 + exhausted fallback (`ASK`, `retrieval_required=false`, `final_safety_state=normal`) cho non-hard-safety path.

## 5. Consistency rules coverage (A→G core)
- [x] 5.1 Implement required_next_slots consistency: ASK+empty => corrective; non-ASK+non-empty => clear.
- [x] 5.2 Implement case_slots consistency: fulfilled slot removed from required_next_slots.
- [x] 5.3 Implement case_slots/context/action guard cho `TEACH` và `FOLLOWUP` theo Main Flow.
- [x] 5.4 Implement intent/action consistency rules cốt lõi (`unclear`, `ask_teaching_or_perspective`, `emotional_support`, `report_progress`, `self_understanding`).

## 6. Tests and verification
- [x] 6.1 Thêm unit tests cho schema/normalization + safety override matrix.
- [x] 6.2 Thêm unit tests cho corrective retry success và exhausted fallback (limit=2).
- [x] 6.3 Thêm unit tests cho required_next_slots/case_slots/intent consistency mapping.
- [x] 6.4 Chạy test runtime/orchestrator + regression nhóm liên quan.
