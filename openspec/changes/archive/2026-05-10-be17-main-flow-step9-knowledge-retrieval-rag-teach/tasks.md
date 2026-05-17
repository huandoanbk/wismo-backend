## 1. Step 9 runtime gate and state wiring
- [x] 1.1 Thay stub `_knowledge_retrieval` bằng Step 9 gate logic theo `response_method/retrieval_required/final_safety_state`.
- [x] 1.2 Đảm bảo Step 9 chỉ đọc runtime state hiện có, không reload context nền Step 6 từ DB.
- [x] 1.3 Bổ sung state outputs chuẩn Step 9: `retrieval_result`, `retrieval_debug_meta`.

## 2. Retrieval query builder integration
- [x] 2.1 Implement call `OperationKey.RETRIEVAL_QUERY_BUILDER` qua `LLMGateway`.
- [x] 2.2 Chuẩn hóa parse output retrieval query và fallback query khi parse/gateway lỗi.
- [x] 2.3 Ghi debug meta cho query builder (`retrieval_query`, error/fallback flags).

## 3. Vector retrieval and ranking
- [x] 3.0 Implement query embedding dual-path: gateway-first (`retrieval_query_embedding`) then local fallback client.
- [x] 3.1 Implement vector candidate fetch từ knowledge vector DB (enabled docs/chunks only).
- [x] 3.2 Implement shortlist + deterministic dense-only prerank path cho candidate ranking.
- [x] 3.3 Implement reranker hook + fallback prerank khi reranker unavailable/fail.
- [x] 3.4 Implement `RerankerClient` HTTP contract (`POST /rerank`, query+candidates, scores/ranked_ids parse) + env config (`WISMO_RERANKER_*`).
- [x] 3.5 Ghi rõ debug metadata cho dense-only retrieval path trong BE-17.

## 4. Stitch confirm and retrieval unit assembly
- [x] 4.1 Implement stitch validator call qua `OperationKey.RETRIEVAL_STITCH_VALIDATOR`.
- [x] 4.2 Enforce stitch guards (same source, contiguous segment, max 5 chunks).
- [x] 4.3 Assemble `retrieval_result`, `retrieval_debug_meta`, `retrieval_prompt_payload` đúng contract Step 9.

## 5. Failure handling and fallbacks
- [x] 5.1 Đảm bảo retrieval/rerank/stitch lỗi không làm fail turn runtime.
- [x] 5.0 Đảm bảo embedding gateway fail -> local fallback; cả hai fail vẫn non-fatal và đi tiếp Step 10.
- [x] 5.2 Đảm bảo empty retrieval trả `retrieval_result = null` và vẫn đi Step 10.
- [x] 5.3 Đảm bảo TEACH path với retrieval lỗi vẫn để Step 10 fallback xử lý.
- [x] 5.4 Đảm bảo reranker timeout/network/non-2xx/invalid payload đều fallback prerank non-fatal.

## 6. Tests and verification
- [x] 6.1 Thêm unit tests cho Step 9 gate + skip/run behavior.
- [x] 6.2 Thêm unit tests cho query builder fallback + embedding dual-path fallback + vector retrieval assembly.
- [x] 6.3 Thêm unit tests cho reranker/stitch fallback matrix + reranker HTTP response parsing.
- [x] 6.4 Chạy regression tests runtime/orchestrator + llm gateway + Step 8/9 interaction.
