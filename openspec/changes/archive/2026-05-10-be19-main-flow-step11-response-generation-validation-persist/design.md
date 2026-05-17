## Context

Sau BE-18, Step 10 đã có prompt assembly theo method. Tuy nhiên Step 11 trong code vẫn chỉ gọi `response_generation` một lần rồi persist, chưa có:
- logic validation rỗng/whitespace,
- validator theo `response_method` (general + method-specific),
- corrective retry loop với feedback quay lại Step 10,
- safe fallback response khi exhausted retry.

Spec references:
- `project-spec/Main-flow.md` (Step 11.1 -> 11.7)
- `project-spec/WISMO_MVP_Spec.md` (Step 11 section)
- `openspec/specs/runtime-prompt-assembly/spec.md`
- `openspec/specs/runtime-validation-safety-method-selection/spec.md`

## Goals / Non-Goals

**Goals:**
- Implement Step 11 pipeline đầy đủ theo Main Flow/MVP.
- Tách rõ generate và validate operations qua `LLMGateway` registry.
- Đảm bảo retry/fallback behavior deterministic, fail-safe, có persist metadata rõ ràng.
- Đảm bảo `done` chỉ phát sau khi final response của turn đã persist thành công.
- Cleanup phần metadata Step 10 đang ngoài source-of-truth (`effective_builder_name`) để spec/code đồng nhất.

**Non-Goals:**
- Không triển khai Step 12 consolidation trong sprint này (chỉ giữ contract handoff).
- Không thay đổi selection logic Step 8 hoặc retrieval pipeline Step 9.
- Không thay đổi API route/controller layer ngoài runtime behavior.

## Decisions

### 1) Tách Step 11 thành service chuyên biệt
- Quyết định: thêm service/module Step 11 (ví dụ `runtime/response_generation.py`) để encapsulate generate/validate/retry/fallback.
- Lý do: giữ `RuntimeOrchestrator` ngắn, test được từng nhánh logic.
- Alternative:
  - Viết hết trong `_response_generation_and_persist`: nhanh nhưng khó maintain/test.

### 2) Validation hai tầng: logic-first, LLM-second
- Quyết định: chạy logic validation trước (empty/whitespace/coherence cơ bản); chỉ gọi validator LLM khi pass logic tối thiểu.
- Lý do: tiết kiệm call và bám Step 11.3/11.4.
- Alternative:
  - Gọi validator LLM cho mọi output kể cả rỗng: tốn token, không cần thiết.

### 3) Retry budget cứng = 2 và feedback loop qua Step 10
- Quyết định: khi fail validation, tăng `generation_retry_count`; nếu `<=2`, tạo `generation_validation_feedback` rồi gọi lại Step 10 build prompt mới trước lần generate tiếp theo.
- Lý do: bám đúng Step 11.5 spec.
- Alternative:
  - Retry trực tiếp Step 11.2 không rebuild prompt: lệch main flow.

### 4) Safe fallback response khi exhausted retry
- Quyết định: fallback ASK clarify question khi `fallback_recommended=ASK`, ngược lại LISTEN ngắn/trung tính/an toàn; fallback response vẫn persist và stream như success path.
- Lý do: đảm bảo luôn có final output an toàn cho user.

### 5) Cleanup `effective_builder_name` khỏi contract Step 10
- Quyết định: bỏ `effective_builder_name` khỏi contract debug metadata của Step 10 và các assertion/consumers liên quan.
- Lý do: field này không có trong Main Flow/MVP Step 10/11, nên giữ lại sẽ gây lệch source-of-truth.
- Alternative:
  - Giữ lại như internal debug field: dễ làm trượt scope spec-first và tạo nhiễu khi implement Step 11.

## Risks / Trade-offs

- [Risk] Validator prompt quá nghiêm có thể làm retry quá nhiều -> Mitigation: tách `severity=light/hard` và chỉ escalate fallback khi exhausted budget.
- [Risk] Prompt-feedback loop làm tăng latency -> Mitigation: budget retry cố định 2, payload feedback compact.
- [Risk] Metadata persist lớn -> Mitigation: chỉ lưu minimal canonical fields cho audit/debug.
- [Risk] Step 10 feedback integration có thể làm lệch style constraints -> Mitigation: Step 10 giữ `keep_constraints` và chỉ thêm rewrite instruction cục bộ.
- [Risk] Cleanup metadata có thể làm fail test cũ -> Mitigation: update test assertions cùng lúc với cleanup để tránh false regression.

## Migration Plan

- Không có migration DB bắt buộc cho phase đầu nếu reuse `runtime_metadata` JSON hiện có.
- Nếu cần fields mới ở `ChatTurn` cho analytics sau này, tách sprint riêng để tránh mở scope BE-19.

## Open Questions

- Không còn blocker mâu thuẫn spec/code ở mức propose. BE-19 có thể triển khai trực tiếp theo contract trên.
