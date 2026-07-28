# Video script — "Memory that survives"

CockroachDB × AWS Agentic Memory Challenge. Target runtime: **2:40–2:50** (hard ceiling 3:00 —
3:05 is a disqualifying violation per the rules, leave margin). 60/40 explain/demo split.
Mandatory tech must be **named on screen**, not just implied: CockroachDB Managed MCP Server,
Distributed Vector Indexing, AWS S3.

Record terminal segments in a **clean Docker session** — no DataHub or other heavy containers
running (see `SPIKE.md`'s flakiness note; unrelated resource contention crashed nodes during dev
testing, and a live take doesn't get a retry). Run `scripts/local_cluster.sh up` and let it settle
for a minute before hitting record.

Columns: **Time** (target timestamp) · **On screen / do** (exact action) · **Line** (narration,
read at a normal pace — timed to roughly match a relaxed reading speed for the segment length).

---

## 0:00–0:20 — Hook + pitch (Real-World Impact, Agentic Memory Design)

| Time | On screen / do | Line |
|---|---|---|
| 0:00 | Cold open on the CockroachDB Cloud console, `tinted-guppy` cluster overview page. | "Agent memory has a trust problem. Every framework claims persistence — but what happens to that memory when the node holding it goes down mid-conversation?" |
| 0:10 | Cut to the `README.md` architecture diagram (rendered, e.g. GitHub preview or a rendered mermaid image). | "This is crdb-memory — governed, append-only agent memory on CockroachDB, with an AWS S3 durability backstop. Built so a node failure can cost an uncommitted write. Never corrupted history." |

## 0:20–0:50 — Architecture (Technical Implementation)

| Time | On screen / do | Line |
|---|---|---|
| 0:20 | Screen: `README.md` architecture section, scroll to the mermaid diagram. | "Claude extracts and judges candidate memories from a conversation. Gemini embeds them. Everything lands in CockroachDB — never an UPDATE, never a DELETE. Reinforcing a memory and superseding it are the same operation underneath: insert the next link in a lineage chain." |
| 0:35 | Cut to `store.py` in an editor, `evolve()` method highlighted (lines ~54–69). | "A killed node can only ever cost an uncommitted insert. It can never corrupt what's already there — because nothing is ever mutated in place." |
| 0:45 | Cut to CockroachDB Cloud console, `tinted-guppy` → SQL Users / Connect modal, **Model Context Protocol tab visible**. | "This whole engine was built and operated through CockroachDB's Managed MCP Server — schema, queries, cluster management, straight from an AI coding assistant." |

## 0:50–1:35 — Live demo with real models (Agentic Memory Design)

| Time | On screen / do | Line |
|---|---|---|
| 0:50 | Terminal, `.venv` active, run the live remember/recall test (pre-stage the script; see note below). | "Let's see it live — real Claude, real Gemini, real cluster. A guest mentions a window-seat preference, a shellfish allergy, and an upcoming anniversary." |
| 1:00 | Show `remember()` output on screen (the three extracted memories). | "Claude doesn't just log the transcript — it extracts three clean, standalone facts." |
| 1:10 | Show `recall()` output, highlight the top result + score. | "Now ask: what are this guest's dietary restrictions? The shellfish allergy comes back first — 0.89 relevance — well ahead of the seating and anniversary memories at 0.53 and 0.58. That's Gemini's embeddings and CockroachDB's **Distributed Vector Indexing** doing real semantic ranking, not keyword match." |
| 1:25 | Quick cut: `EXPLAIN` output or the vector index in `SHOW CREATE TABLE`, on screen for ~5s. | "The query runs a real nearest-neighbor search against that index — `embedding <=> query` — not a Python loop over every memory." |

## 1:35–2:20 — Node-kill demo (Production Readiness, the differentiator)

| Time | On screen / do | Line |
|---|---|---|
| 1:35 | Terminal, run `python scripts/node_kill_demo.py`. Let the "all 3 nodes live" + first remember/recall play. | "Here's the actual test: three-node CockroachDB cluster, a real conversation in progress." |
| 1:45 | **Cut/speed up** the `docker stop roach2` + ~12s liveness-wait segment (editing — don't make viewers watch a real-time countdown). | "We kill a node — mid-conversation — the same way a real outage would." |
| 1:55 | Show the node status table on screen: node 2, `is_available: false`, `is_live: false`. Hold for 3–4s. | "Confirmed dead. Not stopped-and-still-answering — actually down." |
| 2:05 | Show the guest writing a new memory + recall still succeeding, on screen. | "The guest keeps talking. A new memory writes and recalls correctly — on the surviving two-of-three quorum. No error, no retry logic the viewer has to trust — it just works." |
| 2:15 | Show the final full-history output — all memories intact, lineage chain visible via `supersedes`. | "Node comes back. Full history, nothing lost, nothing corrupted." |

## 2:20–2:45 — AWS + close (Real-World Impact, Creativity & Originality)

| Time | On screen / do | Line |
|---|---|---|
| 2:20 | Terminal: run `archive.export_snapshot()` (or show pre-run output) + cut to the AWS S3 console showing the bucket and the `.jsonl` object. | "One more layer: the entire memory ledger — every guest, every version, on **AWS S3** as a durability backstop. If the cluster itself were ever lost — not just a node — the whole history replays into a fresh one." |
| 2:35 | Cut back to the architecture diagram, final wide shot. | "Memory that survives a node. Survives the cluster. And never once has to lie about what it forgot." |
| 2:42 | Title card: project name, GitHub link, "CockroachDB × AWS Agentic Memory Challenge." | (silent / music only) |

---

## Production notes

- **Pre-stage the live-model demo.** `remember()`/`recall()` against real Claude+Gemini take real
  wall-clock time (LLM round trips). Either run it once before recording and screen-capture the
  real output, or run it live and cut dead air in editing — don't narrate over a spinner.
- **The node-kill demo's ~12s liveness wait is real and necessary for the honest "confirmed dead"
  beat** (an earlier cut checked status too fast and it still showed live — see `SPIKE.md`) — cut
  or speed-ramp that wait in editing, don't skip the status check itself.
- **Have a completely idle Docker session before recording** — no DataHub or other multi-container
  stacks running. Confirmed cause of node crashes during dev testing; a live take doesn't get a
  retry mid-record.
- **Name every mandatory-tech element out loud, on screen, once, unambiguously**: "CockroachDB
  Managed MCP Server," "Distributed Vector Indexing," "AWS S3." Judges score against a checklist —
  don't make them infer it from a diagram.
- **No third-party trademarks beyond the sponsor tech being disclosed** (Claude, Gemini, CockroachDB,
  AWS are the point of the entry, not a violation) — don't show unrelated branded content in any
  B-roll.
- **Timing checkpoint**: read through once at natural pace with a stopwatch before final recording.
  If it's running past 2:50, cut from the AWS/close section first (2:20–2:45) — the node-kill demo
  is the strongest beat and shouldn't be the one that gets trimmed.
- **The 0.89/0.58/0.53 scores are real, from one actual live run** (`live-test-guest-1`, this
  session) — not invented for the script. Claude's extraction and Gemini's embeddings aren't
  guaranteed byte-identical on a fresh call, so a new take may score slightly differently (e.g.
  0.87 instead of 0.89). **Read whatever number the terminal actually shows during the real
  recording, not the numbers printed here** — if it drifts, that's fine, don't force a match.
- **Use a fresh `guest_id` for the recorded take** (not `live-test-guest-1` — that guest already
  has real data sitting in `crdbmemory` from this session's testing). Re-running the same content
  against an existing guest hits the dedupe/reinforce path instead of a clean first-time `stored`
  result, which looks different on screen than what this script describes.
