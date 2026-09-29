"""
Request payload factories.

Every default here satisfies the PRD's format rules so that a factory call
never trips the request-shape rung of the validation ladder by accident:
campaign codes are uppercase letters, digits and hyphens within 32
characters; quarter codes match a four-digit year beginning 20 followed by
Q and a digit 1-4; keywords and expertise tags are lowercase; slot week
dates are Mondays in ``YYYY-MM-DD`` form; every instant carries three
fractional digits; monetary amounts are whole-cent integers; publication
metadata clears the accessibility floor of at least 50 characters and at
least two tags.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# ─── Instant helpers ──────────────────────────────────

_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def instant(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    millisecond: int = 0,
) -> str:
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    moment = datetime(
        year, month, day, hour, minute, second, millisecond * 1000, tzinfo=timezone.utc
    )
    return moment.strftime(_INSTANT_FORMAT)[:-4] + "Z"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant that may or may not carry a fraction."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def render_instant(moment: datetime) -> str:
    """Render a datetime back to the PRD's three-fractional-digit form."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(_INSTANT_FORMAT)[:-4] + "Z"


def shift_instant(
    value: str,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    milliseconds: int = 0,
) -> str:
    """Offset an instant, keeping the three-fractional-digit rendering."""
    moment = parse_instant(value) + timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
    )
    return render_instant(moment)


def week_start(value: str) -> str:
    """Return the ``YYYY-MM-DD`` Monday anchor of the ISO week holding an instant."""
    moment = parse_instant(value)
    monday = moment - timedelta(days=moment.weekday())
    return monday.strftime("%Y-%m-%d")


def week_start_instant(date_text: str) -> str:
    """Render a ``YYYY-MM-DD`` slot week date as its opening instant."""
    parts = [int(piece) for piece in date_text.split("-")]
    return instant(parts[0], parts[1], parts[2])


# ─── Campaign (PRD 3.1) ───────────────────────────────

def campaign_payload(
    code: str = "CMP-BASE-001",
    persona: str = "PRACTITIONER",
    primary_funnel_stage: str = "CONSIDERATION",
    quarter_code: str = "2026Q3",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "persona": persona,
        "primary_funnel_stage": primary_funnel_stage,
        "quarter_code": quarter_code,
    }
    payload.update(overrides)
    return payload


# ─── Calendar slot (PRD 3.1) ──────────────────────────

def calendar_slot_payload(
    week_start_date: str = "2026-08-03",
    funnel_stage: str = "CONSIDERATION",
    capacity_points: int = 40,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "week_start_date": week_start_date,
        "funnel_stage": funnel_stage,
        "capacity_points": capacity_points,
    }
    payload.update(overrides)
    return payload


# ─── Expert (PRD 3.2) ─────────────────────────────────

def expert_payload(
    full_name: str = "Avery Stone",
    expertise_tags: Optional[List[str]] = None,
    weekly_capacity_hours: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "expertise_tags": list(expertise_tags or ["cloud-security"]),
        "weekly_capacity_hours": weekly_capacity_hours,
    }
    payload.update(overrides)
    return payload


# ─── Brief (PRD 3.3) ──────────────────────────────────

def brief_payload(
    campaign_id: str,
    funnel_stage: str = "CONSIDERATION",
    search_intent: str = "COMMERCIAL",
    primary_keyword: str = "zero trust rollout",
    target_word_count: int = 1500,
    required_expertise_tag: str = "cloud-security",
    review_window_start: str = "2026-08-03T09:00:00.000Z",
    review_window_end: str = "2026-08-03T17:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "funnel_stage": funnel_stage,
        "search_intent": search_intent,
        "primary_keyword": primary_keyword,
        "target_word_count": target_word_count,
        "required_expertise_tag": required_expertise_tag,
        "review_window_start": review_window_start,
        "review_window_end": review_window_end,
    }
    payload.update(overrides)
    return payload


def review_window(start: str, hours: int) -> Dict[str, str]:
    """A whole-hour review window inside a single ISO week."""
    return {
        "review_window_start": start,
        "review_window_end": shift_instant(start, hours=hours),
    }


