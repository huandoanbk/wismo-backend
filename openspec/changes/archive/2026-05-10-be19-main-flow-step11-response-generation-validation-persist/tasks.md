## 1. Step 11 pipeline foundation

- [x] 1.1 Tạo service/module Step 11 để điều phối generate -> validate -> retry/fallback -> persist/stream.
- [x] 1.2 Tích hợp `OperationKey.RESPONSE_GENERATION` qua `LLMGateway` để tạo `candidate_response_text`.
- [x] 1.3 Triển khai logic validation cơ bản (empty/whitespace/coherence baseline) trước validator LLM.
- [x] 1.4 Tích hợp `OperationKey.RESPONSE_VALIDATION` qua `LLMGateway` và normalize output contract (`pass`, `severity`, `error_codes`, `rewrite_instruction`, `fallback_recommended`).

## 2. Retry / feedback / fallback flow

- [x] 2.1 Triển khai `generation_retry_count` và corrective retry budget tối đa 2 lần.
- [x] 2.2 Triển khai `generation_validation_feedback` (`error_codes`, `rewrite_instruction`, `keep_constraints`) và gọi lại Step 10 để rebuild prompt trước lần generate lại.
- [x] 2.3 Cập nhật Step 10 service để nhận feedback-aware rebuild nhưng không override `response_method`/`final_safety_state`.
- [x] 2.4 Cleanup Step 10 metadata: xoá `effective_builder_name` khỏi output contract và update các điểm tiêu thụ/assertion liên quan.
- [x] 2.5 Triển khai safe fallback response path (ASK clarify hoặc LISTEN fallback) khi exhausted retry.

## 3. Persist / stream contract

- [x] 3.1 Persist final response (success hoặc fallback) cùng runtime metadata tối thiểu: retry count, validation outcome, fallback flag.
- [x] 3.2 Đảm bảo thứ tự stream `response` rồi `done` sau khi persist thành công.
- [x] 3.3 Đảm bảo validator payload bám đúng input contract Step 11.4 từ Main Flow/MVP spec.

## 4. Tests và kiểm chứng

- [x] 4.1 Thêm unit tests cho generate+validate success path.
- [x] 4.2 Thêm unit tests cho retry loop với feedback rebuild Step 10.
- [x] 4.3 Thêm unit tests cho exhausted retry -> safe fallback ASK/LISTEN.
- [x] 4.4 Thêm unit tests cho validator input completeness (bao gồm TEACH phải có retrieval context).
- [x] 4.5 Thêm/điều chỉnh tests xác nhận `prompt_debug_meta` không còn `effective_builder_name`.
- [x] 4.6 Chạy `openspec validate --changes be19-main-flow-step11-response-generation-validation-persist --strict` và test runtime liên quan.
