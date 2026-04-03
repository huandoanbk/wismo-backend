# Counseling Pipeline — Backend Domain Spec

Tài liệu mô tả cách WISMO tư vấn: 3 phases, 3 methods, prompts P1-P9, PromptBuilder, response templates, và DO NOT REPEAT mechanism.

Worker PHẢI đọc file này khi code SituationAnalyzer (P1), CasePhaseEvaluator (P2), PromptBuilder, ResponseGenerator (P3), hoặc bất kỳ service nào ảnh hưởng nội dung response gửi user.

---

## 1. Counseling Flow — 3 Phases

```
Phase 1: THẤU HIỂU ──→ Phase 2: SOI CHIẾU ──→ Phase 3: THEO DÕI
   (lắng nghe, hỏi)      (khai vấn, câu chuyện)    (check tiến triển)
   1-5 turns              3-10+ turns               1-3 turns
   KHÔNG advice           User TỰ tìm giải pháp     Quay Phase 2
   KHÔNG insight          WISMO chỉ soi đèn          hoặc case mới
```

### 1.1 Phase 1: Thấu hiểu (Understand)

**Mục tiêu:** Hiểu đầy đủ bối cảnh + con người TRƯỚC khi làm bất cứ điều gì.

WISMO cần biết: vấn đề cụ thể, bối cảnh (ai, khi nào, tần suất), cảm xúc user, đã thử gì, user muốn gì.

**Được làm:** lắng nghe, mirror cảm xúc, hỏi cụ thể (ai, khi nào, cảm giác gì), max 1 câu hỏi/response.

**KHÔNG được:** cho lời khuyên, chia sẻ insight/wisdom, gợi ý bài tập, kể câu chuyện RAG, gợi ý thiền.

**Chuyển Phase 2 khi:** vấn đề rõ + pattern/trigger xác định + user goal biết → TẤT CẢ 3 cùng đúng.

### 1.2 Phase 2: Soi chiếu (Illuminate)

**Mục tiêu:** Dẫn user TỰ THẤY gốc rễ + TỰ TÌM giải pháp. Phase chính, có thể nhiều sessions.

**4 công cụ khai vấn:**

| Công cụ | Ví dụ |
|---------|-------|
| Câu hỏi Socratic | "Tại sao bạn nghĩ mình phản ứng như vậy?" |
| Câu chuyện/Wisdom (RAG) | Kể câu chuyện → KHÔNG giải thích → hỏi user liên hệ gì |
| Body awareness | "Khi nghĩ về điều này, cơ thể bạn cảm thấy gì?" |
| Phản chiếu (Reflection) | "Bạn vừa nói [X]. Điều đó có ý nghĩa gì?" |

**Được làm:** Socratic, kể RAG story, body awareness, phản chiếu, validate khi user tự đề xuất.

**KHÔNG được:** "bạn nên...", gợi ý bài tập, cho đáp án, gợi ý thiền, giải thích ý nghĩa câu chuyện.

**Khi user hỏi "phải làm gì?":** Đẩy ngược: "Từ những gì bạn đã thấy, bạn MUỐN làm gì?"

**Khi user tự đề xuất:** Validate → deepen: "Đó là ý tưởng của bạn. Điều gì sẽ giúp bạn NHỚ làm?"

**Trụ cột Tam Học:** Trí tuệ (thấy pattern), Đạo đức (impact lên người khác), Nghị lực (celebrate effort).

### 1.3 Phase 3: Theo dõi (Follow-up)

**Mục tiêu:** Check tiến triển khi user quay lại.

- Có tiến triển → celebrate + deepen (quay Phase 2)
- Không tiến triển → explore tại sao, KHÔNG phán xét
- User resolve → close case
- User topic mới → pause case cũ, Phase 1 case mới

---

## 2. Counseling Methods — 3 methods

| Method | Khi nào | WISMO làm gì | RAG |
|--------|---------|---------------|-----|
| **LISTEN** | User emotional, cần được nghe | Mirror cảm xúc, validate, max 1 câu hỏi nhẹ | Không |
| **INQUIRY** | User đang khám phá, cần đi sâu | Socratic, body awareness, phản chiếu | Không |
| **TEACH** | User sẵn sàng insight | Kể câu chuyện RAG → hỏi user liên hệ gì | Có |

**TEACH:** Không "dạy" user. Là kể story + hỏi user tự rút bài học.

**GUIDE:** Không dùng trong counseling pipeline (chỉ Meditation Pipeline Phase 2 dự án).

---

## 3. Prompts Overview — 9 Runtime + 1 Ingestion

