## MODIFIED Requirements

### Requirement: Chat message API SHALL expose SSE lifecycle rõ ràng cho FE
`POST /api/chat/message/` SHALL có 2 lớp response tách biệt:
- Gate layer: HTTP status + JSON error khi gate fail
- Stream layer: SSE events khi gate pass

#### Scenario: Gate fail trả JSON error
- **WHEN** request fail ở Request Gate
- **THEN** API MUST trả HTTP non-2xx và JSON body keyword-only
- **AND** API MUST NOT mở SSE stream

#### Scenario: Gate pass mở SSE stream
- **WHEN** request pass toàn bộ Request Gate
- **THEN** API MUST trả `StreamingHttpResponse` với `Content-Type: text/event-stream`
- **AND** runtime MUST stream event lifecycle theo contract

#### Scenario: done event chốt final response đã persist
- **WHEN** runtime hoàn tất response path của turn
- **THEN** API MUST phát `done` event như tín hiệu final assistant response đã được persist chính thức

#### Scenario: Implicit chat creation trả canonical ids
- **WHEN** request không có `chat_id` và backend tạo chat mới trong Step 3
- **THEN** SSE lifecycle MUST cung cấp `chat_id` canonical và `turn_id` canonical để FE cập nhật thread state
- **AND** FE MUST có đủ dữ liệu để map local pending message vào persisted turn khi nhận `done`
