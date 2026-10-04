"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "program_code": f"G-{n:04d}",
        "program_name": f"Program {n}",
        "outreach_mode": "PUSH",
        "measure_year": TEST_DEFAULTS["MEASURE_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "external_ref": f"p-{n:04d}",
        "date_of_birth": TEST_DEFAULTS["DOB_ADULT"],
        "risk_category": "AVERAGE",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "npi": f"{1_000_000_000 + n:010d}",
        "display_name": f"Dr {n}",
        "channel": "ORDERING",
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(patient_id, **overrides) -> dict:
    defaults = {"patient_id": patient_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(patient_id, provider_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
    }
    defaults.update(overrides)
    return defaults


def create_kit_payload(expected_order_version, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def create_outreach_payload(**overrides) -> dict:
    defaults = {"channel": "MAIL", "template_code": "T1"}
    defaults.update(overrides)
    return defaults


def create_adequacy_payload(adequacy="ADEQUATE", **overrides) -> dict:
    defaults = {"adequacy": adequacy}
    defaults.update(overrides)
    return defaults


def create_result_payload(outcome="NEGATIVE", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults
