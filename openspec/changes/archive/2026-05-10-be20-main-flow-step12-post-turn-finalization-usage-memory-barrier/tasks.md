## 1. Step 12 service foundation

- [x] 1.1 Tạo module/service Step 12 (`PostTurnFinalizationService`) tách khỏi orchestrator để điều phối usage finalization + consolidation subtasks.
- [x] 1.2 Wire orchestrator gọi service mới sau Step 11 persist success; bảo toàn lifecycle sync trong cùng request runtime path.
- [x] 1.3 Chuẩn hóa state machine cho `usage_accounting_status` và `step12_finalization_status` với mapping `finalized|partial|failed` rõ ràng.

## 2. Usage finalization và quota update

- [x] 2.1 Hoàn thiện usage aggregation theo `llm_usage_events` của `turn_id`, persist đầy đủ token totals trên `ChatTurn`.
- [x] 2.2 Hoàn thiện quota consume + persist `quota_window_before`, `quota_window_after`, `quota_exhausted_after_turn` theo output Step 12.
- [x] 2.3 Implement policy khi usage finalization fail: log operational error + persist status `failed/partial`, không thêm gate block mới.

## 3. Identity-state persistence models

- [x] 3.1 Thêm models/migrations cho persistence `user_profile`, `user_preference`, `user_state` theo owner (`user` xor `guest_identity`) + indexes/constraints.
- [x] 3.2 Implement repository/service layer cho upsert/read identity-state records.
- [x] 3.3 Cập nhật `RuntimeBundleService` Step 6 để load 3 identity-state fields từ DB, fallback `{}` khi chưa có dữ liệu.

## 4. Consolidation subtasks implementation

- [x] 4.1 Implement LLM subtask `context_summary_updater` qua `LLMGateway` + parse/validate output + fallback giữ summary cũ khi fail.
- [x] 4.2 Implement LLM subtask `long_term_memory_extractor` qua `LLMGateway` + dedup/upsert `MemoryItem` + fallback không ghi memory khi fail.
- [x] 4.3 Implement rule-based update `user_state` từ `user_state_signals`.
- [x] 4.4 Implement rule-based update `user_profile` từ `explicit_profile_facts`.
- [x] 4.5 Implement rule-based update `user_preference` từ `style_signals` với evidence threshold.
- [x] 4.6 Persist consolidation output meta tối thiểu: `updated_context_summary_id`, `memory_items_upserted_count`, `profile_fields_updated`, `preference_fields_updated`, `updated_user_state`, `consolidation_log_meta`.

## 5. Contract updates và barrier semantics

- [x] 5.1 Giữ contract SSE `done` đúng semantics response đã persist (không đại diện Step 12 hoàn tất) và đồng bộ metadata quota hậu turn theo contract hiện hành.
- [x] 5.2 Giữ đúng barrier semantics ở request gate: chỉ block khi previous turn `pending/processing`; cho pass khi `finalized/partial/failed`.
- [x] 5.3 Cập nhật `project-spec/frontend-backend-contract.md` cho `done` payload mới và semantics quota/finalization status.

## 6. Tests và kiểm chứng

- [x] 6.1 Thêm unit tests cho Step 12 usage aggregation/quota update (success + quota exhausted after turn).
- [x] 6.2 Thêm tests cho matrix `step12_finalization_status` và `usage_accounting_status` (finalized/partial/failed).
- [x] 6.3 Thêm tests cho context summary updater fallback và long-term memory extractor fallback.
- [x] 6.4 Thêm tests cho rule-based updates của user_state/profile/preference và Step 6 load persisted identity-state.
- [x] 6.5 Thêm/cập nhật tests cho request gate barrier semantics và SSE done semantics (response persisted, không suy diễn Step 12 đã finalized).
- [x] 6.6 Chạy `openspec validate --changes be20-main-flow-step12-post-turn-finalization-usage-memory-barrier --strict` và bộ test runtime/chat/memory/llm_ops liên quan.
