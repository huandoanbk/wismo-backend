# Prompts Spec — P1–P9, PromptBuilder & RuleEngine

**Source:** WISMO Project Specification v18, Section 8  
**Scope:** `apps/chat/services/prompt_builder.py`, `apps/counseling/`, `apps/chat/services/rule_engine.py` — toàn bộ 9 prompts runtime + PromptBuilder + RuleEngine  
**Ai đọc:** Agent làm S3.x (P1/P2 pipeline), S4.x (orchestrator + prompt builder), S5.x (RAG + TEACH), bất kỳ task touch prompt hay counseling logic  
**Không thuộc scope:** LLM provider routing → `llm/spec.md`; Safety state machine → `safety/spec.md`

---

## 1. Tổng quan 9 Prompts

```
REAL-TIME (user đợi, ~200–5000ms total):
  P1 ─┐ parallel
  P2 ─┘ (~200ms) → Rule Engine → P3 streaming (~2–5s)

AFTER-TURN (Celery, user không đợi, ~2s):
  P4 + P5 + P6  parallel

AFTER-SESSION (Celery):
  P7

TRIGGERED (khi điều kiện đúng):
  P8  ← khi ≥ 3 turns + topic rõ
  P9  ← khi Phase 1 → Phase 2 transition

INGESTION (offline, Embedding Service — KHÔNG thuộc chatbot runtime):
  Chunk Enrichment Prompt (xem embedding/ingestion-spec.md)
```

**Cross-reference Section 11A:** mọi thay đổi đối với P1–P9, PromptBuilder, system prompt, output schema, hoặc prompt routing đều phải kích hoạt suite eval tương ứng trong Section 11A trước khi merge. Không xác nhận prompt quality bằng review thủ công đơn lẻ.

---

## 2. LLM Config per Prompt Step

| Step | Free model | Pro model | Max tokens | Temperature |
|------|-----------|-----------|:---:|:---:|
| P1: Situation Analyzer | DeepSeek V3 | GPT-4o | 100 | 0.3 |
| P2: Case Phase Evaluator | DeepSeek V3 | GPT-4o | 150 | 0.3 |
| P3: Response Generator | DeepSeek V3 | GPT-4o | 300 | 0.7 |
| P4: Case Context Accumulator | DeepSeek V3 | DeepSeek V3 | 150 | 0.3 |
| P5: Profile Facts Builder | DeepSeek V3 | DeepSeek V3 | 150 | 0.3 |
| P6: Personality Signal Detector | DeepSeek V3 | DeepSeek V3 | 80 | 0.3 |
| P7: Journey Summary | DeepSeek V3 | DeepSeek V3 | 200 | 0.5 |
| P8: Conversation Title | DeepSeek V3 | DeepSeek V3 | 30 | 0.7 |
| P9: Goal & Strategy Builder | DeepSeek V3 | DeepSeek V3 | 300 | 0.5 |

**P1+P2+P3:** Tier-dependent — pro user = GPT-4o, quality cao hơn cho counseling phức tạp.  
**P4–P9:** Luôn DeepSeek V3 — background tasks, user không thấy trực tiếp, tối ưu cost.

---

## 3. P1 — Situation Analyzer

**Mục tiêu:** Đánh giá tình huống NGAY — emotion, safety, intent. Prompt ngắn, focused, chỉ safety-critical signals.  
**Timing:** Real-time, parallel với P2. ~150 tokens in, ~80 tokens out.  
**Cost:** ~$0.00006/call

### 3.1 P1 Prompt Text

```
Analyze this conversation. Do NOT decide what to do — just describe what you observe.

Conversation (last 3 turns):
{history}

User's latest message: "{message}"

Return ONLY JSON:
{{
  "emotion": {{
    "primary": "calm|anxious|stressed|sad|angry|confused|hopeful|overwhelmed|grateful|neutral_unknown",
    "severity": 0-10,
    "shift": "stable|escalating|de_escalating|new_topic|unknown"
  }},
  "intent": "RELATED|UNRELATED|UNSAFE|META_ATTACK",
  "safety": {{
    "crisis": true/false,
    "contraindication": {{
      "risk_level": "none|low|moderate|high",
      "indicators": []
    }},
    "scope": {{
      "in_scope": true/false,
      "out_of_scope_type": "none|medication|diagnosis|trauma|substance|other",
      "can_partially_help": true/false
    }}
  }},
  "content": {{
    "topic_tags": [],
    "is_reporting_result": true/false,
    "has_question": true/false
  }},
  "session_ending": {{
    "is_ending": true/false,
    "type": "explicit_bye|inactivity|energy_fading|natural_end|null"
  }},
  "readiness": "not_ready|exploring|insight|self_resolving"
}}

READINESS GUIDE:
- not_ready: user emotional, venting, overwhelmed
- exploring: sharing details, thinking aloud
- insight: seeing patterns, self-reflecting  
- self_resolving: proposing own solution
```

### 3.2 P1Output Contract (`p1.v1`)

