# Database Schema — Backend Domain Spec

Tài liệu mô tả toàn bộ database schema: dual database strategy, 22 tables + outbox, SQL schema, Django model patterns, indexes, JSONB conventions, và VectorRouter.

Worker PHẢI đọc file này khi code Django models, migrations, db_router, hoặc bất kỳ service nào query/write database.

---

## 1. Dual Database Strategy

```
postgres-app (port 5432):       19 tables — Django ORM default
  Auth, Chat, Memory, Subscription, Telemetry, Prompt, Ingestion, Outbox

postgres-vector (port 5433):    3 tables — pgvector extension
  source_documents, content_chunks, chunk_embeddings
  Populated bởi Embedding Service TRƯỚC khi app launch
```

Django VectorRouter tự route models đúng DB — code không cần chỉ định manually.

### 1.1 Architecture Decisions đã chốt

- **NoSQL:** KHÔNG CẦN. PostgreSQL JSONB đủ cho metadata, context, strategy.
- **VectorStore abstraction:** KHÔNG CẦN. Dùng pgvector trực tiếp. Migrate sang Qdrant sau nếu cần.
- **collection_id:** KHÔNG DÙNG. Filter bằng source_type + is_active + topic_tags.

---

## 2. Tables Overview — 22 tables + outbox

### postgres-app (port 5432): 20 tables

| Group | Tables | Mô tả |
|-------|--------|-------|
| Auth (5) | users, user_profiles, user_preferences, user_states, gdpr_consent | User identity, profile, consent |
| Chat (3) | sessions, user_cases, messages | Core chat data |
| Memory (1) | memory_items | Long-term user facts (có vector) |
| Subscription (3) | plans, subscriptions, usage_tracking | Phase 2 stubs |
| Telemetry (5) | feedback_log, crisis_events, attack_logs, gdpr_audit_log, daily_stats | Logging + analytics |
| Prompt (1) | prompt_versions | A/B test prompts |
| Ingestion (1) | ingestion_queue | Embedding pipeline queue |
| Outbox (1) | outbox_events | Transactional outbox |

### postgres-vector (port 5433): 3 tables

| Table | Mô tả |
|-------|-------|
| source_documents | Metadata nguồn dữ liệu (PDF, audio, video...) |
| content_chunks | Chunks + enrichment metadata |
| chunk_embeddings | BGE-M3 1024-dim vectors |

---

## 3. SQL Schema — Auth & User

### users
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR UNIQUE,               -- NULL cho guest
    password_hash VARCHAR,              -- NULL cho OAuth
    auth_provider VARCHAR,              -- 'email', 'google'
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP
);
```

### user_profiles
```sql
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    age_range VARCHAR,                  -- 'under_18','18-25','26-35','36-50','50+'
    goal TEXT,
    language VARCHAR DEFAULT 'en',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### user_preferences (P6 detect dần, chỉ registered)
```sql
CREATE TABLE user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    tone VARCHAR DEFAULT 'gentle',          -- direct/gentle/neutral
    verbosity VARCHAR DEFAULT 'medium',     -- short/medium/long
    depth VARCHAR DEFAULT 'moderate',       -- surface/moderate/deep
    experience_level VARCHAR DEFAULT 'beginner',
    trust_level VARCHAR DEFAULT 'guarded',  -- guarded/opening/open
    expressiveness VARCHAR DEFAULT 'mixed', -- expressive/reserved/mixed
    help_seeking VARCHAR DEFAULT 'mixed',   -- proactive/reactive/mixed
    pending_signals JSONB DEFAULT '[]',
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### user_states (P1 update real-time, chỉ registered)
```sql
CREATE TABLE user_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    emotion_tag VARCHAR,
    severity_score INT CHECK (severity_score BETWEEN 0 AND 10),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### gdpr_consent
```sql
CREATE TABLE gdpr_consent (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    consent_version VARCHAR(10),         -- 'v1.0'
    chat_processing BOOLEAN,             -- REQUIRED = true
    memory_storage BOOLEAN,              -- REQUIRED = true (registered); false (guest)
    anonymous_analytics BOOLEAN,         -- optional
    consented_at TIMESTAMP DEFAULT NOW(),
    ip_address INET,
    user_agent VARCHAR(500),
    consent_method VARCHAR(20),          -- 'checkbox_click'
    consent_text_hash VARCHAR(64),       -- SHA-256
    withdrawn_at TIMESTAMP,
    withdrawal_reason TEXT
);
CREATE INDEX idx_consent_user ON gdpr_consent(user_id, consented_at DESC);
```

---

## 4. SQL Schema — Chat Core

