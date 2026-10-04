"""Payload factories — one per entity, input fields only (PRD §4)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_user_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "email": f"user{n}@example.com",
        "display_name": f"Test User {n}",
        "home_region": "US-CA",
    }
    defaults.update(overrides)
    return defaults


def create_business_page_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Test Business {n}",
        "address_line": f"{n} Main St",
        "city": "Springfield",
        "category": "cafe",
        "website": f"https://biz{n}.example",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {
        "rating": 4,
        "text": "A fair and detailed review of this place.",
    }
    defaults.update(overrides)
    return defaults


def edit_review_payload(**overrides) -> dict:
    defaults = {
        "rating": 5,
        "text": "Updated review text after further visits.",
    }
    defaults.update(overrides)
    return defaults


def create_page_claim_payload(**overrides) -> dict:
    defaults = {
        "kind": "CLAIM",
        "evidence_text": "Ownership evidence bundle attached here.",
    }
    defaults.update(overrides)
    return defaults


def create_ad_account_payload(**overrides) -> dict:
    defaults = {"daily_budget_cents": 10000}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "kind": "SPONSORED_PLACEMENT",
        "bid_cents": 100,
        "starts_on": "2026-09-01",
        "ends_on": "2026-09-30",
        "call_tracking_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_impression_payload(**overrides) -> dict:
    defaults = {"campaign_id": "", "idempotency_key": f"imp-{_seq()}"}
    defaults.update(overrides)
    return defaults


def create_call_event_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": "",
        "caller_number": "+15550001000",
        "called_at": "2026-09-05T12:00:00Z",
        "duration_seconds": 60,
    }
    defaults.update(overrides)
    return defaults


def create_attribution_report_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": "",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "variant": "STRICT",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {
        "review_id": "",
        "kind": "NEGATIVE_DISPUTE",
        "body": "This complaint explains the issue in detail.",
    }
    defaults.update(overrides)
    return defaults


def create_solicitation_case_payload(**overrides) -> dict:
    defaults = {
        "target_review_ids": [],
        "evidence_text": "Evidence of an incentivized review offer.",
    }
    defaults.update(overrides)
    return defaults


def create_consumer_alert_payload(**overrides) -> dict:
    defaults = {
        "kind": "SUSPICIOUS_ACTIVITY",
        "evidence_text": "Public summary of the suspicious activity.",
    }
    defaults.update(overrides)
    return defaults


def create_identity_request_payload(**overrides) -> dict:
    defaults = {
        "subject_user_id": "",
        "requester_label": "Requesting Party LLP",
        "channel": "LEGAL_SUBPOENA",
        "legal_process_ref": "DOCKET-2026-001",
    }
    defaults.update(overrides)
    return defaults


def create_merge_request_payload(**overrides) -> dict:
    defaults = {
        "duplicate_page_id": "",
        "survivor_page_id": "",
        "reason": "Duplicate listings for the same business.",
    }
    defaults.update(overrides)
    return defaults