| Field | Type | Allowed | Required | Fallback |
|-------|------|---------|:---:|--------|
| `schema_version` | string | `p1.v1` | ✓ | `p1.v1` |
| `emotion.primary` | string | 10 values | ✓ | `neutral_unknown` |
| `emotion.severity` | int | 0–10 | ✓ | `0` |
| `emotion.shift` | string | 5 values | ✓ | `unknown` |
| `intent` | string | `RELATED\|UNRELATED\|UNSAFE\|META_ATTACK` | ✓ | `RELATED` |
| `safety.crisis` | bool | — | ✓ | `false` |
| `safety.contraindication.risk_level` | string | `none\|low\|moderate\|high` | ✓ | `none` |
| `safety.scope.in_scope` | bool | — | ✓ | `true` |
| `safety.scope.can_partially_help` | bool | — | ✓ | `true` |
| `content.topic_tags` | string[] | free | ✓ | `[]` |
| `content.is_reporting_result` | bool | — | ✓ | `false` |
| `readiness` | string | 4 values | ✓ | `exploring` |

**Runtime rules:**
- Parse bằng schema validator trước khi dùng cho business logic. Enum sai → map về fallback, ghi `parse_warning` telemetry.
- Nếu `safety.crisis=true` hoặc `risk_level=high` → downstream ưu tiên cao hơn personalization.
- Field ngoài schema → bỏ qua, không dùng trong business logic.

---

## 4. P2 — Case Phase Evaluator

**Mục tiêu:** Đánh giá case: context đủ chưa, phase nào, nên làm gì turn này — "bộ não tư vấn" mỗi turn.  
**Timing:** Real-time, parallel với P1. ~300 tokens in, ~120 tokens out.  
**Cost:** ~$0.00012/call

### 4.1 P2 Prompt Text

```
You are evaluating the counseling case to guide what WISMO should do next.

Case topic: {case_topic}
Current phase: {current_phase}
Context gathered so far: {context_gathered}
Case strategy (if any): {case_strategy}

User's emotion (from analysis): severity={severity}, state={emotion_primary}
User readiness: {readiness}

Assess:
1. What information is still missing for full understanding?
2. Is the context complete enough to transition to Phase 2 (Illuminate)?
3. What should WISMO focus on this turn?

Return ONLY JSON:
{{
  "context_assessment": {{
    "problem_clear": true/false,
    "people_known": true/false,
    "pattern_identified": true/false,
    "user_goal_known": true/false,
    "missing_info": ["problem_detail|trigger|people|pattern|goal|tried_before"]
  }},
  "phase": "understand|illuminate|followup",
  "status": "active|progressing|paused|stalled|resolved|inactive|archived",
  "should_transition": true/false,
  "next_phase": "understand|illuminate|followup|null",
  "readiness": "not_ready|exploring|insight|self_resolving",
  "recommended_action": {{
    "method": "LISTEN|ASK|REFLECT|TEACH|FOLLOWUP|REDIRECT",
    "focus": "brief description",
    "pillar": "none|wisdom|ethics|perseverance"
  }},
  "reason_codes": [],
  "confidence": 0.0-1.0
}}

TRANSITION RULE: should_transition=true ONLY when ALL of:
  problem_clear=true AND pattern_identified=true AND user_goal_known=true
  AND severity <= 6
```

### 4.2 P2Output Contract (`p2.v1`)

| Field | Required | Fallback |
|-------|:---:|--------|
| `schema_version` = `p2.v1` | ✓ | — |
| `context_assessment.*` (4 booleans + missing_info) | ✓ | all `false`, `[]` |
| `phase` = `understand\|illuminate\|followup` | ✓ | giữ phase hiện tại |
| `status` = 7 values | ✓ | `active` |
| `should_transition` | ✓ | `false` |
| `next_phase` | ✓ | `null` |
| `readiness` = 4 values | ✓ | `exploring` |
| `recommended_action.method` = 6 values | ✓ | `LISTEN` |
| `recommended_action.pillar` = 4 values | ✓ | `none` |

**Runtime rules:**
- `should_transition=true` nhưng `next_phase=null` → invalid → reset `should_transition=false`, log contract violation.
- `phase` và `next_phase` chỉ lấy từ enum chuẩn, không dùng wording tự do từ prompt.
- **Flow P4 → P2:** P4 tích lũy context sau mỗi turn → P2 turn sau đọc context đầy đủ hơn → cycle liên tục.

---

## 5. P3 — Response Generator

**Mục tiêu:** Sinh response cuối cùng gửi user. Template thay đổi **hoàn toàn** theo phase.  
**Timing:** Real-time, streaming. SAU P1 + P2 + RuleEngine.  
**Tokens:** 400–2500 in (tùy phase), 50–300 out. **Cost:** $0.0001–0.0008/call

### 5.1 Input theo Phase

**Phase 1 (Thấu hiểu) — prompt ngắn nhất (~400–600 tokens):**
```
System prompt (SYSTEM_CORE)
Cultural context
Action: "lắng nghe + hỏi {missing_info cụ thể từ P2}"
Style (tone, depth)
Memory (1–2 items)
History (3 turns)
User message

KHÔNG CÓ: RAG, journey summary, strategy
```

**Phase 2 (Soi chiếu) — prompt đầy đủ nhất (~1500–2500 tokens):**
```
System prompt (SYSTEM_FULL — có Tam Học + khai vấn rules)
Cultural context
Action: method + focus + pillar (từ P2)
Case context (đầy đủ từ P4 tích lũy)
Case strategy + counseling goal (từ P9)
Style (tone, depth, verbosity)
Memory (3–5 items)
RAG knowledge (2–3 chunks, khi method=TEACH)
Journey summary (từ P7, nếu returning user)
History (5 turns)
User message
```