### sessions
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    auth_state VARCHAR(20) DEFAULT 'guest',
    guest_session_token VARCHAR UNIQUE,
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    temp_profile_snapshot JSONB DEFAULT '{}',
    temp_case_snapshot JSONB DEFAULT '{}',
    temp_preference_snapshot JSONB DEFAULT '{}',
    temp_state_snapshot JSONB DEFAULT '{}'
);
CREATE INDEX idx_session_user_active ON sessions(user_id, is_active);
```

**Lưu ý:** `temp_*_snapshot` fields dùng cho guest session-scoped state. Registered user KHÔNG dùng.

### user_cases
```sql
CREATE TABLE user_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    topic VARCHAR(200),
    topic_tags TEXT[],
    status VARCHAR(20) DEFAULT 'active',
        -- active / progressing / resolved / paused / inactive / stalled
    current_phase VARCHAR(20) DEFAULT 'understand',
        -- understand / illuminate / followup
    context_gathered JSONB DEFAULT '{}',
        -- {problem, people_involved, trigger, pattern, user_goal,
        --  tried_before, insight, user_proposed_action}
    counseling_strategy JSONB DEFAULT '{}',
        -- {counseling_goal, root_cause_hypothesis, strategy, success_indicators, risks}
    sessions_count INT DEFAULT 1,
    severity_first INT,
    severity_current INT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);
CREATE INDEX idx_case_user_status ON user_cases(user_id, status);
CREATE INDEX idx_case_topic_tags ON user_cases USING GIN(topic_tags);
```

### messages
```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    case_id UUID REFERENCES user_cases(id) ON DELETE SET NULL,
    role VARCHAR(10) NOT NULL,          -- 'user', 'assistant'
    content TEXT NOT NULL,
    emotion_tag VARCHAR(20),
    emotion_severity INT,
    metadata JSONB DEFAULT '{}',        -- pipeline trace ~700 bytes (Section 12)
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_msg_user_time ON messages(user_id, created_at);
CREATE INDEX idx_msg_case_time ON messages(case_id, created_at);
CREATE INDEX idx_msg_session ON messages(session_id);
```

**7.6A bổ sung cho messages (production hardening):**
- Thêm `turn_id` (UUID, indexed) + `sequence_no` (bigint) + `final_status` + `persisted_at` + `archived_at`
- Unique constraint: `(session_id, sequence_no)` và `(turn_id, role)`
- Partial index: `role='assistant' AND final_status IN (...)`
- GIN index trên metadata CHỈ cho fields query thường xuyên: method, phase, validator_action

---

## 5. SQL Schema — Memory

### memory_items
```sql
CREATE TABLE memory_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    embedding VECTOR(1024),             -- BGE-M3
    tags TEXT[],                         -- general_fact/demographics/occupation/trigger/
                                         -- coping/relationship/contraindication...
    salience FLOAT DEFAULT 0.5,
    sensitivity VARCHAR DEFAULT 'public_safe',
        -- public_safe / private_safe / clinical_sensitive
    retention_policy VARCHAR DEFAULT 'permanent',
    user_visible BOOLEAN DEFAULT TRUE,
    user_editable BOOLEAN DEFAULT TRUE,
    source_confidence FLOAT DEFAULT 1.0,
    usage_scope VARCHAR DEFAULT 'all',  -- all / personalization_only / safety_only
    source_session_id UUID,
    occurrence_count INT DEFAULT 1,
    last_seen_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_memory_user ON memory_items(user_id);
CREATE INDEX idx_memory_embedding ON memory_items
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_memory_tags ON memory_items USING GIN(tags);
CREATE INDEX idx_memory_sensitivity ON memory_items(user_id, sensitivity);
```

**Quan trọng:** `sensitivity` default = `'public_safe'` (KHÔNG phải `'safe'`).

---

## 6. SQL Schema — Knowledge / RAG (postgres-vector)

### source_documents
```sql
CREATE TABLE source_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR NOT NULL,       -- pdf/audio/youtube/video/website/slide
    title VARCHAR,
    author VARCHAR,
    language VARCHAR DEFAULT 'vi',
    file_hash VARCHAR(64),              -- SHA-256 dedup
    s3_raw_key VARCHAR,
    s3_text_key VARCHAR,
    type_metadata JSONB DEFAULT '{}',
    total_chunks INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,     -- RAG enable/disable toggle
    ingested_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### content_chunks
