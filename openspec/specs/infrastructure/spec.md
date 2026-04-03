# Infrastructure — Backend Domain Spec

Tài liệu mô tả hạ tầng WISMO backend: VPS, Docker, Nginx, PostgreSQL, Redis, ML models, Vast.ai GPU, S3, deployment, backup, monitoring, incident response, kill switches, NFR/SLOs, và environment variables.

Worker PHẢI đọc file này khi code Docker configs, deployment scripts, backup, monitoring, health checks, kill switches, hoặc bất kỳ thay đổi infra nào.

---

## 1. Hạ tầng tổng quan

```
VPS 12GB RAM, 4vCPU
├── Nginx (reverse proxy, SSL, SSE buffering off)
├── Django + Gunicorn (2 workers, ASGI)
├── Celery workers (2) + Celery Beat
├── Redis (broker + cache, 256MB)
├── PostgreSQL app (port 5432, 1GB shared_buffers)
├── PostgreSQL vector (port 5433, pgvector, 512MB)
└── ML Models (CPU singleton: BGE-M3 ~1.5GB + Reranker ~2GB)

External:
├── Next.js frontend (cùng VPS hoặc Vercel)
├── Vast.ai GPU (on-demand: Whisper + batch embedding)
└── Contabo S3 (EU Germany: raw files, text extracts, archives)
```

---

## 2. VPS Specs & RAM Allocation

**Specs:** 12GB RAM, 4 vCPU (đã có)

| Component | RAM | Note |
|-----------|-----|------|
| Django + Gunicorn (2 workers) | ~500MB | preload_app=True |
| PostgreSQL app | ~1GB | shared_buffers=1GB |
| PostgreSQL vector | ~500MB | shared_buffers=512MB |
| Redis + Celery (2 workers) | ~500MB | |
| BGE-M3 (query, CPU) | ~1.5GB | singleton lazy load |
| bge-reranker-v2-m3 (CPU) | ~2GB | singleton lazy load |
| OS + buffer | ~1GB | |
| **Tổng** | **~7.5GB** | **Dư ~4.5GB headroom** |

**Capacity:** ~100-300 concurrent users (1 msg/phút/user). Reranker ~5 req/s.

**Scaling path:**

| Giai đoạn | Trigger | Action |
|-----------|---------|--------|
| Phase 1 | < 100 concurrent | VPS 12GB gộp |
| Phase 2 | RAM > 80% | Nâng VPS 16-32GB |
| Phase 3 | > 300 concurrent | Tách model VPS riêng 8GB |

---

## 3. Docker Compose

### 3.1 Production (docker-compose.prod.yml)

**Services:**

| Service | Image | Port | Config |
|---------|-------|------|--------|
| postgres-app | postgres:16 | 5432 | shared_buffers=1GB, max_connections=50 |
| postgres-vector | pgvector/pgvector:pg16 | 5433 | shared_buffers=512MB |
| redis | redis:7-alpine | 6379 | maxmemory=256mb, allkeys-lru |
| django | custom Dockerfile | 8000 | gunicorn 2 workers, uvicorn, preload, timeout=120 |
| celery-worker | same image | — | concurrency=2 |
| celery-beat | same image | — | scheduler |
| nginx | nginx:alpine | 80, 443 | SSL, SSE proxy |

### 3.2 Backend Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput 2>/dev/null || true
EXPOSE 8000
CMD ["gunicorn", "wismo.asgi:application", "-k", "uvicorn.workers.UvicornWorker",
     "--workers", "2", "--preload", "--timeout", "120", "--bind", "0.0.0.0:8000"]
```

---

## 4. Nginx Config

```nginx
upstream django { server django:8000; }

