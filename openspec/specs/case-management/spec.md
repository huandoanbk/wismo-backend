# Case Management — Backend Domain Spec

Tài liệu mô tả cách WISMO quản lý "vấn đề" (case) của user: vòng đời, trạng thái, chuyển phase, case switch, CaseManager logic, và P9 counseling strategy.

Worker PHẢI đọc file này khi code CaseManager, CaseLifecycle, orchestrator (phần case resolution), sidebar sync, hoặc bất kỳ service nào đọc/ghi UserCase.

---

## 1. Khái niệm Case

Mỗi vấn đề user mang đến = 1 case. Case là đơn vị quản lý chính.

```
User profile = CON NGƯỜI (ổn định, xuyên suốt)
Case         = VẤN ĐỀ   (thay đổi, có vòng đời)
Session      = LẦN CHAT  (mở/đóng app, user không thấy)

1 user có thể có nhiều cases:
  Case 1: "Nổi nóng với con"     → resolved
  Case 2: "Stress công việc"     → progressing
  Case 3: "Mối quan hệ hôn nhân" → paused
```

User KHÔNG CẦN biết "case" tồn tại — hệ thống tự quản lý ngầm. UI chỉ hiện sidebar dạng danh sách topics.

---

## 2. Case Status — 6 trạng thái

```
active      → Mới tạo, đang Phase 1 (thu thập context)
progressing → Đang Phase 2 (khai vấn, soi chiếu)
resolved    → User XÁC NHẬN đã ổn (CHỈ user quyết, WISMO hỏi confirm)
paused      → User chuyển sang topic khác (tạm dừng, giữ context)
inactive    → Không nhắc 5+ sessions (KHÔNG = resolved, user quay lại bất cứ lúc nào)
stalled     → Nhiều sessions không tiến triển (trigger escalation)
```

**Quan trọng:**
- `inactive` ≠ `resolved`: không nhắc không có nghĩa đã ổn (có thể tránh né, xấu hổ)
- `resolved` CHỈ khi user xác nhận rõ ràng — KHÔNG BAO GIỜ auto-resolve

---

## 3. Case Phase — 3 giai đoạn tư vấn

```
understand  → Thu thập context (P1 phân tích, P4 tích lũy)
illuminate  → Khai vấn, user tự tìm giải pháp (P3 dùng strategy từ P9)
followup    → User quay lại, check tiến triển
```

**Status và Phase là 2 machine LIÊN QUAN nhưng ĐỘC LẬP:**
- Status: source of truth cho sidebar / resume logic
- Phase: source of truth cho PromptBuilder / RuleEngine

KHÔNG CÓ phase "act" — phương pháp khai vấn = user TỰ tìm giải pháp.

---

## 4. Status Transition Table

| Current | Trigger | Guard | Next | Side effects | Idempotency |
|---------|---------|-------|------|-------------|-------------|
| none | CaseManager detect topic mới | Chưa có active case | `active` | Tạo case, seed topic/tags | `(user_id, topic_fingerprint, session_id)` |
| `active` | P2 `should_transition=true` | Context đủ: problem + pattern + goal | `progressing` | Set phase=illuminate, enqueue P9 | `(case_id, transition_to_progressing)` |
| `active`/`progressing` | User chuyển topic khác hoặc confirm switch | Case mới tạo thành công | `paused` | Ghi paused_at, emit CaseTransitionEvent | `message_id` |
| `progressing` | User xác nhận đã ổn | User confirmation RÕ RÀNG | `resolved` | Set resolved_at, build journey summary | `(case_id, resolved_at)` |
| `progressing` | Stall detector | ≥5 sessions, severity không giảm, không insight mới | `stalled` | Set stalled_detected_at, create escalation candidate | `(case_id, stalled_window_id)` |
| `stalled` | User quay lại có tiến triển | Turn mới, re-engage same case | `progressing` | Clear escalation candidate | `message_id` |
| `paused` | User quay lại đúng case cũ | Reference rõ hoặc overlap đủ mạnh | `progressing` | Resume context + last phase | `message_id` |
| `resolved` | User nói tái phát | Reference rõ case resolved | `progressing` | Reopen, set reopened_at | `message_id` |
| `resolved` | Archive job | Quá age threshold | `archived` | Read-only | nightly job key |
| `progressing` | Không nhắc 5+ sessions | Tự động detect | `inactive` | Sidebar mờ, WISMO KHÔNG nhắc | auto |

**Forbidden transitions:**
- `resolved` → `active` (reopen phải vào `progressing`)
- `archived` → `progressing` trực tiếp
- `paused` → `resolved` tự động
- `stalled` → `resolved` nếu không có user confirmation

---

## 5. Phase Transition Table

| Current | Trigger | Guard | Next | Side effects |
|---------|---------|-------|------|-------------|
| `understand` | P2 says context đủ | problem + pattern + goal đủ | `illuminate` | Enqueue P9, update rule defaults |
| `illuminate` | Session kết thúc tự nhiên | Case chưa resolved | `followup` | Persist phase |
| `followup` | Turn mới cần đào sâu | Same case, progress ambiguous | `illuminate` | Restore inquiry mode |

