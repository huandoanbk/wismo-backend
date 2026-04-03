# Memory Domain Spec — Memory Layer

**Source:** WISMO Project Specification v18, Section 10 (trích lọc và tổng hợp)  
**Scope:** `apps/memory/` — memory item lifecycle, dedup, retrieval, profile facts (P5), cleanup  
**Owner app:** `memory`  
**Không thuộc scope:** session/message transport, SSE, direct chat orchestration

---

## 1. Vai trò và Ranh giới

`memory` là nơi duy nhất sở hữu và quản lý `MemoryItem`. Nó:

- Nhận extraction request từ P5 (sau mỗi turn, qua Celery)
- Dedup embedding mới với existing items
- Cung cấp retrieval API cho Orchestrator/PromptBuilder
- Xử lý user-initiated delete và GDPR full cascade
- Đọc consent/profile từ `accounts` (qua facade) — không tự query

**Forbidden:** `memory` không import từ `chat.views`, không tự query `Message`/`Session`, không trực tiếp gọi provider LLM (phải qua `llm` facade). Không tự điều phối chat session.

**Callers:** `chat.services.orchestrator` gọi `MemoryManager.retrieve()` khi build P3 prompt. `chat.tasks` dispatch `extract_memory_facts` sau mỗi turn.

---

## 2. Memory Architecture — 3 tầng

```
Tầng 1: Ephemeral Session State (guest + first turns)
  → Lưu trong session store (Redis hoặc DB session)
  → Không có embedding
  → Xóa khi session kết thúc (guest) hoặc promote khi register

Tầng 2: Long-term Memory Items (registered users)
  → memory_items table với embedding vector (BGE-M3, 1024 dims)
  → Persistent, dedup, sensitivity-controlled
  → Đây là scope chính của memory domain

Tầng 3: Case Context (P4 — short-term per case)
  → Lưu trong user_cases.context_snapshot JSONB
  → Thuộc ownership của case-management, không phải memory
  → memory/spec.md không cover
```

---

## 3. MemoryItem — Model đầy đủ

### 3.1 Field schema

```python
# apps/memory/models.py

class MemoryItem(models.Model):
    """
    Một fact ổn định về user. Persist xuyên cases và sessions.
    Embedding cho semantic search. Sensitivity controls recall policy.
    """

    id                = models.UUIDField(primary_key=True, default=uuid4)
    user              = models.ForeignKey('accounts.User', on_delete=models.CASCADE)

    # Nội dung
    text              = models.TextField()           # fact text ngắn gọn
    embedding         = VectorField(dimensions=1024) # BGE-M3 embedding

    # Phân loại
    tags              = models.JSONField(default=list)   # canonical tag list
    salience          = models.FloatField(default=0.5)   # 0.0-1.0 importance score
    sensitivity       = models.CharField(max_length=20)  # 3 levels (xem mục 4)

    # Extended fields
    retention_policy  = models.CharField(max_length=30)  # permanent/session_only/case_duration/user_controlled/auto_expire_90d
    user_visible      = models.BooleanField(default=True)
    user_editable     = models.BooleanField(default=True)
    source_confidence = models.FloatField(default=1.0)   # 1.0=explicit, 0.5=implication
    usage_scope       = models.CharField(max_length=30)  # all/personalization_only/safety_only

    # Tracking
    source_session    = models.ForeignKey('chat.Session', null=True, on_delete=models.SET_NULL)
    last_seen_at      = models.DateTimeField(null=True)
    occurrence_count  = models.IntegerField(default=1)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'sensitivity']),
            models.Index(fields=['user', 'last_seen_at']),
            # pgvector index tạo bằng migration raw SQL (IVFFlat hoặc HNSW)
        ]
```

### 3.2 Tags phân loại (canonical list)

| Tag | Ví dụ | Nguồn |
|-----|-------|-------|
| `general_fact` | "Làm IT, senior developer" | P5 |
| `demographics` | "Khoảng 30 tuổi" | P5 — chỉ khi user tự nói |
| `occupation` | "Bác sĩ", "Sinh viên năm 3" | P5 |
| `expertise` | "Senior developer", "Chuyên khoa tim mạch" | P5 |
| `family` | "Có 2 con nhỏ", "Sống một mình" | P5 |
| `relationship` | "Vợ hay phàn nàn", "Bố mẹ ở xa" | P5 |
| `trigger` | "Stress khi deadline", "Mất ngủ khi lo lắng" | P5 |
| `coping` | "Đi bộ giúp thư giãn", "Viết nhật ký" | P5 |
| `meditation_exp` | "Đã tham gia 1 khóa thiền" | P5 |
| `location` | "Ở Helsinki", "Mới chuyển đến Phần Lan" | P5 |
| `interest` | "Thích chạy bộ", "Đọc sách" | P5 |
| `contraindication` | "Flashback khi body scan" | P5 → LUÔN `clinical_sensitive` |

