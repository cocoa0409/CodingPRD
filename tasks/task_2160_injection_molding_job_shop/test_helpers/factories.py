"""Payload factories -- one per entity, carrying only caller-supplied fields."""

from .constants import TEST_DEFAULTS as D


def create_customer_payload(**overrides) -> dict:
    payload = {"name": D["CUSTOMER_NAME"], "code": D["CUSTOMER_CODE"]}
    payload.update(overrides)
    return payload


def create_press_payload(**overrides) -> dict:
    payload = {
        "press_code": D["PRESS_CODE"],
        "tonnage": D["PRESS_TONNAGE"],
        "shot_size_grams_max": D["PRESS_SHOT_SIZE_GRAMS_MAX"],
        "hourly_rate_cents": D["PRESS_HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_mold_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "mold_code": D["MOLD_CODE"],
        "customer_id": customer_id,
        "cavity_count": D["MOLD_CAVITY_COUNT"],
        "shot_weight_grams": D["MOLD_SHOT_WEIGHT_GRAMS"],
        "required_min_tonnage": D["MOLD_MIN_TONNAGE"],
        "required_max_tonnage": D["MOLD_MAX_TONNAGE"],
        "pm_interval_shots": D["MOLD_PM_INTERVAL_SHOTS"],
        "tooling_cost_cents": D["MOLD_TOOLING_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_press_qualification_payload(mold_id: str, press_id: str, **overrides) -> dict:
    payload = {"mold_id": mold_id, "press_id": press_id}
    payload.update(overrides)
    return payload


def schedule_run_at_rate_payload(**overrides) -> dict:
    payload = {
        "scheduled_start": D["TRIAL_START"],
        "scheduled_end": D["TRIAL_END"],
        "target_parts_per_hour": D["TRIAL_TARGET_PARTS_PER_HOUR"],
    }
    payload.update(overrides)
    return payload


def create_quote_payload(customer_id: str, mold_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "mold_id": mold_id,
        "part_weight_grams": D["QUOTE_PART_WEIGHT_GRAMS"],
        "cycle_time_sec": D["QUOTE_CYCLE_TIME_SEC"],
        "cavitation": D["QUOTE_CAVITATION"],
        "resin_grade": D["QUOTE_RESIN_GRADE"],
        "resin_price_cents_per_kg": D["QUOTE_RESIN_PRICE_CENTS_PER_KG"],
        "annual_volume": D["QUOTE_ANNUAL_VOLUME"],
    }
    payload.update(overrides)
    return payload


def create_ppap_submission_payload(mold_id: str, quote_id: str, **overrides) -> dict:
    payload = {
        "mold_id": mold_id,
        "quote_id": quote_id,
        "level": D["PPAP_LEVEL"],
        "max_regrind_bp": D["PPAP_MAX_REGRIND_BP"],
    }
    payload.update(overrides)
    return payload


def submit_ppap_payload(**overrides) -> dict:
    payload = {
        "fai_dimensional_pass": True,
        "fai_sample_shots": D["PPAP_FAI_SAMPLE_SHOTS"],
    }
    payload.update(overrides)
    return payload


def create_resin_lot_payload(**overrides) -> dict:
    payload = {
        "resin_grade": D["QUOTE_RESIN_GRADE"],
        "supplier_lot_code": D["LOT_CODE"],
        "qty_kg_received": D["LOT_QTY_KG"],
        "moisture_bp": D["LOT_MOISTURE_BP"],
    }
    payload.update(overrides)
    return payload


def create_production_job_payload(quote_id: str, **overrides) -> dict:
    payload = {
        "quote_id": quote_id,
        "planned_qty": D["JOB_PLANNED_QTY"],
        "scheduled_start": D["JOB_START"],
        "scheduled_end": D["JOB_END"],
    }
    payload.update(overrides)
    return payload


def create_production_report_payload(job_id: str, expected_job_version: int, **overrides) -> dict:
    """A conserving 1,000-shot line against a four-cavity tool.

    good_parts + scrap_parts == shots * cavity_count == 4000, and scrap_parts
    (40) is at or above short_shot_shots (5) * cavity_count (4) == 20.
    """
    payload = {
        "job_id": job_id,
        "shots": 1000,
        "short_shot_shots": 5,
        "good_parts": 3960,
        "scrap_parts": 40,
        "virgin_grams": 36000,
        "regrind_grams": 4000,
        "run_minutes": 600,
        "expected_job_version": expected_job_version,
    }
    payload.update(overrides)
    return payload


def create_maintenance_order_payload(mold_id: str, **overrides) -> dict:
    payload = {
        "mold_id": mold_id,
        "kind": "PM",
        "window_start": "2026-09-20T08:00:00Z",
        "window_end": "2026-09-20T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_tool_transfer_payload(mold_id: str, to_customer_id: str, **overrides) -> dict:
    payload = {
        "mold_id": mold_id,
        "to_customer_id": to_customer_id,
        "settlement_cents": 2000000,
    }
    payload.update(overrides)
    return payload


def create_capacity_commit_payload(customer_id: str, press_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "press_id": press_id,
        "window_start": "2026-09-15T00:00:00Z",
        "window_end": "2026-09-16T00:00:00Z",
        "committed_minutes": 600,
        "shortfall_policy": "STRICT",
    }
    payload.update(overrides)
    return payload