---

## 6. Case chứa gì (data model)

```python
UserCase:
  topic: str                    # "Nổi nóng với con"
  topic_tags: list[str]         # ["anger", "parenting", "family"]
  status: CaseStatus            # 6 values
  current_phase: CasePhase      # understand | illuminate | followup
  
  context_gathered: dict        # P4 tích lũy mỗi turn (JSONB)
    # problem_detail, people_involved, trigger, pattern,
    # user_goal, tried_before, insight, user_proposed_action
  
  counseling_strategy: dict     # P9 build khi Phase 1→2 (JSONB)
    # counseling_goal, root_cause_hypothesis, strategy, 
    # success_indicators, risks
  
  sessions_count: int
  severity_first: int
  severity_current: int
  resolved_at: datetime | None
  stalled_detected_at: datetime | None
```

### 6.1 Context tích lũy (P4 mỗi turn)

P4 extract từ mỗi turn, MERGE vào `context_gathered` (chỉ thêm, KHÔNG overwrite):

| Field | Ý nghĩa |
|-------|---------|
| `problem_detail` | Vấn đề cụ thể user mô tả |
| `people_involved` | Ai liên quan (con, vợ, sếp...) |
| `trigger` | Trigger gì gây ra vấn đề |
| `pattern` | Pattern lặp lại user thể hiện |
| `user_goal` | User muốn gì (user tự nói) |
| `tried_before` | Đã thử cách gì |
| `insight` | User có realization gì (tự nhận ra) |
| `user_proposed_action` | User TỰ đề xuất hành động (WISMO không suggest) |

Null cho fields không có info mới. Merge chỉ additive.

### 6.2 Ví dụ tích lũy qua 6 turns

```
Turn 1: {problem: "nổi nóng với con"}
Turn 2: + {trigger: "mệt sau giờ làm + con không nghe"}
Turn 3: + {people: ["con", "vợ"], feeling: "hối hận"}
Turn 4: + {pattern: "suppress at work → explode at home"}
Turn 5: + {user_goal: "không quát con nữa"}
Turn 8: + {user_proposed_action: "dừng lại lúc cởi giày trước cửa"}
```

---

## 7. CaseManager — Logic phân biệt case cũ/mới

CaseManager quyết định mỗi message: tiếp case cũ, tạo case mới, hay hỏi user.

### 7.1 resolve_case() flow

```
1. Không có case active → tạo mới
2. Topic overlap (tags trùng) → cùng case, tiếp tục
3. User reference case cũ ("lần trước", "vẫn còn") → cùng case
4. User nói rõ topic mới ("chuyện khác", "vấn đề mới") → switch ngay
5. Không rõ → action='ambiguous' → WISMO hỏi user confirm
```

### 7.2 Ba trường hợp switch

**TH1: User nói RÕ muốn đổi (switch ngay, không hỏi)**
```
User: "Hôm nay muốn nói chuyện khác"
→ Switch ngay, case cũ → paused, tạo case mới
```

**TH2: System AUTO-DETECT topic mới (hỏi confirm)**
```
User đang nói "Stress công việc", bỗng nói: "Vợ tôi muốn ly hôn"
P1: topic_tags=["relationship","divorce"] ≠ case hiện tại
→ WISMO hỏi: "Đây là chủ đề mới, khác stress công việc. Đúng không?"
→ 2 nút: [Đúng, chuyện mới]  [Không, vẫn liên quan]
→ Timeout 2 phút không chọn → giữ case cũ (safe default)
```

**TH3: Liên quan nhưng khác góc (không switch)**
```
Case: "Nổi nóng với con"
User: "Stress công việc làm tôi nổi nóng"
→ topic_tags overlap ["anger"] → cùng case
→ P4 thêm trigger_detail: "stress công việc là trigger chính"
```

### 7.3 Reference code

```python
class CaseManager:
    def resolve_case(self, user, message, p1_signals) -> CaseResolution:
        """Mỗi message: case cũ, case mới, hay mở rộng?"""
        active = UserCase.objects.filter(
            user=user, status__in=['active', 'progressing']
        ).order_by('-updated_at').first()
        
        if not active:
            return self._create_new_case(user, message, p1_signals)
        
        message_topics = p1_signals.get('topic_tags', [])
        if set(message_topics) & set(active.topic_tags):
            return CaseResolution(case=active, action='continue')
        
        if self._references_old_case(message):
            return CaseResolution(case=active, action='continue')
        
        if self._says_new_topic(message):
            return self._switch_case(user, active, message, p1_signals)
        
        return CaseResolution(case=active, action='ambiguous')
```

Heuristics:
- References cũ: "lần trước", "chuyện đó", "vẫn còn", "tiếp tục"
- Topic mới: "chuyện khác", "hôm nay khác", "vấn đề mới"

---

## 8. Stalled Detection & Escalation

### 8.1 Điều kiện stalled (TẤT CẢ phải đúng)