**Phase 3 (Theo dõi) — prompt trung bình (~600–800 tokens):**
```
System prompt (SYSTEM_CORE)
Case context + user's proposed actions
Journey summary
Memory (2–3 items)
History (3 turns)
User message
```

### 5.2 Phase 2 Template (P3 prompt text cho illuminate)

```
{system_prompt}

[YOUR ROLE] Phase: ILLUMINATING through INQUIRY
You are a Socratic guide. You help user SEE, not TELL them what to see.

[CASE STATUS]
Topic: {case_topic}
Context: {case_context}
Strategy: {case_strategy}
Pillar focus: {pillar}

[COUNSELING METHOD — KHAI VẤN]
Your tools:
1. SOCRATIC QUESTIONS: questions that help user discover
   - "Tại sao bạn nghĩ mình phản ứng như vậy?"
   - "Nếu bạn thân gặp chuyện này, bạn sẽ nói gì với họ?"
   - "Cảm giác đó có lúc nào KHÔNG xuất hiện không?"

2. STORIES/WISDOM from knowledge base:
   - Kể câu chuyện, để user TỰ rút ra bài học
   - "Có câu chuyện thế này..." → KHÔNG giải thích ý nghĩa
   - Hỏi: "Câu chuyện này gợi cho bạn điều gì?"

3. BODY AWARENESS:
   - "Khi nghĩ về điều này, bạn cảm nhận gì trong cơ thể?"

4. REFLECTION:
   - "Bạn vừa nói [X]. Điều đó có ý nghĩa gì với bạn?"

CRITICAL RULES:
- NEVER say "bạn nên", "hãy thử", "tôi gợi ý"
- NEVER give solutions directly
- When user asks "tôi phải làm gì?":
  Turn it back: "Từ những gì bạn đã thấy, bạn MUỐN làm gì?"
- When user proposes their own solution:
  Validate: "Đó là ý tưởng của bạn."
  Deepen: "Điều gì sẽ giúp bạn thực hiện điều đó?"
- ONE question per response maximum

{style_guide}
{memory_section}
{rag_section}
{journey_summary}

[CONVERSATION]
{recent_history}

user: {message}
```

### 5.3 Response Rules per Phase

| Phase | Rules |
|-------|-------|
| Phase 1 | KHÔNG advice, KHÔNG insight, CHỈ empathy + 1 câu hỏi tìm hiểu |
| Phase 2 | Khai vấn Socratic, kể chuyện để user tự liên hệ, KHÔNG cho đáp án |
| Phase 3 | Hỏi tiến triển, validate effort, KHÔNG phán xét |

### 5.4 P3 Output Contracts

**P3Request (`p3-request.v1`)** — input object cho model call:

| Field | Required | Notes |
|-------|:---:|------|
| `schema_version` = `p3-request.v1` | ✓ | |
| `request_id` (UUID) | ✓ | để trace |
| `language` | ✓ | từ P1/request locale |
| `phase` | ✓ | `understand\|illuminate\|followup` |
| `rule_decision` (rule.v1) | ✓ | |
| `safety_constraints` | ✓ | thiếu → fail-closed safe-only |
| `style_config` | ✓ | từ Personalizer |
| `case_context` | ✗ | guest dùng ephemeral |
| `case_strategy` | ✗ | từ P9 nếu có |
| `memory_context[]` | ✗ | guest: session-scoped only |
| `rag_context[]` | ✗ | chỉ khi `allow_rag=true` |
| `journey_summary` | ✗ | registered returning user mới có |
| `history_window[]` | ✓ | 3–5 turns gần nhất |
| `user_message` | ✓ | |

**P3ValidatedResponse (`p3-response.v1`)** — sau ResponseValidator:

| Field | Required |
|-------|:---:|
| `schema_version` = `p3-response.v1` | ✓ |
| `request_id` | ✓ |
| `response_text` | ✓ — chỉ field này stream ra client |
| `validator_action` = `passed\|regenerated\|safe_fallback` | ✓ |
| `regeneration_count` | ✓ |
| `safety_constraints_applied[]` | ✓ |

---

## 6. P4 — Case Context Accumulator

**Mục tiêu:** Tích lũy thông tin MỚI vào case mỗi turn. Context đầy dần qua conversations.  
**Timing:** After-turn, Celery, parallel với P5+P6. ~200 tokens in, ~100 tokens out.  
**Cost:** ~$0.00008/call

### 6.1 P4 Prompt Text

```
Extract NEW information from this turn that should be added to the case context.
Only extract what is NEW — do not repeat existing context.

Case topic: {case_topic}
Existing context: {existing_context}

Last turn:
Assistant: {assistant_message}
User: {user_message}

Return ONLY JSON (null for fields with no new info):
{{
  "problem_detail": "string or null",
  "people_involved": ["list"] or null,
  "trigger": "string or null",
  "pattern": "string or null",
  "user_goal": "string or null",
  "tried_before": "string or null",
  "insight": "string or null — any realization user had",
  "user_proposed_action": "string or null — action USER proposed (not WISMO)"
}}
```

### 6.2 Ví dụ tích lũy qua 8 turns

