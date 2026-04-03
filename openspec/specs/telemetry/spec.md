# Telemetry Domain Spec — Logging, Metrics & GDPR Audit

**Source:** WISMO Project Specification v18, Section 12 (trích lọc và tổng hợp)  
**Scope:** `apps/telemetry/` — per-message metadata, aggregation, feedback, GDPR audit, alerts, archive  
**Owner app:** `telemetry`  
**Không thuộc scope:** domain decision-making, case/session state, source of truth cho safety/consent

---

## 1. Vai trò và Ranh giới

Telemetry là **observer layer** — không nằm trên flow chính, không block response. Nó:

- Ghi metadata pipeline vào `messages.metadata` JSONB sau mỗi turn
- Aggregates daily stats
- Cung cấp feedback mechanism (thumbs up/down)
- Ghi GDPR audit log cho mọi consent/delete action
- Trigger alerts khi metrics vượt ngưỡng
- Archive messages > 90 ngày lên S3

**Quan trọng:** Telemetry là **sink**, không phải orchestrator. Nó không được đọc ngược domain service để thay đổi state. Không được là source of truth cho session/case/consent state.

**Dependency rule:** app khác gọi `TelemetryService` facade hoặc dispatch Celery task. Telemetry không được import `chat.views`, không mutate `Session`, `UserCase`, `GDPRConsent`.

**Nối với eval:** Telemetry là nguồn dữ liệu hậu triển khai cho Section 11A. Validator rejects, failover spikes, crisis anomalies, thumbs-down clusters phải chảy ngược thành regression cases trong eval datasets.

---

## 2. Kiến trúc 3 tầng

```
PER MESSAGE: messages.metadata JSONB (~700 bytes)
  → Mọi thông tin pipeline ghi ngay trong message row
  → KHÔNG có RequestTrace table riêng (conflict resolved: Section 15.6, conflict #6)

PER EVENT: tables riêng cho events đặc biệt
  → feedback_log, crisis_events, attack_logs, gdpr_audit_log

PER DAY: DailyStats aggregate
  → 1 row/ngày, anonymous, giữ vĩnh viễn
```

---

## 3. messages.metadata JSONB Schema

Mỗi assistant message có `metadata` JSONB chứa toàn bộ pipeline trace cho turn đó.

```python
# Canonical metadata schema (lưu trong messages.metadata)

metadata = {
    # Trace correlation (Section 7.5C trace.v1)
    "request_id":        "uuid",          # global request ID
    "turn_id":           "uuid",          # logical turn ID
    "schema_version":    "trace.v1",

    # LLM execution
    "model_response":    "deepseek-v3",   # model thực sự dùng (sau failover)
    "model_primary":     "deepseek-v3",   # model được config cho tier/step
    "had_failover":      False,           # True nếu failover xảy ra
    "failover_reason":   None,            # lý do failover nếu có
    "tokens_in":         250,
    "tokens_out":        180,
    "tokens_total":      430,

    # Timing (ms)
    "total_latency_ms":  1850,
    "ttft_ms":           320,             # time-to-first-token
    "llm_latency_ms":    1500,
    "p1_latency_ms":     180,
    "p2_latency_ms":     90,

    # Pipeline decisions
    "method":            "INQUIRY",       # LISTEN/INQUIRY/TEACH
    "phase":             "understand",
    "safety_state":      "normal",        # ConversationSafetyState value
    "guarded_turn":      False,

    # Validation
    "validation_passed": True,
    "validation_violations": [],          # list nếu có violations
    "regeneration_count": 0,             # số lần phải regenerate

    # User tier
    "user_tier":         "free",

    # Context depth
    "memory_items_used": 2,
    "rag_chunks_used":   0,
    "history_turns_used": 3,

    # After-turn tasks
    "p4_dispatched":     True,
    "p5_dispatched":     True,
    "p6_dispatched":     True,
}
```

### 3.1 Trace propagation rule

Ít nhất các record/log sau phải chứa `request_id` và khi có thể cả `turn_id`:

| Record | Bắt buộc | Mục đích |
|--------|:---:|---------|
| Request ingress log | ✓ | Debug request path |
| `messages.metadata` | ✓ | Nối preview với final persisted turn |
| `outbox_events.trace_context` | ✓ | Triage async side effects |
| Provider call logs | ✓ | Điều tra failover/latency/parity |
| Validator/recovery events | ✓ | Phân tích regenerate/reject |
| `recovery_status` | ✗ | Chỉ khi có reconnect/recover |

