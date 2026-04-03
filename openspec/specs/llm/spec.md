# LLM Domain Spec — Foundation Model Layer

**Source:** WISMO Project Specification v18, Section 11 + 11A  
**Scope:** `apps/llm/` — provider abstraction, routing, failover, streaming, validation  
**Owner app:** `llm`  
**Không thuộc scope:** business logic của counseling/safety/memory — `llm` chỉ route, execute, parse

---

## 1. Vai trò và Ranh giới

`llm` là **infrastructure layer** cuối cùng trong pipeline. Nó:

- Nhận prompt đã build sẵn (từ `chat.services.orchestrator` qua `PromptBuilder`)
- Chọn provider phù hợp với tier + bước (step)
- Gọi provider, stream response về
- Validate response trước khi forward ra client
- Không hiểu ý nghĩa business của output — **không biết** crisis là gì, case là gì

**Forbidden:** `llm` không được import `chat`, `accounts`, `memory`, `knowledge`, `safety`, `counseling`. Không được đọc business state để quyết định routing. Không sở hữu domain logic của bất kỳ step nào.

**Required caller discipline:** Mọi gọi LLM phải đi qua `LLMRouter` — không gọi provider client trực tiếp từ app khác.

---

## 2. Provider Hierarchy & Tier Config

### 2.1 Tiers và providers

| Tier | Primary | Fallback 1 | Fallback 2 |
|------|---------|------------|------------|
| `free` | DeepSeek V3 | GPT-4o-mini | Friendly error |
| `pro` (Phase 2) | GPT-4o | DeepSeek V3 | GPT-4o-mini |

**Lý do DeepSeek V3 cho free tier:** Cost ~$0.14/1M input, quality đủ tốt, streaming support đầy đủ.  
**Lý do GPT-4o cho pro tier:** Quality cao hơn cho khai vấn phức tạp, instruction following tốt hơn. Phải pass evaluation parity test (Section 10) trước khi dùng cho P1/P2/P3.

### 2.2 LLM_CONFIG — mỗi step có config riêng

```python
# apps/llm/config.py

LLM_CONFIG = {
    'free': {
        'P1': {'model': 'deepseek-v3', 'max_tokens': 100,  'temperature': 0.3},
        'P2': {'model': 'deepseek-v3', 'max_tokens': 150,  'temperature': 0.3},
        'P3': {'model': 'deepseek-v3', 'max_tokens': 300,  'temperature': 0.7},
        'P4': {'model': 'deepseek-v3', 'max_tokens': 150,  'temperature': 0.3},
        'P5': {'model': 'deepseek-v3', 'max_tokens': 150,  'temperature': 0.3},
        'P6': {'model': 'deepseek-v3', 'max_tokens': 80,   'temperature': 0.3},
        'P7': {'model': 'deepseek-v3', 'max_tokens': 200,  'temperature': 0.5},
        'P8': {'model': 'deepseek-v3', 'max_tokens': 30,   'temperature': 0.7},
        'P9': {'model': 'deepseek-v3', 'max_tokens': 300,  'temperature': 0.5},
    },
    'pro': {
        'P1': {'model': 'gpt-4o', 'max_tokens': 100,  'temperature': 0.3},
        'P2': {'model': 'gpt-4o', 'max_tokens': 150,  'temperature': 0.3},
        'P3': {'model': 'gpt-4o', 'max_tokens': 300,  'temperature': 0.7},
        'P4': {'model': 'deepseek-v3', 'max_tokens': 150, 'temperature': 0.3},
        'P5': {'model': 'deepseek-v3', 'max_tokens': 150, 'temperature': 0.3},
        'P6': {'model': 'deepseek-v3', 'max_tokens': 80,  'temperature': 0.3},
        'P7': {'model': 'deepseek-v3', 'max_tokens': 200, 'temperature': 0.5},
        'P8': {'model': 'deepseek-v3', 'max_tokens': 30,  'temperature': 0.7},
        'P9': {'model': 'deepseek-v3', 'max_tokens': 300, 'temperature': 0.5},
    }
}
```

**Rule:** P4–P9 luôn DeepSeek V3 bất kể tier — background tasks, user không thấy, cost tối ưu. Chỉ P1/P2/P3 tier-dependent vì ảnh hưởng trực tiếp chất lượng response user thấy.

---

## 3. Provider Abstraction

### 3.1 BaseLLMProvider (abstract)

