"""Payload factories — one per resource, input fields only."""

GRAZIER_DEFAULTS = {
    "business_name": "Bitterroot Custom Grazing",
    "state_code": "MT",
    "liability_carrier": "Farm Mutual",
}

CATTLE_OWNER_DEFAULTS = {
    "legal_name": "Sixteen Mile Cattle Co",
    "state_code": "MT",
    "brand_registration": "MT-4471",
    "credit_limit_cents": 5_000_000,
}

RANGE_CONSULTANT_DEFAULTS = {
    "full_name": "Dana Reyes",
    "certification_number": "RC-1102",
    "state_code": "MT",
}

# North Bench: 1200 acres rated by DRY_MATTER at 1800 lb/acre and 25 percent
# utilization -> rated_aum 683.54 and rated_head_days 20769.
NORTH_BENCH_DEFAULTS = {
    "name": "North Bench",
    "acres": 1200,
    "forage_type": "NATIVE_RANGE",
    "water_source_type": "WELL",
    "fence_class": "CLASS_B",
    "prior_season_head_days": 5000,
}

DRY_MATTER_ASSESSMENT_DEFAULTS = {
    "method": "DRY_MATTER",
    "forage_dry_matter_lbs_per_acre": 1800,
    "utilization_pct": 25,
    "assessment_date": "2026-07-15",
}

# Contract K1: per-pound-of-gain at 85 cents with a 3.5 percent pencil shrink.
CONTRACT_DEFAULTS = {
    "billing_mode": "PER_POUND_OF_GAIN",
    "rate_cents": 85,
    "shrink_pct": 3.5,
    "out_shrink_pct": 0,
    "head_count_committed": 150,
    "head_value_cents": 140000,
    "start_date": "2026-08-10",
    "end_date": "2026-11-10",
    "min_days": 60,
    "treatment_cost_split_pct": 33,
    "water_responsibility": "SHARED",
    "fence_responsibility": "GRAZIER",
    "infrastructure_owner_cap_cents": 100000,
    "death_loss_terms": "GRAZIER_SHARE_ABOVE_THRESHOLD",
    "death_loss_threshold_pct": 2.0,
}

LOT_DEFAULTS = {
    "scheduled_head_count": 150,
    "scheduled_delivery_date": "2026-08-10",
}

RECEIVE_DEFAULTS = {
    "head_count_received": 150,
    "gross_weight_lbs": 63745,
    "scale_ticket_ref": "T-1001",
    "received_at": "2026-08-10T09:00:00Z",
}

OUT_WEIGHT_DEFAULTS = {
    "event_type": "OUT",
    "gross_weight_lbs": 74970,
    "head_count": 150,
    "scale_ticket_ref": "T-2001",
    "weighed_at": "2026-11-10T09:00:00Z",
}

TREATMENT_DEFAULTS = {
    "protocol_code": "BRD-A",
    "classification": "ROUTINE_PROTOCOL",
    "treatment_date": "2026-08-20",
    "withdrawal_days": 21,
    "head_treated": 12,
    "drug_cost_cents": 1250,
    "labor_cost_cents": 375,
}

DEATH_LOSS_DEFAULTS = {
    "death_date": "2026-08-20",
    "head_lost": 2,
    "cause": "DISEASE",
    "necropsy_performed": False,
}

TICKET_DEFAULTS = {
    "asset_type": "WATER",
    "severity": "MAJOR",
    "description": "Well pump seal leaking at the stock tank",
    "reported_at": "2026-09-10T08:00:00Z",
}

DROUGHT_READING_DEFAULTS = {
    "reading_date": "2026-09-01",
    "drought_index": 3,
    "forage_remaining_pct": 45,
}


def _merge(defaults: dict, overrides: dict) -> dict:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


def grazier_payload(**overrides) -> dict:
    return _merge(GRAZIER_DEFAULTS, overrides)


def cattle_owner_payload(**overrides) -> dict:
    return _merge(CATTLE_OWNER_DEFAULTS, overrides)


def range_consultant_payload(**overrides) -> dict:
    return _merge(RANGE_CONSULTANT_DEFAULTS, overrides)


def pasture_payload(**overrides) -> dict:
    return _merge(NORTH_BENCH_DEFAULTS, overrides)


def capacity_assessment_payload(expected_pasture_version: int, **overrides) -> dict:
    payload = _merge(DRY_MATTER_ASSESSMENT_DEFAULTS, overrides)
    payload["expected_pasture_version"] = expected_pasture_version
    return payload


def contract_payload(cattle_owner_id: str, pasture_id: str, **overrides) -> dict:
    payload = _merge(CONTRACT_DEFAULTS, overrides)
    payload["cattle_owner_id"] = cattle_owner_id
    payload["pasture_id"] = pasture_id
    return payload


def lot_payload(**overrides) -> dict:
    return _merge(LOT_DEFAULTS, overrides)


def receive_payload(**overrides) -> dict:
    return _merge(RECEIVE_DEFAULTS, overrides)


def out_weight_payload(**overrides) -> dict:
    return _merge(OUT_WEIGHT_DEFAULTS, overrides)


def interim_weight_payload(**overrides) -> dict:
    defaults = dict(OUT_WEIGHT_DEFAULTS, event_type="INTERIM")
    return _merge(defaults, overrides)


def treatment_payload(**overrides) -> dict:
    return _merge(TREATMENT_DEFAULTS, overrides)


def death_loss_payload(**overrides) -> dict:
    return _merge(DEATH_LOSS_DEFAULTS, overrides)


def infrastructure_ticket_payload(pasture_id: str, contract_id: str, **overrides) -> dict:
    payload = _merge(TICKET_DEFAULTS, overrides)
    payload["pasture_id"] = pasture_id
    payload["contract_id"] = contract_id
    return payload


def drought_reading_payload(**overrides) -> dict:
    return _merge(DROUGHT_READING_DEFAULTS, overrides)


def settlement_payload(contract_id: str, lot_id: str, expected_contract_version: int) -> dict:
    return {
        "contract_id": contract_id,
        "lot_id": lot_id,
        "expected_contract_version": expected_contract_version,
    }
