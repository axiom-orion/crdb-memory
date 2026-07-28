# crdb-memory — Devpost submission copy

Paste-ready. Each `##` maps to a field on the Devpost form.
**Draft-save the form the moment you open it, then edit forever.**
Narration and on-screen beats live in `VIDEO-SCRIPT.md` — this copy is written to match it.

---

## Project name

crdb-memory — memory that survives

## Elevator pitch (one line, ~200 char limit)

Governed, append-only agent memory on CockroachDB with an AWS S3 backstop. A node can die mid-conversation and cost you an uncommitted insert — never corrupted history.

---

## About the project

### Inspiration

Every agent framework claims persistent memory. Almost none of them say what happens to that
memory when the node holding it goes down mid-conversation.

The two common designs both have a failure I didn't want. A naive append log degrades: stale
facts and near-duplicates pile up until recall quality collapses. An UPDATE-based store fixes
that by mutating rows in place — and quietly loses history the moment a write is interrupted.

So the constraint came first: **nothing is ever UPDATEd and nothing is ever DELETEd.** Then
the question became whether a real memory-governance loop — dedupe, contradiction detection,
supersession — can be built under that constraint. It can, and it turns out to be a better
fit for a distributed database than the mutable version ever was.

### What it does

A hotel concierge agent remembers guest preferences across stays — "prefers window seating,"
"allergic to shellfish" — and has to not re-ask what it already knows, recognise when a new
statement contradicts an old one, and keep working through a node failure.

- **`store.py`** — append-only. Reinforcing a memory and superseding it are the same
  operation underneath (`evolve()`): INSERT a new row whose `supersedes` column points at the
  row it replaces. A memory is "active" if it is the tip of its lineage chain — the row
  nothing else points at. `retire()` writes tombstones, which handles fan-in (one new memory
  contradicting several old ones) without an array column.
- **`engine.py`** — the governance loop: extract candidates from a transcript, dedupe by
  embedding similarity, run an LLM contradiction check in the gray zone, then
  reinforce / supersede / store. Recall scores by
  `cosine similarity × recency decay × importance × reinforcement boost`.
- **`llm.py`** — Claude (`claude-opus-5`) for extraction and contradiction judging via
  structured outputs; Gemini (`gemini-embedding-001`) for embeddings. A deterministic
  `MockClient` runs the entire pipeline offline with zero API keys.
- **`archive.py`** — exports the full lineage, tombstones included, to S3 as JSONL. Replayable
  into a fresh cluster if the cluster itself were lost, not just a node inside it.

On a live run against the real cloud cluster, Claude extracted three clean standalone facts
from a three-statement transcript, and a "dietary restrictions" query ranked the shellfish
allergy first at **0.89**, ahead of the anniversary and seating memories at 0.58 and 0.53 —
semantic ranking, not keyword match.

### How I built it

Python with a direct `psycopg` connection to CockroachDB Cloud (cluster `tinted-guppy`, AWS
`us-east-1`) for all memory CRUD.

That was a deliberate architecture call. The Managed MCP Server is OAuth / human-session
gated — the Console's MCP client picker lists interactive coding assistants and offers no
service-account option — so it is genuinely excellent as a **development and operations**
surface and genuinely wrong as a runtime dependency for an unattended agent. It was used
throughout the build to inspect schema, run queries, and manage the cluster from Claude Code;
the production data path does not call it. Claiming otherwise would have been the easy
submission and the dishonest one.

### Challenges I ran into

**The vector index existed in the schema and nothing queried it.** I caught this while
writing the README, not while writing the code: `remember()` and `recall()` were both
fetching every active memory with a plain SELECT and computing cosine similarity in Python.
The `VECTOR(1024)` column and its `vector_cosine_ops` index were real, and entirely
decorative. Fixed by adding `store.nearest()` — an actual
`ORDER BY embedding <=> query LIMIT k` — and switching both call sites to it.

**A bug that only a resilience test could surface.** `store.evolve()` referenced `guest_id`
without taking it as a parameter. The earlier end-to-end cloud test never triggered it,
because that run never hit a dedupe-or-reinforce match. The node-kill demo did, immediately.

**Infrastructure contention looked exactly like a distributed-systems bug.** Running another
hackathon's six-container stack concurrently caused genuine CockroachDB node crashes and a
real quorum-loss error mid-test. Nothing was wrong with the code. Worth stating plainly
because the debugging instinct — "my quorum logic is broken" — was wrong for about an hour.

### Accomplishments I'm proud of

