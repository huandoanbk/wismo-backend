## Why

Step 10 (Prompt assembly) hiện vẫn là stub trong `runtime/orchestrator.py`: luôn build prompt ASK tối giản, chưa chọn builder theo `response_method`, chưa lắp dữ liệu từ Step 6/8/9, và chưa áp dụng fallback/compact rules như `Main-flow.md` và `WISMO_MVP_Spec.md` yêu cầu. Cần chuẩn hóa Step 10 để Step 11 nhận đúng prompt contract theo từng mode hội thoại.

## What Changes

- Triển khai Step 10 Prompt assembly đúng contract Main Flow/MVP cho nhóm conversational methods: `LISTEN`, `ASK`, `REFLECT`, `FOLLOWUP`, `TEACH`.
- Thêm cơ chế chọn builder theo `response_method` từ Step 8 và giữ nguyên `final_safety_state`/`response_method` (không override trong Step 10).
- Xây `prompt_messages` chuẩn gồm đúng 1 `system message` + 1 `user message` và `prompt_debug_meta` (`builder_name`, `used_fields`, `compact_applied`, `estimated_tokens`).
- Thực thi fallback rules cho từng builder, đặc biệt `TEACH` fallback sang `LISTEN` khi `retrieval_result` null hoặc `retrieval_unit_text` rỗng/lỗi.
- Thực thi compact/token-control rule: compact `recent_turns` trước, rồi `context_summary`, không cắt `current_message`; ở TEACH ưu tiên giữ `retrieval_unit_text`.
- Bổ sung test cho selection, fallback, compact behavior, và output contract Step 10.

## Capabilities

### New Capabilities
- `runtime-prompt-assembly`: Định nghĩa requirement cho Step 10 prompt assembly (input/output contract, builder selection, fallback, compact/token-control, runtime bundle usage boundary).

### Modified Capabilities
- `runtime-knowledge-retrieval-rag-teach`: Chốt handoff contract Step 9 -> Step 10 để TEACH builder dùng `retrieval_prompt_payload`/`retrieval_unit_text` và fallback hợp lệ khi retrieval không dùng được.

## Impact

- Affected code:
  - `runtime/orchestrator.py` (thay `_prompt_assembly` từ stub sang triển khai Step 10 đầy đủ)
  - Có thể thêm module builder/helper trong `runtime/` nếu cần để giữ orchestrator mỏng.
  - `tests/unit/` cho Step 10 flow.
- Không đổi API surface trực tiếp ở endpoint Step 3/4/5/6/7/8/9, nhưng output runtime nội bộ cho Step 11 sẽ chuẩn theo spec.
- Không thêm external dependency mới.