server {
    listen 443 ssl;
    server_name wismo.app;
    ssl_certificate /etc/letsencrypt/live/wismo.app/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/wismo.app/privkey.pem;

    # SSE: disable buffering (QUAN TRỌNG)
    proxy_buffering off;
    proxy_cache off;

    location /api/ {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_read_timeout 300s;        # long timeout cho streaming
    }

    location / {
        proxy_pass http://localhost:3000; # Next.js
    }
}
```

---

## 5. PostgreSQL Tuning

```ini
# config/postgresql-app.conf (VPS 12GB)
shared_buffers = 1GB
effective_cache_size = 3GB
work_mem = 16MB
maintenance_work_mem = 256MB
random_page_cost = 1.1              # SSD
effective_io_concurrency = 200      # SSD
max_connections = 50
wal_buffers = 16MB
min_wal_size = 1GB
max_wal_size = 4GB
```

---

## 6. Gunicorn Config

```python
workers = 2
worker_class = 'uvicorn.workers.UvicornWorker'  # async SSE
preload_app = True                               # ML models share memory
timeout = 120                                    # LLM streaming
keepalive = 5
max_requests = 1000                              # memory leak prevention
max_requests_jitter = 50
```

---

## 7. ML Models — Singleton Lazy Load

```python
_embedder = None
_reranker = None

def get_embedder():
    """BGE-M3, ~1.5GB. Load 1 lần, dùng mãi."""
    global _embedder
    if _embedder is None:
        from FlagEmbedding import BGEM3FlagModel
        _embedder = BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)
    return _embedder

def get_reranker():
    """bge-reranker-v2-m3, ~2GB. Load 1 lần, dùng mãi."""
    global _reranker
    if _reranker is None:
        from FlagEmbedding import FlagReranker
        _reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=False)
    return _reranker
```

`preload_app=True` → load trước fork → 2 workers share memory.

---

## 8. Vast.ai GPU — On-demand

**Dùng cho:** Whisper STT + BGE-M3 batch embedding (offline, không real-time).

**Instance specs:** verified, CUDA ≥12.1, GPU RAM ≥16GB, reliability >0.98. Max 2 instances, max $0.50/hr each.

**Auto-scale logic (Celery beat mỗi 5 phút):**
- Pending tasks > 0 + no active instance → create
- Instance idle > 30 phút → destroy
- Health check fail → destroy + create new

**Kill switch:** `disable_rag_runtime` hoặc `disable_primary_provider` disables Vast.ai scaling.

**VPS Internal API (callback từ Vast.ai):**

| Endpoint | Mục đích |
|----------|---------|
| POST /api/internal/transcript-ready/ | Trigger chunk pipeline |
| POST /api/internal/get-chunks/ | Return chunk texts cho embedding |
| POST /api/internal/store-embeddings/ | Save vectors vào pgvector |

Bảo mật: shared secret header hoặc IP whitelist.

---

## 9. Contabo S3

**Provider:** Contabo (EU Germany), S3-compatible. Cost: €2.49/tháng cho 250GB.

| Bucket | Nội dung | Retention |
|--------|----------|-----------|
| wismo-raw-files/ | File gốc (PDF, audio, video) | Tạm — xóa sau process |
| wismo-text-extracts/ | Text extracts (.json.gz) | Vĩnh viễn |
| wismo-archives/ | Messages archive > 90 ngày | Vĩnh viễn |
| wismo-backups/ | DB backups | 30 ngày rolling |

---

## 10. SSL & Domain

```bash
# Let's Encrypt, auto-renew
certbot --nginx -d wismo.app -d www.wismo.app
```

---

## 11. CI/CD — GitHub Actions

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python manage.py test
  deploy:
    needs: test
    steps:
      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          script: |
            cd /home/wismo/app
            git pull origin main
            docker compose -f docker-compose.prod.yml build django
            docker compose -f docker-compose.prod.yml up -d django celery-worker
            docker compose -f docker-compose.prod.yml exec django python manage.py migrate
```

---

## 12. Monitoring

### 12.1 Sentry

```python
# settings/prod.py
import sentry_sdk
sentry_sdk.init(dsn=os.environ['SENTRY_DSN'], traces_sample_rate=0.1)
```

### 12.2 Structured Logging

JSON format → `/var/log/wismo/app.json`, dùng `pythonjsonlogger`.

### 12.3 Health Check Endpoint

```python
# GET /api/health/
def health(request):
    checks = {
        'db_app': check_db('default'),
        'db_vector': check_db('vector'),
        'redis': check_redis(),
        'embedder': get_embedder() is not None,
        'reranker': get_reranker() is not None,
    }
    return JsonResponse(checks, status=200 if all(checks.values()) else 503)
```

---

## 13. Backup & Restore

### 13.1 Backup Policy