**The node-kill demo does what it says.** Three-node cluster, conversation in progress, kill a
node, then *wait for CockroachDB's liveness record to actually expire* — about 12 seconds — so
the status table can honestly show `is_live: false` before the next write. An earlier cut
checked status too fast and the node still showed live; the honest version is slower and is
the one that shipped. New memory writes and recalls correctly on the surviving two-of-three
quorum, the node rejoins, and the full lineage is intact.

**Honest about the query plan.** At the row counts a live demo runs at, CockroachDB's
cost-based optimizer may choose a full scan over the vector index. That is `EXPLAIN`-verified
and documented CockroachDB behaviour — `ANALYZE` after real data volume is what flips it — and
the results are correct either way; only the physical plan changes. The submission says so
rather than hiding it, because a judge running `EXPLAIN` will find it in thirty seconds.

**Every layer proven on real infrastructure**, not mocks: real Claude, real Gemini, real
CockroachDB Cloud, real S3 round-trip matching row counts, real node kill.

### What I learned

**Append-only is not a limitation you work around for a distributed store — it is the design
that fits it.** The original mutable version had to reason about what a half-applied UPDATE
means across nodes. This one cannot have that failure, structurally. The constraint made the
resilience story simpler to build *and* simpler to prove.

**Write the README before you believe the code works.** The dead vector index survived a full
end-to-end verification run against a live cluster. What caught it was having to write down,
in plain sentences, what each component did.

### What's next

Per-tenant filter strategy is the open architecture question: `ORDER BY embedding <=> ...`
combined with a `WHERE guest_id = ...` filter falls back to a full scan (tested at 503 rows),
while pure nearest-neighbour queries use the index. Partitioned indexes or a per-tenant table
strategy is the real answer at scale, and it is a decision to make deliberately rather than
patch later.

---

## Built with

`python` · `cockroachdb` · `psycopg` · `aws-s3` · `boto3` · `anthropic` · `claude` · `gemini` · `docker` · `apache-2.0`

## Try it out

- **Repo:** _(GitHub URL — Apache-2.0, top-level LICENSE present)_
- **Judge access:** must stay reachable through **Sep 15** (caps + billing alarms set)

---

## Hackathon-required fields

| Requirement | How it's met |
|---|---|
| **CockroachDB tool #1** | **Cloud Managed MCP Server** — schema inspection, queries, cluster management from Claude Code throughout the build |
| **CockroachDB tool #2** | **Distributed Vector Indexing** — `guest_memories.embedding VECTOR(1024)` + `vector_cosine_ops` index; `store.nearest()` issues a real `ORDER BY embedding <=> query LIMIT k`, used by both `recall()` and dedupe |
| **AWS service (≥1)** | **S3** — `archive.py` exports full lineage as JSONL; verified round-trip, row counts match |
| **Public repo** | Apache-2.0, LICENSE at top level |
| **Demo video** | Under 3:00, public — script in `VIDEO-SCRIPT.md` |

### Code reuse disclosure (required — state it in the form, not just the README)

The append-only storage engine, the CockroachDB schema, the Claude + Gemini integration, the
S3 archive/restore path, and the node-kill demo were all written for this submission.

The **governance algorithm** in `engine.py` — the dedupe/contradiction control flow and the
recall scoring formula — is adapted from a pre-existing personal project (`majordomo`, a
SQLite + Qwen concierge memory agent, never published publicly). The algorithm carries over;
every line implementing it here was rewritten for CockroachDB's append-only constraints (the
original used in-place `UPDATE`, which this project deliberately does not) and for the
Claude/Gemini backend.

---

## Pre-submission checklist

- [ ] **⚠️ COMMIT THE REPO.** Only `a910758` (the spike) is in git history. `src/`, `scripts/`,
      `README.md`, `LICENSE`, `pyproject.toml`, `VIDEO-SCRIPT.md` are all **untracked** —
      the entire engine is one `git clean` from gone, and the hackathon requires a public repo
      with a top-level LICENSE
- [ ] Create the GitHub repo and push public (**needs your approval — push gate**)
- [ ] Devpost form **draft-saved** (do this first, empty if necessary)
- [ ] Video recorded on a **clean Docker session** — DataHub's stack stopped, cluster settled a
      minute before recording
- [ ] Use a **fresh `guest_id`** for the take, not `live-test-guest-1` (already has data; would
      hit the dedupe path instead of a clean first-time store)
- [ ] Read whatever relevance scores the terminal actually shows — don't force a match to 0.89
- [ ] All three mandatory-tech names said out loud and shown on screen
- [ ] Judge URL live through **Sep 15**, caps + alarms set
- [ ] Submitted well before **Aug 18, 5:00 PM EDT** — target Sun Aug 17
