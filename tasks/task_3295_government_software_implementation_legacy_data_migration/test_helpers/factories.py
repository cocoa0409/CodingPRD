"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n():
    return next(_counter)


def agency_payload(**overrides):
    defaults = {
        "agency_code": TEST_DEFAULTS["AGENCY_CODE"],
        "display_name": TEST_DEFAULTS["AGENCY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def calendar_window_payload(**overrides):
    defaults = {
        "kind": "FISCAL_YEAR_END",
        "starts_on": "2026-12-20",
        "ends_on": "2026-12-31",
        "blackout": True,
        "description": "Fiscal year end freeze",
    }
    defaults.update(overrides)
    return defaults


def staff_payload(**overrides):
    n = _n()
    defaults = {
        "full_name": f"Staff {n}",
        "email": f"staff{n}@x.gov",
        "tenure_years": 1,
        "staff_function": "TRAINEE",
    }
    defaults.update(overrides)
    return defaults


def contract_payload(agency_id, **overrides):
    defaults = {
        "agency_id": agency_id,
        "solicitation_number": TEST_DEFAULTS["SOLICITATION_NUMBER"],
        "vendor_name": TEST_DEFAULTS["VENDOR_NAME"],
        "contract_value_cents": TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def phase_payload(sequence_no=1, **overrides):
    defaults = {
        "sequence_no": sequence_no,
        "name": f"PHASE-{sequence_no}",
        "planned_start_on": TEST_DEFAULTS["PHASE_START"],
        "planned_end_on": TEST_DEFAULTS["PHASE_END"],
    }
    defaults.update(overrides)
    return defaults


def milestone_payload(**overrides):
    defaults = {
        "code": f"M-{_n()}",
        "description": "milestone",
        "billable_amount_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def criterion_payload(**overrides):
    defaults = {
        "code": f"AC-{_n()}",
        "narrative": "criterion",
    }
    defaults.update(overrides)
    return defaults


def workflow_process_payload(**overrides):
    defaults = {
        "name": f"Process-{_n()}",
        "as_is_summary": "as-is",
        "to_be_summary": "to-be",
    }
    defaults.update(overrides)
    return defaults


def decision_payload(**overrides):
    defaults = {
        "decision_key": f"DK-{_n()}",
        "chosen_value": "v",
        "rationale": "r",
    }
    defaults.update(overrides)
    return defaults


def migration_batch_payload(**overrides):
    defaults = {
        "domain": "PROPERTY_TAX",
        "source_system_label": f"LEGACY-{_n()}",
        "expected_record_count": 1,
        "expected_net_value_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def record_payload(key=None, value=100, **overrides):
    defaults = {
        "legacy_primary_key": key if key is not None else f"R-{_n()}",
        "field_payload": {},
        "signed_value_cents": value,
    }
    defaults.update(overrides)
    return defaults


def interface_payload(**overrides):
    defaults = {
        "name": f"Iface-{_n()}",
        "direction": "OUTBOUND",
        "endpoint_kind": "STATE_SYSTEM",
    }
    defaults.update(overrides)
    return defaults


def certification_payload(**overrides):
    defaults = {
        "window_starts_on": "2026-09-01",
        "window_ends_on": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def uat_cycle_payload(**overrides):
    defaults = {"label": f"UAT-{_n()}"}
    defaults.update(overrides)
    return defaults


def uat_session_payload(tester_id, **overrides):
    defaults = {
        "scenario_code": f"S-{_n()}",
        "assigned_tester_id": tester_id,
        "scheduled_on": "2026-09-05",
    }
    defaults.update(overrides)
    return defaults


def training_session_payload(**overrides):
    defaults = {
        "title": f"Training {_n()}",
        "delivery_mode": "INSTRUCTOR_LED",
        "scheduled_on": "2026-10-01",
        "capacity": 3,
    }
    defaults.update(overrides)
    return defaults


def go_live_payload(**overrides):
    defaults = {"planned_date": TEST_DEFAULTS["GO_LIVE_DATE"]}
    defaults.update(overrides)
    return defaults


def ticket_payload(**overrides):
    defaults = {"severity": "SEV3", "summary": f"ticket {_n()}"}
    defaults.update(overrides)
    return defaults


def maintenance_payload(**overrides):
    defaults = {
        "annual_fee_cents": 12_000_000,
        "coverage_start_on": "2027-03-02",
    }
    defaults.update(overrides)
    return defaults
