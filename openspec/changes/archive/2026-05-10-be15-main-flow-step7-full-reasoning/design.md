## Overview
BE-15 triển khai Step 7 như một reasoning stage độc lập, dùng operation `full_reasoning` và trả `reasoning_result` schema đóng để Step 8 consume. Step 7 không tạo response user cuối cùng và không reload DB contexts.

## Runtime Placement
- Chỉ chạy ở continue path: sau Step 6, trước Step 8.
- Preconditions:
  - `triage_decision = continue_to_full_reasoning`;
  - `runtime_bundle` đã assemble xong ở Step 6.

## Input Contract
Step 7 nhận input runtime:
- bắt buộc: `runtime_bundle`
  - `current_message`
  - `recent_turns`
  - `context_summary`
  - `user_profile`
  - `user_preference`
  - `user_state`
  - `long_term_memory`
- optional: `reasoning_control`
  - `is_corrective_retry`
  - `retry_count`
  - `validation_error_feedback`

Rule:
- Step 7 chỉ đọc dữ liệu từ `runtime_bundle` (no DB reload).
- Nếu `reasoning_control` không có: chạy normal reasoning.
- Nếu `reasoning_control.is_corrective_retry = true`: chạy corrective reasoning với feedback từ Step 8.

## LLM Operation Routing
- Bắt buộc gọi `LLMGateway.complete(operation_key=OperationKey.FULL_REASONING, ...)`.
- Prompt messages gồm:
  - system instruction cho schema output đóng;
  - user/runtime context từ `runtime_bundle`;
  - corrective block nếu có `reasoning_control`.
- Không hard-code provider/model.

## Reasoning Result Schema
Step 7 phải chuẩn hóa output về object gồm đúng các field:
- `risk_flags` (enum list đóng)
- `intent` (enum đóng)
- `action_recommended` (enum đóng)
- `is_context_sufficient` (bool)
- `required_next_slots` (enum list đóng)
- `case_slots` (object schema cố định)
- `turn_strategy` (object: `focus`, `angle`, `avoid`)
- `explicit_profile_facts` (string list)
- `style_signals` (enum list đóng)
- `user_state_signals` (enum list đóng)
- `suggested_chat_display_name` (string|null)

Sanitization/Validation:
- Unknown enum values bị loại hoặc map về canonical safe defaults.
- Missing required fields được backfill bằng defaults an toàn.
- `suggested_chat_display_name` chỉ giữ khi hợp lệ; ngược lại `null`.

## Failure and Safe Fallback
- Gateway/provider lỗi transient: Step 7 retry tối đa 2 lần trong cùng turn.
- Nếu sau 2 lần retry vẫn lỗi: để exception path hiện tại xử lý và trả lỗi cho FE.
- Không fallback `reasoning_result` khi gateway/provider fail.
- Output parse/schema fail: Step 7 không crash runtime; dùng canonical fallback `reasoning_result` để Step 8 tiếp tục kiểm tra/sửa.

## Runtime State Updates
- `runtime_bundle["reasoning_result"]` được set sau Step 7.
- Thêm `RuntimeState.reasoning_retry_count` để Step 8/loop quản lý corrective retry.
- Không ghi DB side effects ở Step 7.

## Tests
- Unit tests cho:
  - gọi đúng operation `full_reasoning`;
  - normal path trả reasoning_result canonical;
  - corrective retry path include feedback control;
  - parse/schema invalid -> fallback canonical;
  - Step 7 không reload DB contexts ngoài `runtime_bundle` input.
