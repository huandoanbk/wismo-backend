## Context

Step 5 trong `project-spec/Main-flow.md` yêu cầu một state machine rõ ràng cho case resolution: existing chat reuse case, new chat + detector, pending confirmation, re-resolution classifier, và auto-resolve sau 3 pending turns. Code hiện tại mới có nhánh tối giản `chat.case_id` có thì dùng, không có thì create new case, nên chưa đủ để giữ continuity đúng cho các chat mới có lịch sử case phong phú.

Spec References:
- `project-spec/Main-flow.md` (Step 5, mục B.2/B.3/B.4)
- `project-spec/WISMO_MVP_Spec.md` (A.6.2.2 Step 5)
- `openspec/specs/chat-context-resolution/spec.md`
- `openspec/specs/runtime-triage-routing/spec.md`
- `openspec/specs/llm-gateway-routing/spec.md`

## Goals / Non-Goals

**Goals:**
- Implement đầy đủ Step 5 runtime behavior theo Main Flow.
- Đảm bảo mọi path `continue_to_full_reasoning` trả trạng thái resolution rõ ràng, cho phép `case_id = null` khi classifier unavailable.
- Tách rõ quyết định giữa deterministic branch (existing/no-history) và classifier branch (history/pending).
- Giữ service boundary: orchestration ở `runtime`, persistence + domain logic ở `chat` services, model routing qua `llm_ops` gateway.

**Non-Goals:**
- Không thay đổi API endpoint public hoặc SSE shape ở sprint này.
- Không triển khai Step 6+ logic mới.
- Không tối ưu ranking/relevance nâng cao cho case summaries beyond phạm vi “tối đa 10 recent summaries”.

## Decisions

1. Thêm state fields cho pending case resolution trên `Chat`
- Chọn thêm các field canonical để biểu diễn state machine Step 5 (ví dụ: `is_pending_case_confirmation`, `pending_confirm_turn_count`).
- Lý do: tránh encode pending state trong metadata tự do, giúp query/test/migration rõ ràng.
- Alternative đã cân nhắc: lưu JSON metadata trong chat/runtime metadata. Bỏ vì khó enforce invariant và khó index/debug.

2. Tạo service chuyên trách Step 5 trong `chat/services.py`
- Tạo một domain service (ví dụ `CaseResolutionService`) nhận `identity`, `chat`, `turn`, `message`, trả `resolved_case` + trạng thái pending transition.
- Lý do: giữ `RuntimeOrchestrator` mỏng, testable theo unit state transitions.
- Alternative: dồn toàn bộ logic vào `runtime/orchestrator.py`. Bỏ vì branch nhiều, khó maintain.

3. Bắt buộc route classifier qua LLM Gateway operation keys
- `case_detector` và `case_reresolution_classifier` phải gọi bằng `OperationKey` tương ứng, không direct provider.
- Lý do: bám fail-closed routing foundation BE-7, admin-configurable.
- Alternative: hardcode provider/model trong Step 5. Bỏ vì lệch kiến trúc hiện tại.

4. Pending counter áp dụng trên mỗi message mới khi classifier trả `still_ambiguous`
- Counter tăng đúng 1 mỗi turn ambiguous trong pending mode; đạt 3 thì auto-create case.
- Lý do: bám main-flow B.4.2/B.4.3, đảm bảo liveness để runtime không bị kẹt indefinite.
- Alternative: reset counter theo thời gian hoặc theo triage confidence. Bỏ vì chưa có trong MVP spec.

5. Turn binding invariant
- Turn được tạo tại Step 3 phải là turn duy nhất của request; Step 5 chỉ update `turn.case_id`, không tạo turn mới.
- Lý do: giữ consistency với `chat-context-resolution` và downstream accounting/usage.

## Risks / Trade-offs

- [Risk] Classifier output không ổn định (`confirm_required`, `use_existing_case`, ...) → Mitigation: parse/normalize output strict enum + fallback `case_id = null` + status rõ ràng.
- [Risk] Race condition khi nhiều request cùng chat pending → Mitigation: transaction + row lock khi update chat pending state/counter.
- [Risk] Auto-resolve tạo case mới có thể sai ngữ nghĩa hơn kỳ vọng user → Mitigation: giữ logic minh bạch, log reason tag, và cho phép future sprint tinh chỉnh classifier/policy.
- [Risk] Migration field mới tác động dữ liệu hiện hữu → Mitigation: default-safe values, backfill đơn giản, không phá flow chat đã có case_id.

## Migration Plan

1. Thêm migration cho các field pending case resolution trên `Chat`.
2. Backfill giá trị default cho dữ liệu cũ (`is_pending_case_confirmation=false`, `pending_confirm_turn_count=0`).
3. Triển khai service + orchestrator wiring phía sau feature-compatible path.
4. Bổ sung/seed operation config cần thiết cho `case_detector` và `case_reresolution_classifier` nếu thiếu.
5. Chạy verification suite: `manage.py check`, `pytest`, `ruff check .`, `makemigrations --check --dry-run`.

Rollback:
- Revert code + migration trong change nếu chưa deploy production.
- Nếu đã migrate, dùng migration rollback theo thứ tự ngược và disable Step 5 classifier path qua config.

## Open Questions

- Không còn open question cho BE-13 sau khi chốt.
