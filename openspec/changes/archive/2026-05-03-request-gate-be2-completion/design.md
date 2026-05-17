## Context

### Spec References
- `project-spec/WISMO_BE_Implementation_Plan.md` mục `C.6. Request gate tối thiểu` và `C.9.2. Sprint BE-2 — Request gate`
- `project-spec/Main-flow.md` phần `2. Request gate`
- `project-spec/WISMO_MVP_Spec.md` phần `A.6.2.2. Flow chuẩn của một chat turn`
- `openspec/specs/identity-consent-auth/spec.md` cho phần consent/session state đã được chốt trước

Request gate đang tồn tại trong `runtime/request_gate.py` và đã có skeleton khá gần với spec. Tuy nhiên BE-2 chưa hoàn tất ở ba điểm chính: contract validation ở API/gate chưa đủ chặt, idempotency chưa trả về canonical behavior cho replay/in-progress, và quota/input/ownership behavior chưa được chốt đầy đủ bằng spec + regression coverage.

Request gate là điểm chặn sớm cho mọi `POST /api/chat/message/`. Nếu phần này không ổn định trước khi sang runtime shell, mọi bước sau sẽ phải gánh thêm các invalid request hoặc duplicated turn mà lẽ ra phải bị chặn ở đầu flow.

## Goals / Non-Goals

**Goals:**
- Chốt request gate đúng thứ tự 8 bước đã được định nghĩa trong spec.
- Chuẩn hóa control responses tối thiểu cho `POST /api/chat/message/` ở pha gate fail.
- Hoàn thiện idempotency tối thiểu theo `client_turn_id` trên owner hiện tại.
- Chốt side effects của quota gate cho `pending_input_text` theo đúng MVP policy.
- Chốt behavior clear guest cookie khi gate resolve sang registered user.
- Bổ sung regression coverage để BE-2 có thể được kiểm chứng độc lập trước BE-3.

**Non-Goals:**
- Không triển khai runtime shell Step 3-12 đầy đủ trong change này.
- Không thêm SSE event set hoặc stream contract đầy đủ.
- Không thay đổi auth flow, consent API, attach flow, hoặc quota policy tổng quát ngoài phần gate dùng trực tiếp.
- Không thêm schema/migration mới nếu model hiện tại đã đủ.

## Decisions

### 1. Giữ `RequestGatePipeline` làm nơi tập trung toàn bộ gate ordering

Request gate sẽ tiếp tục nằm trong `runtime/request_gate.py` thay vì tách thêm service nhỏ hơn ở pass này. Lý do là BE-2 cần khóa order và behavior tổng thể trước; việc chia nhỏ thêm bây giờ chỉ làm tăng bề mặt refactor mà không tạo thêm giá trị nghiệp vụ.

Alternative considered:
- Dùng serializer/view-level validation cho phần schema rồi chỉ để `RequestGatePipeline` xử lý authorization. Không chọn ở pass này vì spec xem request gate là một flow canonical thống nhất; tách đôi quá sớm dễ làm lệch thứ tự hoặc error mapping.

### 2. Payload validation vẫn trả các error code hẹp, không chỉ một mã `invalid_request`

Gate sẽ phân biệt ít nhất các lỗi `missing_required_field`, `invalid_chat_id`, `invalid_client_turn_id`, `empty_message`, `message_too_long`, `payload_too_large`, ngoài `invalid_request` cho các trường hợp shape/type không hợp lệ. Điều này bám sát `Main-flow` và giúp FE/BFF có control behavior rõ hơn mà chưa cần full response envelope sau này.

Alternative considered:
- Gộp toàn bộ lỗi validation vào `invalid_request`. Không chọn vì spec đã liệt kê riêng một số mã lỗi canonical và gate này là nơi rẻ nhất để giữ contract rõ.

### 3. Idempotency tối thiểu bám theo owner hiện tại và persisted turn state

Kiểm tra duplicate sẽ tiếp tục dựa trên `client_turn_id` + owner hiện tại (`user` hoặc `guest_identity`). Nếu turn trước đã `COMPLETED`, gate trả `replay_previous_result`; nếu turn trước chưa finalized bình thường hoặc Step 12 đang pending thì trả `turn_in_progress`.

Alternative considered:
- Dùng lock table hoặc request token registry riêng. Không chọn ở pass này vì schema hiện tại đã có `ChatTurn` và unique constraints đủ để hỗ trợ idempotency tối thiểu cho MVP.

### 4. Quota gate là nơi thực hiện side effect `pending_input_text` trên quota window hiện tại

Khi quota đã exhausted, gate sẽ append message hiện tại vào `pending_input_text` của `UsageQuotaWindow` hiện tại trước khi chặn runtime và trả `registration_required_by_quota` hoặc `quota_exceeded`. Hành vi này phải ở trong gate thay vì dời ra orchestrator vì spec yêu cầu quota fail không được đi tiếp vào runtime core.

Alternative considered:
- Chỉ trả mã lỗi và để FE lưu pending message. Không chọn vì spec đã chốt pending input là business state của backend.

### 5. Resolve sang registered user phải làm sạch guest cookie cũ

Khi request gate resolve được registered user hợp lệ, response path của API phải có khả năng clear `wismo_guest` nếu cookie cũ vẫn tồn tại. Điều này bám sát `Main-flow` và tránh việc client tiếp tục gửi một guest cookie stale song song với registered identity canonical.

Alternative considered:
- Bỏ qua việc clear cookie ở BE-2 và chờ tới attach/login flow khác xử lý. Không chọn vì `Main-flow` đã nêu đây là behavior của bước resolve identity trong runtime path chính.

### 6. Chat ownership check tiếp tục là bước cuối của gate nhưng phải giữ barrier turn trước

Ownership check vẫn ở bước 8 theo spec. Nếu `chat_id` hợp lệ và thuộc owner hiện tại, gate còn phải kiểm tra previous-turn finalization barrier trước khi cho đi tiếp. Barrier này không thay đổi thứ tự gate; nó là một phần của ownership/access readiness cho existing chat.

Alternative considered:
- Dời barrier sang runtime orchestrator. Không chọn vì turn trước chưa finalized là điều kiện chặn sớm canonical, không nên để runtime core mới phát hiện.

## Risks / Trade-offs

- [Risk] Error code của gate bị chốt quá sớm, sau này runtime shell muốn đổi khó hơn. → Mitigation: chỉ khóa những mã đã được spec và Main-flow nêu rõ; không chốt full envelope ngoài phạm vi BE-2.
- [Risk] Idempotency dựa trên `ChatTurn` state có thể chưa đủ cho replay trả lại payload cũ ngay. → Mitigation: ở BE-2 chỉ chốt behavior chặn/replay tối thiểu; trả full previous result nếu cần sẽ là follow-up của runtime shell.
- [Risk] Quota side effect làm test khó chạy vì phụ thuộc DB state. → Mitigation: thêm regression coverage DB-backed và giữ `manage.py check` như verification nhanh khi local DB credentials chưa sẵn sàng.
- [Risk] Clear guest cookie ở path chat có thể tạo side effect response-level ngoài `RequestGatePipeline`. → Mitigation: chốt rõ ranh giới giữa gate result và API response mapping trong implementation tasks, không nhồi logic set/delete cookie trực tiếp vào pipeline thuần dữ liệu.
- [Risk] Nếu view layer và gate cùng validate payload theo hai cách khác nhau sẽ bị drift. → Mitigation: change này ưu tiên một đường canonical, sau đó view chỉ map request vào gate/orchestrator.
