"""Payload factories — one per creatable entity, input fields only.

Factories never include system-managed fields (``id``, ``created_at``,
``updated_at``, ``version``) and never include computed or status fields;
those belong to the server.
"""

import itertools

_seq = itertools.count(1)


def _n():
    return next(_seq)


DEFAULTS = {
    "CYCLE_START": "2026-09-01T00:00:00Z",
    "CYCLE_END": "2026-12-01T00:00:00Z",
    "HIRE_DATE": "2021-01-01T00:00:00Z",
    "LOT_EXPIRATION": "2027-06-01T00:00:00Z",
    "TEMP_MIN_C": 2.0,
    "TEMP_MAX_C": 8.0,
}


def create_region_payload(**overrides):
    payload = {
        "region_code": "R-{0:04d}".format(_n()),
        "name": "Region {0}".format(_n()),
    }
    payload.update(overrides)
    return payload


def create_territory_payload(**overrides):
    payload = {
        "territory_code": "T-{0:04d}".format(_n()),
        "name": "Territory {0}".format(_n()),
        "cycle_start_date": DEFAULTS["CYCLE_START"],
        "cycle_end_date": DEFAULTS["CYCLE_END"],
        "cycle_sample_budget_units": 100,
    }
    payload.update(overrides)
    return payload


def create_representative_payload(**overrides):
    n = _n()
    payload = {
        "employee_id": "E-{0:05d}".format(n),
        "full_name": "Rep {0}".format(n),
        "hire_date": DEFAULTS["HIRE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_prescriber_payload(**overrides):
    n = _n()
    payload = {
        "npi_number": "{0:010d}".format(1000000000 + n),
        "full_name": "Dr. {0}".format(n),
        "state_license_number": "ST-{0:05d}".format(n),
        "specialty_code": "207Q00000X",
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides):
    n = _n()
    payload = {
        "ndc_code": "0006-{0:04d}".format(n),
        "brand_name": "Brand{0}".format(n),
        "controlled": False,
        "per_visit_max_units": 10,
        "annual_max_units_per_prescriber": 100,
        "storage_temp_min_c": DEFAULTS["TEMP_MIN_C"],
        "storage_temp_max_c": DEFAULTS["TEMP_MAX_C"],
    }
    payload.update(overrides)
    return payload


def create_sample_lot_payload(**overrides):
    n = _n()
    payload = {
        "lot_number": "LOT-{0:05d}".format(n),
        "expiration_date": DEFAULTS["LOT_EXPIRATION"],
        "quantity_received": 100,
    }
    payload.update(overrides)
    return payload


def issue_lot_balance_payload(lot_id, quantity, **overrides):
    payload = {"lot_id": lot_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_target_list_entry_payload(prescriber_id, product_id, **overrides):
    payload = {
        "prescriber_id": prescriber_id,
        "product_id": product_id,
        "tier": "B",
        "planned_sample_units": 20,
    }
    payload.update(overrides)
    return payload


def create_call_plan_payload(territory_id, expected_territory_version, **overrides):
    payload = {
        "territory_id": territory_id,
        "cycle_label": "2026-Q4",
        "expected_territory_version": expected_territory_version,
    }
    payload.update(overrides)
    return payload


def create_call_visit_payload(call_plan_id, target_list_entry_id, **overrides):
    payload = {
        "call_plan_id": call_plan_id,
        "target_list_entry_id": target_list_entry_id,
        # Scheduled before the default clock's instant so the visit can be
        # completed at server-start time without advancing the clock.
        "scheduled_start": "2026-08-31T08:00:00Z",
        "scheduled_end": "2026-08-31T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sample_disbursement_payload(call_visit_id, lot_id, quantity, **overrides):
    payload = {
        "call_visit_id": call_visit_id,
        "lot_id": lot_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_sample_transfer_payload(
    to_rep_id, lot_id, quantity, expected_lot_version, **overrides
):
    payload = {
        "to_rep_id": to_rep_id,
        "lot_id": lot_id,
        "quantity": quantity,
        "reason_code": "REBALANCE",
        "documentation_note": "Transfer documentation note (>= 20 chars)",
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_count_session_payload(representative_id, counter_rep_id, **overrides):
    payload = {
        "representative_id": representative_id,
        "counter_rep_id": counter_rep_id,
        "window_start": "2026-09-05T00:00:00Z",
        "window_end": "2026-09-06T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def submit_count_payload(lines, **overrides):
    payload = {"lines": lines}
    payload.update(overrides)
    return payload


def create_temperature_excursion_payload(product_id, **overrides):
    payload = {
        "product_id": product_id,
        "location_type": "VEHICLE",
        "observed_temp_c": 9.0,
        "excursion_minutes": 10,
    }
    payload.update(overrides)
    return payload


def create_sample_return_payload(lot_id, quantity, **overrides):
    payload = {
        "lot_id": lot_id,
        "quantity": quantity,
        "return_reason": "DAMAGED",
        "destruction_method": "INCINERATION",
    }
    payload.update(overrides)
    return payload
