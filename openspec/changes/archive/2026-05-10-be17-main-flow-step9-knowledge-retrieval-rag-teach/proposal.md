## Why
Step 9 (Knowledge retrieval / RAG TEACH) trong runtime hiện còn stub (`retrieval_result = None`) nên chưa có retrieve pipeline cho TEACH path. Sau BE-16, Step 8 đã chốt `response_method` và `retrieval_required`, vì vậy cần triển khai Step 9 để tạo `retrieval_result` chuẩn cho Step 10 TEACH prompt assembly.

## What Changes
- Implement Step 9 retrieval pipeline cho TEACH-only path:
  - gate điều kiện vào step (`response_method=TEACH`, `retrieval_required=true`, safety cho phép);
  - build `retrieval_query` qua operation `retrieval_query_builder`;
  - convert `retrieval_query` thành vector với ưu tiên qua LLM gateway operation, fallback local embedding client;
  - vector search trên knowledge vector DB (enabled docs/chunks) theo dense cosine;
  - shortlist + rerank (fallback prerank nếu reranker fail/unavailable);
  - primary chunk + optional stitch confirm qua `retrieval_stitch_validator` (fallback no-stitch nếu lỗi);
  - assemble `retrieval_result` + `retrieval_debug_meta` + `retrieval_prompt_payload`.
- Enforce runtime usage rule:
  - Step 9 chỉ đọc `runtime_bundle` + output Step 8;
  - không reload context nền Step 6 từ DB;
  - output Step 9 chỉ append vào runtime state (`retrieval_result`, `retrieval_debug_meta`).
- Failure handling bám MVP:
  - không fail cả turn chỉ vì retrieval/rerank/stitch lỗi;
  - không fail cả turn khi query embedding lỗi;
  - degrade về `retrieval_result = null` và để Step 10 TEACH fallback xử lý.
- Chốt deployment contract cho reranker `bge-reranker-v2-m3`:
  - connector HTTP `POST /rerank` (query + candidates -> scores/ranked ids),
  - env config `WISMO_RERANKER_*`,
  - timeout/network/non-2xx/invalid payload đều fallback prerank non-fatal.
- Scope decision cho BE-17:
  - dùng dense cosine retrieval cho sprint này;
  - không triển khai `sparse/lexical search` và `RRF` trong BE-17.

## Scope
- Trong scope:
  - `runtime/orchestrator.py` Step 9 logic;
  - retrieval service module mới trong `runtime/`;
  - unit tests cho Step 9 path + fallback matrix.
- Ngoài scope:
  - thay đổi Step 10 prompt builder chi tiết;
  - ingestion/chunking pipeline ngoài runtime;
  - tối ưu production infra cho reranker deployment.

## Impact
- Có `retrieval_result` thực tế cho TEACH path thay vì stub.
- Luồng TEACH bám đúng Main Flow/MVP contract với fail-safe không làm rơi cả turn.
- Chuẩn bị nền cho Step 10/11 TEACH quality validations.