---

## 4. Event Tables

### 4.1 feedback_log

```sql
CREATE TABLE feedback_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id   UUID REFERENCES messages(id) ON DELETE CASCADE,
    user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
    rating       SMALLINT,          -- +1 thumbs up, -1 thumbs down
    feedback_text TEXT,             -- optional free-text comment
    created_at   TIMESTAMP DEFAULT NOW()
);
```

### 4.2 crisis_events (anonymous)

```sql
CREATE TABLE crisis_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_hash      VARCHAR(64),   -- SHA-256 của session_id — KHÔNG lưu user_id
    trigger_type      VARCHAR(30),   -- 'keyword_match' / 'llm_classify' / 'user_confirmed'
    crisis_level      VARCHAR(20),   -- 'A' / 'B' / 'C' / 'D'
    detected_keywords TEXT[],
    action_taken      VARCHAR(50),   -- 'fullscreen_hotline' / 'inline_hotline' / 'listen_only'
    created_at        TIMESTAMP DEFAULT NOW()
);
```

### 4.3 attack_logs (anonymous)

```sql
CREATE TABLE attack_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_hash  VARCHAR(64),
    attack_type   VARCHAR(30),   -- 'injection' / 'jailbreak' / 'adversarial'
    blocked       BOOLEAN,
    input_snippet VARCHAR(50),   -- first 50 chars only
    created_at    TIMESTAMP DEFAULT NOW()
);
```

### 4.4 gdpr_audit_log (giữ 5 năm)

```sql
CREATE TABLE gdpr_audit_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID,              -- giữ sau khi user delete account (audit requirement)
    action        VARCHAR(50),       -- xem mục 4.4.1
    detail        JSONB DEFAULT '{}',
    ip_address    INET,
    performed_by  VARCHAR(20),       -- 'user' / 'system' / 'admin'
    created_at    TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_gdpr_user ON gdpr_audit_log(user_id, created_at);
```

**Actions bắt buộc log:**

| Action | Khi nào |
|--------|---------|
| `consent_given` | User grant consent |
| `consent_withdrawn` | User withdraw consent |
| `consent_version_updated` | User re-consent do version change |
| `data_export_requested` | User trigger GDPR export |
| `data_delete_requested` | User trigger account deletion |
| `memory_item_deleted` | User xóa 1 memory item |
| `all_memory_deleted` | User xóa tất cả memory |
| `full_data_deletion` | Cascade delete sau withdraw consent |
| `admin_data_access` | Admin view transcript/crisis data |

### 4.5 daily_stats (giữ vĩnh viễn)

```sql
CREATE TABLE daily_stats (
    date                DATE PRIMARY KEY,
    total_messages      INT DEFAULT 0,
    total_sessions      INT DEFAULT 0,
    unique_users        INT DEFAULT 0,

    -- Method distribution
    method_listen       INT DEFAULT 0,
    method_inquiry      INT DEFAULT 0,
    method_teach        INT DEFAULT 0,

    -- Latency (ms)
    avg_latency_ms      INT DEFAULT 0,
    avg_ttft_ms         INT DEFAULT 0,
    p95_latency_ms      INT DEFAULT 0,

    -- Errors
    validation_fails    INT DEFAULT 0,
    failover_count      INT DEFAULT 0,
    crisis_events_count INT DEFAULT 0,

    -- Feedback
    thumbs_up           INT DEFAULT 0,
    thumbs_down         INT DEFAULT 0,

    -- Token usage
    total_tokens        BIGINT DEFAULT 0,
    estimated_cost_usd  NUMERIC(10, 4) DEFAULT 0
);
```

---

## 5. TelemetryService

```python
# apps/telemetry/services/telemetry_service.py

class TelemetryService:
    """
    Facade để app khác ghi telemetry mà không cần import models trực tiếp.
    Không phải source of truth cho domain state — chỉ là sink.
    """

    def record_turn(
        self,
        message_id: str,
        metadata: dict,
    ) -> None:
        """
        Ghi metadata vào messages.metadata JSONB.
        Gọi sau khi persist final message (step 11 canonical pipeline).
        """
        Message.objects.filter(id=message_id).update(metadata=metadata)

    def record_feedback(
        self,
        message_id: str,
        user_id: str,
        rating: int,
        feedback_text: str | None = None,
    ) -> None:
        FeedbackLog.objects.create(
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            feedback_text=feedback_text,
        )

    def record_crisis(
        self,
        session_hash: str,
        trigger_type: str,
        crisis_level: str,
        keywords: list[str],
        action_taken: str,
    ) -> None:
        """Anonymous — không lưu user_id."""
        CrisisEvent.objects.create(
            session_hash=session_hash,
            trigger_type=trigger_type,
            crisis_level=crisis_level,
            detected_keywords=keywords,
            action_taken=action_taken,
        )

    def record_attack(
        self,
        session_hash: str,
        attack_type: str,
        blocked: bool,
        input_snippet: str,
    ) -> None:
        AttackLog.objects.create(
            session_hash=session_hash,
            attack_type=attack_type,
            blocked=blocked,
            input_snippet=input_snippet[:50],
        )
```

