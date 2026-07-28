"""LLM backends.

LiveClient pairs Claude (chat/reasoning — extract + contradiction judging)
with Gemini (embeddings — Claude has no embeddings endpoint). Both stay
within the Claude/Gemini/Grok provider set. MockClient is a deterministic
offline backend so the entire pipeline (memory governance, recall, evals,
CLI) runs and tests with zero API keys.
"""

import hashlib
import json
import math
import re

import anthropic
from google import genai
from google.genai import types

from crdbmemory.config import settings

_TOKEN = re.compile(r"[a-z]{3,}")
_SUFFIXES = ("ically", "ally", "ies", "ing", "ely", "ed", "ly", "es", "ic", "s", "y")
_STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "that", "this", "these", "those",
    "could", "would", "should", "will", "can", "may", "might", "have", "has",
    "was", "were", "are", "not", "but", "all", "any", "one", "two", "out",
    "pleas", "alway", "never", "usuall", "same", "again", "back", "now", "note",
    "just", "also", "here", "there", "what", "when", "where", "how", "who",
    "does", "did", "get", "got", "make", "made", "take", "took", "last", "time",
    "certain", "certainl", "know", "based", "good", "evening", "hello", "thank",
}


def _stem(tok: str) -> str:
    """Crude suffix stripper so the mock backend bridges morphology the way
    real embeddings bridge it semantically (allergy/allergic, morning/mornings).
    Runs to a fixpoint so 'mornings' and 'morning' both land on 'morn'."""
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= 4:
                tok = tok[: -len(suf)]
                changed = True
                break
    return tok


def _tokens(text: str) -> list[str]:
    out = [_stem(t) for t in _TOKEN.findall(text.lower())]
    return [t for t in out if t not in _STOPWORDS]


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


# Structured-output schemas for the two prompt kinds engine.py sends with
# json_mode=True (see the [extract] / [contradiction] markers below) — using
# output_config.format instead of asking nicely for JSON in the prompt.
_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "kind": {"type": "string", "enum": [
                        "preference", "fact", "incident", "policy_learning"]},
                    "importance": {"type": "integer"},
                },
                "required": ["content", "kind", "importance"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["memories"],
    "additionalProperties": False,
}
_CONTRADICTION_SCHEMA = {
    "type": "object",
    "properties": {"contradicts": {"type": "boolean"}},
    "required": ["contradicts"],
    "additionalProperties": False,
}


class LiveClient:
    """Claude (chat) + Gemini (embeddings) over the official SDKs."""

    def __init__(self):
        self._anthropic = anthropic.Anthropic()  # resolves credentials itself
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not set — add it to .env or use LLM_BACKEND=mock")
        self._genai = genai.Client(api_key=settings.gemini_api_key)

    def chat(self, system: str, user: str, model: str | None = None,
             json_mode: bool = False) -> str:
        kwargs = {}
        if json_mode:
            schema = (_EXTRACT_SCHEMA if "[extract]" in system
                      else _CONTRADICTION_SCHEMA if "[contradiction]" in system
                      else None)
            if schema:
                kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        response = self._anthropic.messages.create(
            model=model or settings.chat_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        return next(b.text for b in response.content if b.type == "text")

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self._genai.models.embed_content(
            model=settings.embed_model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=settings.embed_dim),
        )
        return [_normalize(e.values) for e in result.embeddings]


class MockClient:
    """Deterministic offline backend.

    chat(): recognizes the pipeline's prompt kinds by marker tags the callers
    embed in their system prompts ([extract] / [contradiction]) and produces
    rule-based outputs good enough to exercise every code path. embed():
    bag-of-hashed-tokens vectors (token overlap ~= cosine similarity).
    """

    def chat(self, system: str, user: str, model: str | None = None,
             json_mode: bool = False) -> str:
        if "[extract]" in system:
            keywords = ("prefer", "allerg", "always", "never", "love", "hate",
                        "usually", "usual", "need", "morning", "each",
                        "instead", "no longer", "vegetarian", "vegan", "kosher", "halal")
            memories = []
            for line in user.splitlines():
                line = line.strip()
                if not line.lower().startswith("guest:"):
                    continue
                line = line.split(":", 1)[-1].strip()
                for sentence in re.split(r"(?<=[.!?])\s+", line):
                    sentence = sentence.strip().rstrip(".!?")
                    if sentence and any(k in sentence.lower() for k in keywords):
                        memories.append({
                            "content": sentence,
                            "kind": "preference",
                            "importance": 4,
                        })
            return json.dumps({"memories": memories})
        if "[contradiction]" in system:
            m = re.findall(r'"([^"]+)"', user)
            if len(m) >= 2:
                old, new = m[0], m[1]
                a, b = set(_tokens(old)), set(_tokens(new))
                neg = re.compile(r"\b(never|no longer|not|stopped|given up|quit)\b")
                change = re.compile(r"\b(instead|no longer|switch\w*|chang\w*|quit|given up|stopped|correction)\b")
                polarity_flip = bool(neg.search(old.lower())) != bool(neg.search(new.lower()))
                shared_topic = len(a & b) >= 2
                return json.dumps({"contradicts": shared_topic and
                                   (polarity_flip or bool(change.search(new.lower())))})
            return json.dumps({"contradicts": False})
        mems = re.findall(r"- (.+)", system + "\n" + user)
        mems = [m for m in mems if "no prior memories" not in m]
        if mems:
            return "Certainly. Based on what I know: " + "; ".join(mems[:2]) + "."
        return "Certainly — how may I assist you today?"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * settings.embed_dim
            for tok in _tokens(text):
                h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "big")
                vec[h % settings.embed_dim] += 1.0
            out.append(_normalize(vec))
        return out


def get_client():
    if settings.llm_backend == "mock":
        return MockClient()
    return LiveClient()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