```
REAL-TIME (user đợi):
  P1 ─┐ parallel (~200ms)
  P2 ─┘
  P3 ── streaming (~2-5s)

AFTER-TURN (Celery, parallel, ~2s):
  P4 + P5 + P6

AFTER-SESSION (Celery):
  P7

TRIGGERED (khi điều kiện đúng):
  P8, P9

INGESTION (offline, Embedding Service):
  Chunk Enrichment Prompt
```

Mọi thay đổi P1-P9 / PromptBuilder / system prompt phải kích hoạt eval suite (Section 11A) trước khi merge.

---

## 4. P1: Situation Analyzer

**Mục tiêu:** Đánh giá tình huống NGAY — emotion, safety, intent. KHÔNG quyết định response.

| Thuộc tính | Chi tiết |
|-----------|---------|
| Timing | Mỗi message, real-time, PARALLEL với P2 |
| Input | User message + 3 turns gần nhất |
| Output | P1Output (`p1.v1`) |
| Model | Configurable (free: DeepSeek V3, pro: GPT-4o) |
| Tokens | ~150 in, ~80 out |

### 4.1 P1Output contract (`p1.v1`)

```python
class P1Output(BaseModel):
    schema_version: str = "p1.v1"
    language: str                       # vi, en, fi, unknown
    emotion: EmotionSignal              # primary + severity(0-10) + shift
    intent: str                         # RELATED | UNRELATED | UNSAFE | META_ATTACK
    safety: SafetySignal               # crisis, contraindication, scope
    content: ContentSignal             # topic_tags, is_reporting_result
    session_ending: SessionEndingSignal # is_ending, type
    confidence: float = 0.5
```

**Fallback khi parse fail:** emotion→neutral_unknown/severity 5, intent→RELATED + parse_warning, crisis→False.

**Consumer:** SafetyStateMachine, RuleEngine, telemetry. KHÔNG expose ra frontend.

### 4.2 P1 Prompt

```
Analyze this conversation. Do NOT decide what to do — just describe what you observe.

Conversation (last 3 turns):
{history}

User's latest message: "{message}"

Return ONLY JSON:
{
  "emotion": {"primary": "...", "severity": 0-10, "shift": "..."},
  "intent": "RELATED|UNRELATED|UNSAFE|META_ATTACK",
  "safety": {
    "crisis": true/false,
    "contraindication": {"risk_level": "none|low|moderate|high", "indicators": []},
    "scope": {"in_scope": true/false, "out_of_scope_type": "...", "can_partially_help": ...}
  },
  "content": {"topic_tags": [], "is_reporting_result": true/false},
  "session_ending": {"is_ending": false, "type": null}
}
```

---

## 5. P2: Case Phase Evaluator

**Mục tiêu:** Đánh giá case — context đủ chưa, phase nào, nên làm gì turn này. "Bộ não tư vấn."

| Thuộc tính | Chi tiết |
|-----------|---------|
| Timing | Mỗi message, real-time, PARALLEL với P1 |
| Input | Message + case.context_gathered + case.phase + case.strategy + P1.emotion |
| Output | P2Output (`p2.v1`) |
| Tokens | ~300 in, ~120 out |

### 5.1 P2Output contract (`p2.v1`)

```python
class P2Output(BaseModel):
    schema_version: str = "p2.v1"
    context_assessment: ContextAssessment  # problem_clear, pattern_identified, user_goal_known, missing_info
    phase: str                             # understand | illuminate | followup
    should_transition: bool = False
    next_phase: Optional[str] = None
    readiness: str = "exploring"           # not_ready | exploring | insight | self_resolving
    recommended_action: RecommendedAction  # method + focus + pillar
    confidence: float = 0.5
```

**P4 → P2 cycle:** Turn N-1 P4 tích lũy context → Turn N P2 đọc context cập nhật → đánh giá → response → P4 tích lũy thêm → cycle.

---

## 6. P3: Response Generator

**Mục tiêu:** Sinh response cuối cùng gửi user. Template THAY ĐỔI HOÀN TOÀN theo phase + method.

| Thuộc tính | Chi tiết |
|-----------|---------|
| Timing | Mỗi message, streaming, SAU P1+P2+RuleEngine |
| Input | Prompt assembled by PromptBuilder (400-2500 tokens tùy phase) |
| Output | Text response, SSE token-by-token (50-300 tokens) |
| Model | Configurable |

---

## 7. After-Turn Prompts (P4, P5, P6) — Tóm tắt

| Prompt | Mục tiêu | Timing | Output |
|--------|---------|--------|--------|
| **P4** | Tích lũy context vào case | After-turn, Celery | 8 fields: problem, people, trigger, pattern, goal, tried, insight, user_proposed_action |
| **P5** | Extract long-term facts vào memory | After-turn, Celery | MemoryItemPayload (text, tags, sensitivity) |
| **P6** | Detect personality signals | After-turn, Celery | P6PersonalitySignalResult (dimension, value, confidence) |