---

## 6. GDPRAuditService

```python
# apps/telemetry/services/gdpr_audit.py

class GDPRAuditService:
    """
    Ghi audit log cho mọi GDPR-relevant action.
    Giữ 5 năm theo legal requirement.
    """

    def log(
        self,
        user_id: str,
        action: str,
        detail: dict | None = None,
        performed_by: str = 'user',
        ip: str | None = None,
    ) -> None:
        GDPRAuditLog.objects.create(
            user_id=user_id,
            action=action,
            detail=detail or {},
            ip_address=ip,
            performed_by=performed_by,
        )

    def log_consent(self, user_id, consent_type, given=True, ip=None):
        action = 'consent_given' if given else 'consent_withdrawn'
        self.log(user_id, action, detail={'consent_type': consent_type}, ip=ip)

    def log_data_export(self, user_id, ip):
        self.log(user_id, 'data_export_requested', ip=ip)

    def log_data_delete(self, user_id, ip):
        self.log(user_id, 'data_delete_requested', ip=ip)

    def log_memory_deleted(self, user_id, memory_id):
        self.log(user_id, 'memory_item_deleted',
                 detail={'memory_item_id': str(memory_id)})

    def log_admin_access(self, actor_id, actor_role, target_type,
                         target_id=None, action='view', reason_code=None):
        """Ghi khi admin truy cập transcript, crisis event, hay memory nhạy cảm."""
        self.log(
            user_id=None,
            action='admin_data_access',
            detail={
                'actor_id': str(actor_id),
                'actor_role': actor_role,
                'target_type': target_type,
                'target_id': str(target_id) if target_id else None,
                'action': action,
                'reason_code': reason_code,
            },
            performed_by='admin',
        )
```

---

## 7. Feedback API

```python
# apps/telemetry/views.py

class MessageFeedbackView(APIView):
    """POST /api/chat/messages/{id}/feedback/ — thumbs up/down."""

    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        rating = request.data.get('rating')  # +1 or -1
        if rating not in (1, -1):
            return Response({'error': 'rating must be 1 or -1'}, status=400)

        text = request.data.get('text')

        message = get_object_or_404(Message, id=message_id)

        FeedbackLog.objects.create(
            message_id=message_id,
            user_id=request.user.id,
            rating=rating,
            feedback_text=text,
        )

        # Update prompt version feedback stats nếu message có version tag
        prompt_version = message.metadata.get('prompt_version')
        if prompt_version:
            update_prompt_feedback.delay(prompt_version, rating)

        return Response({'status': 'ok'})
```

---

## 8. Alert Triggers

### 8.1 Alert conditions

| Điều kiện | Hành động | Kênh |
|-----------|-----------|------|
| LLM failover > 5 lần trong 10 phút | Email admin | Email |
| Crisis event bất kỳ tier A | Email admin ngay | Email |
| Validation fail rate > 10% trong 1 giờ | Email admin | Email |
| Average latency > 5s trong 15 phút | Email admin | Email |
| Thumbs-down rate > 30% trong 1 ngày | Log warning, review hàng ngày | Log |

### 8.2 Alert implementation