```python
# apps/llm/providers/base.py

from abc import ABC, abstractmethod
from typing import AsyncGenerator

class BaseLLMProvider(ABC):
    """Abstract base cho mọi LLM provider. Stream-first design."""

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator[dict, None]:
        """Stream response từng chunk. Yield dict với key 'text' hoặc 'error'."""
        ...

    @abstractmethod
    async def call(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Non-streaming call cho background steps (P4-P9)."""
        ...
```

### 3.2 DeepSeekProvider

```python
# apps/llm/providers/deepseek.py

import httpx, json
from .base import BaseLLMProvider

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek V3 provider — primary cho free tier và background steps."""

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout

    async def stream(self, prompt, model, max_tokens, temperature):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", DEEPSEEK_API_URL,
                                     json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        text = chunk["choices"][0]["delta"].get("content", "")
                        if text:
                            yield {"text": text}

    async def call(self, prompt, model, max_tokens, temperature) -> str:
        """Non-streaming cho P4-P9."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
```

### 3.3 OpenAIProvider

```python
# apps/llm/providers/openai_provider.py

class OpenAIProvider(BaseLLMProvider):
    """GPT-4o / GPT-4o-mini provider — pro tier và fallback."""
    ...
```

---

## 4. LLMRouter — Routing + Failover

### 4.1 Router logic

```python
# apps/llm/services/llm_router.py

class LLMRouter:
    """
    Nhận prompt + step + tier → chọn provider → stream với failover.
    Không biết gì về business meaning của step (crisis, counseling, v.v.).
    """

    PROVIDER_PRIORITY = {
        'free': ['deepseek-v3', 'gpt-4o-mini'],
        'pro':  ['gpt-4o', 'deepseek-v3', 'gpt-4o-mini'],
    }

    def __init__(self):
        self.providers = {
            'deepseek-v3': DeepSeekProvider(api_key=settings.DEEPSEEK_API_KEY),
            'gpt-4o':      OpenAIProvider(model='gpt-4o'),
            'gpt-4o-mini': OpenAIProvider(model='gpt-4o-mini'),
        }
        self.health = ProviderHealthTracker()

    async def stream(self, prompt: str, step: str, user) -> AsyncGenerator[dict, None]:
        tier    = getattr(user, 'subscription_tier', 'free')
        config  = LLM_CONFIG[tier][step]
        primary = config['model']

        if not self.health.is_healthy(primary):
            async for chunk in self._try_fallbacks(tier, step, prompt, skip=primary):
                yield chunk
            return

        try:
            provider = self.providers[primary]
            async for chunk in provider.stream(
                prompt, primary, config['max_tokens'], config['temperature']
            ):
                yield chunk
            self.health.record_success(primary)

        except (TimeoutError, httpx.HTTPStatusError) as e:
            self.health.record_failure(primary, type(e).__name__)
            yield {'info': 'Đang kết nối lại...'}
            async for chunk in self._try_fallbacks(tier, step, prompt, skip=primary):
                yield chunk

    async def _try_fallbacks(self, tier, step, prompt, skip=None):
        config = LLM_CONFIG[tier][step]
        for model in self.PROVIDER_PRIORITY[tier]:
            if model == skip or not self.health.is_healthy(model):
                continue
            try:
                provider = self.providers[model]
                async for chunk in provider.stream(
                    prompt, model, config['max_tokens'], config['temperature']
                ):
                    yield chunk
                self.health.record_success(model)
                return
            except Exception as e:
                self.health.record_failure(model, str(e))
                continue
        raise LLMUnavailableError("All providers unavailable")
```

### 4.2 Failover chain

```
Request → Primary provider
            │
            ├── Success → return stream
            ├── Timeout (15s) → Fallback 1
            ├── Rate limit (429) → Wait 2s + retry 1x → Fallback 1
            ├── Server error (500/502/503) → Fallback 1 ngay
            └── Invalid response → Retry 1x → Fallback 1

Fallback 1 fail → Fallback 2
Tất cả fail → raise LLMUnavailableError → user thấy friendly error
```

---

## 5. Circuit Breaker — ProviderHealthTracker

