## 1. Scope lock và contract alignment

- [x] 1.1 Đối chiếu `project-spec/Main-flow.md` và `project-spec/WISMO_MVP_Spec.md` để khóa Step 4 chỉ dùng 6 outputs canonical (không thêm decision khác).
- [x] 1.2 Cập nhật `project-spec/frontend-backend-contract.md` cho control-path SSE behavior sau gate pass, gồm event semantics cho `CRISIS_SAFE_ONLY`, `BLOCKED_MINOR`, `REDIRECT`, `REFUSAL`, `SPAM_REPLY`.

## 2. Runtime Step 4 implementation

- [x] 2.1 Tạo rule-based triage detector baseline (current message + 1-3 recent user turns) với confidence gating.
- [x] 2.2 Tích hợp LLM fallback `triage_classifier` qua Gateway khi rule chưa đủ chắc; fallback `continue_to_full_reasoning` nếu classifier fail.
- [x] 2.2.1 Tạo/đảm bảo tồn tại operation registry entry `triage_classifier` (active) để Owner có thể tự map gateway/model từ admin/config.
- [x] 2.2.2 Runtime Step 4 chỉ gọi qua operation key `triage_classifier`; không hard-code supplier/model trong code.
- [x] 2.3 Implement branch routing trong orchestrator:
- [x] 2.3.1 `crisis_hotline_immediate` -> persist control turn (`CRISIS_SAFE_ONLY`), short-circuit không đi Step 5+.
- [x] 2.3.2 `blocked_minor` / `hard_redirect` / `policy_bypass_refusal` / `spam_or_non_conversational` -> non-persist control response, short-circuit không đi Step 5+.
- [x] 2.3.3 `continue_to_full_reasoning` -> đi Step 5 như normal path.
- [x] 2.4 Bổ sung triage provenance metadata (`triage_source`, `triage_decision`) cho debug/audit.

## 3. Regression coverage và verification

- [x] 3.1 Thêm tests cho rule-hit paths của 5 nhánh control + continue path.
- [x] 3.2 Thêm tests cho LLM fallback path (`rule unsure -> llm`) và classifier-fail fallback path (`-> continue_to_full_reasoning`).
- [x] 3.3 Thêm/cập nhật SSE tests cho control responses sau gate pass (không JSON post-gate).
- [x] 3.4 Thêm tests đảm bảo persist policy đúng: crisis persist, 4 control branches non-persist.
- [x] 3.5 Chạy verification: `manage.py check`, `ruff check .`, `pytest -q`, `manage.py makemigrations --check --dry-run`.