```python
# apps/telemetry/tasks.py

@shared_task
def check_validation_fail_rate():
    """Celery beat: chạy mỗi giờ — check validation fail rate."""
    one_hour_ago = now() - timedelta(hours=1)

    total = Message.objects.filter(
        role='assistant',
        created_at__gte=one_hour_ago,
    ).count()

    if total == 0:
        return

    fails = Message.objects.filter(
        role='assistant',
        created_at__gte=one_hour_ago,
        metadata__validation_passed=False,
    ).count()

    fail_rate = fails / total
    if fail_rate > 0.10:
        send_mail(
            subject=f"[WISMO] Validation fail rate {fail_rate:.1%} in last hour",
            message=f"Total: {total}, Fails: {fails}, Rate: {fail_rate:.1%}",
            from_email=settings.ALERT_FROM,
            recipient_list=[settings.ADMIN_EMAIL],
        )


@shared_task
def check_latency():
    """Celery beat: chạy mỗi 15 phút — check average latency."""
    fifteen_min_ago = now() - timedelta(minutes=15)

    result = Message.objects.filter(
        role='assistant',
        created_at__gte=fifteen_min_ago,
    ).aggregate(
        avg_latency=Avg(Cast(KeyTextTransform('total_latency_ms', 'metadata'), IntegerField()))
    )

    avg_latency = result['avg_latency'] or 0
    if avg_latency > 5000:
        send_mail(
            subject=f"[WISMO] High latency: {avg_latency:.0f}ms avg in last 15min",
            message=f"Average total_latency_ms: {avg_latency:.0f}ms",
            from_email=settings.ALERT_FROM,
            recipient_list=[settings.ADMIN_EMAIL],
        )
```

---

## 9. Daily Stats Aggregation

```python
# apps/telemetry/tasks.py

@shared_task
def aggregate_daily_stats(date_str: str | None = None):
    """
    Celery beat: chạy 00:05 mỗi ngày — aggregate hôm qua.
    Dùng date_str để support backfill.
    """
    target_date = date.fromisoformat(date_str) if date_str else date.today() - timedelta(days=1)

    messages = Message.objects.filter(
        role='assistant',
        created_at__date=target_date,
    )

    total = messages.count()
    if total == 0:
        return

    # Method distribution
    method_counts = {}
    for method in ('LISTEN', 'INQUIRY', 'TEACH'):
        method_counts[method] = messages.filter(
            metadata__method=method
        ).count()

    # Latency
    latencies = [
        m.metadata.get('total_latency_ms', 0)
        for m in messages
        if m.metadata.get('total_latency_ms')
    ]
    avg_latency = sum(latencies) // len(latencies) if latencies else 0
    p95_latency = int(sorted(latencies)[int(len(latencies) * 0.95)]) if latencies else 0

    # Validation
    validation_fails = messages.filter(metadata__validation_passed=False).count()

    DailyStats.objects.update_or_create(
        date=target_date,
        defaults={
            'total_messages': total,
            'method_listen': method_counts.get('LISTEN', 0),
            'method_inquiry': method_counts.get('INQUIRY', 0),
            'method_teach': method_counts.get('TEACH', 0),
            'avg_latency_ms': avg_latency,
            'p95_latency_ms': p95_latency,
            'validation_fails': validation_fails,
        }
    )
```

---

## 10. Storage Layout & Archive Pipeline

### 10.1 Hot / Cold / Permanent

```
HOT (PostgreSQL, < 90 ngày):
  messages + metadata JSONB     → query nhanh, debug ngay
  feedback_log                  → ratings gần đây

COLD (Contabo S3, > 90 ngày):
  s3://wismo-archives/messages/YYYY/MM/messages_YYYY_MM.json.gz
  → Monthly batch archive bởi Celery
  → Cần lại → download + import tạm thời

PERMANENT (PostgreSQL):
  daily_stats       → giữ vĩnh viễn (1 row/ngày, nhẹ)
  gdpr_audit_log    → 5 năm
  crisis_events     → 24 tháng
  feedback_log      → 12 tháng
  attack_logs       → 90 ngày
```

### 10.2 Retention matrix

| Data type | Lưu ở đâu | Retention | Ghi chú |
|-----------|-----------|:---------:|---------|
| Active messages + metadata | PostgreSQL | 90 ngày hot | Sau đó archive |
| Archived messages | S3 | 12 tháng | Restore khi support/incident |
| Guest runtime state | Session store | Lifecycle session | Xóa khi session đóng |
| Long-term memory items | PostgreSQL | Đến user xóa / delete account | Section 10 |
| Daily telemetry aggregate | PostgreSQL | Vĩnh viễn | Anonymous |
| feedback_log | PostgreSQL | 12 tháng | Production learning |
| crisis_events | PostgreSQL | 24 tháng | Safety review |
| attack_logs | PostgreSQL | 90 ngày | Security triage |
| gdpr_audit_log | PostgreSQL | 5 năm | Legal requirement |
| sensitive_access_audit | PostgreSQL | 24 tháng | Internal investigation |

### 10.3 Archive Celery task

