"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid

DEFAULTS = {
    "SUPPLIER_NAME": "Test Supplier",
    "COUNTRY_CODE": "US",
    "INGREDIENT_CATEGORY": "DAIRY",
    "CERT_ISSUED_AT": "2026-01-01T00:00:00Z",
    "CERT_VALID_UNTIL": "2027-06-01T00:00:00Z",
    "COMMITMENT_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "COMMITMENT_EFFECTIVE_TO": "2027-01-01T00:00:00Z",
    "AUDIT_SCHEDULED_FOR": "2026-09-05T00:00:00Z",
    "BASELINE_VOLUME_LITERS": 8000,
    "SEASON_YEAR": 2026,
    "DECLARED_VOLUME_LITERS": 10000,
    "COMMODITY_PRICE_CENTS_PER_LITER": 45,
    "PINT_PRICE_CENTS": 150,
    "PRODUCTION_DATE": "2026-10-05",
    "PLANNED_PINTS": 500,
    "CREDIT_LIMIT_CENTS": 10_000_000,
}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("supplier"),
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "ingredient_category": DEFAULTS["INGREDIENT_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(expected_supplier_version, **overrides) -> dict:
    defaults = {
        "ingredient_category": DEFAULTS["INGREDIENT_CATEGORY"],
        "fair_trade_required": True,
        "min_social_score": 60,
        "premium_over_commodity_pct": 5,
        "effective_from": DEFAULTS["COMMITMENT_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["COMMITMENT_EFFECTIVE_TO"],
        "expected_supplier_version": expected_supplier_version,
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "scheme": "FAIR_TRADE",
        "certificate_number": _uniq("cert"),
        "ingredient_scope": "DAIRY",
        "issued_at": DEFAULTS["CERT_ISSUED_AT"],
        "valid_until": DEFAULTS["CERT_VALID_UNTIL"],
        "declared_coverage_pct": 95,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"scheduled_for": DEFAULTS["AUDIT_SCHEDULED_FOR"]}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {
        "farm_name": _uniq("farm"),
        "region": "VT",
        "herd_size": 80,
        "season_year": DEFAULTS["SEASON_YEAR"],
        "baseline_volume_liters": DEFAULTS["BASELINE_VOLUME_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_premium_payment_payload(**overrides) -> dict:
    defaults = {
        "period": "Q1",
        "declared_volume_liters": DEFAULTS["DECLARED_VOLUME_LITERS"],
        "commodity_price_cents_per_liter": DEFAULTS["COMMODITY_PRICE_CENTS_PER_LITER"],
    }
    defaults.update(overrides)
    return defaults


def create_flavor_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("flavor"),
        "base_type": "DAIRY",
        "chunk_load_pct": 5,
        "swirl_load_pct": 5,
        "pint_price_cents": DEFAULTS["PINT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_revival_request_payload(**overrides) -> dict:
    defaults = {
        "fan_email": f"fan-{uuid.uuid4().hex[:8]}@example.com",
        "title": _uniq("revive"),
    }
    defaults.update(overrides)
    return defaults


def create_production_slot_payload(flavor_id, **overrides) -> dict:
    defaults = {
        "plant_code": "VT_WATERBURY",
        "flavor_id": flavor_id,
        "production_date": DEFAULTS["PRODUCTION_DATE"],
        "shift": "DAY",
        "planned_pints": DEFAULTS["PLANNED_PINTS"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "title": _uniq("campaign"),
        "issue_area": "CLIMATE",
        "retail_partner_impact": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_scoop_shop_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("shop"),
        "operator_type": "FRANCHISEE",
        "city": "Burlington",
        "country_code": "US",
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_order_payload(lines, **overrides) -> dict:
    defaults = {
        "production_date": DEFAULTS["PRODUCTION_DATE"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults
