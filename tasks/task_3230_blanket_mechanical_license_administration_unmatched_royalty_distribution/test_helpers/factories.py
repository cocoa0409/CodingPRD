"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS, ROUTING_VALID

_isrc_counter = [0]


def next_isrc() -> str:
    """Generate a well-formed unique ISRC (2 letters, 3 alphanumeric, 7 digits)."""
    _isrc_counter[0] += 1
    return "USAA1" + f"{_isrc_counter[0]:07d}"


def create_service_provider_payload(**overrides) -> dict:
    defaults = {"legal_name": TEST_DEFAULTS["DSP_LEGAL_NAME"]}
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["MEMBER_A_NAME"],
        "member_type": "PUBLISHER",
        "ipi_number": TEST_DEFAULTS["IPI_A"],
    }
    defaults.update(overrides)
    return defaults


def create_payee_payload(**overrides) -> dict:
    defaults = {
        "payee_legal_name": "Alder Publishing LLC",
        "payment_method": "ACH",
        "routing_number": ROUTING_VALID,
        "account_number": TEST_DEFAULTS["ACCOUNT_NUMBER"],
        "tax_id": TEST_DEFAULTS["TAX_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_work_payload(**overrides) -> dict:
    defaults = {"title": "Kestrel"}
    defaults.update(overrides)
    return defaults


def create_share_payload(**overrides) -> dict:
    defaults = {
        "share_percent": 100,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "effective_from": "2026-01-01T00:00:00Z",
        "rate_cents_under_5min": 131,
        "rate_cents_per_minute_over_5min": 252,
    }
    defaults.update(overrides)
    return defaults


def create_usage_report_payload(**overrides) -> dict:
    defaults = {"reporting_month": "2026-06"}
    defaults.update(overrides)
    return defaults


def create_usage_line_payload(**overrides) -> dict:
    defaults = {
        "isrc": next_isrc(),
        "track_title": "Sora",
        "plays_count": 10,
        "duration_seconds": 100,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {"share_percent_claimed": 100}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"share_context": "contested 100% share"}
    defaults.update(overrides)
    return defaults


def create_cycle_run_payload(**overrides) -> dict:
    defaults = {
        "cycle_month": "2029-08",
        "pool_from_month": "2026-06",
        "pool_to_month": "2026-06",
        "methodology": "MARKET_SHARE_USAGE",
    }
    defaults.update(overrides)
    return defaults