---

## 4. Memory Sensitivity — 3 mức (source of truth)

### 4.1 Bảng sensitivity

| Level | Mô tả | Inject vào P3 | Personalizer | Safety | User thấy | Export GDPR |
|-------|--------|:---:|:---:|:---:|:---:|:---:|
| `public_safe` | Facts user tự nói, không nhạy cảm | ✅ | ✅ | ✅ | ✅ rõ ràng | ✅ |
| `private_safe` | Facts cá nhân, hơi nhạy | ❌ KHÔNG inject | ✅ gián tiếp qua style | ✅ | ✅ masked | ✅ |
| `clinical_sensitive` | Trauma, self-harm, contraindication | ❌ KHÔNG BAO GIỜ | ❌ | ✅ Safety ONLY | ⚠ masked + confirm | ❌ |

### 4.2 Ví dụ phân loại cụ thể

```
public_safe:
  "Làm IT, senior developer"  → inject vào P3, dùng metaphor kỹ thuật
  "Có 2 con nhỏ"              → "Với 2 bé, áp lực chắc không ít..."
  "Sống ở Helsinki"           → resource matching

private_safe:
  "Đã ly hôn"                 → KHÔNG nhắc trong response, Personalizer biết context
  "Bố mẹ ở xa"               → KHÔNG nhắc, nhưng biết thiếu support gia đình
  "Hay uống rượu khi stress"  → KHÔNG nhắc, nhưng biết coping pattern

clinical_sensitive:
  "Từng bị bố đánh hồi nhỏ"  → CHỈ dùng cho Safety State Machine
  "Flashback khi body scan"   → contraindication flag → HIGH_RISK state
  "Từng uống thuốc trầm cảm" → scope awareness, KHÔNG nhắc
  "Đã từng tự tử"            → crisis history flag, KHÔNG BAO GIỜ nhắc
```

### 4.3 Retention policy per sensitivity

| Policy | Khi nào xóa | Áp dụng cho |
|--------|-------------|------------|
| `permanent` | Chỉ khi user xóa hoặc delete account | occupation, expertise, location |
| `session_only` | Kết thúc session (guest) | tất cả guest memory |
| `case_duration` | Khi case resolved + 30 ngày | trigger, coping case-specific |
| `user_controlled` | User quyết định | facts user tự thêm qua Settings |
| `auto_expire_90d` | 90 ngày không accessed | minor facts, interest |

---

## 5. Memory Extraction — P5 sau mỗi turn

### 5.1 Trigger và scope

- **Khi nào:** Celery task `extract_memory_facts`, dispatch from `dispatch_after_turn`, ~2s sau turn
- **Input:** last 5 messages + danh sách existing memory items (để dedup prompt-side)
- **Output:** max 3 items dạng `P5ExtractionResult`
- **Model:** DeepSeek V3, ~300 tokens in, ~100 tokens out

### 5.2 P5 Extraction rules (cứng)

```
P5 CHỈ extract khi:
  ✅ User nói RÕ RÀNG, TRỰC TIẾP (explicit statement)
  ✅ source_confidence = 1.0 cho explicit, 0.7+ cho clear implication

P5 KHÔNG extract khi:
  ❌ Suy luận demographic (user nói về con → WISMO KHÔNG suy ra "user ~30 tuổi")
  ❌ Suy luận tính cách → đây là việc của P6
  ❌ Suy luận sức khỏe từ triệu chứng ("mất ngủ" ≠ "có thể bị trầm cảm")
  ❌ Bất kỳ inference nào confidence < 0.7
  ❌ Giới tính, tôn giáo, thu nhập (không thu thập — xem Product spec)

Ví dụ:
  User: "Tôi 35 tuổi, làm IT" → extract ✅ (explicit, confidence=1.0)
  User: "Con tôi 5 tuổi"      → extract "có con 5 tuổi" ✅
                              → KHÔNG extract "user ~30 tuổi" ❌ (inference)
  User: "Tôi hay mất ngủ"    → extract trigger "mất ngủ" ✅
                              → KHÔNG extract "có thể bị trầm cảm" ❌
```

