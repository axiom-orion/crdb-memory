"""CockroachDB-backed memory store with full lifecycle provenance.

Append-only by design: nothing is ever UPDATEd or DELETEd. Reinforcing a
memory and superseding it are the same operation underneath — INSERT a new
row whose `supersedes` column points at the old one. "Reinforce" just means
the new row repeats the old content with reinforcements+1; "supersede" means
it carries different content and a reason. An "active" memory is the tip of
its lineage chain: the row nothing else points `supersedes` at.

This is deliberately stronger than an UPDATE-based design on a distributed
store — there is no in-place mutation for a node failure to catch mid-write.
A killed node can only ever cost you an uncommitted INSERT, never corrupt
existing history.
"""

import psycopg

from crdbmemory.config import settings


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _parse_vec(raw) -> list[float]:
    if isinstance(raw, list):
        return [float(x) for x in raw]
    return [float(x) for x in raw.strip("[]").split(",") if x.strip()]


class MemoryStore:
    def __init__(self, database_url: str | None = None):
        dsn = database_url or settings.database_url
        if not dsn:
            raise RuntimeError("DATABASE_URL not set — add it to .env")
        self.con = psycopg.connect(dsn, autocommit=True)

    def close(self) -> None:
        self.con.close()

    # ---------------- writes (INSERT only — no UPDATE, no DELETE) ----------------

    def add(self, guest_id: str, content: str, embedding: list[float],
             kind: str, importance: float, session_id: str) -> str:
        with self.con.cursor() as cur:
            cur.execute(
                "INSERT INTO guest_memories"
                " (guest_id, kind, content, embedding, importance, source_session)"
                " VALUES (%s, %s, %s, %s::VECTOR, %s, %s) RETURNING id",
                (guest_id, kind, content, _vec_literal(embedding), importance, session_id),
            )
            return str(cur.fetchone()[0])

    def evolve(self, old_id: str, guest_id: str, content: str, embedding: list[float],
               kind: str, importance: float, session_id: str,
               reinforcements: int, reason: str | None = None) -> str:
        """INSERT the next link in old_id's lineage chain. Same content +
        reinforcements=old+1 = a reinforcement; different content + reason =
        a supersession. old_id's row itself is never touched."""
        with self.con.cursor() as cur:
            cur.execute(
                "INSERT INTO guest_memories"
                " (guest_id, kind, content, embedding, importance, reinforcements,"
                "  source_session, supersedes, supersede_reason)"
                " VALUES (%s, %s, %s, %s::VECTOR, %s, %s, %s, %s, %s) RETURNING id",
                (guest_id, kind, content, _vec_literal(embedding), importance,
                 reinforcements, session_id, old_id, reason),
            )
            return str(cur.fetchone()[0])

    def retire(self, old_id: str, guest_id: str, embedding: list[float],
               session_id: str, reason: str) -> None:
        """Mark old_id superseded without introducing a new recallable memory.

        Used when a single new memory contradicts *multiple* unrelated
        existing ones in the same turn — evolve() already linked the primary
        match; each additional contradicted memory gets a tombstone row
        instead, so fan-in supersession works without ever UPDATEing the old
        row or needing an array-typed column."""
        with self.con.cursor() as cur:
            cur.execute(
                "INSERT INTO guest_memories"
                " (guest_id, kind, content, embedding, importance, reinforcements,"
                "  source_session, supersedes, supersede_reason)"
                " VALUES (%s, 'tombstone', '(retired)', %s::VECTOR, 0, 0, %s, %s, %s)",
                (guest_id, _vec_literal(embedding), session_id, old_id, reason),
            )

    # ---------------- reads ----------------

    def active(self, guest_id: str) -> list[dict]:
        """Lineage tips for this guest: rows nothing else `supersedes`,
        excluding tombstones (they exist only to retire other rows)."""
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT id, guest_id, kind, content, embedding, importance,"
                " reinforcements, created_at, source_session, supersedes, supersede_reason"
                " FROM guest_memories m"
                " WHERE m.guest_id = %s AND m.kind != 'tombstone'"
                "   AND NOT EXISTS (SELECT 1 FROM guest_memories s WHERE s.supersedes = m.id)",
                (guest_id,),
            )
            cols = [d.name for d in cur.description]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["embedding"] = _parse_vec(d["embedding"])
                d["id"] = str(d["id"])
                out.append(d)
            return out

    def nearest(self, guest_id: str, query_embedding: list[float], k: int = 25) -> list[dict]:
        """Active lineage tips for this guest, nearest-first by cosine distance
        via CRDB's vector index (`embedding <=> query`) — the actual runtime
        query dedupe/recall use, not just a schema-level index nobody queries."""
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT id, guest_id, kind, content, embedding, importance,"
                " reinforcements, created_at, source_session, supersedes, supersede_reason"
                " FROM guest_memories m"
                " WHERE m.guest_id = %s AND m.kind != 'tombstone'"
                "   AND NOT EXISTS (SELECT 1 FROM guest_memories s WHERE s.supersedes = m.id)"
                " ORDER BY embedding <=> %s::VECTOR LIMIT %s",
                (guest_id, _vec_literal(query_embedding), k),
            )
            cols = [d.name for d in cur.description]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["embedding"] = _parse_vec(d["embedding"])
                d["id"] = str(d["id"])
                out.append(d)
            return out

    def history(self, guest_id: str) -> list[dict]:
        """Full audit trail including superseded links (no embeddings)."""
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT id, kind, content, importance, reinforcements, source_session,"
                " supersedes, supersede_reason, created_at"
                " FROM guest_memories WHERE guest_id = %s ORDER BY created_at",
                (guest_id,),
            )
            cols = [d.name for d in cur.description]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                if d["supersedes"] is not None:
                    d["supersedes"] = str(d["supersedes"])
                out.append(d)
            return out

    def export_all(self) -> list[dict]:
        """Every row, every guest, full lineage incl. tombstones — for offsite
        backup (see crdbmemory.archive), not for recall (see active())."""
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT id, guest_id, kind, content, embedding, importance,"
                " reinforcements, created_at, source_session, supersedes, supersede_reason"
                " FROM guest_memories ORDER BY created_at"
            )
            cols = [d.name for d in cur.description]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                if d["supersedes"] is not None:
                    d["supersedes"] = str(d["supersedes"])
                d["embedding"] = _parse_vec(d["embedding"])
                d["created_at"] = d["created_at"].isoformat()
                out.append(d)
            return out