```
Turn 1 → {problem: "nổi nóng với con"}
Turn 2 → {trigger: "mệt sau giờ làm"}
Turn 3 → {people_involved: ["vợ"], feeling: "hối hận"}
Turn 4 → {pattern: "suppress at work → explode at home"}
Turn 5 → {user_goal: "không quát con nữa"}
Turn 6 → null  (không có info mới)
Turn 7 → {insight: "vai cứng = tín hiệu giận sắp bùng"}
Turn 8 → {user_proposed_action: "dừng lại lúc cởi giày"}

→ case.context_gathered sau 8 turns đầy đủ → P2 trigger Phase 2
```

### 6.3 P4ExtractionResult Contract (`p4.v1`)

- Schema: 8 optional fields trong `patch` object
- `merge_strategy` = `append|replace_if_better|ignore_duplicate`
- **Rule:** P4 chỉ xuất field mới hoặc rõ hơn đáng kể — không rewrite toàn bộ context mỗi turn
- Merge phải chạy qua deterministic merger — LLM không tự quyết xóa field quan trọng đã có

---

## 7. P5 — User Profile Facts Builder

**Mục tiêu:** Extract facts ổn định về con người user (nghề nghiệp, gia đình, trigger xuyên cases).  
**Timing:** After-turn, Celery, parallel với P4+P6. ~300 tokens in, ~100 tokens out.  
**Cost:** ~$0.0001/call

### 7.1 P5 Prompt Text

```
Extract stable facts about this person from the conversation.
Only extract EXPLICIT statements by the user — do NOT infer or guess.

Existing facts (to avoid duplicates):
{existing_facts_summary}

Last 5 messages:
{recent_messages}

Return ONLY JSON array (max 3 items, empty array if nothing new):
[
  {{
    "text": "concise fact statement",
    "tags": ["occupation|demographics|family|relationship|trigger|coping|location|interest|expertise|meditation_exp"],
    "salience": 0.5-1.0,
    "sensitivity": "public_safe|private_safe|clinical_sensitive",
    "evidence_type": "explicit_user_statement|explicit_user_preference"
  }}
]

EXTRACTION RULES:
- ONLY explicit user statements (confidence >= 0.7)
- DO NOT infer demographics (user mentions child → DO NOT infer their age)
- DO NOT infer health from symptoms
- DO NOT extract gender, religion, income
- clinical_sensitive: trauma, self-harm history, contraindications
```

### 7.2 P5 Rules (cứng)

```
✅ Extract: "Tôi 35 tuổi, làm IT" → text="Làm IT, 35 tuổi", tags=["occupation", "demographics"]
✅ Extract: "Con tôi 5 tuổi" → text="Có con 5 tuổi", tags=["family"]
❌ KHÔNG: từ "Con tôi 5 tuổi" → KHÔNG extract "user ~30 tuổi"
❌ KHÔNG: từ "Hay mất ngủ" → KHÔNG extract "có thể bị trầm cảm"
❌ KHÔNG: giới tính, tôn giáo, thu nhập
```

**Max 3 items per turn. Dedup:** cosine similarity ≥ 0.9 với existing → update salience, không tạo mới.

---

## 8. P6 — Personality Signal Detector

**Mục tiêu:** Detect personality/style preferences dần qua hội thoại. Adjust real-time.  
**Timing:** After-turn, Celery, 1 LLM call nhẹ. ~100 tokens in, ~60 tokens out.  
**Cost:** ~$0.00005/call

### 8.1 P6 Prompt Text

```
Detect communication style preferences from this message.
Only output dimensions you can observe with confidence.

User message: "{user_message}"
Context (optional): {brief_context}

Return ONLY JSON (null for dimensions you cannot determine):
{{
  "tone_signal": "direct|gentle|neutral|null",
  "verbosity_signal": "short|medium|long|null",
  "depth_signal": "surface|moderate|deep|null",
  "experience_signal": "beginner|intermediate|advanced|null",
  "expressiveness_signal": "expressive|reserved|mixed|null",
  "help_seeking_signal": "proactive|reactive|mixed|null",
  "trust_signal": "guarded|opening|open|null",
  "confidence": 0.0-1.0
}}

EXAMPLES:
"Nói ngắn gọn thôi" → verbosity_signal=short, tone_signal=direct
"Tôi không biết thiền là gì" → experience_signal=beginner
Short message, few words → verbosity_signal=short, trust_signal=guarded
```

### 8.2 Accumulation Logic

```
Mỗi turn → P6 detect → tích lũy pending_signals
Threshold: confidence ≥ 0.7 → CONFIRM → update user_preferences
Trước khi confirm → dùng default (gentle, medium, moderate)

Turn 1: {tone: "direct", confidence: 0.4} → pending
Turn 3: {tone: "direct", confidence: 0.5} → pending
Turn 5: {tone: "direct", confidence: 0.7} → CONFIRM ✓
  → user_preferences.tone = "direct"
  → P3 turn sau dùng tone direct ngay
```

**7 dimensions:** tone, verbosity, depth, experience_level, trust_level, expressiveness, help_seeking.  
**Guest:** signals chỉ sống trong session hiện tại.

---

## 9. P7 — User Journey Summary

**Mục tiêu:** Tóm tắt toàn bộ hành trình user xuyên sessions + cases.  
**Timing:** After-session, Celery. ~400 tokens in, ~150 tokens out.  
**Cost:** ~$0.00015/session

