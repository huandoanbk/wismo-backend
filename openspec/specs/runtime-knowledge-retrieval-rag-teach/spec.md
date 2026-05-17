## Purpose
Định nghĩa contract runtime cho Main Flow Step 9 (Knowledge retrieval / RAG TEACH), bao gồm retrieval gate, query/embedding/rerank/stitch flow, fallback non-fatal, và output handoff cho Step 10 prompt assembly.
## Requirements
### Requirement: Step 9 chỉ chạy retrieval cho TEACH path được Step 8 cho phép
Runtime MUST chạy Step 9 retrieval chỉ khi `response_method = TEACH`, `retrieval_required = true`, và `final_safety_state` cho phép retrieval.

#### Scenario: Retrieval gate pass
- **WHEN** Step 8 chốt `response_method = TEACH`
- **AND** `retrieval_required = true`
- **AND** `final_safety_state = normal`
- **THEN** runtime MUST chạy Step 9 retrieval pipeline

#### Scenario: Retrieval gate skip
- **WHEN** một trong các điều kiện gate không đạt
- **THEN** runtime MUST set `retrieval_result = null`
- **AND** MUST append `retrieval_debug_meta.retrieval_status = skipped`
- **AND** MUST đi tiếp Step 10

### Requirement: Step 9 chỉ dùng runtime state và không reload context nền
Step 9 MUST chỉ dùng `runtime_bundle` và output Step 8 cho query/retrieval decisions, và MUST NOT reload `current_message`, `context_summary`, `user_profile`, `user_preference`, `user_state`, `long_term_memory`, `recent_turns` từ DB.

#### Scenario: Runtime bundle usage contract
- **WHEN** Step 9 build retrieval query và execute retrieval
- **THEN** input context MUST lấy từ runtime state hiện có
- **AND** Step 9 MUST NOT query lại context nền Step 6

### Requirement: Retrieval query phải đi qua operation registry
Step 9 MUST gọi query-builder qua `OperationKey.RETRIEVAL_QUERY_BUILDER` bằng `LLMGateway`, không gọi provider trực tiếp.

#### Scenario: Query builder operation routing
- **WHEN** Step 9 cần build `retrieval_query`
- **THEN** runtime MUST gọi `LLMGateway.complete(operation_key=retrieval_query_builder, ...)`
- **AND** output query MUST được normalize trước khi search

#### Scenario: Query builder fail fallback
- **WHEN** query-builder gateway/parse fail
- **THEN** runtime MUST fallback query tối thiểu từ `current_message`
- **AND** MUST tiếp tục retrieval pipeline

### Requirement: Vector retrieval chỉ search knowledge enabled corpus
Step 9 MUST search chỉ trên knowledge corpus enabled (`SourceDocument.is_enabled=true`, `ContentChunk.is_enabled=true`) và MUST không search memory tables/recent turns.

#### Scenario: Enabled-only retrieval scope
- **WHEN** Step 9 execute vector retrieval
- **THEN** runtime MUST filter enabled source/chunk
- **AND** MUST NOT query memory tables làm retrieval corpus

### Requirement: BE-17 dùng dense-only retrieval trong scope sprint hiện tại
Trong BE-17, retrieval ranking MUST dùng dense cosine path làm canonical prerank; `sparse/lexical` và `RRF` không nằm trong phạm vi triển khai sprint này.

#### Scenario: Dense-only ranking in BE-17
- **WHEN** Step 9 chạy retrieval trong BE-17
- **THEN** runtime MUST dùng dense retrieval để tạo prerank shortlist
- **AND** MUST không phụ thuộc sparse/lexical index hoặc RRF fusion để hoàn tất Step 9

### Requirement: Query embedding phải ưu tiên gateway và fallback local
Step 9 MUST convert `retrieval_query` thành embedding vector bằng cơ chế gateway-first và local fallback.

#### Scenario: Embedding gateway-first success
- **WHEN** operation `retrieval_query_embedding` qua `LLMGateway` khả dụng và trả vector hợp lệ
- **THEN** runtime MUST dùng vector từ gateway để chạy dense retrieval

#### Scenario: Embedding gateway fail then local success
- **WHEN** operation `retrieval_query_embedding` lỗi (missing config/provider/parse) nhưng local embedding client thành công
- **THEN** runtime MUST fallback local embedding client
- **AND** MUST tiếp tục retrieval pipeline

#### Scenario: Embedding dual-path failure
- **WHEN** cả gateway embedding và local embedding đều thất bại
- **THEN** runtime MUST set `retrieval_result = null`
- **AND** MUST set `retrieval_debug_meta.retrieval_status = embedding_failed`
- **AND** MUST đi tiếp Step 10 (non-fatal)

### Requirement: Step 9 phải chọn primary chunk với rerank fallback an toàn
Step 9 MUST chọn `primary_chunk` từ candidate shortlist; nếu reranker fail/unavailable thì MUST fallback về prerank ordering.

#### Scenario: Reranker success
- **WHEN** reranker available và chạy thành công
- **THEN** runtime MUST dùng rerank order để chọn `primary_chunk`
- **AND** MUST set debug meta `reranker_used = true`