- PostgreSQL app + vector: daily full dump (3AM)
- Upload → S3 `wismo-backups/`
- Local: giữ 7 ngày. S3: giữ 30 ngày.
- Checksum trước khi mark success
- Alert nếu > 26h không có backup mới

### 13.2 RPO / RTO Targets

- **RPO:** ≤ 24 giờ (PostgreSQL app + vector)
- **RTO:** ≤ 4 giờ (phục hồi service cốt lõi)
- Redis KHÔNG critical (rebuild được)

### 13.3 Restore Drill (monthly)

1. Lấy backup gần nhất từ S3
2. Restore vào môi trường tách biệt
3. Verify: login, transcript, vector query, chat smoke test
4. Ghi lại: thời gian, file dùng, lỗi gặp, người thực hiện

**Fail 2 lần liên tiếp → block mọi thay đổi infra không khẩn cấp.**

---

## 14. Secrets & Encryption

### 14.1 Secrets Policy

- Secrets chỉ trong `.env` server + GitHub Actions secrets
- KHÔNG commit secrets vào repo
- Rotate: ngay khi nghi lộ, đổi người, hoặc mỗi 90 ngày

### 14.2 Encryption at Rest

- PostgreSQL volumes: disk encryption nếu VPS hỗ trợ
- S3 buckets (backups, archives): server-side encryption BẮT BUỘC
- File export tạm: TTL ngắn, không lưu public

### 14.3 RBAC Tối thiểu

| Role | Có thể | Không nên |
|------|--------|-----------|
| Admin | Vận hành, config, dashboard | Xem full transcript hàng loạt |
| Support | Case hỗ trợ, transcript khi có reason | Crisis review queue |
| Safety reviewer | Crisis events, transcripts liên quan | Infra secrets |
| Developer | Logs, metrics, staging | Production transcript |

---

## 15. Incident Response

### 15.1 Mỗi incident phải có

Severity (Sev-1/2/3), owner, timeline, impact, mitigation, postmortem + regression case.

### 15.2 Severity & Ownership

| Incident class | Owner | Action window |
|---------------|-------|---------------|
| Safety regression / crisis bug | Incident commander | Immediate |
| Data / privacy / delete issue | Incident commander | Immediate |
| Provider outage | Incident commander | Immediate |
| RAG corruption | Incident commander | Same working block |
| Queue backlog / outbox failure | Incident commander | Same working block |

### 15.3 Degraded Mode Matrix

| Condition | Allowed mode | Forbidden | Kill switch |
|-----------|-------------|-----------|------------|
| LLM primary unstable | Fallback provider hoặc safe fallback | Bỏ safety gate | `disable_primary_provider` |
| RAG corpus suspect | No-RAG mode | Dùng source chưa approved | `disable_rag_runtime` |
| Guest attach broken | Disable attach tạm | Attach thủ công nửa chừng | `disable_guest_attach` |
| Queue/outbox broken | Sync core chat only | Fire Celery trực tiếp | Pause non-critical jobs |
| Safety anomaly | Safe fallback only | Tiếp tục TEACH/RAG | `force_safe_fallback_only` |

### 15.4 Canonical Kill Switches

Mỗi switch phải có: owner, conditions, user-visible effect, audit log.

- `disable_rag_runtime`
- `disable_guest_attach`
- `disable_primary_provider`
- `disable_provider_failover`
- `force_safe_fallback_only`

### 15.5 Escalation Rule

Safety/privacy có nguy cơ → **degrade trước, điều tra sau**. Không chắc fallback giữ safety → **safe fallback only**.

### 15.6 Provider Outage Runbook

1. Xác nhận lỗi (health checks, Sentry, failover spike)
2. Chuyển fallback nếu parity hợp lệ
3. Fallback cũng không ổn → degrade: dừng stream mới, thông báo, không gửi partial unsafe
4. Log incident + canary checks sau phục hồi

---

## 16. Non-Functional Requirements (NFR / SLOs)

### 16.1 User-Facing Latency

| Metric | Target | Severity |
|--------|--------|----------|
| P95 first-token (no-RAG) | ≤ 2.5s | Launch-blocking |
| P95 first-token (TEACH + RAG) | ≤ 3.5s | Launch-blocking |
| P95 full-response (normal) | ≤ 12s | Operational |
| P95 full-response (crisis) | ≤ 8s | Launch-blocking |