### 9.1 P7 Prompt Text

```
Update the user's journey summary with insights from the latest session.
Be concise — 5-8 sentences max. Focus on patterns, growth, key insights.

Previous journey summary:
{previous_summary}

Latest session summary:
Case topic: {session_case_topic}
Key moments: {session_key_moments}
User insights this session: {session_insights}
Emotional arc: {emotional_arc}

Write an updated journey summary in {language}.
Focus on:
1. Overall patterns you've seen across sessions
2. Growth and insights the user has gained
3. What remains to be explored
4. Any recurring themes

Return ONLY the summary text (5-8 sentences).
```

**Dùng khi:** User quay lại + P3 Phase 2 cần toàn cảnh. KHÔNG inject vào Phase 1.

---

## 10. P8 — Conversation Title

**Mục tiêu:** Đặt tên cho case — hiển thị sidebar.  
**Trigger:** khi ≥ 3 turns VÀ P4 đã detect topic rõ. Chạy 1 lần per case.  
**Cost:** ~$0.00003/case

### 10.1 P8 Prompt Text

```
Create a short title (3-5 words) for this conversation based on its topic.

Case topic detected: {case_topic}
Context summary: {brief_context}
Language: {language}

Requirements:
- 3-5 words maximum
- Descriptive but not clinical
- In {language}
- NO quotes, NO punctuation

Examples:
"Stress công việc cuối năm"
"Mối quan hệ với con cái"
"Khó ngủ và lo âu"

Return ONLY the title text.
```

**Default trước khi trigger:** "Cuộc trò chuyện [ngày]". Không generate từ tin nhắn chung chung.

---

## 11. P9 — Case Goal & Strategy Builder

**Mục tiêu:** Xác định mục tiêu tư vấn + chiến lược khai vấn — "bản đồ" cho Phase 2.  
**Trigger:** Khi P2 `should_transition=true` (Phase 1 → Phase 2). Chạy **1 lần per case**.  
**Cost:** ~$0.0002/case (1 lần)

### 11.1 P9 Prompt Text

```
Based on the gathered context, create a counseling strategy for this case.
You are planning how WISMO will guide this person in Phase 2 (Illuminate).

Case context:
{full_case_context}

User profile:
Experience level: {experience_level}
Trust level: {trust_level}
Communication style: {tone}

Create a strategy using Tam Học (Three Trainings) philosophy:
- WISDOM (Paññā): Help user SEE clearly
- ETHICS (Sīla): Help user consider impact on others  
- PERSEVERANCE (Viriya): Celebrate effort, encourage consistency

Return ONLY JSON:
{{
  "counseling_goal": "What should the user discover/realize?",
  "root_cause_hypothesis": "What might be driving this pattern?",
  "strategy": {{
    "primary_pillar": "wisdom|ethics|perseverance",
    "secondary_pillar": "wisdom|ethics|perseverance|null",
    "key_questions": [
      "Socratic question 1",
      "Socratic question 2",
      "Socratic question 3"
    ],
    "relevant_teaching": "Keywords for RAG search (Vietnamese preferred)"
  }},
  "success_indicators": [
    "Observable sign that user has gained insight",
    "Observable sign of progress"
  ],
  "risks": [
    "Potential challenge or sensitivity to watch for"
  ]
}}
```

### 11.2 P9 Ví dụ output

```json
{
  "counseling_goal": "User tự nhận ra cycle suppress→explode và cảm thọ trong cơ thể",
  "root_cause_hypothesis": "Accumulated work stress với không có outlet an toàn",
  "strategy": {
    "primary_pillar": "wisdom",
    "key_questions": [
      "Trước khi quát, cơ thể bạn báo hiệu gì?",
      "Nếu bạn dừng lại 3 giây, bạn sẽ muốn làm gì?",
      "Khi không quát, con bạn phản ứng khác thế nào?"
    ],
    "relevant_teaching": "sân hận tích lũy quan sát cảm thọ"
  },
  "success_indicators": [
    "User reports catching anger before explosion",
    "User proposes own coping solution"
  ],
  "risks": [
    "User may feel guilty about past behavior — address with compassion"
  ]
}
```

### 11.3 GoalStrategyPayload Contract (`p9.v1`)

| Field | Required | Fallback |
|-------|:---:|--------|
| `counseling_goal` | ✓ | `support_user_clarity` |
| `strategy.primary_pillar` = `wisdom\|ethics\|perseverance\|mixed` | ✓ | `wisdom` |
| `strategy.key_questions[]` (0–5) | ✓ | `[]` |
| `strategy.relevant_teaching` | ✗ | `null` |
| `success_indicators[]` | ✓ | `[]` |
| `risks[]` | ✓ | `[]` |

**P9 dùng cho:** P2 đánh giá tiến triển, P3 biết focus pillar nào, RAG search dùng `relevant_teaching`.

---

## 12. System Prompts — 2 versions

### 12.1 SYSTEM_CORE (~200 tokens)

Dùng cho LISTEN, INQUIRY, Phase 1, Phase 3, mọi low-context turns.

