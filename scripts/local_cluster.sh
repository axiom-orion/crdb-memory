#!/usr/bin/env bash
# 3-node local CockroachDB cluster for the node-kill resilience demo.
# Not the production data path (that's CockroachDB Cloud, tinted-guppy) —
# this exists purely to prove the underlying distributed-storage guarantee:
# kill one node, quorum survives, the memory ledger keeps serving.
set -euo pipefail

NET=crdb-demo-net
IMAGE=cockroachdb/cockroach:latest
SQL_PORT=26258  # host port -> node 1's 26257; picked to dodge a local conflict

up() {
  docker network create "$NET" 2>/dev/null || true
  for n in roach1 roach2 roach3; do
    docker rm -f "$n" 2>/dev/null || true
  done
  docker run -d --name=roach1 --hostname=roach1 --net="$NET" -p "$SQL_PORT:26257" \
    "$IMAGE" start --insecure --join=roach1,roach2,roach3
  docker run -d --name=roach2 --hostname=roach2 --net="$NET" \
    "$IMAGE" start --insecure --join=roach1,roach2,roach3
  docker run -d --name=roach3 --hostname=roach3 --net="$NET" \
    "$IMAGE" start --insecure --join=roach1,roach2,roach3
  sleep 3
  docker exec roach1 ./cockroach init --insecure
  sleep 5
  docker exec roach1 ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS crdbmemory"
  docker exec roach1 ./cockroach sql --insecure -d crdbmemory -e "
    CREATE TABLE IF NOT EXISTS guest_memories (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      guest_id STRING NOT NULL,
      kind STRING NOT NULL DEFAULT 'preference',
      content STRING NOT NULL,
      embedding VECTOR(1024) NOT NULL,
      importance FLOAT NOT NULL DEFAULT 3,
      reinforcements INT NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      source_session STRING NOT NULL,
      supersedes UUID REFERENCES guest_memories(id),
      supersede_reason STRING,
      VECTOR INDEX idx_guest_memories_embedding (embedding vector_cosine_ops)
    )"
  docker exec roach1 ./cockroach node status --insecure
  echo "Cluster up. DATABASE_URL_LOCAL=postgresql://root@localhost:$SQL_PORT/crdbmemory?sslmode=disable"
}

status() {
  docker exec roach1 ./cockroach node status --insecure
}

down() {
  for n in roach1 roach2 roach3; do
    docker rm -f "$n" 2>/dev/null || true
  done
  docker network rm "$NET" 2>/dev/null || true
}

case "${1:-up}" in
  up) up ;;
  status) status ;;
  down) down ;;
  *) echo "usage: $0 [up|status|down]"; exit 1 ;;
esac
