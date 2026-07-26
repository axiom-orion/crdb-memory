# CockroachDB × AWS Hackathon — de-risk spike (2026-07-25)

Deadline **Aug 18 5pm EDT**. Verdict from the 7/13 war room: **GO with reframe** — CRDB-backed
agent memory over MCP, "memory that survives" (node-kill resilience is the demo beat), rebasing
Majordomo's memory/judge patterns (`D:\majordomo\src\majordomo\store.py`) onto CRDB instead of
SQLite. This file is the 6-hour technical de-risk pass — what's proven, what's still blocked on
account creation, and the concrete gotchas found.

## Rules — re-verified live 2026-07-25 (WebFetch, not memory)

- **Must use ≥2 of 4 CockroachDB tools**: Cloud Managed MCP Server, Distributed Vector Indexing,
  ccloud CLI (Agent-Ready), Agent Skills Repo (Open Source). Locked pair from 7/13: **Managed MCP
  Server + Distributed Vector Indexing**.
- **AWS: "at least one AWS service" — much broader than previously assumed.** Bedrock, Lambda,
  ECS/EKS, S3, SageMaker, Bedrock Agents, or "any other AWS service." Bedrock is explicitly
  **optional**, one option among many — direct Anthropic API elsewhere is fine.
- Judging: Agentic Memory Design, Technical Implementation, Real-World Impact, Production
  Readiness, Creativity & Originality.

## Proven today (local Docker, `cockroachdb/cockroach:latest` = v26.2.4, no cloud account needed)

Ran real DDL/DML/query against a live CRDB instance — not guessed from docs:

```sql
CREATE TABLE memories (..., embedding VECTOR(3) NOT NULL, ...);
CREATE VECTOR INDEX idx_memories_embedding ON memories (embedding vector_cosine_ops);
SELECT content, embedding <=> '[0.15,0.88,0.02]' AS distance FROM memories
  ORDER BY embedding <=> '[0.15,0.88,0.02]' LIMIT 3;
```

- **VECTOR column + cosine index syntax works exactly as documented.** Nearest-neighbor ranking
  was semantically correct (tea-preference memories ranked close; shellfish-allergy ranked far).
- **GOTCHA 1 — index build is an async background job** (`SHOW JOBS` — `NEW SCHEMA CHANGE`,
  `CREATE VECTOR INDEX`). Immediately-after-create queries may not see it yet; check job status
  before trusting the index in a demo.
- **GOTCHA 2 — the optimizer won't use the vector index until the table has stats.** On a fresh/
  small table, `EXPLAIN` showed a full scan even after the index build succeeded; `ANALYZE`
  (or auto-stats catching up) made the planner switch to a real `vector search` operator +
  lookup join. In production auto-stats handles this, but a live demo right after a bulk insert
  can hit the same "looks broken, isn't" moment — pre-warm with `ANALYZE` before recording.
- **GOTCHA 3 — combining `ORDER BY embedding <=> ...` with a `WHERE guest_id = ...` filter falls
  back to a full scan.** The vector index is only chosen for pure nearest-neighbor queries with
  no other predicate (tested at 503 rows). For a multi-tenant memory store this matters: either
  (a) accept the full scan at per-guest data volumes small enough not to care, (b) over-fetch top-
  K·factor by vector distance across the whole table then filter by guest_id in application code,
  or (c) look into CRDB partial/expression indexes scoped per-tenant. **Decide which before
  building the real engine — don't discover this live.**
- No Drizzle: confirmed no CRDB dialect exists — plan stands to hand-write raw SQL over
  `node-postgres` (or `psycopg`/`asyncpg` if the engine stays Python like Majordomo).

## Still blocked on account creation (Ryan)

Two of the four locked-in requirements are CockroachDB **Cloud** product features — not
replicable locally, no way around this:

- **CockroachDB Cloud account** — needed for: the Managed MCP Server (config snippet is
  generated from the Cloud Console, per Cockroach Labs' own blog — there is no local
  equivalent), and to run Distributed Vector Indexing on an actual distributed (not
  single-node-Docker) cluster for full credit. Sign up at cockroachlabs.cloud — a free/serverless
  tier is expected to exist (standard for CRDB Cloud) but rules page didn't confirm; verify at
  signup.
- **AWS account** — needed for literally any of the eligible services. No existing AWS
  credentials or CLI found on this machine (checked `~/.aws/credentials`, `aws --version`) —
  this is a from-scratch signup, unlike the Vercel/Firebase/GCP stack the rest of BAI/Vorion runs
  on.
- **Bedrock model-access FTU form** — optional per the rules (direct Anthropic API is
  compliant), so **not on the critical path**. Skip unless the demo specifically wants a Bedrock-
  branded model call for tool-credit optics.

## Recommendation / next steps

1. **Ryan**: create CockroachDB Cloud account + a serverless cluster; create AWS account. Both
   are prerequisites for the parts of this spike that can't be de-risked further locally.
2. Once the CRDB Cloud cluster exists: regenerate the Managed MCP Server config snippet, smoke-
   test one tool call through it, and re-run today's vector queries against the real cluster
   (confirm the async-index and stats gotchas behave the same on Cloud as on local Docker).
3. Decide the per-tenant filter strategy (gotcha 3) before writing the real engine — this is an
   architecture call, not a code fix.
4. AWS: given "any service" qualifies, the lowest-friction path is likely **S3** (store
   transcripts/session snapshots) or **Lambda** (host the MCP server or agent endpoint) —
   decide based on where the real deployment target ends up; a bare hello-world Lambda is
   ready to go the moment credentials exist (ask for it — not built yet, since there's nothing
   to deploy without an account).

Reuse boundary: `store.py`'s provenance model (reinforcements, supersede-not-delete, source
session) ports directly to CRDB — same columns, `VECTOR` instead of JSON-text embeddings, `<=>`
instead of Python-side cosine math. The recall query logic (dedupe/reinforce/contradiction-
supersede) is LLM-judged the same way regardless of storage backend.
