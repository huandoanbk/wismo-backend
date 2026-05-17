## Overview
BE-17 triển khai Step 9 như retrieval orchestrator cho TEACH mode, chạy sau Step 8 và trước Step 10. Trọng tâm là correctness contract + safe degradation, không làm gián đoạn turn khi retrieval stack có lỗi.

## Entry Gate
Step 9 chỉ chạy retrieval khi:
- `response_method == TEACH`
- `retrieval_required == true`
- `final_safety_state == normal`

Nếu không đạt điều kiện:
- set `retrieval_result = None`
- set `retrieval_debug_meta.retrieval_status = skipped`
- đi tiếp Step 10

## Input Sources (No context DB reload)
Step 9 chỉ dùng runtime state hiện có:
- từ Step 6: `current_message`, `context_summary`
- từ Step 8: `normalized_reasoning_result`, `response_method`, `retrieval_required`, `final_safety_state`

Không query lại profile/memory/recent turns để rebuild context nền.

## Retrieval Pipeline
1. Build `retrieval_query`
- gọi `LLMGateway.complete(operation_key=OperationKey.RETRIEVAL_QUERY_BUILDER, ...)`
- input: `current_message`, `context_summary`, selected fields từ `normalized_reasoning_result`
- parse query text (fallback query từ `current_message` nếu parse fail)

2. Vector candidate fetch (vector DB only)
- Query embedding strategy:
  - ưu tiên gọi `LLMGateway.complete(operation_key=OperationKey.RETRIEVAL_QUERY_EMBEDDING, ...)`
  - nếu operation/gateway parse/config/provider fail thì fallback `EmbeddingClient` local/remote endpoint
  - nếu cả hai fail: kết thúc Step 9 với `retrieval_result=None`, `retrieval_status=embedding_failed`, đi tiếp Step 10
- query `knowledge.ContentChunk` + `ChunkEmbedding` + `SourceDocument` với filter enabled
- dùng pgvector cosine distance cho dense ranking
- tạo prerank shortlist theo dense-only deterministic ordering

3. Rerank + primary selection
- cố gắng rerank shortlist (service hook; initial implementation có thể dùng prerank fallback nếu reranker unavailable)
- chọn top-1 làm `primary_chunk`
- set debug flags: `reranker_used`, `reranker_failed`, `fallback_to_prerank`

4. Stitch confirm (optional)
- gọi operation `retrieval_stitch_validator` để quyết định `KEEP|STITCH_PREV|STITCH_NEXT|STITCH_BOTH`
- chỉ stitch contiguous chunks trong cùng `source_document_id`, max 5 chunks
- lỗi stitch llm => fallback giữ primary chunk, set debug flags

5. Output assembly
- `retrieval_result` canonical fields:
  - `primary_chunk_id`, `stitched_chunk_ids`, `retrieval_unit_text`
  - source metadata (`source_document_id`, `source_title`, `speaker_or_author`, `source_type`, `topic`, `content_type`, `dharma_concepts`)
  - scores/rank (`retrieval_score`, `rerank_score`, `rank_final`, `stitch_span`)
  - `retrieval_debug_meta`
  - `retrieval_prompt_payload`

## Failure Policy
- Query builder fail => fallback query text tối thiểu, tiếp tục retrieval.
- Embedding gateway fail => fallback local embedding client.
- Embedding cả gateway và local đều fail => `retrieval_result=None`, tiếp tục Step 10.
- Vector search fail/empty => `retrieval_result=None`, `retrieval_status=empty_or_failed`, tiếp tục Step 10.
- Reranker fail => fallback prerank top-1, tiếp tục.
- Stitch validator fail => no-stitch primary chunk, tiếp tục.
- Không throw lỗi làm fail turn chỉ vì Step 9 nội bộ.

## Services and Boundaries
- Thêm `runtime/retrieval.py`:
  - `KnowledgeRetrievalService` cho vector fetch/rerank/stitch/output assembly.
- Thêm `runtime/embedding.py`:
  - `EmbeddingService` với dual-path: gateway-first, local fallback.
- Thêm `runtime/reranker.py`:
  - `RerankerClient` gọi HTTP service external/internal cho model `bge-reranker-v2-m3`.
- `RuntimeOrchestrator._knowledge_retrieval()` gọi service và ghi vào state.
- Step 9 không gọi provider trực tiếp cho LLM operations; query-builder/stitch-validator/query-embedding (gateway path) đều qua `LLMGateway`.

## Reranker Deployment Contract
Backend connect tới reranker service qua HTTP API.

### Environment variables
- `WISMO_RERANKER_ENABLED=true|false`
- `WISMO_RERANKER_ENDPOINT=http(s)://<host>:<port>/rerank`
- `WISMO_RERANKER_MODEL=bge-reranker-v2-m3`
- `WISMO_RERANKER_TIMEOUT_MS=2000` (default)

### Request/response contract
- Request (`POST /rerank`):
  - `query: string`
  - `candidates: list[{chunk_id: string, text: string}]`
  - `model: string` (optional; default từ env)
- Response:
  - `scores: list[{chunk_id: string, score: number}]` hoặc
  - `ranked_ids: list[string]`

### Timeout/error behavior
- Timeout, network error, invalid payload, non-2xx:
  - set `reranker_failed = true`
  - `fallback_to_prerank = true`
  - chọn top-1 từ prerank order
  - tiếp tục Step 10 (non-fatal)

## Ollama Note
- Nếu deploy reranker qua Ollama, runtime vẫn connect qua `RerankerClient` adapter riêng.
- `LLMGateway` chỉ dùng cho operations dạng prompt/messages (`retrieval_query_builder`, `retrieval_stitch_validator`, và gateway-path query embedding), không dùng cho reranker scoring API.


## Testing
- Unit tests cho gate conditions (skip vs run)
- Query builder parsing/fallback tests
- Dense retrieval success + metadata assembly tests
- Reranker fail fallback tests
- Stitch validator fail fallback tests
- Retrieval empty/failure không làm fail turn tests