### 16.2 Retrieval Latency

| Metric | Target |
|--------|--------|
| P95 memory retrieval | ≤ 120ms |
| P95 RAG retrieve + rerank | ≤ 900ms |

### 16.3 Async Freshness

| Queue | P95 age target | Severity |
|-------|---------------|----------|
| After-turn (P4/P5/P6) | ≤ 60s | Operational |
| After-session (P7/P9) | ≤ 5 min | Operational |
| Delete / export | ≤ 15 min | Launch-blocking |
| Repair / dead-letter | ≤ 30 min | Operational |

### 16.4 Data Rights SLA

| Right | SLA |
|-------|-----|
| User export | ≤ 24h |
| User delete (logical) | ≤ 24h |
| Physical cleanup | ≤ 7 ngày |

### 16.5 Streaming & Identity

| Metric | Target |
|--------|--------|
| Concurrent SSE streams | ≥ 200 (Phase 1) |
| SSE reconnect recovery | P99 ≤ 5s |
| Guest attach completion | P95 ≤ 60s |

### 16.6 Recovery & Storage

| Metric | Target | Severity |
|--------|--------|----------|
| App DB RTO | ≤ 4h | Launch-blocking |
| Vector DB RTO | ≤ 6h | Launch-blocking |
| Backup freshness alert | > 26h no backup | Launch-blocking |
| Hot DB growth | ≤ 15GB / 100k sessions | Operational |
| Archive cadence | Messages > 90 days → archive ≤ 24h | Operational |

### 16.7 Safety-Preserving Degradation

- SafetyStateMachine KHÔNG bypass khi timeout/failover (Launch-blocking)
- Failover added latency ≤ +1.5s P95 (Operational)
- Safety và correctness LUÔN ưu tiên hơn latency

---

## 17. Operational Maturity Roadmap

### Tầng 1 — MVP-required (trước launch)

- Backup tự động daily + restore drill monthly
- RPO/RTO targets đo được
- Encryption at rest cho DB volumes + S3
- RBAC tối thiểu
- Sensitive access audit trail
- Incident response runbook bản gọn
- Kill switches hoạt động

### Tầng 2 — Post-MVP (30-60 ngày)

- Access review định kỳ
- Secret rotation cadence chặt hơn
- Restore drill có checklist + biên bản
- Dashboard: backup health, restore time, failover frequency

### Tầng 3 — Scale / compliance

- Formal access recertification
- Break-glass access flow
- Tamper-evident audit trail
- Disaster recovery exercise đa thành phần

---

## 18. Environment Variables

```bash
# Database
DB_APP_PASSWORD=<strong>
DB_VECTOR_PASSWORD=<strong>

# Redis
REDIS_URL=redis://redis:6379/0

# Django
DJANGO_SECRET_KEY=<long-random>
DJANGO_SETTINGS_MODULE=wismo.settings.prod
ALLOWED_HOSTS=wismo.app

# LLM
DEEPSEEK_API_KEY=<key>
OPENAI_API_KEY=<key>

# Contabo S3
S3_ENDPOINT=https://eu2.contabostorage.com
S3_ACCESS_KEY=<key>
S3_SECRET_KEY=<key>

# Vast.ai
VASTAI_API_KEY=<key>
VPS_CALLBACK_URL=https://wismo.app

# Google OAuth
GOOGLE_CLIENT_ID=<id>
GOOGLE_CLIENT_SECRET=<secret>

# Sentry
SENTRY_DSN=<dsn>
```

---

## 19. Cost Summary (Monthly)

| Item | Cost |
|------|------|
| VPS 12GB | ~€15-25 |
| Contabo S3 250GB | €2.49 |
| Domain + SSL | ~€1 |
| Vast.ai GPU | ~€5-20 (on-demand) |
| DeepSeek API | ~€15-75 (100-500 sessions/day) |
| OpenAI API | €0 Phase 1 |
| Sentry | Free tier |
| **Tổng Phase 1** | **~€40-125** |

---

## 20. Frontend Deployment Options

**Phase 1 (khuyến nghị):** Next.js trên cùng VPS, Nginx proxy `/` → localhost:3000.

**Phase 2:** Next.js deploy Vercel, API calls → VPS qua HTTPS. CDN tự động.