```sql
CREATE TABLE content_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES source_documents(id) ON DELETE CASCADE,
    chunk_index INT,
    content TEXT NOT NULL,
    topic VARCHAR(200),
    topic_tags TEXT[],                   -- max 6
    summary TEXT,
    teaching_type VARCHAR(20),          -- story/analogy/explanation/practice/dialogue/reflection
    applicable_issues TEXT[],           -- max 4
    depth_level VARCHAR(15),
    emotional_tone VARCHAR(15),
    page_start INT, page_end INT,
    start_time FLOAT, end_time FLOAT,   -- audio/video seconds
    section_heading VARCHAR,
    content_hash VARCHAR(64),           -- SimHash dedup
    duplicate_of UUID,                  -- NULL = original
    language VARCHAR DEFAULT 'vi',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_chunk_source ON content_chunks(source_id, chunk_index);
CREATE INDEX idx_chunk_topic_tags ON content_chunks USING GIN(topic_tags);
CREATE INDEX idx_chunk_issues ON content_chunks USING GIN(applicable_issues);
CREATE INDEX idx_chunk_dedup ON content_chunks(duplicate_of) WHERE duplicate_of IS NULL;
```

### chunk_embeddings
```sql
CREATE TABLE chunk_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID UNIQUE REFERENCES content_chunks(id) ON DELETE CASCADE,
    embedding VECTOR(1024),             -- BGE-M3
    model_name VARCHAR DEFAULT 'bge-m3',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_embedding_vector ON chunk_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## 7. SQL Schema — Telemetry

### feedback_log
```sql
CREATE TABLE feedback_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    rating SMALLINT,                    -- +1 / -1
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### crisis_events (ANONYMOUS — không có user_id)
```sql
CREATE TABLE crisis_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_hash VARCHAR(64),           -- KHÔNG lưu user_id
    trigger_type VARCHAR(30),
    crisis_level VARCHAR(20),
    detected_keywords TEXT[],
    action_taken VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### attack_logs (ANONYMOUS)
```sql
CREATE TABLE attack_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_hash VARCHAR(64),
    attack_type VARCHAR(30),
    blocked BOOLEAN,
    input_snippet VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### gdpr_audit_log (giữ 5 NĂM — legal)
```sql
CREATE TABLE gdpr_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,                       -- NOT FK — survives user deletion
    action VARCHAR(50),
    detail JSONB DEFAULT '{}',
    ip_address INET,
    performed_by VARCHAR(20),           -- user/system/admin
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_gdpr_user ON gdpr_audit_log(user_id, created_at);
```

### daily_stats (giữ vĩnh viễn)
```sql
CREATE TABLE daily_stats (
    date DATE PRIMARY KEY,
    total_messages INT DEFAULT 0,
    total_sessions INT DEFAULT 0,
    unique_users INT DEFAULT 0,
    method_listen INT DEFAULT 0,
    method_inquiry INT DEFAULT 0,
    method_teach INT DEFAULT 0,
    avg_latency_ms INT DEFAULT 0,
    avg_ttft_ms INT DEFAULT 0,
    p95_latency_ms INT DEFAULT 0,
    total_tokens_in BIGINT DEFAULT 0,
    total_tokens_out BIGINT DEFAULT 0,
    total_feedback_up INT DEFAULT 0,
    total_feedback_down INT DEFAULT 0,
    validation_fail_count INT DEFAULT 0,
    regeneration_count INT DEFAULT 0,
    safe_fallback_count INT DEFAULT 0,
    failover_count INT DEFAULT 0,
    crisis_count INT DEFAULT 0,
    attack_count INT DEFAULT 0,
    rag_used_count INT DEFAULT 0,
    avg_rag_score FLOAT,
    emotion_distribution JSONB DEFAULT '{}',
    avg_severity FLOAT
);
```

---

## 8. SQL Schema — Outbox

### outbox_events
```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type VARCHAR,             -- session/case/consent/account/archive
    aggregate_id UUID,
    event_type VARCHAR,
    event_version VARCHAR,
    payload JSONB,
    idempotency_key VARCHAR UNIQUE,     -- UNIQUE — prevent duplicates
    delivery_state VARCHAR DEFAULT 'pending',
        -- pending / dispatched / failed / dead_lettered / replayed
    attempt_count INT DEFAULT 0,
    available_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    dispatched_at TIMESTAMP
);
CREATE INDEX idx_outbox_dispatch ON outbox_events(delivery_state, available_at);
```

---

## 9. SQL Schema — Subscription (Phase 2 stubs) + Prompt + Ingestion

### plans + subscriptions + usage_tracking
```sql
CREATE TABLE plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR UNIQUE,                -- 'free', 'pro'
    llm_model VARCHAR,
    daily_token_limit INT,
    price_monthly DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    plan_id UUID REFERENCES plans(id),
    status VARCHAR DEFAULT 'active',
    started_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    payment_provider VARCHAR,
    payment_id VARCHAR
);

CREATE TABLE usage_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    date DATE,
    tokens_used INT DEFAULT 0,
    messages_count INT DEFAULT 0,
    UNIQUE(user_id, date)
);
```

### prompt_versions
```sql
CREATE TABLE prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL,
    version INT NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    avg_feedback FLOAT,
    violation_rate FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(name, version)
);
```

