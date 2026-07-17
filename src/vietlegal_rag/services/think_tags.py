"""Balance ``<think>`` blocks in a streamed answer.

Reasoning models reach us two different ways. Some send their reasoning out of
band in ``reasoning_content``, and we wrap it in ``<think>`` tags ourselves.
Others (Qwen3 via the OpenAI-compatible endpoint) inline the tags in the normal
content stream, so we never see ``reasoning_content`` at all and simply pass the
tags through.

The inline case is the one that bites: the block is only closed if the model
actually emits ``</think>``. It won't when generation is cut off mid-reasoning
by ``max_tokens``, or when a turn ends in a tool call. Open WebUI then keeps
folding every later token — the answer and the citations — into the collapsed
reasoning bubble, so the user never sees an answer.

Counting on the accumulated text rather than per-chunk is deliberate: tags
arrive split across SSE chunks ("</", "think", ">").
"""
from __future__ import annotations

OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"
CLOSER = "\n</think>\n\n"


def has_unclosed_think(text: str) -> bool:
    """True when ``text`` opened a ``<think>`` block it never closed."""
    if not text:
        return False
    return text.count(OPEN_TAG) > text.count(CLOSE_TAG)
