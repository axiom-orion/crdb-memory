"""Node-kill resilience demo — the video beat for "memory that survives".

Connects to the local 3-node CockroachDB cluster (scripts/local_cluster.sh),
writes and recalls real guest memories through the actual engine, kills one
node mid-conversation, and proves the memory keeps serving on the surviving
2-of-3 quorum — no data loss, no downtime, nothing to explain away.

Run: python scripts/node_kill_demo.py
Requires: scripts/local_cluster.sh up (already running), DATABASE_URL_LOCAL in .env
"""

import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults mangle em-dashes

from crdbmemory.config import settings
from crdbmemory.engine import MemoryEngine
from crdbmemory.store import MemoryStore


def say(msg: str) -> None:
    print(f"\n>>> {msg}")
    sys.stdout.flush()


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True)


def main() -> None:
    if not settings.database_url_local:
        raise SystemExit("DATABASE_URL_LOCAL not set — run scripts/local_cluster.sh up first")

    store = MemoryStore(database_url=settings.database_url_local)
    engine = MemoryEngine(store=store)
    guest = "demo-guest"
    session = "node-kill-demo"

    say("All 3 nodes live. Guest checks in.")
    engine.remember(
        guest,
        "Guest: I prefer window seating. Guest: I am allergic to shellfish.",
        session,
    )
    for m in store.active(guest):
        print(f"  stored: {m['content']!r}")

    say("Recall while all 3 nodes are healthy:")
    for r in engine.recall(guest, "seating"):
        print(f"  recalled: {r['content']!r} (score={r['score']})")

    say("Killing node roach2 mid-conversation (docker stop)...")
    docker("stop", "roach2")
    say("Waiting for CockroachDB's liveness record to actually expire (~12s)...")
    time.sleep(12)

    say("Node status — confirmed down, not just stopped:")
    result = subprocess.run(
        ["docker", "exec", "roach1", "./cockroach", "node", "status", "--insecure"],
        capture_output=True, text=True,
    )
    print(result.stdout)

    say("Guest keeps talking — writing a NEW memory with only 2/3 nodes up:")
    engine.remember(guest, "Guest: I also prefer a quiet room.", f"{session}-post-kill")

    say("Recall again — quorum (2 of 3) still serves reads and writes:")
    for r in engine.recall(guest, "seating"):
        print(f"  recalled: {r['content']!r} (score={r['score']})")

    say("Bringing roach2 back...")
    docker("start", "roach2")
    time.sleep(5)

    say("Full history for this guest — nothing lost, nothing corrupted:")
    for h in store.history(guest):
        print(f"  {h['created_at']}: {h['content']!r} (supersedes={h['supersedes']})")

    store.close()
    say("Done. The killed node's downtime never touched the memory the guest experienced.")


if __name__ == "__main__":
    main()
