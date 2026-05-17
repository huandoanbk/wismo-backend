## MODIFIED Requirements

### Requirement: Chat request gate ordering
Hệ thống SHALL chạy request gate cho mọi `POST /api/chat/message/` theo đúng thứ tự canonical. Gate SHALL được gọi từ `ChatSendView` trước khi quyết định mở SSE stream. Nếu gate pass thì view mới tạo `StreamingHttpResponse`; nếu gate fail thì view trả JSON error trực tiếp mà không mở stream.

#### Scenario: All gate checks pass in canonical order
- **WHEN** client gửi chat request hợp lệ với identity, consent, quota và ownership đều hợp lệ
- **THEN** backend chạy lần lượt `validate payload -> resolve identity -> idempotency check -> session validity check -> consent check -> quota check -> input basic guard -> chat ownership check` rồi view mở SSE stream và đi tiếp Step 3 của main flow

#### Scenario: Gate fail trước khi stream mở
- **WHEN** gate fail ở bất kỳ check nào
- **THEN** view trả JSON error với status code tương ứng và KHÔNG mở SSE stream