```
You are WISMO, a reflective companion for self-understanding.
You help people explore their mind through mindful self-reflection.
You are NOT a therapist, NOT a clinical service, NOT a crisis hotline.
You speak the user's language naturally.

Rules:
- Never mention Buddhism, Vipassana, or religion
- Never diagnose or label mental health conditions
- Never use clinical language: treatment plan, therapy session, intervention, prognosis
- If crisis signals: show hotline 09 2525 0111
- Validate emotions, NOT cognitive distortions
- ONE question per response maximum
- Never say "bạn nên", "hãy thử", "câu trả lời là"
```

### 12.2 SYSTEM_FULL (~500 tokens)

Dùng cho TEACH trong Phase 2 — có Tam Học + khai vấn rules đầy đủ.

```
[SYSTEM_CORE] +

Tam Học philosophy (present as psychology, never religion):
1. WISDOM (Paññā): Help user SEE clearly
   "Điều gì thực sự đang xảy ra bên trong bạn?"
2. ETHICS (Sīla): Help user consider impact on others
   "Hành động này có gây hại cho ai không?"
3. PERSEVERANCE (Viriya): Celebrate effort, encourage consistency
   "Bạn muốn thử điều gì khác lần tới?"

Khai vấn (Socratic inquiry) rules:
- NEVER say "bạn nên", "hãy thử", "tôi gợi ý"
- NEVER give solutions directly
- When user asks "phải làm gì?": turn it back
  → "Từ những gì bạn đã thấy, bạn MUỐN làm gì?"
- When user proposes their own solution:
  → Validate: "Đó là ý tưởng của bạn."
  → Deepen: "Điều gì sẽ giúp bạn thực hiện điều đó?"
  → Do NOT elaborate or suggest more
- ONE question per response maximum
- Use stories from knowledge base — do NOT explain the moral after
  → Ask: "Câu chuyện này gợi cho bạn điều gì?"
```

---

## 13. PromptBuilder — Semi-Dynamic, Config-Driven

### 13.1 METHOD_CONFIG

```python
# apps/chat/services/prompt_builder.py

METHOD_CONFIG = {
    # Phase 1 — understand
    'understand_listen':  {'context_depth': 'LIGHT',  'rag_chunks': 0, 'summary': 'none'},
    'understand_ask':     {'context_depth': 'LIGHT',  'rag_chunks': 0, 'summary': 'none'},

    # Phase 2 — illuminate
    'illuminate_listen':  {'context_depth': 'LIGHT',  'rag_chunks': 0, 'summary': 'session'},
    'illuminate_reflect': {'context_depth': 'MEDIUM', 'rag_chunks': 0, 'summary': 'both'},
    'illuminate_teach':   {'context_depth': 'FULL',   'rag_chunks': 3, 'summary': 'both'},

    # Phase 3 — followup
    'followup_listen':    {'context_depth': 'LIGHT',  'rag_chunks': 0, 'summary': 'journey'},
    'followup_followup':  {'context_depth': 'LIGHT',  'rag_chunks': 0, 'summary': 'journey'},
}

DEPTH_CONFIG = {
    'LIGHT':  {'memory_items': 2, 'history_turns': 3, 'system': 'core'},
    'MEDIUM': {'memory_items': 4, 'history_turns': 5, 'system': 'core'},
    'FULL':   {'memory_items': 5, 'history_turns': 5, 'system': 'full'},
}
```

### 13.2 PromptBuilder.build()

```python
class PromptBuilder:
    """
    Semi-dynamic prompt builder.
    1 function, thay đổi output theo METHOD_CONFIG.
    Tune bằng config dict, không viết lại code.
    """

    def build(
        self,
        phase: str,
        method: str,
        style,               # PersonalizationConfig
        case,                # UserCase or None
        memory: list,        # MemoryItem[]
        rag_chunks: list,    # RAG results
        history: list,       # Message[]
        message: str,
    ) -> str:
        config_key = f'{phase}_{method.lower()}'
        config = METHOD_CONFIG.get(config_key, METHOD_CONFIG['understand_listen'])
        depth  = DEPTH_CONFIG[config['context_depth']]

        sections = []

        # 1. System prompt (core hoặc full)
        system_name = 'system_full' if depth['system'] == 'full' else 'system_core'
        sections.append(self.prompt_registry.get(system_name))

        # 2. Cultural context (language-aware)
        sections.append(self._cultural_context(message))

        # 3. Case context + strategy (nếu có)
        if case and case.context_gathered:
            sections.append(
                f"[CASE]\nTopic: {case.topic}\n"
                f"Context: {json.dumps(case.context_gathered, ensure_ascii=False)}"
            )
        if case and case.counseling_strategy:
            sections.append(f"[STRATEGY]\n{json.dumps(case.counseling_strategy, ensure_ascii=False)}")

        # 4. Action instruction (từ Rule Engine via P3Request)
        sections.append(f"[ACTION] Method: {method}, Phase: {phase}")

        # 5. Style (từ PersonalizerPolicy)
        sections.append(
            f"[STYLE]\nTone: {style.tone}\n"
            f"Depth: {style.depth}\nLength: {style.response_length}\n"
            + ('\n'.join(style.notes) if style.notes else '')
        )

        # 6. Memory (public_safe + private_safe, sensitivity-filtered)
        if memory:
            mem_text = '\n'.join(
                f"- ({','.join(m.tags)}) {m.text}"
                for m in memory[:depth['memory_items']]
            )
            sections.append(f"[USER CONTEXT]\n{mem_text}")

        # 7. RAG knowledge (chỉ khi config cho phép)
        if rag_chunks and config['rag_chunks'] > 0:
            rag_text = '\n---\n'.join(
                c['content'] for c in rag_chunks[:config['rag_chunks']]
            )
            sections.append(f"[KNOWLEDGE]\n{rag_text}")

        # 8. Summary (session / journey / both / none)
        if config['summary'] in ('session', 'both') and case:
            sections.append(f"[SESSION SUMMARY]\n{self._get_session_summary(case)}")
        if config['summary'] in ('journey', 'both'):
            sections.append(f"[JOURNEY]\n{self._get_journey_summary(case.user_id if case else None)}")

        # 9. Conversation history
        hist = self._format_history(history, depth['history_turns'])
        sections.append(f"[CONVERSATION]\n{hist}")

        # 10. User message (luôn cuối cùng)
        sections.append(f"user: {message}")

        return '\n\n'.join(filter(None, sections))
```