#### Scenario: Reranker failure fallback
- **WHEN** reranker fail hoặc unavailable
- **THEN** runtime MUST fallback prerank top-1 làm `primary_chunk`
- **AND** MUST set debug meta `reranker_failed = true` và `fallback_to_prerank = true`

### Requirement: Reranker service contract phải rõ và có timeout-safe fallback
Step 9 MUST gọi reranker qua HTTP contract chuẩn hóa và MUST fallback prerank cho mọi lỗi transport/payload.

#### Scenario: Reranker HTTP contract success
- **WHEN** reranker endpoint trả 2xx với payload hợp lệ (`scores[]` hoặc `ranked_ids`)
- **THEN** runtime MUST parse payload và dùng kết quả đó để rerank shortlist

#### Scenario: Reranker timeout/network/non-2xx/invalid payload
- **WHEN** reranker call timeout, network fail, non-2xx, hoặc payload không parse được
- **THEN** runtime MUST set `reranker_failed = true`
- **AND** MUST set `fallback_to_prerank = true`
- **AND** MUST chọn `primary_chunk` từ prerank order
- **AND** MUST tiếp tục Step 10 (non-fatal)

### Requirement: Reranker config phải qua env contract
Reranker integration MUST dùng env config chuẩn để deploy local/remote linh hoạt.

#### Scenario: Reranker env config
- **WHEN** runtime khởi tạo reranker client
- **THEN** runtime MUST đọc tối thiểu `WISMO_RERANKER_ENABLED`, `WISMO_RERANKER_ENDPOINT`, `WISMO_RERANKER_MODEL`, `WISMO_RERANKER_TIMEOUT_MS`

### Requirement: Stitch validator phải qua operation registry và tuân thủ guard
Nếu stitch được bật, Step 9 MUST gọi `OperationKey.RETRIEVAL_STITCH_VALIDATOR` qua gateway và MUST chỉ stitch chunks contiguous cùng source, tối đa 5 chunks.

#### Scenario: Stitch apply with guards
- **WHEN** stitch validator trả quyết định stitch
- **THEN** runtime MUST chỉ stitch chunks cùng `source_document_id`
- **AND** MUST chỉ stitch segment liên tiếp
- **AND** MUST không vượt quá 5 chunks liên tục

#### Scenario: Stitch validator failure fallback
- **WHEN** stitch validator fail
- **THEN** runtime MUST giữ `primary_chunk` không stitch
- **AND** MUST set debug meta `stitch_applied = false`
- **AND** MUST tiếp tục Step 10

### Requirement: Step 9 output phải canonical cho Step 10 TEACH prompt
Step 9 MUST append `retrieval_result` canonical gồm retrieval unit, source metadata, scores/ranks, debug meta, và prompt payload.

#### Scenario: Retrieval result assembly
- **WHEN** Step 9 retrieval thành công
- **THEN** `retrieval_result` MUST có các field tối thiểu: `primary_chunk_id`, `stitched_chunk_ids`, `retrieval_unit_text`, `source_document_id`, `source_title`, `speaker_or_author`, `source_type`, `topic`, `content_type`, `dharma_concepts`, `retrieval_score`, `rerank_score`, `rank_final`, `stitch_span`, `retrieval_debug_meta`, `retrieval_prompt_payload`

### Requirement: Step 9 lỗi không được fail cả turn
Step 9 MUST degrade an toàn khi retrieval/rerank/stitch lỗi và MUST không làm runtime turn fail chỉ vì retrieval stack.

#### Scenario: Retrieval failure non-fatal
- **WHEN** retrieval stack lỗi hoặc không tìm thấy candidate
- **THEN** runtime MUST set `retrieval_result = null` (hoặc retrieval unit rỗng theo policy)
- **AND** MUST append status phù hợp trong `retrieval_debug_meta`
- **AND** MUST đi tiếp Step 10

### Requirement: Step 9 -> Step 10 TEACH handoff phải luôn có prompt-ready payload
Khi Step 9 retrieval thành công, runtime MUST đảm bảo `retrieval_result` chứa đủ dữ liệu để Step 10 TEACH builder assemble prompt (`retrieval_unit_text` hoặc `retrieval_prompt_payload.content_text_for_prompt`).

#### Scenario: Retrieval success handoff
- **WHEN** Step 9 trả `retrieval_result` khác null
- **THEN** payload handoff MUST có text usable cho Step 10 TEACH builder
- **AND** Step 10 MUST có thể assemble prompt không cần query lại DB

### Requirement: Retrieval failure phải tương thích fallback TEACH của Step 10
Khi Step 9 không tìm được retrieval unit usable hoặc degrade về null, runtime MUST giữ output ở trạng thái để Step 10 áp dụng TEACH fallback sang LISTEN một cách deterministic.

#### Scenario: Retrieval null handoff for TEACH fallback
- **WHEN** Step 9 trả `retrieval_result = null` hoặc retrieval text unusable
- **THEN** runtime MUST vẫn tiếp tục flow sang Step 10
- **AND** Step 10 MUST có đủ tín hiệu để fallback TEACH -> LISTEN theo rule 10.7.4