```python
@shared_task
def archive_old_messages():
    """
    Celery beat: ngày 1 mỗi tháng — archive messages > 90 ngày lên S3.
    """
    cutoff = date.today() - timedelta(days=90)

    messages = Message.objects.filter(created_at__date__lt=cutoff)
    count = messages.count()

    if count == 0:
        return

    # Export → gzip → upload S3
    data = list(messages.values())
    json_bytes = json.dumps(data, default=str).encode('utf-8')
    gz_bytes = gzip.compress(json_bytes)

    month_str = cutoff.strftime('%Y_%m')
    s3_key = f"messages/{cutoff.year}/{cutoff.month:02d}/messages_{month_str}.json.gz"

    s3_client.put_object(
        Bucket=settings.ARCHIVE_BUCKET,
        Key=s3_key,
        Body=gz_bytes,
    )

    messages.delete()
    logger.info(f"Archived {count} messages → s3://{settings.ARCHIVE_BUCKET}/{s3_key}")
```

---

## 11. Sensitive Access Audit Trail

Các truy cập nội bộ vào dữ liệu nhạy cảm **phải** có audit trail:

### 11.1 Bắt buộc audit khi truy cập

- Full transcript / session transcript
- Crisis event detail
- Thumbs-down feedback có free-text
- Data export theo GDPR request
- Archived raw content restore để điều tra
- Admin view memory facts nhạy cảm

### 11.2 sensitive_access_audit schema

```sql
CREATE TABLE sensitive_access_audit (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id  UUID NULL,           -- nhân sự nội bộ / admin
    actor_role     VARCHAR(30),         -- admin / support / safety_reviewer / system
    target_type    VARCHAR(30),         -- transcript / crisis_event / feedback / export / archive / memory
    target_id      UUID NULL,
    action         VARCHAR(30),         -- view / export / restore / disable_source / delete / redacted_view
    reason_code    VARCHAR(30) NULL,    -- support_case / safety_review / incident / gdpr_request
    metadata       JSONB DEFAULT '{}',
    created_at     TIMESTAMP DEFAULT NOW()
);
```

### 11.3 Operational rules

- Mọi truy cập nội bộ vào transcript và crisis event phải đi qua service có ghi audit
- Reviewer chỉ thấy phần dữ liệu tối thiểu cần thiết (principle of least privilege)
- Admin panel ưu tiên `redacted_view` khi full text không cần thiết
- Access audit giữ 24 tháng để phục vụ điều tra incident

---

## 12. Analytics Queries — Ví dụ từ metadata JSONB

```sql
-- Token consumption by model (last 7 days)
SELECT metadata->>'model_response' AS model,
       SUM((metadata->>'tokens_total')::int) AS total_tokens
FROM messages
WHERE role='assistant' AND created_at > now() - interval '7 days'
GROUP BY 1;

-- Method distribution hôm nay
SELECT metadata->>'method' AS method, COUNT(*)
FROM messages
WHERE role='assistant' AND created_at::date = CURRENT_DATE
GROUP BY 1;

-- Validation fail rate (last 7 days)
SELECT
    COUNT(*) FILTER (WHERE (metadata->>'validation_passed')::bool = false) * 100.0
    / NULLIF(COUNT(*), 0) AS fail_rate_pct
FROM messages
WHERE role='assistant' AND created_at > now() - interval '7 days';

-- Average latency by tier
SELECT
    metadata->>'user_tier' AS tier,
    AVG((metadata->>'total_latency_ms')::int) AS avg_latency_ms
FROM messages
WHERE role='assistant' AND created_at > now() - interval '7 days'
GROUP BY 1;

-- Feedback correlation with method
SELECT
    metadata->>'method' AS method,
    AVG(f.rating) AS avg_rating,
    COUNT(*) AS total_feedback
FROM messages m
JOIN feedback_log f ON f.message_id = m.id
WHERE m.created_at > now() - interval '30 days'
GROUP BY 1
ORDER BY avg_rating DESC;

-- Failover count by provider (last 24h)
SELECT
    metadata->>'model_primary' AS attempted_primary,
    COUNT(*) FILTER (WHERE (metadata->>'had_failover')::bool) AS failover_count,
    COUNT(*) AS total
FROM messages
WHERE role='assistant' AND created_at > now() - interval '24 hours'
GROUP BY 1;
```

---

## 13. Celery Beat Schedule

