## Why

Step 11 hiện còn ở trạng thái foundation stub: backend chỉ gọi `response_generation` một lần rồi persist ngay, chưa có validation layer, chưa có corrective retry/fallback, và chưa bám contract `safe fallback + done semantics` của Main Flow/MVP. Cần chuẩn hóa Step 11 để đảm bảo chất lượng response, an toàn theo method, và tính nhất quán persist/stream trước khi vào Step 12.

## What Changes

- Triển khai đầy đủ Step 11: response generation -> logic validation -> LLM validation -> retry/fallback handling -> persist/stream success hoặc safe fallback.
- Dùng `OperationKey.RESPONSE_GENERATION` cho generate và `OperationKey.RESPONSE_VALIDATION` cho validator, đều đi qua `LLMGateway` operation registry.
- Thêm generation retry loop tối đa 2 lần; mỗi lần fail tạo `generation_validation_feedback` và rebuild prompt trước khi generate lại.
- Bổ sung safe fallback response path khi vượt retry budget; fallback ASK hoặc LISTEN theo `fallback_recommended`/rule.
- Chuẩn hóa persist metadata Step 11 (gồm retry counters, validation outcomes, fallback flags) trước khi stream `response` + `done`.
- Đồng bộ Step 10 integration: support input `generation_validation_feedback` để rebuild prompt trong retry loop Step 11.
- Cleanup Step 10 metadata để bám strict Main Flow/MVP: loại bỏ `effective_builder_name` khỏi contract debug output và chỗ tiêu thụ liên quan.
- Bổ sung test unit/integration cho validation contract, retry loop, fallback path, persist semantics, stream done semantics.

## Capabilities

### New Capabilities
- `runtime-response-generation-validation-persist`: Contract cho Main Flow Step 11 gồm generate/validate/retry/fallback/persist/stream và invariant trước Step 12.

### Modified Capabilities
- `runtime-prompt-assembly`: Mở rộng contract Step 10 để nhận `generation_validation_feedback` từ Step 11 retry loop và rebuild prompt mà không vi phạm các constraints builder; đồng thời cleanup metadata ngoài spec (`effective_builder_name`).

## Impact

- Affected code:
  - `runtime/orchestrator.py` (thay thế Step 11 stub bằng pipeline đầy đủ)
  - `runtime/prompt_assembly.py` (bổ sung nhánh rebuild prompt theo `generation_validation_feedback`)
  - `openspec/specs/runtime-prompt-assembly/spec.md` và tests liên quan (cleanup `effective_builder_name`)
  - Có thể thêm module validator/fallback helper trong `runtime/` để giữ orchestrator mỏng.
  - `tests/unit/` cho Step 11 + Step 10 retry integration.
- Không thay đổi public endpoint shape, nhưng thay đổi hành vi nội bộ chất lượng response và metadata persist/stream của turn.
- Không thêm external dependency mới; tận dụng `LLMGateway` hiện có.