### 5.3 P5ExtractionResult contract (`memory.v1`)

| Field | Type | Required | Fallback |
|-------|------|:---:|--------|
| `schema_version` | string = `memory.v1` | ✓ | `memory.v1` |
| `source_turn_id` | UUID string | ✓ | current turn |
| `text` | string (fact ngắn gọn) | ✓ | bỏ item nếu rỗng |
| `tags` | string[] (canonical list) | ✓ | `[]` |
| `salience` | float 0.0-1.0 | ✓ | `0.5` |
| `sensitivity` | `public_safe` \| `private_safe` \| `clinical_sensitive` | ✓ | `private_safe` |
| `evidence_type` | `explicit_user_statement` \| `explicit_user_preference` | ✓ | reject nếu lạ |
| `recall_policy` | `allowed` \| `silent_use_only` \| `never_recall` | ✓ | theo sensitivity |
| `expires_with_session` | boolean | ✓ | guest=`true`, registered=`false` |
| `dedup_key` | hash string | ✓ | generate từ normalized text + tags |

**Rule:** `clinical_sensitive` mặc định `recall_policy=never_recall`. P5 không được tạo item từ suy luận — chỉ từ explicit statement.

### 5.4 Celery task

```python
# apps/memory/tasks.py

@shared_task(bind=True, max_retries=3)
def extract_memory_facts(self, user_id, session_id, message_text, response_text):
    """
    P5: Chạy after-turn. Extract facts mới → dedup → store.
    Idempotent: kiểm tra dedup_key trước khi tạo mới.
    """
    try:
        result = llm_facade.call(
            prompt=P5_EXTRACTION_PROMPT.format(
                user_message=message_text,
                assistant_response=response_text,
                existing_facts=MemoryManager().get_existing_summary(user_id),
            ),
            step='P5', user_id=user_id,
        )
        items = json.loads(result)  # max 3 items

        for item_data in items:
            MemoryManager().store(user_id, session_id, item_data)

    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
```

---

## 6. Deduplication

### 6.1 Dedup logic

```python
# apps/memory/services/memory_manager.py

def store(self, user_id: str, session_id: str, item_data: dict):
    """Embed mới → dedup với existing → store hoặc update."""

    embedding = self.embedder.embed(item_data['text'])

    # pgvector: tìm existing có cosine similarity ≥ 0.9
    existing = (
        MemoryItem.objects.filter(user_id=user_id)
        .annotate(sim=1 - CosineDistance('embedding', embedding))
        .filter(sim__gte=0.9)
        .first()
    )

    if existing:
        # Update salience + tracking, không tạo mới
        existing.salience = max(existing.salience, item_data['salience'])
        existing.last_seen_at = now()
        existing.occurrence_count = F('occurrence_count') + 1
        existing.save(update_fields=['salience', 'last_seen_at', 'occurrence_count'])
    else:
        MemoryItem.objects.create(
            user_id=user_id,
            text=item_data['text'],
            embedding=embedding,
            tags=item_data['tags'],
            salience=item_data['salience'],
            sensitivity=item_data.get('sensitivity', 'private_safe'),
            retention_policy=self._infer_retention(item_data),
            source_session_id=session_id,
            source_confidence=item_data.get('source_confidence', 1.0),
            usage_scope=self._infer_scope(item_data),
        )
```

**Threshold:** cosine similarity ≥ 0.9 = duplicate → update, không tạo mới.

---

## 7. Memory Retrieval

### 7.1 retrieve() — Composite scoring

```python
def retrieve(self, user, query: str, top_k: int = 5) -> list[MemoryItem]:
    """
    Semantic search với composite re-score.
    KHÔNG bao giờ trả về clinical_sensitive items.
    """
    query_embedding = self.embedder.embed(query)

    # Step 1: pgvector top-20 candidates — loại clinical_sensitive ngay từ query
    candidates = (
        MemoryItem.objects.filter(
            user_id=user.id,
            sensitivity__in=['public_safe', 'private_safe'],
        )
        .exclude(sensitivity='clinical_sensitive')
        .order_by(CosineDistance('embedding', query_embedding))
    )[:20]

    # Step 2: Composite re-score
    scored = []
    for item in candidates:
        cosine_sim = 1 - cosine_distance(query_embedding, item.embedding)
        recency    = self._recency_score(item.last_seen_at)
        final      = cosine_sim * 0.7 + recency * 0.2 + item.salience * 0.1
        scored.append((item, final))

    scored.sort(key=lambda x: x[1], reverse=True)
    results = [item for item, _ in scored[:top_k]]

    # Step 3: Update last_seen
    MemoryItem.objects.filter(id__in=[i.id for i in results]).update(last_seen_at=now())

    return results
```

