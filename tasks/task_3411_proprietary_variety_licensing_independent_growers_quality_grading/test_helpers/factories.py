"""Payload factories — one per creatable entity/action, input fields only."""

DEFAULTS = {
    "VARIETY_CODE": "BRB-STR-01",
    "VARIETY_NAME": "Cielo Rojo",
    "BERRY_TYPE": "STRAWBERRY",
    "LEGAL_NAME": "Mesa Verde Farms",
    "REGION": "CA-SALINAS",
    "MAX_PLANTING_UNITS": 100000,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-12-31T00:00:00Z",
    "NURSERY_CODE": "NUR-CA-01",
    "QUANTITY_PLANTS": 2000,
    "PLANNED_PLANTS": 1500,
    "PLANTS_ACTUAL": 1500,
    "TARGET_VOLUME_KG": 10000,
    "GROSS_WEIGHT_KG": 1200,
    "TARE_WEIGHT_KG": 50,
    "ESTIMATED_PRICE": 500,
    "ACTUAL_PRICE": 520,
    "REASON": "field resistance failure",
    "DESTROY_BEFORE": "2026-11-15T00:00:00Z",
}


def create_variety_payload(**overrides) -> dict:
    d = {"variety_code": DEFAULTS["VARIETY_CODE"],
         "berry_type": DEFAULTS["BERRY_TYPE"],
         "name": DEFAULTS["VARIETY_NAME"]}
    d.update(overrides)
    return d


def release_variety_payload() -> dict:
    return {}


def recall_variety_payload(**overrides) -> dict:
    d = {"reason": DEFAULTS["REASON"], "destroy_before": DEFAULTS["DESTROY_BEFORE"]}
    d.update(overrides)
    return d


def create_grower_payload(**overrides) -> dict:
    d = {"legal_name": DEFAULTS["LEGAL_NAME"], "region_code": DEFAULTS["REGION"]}
    d.update(overrides)
    return d


def suspend_grower_payload(**overrides) -> dict:
    return dict(overrides)


def create_agreement_payload(grower_id, variety_id, **overrides) -> dict:
    d = {"grower_id": grower_id,
         "variety_id": variety_id,
         "region_code": DEFAULTS["REGION"],
         "max_planting_units": DEFAULTS["MAX_PLANTING_UNITS"],
         "cultural_practice_codes": ["ORGANIC", "DRIP_IRRIGATION"],
         "effective_from": DEFAULTS["EFFECTIVE_FROM"],
         "effective_to": DEFAULTS["EFFECTIVE_TO"],
         "exclusive_marketing": True}
    d.update(overrides)
    return d


def decide_agreement_payload(decision="APPROVE", **overrides) -> dict:
    d = {"decision": decision}
    d.update(overrides)
    return d


def create_plant_lot_payload(agreement_id, variety_id, **overrides) -> dict:
    d = {"nursery_code": DEFAULTS["NURSERY_CODE"],
         "agreement_id": agreement_id,
         "variety_id": variety_id,
         "quantity_plants": DEFAULTS["QUANTITY_PLANTS"]}
    d.update(overrides)
    return d


def create_planting_payload(agreement_id, plant_lot_id, expected_agreement_version,
                            **overrides) -> dict:
    d = {"agreement_id": agreement_id,
         "plant_lot_id": plant_lot_id,
         "planned_plants": DEFAULTS["PLANNED_PLANTS"],
         "expected_agreement_version": expected_agreement_version}
    d.update(overrides)
    return d


def confirm_planting_payload(**overrides) -> dict:
    d = {"plants_planted_actual": DEFAULTS["PLANTS_ACTUAL"],
         "planted_on": "2026-08-01T00:00:00Z"}
    d.update(overrides)
    return d


def create_harvest_window_payload(variety_id, **overrides) -> dict:
    d = {"region_code": DEFAULTS["REGION"],
         "variety_id": variety_id,
         "week_start": "2026-09-28T00:00:00Z",
         "week_end": "2026-10-05T00:00:00Z",
         "target_volume_kg": DEFAULTS["TARGET_VOLUME_KG"]}
    d.update(overrides)
    return d


def create_harvest_lot_payload(planting_id, expected_planting_version,
                               **overrides) -> dict:
    d = {"planting_id": planting_id,
         "harvested_at": "2026-10-06T06:00:00Z",
         "gross_weight_kg": DEFAULTS["GROSS_WEIGHT_KG"],
         "expected_planting_version": expected_planting_version}
    d.update(overrides)
    return d


def receive_lot_payload(**overrides) -> dict:
    d = {"received_at": "2026-10-06T12:00:00Z", "pulp_temp_c_at_receipt": 3.5}
    d.update(overrides)
    return d


def grade_payload(**overrides) -> dict:
    """Defaults grade PREMIUM."""
    d = {"flavor_brix": 12.0, "firmness_g": 400,
         "appearance_score": 90, "defect_pct": 1.0}
    d.update(overrides)
    return d


def dispute_grade_payload(**overrides) -> dict:
    d = {"reason": "firmness gauge miscalibrated"}
    d.update(overrides)
    return d


def create_pool_payload(**overrides) -> dict:
    d = {"berry_type": DEFAULTS["BERRY_TYPE"],
         "week_start": "2026-10-05T00:00:00Z",
         "week_end": "2026-10-12T00:00:00Z",
         "is_shoulder_week": False}
    d.update(overrides)
    return d


def close_pool_payload(**overrides) -> dict:
    d = {"estimated_price_cents_per_kg": DEFAULTS["ESTIMATED_PRICE"]}
    d.update(overrides)
    return d


def settle_pool_payload(**overrides) -> dict:
    d = {"actual_price_cents_per_kg": DEFAULTS["ACTUAL_PRICE"]}
    d.update(overrides)
    return d


def dispute_statement_payload(**overrides) -> dict:
    d = {"reason": "cold-chain deduction misapplied"}
    d.update(overrides)
    return d


def resolve_statement_payload(resolution="UPHOLD", **overrides) -> dict:
    d = {"resolution": resolution}
    d.update(overrides)
    return d


def set_clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