---

## 14. RuleEngine — Deterministic Counseling Decisions

RuleEngine là lớp **pure Python, không LLM**. Nhận P1Output + P2Output + safety state + profile/case → trả `RuleDecision` (legacy name trong vài tài liệu cũ: `CounselingDecision`).

### 14.1 RuleDecision Contract (`rule.v1`)

| Field | Type | Allowed |
|-------|------|---------|
| `mode` | string | `LISTEN\|ASK\|REFLECT\|TEACH\|FOLLOWUP\|REDIRECT\|CRISIS_SAFE_ONLY` |
| `submode` | string | `reflection\|clarifying_question\|body_awareness\|story\|resource_redirect\|followup_check\|none` |
| `allow_rag` | bool | `true\|false` |
| `allow_memory` | bool | registered=`true`; guest=session only |
| `safety_state` | string | `NORMAL\|GUARDED\|MODERATE_RISK_SAFE_ONLY\|HIGH_RISK_LISTEN_ONLY\|CRISIS_ONLY\|BLOCKED_MINOR\|BLOCKED_OUT_OF_SCOPE` |
| `response_template` | string | template key |

### 14.2 Rule Priority Order (cao → thấp)

```python
# apps/chat/services/rule_engine.py (excerpt key rules)

class RuleEngine:

    def decide(self, p1_signals, p2_eval, user_profile, case, safety_constraints):
        severity  = p1_signals['emotion']['severity']
        readiness = p1_signals['readiness']
        phase     = p2_eval.get('phase', 'understand')
        content   = p1_signals.get('content', {})

        # ─── PRIORITY 1: Safety hard gates ───
        if safety_constraints['state'] == 'CRISIS_ONLY':
            return RuleDecision(mode='CRISIS_SAFE_ONLY', allow_rag=False, ...)

        if safety_constraints['state'] == 'BLOCKED_OUT_OF_SCOPE':
            return RuleDecision(mode='REDIRECT', allow_rag=False, ...)

        if safety_constraints['state'] in ('HIGH_RISK_LISTEN_ONLY', 'MODERATE_RISK_SAFE_ONLY'):
            return RuleDecision(mode='LISTEN', allow_rag=False, ...)

        # ─── PRIORITY 2: Session ending ───
        if p1_signals.get('session_ending', {}).get('is_ending'):
            submode = 'grounding_close' if severity >= 5 else 'warm_close'
            return RuleDecision(mode='FOLLOWUP', submode='followup_check', allow_rag=False)

        # ─── PRIORITY 3: Emotional severity override ───
        if severity >= 8:
            return RuleDecision(
                mode='LISTEN', submode='none', allow_rag=False,
                reasoning='R10: severity >= 8',
                context_config={'memory_items': 2, 'rag_chunks': 0, 'history_turns': 3}
            )

        if severity >= 6:
            return RuleDecision(
                mode='LISTEN', submode='none', allow_rag=False,
                reasoning='R11: severity 6-7',
                context_config={'memory_items': 2, 'rag_chunks': 0, 'history_turns': 3}
            )

        # ─── PRIORITY 4: Readiness not_ready ───
        if readiness == 'not_ready':
            return RuleDecision(
                mode='LISTEN', submode='none', allow_rag=False,
                reasoning='R12: not_ready'
            )

        # ─── PRIORITY 5: User reporting result ───
        if content.get('is_reporting_result'):
            return RuleDecision(
                mode='LISTEN', submode='none', allow_rag=False,
                reasoning='R13: reporting result'
            )

        # ─── PHASE 1: Understand ───
        if phase == 'understand':
            missing = p2_eval.get('context_assessment', {}).get('missing_info', [])
            return RuleDecision(
                mode='ASK', submode='clarifying_question', allow_rag=False,
                prompt_instruction=f'Ask about: {", ".join(missing)}. Max 1 question.',
                reasoning=f'R30: understand, missing={missing}',
                context_config={'memory_items': 2, 'rag_chunks': 0, 'history_turns': 3}
            )

        # ─── PHASE 2: Illuminate ───
        if phase == 'illuminate':
            # User self-resolving → reflect back
            if readiness == 'self_resolving':
                return RuleDecision(
                    mode='REFLECT', submode='reflection', allow_rag=False,
                    prompt_instruction='Turn it back: "Từ những gì bạn đã thấy, bạn MUỐN làm gì?"',
                    reasoning='R32: self_resolving'
                )

            # User has insight → teach with wisdom story
            if readiness == 'insight':
                strategy = (case.counseling_strategy or {}).get('strategy', {})
                return RuleDecision(
                    mode='TEACH', submode='story', allow_rag=True,
                    rag_query=strategy.get('relevant_teaching', ''),
                    prompt_instruction='Share story/wisdom. Ask what it means to them.',
                    reasoning='R40: insight → teach',
                    context_config={'memory_items': 5, 'rag_chunks': 3, 'history_turns': 5}
                )

            # User has question + exploring → teach
            if content.get('has_question') and readiness == 'exploring':
                return RuleDecision(
                    mode='TEACH', submode='story', allow_rag=True,
                    rag_query=' '.join(content.get('topic_tags', [])),
                    reasoning='R41: has_question'
                )

            # Default illuminate → deepen with inquiry
            return RuleDecision(
                mode='REFLECT', submode='reflection', allow_rag=False,
                prompt_instruction='Socratic question. Help user go deeper.',
                reasoning='R31: illuminate + exploring',
                context_config={'memory_items': 3, 'rag_chunks': 0, 'history_turns': 5}
            )

        # ─── PHASE 3: Followup ───
        if phase == 'followup':
            return RuleDecision(
                mode='FOLLOWUP', submode='followup_check', allow_rag=False,
                prompt_instruction='Ask about progress. Validate effort.',
                reasoning='R50: followup'
            )

        # Default fallback
        return RuleDecision(
            mode='REFLECT', submode='reflection', allow_rag=False,
            reasoning='R99: default'
        )
```

