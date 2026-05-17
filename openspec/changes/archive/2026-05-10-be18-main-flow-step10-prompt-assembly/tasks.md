## 1. Runtime prompt assembly implementation

- [x] 1.1 Tạo module/service Step 10 để dispatch builder theo `response_method` conversational (`LISTEN`, `ASK`, `REFLECT`, `FOLLOWUP`, `TEACH`).
- [x] 1.2 Triển khai từng builder để assemble đúng `system message` + `user message` theo input contract Main Flow và shared composition rules.
- [x] 1.3 Triển khai fallback rules 10.7 cho LISTEN/REFLECT/FOLLOWUP/TEACH (bao gồm TEACH -> LISTEN khi retrieval unusable).
- [x] 1.4 Triển khai compact/token-control rule 10.6 và emit `prompt_debug_meta` đầy đủ (`builder_name`, `effective_builder_name`, `used_fields`, `compact_applied`, `estimated_tokens`).
- [x] 1.5 Bổ sung metadata `effective_builder_name` và bảo đảm Step 11 có thể đọc metadata này để validate theo prompt thực tế khi fallback builder xảy ra.

## 2. Orchestrator integration

- [x] 2.1 Tích hợp service Step 10 vào `RuntimeOrchestrator._prompt_assembly`, thay thế ASK stub hiện tại.
- [x] 2.2 Đảm bảo Step 10 chỉ đọc runtime state hiện có, không query lại DB context nền/memory.
- [x] 2.3 Đảm bảo output Step 10 được append vào runtime state đúng keys: `prompt_messages`, `prompt_debug_meta`.

## 3. Tests và kiểm chứng

- [x] 3.1 Thêm unit tests cho builder selection và output contract (đúng 1 system + 1 user message).
- [x] 3.2 Thêm unit tests cho fallback paths, đặc biệt TEACH retrieval null/invalid -> LISTEN builder.
- [x] 3.3 Thêm unit tests cho compact priority order (`recent_turns` trước `context_summary`, không cắt `current_message`, TEACH giữ retrieval unit).
- [x] 3.4 Chạy `openspec validate --changes be18-main-flow-step10-prompt-assembly --strict` và test runtime liên quan.