def assign_sme_payload(
    sme_expert_id: str, expected_expert_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sme_expert_id": sme_expert_id,
        "expected_expert_version": expected_expert_version,
    }
    payload.update(overrides)
    return payload


# ─── Content item (PRD 3.4) ───────────────────────────

def content_item_payload(
    brief_id: str,
    slot_id: str,
    expected_campaign_version: int,
    title: str = "Zero trust rollout playbook",
    planned_publish_at: str = "2026-08-05T09:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brief_id": brief_id,
        "slot_id": slot_id,
        "expected_campaign_version": expected_campaign_version,
        "title": title,
        "planned_publish_at": planned_publish_at,
    }
    payload.update(overrides)
    return payload


# ─── Claims and evidence (PRD 3.6) ────────────────────

def claim_payload(
    claim_text: str = "Deployments complete forty percent faster on the new platform.",
    claim_type: str = "PERFORMANCE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claim_text": claim_text, "claim_type": claim_type}
    payload.update(overrides)
    return payload


def evidence_payload(
    source_type: str = "THIRD_PARTY_TEST",
    citation: str = "Independent lab benchmark report, third quarter 2026",
    collected_at: str = "2026-07-01T00:00:00.000Z",
    valid_until: str = "2026-12-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_type": source_type,
        "citation": citation,
        "collected_at": collected_at,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


# ─── Assets and usages (PRD 3.7) ──────────────────────

def asset_payload(
    name: str = "Hero photography set",
    asset_type: str = "STOCK",
    license_start: str = "2026-07-01T00:00:00.000Z",
    license_end: str = "2026-12-31T00:00:00.000Z",
    licensed_channels: Optional[List[str]] = None,
    max_licensed_uses: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "asset_type": asset_type,
        "license_start": license_start,
        "license_end": license_end,
        "licensed_channels": list(licensed_channels or ["OWNED", "EMAIL"]),
        "max_licensed_uses": max_licensed_uses,
    }
    payload.update(overrides)
    return payload


def asset_usage_payload(
    asset_id: str, channel: str = "OWNED", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"asset_id": asset_id, "channel": channel}
    payload.update(overrides)
    return payload


# ─── Publication (PRD 3.8) ────────────────────────────

# At least 50 characters, so the accessibility floor is cleared.
COMPLIANT_META_DESCRIPTION = (
    "A practical walkthrough of staged zero trust rollout for platform teams."
)
# Fewer than 50 characters, for the metadata floor rejection.
SHORT_META_DESCRIPTION = "A short summary of the rollout guide only."
COMPLIANT_TAGS = ["security", "platform"]


def publish_payload(
    scheduled_at: str = "2026-08-05T09:00:00.000Z",
    channels: Optional[List[str]] = None,
    meta_description: str = COMPLIANT_META_DESCRIPTION,
    url_slug: str = "zero-trust-rollout-playbook",
    tags: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_at": scheduled_at,
        "channels": list(channels or ["OWNED", "EMAIL"]),
        "meta_description": meta_description,
        "url_slug": url_slug,
        "tags": list(tags if tags is not None else COMPLIANT_TAGS),
    }
    payload.update(overrides)
    return payload


# ─── Measurement (PRD 3.9) ────────────────────────────

def performance_snapshot_payload(
    period_start: str,
    period_end: str,
    engaged_sessions: int = 400,
    conversions: int = 7,
    influenced_opportunity_amount_cents: int = 250000,
    touch_position: str = "LAST",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Build a measurement period.

    ``influenced_opportunity_amount_cents`` is a whole-cent integer, never a
    decimal string, because the PRD holds monetary quantities in whole cents.
    """
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "engaged_sessions": engaged_sessions,
        "conversions": conversions,
        "influenced_opportunity_amount_cents": influenced_opportunity_amount_cents,
        "touch_position": touch_position,
    }
    payload.update(overrides)
    return payload


# ─── Audit (PRD 3.9) ──────────────────────────────────

def audit_payload(
    audit_type: str = "DECAY",
    accuracy_finding: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"audit_type": audit_type}
    if accuracy_finding is not None:
        payload["accuracy_finding"] = accuracy_finding
    payload.update(overrides)
    return payload