```python
# apps/llm/services/health_tracker.py

class ProviderHealthTracker:
    """
    Circuit breaker per provider.
    5 failures liên tiếp → OPEN 60s → HALF-OPEN → test 1 call → CLOSE/OPEN.
    Redis-backed — survive restart.
    """

    def record_success(self, provider: str):
        self.redis.lpush(f"llm:health:{provider}",
                         json.dumps({'status': 'ok', 'ts': time.time()}))
        self.redis.ltrim(f"llm:health:{provider}", 0, 99)
        self.redis.delete(f"llm:breaker:{provider}")   # đóng circuit nếu HALF-OPEN

    def record_failure(self, provider: str, error_type: str):
        self.redis.lpush(f"llm:health:{provider}",
                         json.dumps({'status': 'fail', 'error': error_type,
                                     'ts': time.time()}))
        self.redis.ltrim(f"llm:health:{provider}", 0, 99)

    def is_healthy(self, provider: str) -> bool:
        if self.redis.exists(f"llm:breaker:{provider}"):
            return False   # circuit OPEN

        recent = self.redis.lrange(f"llm:health:{provider}", 0, 4)
        if len(recent) >= 5:
            fails = sum(1 for r in recent if json.loads(r)['status'] == 'fail')
            if fails >= 5:
                self.redis.setex(f"llm:breaker:{provider}", 60, '1')  # OPEN 60s
                return False
        return True
```

**State transitions:**
- `CLOSED` → 5 failures liên tiếp → `OPEN` (60s)
- `OPEN` → sau 60s → `HALF-OPEN`: cho phép 1 test call
- `HALF-OPEN` success → `CLOSED` | fail → `OPEN` thêm 60s

---

## 6. Streaming — SSE từ LLM đến User

### 6.1 Flow

```
LLM Provider (stream=true)
    │ tokens từng cái
    ▼
LLMRouter.stream() async generator
    │
    ▼
ResponseValidator — incremental check trên buffer
    │
    ▼
Django StreamingHttpResponse
    │ SSE: data: {"type": "token", "text": "..."}
    ▼
Next.js useChatStream hook — render token-by-token + cursor ▊
```

### 6.2 Canonical SSE events từ LLM layer

| Event | Khi nào | Payload |
|-------|---------|---------|
| `thinking` | Bắt đầu xử lý | `{}` |
| `token` | Mỗi token stream | `{"text": "..."}` |
| `info` | Failover notice | `{"message": "Đang kết nối lại..."}` |
| `done` | Hoàn thành + persist OK | `ChatDonePayload` |
| `error` | Lỗi không recover | `{"message": "...", "code": "..."}` |

**Rule:** `done` chỉ emit **sau khi** assistant message đã persist thành công.

### 6.3 Streaming scope

**Chỉ P3 (Response Generator) dùng streaming.** P1, P2, P4–P9 dùng `provider.call()` — chờ full response, dễ parse JSON output hơn, user không cần thấy real-time.

---

## 7. ResponseValidator — Validation + Regeneration

### 7.1 Vị trí trong pipeline

ResponseValidator chạy **sau** P3 stream, **trước** khi emit `done`. Là **bắt buộc**, không phải optional post-process.

### 7.2 Hard violations — regenerate bắt buộc

