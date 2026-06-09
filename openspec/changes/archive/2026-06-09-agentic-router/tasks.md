## 1. Router Contract

- [x] 1.1 Define Agentic Router input model with `query`, `conversation_history`, `source`, and optional `trace_id`.
- [x] 1.2 Define Agentic Router output model with `route`, `tool`, `reason`, `confidence`, optional `query_for_tool`, `clarifying_questions`, `risk_flags`, and `fallback_to_rag`.
- [x] 1.3 Define the four supported route values: `rag_search`, `direct_response`, `clarify`, and `human_handoff`.
- [x] 1.4 Add unit tests for Router output validation and invalid route handling.

## 2. Router Decision Logic

- [x] 2.1 Implement `rag_search` as the default route for support knowledge questions.
- [x] 2.2 Implement `direct_response` classification for greetings, capability questions, and simple interactions that do not require knowledge-base evidence.
- [x] 2.3 Implement `clarify` classification for questions missing critical conditions, including one to three follow-up questions.
- [x] 2.4 Implement `human_handoff` classification for account, billing, security, deletion, refund execution, order modification, and other human-only actions.
- [x] 2.5 Add low-confidence handling that sets `fallback_to_rag=true` and routes to `rag_search`.
- [x] 2.6 Add exception handling that routes to `rag_search` without breaking the current answer flow.

## 3. RAG Entrypoint Integration

- [x] 3.1 Locate the shared point after guardrails and intent cache miss for `/reply/generate`, synchronous conversation, and streaming conversation entrypoints.
- [x] 3.2 Ensure intent cache hits skip Agentic Router and return existing intent answers unchanged.
- [x] 3.3 Call Agentic Router only on intent cache miss and before the fixed RAG flow.
- [x] 3.4 Preserve the existing RAG flow for `rag_search`: `query extract -> retrieve -> assess evidence -> retry -> generate -> verify`.
- [x] 3.5 Keep Agentic Router separate from `app/services/decision_router.py`, which remains the post-retrieval evidence decision component.

## 4. Response Mapping

- [x] 4.1 Map `rag_search` results to the existing RAG response shape with citations preserved.
- [x] 4.2 Map `direct_response` to `decision=PASS` with no citations.
- [x] 4.3 Map `clarify` to `decision=ASK_USER` with follow-up questions.
- [x] 4.4 Map `human_handoff` to `decision=ESCALATE`.
- [x] 4.5 Add optional `debug.agentic_router` metadata without changing top-level API fields.
- [x] 4.6 Add debug metadata for intent cache hit skip and Router fallback-to-RAG cases.

## 5. Verification

- [x] 5.1 Add tests proving configured intent hits skip Router.
- [x] 5.2 Add tests proving ordinary knowledge-base questions choose `rag_search` and preserve citations.
- [x] 5.3 Add tests proving greetings and capability questions choose `direct_response` without retrieval or citations.
- [x] 5.4 Add tests proving missing key conditions choose `clarify` and return `ASK_USER`.
- [x] 5.5 Add tests proving account, billing, security, deletion, refund execution, and order modification requests choose `human_handoff` and return `ESCALATE`.
- [x] 5.6 Add tests proving prompt injection inputs are still intercepted by existing guardrails before Router.
- [x] 5.7 Add tests proving low-confidence and Router exception paths fall back to `rag_search`.
- [x] 5.8 Add tests proving `/reply/generate`, synchronous conversation, and streaming conversation entrypoints use consistent Router policy.

## 6. Documentation Sync

- [x] 6.1 Update `.agent-harness/02_RAG_FLOW.md` only when the Router is actually wired into the RAG query chain.
- [x] 6.2 Keep `.agent-harness/spec/Agentic Router.md` aligned with final implementation decisions if behavior changes during build.
- [x] 6.3 Record any reproducible implementation failure or rollback lesson in `.agent-harness/07_FAILURE_MEMORY.md`.
