from __future__ import annotations

from app.models import NewsItem


MAX_TEXT_CHARS = 2000

LLM_ANALYSIS_SYSTEM_PROMPT = (
    "You analyze gold-market news for a research and paper-trading MVP. "
    "Return only valid JSON. Do not include markdown. "
    "Use sentiment values positive, negative, or neutral. "
    "Scores must be decimals between -1 and 1. Confidence and relevance scores "
    "must be decimals between 0 and 1."
)

LLM_ANALYSIS_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["sentiment", "score", "confidence", "reasoning", "event_tags"],
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "score": {"type": "number", "minimum": -1, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "event_tags": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tag_type", "tag_value", "relevance_score"],
                "properties": {
                    "tag_type": {"type": "string"},
                    "tag_value": {"type": "string"},
                    "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}


def build_analysis_prompt(item: NewsItem) -> str:
    text_parts = [
        f"Title: {_clean_text(item.title)}",
        f"Published at UTC: {item.published_at.isoformat()}",
    ]
    if item.summary:
        text_parts.append(f"Summary: {_clean_text(item.summary)}")
    if item.content:
        text_parts.append(f"Content: {_clean_text(item.content)}")

    article_text = "\n".join(text_parts)
    if len(article_text) > MAX_TEXT_CHARS:
        article_text = article_text[:MAX_TEXT_CHARS].rstrip() + "\n[truncated]"

    return (
        "Analyze this news item for expected gold price impact.\n"
        "Return JSON with exactly these top-level fields: sentiment, score, "
        "confidence, reasoning, event_tags.\n"
        "event_tags must contain zero or more objects with tag_type, tag_value, "
        "and relevance_score.\n\n"
        f"{article_text}"
    )


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())