P4+P5+P6 chạy PARALLEL, qua outbox dispatch (không Celery trực tiếp).

Chi tiết P5/P6: xem `memory-spec.md` và `user-profile-spec.md`.

---

## 8. Triggered Prompts (P7, P8, P9) — Tóm tắt

| Prompt | Trigger | Mục tiêu |
|--------|---------|---------|
| **P7** | Cuối session | Journey summary |
| **P8** | ≥3 turns + topic rõ | Conversation title |
| **P9** | P2 says Phase 1→2 | Case goal & strategy (1 lần per case) |

Chi tiết P9: xem `case-management-spec.md` Section 10.

---

## 9. PromptBuilder — Semi-Dynamic, Config-Driven

PromptBuilder assemble P3 prompt theo config per method. Thay đổi config = thay đổi behavior, không rewrite code.

### 9.1 METHOD_CONFIG

| Config key | Context depth | RAG chunks | Summary |
|-----------|---------------|------------|---------|
| understand_listen | LIGHT | 0 | none |
| understand_inquiry | LIGHT | 0 | none |
| illuminate_listen | LIGHT | 0 | session |
| illuminate_inquiry | MEDIUM | 0 | both |
| illuminate_teach | FULL | 3 | both |
| followup_listen | LIGHT | 0 | journey |
| followup_inquiry | LIGHT | 0 | journey |

### 9.2 Context Depth

| Depth | Memory items | History turns | System prompt |
|-------|-------------|--------------|--------------|
| LIGHT | 1-2 | 3 | core (~200 tokens) |
| MEDIUM | 3-4 | 5 | core |
| FULL | 5 | 5 | full (~500 tokens, có Tam Học) |

### 9.3 PromptBuilder.build() Flow

```
1. Chọn config từ METHOD_CONFIG[f"{phase}_{method}"]
2. System prompt (core hoặc full)
3. Cultural context
4. Case context + strategy (nếu có)
5. Action instruction (từ RuleEngine: method + sub_action)
6. Style (từ Personalizer: tone, depth, length)
7. Memory (N items theo depth config)
8. RAG chunks (nếu config > 0)
9. Summary (session / journey / both / none)
10. DO NOT REPEAT section
11. Recent history (N turns theo depth)
12. User message
```

---

## 10. Response Templates — P3 per Phase

### 10.1 Phase 1: Understand

```
{system_prompt}

[YOUR ROLE] Phase: UNDERSTANDING
You are gathering information. You DO NOT have the full picture yet.

[CASE STATUS]
Topic: {case_topic}
What you know: {case_context}
What you STILL NEED: {missing_info}

[GUIDELINES]
- Ask about what's MISSING
- Max 1 question per response
- Lead with empathy FIRST, then ask
- Do NOT give advice, insight, or exercises
- Mirror emotions, validate feelings

{cultural_context}
{style_guide}
{memory_section}
[CONVERSATION]
{recent_history}
user: {message}
```

### 10.2 Phase 2: Illuminate

```
{system_prompt}

[YOUR ROLE] Phase: ILLUMINATING through INQUIRY
You are a Socratic guide. Help user SEE, not TELL them.

[CASE STATUS]
Topic: {case_topic}
Context: {case_context}
Strategy: {case_strategy}
Pillar focus: {pillar}

[COUNSELING METHOD — KHAI VẤN]
1. SOCRATIC QUESTIONS
2. STORIES/WISDOM (KHÔNG giải thích ý nghĩa)
3. BODY AWARENESS
4. REFLECTION

CRITICAL RULES:
- NEVER "bạn nên", "hãy thử"
- NEVER give solutions
- User hỏi "phải làm gì?" → turn it back
- User proposes solution → validate + deepen
- ONE question per response

{cultural_context}
{style_guide}
{memory_section}
{rag_section}
{journey_summary}
[CONVERSATION]
{recent_history}
user: {message}
```

### 10.3 Phase 3: Follow-up

```
{system_prompt}

[YOUR ROLE] Phase: FOLLOW-UP
User is returning. Check on progress.

[CASE STATUS]
Topic: {case_topic}
User's proposed action: {user_proposed_action}

[GUIDELINES]
- FIRST: ask about their action
- Tried + positive → celebrate EFFORT, deepen
- Tried + negative → explore gently, adjust
- Didn't try → NO judgment. "Không sao."

{cultural_context}
{style_guide}
{memory_section}
{journey_summary}
[CONVERSATION]
{recent_history}
user: {message}
```

---

## 11. Method Instructions — Inject vào [ACTION]

### LISTEN sub-actions

