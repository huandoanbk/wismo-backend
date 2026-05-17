## Context

BE-10 đã hoàn tất gate + SSE transport foundation. Theo `project-spec/Main-flow.md`, bước kế tiếp bắt buộc là Step 3: resolve chat context tối thiểu trước khi vào triage Step 4. Hiện repo cần một change đúng scope BE-11-main để tránh trộn requirements của các đề tài khác (guest idle TTL/auto-attach). Quy tắc nguồn sự thật cho change này:
- `project-spec/WISMO_MVP_Spec.md` (chat/case/turn model, runtime continuity)
- `project-spec/Main-flow.md` (Step 3 behavior)
- `project-spec/frontend-backend-contract.md` (SSE payload contract)

## Goals / Non-Goals

**Goals:**
- Chốt logic Step 3 thành service/runtime path rõ ràng, deterministic, testable.
- Đảm bảo sau gate pass luôn có đủ context tối thiểu cho Step 4:
  - `chat_id` resolved
  - `turn_id` mới
  - `ChatTurn` persisted với `user_message_text`
- Giữ contract FE nhất quán khi request không có `chat_id` (implicit create).
- Không đưa lại `client_turn_id` vào runtime contract.

**Non-Goals:**
- Không triển khai triage/hard routing Step 4 (BE-12).
- Không đổi quota policy, consent logic, attach logic, hoặc auth/session behavior.
- Không mở rộng sang memory consolidation Step 12.

## Decisions

1. Tách Step 3 thành boundary rõ trong runtime orchestrator
- Quyết định: tạo hoặc dùng service function chuyên trách `resolve_chat_context(...)` (nằm ở `chat.services` hoặc `runtime` adapter) để orchestration gọi một điểm.
- Lý do: giữ `views`/`orchestrator` mỏng, dễ test branch create-vs-load, tránh lặp logic.
- Alternative bị loại: viết inline trực tiếp trong view/orchestrator; nhanh nhưng khó kiểm thử và dễ drift contract.

2. Persist opening input chỉ khi chat mới được tạo
- Quyết định: nhánh không có `chat_id` sẽ tạo chat mới + set `opening_input_text = message` một lần.
- Lý do: đúng Main Flow Step 3; giữ semantic “opening input” ổn định cho analytics/case bootstrap sau này.
- Alternative bị loại: luôn overwrite `opening_input_text`; sai nghiệp vụ continuity.

3. Turn intake record tạo ngay tại Step 3, bind case ở Step 5
- Quyết định: tạo `ChatTurn` ngay sau khi chat context resolved, set trạng thái khởi tạo phù hợp stream lifecycle hiện tại, lưu `user_message_text`, và để `case_id = null` tại Step 3.
- Quyết định bổ sung: sau khi Step 5 resolve case xong, hệ thống cập nhật `ChatTurn.case_id` theo case đã resolve.
- Lý do: downstream Step 4+ cần anchor turn cố định để persist/update kết quả an toàn.
- Alternative bị loại: trì hoãn tạo turn đến Step 11; làm yếu khả năng audit và error recovery sớm.

4. Backend là nguồn sinh `turn_id` duy nhất
- Quyết định: không nhận `client_turn_id`; `turn_id` sinh server-side và expose qua SSE `done` event.
- Lý do: repo đã loại bỏ client idempotency key; giảm mismatch FE/BE.
- Alternative bị loại: cho phép client gửi idempotency key trong BE-11; trái với trạng thái hiện tại.

5. Contract-first update cho implicit chat creation
- Quyết định: cập nhật `project-spec/frontend-backend-contract.md` đồng bộ code cho behavior “no chat_id => backend create chat”.
- Lý do: FE/BFF cần biết chính xác khi nào phải upsert local chat id từ stream.
- Alternative bị loại: chỉ thay code, không cập nhật contract; tạo drift liên repo.

## Risks / Trade-offs

- [Risk] Race condition khi 2 request đồng thời cho cùng chat gây `turn_in_progress`/ordering khó đoán.  
  → Mitigation: giữ barrier check từ BE-10, thêm test concurrent-lite theo phạm vi cho phép.

- [Risk] Trạng thái khởi tạo `ChatTurn.status` không khớp SSE pipeline hiện hữu.  
  → Mitigation: dùng enum/status constants canonical đã có; test event order + persisted status transition.

- [Risk] FE parse stream trước khi `done` đến, chưa có `chat_id` local cho chat mới.  
  → Mitigation: contract ghi rõ FE chỉ commit thread identity khi nhận `done` chứa `chat_id`/`turn_id`.

- [Risk] Scope creep sang Step 4 triage vì cùng orchestrator path.  
  → Mitigation: task checklist khóa phạm vi Step 3-only, không thêm triage decision logic.

## Migration Plan

- Không bắt buộc migration ở giai đoạn propose.
- Nếu khi apply phát hiện thiếu field cho turn intake/status, tạo migration nhỏ đúng scope BE-11-main.
- Rollback: revert code path Step 3 và migration liên quan (nếu có), giữ nguyên BE-10 gate/transport behavior.

## Open Questions

- Không còn open question ở mức spec cho BE-11-main; behavior chính đã chốt theo MVP spec + Main Flow.