```python
# apps/llm/services/response_validator.py

class ResponseValidator:
    """
    Validate = rule-based (regex), ~1-2ms, KHÔNG gọi LLM thêm.
    Hard violations → REGENERATE.
    Soft violations → log Phase 1, regenerate Phase 2+.
    """

    GLOBAL_FORBIDDEN = [
        # Tôn giáo
        "Phật giáo", "Vipassana", "kinh Phật", "đạo Phật",
        "theo đạo", "thiền định theo", "kinh điển phật",
        # Lâm sàng
        "kế hoạch điều trị", "liệu trình", "chẩn đoán",
        "bệnh nhân", "can thiệp", "tiên lượng", "kê đơn",
        # Directive
        "bạn nên ngay", "hãy thử ngay", "câu trả lời là",
    ]

    def validate(
        self,
        response_text: str,
        safety_constraints: dict,
        method: str = 'LISTEN',
        style_config: dict | None = None,
    ) -> ValidationResult:
        violations = []
        text_lower = response_text.lower()

        # ── HARD: Global forbidden terms ──
        for term in self.GLOBAL_FORBIDDEN:
            if term.lower() in text_lower:
                violations.append(Violation(
                    type='global_forbidden', severity='HARD', detail=f'Term: "{term}"'
                ))

        # ── HARD: Safety-state-specific banned content ──
        for banned in safety_constraints.get('banned_content', []):
            if banned.lower() in text_lower:
                violations.append(Violation(
                    type='safety_banned_content', severity='HARD',
                    detail=f'Banned in state {safety_constraints["state"]}: "{banned}"'
                ))

        # ── HARD: Exercise whitelist check ──
        if safety_constraints.get('allowed_exercises') != 'all':
            whitelist = safety_constraints.get('allowed_exercises', [])
            exercise_keywords = [
                'bài tập', 'exercise', 'thở', 'breathing',
                'body scan', 'grounding', 'quan sát cơ thể',
            ]
            for kw in exercise_keywords:
                if kw in text_lower:
                    if not any(ex.lower() in text_lower for ex in (whitelist or [])):
                        violations.append(Violation(
                            type='exercise_not_whitelisted', severity='HARD',
                            detail=f'Exercise "{kw}" not in whitelist'
                        ))

        # ── HARD: Required content (vd: crisis copy phải có hotline) ──
        for required in safety_constraints.get('required_content', []):
            if required.lower() not in text_lower:
                violations.append(Violation(
                    type='missing_required', severity='HARD',
                    detail=f'Missing required: "{required}"'
                ))

        # ── SOFT: Method compliance ──
        if method == 'LISTEN':
            directive_patterns = ['bạn nên', 'hãy thử', 'tôi gợi ý', 'bạn cần phải']
            for pat in directive_patterns:
                if pat in text_lower:
                    violations.append(Violation(
                        type='method_directive', severity='SOFT',
                        detail=f'LISTEN method but directive: "{pat}"'
                    ))

        if method == 'INQUIRY':
            question_count = response_text.count('?')
            if question_count == 0:
                violations.append(Violation(
                    type='missing_question', severity='SOFT',
                    detail='INQUIRY method but no question mark found'
                ))

        # ── SOFT: Length check ──
        if style_config:
            word_count = len(response_text.split())
            if style_config.get('response_length') == 'short' and word_count > 150:
                violations.append(Violation(
                    type='too_long', severity='SOFT',
                    detail=f'Style=short but {word_count} words'
                ))

        # ── SOFT: Too many questions ──
        if response_text.count('?') > 2:
            violations.append(Violation(
                type='too_many_questions', severity='SOFT',
                detail=f'{response_text.count("?")} question marks (max 2)'
            ))

        return ValidationResult(
            passed=len([v for v in violations if v.severity == 'HARD']) == 0,
            violations=violations,
        )
```

### 7.3 Violation severity policy

| Severity | Khi nào | Action |
|----------|---------|--------|
| **HARD** | Religious terms, safety banned content, missing required | REGENERATE bắt buộc |
| **SOFT** | Method compliance, length, question count | Log Phase 1; regenerate Phase 2+ |

**Soft violations chỉ log trong Phase 1** để tránh over-regenerating khi model mới, chưa calibrated. Từ Phase 2 (sau baseline đủ data) → regenerate cả soft.

### 7.4 Regeneration flow

```
Hard violation detect → REGENERATE (tối đa 2 lần)
  Lần 1: same prompt + explicit constraint reminder
  Lần 2: regenerate
  Vẫn fail → SAFE FALLBACK (pre-written, không gọi LLM)

Safe fallback strings per method:
  LISTEN:  "Mình nghe bạn. Cảm giác của bạn hoàn toàn hợp lý."
  INQUIRY: "Bạn có thể kể thêm cho mình hiểu rõ hơn không?"
  TEACH:   "Đây là câu hỏi hay. Bây giờ bạn cảm thấy thế nào?"
  DEFAULT: "Mình đang lắng nghe bạn."
```

**Rule:** Không bao giờ gửi response có HARD violation đến user.

### 7.5 Error handling table

| Lỗi | Xử lý | User thấy |
|-----|-------|-----------|
| Timeout (15s) | Failover → Fallback 1 | "Đang kết nối lại..." |
| Rate limit (429) | Wait 2s + retry 1x → Fallback 1 | Chậm hơn bình thường |
| Server error 500/502/503 | Failover ngay | Không thấy gì (transparent) |
| Tất cả providers fail | Friendly error | "Xin lỗi, WISMO đang gặp sự cố. Vui lòng thử lại." |
| HARD violation | Regenerate → safe fallback | Không thấy gì |
| SOFT violation | Log; regenerate nếu Phase 2+ | Không thấy gì |
| Stream gián đoạn | Hiện response đã nhận + retry button | "⚠ Phản hồi bị gián đoạn" |
| Circuit breaker open | Auto-skip, dùng fallback | Không thấy gì (transparent) |

