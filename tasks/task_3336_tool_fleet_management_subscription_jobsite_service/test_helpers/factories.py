"""Payload factories — one per creatable entity, input fields only."""

_ACCOUNT_SEQ = [0]


def _uniq() -> str:
    """Process-unique suffix for factory-generated identifiers."""
    import itertools
    global _UNIQ_COUNTER
    try:
        _UNIQ_COUNTER
    except NameError:
        _UNIQ_COUNTER = itertools.count()
    return f"{next(_UNIQ_COUNTER):x}"


def create_account_payload(**overrides) -> dict:
    _ACCOUNT_SEQ[0] += 1
    n = _ACCOUNT_SEQ[0]
    defaults = {
        "company_name": f"Test Co {n}",
        "tax_id": f"EIN-TEST-{n}-{_uniq()}",
        "credit_limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    _ACCOUNT_SEQ[0] += 1
    n = _ACCOUNT_SEQ[0]
    defaults = {
        "code": f"RC-TEST-{n}-{_uniq()}",
        "tool_category": "DRILL",
        "base_monthly_rate_cents": 5000,
        "tier2_threshold": 100,
        "tier2_monthly_rate_cents": 5000,
        "tier3_threshold": 200,
        "tier3_monthly_rate_cents": 5000,
        "min_monthly_fee_cents": 0,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tool_model_payload(**overrides) -> dict:
    _ACCOUNT_SEQ[0] += 1
    n = _ACCOUNT_SEQ[0]
    defaults = {
        "model_code": f"TM-TEST-{n}-{_uniq()}",
        "category": "DRILL",
        "replacement_value_cents": 80000,
        "weight_class": "LIGHT",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "term_months": 12,
        "start_date": "2026-09-01T00:00:00Z",
        "end_of_term_option": "RETURN",
    }
    defaults.update(overrides)
    return defaults


def create_jobsite_payload(**overrides) -> dict:
    _ACCOUNT_SEQ[0] += 1
    n = _ACCOUNT_SEQ[0]
    defaults = {
        "name": f"Site {n}",
        "address": f"{n} Way",
        "capacity_assets": 10,
        "geofence_radius_m": 500,
    }
    defaults.update(overrides)
    return defaults


def create_loaner_unit_payload(tool_model_id, **overrides) -> dict:
    _ACCOUNT_SEQ[0] += 1
    n = _ACCOUNT_SEQ[0]
    defaults = {
        "tool_model_id": tool_model_id,
        "serial_number": f"LN-TEST-{n}-{_uniq()}",
    }
    defaults.update(overrides)
    return defaults


def create_consumable_product_payload(**overrides) -> dict:
    _ACCOUNT_SEQ[0] += 1
    n = _ACCOUNT_SEQ[0]
    defaults = {
        "sku": f"SKU-TEST-{n}-{_uniq()}",
        "name": f"Product {n}",
        "unit_price_cents": 500,
        "pack_size": 10,
        "requires_application_approval": False,
    }
    defaults.update(overrides)
    return defaults


def create_support_case_payload(jobsite_id, **overrides) -> dict:
    defaults = {
        "kind": "ANCHOR_DESIGN",
        "jobsite_id": jobsite_id,
        "scheduled_for": "2026-09-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(**overrides) -> dict:
    defaults = {
        "started_at": "2026-09-01T08:00:00Z",
        "ended_at": "2026-09-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults
