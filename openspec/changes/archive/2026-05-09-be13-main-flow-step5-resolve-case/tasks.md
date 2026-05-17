## 1. Spec Alignment và Data Model

- [x] 1.1 Chốt requirement deltas cho `runtime-case-resolution` và `chat-context-resolution` theo Main Flow Step 5.
- [x] 1.2 Thiết kế schema state cho pending case resolution trên `Chat` (fields + invariants).
- [x] 1.3 Tạo migration và kiểm tra backward-safe defaults cho dữ liệu hiện hữu.

## 2. Domain Services cho Step 5

- [x] 2.1 Implement service resolve existing chat flow (`chat.case_id` đã có, pending state path).
- [x] 2.2 Implement new chat flow cho identity chưa có case history (create new case trực tiếp).
- [x] 2.3 Implement `case_detector` path cho identity có case history với input `opening_input_text` + tối đa 10 case summaries.
- [x] 2.4 Implement branch handling cho detector outputs: `matched_existing_case`, `new_case`, `confirm_required`.

## 3. Pending Re-resolution State Machine

- [x] 3.1 Implement pending state enter/exit transitions (`is_pending_case_confirmation`, `pending_confirm_turn_count`).
- [x] 3.2 Implement `case_reresolution_classifier` path với outputs `use_existing_case`, `create_new_case`, `still_ambiguous`.
- [x] 3.3 Implement pending counter policy và auto-resolve khi ambiguous đạt 3 lượt.
- [x] 3.4 Đảm bảo clear pending state đúng lúc sau resolve thành công hoặc auto-resolve.

## 4. Runtime Orchestrator Wiring

- [x] 4.1 Refactor Step 5 orchestration để dùng service mới và trả status rõ ràng khi `case_id` resolved hoặc `null`.
- [x] 4.2 Đảm bảo turn created ở Step 3 luôn được bind `turn.case_id` tại Step 5, không tạo turn phụ.
- [x] 4.3 Chuẩn hóa fallback path khi detector/re-resolution classifier fail theo runtime policy.

## 5. LLM Operation Routing và Config

- [x] 5.1 Wire `case_detector` và `case_reresolution_classifier` qua LLM Gateway operation registry.
- [x] 5.2 Bổ sung seed/config validation để phát hiện operation thiếu/inactive/mapping invalid.
- [x] 5.3 Bổ sung runtime metadata tối thiểu cho audit nguồn quyết định case resolution.

## 6. Tests và Verification

- [x] 6.1 Viết unit tests cho toàn bộ Step 5 branches (existing/new/pending/re-resolution/auto-resolve).
- [x] 6.2 Viết regression tests cho turn-binding invariant giữa Step 3 và Step 5.
- [x] 6.3 Viết failure-path tests cho classifier fail, malformed output, và fallback behavior.
- [x] 6.4 Chạy `manage.py check`, `pytest`, `ruff check .`, `makemigrations --check --dry-run` và xử lý failures.
