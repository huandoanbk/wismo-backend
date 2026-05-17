## Context

Main Flow Step 12 và MVP spec yêu cầu post-turn finalization chạy sync trong cùng turn lifecycle, gồm 2 nhóm việc: (1) usage/quota accounting bắt buộc và (2) memory/state consolidation cho turn kế tiếp. Code hiện tại mới hoàn thành usage aggregation + quota consume cơ bản trong `runtime/orchestrator.py::_post_turn_finalization`, chưa có pipeline đầy đủ cho context summary updater, long-term memory extractor, và persistence cho `user_profile/user_preference/user_state`.

Ngoài ra, Step 6 hiện load `user_profile/user_preference/user_state` bằng stub `{}`, nên dù Step 12 có rule update thì turn kế tiếp vẫn không đọc được state đã học. Barrier ở request gate đã đúng hướng (chỉ chặn khi `step12_finalization_status` là `pending/processing`) và theo quyết định owner sẽ giữ nguyên: usage fail chỉ log + status, không thêm gate chặn mới.

## Goals / Non-Goals

**Goals:**
- Hoàn thiện Step 12 service theo đúng Main Flow 12.1-12.13.
- Giữ usage finalization/quota update là mandatory; persist status `finalized|partial|failed` rõ ràng.
- Thêm persistence models cho `user_profile`, `user_preference`, `user_state`; Step 6 load thật từ DB, Step 12 update theo rules.
- Thêm 2 LLM subtasks Step 12 qua `LLMGateway` (`context_summary_updater`, `long_term_memory_extractor`) với failure-safe fallback.
- Persist consolidation outputs vào turn metadata để audit/debug.
- Giữ barrier semantics: chỉ block khi previous turn còn `pending/processing`.

**Non-Goals:**
- Không chuyển Step 12 sang Celery/outbox async.
- Không xây dashboard báo cáo usage vận hành.
- Không thay đổi policy gate để chặn thêm khi `usage_accounting_status=failed`.
- Không mở rộng sang memory vector re-index pipeline nâng cao (chỉ hook/placeholder nếu cần).

## Decisions

### 1) Tách Step 12 thành service riêng `PostTurnFinalizationService`
- Quyết định: đưa toàn bộ logic Step 12 ra module riêng (ví dụ `runtime/finalization.py`), orchestrator chỉ gọi service.
- Lý do: Step 12 đã vượt quá scope của một method đơn; tách service giúp test độc lập theo từng subtask và giảm rủi ro coupling với Step 7-11.
- Alternative đã cân nhắc: giữ trong orchestrator. Loại vì khó maintain, khó unit-test partial failure matrix.

### 2) Áp dụng trạng thái hai lớp: `usage_accounting_status` và `step12_finalization_status`
- Quyết định: usage có status riêng (`finalized|partial|failed`) và Step 12 tổng thể có status riêng (`finalized|partial|failed`), với mapping deterministic.
- Lý do: Main Flow/MVP yêu cầu usage mandatory nhưng consolidation subtasks có thể partial; cần tách rõ để audit và gate behavior chính xác.
- Alternative: một status duy nhất. Loại vì mất khả năng phân biệt usage fail vs consolidation fail.

### 3) Thêm identity-state persistence models trong app `memory`
- Quyết định: tạo 3 model mới `UserProfileState`, `UserPreferenceState`, `UserStateSnapshot` (tên có thể điều chỉnh theo convention) trong app `memory`, owner model giống pattern `MemoryItem` (exactly-one-owner).
- Lý do: tránh mở rộng `accounts.User` bằng JSON blobs, giữ group dữ liệu runtime-learning cùng domain memory/state, dễ query và migration an toàn.
- Alternative: nhét JSON vào `accounts.User`. Loại vì ghép cứng identity với runtime-learning, khó evolve schema/evidence metadata.

### 4) Step 12 LLM subtasks đi qua operation registry sẵn có
- Quyết định: dùng `OperationKey.CONTEXT_SUMMARY_UPDATER` và `OperationKey.LONG_TERM_MEMORY_EXTRACTOR` qua `LLMGateway`; operation phải được cấu hình từ admin như các step trước.
- Lý do: đồng nhất fail-closed routing + usage capture + model swap không sửa code.
- Alternative: gọi provider trực tiếp. Loại vì vi phạm gateway boundary của MVP.

### 5) Giữ semantics `done` đúng Main Flow/MVP
- Quyết định: giữ `done` là tín hiệu response đã persist; không dùng `done` để đại diện Step 12 đã finalized.
- Lý do: Main Flow/MVP định nghĩa rõ `done` không thay thế Step 12; Step 12 vẫn là lifecycle sync riêng với barrier/status riêng.
- Alternative: ép `done` chờ Step 12 hoàn tất. Loại vì làm lệch semantics source-of-truth.

### 6) Usage fail policy: log + status, không thêm gate chặn mới
- Quyết định: nếu usage finalization fail thì persist status + log + runtime metadata; request gate vẫn chỉ block theo pending/processing barrier.
- Lý do: quyết định owner; tránh chặn cứng user flow ngoài quota/turn barrier hiện hành.
- Alternative: fail-closed gate cho turn kế tiếp. Loại theo quyết định owner.

## Risks / Trade-offs

- [Risk] Sai mapping state signals/facts làm cập nhật profile/preference/state nhiễu.
  → Mitigation: rule engine deterministic + threshold guard + test matrix cho conflict/low-confidence.

- [Risk] Step 12 dài hơn làm tăng latency trước `done` nếu giữ sync chặt.
  → Mitigation: tối ưu prompt payload compact, giữ logic pure/rule-based nhẹ, đo timing trong metadata.

- [Risk] Partial failure branch phức tạp gây status drift.
  → Mitigation: state machine rõ cho `usage_accounting_status` và `step12_finalization_status`, test đầy đủ finalized/partial/failed.

- [Risk] Migration model mới ảnh hưởng dữ liệu owner consistency.
  → Mitigation: reuse exactly-one-owner constraint pattern từ `chat`/`memory`, thêm indexes theo owner.

## Migration Plan

1. Tạo migrations cho identity-state models + indexes/constraints.
2. Tạo/đảm bảo seed operation configs cho Step 12 LLM operations nếu thiếu.
3. Implement `PostTurnFinalizationService` + wire vào orchestrator.
4. Update `RuntimeBundleService` để đọc persisted identity-state.
5. Update SSE semantics/docs để FE không suy diễn `done` = Step 12 finalized.
6. Thêm unit/integration tests cho Step 12 full matrix.
7. Chạy `ruff`, `pytest` scope runtime/chat/memory/llm_ops, `openspec validate --strict`.

Rollback:
- Revert code + migrations của BE-20.
- Nếu rollback sau migrate, giữ backward-compatible read fallback `{}` khi records chưa tồn tại.

## Open Questions

- Không còn blocker mở: owner đã chốt bổ sung model persistence và policy usage fail là chỉ log, không chặn gate.
