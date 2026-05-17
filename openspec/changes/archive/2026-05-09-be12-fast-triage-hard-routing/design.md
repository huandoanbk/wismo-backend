## Context

Source of truth cho change này:
- `project-spec/Main-flow.md` (Step 4 C.2–C.10)
- `project-spec/WISMO_MVP_Spec.md` (control methods, safety/control continuity rules)

Current code gap:
- `_fast_triage()` luôn set `continue_to_full_reasoning`
- `_handle_control_branch_if_needed()` luôn `False`
- chưa có control-path SSE contract ở runtime implementation

## Goals / Non-Goals

**Goals**
- Triển khai Step 4 đúng 6 nhánh canonical từ Main Flow.
- Rule-first, LLM-fallback để tối ưu cost/latency mà vẫn an toàn.
- Chốt rõ persist policy theo Main Flow:
  - crisis persist
  - 4 control nhánh còn lại non-persist
- Control responses đi qua SSE vì gate đã pass và stream đã mở.

**Non-Goals**
- Không triển khai Step 5 case detector/re-resolution.
- Không triển khai Step 7/8 structured reasoning/safety override đầy đủ.
- Không thêm nhánh ngoài 6 outputs canonical.

## Decisions

1. Decision source order
- Rule-based detector chạy trước.
- Chỉ khi rule không đủ chắc mới gọi `triage_classifier` qua LLM Gateway.
- Nếu LLM triage lỗi/timeouts: fallback `continue_to_full_reasoning`.
- `triage_classifier` bắt buộc đi qua LLM operation registry để Owner tự chọn gateway/model; Step 4 không hard-code supplier/model.

2. Canonical outputs only
- Step 4 chỉ được trả 1 trong 6 `triage_decision` đã chốt ở Main Flow.
- Không thêm decision mới.

3. Branch execution behavior
- `crisis_hotline_immediate`:
  - persist turn với `response_method = CRISIS_SAFE_ONLY`
  - không đi Step 5+
  - đánh dấu metadata safety-control để downstream memory path bỏ qua
- `blocked_minor` / `hard_redirect` / `policy_bypass_refusal` / `spam_or_non_conversational`:
  - trả control response và kết thúc turn ở Step 4
  - non-persist (không lưu `ChatTurn` final response)
- `continue_to_full_reasoning`:
  - đi Step 5 như flow hiện tại

4. SSE transport for post-gate control
- Vì gate pass mở stream trước khi vào orchestrator, mọi control responses Step 4 trả bằng SSE events theo contract mới.
- Không dùng JSON control sau gate pass.

5. Crisis finalization handling
- Crisis branch không gọi thêm LLM usage steps; usage/quota không phát sinh thêm.
- Vẫn giữ runtime barrier state tối thiểu nhất quán để không phá lifecycle.

## Rule-based detector scope (BE-12)

Baseline rule engine gồm:
- input:
  - `current_message`
  - tối đa 3 recent user turns gần nhất
- output:
  - decision + confidence + reason tags
- nhóm luật:
  - crisis hotline immediate
  - minor-age block
  - hard redirect
  - policy bypass
  - spam/non-conversational
- nguyên tắc:
  - ưu tiên độ chính xác cao (precision) cho control branches
  - khi mơ hồ -> fallback LLM classifier

BE-12 chưa aim hoàn thiện toàn bộ linguistic coverage; tập trung deterministic backbone + regression tests.

## Risks / Trade-offs

- False positive control routing nếu rule quá rộng.
  - Mitigation: conservative thresholds + explicit tests cho negative samples.
- FE mismatch nếu control SSE shape chưa rõ.
  - Mitigation: cập nhật `frontend-backend-contract.md` cùng implementation.
- Runtime lifecycle inconsistency giữa persist và non-persist paths.
  - Mitigation: tách rõ orchestrator paths + test state assertions.

## Open Points Confirmed

Đã được Owner chốt cho change này:
- Control path sau gate pass dùng SSE.
- Chỉ dùng đúng 6 outputs Step 4 từ `Main-flow.md`.
- `crisis_hotline_immediate` short-circuit flow Step 5+; không tính thêm usage.
- Cần giải pháp rule-based detector rõ, deterministic và có fallback.
