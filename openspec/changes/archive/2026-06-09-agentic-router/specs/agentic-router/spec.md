## ADDED Requirements

### Requirement: Router executes only after intent cache miss
The system SHALL execute Agentic Router only after guardrails have accepted the request and intent cache does not match a configured intent.

#### Scenario: Intent cache hit skips Router
- **WHEN** a user query matches an existing intent cache entry
- **THEN** the system MUST return the intent answer without executing Agentic Router

#### Scenario: Intent cache miss invokes Router
- **WHEN** a user query passes guardrails and does not match intent cache
- **THEN** the system MUST evaluate the query with Agentic Router before entering the fixed RAG flow

### Requirement: Router preserves existing RAG as default path
The system SHALL preserve the existing RAG flow as the default route for support knowledge questions and uncertain Router results.

#### Scenario: Knowledge question routes to RAG
- **WHEN** the user asks a product, policy, price, troubleshooting, configuration, or knowledge-base question
- **THEN** Agentic Router MUST choose `rag_search` and enter the existing RAG flow

#### Scenario: Low confidence falls back to RAG
- **WHEN** Agentic Router confidence is below the implementation threshold
- **THEN** the system MUST choose `rag_search` with `fallback_to_rag=true`

#### Scenario: Router error falls back to RAG
- **WHEN** Agentic Router parsing fails or raises an exception
- **THEN** the system MUST choose `rag_search` and continue serving the answer through the existing RAG flow

### Requirement: Router provides four tool routes
The system SHALL expose exactly four planned Router routes for the lightweight Agentic Router: `rag_search`, `direct_response`, `clarify`, and `human_handoff`.

#### Scenario: Greeting uses direct response
- **WHEN** the user sends a greeting or simple capability question that does not require knowledge-base evidence
- **THEN** Agentic Router MUST choose `direct_response`, return `PASS`, and return no citations

#### Scenario: Missing critical information uses clarify
- **WHEN** the user asks a question that lacks required conditions and cannot be safely answered
- **THEN** Agentic Router MUST choose `clarify`, return `ASK_USER`, and include one to three follow-up questions

#### Scenario: Execution or sensitive account request uses handoff
- **WHEN** the user asks for account, billing, security, deletion, refund execution, order modification, or other human-only actions
- **THEN** Agentic Router MUST choose `human_handoff` and return `ESCALATE`

### Requirement: Router output is structured and auditable
The system SHALL represent Router decisions with a structured internal output containing route, tool, reason, confidence, optional query rewrite, clarifying questions, risk flags, and fallback status.

#### Scenario: Router returns complete decision object
- **WHEN** Agentic Router evaluates a request
- **THEN** the Router output MUST include `route`, `tool`, `reason`, `confidence`, `clarifying_questions`, `risk_flags`, and `fallback_to_rag`

#### Scenario: Clarify includes questions
- **WHEN** Agentic Router chooses `clarify`
- **THEN** the Router output MUST include user-facing `clarifying_questions`

### Requirement: External API shape remains stable
The system SHALL keep the existing top-level API response fields unchanged and only add optional Agentic Router metadata under `debug`.

#### Scenario: RAG route preserves citations
- **WHEN** Agentic Router chooses `rag_search`
- **THEN** the final API response MUST preserve existing `answer`, `decision`, `followup_questions`, `citations`, `confidence`, and `debug` behavior

#### Scenario: Router debug is optional
- **WHEN** Router metadata is available
- **THEN** the system MAY include `debug.agentic_router` without requiring clients to change their top-level response parsing

### Requirement: Router remains separate from evidence decision router
The system SHALL keep Agentic Router separate from the existing post-retrieval `app/services/decision_router.py` evidence decision behavior.

#### Scenario: Pre-RAG and post-retrieval decisions are not mixed
- **WHEN** a request enters the RAG path
- **THEN** Agentic Router MUST be treated as a pre-RAG tool selector and `decision_router.py` MUST remain the post-retrieval evidence decision component

### Requirement: Entrypoints use consistent Router policy
The system SHALL apply the same planned Router policy across `/reply/generate`, synchronous conversation, and streaming conversation entrypoints.

#### Scenario: Same question across entrypoints
- **WHEN** the same user query is sent through reply, synchronous conversation, and streaming conversation entrypoints
- **THEN** Agentic Router MUST choose the same route category for each entrypoint
