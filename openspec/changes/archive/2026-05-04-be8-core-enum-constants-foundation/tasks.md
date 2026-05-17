## 1. Chuẩn hóa contract foundation

- [x] 1.1 Rà soát `wismo/contracts/enums.py` và chốt lại các core enums/groupings đang là canonical source cho `ResponseMethod`, `TriageDecision`, và usage/finalization statuses.
- [x] 1.2 Tạo module shared constants cho foundation public error/control codes trong `wismo/contracts` và giới hạn scope ở các keyword đã được dùng chung bởi auth/session, consent, chat bootstrap, và chat request gate.
- [x] 1.3 Chuẩn hóa `wismo/contracts/error.py` và helper liên quan để error/control payload mặc định là keyword-only.

## 2. Adopt vào các code path foundation

- [x] 2.1 Thay các string literal lặp lại ở `accounts`, `consents`, `chat`, và `runtime` bằng import từ canonical contract modules khi keyword đó là shared foundation concern.
- [x] 2.2 Xóa hoặc cô lập khỏi production path các enum/constants/helper legacy trùng nghĩa với canonical contract source, không để old/new definitions tồn tại song song cho cùng concern.
- [x] 2.3 Giữ các domain-local constants ngoài scope BE-8 ở module riêng của chúng nếu không phải shared foundation concern, tránh gom quá tay.
- [x] 2.4 Cập nhật runtime/chat helpers dùng shared payload builder cho control/error replies thay vì tự dựng ad-hoc dictionaries ở các path nền.

## 3. Khóa regression và xác nhận change

- [x] 3.1 Mở rộng contract tests và unit tests để khóa enum values, shared error/control code values, và keyword-only error payload shape.
- [x] 3.2 Chạy `manage.py check`, `ruff check .`, `pytest`, và `manage.py makemigrations --check --dry-run` để xác nhận BE-8 là pure foundation refactor không kéo theo schema drift.
- [x] 3.3 Cập nhật `agent-progress.md` với phạm vi hoàn thành của BE-8 sau khi implementation và verification xong.
