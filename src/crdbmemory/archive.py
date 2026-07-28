"""S3 durability backstop for the memory ledger.

The CockroachDB cluster is the live, queryable memory — but "memory that
survives" means surviving more than a lost node. A full-lineage export to S3
(tombstones included) means the entire guest memory history can be replayed
into a fresh cluster even if the cluster itself were gone, not just a node
within it.
"""

import json
from datetime import datetime, timezone

import boto3

from crdbmemory.config import settings
from crdbmemory.store import MemoryStore


def export_snapshot(store: MemoryStore | None = None, bucket: str | None = None) -> str:
    """Dump every row (all guests, full lineage) to S3 as JSONL. Returns the S3 key."""
    bucket = bucket or settings.s3_archive_bucket
    if not bucket:
        raise RuntimeError("S3_ARCHIVE_BUCKET not set — add it to .env")
    own_store = store is None
    store = store or MemoryStore()
    try:
        rows = store.export_all()
    finally:
        if own_store:
            store.close()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"crdb-memory-snapshots/{stamp}.jsonl"
    body = "\n".join(json.dumps(r) for r in rows).encode("utf-8")

    s3 = boto3.client("s3", region_name=settings.aws_region)
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-ndjson")
    return key


def restore_snapshot(key: str, bucket: str | None = None) -> list[dict]:
    """Read a snapshot back — for verifying the backstop, or replaying rows
    into a fresh cluster after a real loss."""
    bucket = bucket or settings.s3_archive_bucket
    if not bucket:
        raise RuntimeError("S3_ARCHIVE_BUCKET not set — add it to .env")
    s3 = boto3.client("s3", region_name=settings.aws_region)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line.strip()]
