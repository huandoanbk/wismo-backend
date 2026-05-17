## Why
Step 7 (Full reasoning) trong Main Flow/MVP hiện chưa được triển khai đúng contract: runtime vẫn dùng stub `reasoning_result` tối thiểu và chưa gọi operation `full_reasoning` qua LLM Gateway. Điều này làm Step 8/9/10 không có dữ liệu reasoning canonical để validate, chọn response mode, và assemble prompt theo flow chuẩn.

## What Changes
- Triển khai Step 7 đúng Main Flow:
  - gọi LLM operation `full_reasoning` qua `LLMGateway` (không gọi provider trực tiếp);
  - input chỉ đọc từ `runtime_bundle` đã assemble ở Step 6;
  - hỗ trợ `reasoning_control` optional cho corrective retry path khi Step 8 yêu cầu;
  - parse + validate output thành `reasoning_result` schema đóng/canonical.
- Chuẩn hóa error/fallback của Step 7:
  - nếu gateway/provider fail, runtime retry tối đa 2 lần cho lỗi transient rồi mới fail request;
  - nếu quá số lần retry vẫn fail thì trả lỗi cho FE (không fallback `reasoning_result`);
  - nếu output reasoning invalid schema thì mới normalize về `reasoning_result` canonical để Step 8 xử lý tiếp.
- Đồng bộ tests unit/integration cho Step 7 contract.

## Scope
- Trong scope:
  - `runtime/orchestrator.py` Step 7 logic;
  - helper/schema parser cho `reasoning_result`;
  - tests cho normal reasoning + corrective retry + invalid output fallback;
  - cập nhật OpenSpec spec delta cho capability Step 7.
- Ngoài scope:
  - thay đổi logic Step 8 selection policy;
  - thay đổi payload SSE Step 11;
  - refactor enum/flow ngoài Step 7.

## Impact
- Runtime có `reasoning_result` đầy đủ, ổn định cho Step 8 trở đi.
- Giữ đúng nguyên tắc fail-closed của LLM operation routing qua registry.
- Giảm lệch giữa Main Flow/MVP spec và implementation hiện tại.
