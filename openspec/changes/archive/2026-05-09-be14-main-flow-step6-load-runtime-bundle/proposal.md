## Why

Step 6 hiện mới là stub trong code và chưa bám đầy đủ Main Flow/MVP spec cho cách load `runtime_bundle` từ dữ liệu thực tế. Sau BE-13, `case_id` có thể null ở một số path nên Step 6 cần được chuẩn hóa rõ để runtime vẫn chạy ổn định, không suy diễn sai.

## What Changes

- Implement đầy đủ Main Flow Step 6: load `recent_turns`, `context_summary`, `user_profile`, `user_preference`, `user_state`, `long_term_memory` và assemble `runtime_bundle` chuẩn cho Step 7.
- Chốt contract Step 6 cho cả hai path `case_id` đã resolve và `case_id = null`.
- Chuẩn hóa fallback rules khi retrieval/memory fail: không crash runtime, dùng object/list rỗng theo contract.
- Tách service boundary cho dữ liệu Step 6 để orchestrator chỉ điều phối, không query dàn trải trong step function.
- Bổ sung test coverage đảm bảo runtime bundle assemble một lần và downstream steps không reload lại các field core trong cùng turn.

## Capabilities

### New Capabilities
- `runtime-bundle-loading`: Đặc tả Step 6 Load runtime bundle gồm input condition, data loading contract, null-case behavior, fallback behavior, và ownership rule cho downstream steps.

### Modified Capabilities
- `runtime-case-resolution`: Cập nhật handoff contract giữa Step 5 -> Step 6 để xác nhận Step 6 được phép chạy với `case_id = null` và phải xử lý field liên quan theo contract rỗng.

## Impact

- Affected specs: capability mới `runtime-bundle-loading`, cập nhật `runtime-case-resolution`.
- Affected modules dự kiến: `runtime/orchestrator.py`, service layer cho runtime bundle data loading, integration points với `memory` và `knowledge` retrieval path.
- Affected tests: unit/regression cho Step 6 assemble contract, null-case path, fallback path, và runtime bundle ownership rule.
- Không đổi endpoint public; thay đổi tập trung vào runtime internal behavior.
