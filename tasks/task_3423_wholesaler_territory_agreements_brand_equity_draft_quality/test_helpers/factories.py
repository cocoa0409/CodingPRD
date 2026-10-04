"""Payload factories — one per entity, input fields only.

Every factory accepts ``**overrides`` so tests can steer the values their
claim cares about while defaults keep the payload valid.
"""

DEFAULTS = {
    "TERRITORY_NAME": "Test Territory",
    "STATE_CODE": "TX",
    "LEGAL_NAME": "Test Distributing",
    "LICENSE_PREFIX": "TX-W",
    "TIER": "SILVER",
    "SCORE": 75,
    "BRAND_SCOPE": ["BUD"],
    "DIST_TARGET": 80,
    "FRESH_TARGET": 90,
    "SHARE_TARGET": 40,
    "DECLARED_DIST": 80,
    "DECLARED_FRESH": 95,
    "DECLARED_SHARE": 40,
    "TERM_YEARS": 5,
    "PURCHASE_PRICE_CENTS": 1_000_000,
    "REVIEW_DIST": 80,
    "REVIEW_SHARE": 40,
    "ACCOUNT_NAME": "Test Bar",
    "TOTAL_QTY": 400,
    "ITEM_DESCRIPTION": "neon sign",
    "SUGGESTED_DISCOUNT_PCT": 5,
}

_license_counter = [10000]


def _next_license() -> str:
    _license_counter[0] += 1
    return f"{DEFAULTS['LICENSE_PREFIX']}-{_license_counter[0]}"


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TERRITORY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_wholesaler_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "home_state": DEFAULTS["STATE_CODE"],
        "license_number": _next_license(),
        "tier": DEFAULTS["TIER"],
        "financial_capacity_score": DEFAULTS["SCORE"],
        "warehouse_capacity_score": DEFAULTS["SCORE"],
        "market_coverage_score": DEFAULTS["SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(territory_id: str, wholesaler_id: str, **overrides) -> dict:
    defaults = {
        "territory_id": territory_id,
        "wholesaler_id": wholesaler_id,
        "brand_scope": list(DEFAULTS["BRAND_SCOPE"]),
        "distribution_target_pct": DEFAULTS["DIST_TARGET"],
        "freshness_target_index": DEFAULTS["FRESH_TARGET"],
        "share_target_pct": DEFAULTS["SHARE_TARGET"],
        "declared_distribution_pct": DEFAULTS["DECLARED_DIST"],
        "declared_freshness_index": DEFAULTS["DECLARED_FRESH"],
        "declared_share_pct": DEFAULTS["DECLARED_SHARE"],
        "term_years": DEFAULTS["TERM_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(agreement_id: str, buyer_wholesaler_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "buyer_wholesaler_id": buyer_wholesaler_id,
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(wholesaler_id: str, **overrides) -> dict:
    defaults = {
        "wholesaler_id": wholesaler_id,
        "period_year": 2026,
        "period_quarter": "Q3",
        "distribution_pct": DEFAULTS["REVIEW_DIST"],
        "share_pct": DEFAULTS["REVIEW_SHARE"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_event_payload(**overrides) -> dict:
    defaults = {
        "brand_code": "BUD-LTD",
        "total_qty_cases": DEFAULTS["TOTAL_QTY"],
    }
    defaults.update(overrides)
    return defaults


def create_retail_account_payload(serving_wholesaler_id: str, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ACCOUNT_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "serving_wholesaler_id": serving_wholesaler_id,
    }
    defaults.update(overrides)
    return defaults


def create_draft_audit_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "conducted_at": "2026-09-01T00:00:00Z",
        "line_cleaning_last_at": "2026-08-28T00:00:00Z",
        "kegs": [
            {"brand_code": "BUD", "filled_at": "2026-08-25T00:00:00Z", "volume_bbl": 10}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_pos_grant_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "item_description": DEFAULTS["ITEM_DESCRIPTION"],
        "value_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_promotion_payload(**overrides) -> dict:
    defaults = {
        "brand_code": "BUD",
        "starts_at": "2026-10-01T00:00:00Z",
        "ends_at": "2026-11-01T00:00:00Z",
        "suggested_discount_pct": DEFAULTS["SUGGESTED_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def critical_keg(filled_at: str = "2026-05-03T00:00:00Z", volume_bbl=15, brand="BUD") -> dict:
    """A keg whose age at 2026-09-01 is 121 days (>= 120 -> critical)."""
    return {"brand_code": brand, "filled_at": filled_at, "volume_bbl": volume_bbl}


def fresh_keg(filled_at: str = "2026-08-25T00:00:00Z", volume_bbl=10, brand="BUD") -> dict:
    """A keg whose age at 2026-09-01 is 7 days (fresh)."""
    return {"brand_code": brand, "filled_at": filled_at, "volume_bbl": volume_bbl}