- Cùng case ≥ 5 sessions
- Severity không giảm (hoặc tăng) so với severity_first
- P4 không extract insight mới 3+ sessions liên tiếp

### 8.2 Khi detect stalled

```
case.status → 'stalled'
WISMO (lần tới user chat): "Mình thấy chúng ta đã nói về [topic] nhiều lần.
  Mình nghĩ một chuyên gia có thể mở góc nhìn mà mình không thể. Bạn nghĩ sao?"
→ Suggest resources (xem safety/spec.md Section escalation)
→ KHÔNG ép, user có thể tiếp tục
```

---

## 9. Resolve — CHỈ khi user xác nhận

### 9.1 Điều kiện resolve

**Chỉ 2 path, cả 2 đều CẦN user confirmation:**

Path A: User nói rõ
```
User: "tôi thấy ổn rồi"
WISMO: "Nghe vui. Bạn có muốn mình ghi nhận chuyện này đã ổn không?"
User: confirm → resolved
```

Path B: Severity giảm ổn định
```
Severity ≤ 2 trong 3+ sessions liên tiếp
WISMO: "Mình thấy bạn đã tốt hơn nhiều. Bạn cảm thấy chuyện này đã ổn chưa?"
User confirm → resolved
User nói chưa → giữ progressing
```

### 9.2 KHÔNG BAO GIỜ auto-resolve

```
✗ "User không nhắc 5 sessions" = KHÔNG resolve → chuyển inactive
✗ "Severity giảm" = KHÔNG resolve → hỏi user trước
✗ System tự quyết "đã ổn" = KHÔNG BAO GIỜ
```

---

## 10. Goal & Strategy (P9)

Khi P2 trigger Phase 1→2 transition, P9 chạy 1 lần per case (Celery).

### 10.1 Contract: GoalStrategyPayload (`p9.v1`)

| Field | Type | Required |
|-------|------|----------|
| `schema_version` | string ("p9.v1") | ✓ |
| `case_id` | UUID | ✓ |
| `counseling_goal` | string | ✓ |
| `root_cause_hypothesis` | string | ✗ |
| `strategy.primary_pillar` | "wisdom" / "ethics" / "meditation" / "mixed" | ✓ |
| `strategy.secondary_pillar` | same or null | ✗ |
| `strategy.key_questions` | string[] (0..5) | ✓ |
| `strategy.relevant_teaching` | string or null | ✗ |
| `success_indicators` | string[] | ✓ |
| `risks` | string[] | ✓ |

### 10.2 P9 consumers

| Consumer | Dùng gì |
|----------|---------|
| P2 (turn sau) | Đánh giá tiến triển so với goal + success_indicators |
| P3 (PromptBuilder) | Pillar focus + key questions cho response |
| RAG query | relevant_teaching → search knowledge chunks |

### 10.3 Rules

- P9 chạy CHỈ KHI transition `understand → illuminate` đã xác nhận
- Guest được có GoalStrategyPayload nhưng chỉ sống trong session
- success_indicators phải đủ cấu trúc cho P2/telemetry, không prose dài

---

## 11. Session — Ẩn, internal only

User KHÔNG thấy session. Session dùng internal cho P7, P6, telemetry.

| Context | WISMO action |
|---------|-------------|
| First visit (chưa có history) | Greeting: "Chào bạn, mình là WISMO. Bạn muốn chia sẻ gì hôm nay?" |
| Mọi lần sau | Im lặng, đợi user gõ |

---

## 12. UI Integration — Sidebar

```
Sidebar hiển thị:
  ● Active/Progressing → "Đang trao đổi"
  ✓ Resolved → "Đã giải quyết" (user xác nhận)
  ⏸ Paused → "Tạm dừng"
  ○ Inactive → hiện mờ, dưới paused

Click case resolved/paused/inactive → xem read-only messages
Chat window → 1 luồng liên tục, không chia theo case
Case switch → sidebar cập nhật ngay, chat liên tục
```

---

## 13. Phân biệt: Profile vs Case vs Session

| | User Profile | Case | Session |
|---|---|---|---|
| **Thuộc về** | User | User | User |
| **Vòng đời** | Vĩnh viễn | Theo vấn đề | Theo lần chat |
| **Nội dung** | Facts ổn định (tên, nghề, tính cách) | Context vấn đề (trigger, pattern, goal) | Messages trong 1 lần |
| **Số lượng** | 1 per user | Nhiều | Nhiều |
| **User thấy** | Settings | Sidebar | Không |
| **Build bởi** | P5 + P6 | P4 + P9 | Tự động |
| **Dùng bởi** | P3 (style), P9 (strategy) | P2, P3, P9 | P7, telemetry |

---

## 14. Implementation Rules

- Status/phase logic PHẢI nằm trong CaseManager / CaseLifecycle service — KHÔNG rải trong views/PromptBuilder/sidebar
- Consumer đọc từ `CaseTransitionEvent` hoặc case row đã normalize — KHÔNG tự infer state
- Celery jobs mutate case state CHỈ qua CaseManager method
- Guest cases: chỉ `active`/`progressing`/`paused`, session-scoped, không archive