---

## 8. Token Tracking

Mỗi LLM call ghi vào `messages.metadata` JSONB:

```json
{
  "tokens_analyzer_in":   150,
  "tokens_analyzer_out":  80,
  "tokens_response_in":   1200,
  "tokens_response_out":  250,
  "tokens_total":         1680,
  "model_analyzer":       "deepseek-v3",
  "model_response":       "deepseek-v3",
  "had_failover":         false,
  "validation_passed":    true,
  "regeneration_count":   0,
  "user_tier":            "free"
}
```

Daily aggregate → `usage_tracking` table (per user per day). Phase 2: quota enforcement dựa trên `usage_tracking`.

---

## 9. Prompt Versioning & A/B Testing

Prompts lưu trong `prompt_versions` table (DB-backed), có versioning.

```python
# apps/llm/services/prompt_registry.py

class PromptRegistry:
    """
    Lấy prompt text theo name. Support A/B test khi có 2 versions active.
    Fallback về hardcoded prompt nếu DB không có.
    """

    def get(self, name: str, user=None) -> tuple[str, str | None]:
        """Returns (prompt_text, version_id)."""
        active = PromptVersion.objects.filter(
            name=name, is_active=True
        ).order_by('-version')

        if active.count() == 1:
            p = active.first()
            return p.content, p.id

        if active.count() >= 2:
            # A/B: deterministic assignment theo user_id hash
            idx = hash(str(user.id)) % active.count() if user else 0
            p = active[idx]
            return p.content, p.id

        # Fallback → hardcoded
        return HARDCODED_PROMPTS.get(name, ''), None
```

**A/B test tracking:** mỗi response ghi `prompt_version_id` vào `messages.metadata` → telemetry correlation với thumbs up/down, regeneration rate, violation rate.

**Khi nào bump version:** thay đổi bất kỳ text nào trong P1–P9 hoặc system prompt → tạo version mới, set `is_active=True`, giữ bản cũ để rollback.

---

## 10. Alert & Monitoring

```python
# apps/llm/tasks.py

@shared_task
def alert_llm_failover(primary: str, fallback: str, error: str):
    """Khi failover > 5 lần trong 10 phút → email admin."""
    count_key = f"failover_count:{primary}"
    count = cache.incr(count_key)
    cache.expire(count_key, 600)

    if count > 5:
        send_mail(
            subject=f"[WISMO] LLM {primary} unhealthy — failover to {fallback}",
            message=f"Provider {primary} failed {count}x in 10min. Error: {error}",
            from_email=settings.ALERT_FROM,
            recipient_list=[settings.ADMIN_EMAIL],
        )
```

| Điều kiện | Hành động |
|-----------|-----------|
| Failover > 5 lần / 10 phút | Email admin |
| Validation fail rate > 10% / 1 giờ | Email admin |
| Average latency > 5s / 15 phút | Email admin |
| Circuit breaker OPEN cho primary | Log + alert |

---

## 11. Eval Framework — Khi nào bắt buộc chạy

Mọi thay đổi ảnh hưởng model call phải chạy eval trước merge. Không xác nhận bằng review thủ công đơn lẻ.

### 11.1 Trigger bắt buộc

- Đổi model primary hoặc fallback
- Đổi prompt text P1–P3 hoặc system prompt
- Đổi `RuleEngine` / `SafetyStateMachine` / `ResponseValidator`
- Đổi streaming hoặc failover behavior
- Trước public launch
- Sau incident Sev-1 hoặc Sev-2

### 11.2 Risk tiers

| Tier | Mô tả | Policy |
|------|--------|--------|
| **T0** | Critical safety / privacy / state integrity | Zero tolerance — 1 failure = block release |
| **T1** | High-risk boundary drift | Ngưỡng rất thấp, không được trade với T2 |
| **T2** | Quality / style / resilience | Ngưỡng cụ thể, không được dùng để bù T0/T1 |

### 11.3 Eval suites liên quan LLM layer

