"""Composite setup helpers.

These encapsulate the multi-step API sequences (clock setup, center and
schedule creation, donor registration, screening clearance, donation
pipeline steps) so tests can focus on assertions. All helpers use
get_success_data() so a setup failure raises a clear "Setup step failed"
error instead of a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    PASS_HEALTH_HISTORY,
    PASS_IDENTITY,
    create_center_payload,
    create_donation_payload,
    create_donor_payload,
    create_schedule_payload,
    create_screening_payload,
    physical_exam_payload,
    viral_marker_payload,
)
from .test_users import TEST_USERS, make_recorder_headers, make_screener_headers

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
PHLEBOTOMIST = TEST_USERS["phlebotomist_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    resp = api_client.set_clock(current_utc, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 / 2: centers, schedules, donors
# ---------------------------------------------------------------------------

def make_center(**overrides) -> dict:
    resp = api_client.create_center(create_center_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_schedule(center: dict, **overrides) -> dict:
    payload = create_schedule_payload(center["version"], **overrides)
    resp = api_client.create_schedule(center["id"], payload, ADMIN)
    return get_success_data(resp)


def make_center_with_schedule(center_overrides: dict = None, **schedule_overrides):
    """Center plus its ACTIVE compensation schedule. Returns (center, schedule).

    The returned center dict is re-fetched so its version reflects the
    schedule-creation bump.
    """
    center = make_center(**(center_overrides or {}))
    schedule = make_schedule(center, **schedule_overrides)
    center = get_success_data(api_client.get_center(center["id"], ADMIN))
    return center, schedule


def make_donor(center: dict, **overrides) -> dict:
    payload = create_donor_payload(center["id"], **overrides)
    resp = api_client.register_donor(payload, TEST_USERS["recorder_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: screening lifecycle
# ---------------------------------------------------------------------------

def make_screening(donor: dict, center: dict, scheduled_for: str) -> dict:
    resp = api_client.schedule_screening(
        donor["id"],
        create_screening_payload(center["id"], scheduled_for),
        TEST_USERS["recorder_headers"],
    )
    return get_success_data(resp)


def record_pass_sub_record(visit_id: str, record_type: str, recorder_id: str = "rec-01",
                           weight_kg: float = 72.5) -> dict:
    """Write one PASS sub-record of the given type."""
    if record_type == "IDENTITY":
        payload = dict(PASS_IDENTITY)
    elif record_type == "HEALTH_HISTORY":
        payload = dict(PASS_HEALTH_HISTORY)
    elif record_type == "PHYSICAL_EXAM":
        payload = physical_exam_payload(weight_kg=weight_kg)
    elif record_type == "VIRAL_MARKER":
        payload = viral_marker_payload()
    else:
        raise ValueError(record_type)
    resp = api_client.record_sub_record(
        visit_id,
        {"record_type": record_type, "payload": payload},
        make_recorder_headers(recorder_id),
    )
    return get_success_data(resp)


def make_cleared_screening(donor: dict, center: dict, scheduled_for: str,
                           recorder_id: str = "rec-01",
                           screener_id: str = "ms-01",
                           weight_kg: float = 72.5) -> dict:
    """Screening with all four PASS sub-records, cleared by a distinct screener."""
    visit = make_screening(donor, center, scheduled_for)
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM", "VIRAL_MARKER"):
        record_pass_sub_record(visit["id"], rt, recorder_id, weight_kg=weight_kg)
    resp = api_client.clear_screening(visit["id"], make_screener_headers(screener_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: donation lifecycle
# ---------------------------------------------------------------------------

def make_donation(donor: dict, center: dict, screening: dict, scheduled_for: str) -> dict:
    resp = api_client.schedule_donation(
        donor["id"],
        create_donation_payload(center["id"], screening["id"], scheduled_for),
        PHLEBOTOMIST,
    )
    return get_success_data(resp)


def check_in(visit_id: str) -> dict:
    return get_success_data(api_client.check_in(visit_id, PHLEBOTOMIST))


def complete_collection(visit_id: str, actual_volume_ml: int) -> dict:
    return get_success_data(
        api_client.complete_collection(
            visit_id, {"actual_volume_ml": actual_volume_ml}, PHLEBOTOMIST
        )
    )


def discharge(visit_id: str) -> dict:
    return get_success_data(api_client.discharge(visit_id, PHLEBOTOMIST))


def get_payment(visit_id: str) -> dict:
    """Return the single CompensationPayment row for a visit (must exist)."""
    data, meta = _get_payment_list(visit_id)
    assert meta["total_count"] == 1, f"expected exactly one payment, got {meta}"
    return data[0]


def _get_payment_list(visit_id: str):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.get_payment_for_visit(visit_id, ADMIN)
    return validate_paginated(resp)


def get_donor(donor_id: str) -> dict:
    return get_success_data(api_client.get_donor(donor_id, ADMIN))


def get_donation(visit_id: str) -> dict:
    return get_success_data(api_client.get_donation(visit_id, ADMIN))


def get_screening(visit_id: str) -> dict:
    return get_success_data(api_client.get_screening(visit_id, ADMIN))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, ADMIN))


def list_units(params: dict):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_units(ADMIN, params=params))


def list_lookback_cases(params: dict):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_lookback_cases(ADMIN, params=params))


# ---------------------------------------------------------------------------
# Tier 4: full donation lifecycle shortcuts
# ---------------------------------------------------------------------------

def run_completed_donation(donor: dict, center: dict,
                           screening_scheduled_for: str,
                           checkin_time: str,
                           discharge_time: str,
                           actual_volume_ml: int = 690,
                           recorder_id: str = "rec-01",
                           screener_id: str = "ms-01",
                           weight_kg: float = 72.5) -> dict:
    """Drive one donation all the way to COMPLETED.

    Clock assumptions: the screening sub-records are written at the current
    logical clock; the clock is moved to checkin_time before check-in and to
    discharge_time (>= observation entry + 15 min) before discharge.
    Returns the COMPLETED donation visit.
    """
    screening = make_cleared_screening(
        donor, center, screening_scheduled_for,
        recorder_id=recorder_id, screener_id=screener_id, weight_kg=weight_kg,
    )
    donation = make_donation(donor, center, screening, checkin_time)
    set_clock(checkin_time)
    check_in(donation["id"])
    complete_collection(donation["id"], actual_volume_ml)
    set_clock(discharge_time)
    return discharge(donation["id"])


def setup_qualified_donor_with_released_units(center: dict, donor: dict = None,
                                              first_day: str = "2026-09-01",
                                              second_day: str = "2026-09-04"):
    """Donor with two completed donations inside the applicant window.

    Returns (donor, [dv1, dv2]); the donor is QUALIFIED and both units were
    auto-released by the qualification cascade.
    """
    if donor is None:
        donor = make_donor(center)
    dv1 = run_completed_donation(
        donor, center,
        screening_scheduled_for=f"{first_day}T08:00:00Z",
        checkin_time=f"{first_day}T09:30:00Z",
        discharge_time=f"{first_day}T09:46:00Z",
    )
    set_clock(f"{second_day}T09:00:00Z")
    dv2 = run_completed_donation(
        donor, center,
        screening_scheduled_for=f"{second_day}T08:00:00Z",
        checkin_time=f"{second_day}T09:30:00Z",
        discharge_time=f"{second_day}T09:46:00Z",
    )
    return get_donor(donor["id"]), [dv1, dv2]


def setup_lookback_case_ready(center: dict, donor: dict,
                              reactive_day: str, marker: str = "hiv_ag_ab"):
    """Post a reactive viral marker for the donor on a fresh screening.

    The donor's in-window units are swept to LOOKBACK_HOLD and the case
    advances to UNITS_QUARANTINED. Returns the LookBackCase row.
    """
    screening = make_screening(donor, center, f"{reactive_day}T08:00:00Z")
    set_clock(f"{reactive_day}T09:00:00Z")
    payload = viral_marker_payload(**{marker: "REACTIVE"})
    resp = api_client.record_sub_record(
        screening["id"],
        {"record_type": "VIRAL_MARKER", "payload": payload},
        make_recorder_headers("rec-01"),
    )
    get_success_data(resp)
    cases, meta = list_lookback_cases({"donor_id": donor["id"]})
    assert meta["total_count"] == 1, f"expected one look-back case, got {meta}"
    return cases[0]
