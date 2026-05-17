## Why

Main Flow đã có Step 5 chi tiết, nhưng code hiện tại mới dừng ở case resolution tối giản nên chưa đáp ứng đầy đủ nhánh `confirm_required`, pending re-resolution, và auto-resolve sau số lượt pending tối đa. Cần một sprint BE-13 để đưa Step 5 về đúng hành vi trong `project-spec/Main-flow.md` và `project-spec/WISMO_MVP_Spec.md`.

## What Changes

- Bổ sung đầy đủ runtime behavior cho Main Flow Step 5: existing chat flow, new chat flow, case detector output branches (`matched_existing_case`, `new_case`, `confirm_required`), pending case resolution, re-resolution classifier, pending counter, và auto-resolve.
- Chuẩn hóa state machine cho chat pending-case để xử lý rõ nhánh `case_id = null` khi classifier unavailable, không phát sinh field ngoài spec đã chốt.
- Mở rộng dữ liệu và service boundary ở `chat`/`runtime` để quản lý pending counter và quyết định re-resolution một cách deterministic, audit được.
- Bổ sung/điều chỉnh contract nội bộ với LLM Gateway cho `case_detector` và `case_reresolution_classifier` (operation-level), fail-closed theo policy routing đã có.
- Bổ sung test coverage regression cho toàn bộ nhánh Step 5 (bao gồm edge cases ownership, pending overflow, và clear pending state).

## Capabilities

### New Capabilities
- `runtime-case-resolution`: Đặc tả đầy đủ Step 5 Resolve case cho runtime path `continue_to_full_reasoning`, gồm detector + pending resolution + auto-resolve.

### Modified Capabilities
- `chat-context-resolution`: Làm rõ handoff contract giữa Step 3 và Step 5 để turn được tạo ở Step 3 luôn được bind `case_id` đúng tại Step 5 trước khi sang Step 6.

## Impact

- Affected specs: `openspec/specs/chat-context-resolution/spec.md` (modified) và capability mới `runtime-case-resolution`.
- Affected modules dự kiến: `chat/models.py`, `chat/services.py`, `runtime/orchestrator.py`, `llm_ops` operation wiring, migrations liên quan chat/case pending state.
- Affected tests: unit/integration cho runtime step flow và case resolution branching.
- Không đổi public endpoint path ở sprint này; thay đổi tập trung vào runtime behavior và persistence/state transitions nội bộ.
