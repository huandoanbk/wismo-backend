## Context

BE-15/16/17 đã đưa runtime đến trạng thái có `normalized_reasoning_result`, `response_method`, `final_safety_state`, `retrieval_required`, và `retrieval_result` (khi TEACH gate pass). Tuy nhiên Step 10 hiện chưa dùng các output này để dựng prompt theo mode; code vẫn hard-code ASK prompt.

Step 10 là điểm nối quyết định chất lượng input cho Step 11 response generation. Nếu không chuẩn hóa builder theo method, Step 11 sẽ sinh response lệch intent dù Step 8/9 đã xử lý đúng.

Spec references:
- `project-spec/Main-flow.md` (Step 10.1 -> 10.7)
- `project-spec/WISMO_MVP_Spec.md` (Step 10 section)
- `openspec/specs/runtime-validation-safety-method-selection/spec.md`
- `openspec/specs/runtime-knowledge-retrieval-rag-teach/spec.md`

## Goals / Non-Goals

**Goals:**
- Implement Step 10 builder pipeline đúng contract: chọn builder theo `response_method` conversational.
- Dùng đúng input từ runtime state (`runtime_bundle` + output Step 8 + Step 9), không query thêm DB context nền.
- Tạo output chuẩn cho Step 11: `prompt_messages` (1 system + 1 user), `prompt_debug_meta`.
- Cover fallback + compact rules theo Main Flow, gồm TEACH -> LISTEN fallback khi retrieval không usable.

**Non-Goals:**
- Không thay đổi logic Step 8 selection/safety.
- Không thay đổi retrieval pipeline Step 9 ngoài handoff payload đã có.
- Không triển khai validator/generation logic Step 11 trong change này.
- Không thay đổi contract FE/BE public payload trong sprint này.

## Decisions

### 1) Tách PromptAssembly service khỏi orchestrator
- Quyết định: thêm service/module riêng (ví dụ `runtime/prompt_assembly.py`) để xử lý builder selection + payload compose + compact/fallback.
- Lý do: giữ `RuntimeOrchestrator` mỏng, dễ unit test theo từng builder/fallback path.
- Alternative đã cân nhắc:
  - Viết trực tiếp trong `_prompt_assembly`: nhanh hơn ngắn hạn nhưng khó test, khó mở rộng Step 10.x.

### 2) Builder dispatch theo `response_method` với conversational-only guard
- Quyết định: map cứng `LISTEN/ASK/REFLECT/FOLLOWUP/TEACH` -> hàm builder tương ứng; nếu nhận method ngoài conversational ở Step 10 thì fail-fast nội bộ (runtime invariant violation).
- Lý do: Step 10 theo spec chỉ dành cho conversational methods, còn terminal control response phải short-circuit trước đó.
- Alternative:
  - Silent fallback về ASK cho mọi method lạ: dễ che lỗi pipeline Step 8.

### 3) TEACH fallback hạ xuống LISTEN builder, không đổi state Step 8
- Quyết định: khi `response_method=TEACH` nhưng `retrieval_result` null/invalid text, Step 10 dùng LISTEN builder để build prompt; đồng thời ghi `prompt_debug_meta.builder_name` (builder theo response_method) và `prompt_debug_meta.effective_builder_name` (builder chạy thực tế).
- Lý do: đúng fallback rule 10.7.4, đồng thời không override lại quyết định Step 8 (method/safety là source of truth upstream).
- Alternative:
  - Raise error: trái yêu cầu non-fatal degrade cho nhánh retrieval thiếu dữ liệu.

### 4) Compact heuristic deterministic, không gọi model phụ
- Quyết định: ước lượng token nội bộ (heuristic dựa trên độ dài text) và compact theo thứ tự: `recent_turns` -> `context_summary`; giữ nguyên `current_message`; TEACH giữ `retrieval_unit_text` ưu tiên.
- Lý do: đáp ứng rule 10.6, tránh tăng call/cost và tránh dependency mới ở Step 10.
- Alternative:
  - Dùng tokenizer provider-specific: chính xác hơn nhưng tăng coupling, khó maintain đa gateway.

### 5) `prompt_debug_meta` là contract bắt buộc cho kiểm thử
- Quyết định: luôn emit đủ `builder_name`, `used_fields`, `compact_applied`, `estimated_tokens`.
- Lý do: giúp verify behavior Step 10/11 và debug runtime path mà không cần thêm telemetry phụ.

## Risks / Trade-offs

- [Risk] Prompt template quá cứng có thể làm response kém tự nhiên ở vài intent edge case -> Mitigation: tách constants theo builder và thêm unit tests cho payload tối thiểu/maximal.
- [Risk] Heuristic token estimate lệch với tokenizer thật -> Mitigation: chỉ dùng cho compact trigger tương đối; không dùng cho billing/quota.
- [Risk] TEACH fallback sang LISTEN có thể làm output không còn “teaching” như kỳ vọng -> Mitigation: chấp nhận theo spec fallback ưu tiên an toàn và continuity khi retrieval unusable.
- [Risk] Builder input shape đa dạng dễ gây lỗi type -> Mitigation: normalize + drop non-core malformed fields theo rule 10.7.5.
