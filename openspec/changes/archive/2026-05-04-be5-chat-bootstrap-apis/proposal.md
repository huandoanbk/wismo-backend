## Why

Frontend/BFF hiện đã có `chat_id` là đơn vị thao tác chính, nhưng backend mới chỉ có chat send path. Thiếu lớp chat bootstrap khiến FE không thể tạo, liệt kê, hay mở lại chat một cách canonical trước khi gửi message, nên UI phải tự đoán state hoặc phụ thuộc vào runtime path.

BE-5 cần được làm ngay sau identity/consent/auth vì đây là lớp nối giữa session canonical và runtime flow: frontend phải nhìn thấy chat thread thật, backend phải kiểm soát ownership rõ ràng, và contract phải khóa payload/response trước khi runtime sâu hơn được triển khai.

## What Changes

- Thêm chat bootstrap APIs cho FE/BFF:
  - tạo chat mới;
  - liệt kê các chat thuộc identity hiện tại;
  - lấy chat detail kèm turn history tối thiểu.
- Hoàn thiện chat ownership boundary:
  - chỉ cho owner hiện tại xem được chat của mình;
  - chặn truy cập chat của identity khác;
  - giữ behavior nhất quán giữa guest và registered user.
- Chuẩn hóa dữ liệu trả về cho UI:
  - `chat_display_name` là tên user-facing canonical;
  - `opening_input_text` hỗ trợ chat mới được tạo từ turn đầu;
  - `case_id` được trả cho backend/client cần debug hoặc sync, nhưng không thay thế `chat_id` trong UI.
- Cập nhật `project-spec/frontend-backend-contract.md` cho create/list/detail chat, ownership errors, và turn history shape.
- Bổ sung tests cho chat bootstrap, ownership, và response contract.
- Không đổi semantics request gate core, nhưng phải dùng lại ownership/session boundary đã có thay vì tự query rời rạc.

## Capabilities

### New Capabilities

- `chat-bootstrap`: Quản lý create/list/detail chat, turn history tối thiểu, chat ownership, và UI-facing chat metadata cho MVP.

### Modified Capabilities

- None.

## Impact

- Code/API:
  - `chat` app: thêm views/urls/services cho create, list, detail, ownership, và history serialization.
  - `chat` model usage: tận dụng `Chat`, `Case`, `ChatTurn` hiện có, không đổi schema nếu contract hiện tại đã đủ.
  - `runtime`: tiếp tục dùng `chat_id` làm thread UI canonical, không tự suy đoán chat bootstrap state.
- Contract/docs:
  - cập nhật `project-spec/frontend-backend-contract.md` cho chat create/list/detail, ownership errors, và turn history payload.
- Tests:
  - thêm API tests cho create/list/detail chat;
  - thêm regression tests cho ownership deny, empty list, and turn history ordering.
- Dependencies:
  - không thêm dependency mới;
  - không mở rộng sang quota/runtime gateway/LLM gateway trong change này.
