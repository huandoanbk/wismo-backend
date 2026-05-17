## Spec References

- `project-spec/WISMO_MVP_Spec.md`
  - A.6.1 Mô hình conversation, chat và case
  - A.6.1.1 Dữ liệu cốt lõi của chat
  - A.6.1.2 Dữ liệu cốt lõi của case
  - A.6.1.3 Runtime context
- `project-spec/Main-flow.md`
  - Step 3 Resolve chat context tối thiểu
  - Step 5 Xác định case hiện tại
  - chat ownership check trong Request gate
- `project-spec/frontend-backend-contract.md`
- `project-spec/WISMO_BE_Implementation_Plan.md`
  - BE-5 Chat bootstrap APIs

## Context

Foundation hiện đã có `Chat`, `Case`, `ChatTurn` và `ChatContextService` cho runtime path. `POST /api/chat/message/` có thể tạo chat ngầm khi request không có `chat_id`, nhưng backend chưa có API riêng để FE/BFF tạo chat, liệt kê chat, hoặc mở chat detail trước khi gửi message.

BE-5 là lớp API/contract giữa identity canonical và runtime thread UI canonical. FE cần một chat thread thật để render sidebar, active chat, và turn history mà không phải suy diễn từ runtime message path. BE cũng cần giữ ownership boundary rõ ràng để guest và registered user không đọc được chat của nhau.

Ràng buộc hiện tại:

- schema chat foundation đã có đủ trường cho BE-5: `chat_display_name`, `opening_input_text`, `case_id` nullable, `created_at`, `last_activity_at`;
- request gate và runtime path đã có `chat_id` canonical;
- no-migration là mục tiêu mặc định cho change này;
- contract FE/BE phải được cập nhật cùng code.

Stakeholders chính:

- FE/BFF cần list/detail/create chat thread;
- runtime cần cùng ownership boundary để không lệch logic giữa bootstrap path và message path;
- QA cần response shape ổn định để test list/detail/history.

## Goals / Non-Goals

**Goals:**

- Cung cấp chat bootstrap APIs cho FE/BFF:
  - create chat;
  - list chat;
  - get chat detail kèm turn history.
- Chuẩn hóa ownership check cho chat bootstrap theo identity canonical hiện có.
- Trả về `chat_display_name` và `opening_input_text` canonical để UI render thread đúng.
- Giữ `case_id` nullable và hiển thị như metadata backend, không thay `chat_id` trong UI.
- Cập nhật contract để FE/BFF biết payload, status code, và error codes.
- Không cần migration nếu schema hiện có đủ.

**Non-Goals:**

- Không đổi semantics request gate của `POST /api/chat/message/`.
- Không thêm pagination, search, pin, archive, rename, hoặc delete chat trong BE-5.
- Không đổi runtime reasoning, case detector, hay chat-turn generation logic.
- Không thêm schema mới cho chat bootstrap nếu model hiện có đã đáp ứng.
- Không mở rộng sang quota, consent, hoặc LLM gateway.

## Decisions

### 1. Dùng collection-style REST dưới `chat`

Chọn surface:

- `POST /api/chat/` để tạo chat;
- `GET /api/chat/` để list chat;
- `GET /api/chat/<chat_id>/` để lấy detail và turn history.

Rationale:

- namespace `chat` đã tồn tại cho runtime message route;
- FE/BFF thao tác với `chat_id`, nên đường dẫn `chat` là tự nhiên hơn `accounts`;
- giữ contract ngắn và dễ đọc cho BFF.

Alternatives considered:

- `/api/chats/`: loại vì lệch namespace hiện tại của backend;
- nested route dưới `accounts`: loại vì chat không phải identity domain.

### 2. Mở rộng `ChatContextService` thay vì tạo service ownership mới

Chọn dùng một boundary trong `chat/services.py` để:

- tạo chat;
- list chat của owner hiện tại;
- load detail + turn history;
- assert ownership cho `chat_id`.

Rationale:

