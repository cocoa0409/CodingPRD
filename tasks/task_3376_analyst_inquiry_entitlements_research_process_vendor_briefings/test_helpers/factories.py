"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Acme Industrial Group",
    "INDUSTRY": "Manufacturing",
    "REGION": "NA",
    "CONTRACT_START": "2026-07-01T00:00:00Z",
    "CONTRACT_END": "2027-06-30T00:00:00Z",
    "SEAT_COUNT": 10,
    "ALLOWANCE": 10,
    "REPRINT_TIER": "STANDARD",
    "SEAT_EMAIL": "seat@acme.example",
    "ANALYST_NAME": "Dana Whitfield",
    "PRACTICE_AREA": "CIO_TECH",
    "SENIORITY": "DISTINGUISHED",
    "TOPIC_ROUTE": "CLOUD_COST",
    "VENDOR_NAME": "Northwind Analytics",
    "VENDOR_REGION": "NA",
    "VENDOR_BAND": "ENTERPRISE",
    "DOC_TITLE": "Comparative Matrix: Cloud Cost Management",
    "DOC_TYPE": "COMPARATIVE_MATRIX",
    "EVENT_NAME": "Symposium 2026",
    "EVENT_START": "2026-10-20T09:00:00Z",
    "EVENT_END": "2026-10-22T17:00:00Z",
}

# Five dimension rows used across the evaluation fixtures.
STANDARD_DIMENSIONS = [
    {"dimension": "PRODUCT_CAPABILITY", "raw_score": 4.35, "weight_pct": 0.30},
    {"dimension": "MARKET_EXECUTION", "raw_score": 3.80, "weight_pct": 0.25},
    {"dimension": "CUSTOMER_VOICE", "raw_score": 4.10, "weight_pct": 0.20},
    {"dimension": "INNOVATION_ROADMAP", "raw_score": 3.25, "weight_pct": 0.15},
    {"dimension": "PRICING_TRANSPARENCY", "raw_score": 2.90, "weight_pct": 0.10},
]

# Five dimension rows whose per-dimension products land on half-cents.
HALF_CENT_DIMENSIONS = [
    {"dimension": "PRODUCT_CAPABILITY", "raw_score": 4.35, "weight_pct": 0.30},
    {"dimension": "MARKET_EXECUTION", "raw_score": 4.10, "weight_pct": 0.25},
    {"dimension": "CUSTOMER_VOICE", "raw_score": 4.10, "weight_pct": 0.20},
    {"dimension": "INNOVATION_ROADMAP", "raw_score": 3.25, "weight_pct": 0.15},
    {"dimension": "PRICING_TRANSPARENCY", "raw_score": 4.05, "weight_pct": 0.10},
]

# Weak dimension rows that fail the inclusion criteria floor.
WEAK_DIMENSIONS = [
    {"dimension": "PRODUCT_CAPABILITY", "raw_score": 2.10, "weight_pct": 0.30},
    {"dimension": "MARKET_EXECUTION", "raw_score": 2.40, "weight_pct": 0.25},
    {"dimension": "CUSTOMER_VOICE", "raw_score": 1.90, "weight_pct": 0.20},
    {"dimension": "INNOVATION_ROADMAP", "raw_score": 2.20, "weight_pct": 0.15},
    {"dimension": "PRICING_TRANSPARENCY", "raw_score": 2.00, "weight_pct": 0.10},
]


def create_client_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "industry": DEFAULTS["INDUSTRY"],
        "region": DEFAULTS["REGION"],
        "contract_start_utc": DEFAULTS["CONTRACT_START"],
        "contract_end_utc": DEFAULTS["CONTRACT_END"],
        "seat_count_contracted": DEFAULTS["SEAT_COUNT"],
        "inquiry_allowance_total": DEFAULTS["ALLOWANCE"],
        "reprint_tier": DEFAULTS["REPRINT_TIER"],
    }
    payload.update(overrides)
    return payload


def create_seat_payload(client_account_id, **overrides) -> dict:
    payload = {
        "client_account_id": client_account_id,
        "seat_email": DEFAULTS["SEAT_EMAIL"],
        "research_role": "PRACTITIONER",
        "seat_kind": "NAMED",
    }
    payload.update(overrides)
    return payload


def create_analyst_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["ANALYST_NAME"],
        "practice_area": DEFAULTS["PRACTICE_AREA"],
        "topic_routes": [DEFAULTS["TOPIC_ROUTE"]],
        "seniority": DEFAULTS["SENIORITY"],
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_inquiry_payload(seat_id, **overrides) -> dict:
    payload = {
        "seat_id": seat_id,
        "topic_route": DEFAULTS["TOPIC_ROUTE"],
        "question_summary": "How should we sequence a cloud cost programme?",
        "requested_start_utc": "2026-09-20T10:00:00Z",
        "duration_minutes": 45,
        "preparation_notes": "Brief attached.",
    }
    payload.update(overrides)
    return payload


def create_document_payload(lead_analyst_id, **overrides) -> dict:
    payload = {
        "title": DEFAULTS["DOC_TITLE"],
        "doc_type": DEFAULTS["DOC_TYPE"],
        "practice_area": DEFAULTS["PRACTICE_AREA"],
        "lead_analyst_id": lead_analyst_id,
        "embargo_days": 14,
        "peer_reviewer_analyst_id": "",
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    payload = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "hq_region": DEFAULTS["VENDOR_REGION"],
        "employee_count_band": DEFAULTS["VENDOR_BAND"],
    }
    payload.update(overrides)
    return payload


def create_inclusion_payload(vendor_id, expected_document_version, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "dimension_scores": [dict(row) for row in STANDARD_DIMENSIONS],
        "inclusion_criteria_met_count": 5,
        "expected_document_version": expected_document_version,
        "reprint_tier": "NONE",
        "permitted_marketing_use": "NO_USE",
        "reprint_copies_authorized": 0,
    }
    payload.update(overrides)
    return payload


def create_briefing_payload(vendor_id, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "briefing_topic": "MARKET_OUTLOOK",
        "requested_start_utc": "2026-09-25T15:00:00Z",
        "duration_minutes": 45,
    }
    payload.update(overrides)
    return payload


def create_sales_relationship_payload(analyst_id, vendor_id, expected_analyst_version,
                                      **overrides) -> dict:
    payload = {
        "analyst_id": analyst_id,
        "vendor_id": vendor_id,
        "relationship_type": "PAID_ADVISORY",
        "annual_value_cents": 5_000_000,
        "expected_analyst_version": expected_analyst_version,
    }
    payload.update(overrides)
    return payload


def create_conference_event_payload(**overrides) -> dict:
    payload = {
        "event_name": DEFAULTS["EVENT_NAME"],
        "venue_region": DEFAULTS["REGION"],
        "start_utc": DEFAULTS["EVENT_START"],
        "end_utc": DEFAULTS["EVENT_END"],
    }
    payload.update(overrides)
    return payload


def create_session_payload(**overrides) -> dict:
    payload = {
        "session_title": "Opening research keynote",
        "session_kind": "RESEARCH_SESSION",
        "duration_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_sponsorship_payload(conference_event_id, vendor_id, expected_conference_event_version,
                               **overrides) -> dict:
    payload = {
        "conference_event_id": conference_event_id,
        "vendor_id": vendor_id,
        "tier": "GOLD",
        "amount_cents": 2_500_000,
        "exclusivity_start_utc": DEFAULTS["EVENT_START"],
        "exclusivity_end_utc": DEFAULTS["EVENT_END"],
        "expected_conference_event_version": expected_conference_event_version,
    }
    payload.update(overrides)
    return payload