### ingestion_queue
```sql
CREATE TABLE ingestion_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES source_documents(id),
    s3_key VARCHAR NOT NULL,
    file_type VARCHAR,
    status VARCHAR DEFAULT 'pending',
    priority INT DEFAULT 5,
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE INDEX idx_queue_status ON ingestion_queue(status, priority);
```

---

## 10. VectorRouter — Django Multi-Database

```python
class VectorRouter:
    """Route knowledge models (SourceDocument, ContentChunk, ChunkEmbedding)
    sang postgres-vector. Tất cả models khác dùng postgres-app default."""
    
    VECTOR_MODELS = {'sourcedocument', 'contentchunk', 'chunkembedding'}
    
    def db_for_read(self, model, **hints):
        if model._meta.model_name in self.VECTOR_MODELS:
            return 'vector'
        return 'default'
    
    def db_for_write(self, model, **hints):
        if model._meta.model_name in self.VECTOR_MODELS:
            return 'vector'
        return 'default'
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if model_name in self.VECTOR_MODELS:
            return db == 'vector'
        return db == 'default'
```

---

## 11. Django Model Patterns

SQL schema ở trên là source of truth. Django models mirror 1:1. Pattern chuẩn:

```python
# Mọi model: UUID PK, explicit db_table, enums from contracts
class UserCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE,
                             related_name='cases')
    topic = models.CharField(max_length=200)
    topic_tags = ArrayField(models.CharField(max_length=30), default=list)
    status = models.CharField(max_length=20, default='active',
                              choices=[(s.value, s.name) for s in CaseStatus])
    current_phase = models.CharField(max_length=20, default='understand',
                                     choices=[(p.value, p.name) for p in CasePhase])
    context_gathered = models.JSONField(default=dict)
    counseling_strategy = models.JSONField(default=dict)
    sessions_count = models.IntegerField(default=1)
    severity_first = models.IntegerField(null=True)
    severity_current = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True)
    
    class Meta:
        db_table = 'user_cases'

class MemoryItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE)
    text = models.TextField()
    embedding = VectorField(dimensions=1024)  # from pgvector.django
    tags = ArrayField(models.CharField(max_length=30), default=list)
    salience = models.FloatField(default=0.5)
    sensitivity = models.CharField(max_length=20, default='public_safe',
                                   choices=[(s.value, s.name) for s in Sensitivity])
    # ... remaining fields mirror SQL
    
    class Meta:
        db_table = 'memory_items'
```

---

## 12. JSONB Conventions

### 12.1 Versioning rule

Mọi JSONB hot payload PHẢI chứa `schema_version` ở top level:
- `messages.metadata` → `{"schema_version": "msg-meta.v1", ...}`
- `user_cases.context_gathered` → `{"schema_version": "case-ctx.v1", ...}`
- `outbox_events.payload` → `{"schema_version": "outbox-event.v1", ...}`

### 12.2 Index rule

GIN index cho JSONB CHỈ khi field thuộc 1 trong 3 nhóm:
1. Request-path lookup / recovery
2. Operational dashboard thường xuyên
3. Audit/legal bắt buộc

Debug hiếm dùng → sequential scan, KHÔNG GIN index.

---

## 13. Cascade Delete & Retention

### 13.1 User delete → CASCADE

```
User delete → CASCADE tất cả:
  messages, user_cases, sessions, memory_items,
  user_profiles, user_preferences, user_states,
  feedback_log, usage_tracking, subscriptions
```

### 13.2 Dữ liệu KHÔNG bị xóa khi user delete

| Table | Lý do |
|-------|-------|
| crisis_events | Anonymous — không có user_id |
| attack_logs | Anonymous — không có user_id |
| daily_stats | Aggregate — không link user |
| gdpr_audit_log | user_id là UUID field (NOT FK) — survives deletion, giữ 5 năm |

### 13.3 Archive strategy

- Hot window: 90 ngày đầu ở primary table
- Sau 90 ngày: archive theo tháng hoặc batch job
- Archive KHÔNG gãy lookup theo message_id, turn_id, session_id

---

## 14. Implementation Rules

- SQL schema ở trên là SOURCE OF TRUTH — Django models mirror 1:1
- Choices cho enums PHẢI import từ `wismo/contracts/enums.py`
- Mọi UUID dùng uuid4 default
- JSONB fields PHẢI có `schema_version`
- `gdpr_audit_log.user_id` là UUID field, KHÔNG phải FK (survives deletion)
- `crisis_events` và `attack_logs` KHÔNG có user_id (anonymous policy)
- `outbox_events.idempotency_key` PHẢI UNIQUE
- `memory_items.sensitivity` default = `'public_safe'`
- `user_cases.status` PHẢI có 6 values (including `inactive`)
- Migrate cả 2 DB: `manage.py migrate --database=default` + `--database=vector`