- `ChatContextService` đã là nơi runtime resolve chat/case;
- ownership rule và chat bootstrap đều xoay quanh cùng model `Chat`;
- giữ code ít phân mảnh hơn so với `ChatOwnershipService` riêng.

Alternatives considered:

- tạo `ChatOwnershipService` riêng: loại vì sẽ tách logic ownership khỏi context resolution và làm tăng bề mặt bảo trì;
- đẩy toàn bộ logic vào views: loại vì vi phạm boundary service mỏng / business logic nằm ở service.

### 3. Không đổi schema cho BE-5

Chọn không tạo migration mới trong change này.

Rationale:

- `Chat` đã có `chat_display_name`, `opening_input_text`, `case_id` nullable, `created_at`, `last_activity_at`;
- `Case` và `ChatTurn` đã đủ cho detail/history payload;
- change này là API/contract bootstrap, không phải data model redesign.

Alternatives considered:

- thêm bảng summary riêng cho list/detail: loại vì dư thừa ở MVP;
- thêm field mới cho metadata: loại vì chưa có consumer mới.

### 4. Detail trả turn history inline, list chỉ trả summary

Chọn:

- list endpoint trả danh sách summary theo owner hiện tại;
- detail endpoint trả summary + `turns` inline;
- `turns` được sắp xếp từ cũ đến mới để FE render đúng chronology.

Rationale:

- FE cần một call để mở chat thread và render lịch sử turn;
- list chỉ cần metadata để render sidebar;
- tránh tách thêm `/turns/` endpoint ở MVP.

Alternatives considered:

- pagination/cursor cho turn history ngay trong BE-5: loại vì chưa có yêu cầu cụ thể và sẽ làm change lớn hơn cần thiết;
- separate turns endpoint: loại vì FE mở chat sẽ phải gọi thêm một round-trip.

### 5. `chat_display_name` dùng fallback canonical hiện có

Chọn để create/list/detail trả giá trị `chat_display_name` hiện đang lưu trên `Chat`, và create endpoint dùng fallback nếu chat chưa có tên gợi ý riêng.

Rationale:

- BE-5 chỉ cần thread UI canonical, chưa cần LLM naming pipeline;
- fallback name giúp FE render sidebar ngay cả khi chat chưa có gợi ý;
- naming suggestion runtime sẽ là thay đổi sau, không nằm trong scope.

Alternatives considered:

- generate tên bằng LLM ngay trong BE-5: loại vì kéo theo runtime/LLM gateway không cần thiết;
- trả null cho chat chưa có tên: loại vì FE cần label ổn định để render.

## Risks / Trade-offs

- [Risk] `turns` inline có thể làm detail payload lớn khi chat dài. → Mitigation: giữ BE-5 ở mức MVP, chưa thêm pagination; nếu cần tối ưu sẽ làm change riêng sau.
- [Risk] Ownership rule cho list/detail có thể bị lệch với request gate nếu logic bị copy. → Mitigation: để service boundary dùng chung cho chat bootstrap và runtime path nơi phù hợp.
- [Risk] Fallback `chat_display_name` có thể khác với naming runtime sau này. → Mitigation: contract chỉ khóa fallback hiện tại, còn naming suggestion là change runtime riêng.
- [Risk] Không có migration nghĩa là change phụ thuộc vào model hiện có. → Mitigation: nếu phát hiện thiếu field correctness trong lúc implement, tách migration nhỏ và cập nhật tasks thay vì nhồi vào BE-5.

## Migration Plan

1. Dùng schema foundation hiện có, không tạo migration mới nếu model đủ.
2. Thêm endpoint và service methods trong `chat`.
3. Cập nhật `project-spec/frontend-backend-contract.md` cho create/list/detail/history/ownership errors.
4. Thêm regression tests cho ownership, list/detail ordering, empty history, và create response shape.
5. Chạy `manage.py check`, `pytest`, `ruff`, và `makemigrations --check --dry-run`.
6. Nếu phát hiện thiếu field correctness, tạo migration nhỏ riêng và giữ rollback đơn giản bằng revert change.

## Open Questions

- Không có câu hỏi mở bắt buộc trước khi implement BE-5.
