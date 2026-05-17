## Why

Step 12 trong Main Flow/MVP hiện là source of truth cho usage finalization + memory/state consolidation đồng bộ, nhưng codebase mới chỉ hoàn thiện phần usage/quota cơ bản. Nếu không hoàn thiện Step 12 đúng chuẩn thì turn kế tiếp sẽ đọc state thiếu nhất quán (context/memory/profile/preference/state) và khó audit vận hành theo status finalized/partial/failed.

## What Changes

- Hoàn thiện Step 12 runtime pipeline theo đúng Main Flow Step 12.1-12.13, bao gồm usage finalization, quota update, context summary updater, long-term memory extractor, rule-based state/profile/preference updates, và consolidation log meta.
- Bổ sung persistence models cho `user_profile`, `user_preference`, `user_state` (hiện Step 6 đang là stub `{}`), đồng bộ load ở Step 6 và update ở Step 12.
- Tách Step 12 thành service/module chuyên trách, giữ barrier semantics hiện tại: chỉ chặn turn kế tiếp khi status `pending/processing`; không chặn thêm khi `usage_accounting_status=failed` (chỉ log + persist status theo policy đã chốt).
- Bổ sung LLM operations cho Step 12 subtask và usage capture đầy đủ cho các call trong Step 12.
- Cập nhật contract SSE/metadata để giữ đúng semantics `done` (response persisted) và phản ánh quota after-turn theo contract hiện hành.

## Capabilities

### New Capabilities
- `runtime-post-turn-finalization-usage-memory-barrier`: Chuẩn hóa Step 12 sync finalization gồm usage/quota/consolidation, memory/state updates, failure handling và barrier semantics.
- `runtime-identity-state-store`: Bổ sung persistence contract cho `user_profile`, `user_preference`, `user_state` dùng bởi Step 6 load + Step 12 consolidation.

### Modified Capabilities
- `runtime-bundle-loading`: Thay đổi nguồn dữ liệu `user_profile`, `user_preference`, `user_state` từ stub sang persisted identity-state.
- `chat-sse-transport`: Làm rõ semantics `done` không thay thế Step 12 và đồng bộ metadata quota hậu turn.

## Impact

- Affected code:
  - `runtime/orchestrator.py` (tách và gọi Step 12 service)
  - `runtime/services.py` (Step 6 load state thật)
  - module mới cho Step 12 (`runtime/finalization.py` hoặc tương đương)
  - `chat/models.py` (nếu cần mở rộng metadata fields)
  - app/model mới cho identity state (`accounts` hoặc app chuyên biệt)
  - `llm_ops` operation config seeds/migrations cho Step 12 operations
- Affected specs/contracts:
  - Main Flow alignment Step 12
  - FE/BE SSE done metadata liên quan post-turn status/quota
- Migration/deploy impact:
  - thêm DB tables/index cho identity-state persistence
  - migration operation configs cho Step 12 LLM tasks
