"""Runtime pipeline: extract() -> retrieve() -> rank_and_reply().

Claude runtime calls B and C; retrieve() is plain Python.
"""
import json
import logging
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("covio2.pipeline")

MODEL = "claude-haiku-4-5"  # cheapest model; handles extraction + multilingual reply
LISTINGS_PATH = Path(__file__).parent / "data" / "listings.json"
ENV_PATH = Path(__file__).parent / ".env"

# Load ANTHROPIC_API_KEY from covio2/.env if present; an already-exported
# env var still takes precedence (load_dotenv does not override it).
if load_dotenv(ENV_PATH):
    log.info("loaded environment from %s", ENV_PATH)

if not os.environ.get("ANTHROPIC_API_KEY"):
    log.warning(
        "ANTHROPIC_API_KEY not set — create %s with a line like "
        'ANTHROPIC_API_KEY="sk-ant-..." or export the variable', ENV_PATH
    )

_client = None
_listings = None


def _get_client():
    """Lazy client so the app can start (and show a friendly error) even
    when the key is missing — anthropic.Anthropic() raises without one."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client

EXTRACT_SYSTEM = """You are the intake classifier for a nonprofit oxygen-resource helpline.
Extract structured fields from the user's message. The message may be in any
language, including Hindi, Marathi, or English (or transliterated Hinglish).

Return ONLY a JSON object, no other text:
{
  "city": one of "indore" | "mumbai" | "delhi" | "other" | null,
  "city_mentioned": the city name as the user wrote it, or null,
  "language": BCP-47 code of the user's language (e.g. "hi", "mr", "en"),
  "resource_type": one of "cylinder" | "concentrator" | "refill" | "can" | "any",
  "location_detail": neighbourhood/area within the city if mentioned
                     (e.g. "Andheri"), else null,
  "urgency": "high" | "normal",
  "delivery_preference": "home_delivery" | "pickup" | null,
  "notes": one short relevant sentence, or null
}
Rules:
- "city" must be "other" if the user names a city not in the supported three.
- If no resource type is specified, use "any".
- Urgency is "high" only if the message signals emergency/distress."""

RANK_SYSTEM = """You are a helpline assistant for a nonprofit that CONNECTS people to oxygen
suppliers (it does not sell anything). You receive the user's message,
extracted fields, and candidate supplier listings from a static dataset
verified in 2021.

Rank the candidates and pick the best THREE (fewer if fewer exist), best
first, using these rules in priority order:
1. Most recently verified listing wins.
2. Matches the user's delivery preference.
3. If the user gave a locality (location_detail), prefer listings located
   nearby or covering the whole city / offering home delivery.
4. If urgency is "high", prefer listings with fewer/no document requirements.
5. Prefer free or cheaper options when otherwise similar.
6. Prefer complete listings (phone, location, price all present).

Return ONLY a JSON object:
{
  "top_listing_ids": ["<best id>", "<second>", "<third>"],  // up to 3, best first; [] if none
  "reason": "<one sentence in English explaining the ranking>",
  "reply": "<message to the user, ENTIRELY in the user's language (code
            provided). Do NOT repeat supplier details — a table with the
            top options is shown below your message. Briefly say the best
            options are listed below, mention anything important (e.g.
            confirm null price/documents on the phone call). Always include
            a brief caution that (a) this data was verified in 2021 and may
            be outdated, and (b) the nonprofit only connects people to
            suppliers and does not sell or guarantee anything.
            Under 80 words, warm and clear.>"
}
Special cases:
- No candidates because the city is unsupported: politely say only Indore,
  Mumbai, and Delhi are covered, in the user's language; top_listing_ids [].
- Candidates exist but none truly fit: apologize and offer the closest options."""


def load_listings():
    """Returns {"indore": [listing, ...], "mumbai": [...], "delhi": [...]}."""
    global _listings
    if _listings is None:
        log.info("loading listings from %s", LISTINGS_PATH)
        _listings = json.loads(LISTINGS_PATH.read_text())
        for city, rows in _listings.items():
            active = sum(1 for r in rows if r["active"])
            log.info("  %s: %d listings (%d active)", city, len(rows), active)
    return _listings


def _parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def extract(user_message):
    log.info("STEP 1 extract: calling Claude (%s) with message: %r", MODEL, user_message)
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=512,
        system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    try:
        extracted = _parse_json(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        log.error("STEP 1 extract: could not parse Claude response: %r",
                  response.content[0].text if response.content else "<empty>")
        raise
    log.info("STEP 1 extract: city=%s type=%s lang=%s urgency=%s location_detail=%s",
             extracted.get("city"), extracted.get("resource_type"),
             extracted.get("language"), extracted.get("urgency"),
             extracted.get("location_detail"))
    return extracted


def retrieve(extracted):
    city = extracted.get("city")
    city_listings = load_listings().get(city, [])
    active = [l for l in city_listings if l["active"]]
    candidates = [
        l for l in active
        if extracted.get("resource_type") == "any"
        or extracted.get("resource_type") in l["resource_types"]
    ]
    if not candidates and active:
        log.info("STEP 2 retrieve: no %r match in %s, falling back to all active",
                 extracted.get("resource_type"), city)
        candidates = active
    result = sorted(candidates, key=lambda l: l["verified_date"] or "", reverse=True)[:12]
    log.info("STEP 2 retrieve: city=%s -> %d total, %d active, %d candidates (top: %s)",
             city, len(city_listings), len(active), len(result),
             [c["id"] for c in result[:3]])
    return result


def rank_and_reply(user_message, extracted, candidates):
    log.info("STEP 3 rank_and_reply: calling Claude (%s) with %d candidates",
             MODEL, len(candidates))
    # Trim payload to what ranking actually needs: drop bookkeeping fields,
    # `city` (identical across candidates; already in extracted) and
    # `city_mentioned` (only useful during extraction).
    trimmed = [
        {k: v for k, v in c.items()
         if k not in ("active", "inactive_reason", "raw_object", "city")}
        for c in candidates
    ]
    extracted_slim = {k: v for k, v in extracted.items() if k != "city_mentioned"}
    payload = {"user_message": user_message, "extracted": extracted_slim, "candidates": trimmed}
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=RANK_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
    )
    try:
        result = _parse_json(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        log.error("STEP 3 rank_and_reply: could not parse Claude response: %r",
                  response.content[0].text if response.content else "<empty>")
        raise
    # Resolve returned ids to full listings, keeping rank order and dropping
    # any id Claude hallucinated that isn't in the candidate set.
    by_id = {c["id"]: c for c in candidates}
    result["top_listings"] = [by_id[i] for i in result.get("top_listing_ids", []) if i in by_id][:3]
    log.info("STEP 3 rank_and_reply: top_listing_ids=%s reason=%s",
             [l["id"] for l in result["top_listings"]], result.get("reason"))
    return result


def run(user_message):
    """Full pipeline; returns (extracted, candidates, result)."""
    log.info("=== pipeline start ===")
    try:
        extracted = extract(user_message)
        candidates = retrieve(extracted) if extracted.get("city") in ("indore", "mumbai", "delhi") else []
        if not candidates:
            log.info("STEP 2 retrieve: skipped or empty (city=%s) — out-of-scope reply expected",
                     extracted.get("city"))
        result = rank_and_reply(user_message, extracted, candidates)
    except Exception:
        log.exception("pipeline failed")
        raise
    log.info("=== pipeline done ===")
    return extracted, candidates, result