### 7.2 Recency score

| Thời gian kể từ last_seen | Score |
|--------------------------|-------|
| Hôm nay (≤ 1 ngày) | 1.0 |
| 1–7 ngày | 0.8 |
| 7–30 ngày | 0.5 |
| > 30 ngày | 0.2 |

### 7.3 Số items inject theo context depth

| Context depth | Memory items | Khi nào |
|---------------|:-----------:|---------|
| `LIGHT` | 1–2 | Phase 1, LISTEN mode |
| `MEDIUM` | 3–4 | INQUIRY mode |
| `FULL` | 5 | TEACH mode |

### 7.4 Recall policy enforcement

| Sensitivity | recall_policy | Dùng trong P3 | Dùng trong Personalizer |
|-------------|--------------|:---:|:---:|
| `public_safe` | `allowed` | ✅ inject full text | ✅ |
| `private_safe` | `silent_use_only` | ❌ KHÔNG inject | ✅ gián tiếp |
| `clinical_sensitive` | `never_recall` | ❌ | ❌ |

---

## 8. Data Deletion — GDPR Compliance

### 8.1 Xóa 1 memory item

```python
# apps/memory/services/memory_manager.py

def delete_item(self, user, item_id: str):
    """Xóa 1 memory item theo user request. Ghi GDPR audit."""
    item = MemoryItem.objects.get(id=item_id, user=user)
    item.delete()  # cascade embedding trong cùng row
    GDPRAuditService().log_memory_deleted(user.id, item_id)
```

### 8.2 Xóa tất cả memory

```python
def delete_all_memory(self, user):
    count = MemoryItem.objects.filter(user=user).count()
    MemoryItem.objects.filter(user=user).delete()
    GDPRAuditService().log(user.id, 'all_memory_deleted', detail={'count': count})
```

### 8.3 GDPR full cascade (withdraw consent)

```python
def withdraw_consent_full_delete(self, user):
    """
    Full cascade khi user withdraw consent.
    Xóa theo đúng thứ tự để tránh constraint violation.
    GDPR audit log giữ 5 năm dù xóa hết dữ liệu khác.
    """
    # 1. Chat content
    Message.objects.filter(user=user).delete()
    # 2. Cases + context
    UserCase.objects.filter(user=user).delete()
    # 3. Sessions
    Session.objects.filter(user=user).delete()
    # 4. Memory items + embeddings
    MemoryItem.objects.filter(user=user).delete()
    # 5. Derived profile
    UserPreference.objects.filter(user=user).delete()
    UserState.objects.filter(user=user).delete()
    UserProfile.objects.filter(user=user).delete()
    # 6. Feedback + usage
    FeedbackLog.objects.filter(user=user).delete()
    UsageTracking.objects.filter(user=user).delete()
    # 7. Consent record — ghi withdrawn_at, không xóa row (audit)
    consent = GDPRConsent.objects.filter(user=user).first()
    if consent:
        consent.withdrawn_at = now()
        consent.save()
    # 8. GDPR audit (giữ 5 năm — legal requirement)
    GDPRAuditService().log(user.id, 'full_data_deletion',
                           detail={'reason': 'consent_withdrawn'})
    # 9. Deactivate user account
    user.is_active = False
    user.save()
```

---

## 9. Guest Memory — Ephemeral Snapshot

### 9.1 Guest memory rules

Guest session không có user_id ổn định → memory không persist vào `memory_items` table.

```
Guest session store (Redis/DB session):
  temp_profile:
    occupation: "IT"
    facts: [...]
    demographics_hint: {...}
  temp_state:
    emotion_tag: "stressed"
    severity_score: 6

Rules:
  - Không có embedding, không có pgvector search
  - Không xuất hiện trong Settings memory screen
  - Session kết thúc → xóa toàn bộ ngay lập tức
  - User register trong session → promote snapshot sang memory_items thật
```

