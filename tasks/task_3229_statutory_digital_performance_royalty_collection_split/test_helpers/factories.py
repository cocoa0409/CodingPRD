"""Payload factories — one per entity, input fields only."""
from .constants import (
    NS1_CATEGORY,
    NS1_MIN_FEE_CENTS,
    NS1_RATE_MICROCENTS,
    NS1_WINDOW_END,
    NS1_WINDOW_START,
    POOL_WINDOW_END,
    POOL_WINDOW_START,
)


def create_licensee_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Licensee Co",
        "service_category": NS1_CATEGORY,
        "notice_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "proceeding_ref": "D-2025-01",
        "effective_start": NS1_WINDOW_START,
        "effective_end": NS1_WINDOW_END,
        "rate_per_performance_microcents": NS1_RATE_MICROCENTS,
        "min_fee_cents": NS1_MIN_FEE_CENTS,
        "category": NS1_CATEGORY,
    }
    defaults.update(overrides)
    return defaults


def create_rate_proceeding_payload(**overrides) -> dict:
    defaults = {"docket_no": "DKT-2026-01"}
    defaults.update(overrides)
    return defaults


def create_usage_report_payload(licensee_id, **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_play_line_payload(**overrides) -> dict:
    defaults = {
        "isrc": "NO-SUCH-ISRC",
        "track_title": "Test Track",
        "artist_name": "Test Artist",
        "performance_count": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_recording_payload(rights_owner_id, featured_artist_id, **overrides) -> dict:
    defaults = {
        "isrc": "ISRC-TEST-0001",
        "track_title": "Catalog Track",
        "rights_owner_id": rights_owner_id,
        "featured_artist_id": featured_artist_id,
    }
    defaults.update(overrides)
    return defaults


def create_artist_payload(**overrides) -> dict:
    defaults = {
        "stage_name": "Test Stage Name",
        "contact_email": "artist@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_rights_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Label LLC",
        "contact_email": "label@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_ownership_claim_payload(claimant_id, **overrides) -> dict:
    defaults = {
        "claimant_type": "RIGHTS_OWNER",
        "claimant_id": claimant_id,
        "claimed_share_pct": 100,
    }
    defaults.update(overrides)
    return defaults


def create_unclaimed_pool_payload(**overrides) -> dict:
    defaults = {
        "period_start": POOL_WINDOW_START,
        "period_end": POOL_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(**overrides) -> dict:
    defaults = {
        "auditor_ref": "AUD-001",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