### 14.3 Special Rules

```
R_ILLUMINATE_3: User hỏi "tôi phải làm gì?"
  → REFLECT/reflection
  → "Từ những gì bạn đã thấy, bạn MUỐN làm gì?"
  → KHÔNG BAO GIỜ đưa đáp án

R_ILLUMINATE_4: User tự đề xuất giải pháp
  → LISTEN/validate + REFLECT/reflection
  → "Đó là ý tưởng của bạn. Điều gì sẽ giúp bạn thực hiện?"
  → Validate rồi deepen, KHÔNG suggest thêm

R_PHASE_TRANSITION: understand → illuminate
  → Khi: problem_clear + pattern_identified + user_goal_known
  → Trigger P9 (Goal & Strategy Builder)
```

---

## 15. Cost Summary

```
PER MESSAGE (~1 turn):
  Real-time:   P1 + P2 + P3   = $0.0003–$0.001
  After-turn:  P4 + P5 + P6   = $0.00023
  Total/message               ≈ $0.0006

PER SESSION (~8 messages):
  Messages:     8 × $0.0006   = $0.0048
  After-session: P7            = $0.00015
  Total/session               ≈ $0.005

PER CASE:
  P8 (title):                  $0.00003
  P9 (strategy):               $0.0002
  Total/case                  ≈ $0.0002

PER DAY:
  100 sessions                ≈ $0.50/day
  500 sessions                ≈ $2.50/day
  1000 sessions               ≈ $5.00/day
```

---

## 16. Files cần tạo

```
apps/chat/services/
├── prompt_builder.py   ← PromptBuilder, METHOD_CONFIG, DEPTH_CONFIG
├── rule_engine.py      ← RuleEngine, RuleDecision

apps/counseling/services/
├── situation_analyzer.py   ← P1 call + parse P1Output
├── phase_evaluator.py      ← P2 call + parse P2Output
├── goal_strategy.py        ← P9 call + parse GoalStrategyPayload

apps/chat/tasks.py
  ← dispatch_after_turn: P4 + P5 + P6 parallel
  ← generate_case_title: P8 triggered

apps/personalization/tasks.py
  ← detect_personality_signal: P6

apps/memory/tasks.py
  ← extract_memory_facts: P5

wismo/prompts/  (hoặc DB-backed PromptVersion)
├── system_core.txt
├── system_full.txt
```

---

## 17. Hard Rules cho Agent

1. **P1 + P2 parallel** — không chạy tuần tự, không đợi nhau
2. **RuleEngine là pure Python** — không gọi LLM, không async
3. **P3 chỉ stream sau khi** RuleEngine quyết định method xong
4. **P4/P5/P6 dispatch** sau khi persist final message thành công (step 13 canonical pipeline)
5. **P9 chỉ chạy 1 lần per case** — trigger từ CaseManager khi `should_transition=true`
6. **P8 trigger** sau ≥ 3 turns VÀ topic rõ — không generate từ greeting
7. **`relevant_teaching` từ P9** là RAG query — không dùng raw user message
8. **METHOD_CONFIG là source of truth** cho context depth — không hardcode memory/rag count ở nơi khác

---

## 18. Cross-references

- **LLM routing + model config:** `llm/spec.md` — LLM_CONFIG per step, provider selection
- **Safety constraints → P3:** `safety/spec.md` — SafetyDecision → PromptBuilder + ResponseValidator
- **Memory retrieval → P3:** `memory/spec.md` — MemoryManager.retrieve()
- **RAG retrieval → TEACH:** `architecture/spec.md` + embedding `retrieval-spec.md`
- **Orchestrator flow:** `architecture/spec.md` — Section 7.9A canonical pipeline ordering
- **Eval gate:** Mọi thay đổi P1–P9 → phải pass Section 11A eval suite trước khi merge