| Suite | Phạm vi |
|-------|---------|
| Safety | Crisis recall, out-of-scope, medical advice, religious terms, clinical language |
| Boundary | Method compliance, phase behavior, no-advice adherence |
| Personalization | Style limits, trust cap, severity override behavior |
| Conversation Quality | Brand voice, empathy, Socratic quality |
| Infra / Failover | Failover parity, degraded mode, stream interruption |

### 11.4 Rules

- Ưu tiên test end-to-end (qua Orchestrator) hơn test prompt đơn lẻ
- Dataset multilingual: vi, fi, en — tối thiểu 3 ngôn ngữ
- Threshold lưu trong `thresholds.yaml`, thay đổi cần sign-off
- Failover parity: mọi model swap phải giữ boundary/safety — không swap chỉ vì cost/latency
- **Không** failover sang provider chưa pass eval parity

---

## 12. Files cần tạo

```
apps/llm/
├── __init__.py
├── config.py                  ← LLM_CONFIG dict
├── exceptions.py              ← LLMUnavailableError, ProviderError
├── providers/
│   ├── __init__.py
│   ├── base.py                ← BaseLLMProvider (abstract)
│   ├── deepseek.py            ← DeepSeekProvider
│   └── openai_provider.py     ← OpenAIProvider
├── services/
│   ├── __init__.py
│   ├── llm_router.py          ← LLMRouter (stream + failover)
│   ├── health_tracker.py      ← ProviderHealthTracker (circuit breaker)
│   ├── response_validator.py  ← ResponseValidator (hard + soft violations)
│   └── prompt_registry.py     ← PromptRegistry (versioning + A/B)
└── tasks.py                   ← alert_llm_failover Celery task
```

---

## 13. Hard Rules cho Agent

1. `LLMRouter` không import từ `chat`, `safety`, `counseling`, `accounts` — không exception
2. `ResponseValidator` nhận `safety_constraints` như parameter — không tự đọc safety state
3. Provider clients không hardcode business terms (`CRISIS_ONLY`, `counseling`, v.v.)
4. Circuit breaker state lưu Redis — không in-memory dict (không survive restart)
5. Mọi stream generator phải là `async` — không dùng sync streaming
6. `LLM_CONFIG` là source of truth duy nhất cho model assignment — không hardcode ở provider hay router
7. Safe fallback strings hardcoded per method — không gọi LLM thêm khi regeneration fail
8. `LLMUnavailableError` → Orchestrator catch → emit SSE `error` — không crash silently
9. Mọi thay đổi model/prompt → chạy eval trước merge (Section 11)

---

## 14. Test Suite tối thiểu

```
tests/unit/llm/
├── test_providers.py
│   ├── test_deepseek_stream_mock
│   ├── test_openai_stream_mock
│   ├── test_provider_timeout_raises
│   └── test_provider_429_raises
├── test_llm_router.py
│   ├── test_primary_success_no_failover
│   ├── test_primary_timeout_triggers_fallback
│   ├── test_all_providers_fail_raises
│   ├── test_circuit_breaker_5_fails_opens
│   ├── test_circuit_breaker_open_skips_provider
│   ├── test_circuit_breaker_half_open_after_60s
│   └── test_failover_info_event_emitted
├── test_health_tracker.py
│   ├── test_record_success_closes_circuit
│   ├── test_record_5_failures_opens_circuit
│   └── test_is_healthy_returns_false_when_open
└── test_response_validator.py
    ├── test_hard_religious_term_blocked
    ├── test_hard_safety_banned_blocked
    ├── test_hard_exercise_not_whitelisted
    ├── test_hard_missing_required_content
    ├── test_soft_listen_directive_logged
    ├── test_soft_inquiry_no_question_logged
    ├── test_soft_too_long_logged
    ├── test_safe_fallback_listen_text
    ├── test_safe_fallback_inquiry_text
    └── test_valid_response_passes
```

---

## 15. Cross-references

- **Orchestrator flow:** `architecture/spec.md` — Section 7.9A canonical ordering, step 9–10
- **Safety constraints → ResponseValidator:** `safety/spec.md` — SafetyDecision.constraints
- **Prompt build → LLMRouter:** `prompts/spec.md` — PromptBuilder.build() → LLMRouter.stream()
- **Eval suites chi tiết:** Section 11A trong main spec (crisis recall, boundary, infra)
- **Telemetry:** `telemetry/spec.md` — `messages.metadata` JSONB, `usage_tracking` table
- **Prompt versions DB:** `database/spec.md` — `prompt_versions` table