| Sub-action | Instruction |
|-----------|-------------|
| validate | Mirror emotion + validate pain, max 1 gentle question, short (3-5 sentences) |
| normalize | "Nhiều người cũng cảm thấy như vậy", tạo safe space |
| hold_space | Acknowledge without analyzing, "Mình ở đây lắng nghe" |
| celebrate | Celebrate EFFORT not result, hỏi cảm giác khi thử |

### INQUIRY sub-actions

| Sub-action | Instruction |
|-----------|-------------|
| gather_context | Hỏi missing_info, lead empathy then question, ONE specific question |
| deepen | Socratic uncover patterns, "Tại sao bạn nghĩ...?" |
| body_check | "Cơ thể bạn cảm nhận gì?" — connect mind+body |
| reflect_back | User hỏi "phải làm gì?" → turn back: "Bạn MUỐN làm gì?" |
| perspective | "Nếu bạn thân gặp chuyện này, bạn sẽ nói gì?" |
| check_progress | Follow-up: "Lần trước bạn nói sẽ [action]. Có gì mới?" |

### TEACH sub-actions

| Sub-action | Instruction |
|-----------|-------------|
| share_wisdom | Kể RAG story → KHÔNG giải thích → hỏi user liên hệ gì |
| reframe | Dùng wisdom offer new lens, frame as observation not advice |
| explain_concept | Giải thích secular, connect situation, hỏi how applies |

---

## 12. DO NOT REPEAT Mechanism

Inject `[DO NOT REPEAT]` section vào prompt để tránh WISMO lặp ý:

```python
def _build_do_not_repeat(self, recent_turns):
    """Extract key points WISMO đã nói → inject để tránh lặp."""
    wismo_messages = [t.content for t in recent_turns if t.role == 'assistant']
    if not wismo_messages:
        return ""
    
    key_points = []
    for msg in wismo_messages[-3:]:  # last 3 responses
        questions = re.findall(r'[^.!]*\?', msg)
        if questions:
            key_points.append(f"Already asked: {questions[0][:50]}")
    
    if not key_points:
        return ""
    
    return f"""
[DO NOT REPEAT]
You have already covered these points. Do NOT repeat:
{chr(10).join('- ' + p for p in key_points)}
Find a NEW angle or go DEEPER.
"""
```

---

## 13. System Prompt — 2 versions

### SYSTEM_CORE (~200 tokens)

Dùng cho: LISTEN, INQUIRY, Phase 1, Phase 3.

```
You are WISMO, a reflective companion for self-understanding.
You help people explore their mind through mindful self-reflection.
You are NOT a therapist, NOT a clinical service, NOT a crisis hotline.
You speak the user's language naturally.
Rules: Never mention Buddhism/Vipassana/religion.
Never diagnose. Never use clinical language.
If crisis: show 09 2525 0111.
Validate emotions, not cognitive distortions.
```

### SYSTEM_FULL (~500 tokens)

Dùng cho: TEACH trong Phase 2. SYSTEM_CORE + Tam Học + khai vấn rules.

---

## 14. Counseling Rules — Tình huống đặc biệt

```
R_ILLUMINATE_3: User hỏi "phải làm gì?"
  → INQUIRY/reflect_back → "Bạn MUỐN làm gì?"
  → KHÔNG BAO GIỜ đưa đáp án

R_ILLUMINATE_4: User tự đề xuất giải pháp
  → LISTEN/validate + INQUIRY/deepen
  → "Đó là ý tưởng của bạn. Điều gì giúp bạn thực hiện?"

R_PHASE_TRANSITION: understand → illuminate
  → Khi: problem_clear + pattern_identified + user_goal_known
  → Trigger P9

R_PHASE_TRANSITION: illuminate → followup
  → Khi session kết thúc tự nhiên (KHÔNG CÓ phase "act")

R_PHASE_TRANSITION: followup → illuminate
  → Khi user quay lại cùng case → check → deepen
```

---

## 15. Cost Per Message

```
Real-time:  P1+P2+P3   ~$0.0003 - $0.001
After-turn: P4+P5+P6   ~$0.00023
Total/message:          ~$0.0006
Per session (~8 msgs):  ~$0.005
Per day (100 sessions): ~$0.50
Per month (100/day):    ~$15
```

---

## 16. Implementation Rules

- P1 + P2 PARALLEL (giảm latency 200ms → 100ms)
- P3 SAU P1+P2+SafetyGate+RuleEngine (canonical order)
- P4+P5+P6 SAU persist qua outbox (không Celery trực tiếp)
- PromptBuilder CHỈ assemble — không chứa counseling logic
- RuleEngine quyết method, PromptBuilder chọn config
- ResponseValidator check output TRƯỚC khi emit
- Mọi prompt changes → eval suite trước merge
