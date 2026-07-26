CREATE TABLE IF NOT EXISTS memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  guest_id STRING NOT NULL,
  content STRING NOT NULL,
  embedding VECTOR(3) NOT NULL,
  importance FLOAT NOT NULL DEFAULT 3,
  reinforcements INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  superseded_by UUID REFERENCES memories(id)
);

CREATE VECTOR INDEX IF NOT EXISTS idx_memories_embedding
  ON memories (embedding vector_cosine_ops);

INSERT INTO memories (guest_id, content, embedding) VALUES
  ('g1', 'prefers matcha over cappuccino', '[0.10, 0.90, 0.00]'),
  ('g1', 'allergic to shellfish',           '[0.95, 0.02, 0.03]'),
  ('g1', 'likes window seating',            '[0.12, 0.85, 0.05]');

-- nearest-neighbor recall: what does g1 like that's closest to "tea preference"?
SELECT content, embedding <=> '[0.15, 0.88, 0.02]' AS distance
FROM memories
WHERE guest_id = 'g1' AND superseded_by IS NULL
ORDER BY embedding <=> '[0.15, 0.88, 0.02]'
LIMIT 3;

EXPLAIN SELECT content FROM memories
WHERE guest_id = 'g1' AND superseded_by IS NULL
ORDER BY embedding <=> '[0.15, 0.88, 0.02]'
LIMIT 3;
