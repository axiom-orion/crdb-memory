"""The governed memory engine, ported onto CockroachDB's append-only store.

Naive memory agents append everything and retrieve by similarity; over
sessions the store fills with duplicates and stale, contradicted facts, and
recall quality *degrades* with experience. This governs the lifecycle:

  remember():
    1. EXTRACT   candidate memories from the conversation (LLM, JSON mode)
    2. DEDUPE    embedding similarity >= DEDUPE_T -> evolve as a reinforcement
    3. SUPERSEDE similarity in the gray zone -> LLM contradiction check;
                 contradicting old memories are retired (kept for audit,
                 excluded from recall) with the reason recorded
    4. STORE     with importance, provenance (session, timestamps)

  recall():
    hybrid score = cosine(query, memory)
                 * importance weighting
                 * recency decay
                 * reinforcement boost
    -> the memories that are relevant, current, and repeatedly confirmed.

Everything above is INSERT-only against CockroachDB: reinforce and supersede
are both `store.evolve()`, and a fan-in contradiction (one new memory
retiring several old ones) uses `store.retire()` for the extras. No row is
ever UPDATEd or DELETEd, so a node killed mid-write can only lose an
uncommitted insert — never corrupt existing memory.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from crdbmemory.llm import cosine, get_client
from crdbmemory.store import MemoryStore

DEDUPE_T = 0.90        # >= this: same fact, reinforce
# >= this (and < DEDUPE_T): same topic, run the LLM contradiction check.
# Deliberately broad — it is only a prefilter; the verdict is the LLM's.
CONTRADICTION_T = 0.22
HALF_LIFE_DAYS = 90.0

EXTRACT_SYSTEM = """[extract] You extract durable guest memories from a hotel
conversation transcript. Return JSON: {"memories": [{"content": str,
"kind": "preference"|"fact"|"incident"|"policy_learning", "importance": 1-5}]}.
Only extract things worth remembering across future stays: preferences,
allergies, recurring requests, complaints, corrections, learned procedures.
Write each content as a short standalone third-person statement.
No transient chatter. Empty list if nothing durable."""

CONTRADICTION_SYSTEM = """[contradiction] Two guest memory statements follow.
Do they contradict — would acting on the old one violate the new one?
Return JSON: {"contradicts": true|false}. Preference *changes* contradict;
unrelated or compatible facts do not."""


@dataclass
class RememberReport:
    stored: list[str]
    reinforced: list[str]
    superseded: list[tuple[str, str]]  # (old content, new content)


class MemoryEngine:
    def __init__(self, store: MemoryStore | None = None, client=None, govern: bool = True):
        # govern=False disables dedupe + supersede (append-only memory) — the
        # naive baseline an eval harness would compare against.
        self.store = store or MemoryStore()
        self.client = client or get_client()
        self.govern = govern

    # ---------------- remember ----------------

    def remember(self, guest_id: str, transcript: str, session_id: str) -> RememberReport:
        raw = self.client.chat(EXTRACT_SYSTEM, transcript, json_mode=True)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            candidates = parsed.get("memories", [])
        elif isinstance(parsed, list):
            candidates = parsed
        else:
            candidates = []
        candidates = [c for c in candidates if isinstance(c, dict) and c.get("content")]
        report = RememberReport([], [], [])
        if not candidates:
            return report

        vectors = self.client.embed([c["content"] for c in candidates])
        for cand, vec in zip(candidates, vectors):
            # Vector-index nearest-neighbor search, not a Python scan over
            # every active memory — this is what actually exercises CRDB's
            # distributed vector index at runtime.
            existing = self.store.nearest(guest_id, vec)
            match, best = None, 0.0
            for mem in existing:
                sim = cosine(vec, mem["embedding"])
                if sim > best:
                    match, best = mem, sim

            if self.govern and match and best >= DEDUPE_T:
                # High similarity = same TOPIC, not necessarily same fact —
                # "always drinks coffee" vs "never drinks coffee" embed nearly
                # identically. The LLM decides: reinforce or supersede.
                if not self._contradicts(match["content"], cand["content"]):
                    self.store.evolve(
                        match["id"], guest_id, match["content"], match["embedding"],
                        match["kind"], match["importance"], session_id,
                        reinforcements=match["reinforcements"] + 1,
                    )
                    report.reinforced.append(match["content"])
                    continue
                reason = f"contradicted in session {session_id}"
                self.store.evolve(
                    match["id"], guest_id, cand["content"], vec, cand.get("kind", "preference"),
                    float(cand.get("importance", 3)), session_id,
                    reinforcements=1, reason=reason,
                )
                report.stored.append(cand["content"])
                report.superseded.append((match["content"], cand["content"]))
                continue

            self.store.add(
                guest_id, cand["content"], vec, cand.get("kind", "preference"),
                float(cand.get("importance", 3)), session_id,
            )
            report.stored.append(cand["content"])

            if not self.govern:
                continue
            # Gray zone: same topic, different statement -> contradiction check
            # against every OTHER existing memory (fan-in: one new memory can
            # retire several unrelated old ones in the same turn).
            for mem in existing:
                sim = cosine(vec, mem["embedding"])
                if CONTRADICTION_T <= sim < DEDUPE_T:
                    if self._contradicts(mem["content"], cand["content"]):
                        reason = f"contradicted by new memory: {cand['content'][:80]!r} (session {session_id})"
                        self.store.retire(mem["id"], guest_id, mem["embedding"], session_id, reason)
                        report.superseded.append((mem["content"], cand["content"]))
        return report

    def _contradicts(self, old: str, new: str) -> bool:
        verdict = self.client.chat(
            CONTRADICTION_SYSTEM, f'OLD: "{old}"\nNEW: "{new}"', json_mode=True)
        try:
            parsed = json.loads(verdict)
        except json.JSONDecodeError:
            return False
        if isinstance(parsed, dict):
            return bool(parsed.get("contradicts", False))
        if isinstance(parsed, bool):
            return parsed
        return False

    # ---------------- recall ----------------

    def recall(self, guest_id: str, query: str, k: int = 6) -> list[dict]:
        qvec = self.client.embed([query])[0]
        # Vector-index nearest-neighbor search narrows to the k*factor closest
        # candidates before the recency/importance/reinforcement re-scoring
        # below — the index does the retrieval, Python does the final rank.
        memories = self.store.nearest(guest_id, qvec, k=max(k * 4, 25))
        if not memories:
            return []
        now = datetime.now(timezone.utc)
        scored = []
        for m in memories:
            sim = cosine(qvec, m["embedding"])
            if sim <= 0:
                continue
            age_days = (now - m["created_at"]).total_seconds() / 86400
            recency = math.pow(0.5, age_days / HALF_LIFE_DAYS)
            importance = 0.5 + m["importance"] / 10.0        # 0.6..1.0
            reinforcement = 1.0 + math.log1p(m["reinforcements"]) / 4.0
            scored.append((sim * recency * importance * reinforcement, m))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            {"content": m["content"], "kind": m["kind"], "score": round(s, 4),
             "reinforcements": m["reinforcements"], "source_session": m["source_session"]}
            for s, m in scored[:k]
        ]
