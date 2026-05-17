## 1. Runtime Step 7 implementation
- [x] 1.1 Thay stub `_full_reasoning` bằng logic gọi `OperationKey.FULL_REASONING` qua `LLMGateway`.
- [x] 1.2 Tạo prompt assembly cho normal reasoning từ `runtime_bundle` canonical fields.
- [x] 1.3 Bổ sung corrective path khi có `reasoning_control` (`is_corrective_retry=true`).
- [x] 1.4 Bổ sung retry tối đa 2 lần cho lỗi gateway/provider transient ở Step 7; quá giới hạn thì raise lỗi về FE.

## 2. Reasoning result schema normalization
- [x] 2.1 Tạo parser/normalizer để ép output về schema đóng `reasoning_result`.
- [x] 2.2 Thêm safe defaults cho required fields khi output thiếu/sai kiểu.
- [x] 2.3 Chuẩn hóa enum list/object fields theo Main Flow/MVP contract.

## 3. Runtime state integration
- [x] 3.1 Ghi `reasoning_result` vào `runtime_bundle` sau Step 7.
- [x] 3.2 Ghi/duy trì `reasoning_retry_count` trong `RuntimeState` (không ghi vào `runtime_bundle`).
- [x] 3.3 Đảm bảo Step 7 không reload DB context đã có trong `runtime_bundle`.

## 4. Test coverage
- [x] 4.1 Cập nhật unit tests orchestrator cho Step 7 gọi đúng operation + payload.
- [x] 4.2 Thêm test corrective retry input handling.
- [x] 4.3 Thêm test parse/schema fail fallback canonical.
- [x] 4.4 Chạy test liên quan runtime/orchestrator + llm gateway mocks.
