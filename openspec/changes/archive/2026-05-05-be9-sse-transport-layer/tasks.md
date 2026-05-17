## 1. Refactor Gate ra View Layer

- [x] 1.1 Tách `RequestGatePipeline.run()` call từ `RuntimeOrchestrator.handle()` — orchestrator không tự chạy gate nữa
- [x] 1.2 Cập nhật `ChatSendView.post()` chạy gate trực tiếp: gate fail → trả `Response` JSON error với status code tương ứng và clear guest cookie nếu cần; gate pass → tiếp tục tạo SSE response
- [x] 1.3 Đảm bảo `clear_guest_cookie` flag từ `GateResult` vẫn được xử lý đúng trong cả hai nhánh (JSON error và SSE)

## 2. Refactor Orchestrator thành Generator

- [x] 2.1 Thêm method `stream(gate_result: GateResult) -> Iterator[str]` vào `RuntimeOrchestrator` — generator chạy các runtime steps và yield SSE event strings
- [x] 2.2 Yield placeholder `event: response` sau khi `_response_generation_and_persist()` hoàn thành: `event: response\ndata: {"text": "<response_text>"}\n\n`
- [x] 2.3 Yield placeholder `event: done` sau response event: `event: done\ndata: {"turn_id": "...", "chat_id": "...", "response_method": "...", "status": "..."}\n\n`
- [x] 2.4 Yield `event: error` nếu orchestrator gặp exception sau khi stream đã mở: `event: error\ndata: {"error": "<error_code>"}\n\n`
- [x] 2.5 Wrap `handle()` dùng `stream()` để backward compat: chạy gate nội bộ, consume generator, build và trả `RuntimeReply` từ events

## 3. Cập nhật ChatSendView

- [x] 3.1 Cập nhật `ChatSendView.post()` trả `StreamingHttpResponse(orchestrator.stream(gate_result), content_type="text/event-stream")` khi gate pass
- [x] 3.2 Set headers trên `StreamingHttpResponse`: `Cache-Control: no-cache`, `X-Accel-Buffering: no`
- [x] 3.3 Xử lý `clear_guest_cookie` trên `StreamingHttpResponse` (set cookie header trực tiếp trên response object)

## 4. Cập nhật Tests

- [x] 4.1 Cập nhật existing success path tests của `POST /api/chat/message/` để assert `StreamingHttpResponse` với `Content-Type: text/event-stream` thay vì JSON
- [x] 4.2 Thêm test verify gate fail vẫn trả JSON error (không mở SSE stream) — kiểm tra tất cả canonical gate error codes
- [x] 4.3 Thêm test parse SSE event stream từ response và verify `response` + `done` events có đúng fields
- [x] 4.4 Thêm test verify `clear_guest_cookie` hoạt động đúng trên SSE response khi registered identity canonical

## 5. Cập nhật Contract

- [x] 5.1 Thêm section SSE transport vào `project-spec/frontend-backend-contract.md`: mô tả `Content-Type: text/event-stream`, placeholder event shapes (`response`, `done`, `error`), và connection lifecycle cơ bản
- [x] 5.2 Ghi chú rõ trong contract rằng event shapes là placeholder — Step 11 sprint sẽ define chính xác

## 6. Kiểm chứng

- [x] 6.1 Chạy `manage.py check` — pass
- [x] 6.2 Chạy `ruff check .` — pass
- [x] 6.3 Chạy `pytest -q` — tất cả tests pass
- [x] 6.4 Chạy `manage.py makemigrations --check --dry-run` — no changes (BE-9 không đổi model)