```python
# wismo/settings/celery.py (hay apps/telemetry/apps.py)

CELERY_BEAT_SCHEDULE = {
    # Daily aggregation
    'aggregate-daily-stats': {
        'task': 'telemetry.tasks.aggregate_daily_stats',
        'schedule': crontab(hour=0, minute=5),          # 00:05 mỗi ngày
    },
    # Alert checks
    'check-validation-fail-rate': {
        'task': 'telemetry.tasks.check_validation_fail_rate',
        'schedule': crontab(minute=0),                   # mỗi giờ
    },
    'check-latency': {
        'task': 'telemetry.tasks.check_latency',
        'schedule': crontab(minute='*/15'),              # mỗi 15 phút
    },
    # Archive
    'archive-old-messages': {
        'task': 'telemetry.tasks.archive_old_messages',
        'schedule': crontab(hour=3, minute=0, day_of_month=1),  # ngày 1 mỗi tháng, 3AM
    },
    # Cleanup
    'cleanup-expired-guest-sessions': {
        'task': 'telemetry.tasks.cleanup_expired_guest_sessions',
        'schedule': crontab(hour=4, minute=0),           # 4AM hàng ngày
    },
    'cleanup-old-attack-logs': {
        'task': 'telemetry.tasks.cleanup_old_logs',
        'schedule': crontab(hour=3, minute=30),          # 3:30AM hàng ngày
    },
}
```

---

## 14. Constraints cho Agent Implementation

### Files cần tạo

```
apps/telemetry/
├── __init__.py
├── models.py               ← DailyStats, FeedbackLog, CrisisEvent, AttackLog,
│                              GDPRAuditLog, SensitiveAccessAudit
├── services/
│   ├── __init__.py
│   ├── telemetry_service.py ← TelemetryService facade
│   └── gdpr_audit.py        ← GDPRAuditService
├── views.py                ← MessageFeedbackView (POST /feedback/)
├── urls.py
└── tasks.py                ← aggregate_daily_stats, check_validation_fail_rate,
                               check_latency, archive_old_messages,
                               cleanup_expired_guest_sessions
```

### Hard rules cho agent

1. `crisis_events` table KHÔNG lưu `user_id` — chỉ `session_hash` (anonymous)
2. `gdpr_audit_log` giữ 5 năm — Celery cleanup không được xóa trước 5 năm
3. Telemetry service là **sink** — không được đọc ngược domain service để quyết định action
4. `record_turn()` gọi **sau khi** persist final message (step 11 canonical pipeline), không trước
5. `messages.metadata` là JSONB trong cùng row — không có `RequestTrace` table riêng
6. Alert tasks phải idempotent — gửi email chỉ khi vượt threshold, không spam
7. Archive task check S3 connection trước khi delete từ PostgreSQL

### Test suite tối thiểu

```
tests/unit/telemetry/
├── test_telemetry_service.py
│   ├── test_record_turn_writes_metadata
│   ├── test_record_feedback_stores_rating
│   ├── test_record_crisis_anonymous_no_user_id
│   └── test_record_attack_truncates_snippet
├── test_gdpr_audit.py
│   ├── test_log_consent_given
│   ├── test_log_consent_withdrawn
│   ├── test_log_data_export
│   ├── test_log_memory_deleted
│   └── test_log_admin_access
├── test_tasks.py
│   ├── test_aggregate_daily_stats_correct_counts
│   ├── test_aggregate_method_distribution
│   ├── test_check_validation_fail_rate_sends_alert
│   ├── test_check_latency_sends_alert_above_threshold
│   └── test_archive_deletes_after_s3_upload
└── test_feedback_api.py
    ├── test_thumbs_up_stored
    ├── test_thumbs_down_stored
    └── test_invalid_rating_rejected
```

---

## 15. Cross-references

- **Trace model:** `architecture/spec.md` — Section 7.5C `trace.v1` contract
- **Crisis events:** `safety/spec.md` — SafetyStateMachine ghi thông qua `TelemetryService`
- **Memory deletion audit:** `memory/spec.md` — `GDPRAuditService.log_memory_deleted()`
- **Eval nối telemetry:** `prompts/spec.md` — Section 11A mô tả feedback → regression loop
- **Database schema:** `database/spec.md` — SQL đầy đủ cho tất cả telemetry tables
- **Storage:** `infrastructure/spec.md` — S3 bucket config, Contabo credentials
- **Alert từ LLM failover:** `llm/spec.md` — `alert_llm_failover` Celery task (owned bởi `llm` app, dùng cùng alert mechanism)