### 9.2 Guest-to-registered promotion

Khi guest register/login trong session còn mở:

```python
def promote_guest_snapshot(self, guest_session, new_user):
    """
    Promote ephemeral guest facts → permanent memory_items.
    Chỉ promote public_safe items. Skip clinical_sensitive.
    """
    snapshot = guest_session.get('temp_profile', {})
    facts = snapshot.get('facts', [])

    for fact in facts:
        if fact.get('sensitivity') != 'clinical_sensitive':
            self.store(new_user.id, guest_session.session_key, fact)

    # Xóa guest snapshot
    guest_session.flush()
```

---

## 10. Personalization Integration

### 10.1 Memory → Personalizer

```
MemoryManager.retrieve() → public_safe items → inject vào [USER CONTEXT] trong P3 prompt
                         → private_safe items → Personalizer nhận gián tiếp qua PersonalizerPolicy
                         → clinical_sensitive → KHÔNG BAO GIỜ ra khỏi memory app
```

### 10.2 Safety integration

`SafetyStateMachine` đọc memory tags để quyết định safety state:

```python
# apps/safety/services/safety_state_machine.py — caller example

def _load_memory_flags(self, user_id: str) -> dict:
    """Đọc contraindication + crisis history flags từ memory."""
    flags = MemoryManager().get_safety_flags(user_id)
    # flags = {'has_contraindication': True, 'contraindication_types': [...]}
    return flags
```

`MemoryManager.get_safety_flags()` là read-only facade — chỉ trả về flag summary, không expose raw memory items.

---

## 11. Constraints cho Agent Implementation

### Files cần tạo

```
apps/memory/
├── __init__.py
├── models.py               ← MemoryItem model
├── services/
│   ├── __init__.py
│   ├── memory_manager.py   ← retrieve(), store(), delete_item(), delete_all(), get_safety_flags()
│   └── profile_builder.py  ← promote_guest_snapshot()
└── tasks.py                ← extract_memory_facts Celery task
```

### Hard rules cho agent

1. `memory_manager.retrieve()` KHÔNG BAO GIỜ trả `clinical_sensitive` items — filter ở query level, không ở application level
2. `P5ExtractionResult` phải validate `evidence_type` — reject nếu không phải `explicit_user_statement` hoặc `explicit_user_preference`
3. Dedup check dùng pgvector `CosineDistance`, threshold 0.9 — không dùng exact text match
4. Celery task phải idempotent — kiểm tra `dedup_key` hoặc cosine trước khi insert
5. GDPR cascade xóa theo đúng thứ tự trong `withdraw_consent_full_delete` — không skip step nào
6. Guest memory không bao giờ chạm `memory_items` table — chỉ session store

### Test suite tối thiểu

```
tests/unit/memory/
├── test_memory_manager.py
│   ├── test_retrieve_excludes_clinical_sensitive
│   ├── test_retrieve_composite_scoring
│   ├── test_retrieve_updates_last_seen
│   ├── test_store_dedup_cosine_90_updates_existing
│   ├── test_store_new_item_below_threshold
│   ├── test_delete_item_writes_gdpr_audit
│   └── test_withdraw_consent_cascades_all
├── test_p5_extraction.py
│   ├── test_p5_rejects_inferred_demographic
│   ├── test_p5_accepts_explicit_statement
│   ├── test_p5_max_3_items_per_turn
│   ├── test_clinical_sensitive_never_recall
│   └── test_guest_items_expire_with_session
└── test_guest_promotion.py
    ├── test_promote_skips_clinical_sensitive
    └── test_promote_then_flushes_session
```

---

## 12. Cross-references

- **Sensitivity rules:** nguồn gốc từ `product/spec.md` — giá trị user trust vào WISMO phụ thuộc vào việc memory không bao giờ vi phạm sensitivity rules
- **P5 prompt text:** `prompts/spec.md` — Section 8.6
- **Safety integration:** `safety/spec.md` — SafetyStateMachine đọc memory flags
- **Database schema:** `database/spec.md` — `memory_items` table đầy đủ với pgvector index
- **Telemetry:** Memory deletion, consent withdraw → `gdpr_audit_log` (owned by `telemetry`)
- **Architecture:** `architecture/spec.md` — Section 7.4A: direct model access policy cho `memory`
