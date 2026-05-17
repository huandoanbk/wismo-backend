## ADDED Requirements

### Requirement: Step 12 chỉ chạy sau khi Step 11 đã persist response thành công
Runtime MUST chạy Step 12 chỉ khi assistant response của turn hiện tại đã được persist ở Step 11 và turn nằm trong continue path của runtime lifecycle đồng bộ.

#### Scenario: Step 12 entry
- **WHEN** turn đã có assistant response persisted từ Step 11
- **THEN** runtime MUST chuyển `step12_finalization_status` sang `processing` và chạy Step 12 sync

### Requirement: Step 12 usage finalization phải chốt token usage theo llm_usage_events của turn
Runtime MUST aggregate toàn bộ `llm_usage_events` theo `turn_id` để tính `turn_token_usage` gồm `input_tokens`, `cached_input_tokens`, `output_tokens`, `cache_write_tokens`, `total_billable_tokens`, `total_observed_tokens`.

#### Scenario: Usage aggregation success
- **WHEN** Step 12 chạy usage finalization
- **THEN** runtime MUST persist đầy đủ token totals lên `ChatTurn`
- **AND** MUST dùng công thức billable theo MVP: input + cached_input + output + cache_write

### Requirement: Step 12 quota update phải cộng usage vào current window và chốt after-turn status
Runtime MUST cộng `turn_token_usage.total_billable_tokens` vào quota window hiện tại, persist `quota_window_before`, `quota_window_after`, và `quota_exhausted_after_turn`.

#### Scenario: Quota exhausted after turn
- **WHEN** quota window vượt ngưỡng sau khi cộng usage của turn
- **THEN** runtime MUST set `quota_exhausted_after_turn = true`
- **AND** MUST không sửa assistant response đã persist

### Requirement: Step 12 phải chạy context summary updater qua LLM operation registry
Runtime MUST gọi `OperationKey.CONTEXT_SUMMARY_UPDATER` qua `LLMGateway` để cập nhật cumulative `context_summary` theo Main Flow 12.5.

#### Scenario: Context summary meaningful update
- **WHEN** updater trả `has_meaningful_update = true` và summary hợp lệ
- **THEN** runtime MUST persist summary mới cho case hiện tại

#### Scenario: Context summary updater fail
- **WHEN** LLM call hoặc parse output fail
- **THEN** runtime MUST giữ nguyên summary cũ
- **AND** MUST ghi log lỗi + đánh dấu Step 12 không còn fully finalized

### Requirement: Step 12 phải chạy long-term memory extractor qua LLM operation registry
Runtime MUST gọi `OperationKey.LONG_TERM_MEMORY_EXTRACTOR` qua `LLMGateway` để lấy `candidate_memory_items[]`, sau đó dedup/upsert vào `memory.MemoryItem` theo owner + case.

#### Scenario: Memory upsert success
- **WHEN** extractor trả candidates đạt ngưỡng confidence và qua dedup
- **THEN** runtime MUST insert hoặc update memory items tương ứng

#### Scenario: Memory extractor fail
- **WHEN** LLM call hoặc parse output fail
- **THEN** runtime MUST không ghi memory mới
- **AND** MUST ghi log lỗi + đánh dấu Step 12 không còn fully finalized

### Requirement: Step 12 phải cập nhật user_state/user_profile/user_preference theo rule-based consolidation
Runtime MUST dùng `normalized_reasoning_result` để chạy rule-based update cho `user_state_signals`, `explicit_profile_facts`, `style_signals` và persist vào identity-state store.

#### Scenario: Rule-based update success
- **WHEN** có signals/facts hợp lệ theo schema
- **THEN** runtime MUST upsert state/profile/preference fields tương ứng

#### Scenario: Rule-based subtask fail
- **WHEN** một nhánh rule-based update fail
- **THEN** runtime MUST giữ state cũ của nhánh đó
- **AND** MUST không rollback persisted turn

### Requirement: Step 12 failure handling phải rõ status finalized partial failed
Runtime MUST kết thúc Step 12 với `step12_finalization_status` và `usage_accounting_status` phản ánh đúng kết quả thực thi, không để trạng thái mơ hồ.

#### Scenario: Full success
- **WHEN** usage + các consolidation subtasks hoàn tất không lỗi
- **THEN** runtime MUST set `step12_finalization_status = finalized`
- **AND** MUST set `usage_accounting_status = finalized`

#### Scenario: Partial completion
- **WHEN** usage finalized nhưng một hoặc nhiều consolidation subtasks fail-safe fallback
- **THEN** runtime MUST set `step12_finalization_status = partial`

#### Scenario: Usage finalization failed
- **WHEN** không thể finalize usage theo policy
- **THEN** runtime MUST set `usage_accounting_status = failed` hoặc `partial`
- **AND** MUST set `step12_finalization_status = failed` hoặc `partial` tương ứng
- **AND** MUST chỉ log/persist status, không thêm gate chặn mới ngoài barrier pending/processing

### Requirement: Barrier semantics chỉ chặn khi turn trước còn pending hoặc processing
Request gate MUST chỉ trả `turn_in_progress` khi turn gần nhất của chat có `step12_finalization_status` là `pending` hoặc `processing`.

#### Scenario: Previous turn finalized partial failed
- **WHEN** turn trước có `step12_finalization_status` là `finalized` hoặc `partial` hoặc `failed`
- **THEN** request gate MUST cho phép turn mới đi tiếp normal runtime

### Requirement: Step 12 phải persist consolidation outputs tối thiểu cho audit
Runtime MUST persist metadata/output tối thiểu gồm `turn_token_usage`, `quota_exhausted_after_turn`, `updated_context_summary_id`, `memory_items_upserted_count`, `profile_fields_updated`, `preference_fields_updated`, `updated_user_state`, `consolidation_log_meta`.

#### Scenario: Consolidation metadata persisted
- **WHEN** Step 12 kết thúc
- **THEN** turn runtime metadata MUST chứa consolidation outputs tối thiểu để audit/debug
