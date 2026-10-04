"""Depth tests for paired-validation conflicts.

Two instances: the state-vs-referential pair on dispatch, and the
business-safety-vs-business-temporal pair on booking.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import TEST_USERS, api_client, fixtures as F, validate_success
from test_helpers.api_errors import ApiErrorId

DISPATCHER = TEST_USERS["dispatcher_headers"]


# =====================================================================
# state_versus_referential_on_dispatch
# =====================================================================
def _branch_with_plumbing_only_technician():
    branch = F.create_branch()
    F.hire_technician(
        branch["id"],
        name="Dana",
        postal_code="78701",
        skill_codes=["PLUMBING"],
        shift_segments=[{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-10T18:00:00Z"}],
        daily_capacity_hours=8,
    )
    F.create_task(
        code="HVAC-COMP", category="HVAC", required_skill_code="HVAC",
        estimated_hours=3.0, flat_rate_cents=300000,
    )
    return branch


def test_dispatch_with_a_line_but_no_matching_skill_is_refused_referentially(api):
    """PRD §3.5: "When no candidate at all holds every required skill code of the
    appointment's published task revisions, the dispatch is refused with
    `ERR_NO_ELIGIBLE_TECHNICIAN` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_versus_referential_on_dispatch
    """
    branch = _branch_with_plumbing_only_technician()
    appointment = F.book_appointment(branch["id"])
    F.add_line(appointment["id"], code="HVAC-COMP")

    response = api_client.dispatch_order({"appointment_id": appointment["id"]}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_TECHNICIAN)

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["technician_id"] is None
    assert refreshed["dispatch_status"] == "UNASSIGNED"


def test_dispatch_without_lines_is_refused_by_the_state_guard(api):
    """PRD §3.5: "it must carry at least one line; an appointment with no lines has
    `estimated_hours` of 0 and is not dispatchable, and the attempt is refused with
    `ERR_NO_APPOINTMENT_LINES` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_versus_referential_on_dispatch
    """
    branch = _branch_with_plumbing_only_technician()
    line_free = F.book_appointment(
        branch["id"],
        customer_name="Bo",
        window_start_utc="2026-09-10T09:00:00Z",
        window_end_utc="2026-09-10T11:00:00Z",
    )

    response = api_client.dispatch_order({"appointment_id": line_free["id"]}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_APPOINTMENT_LINES)


# =====================================================================
# business_safety_versus_business_temporal_on_booking
# =====================================================================
def test_backwards_window_that_also_overlaps_reports_the_overlap_error(api):
    """PRD §3.3: "When the new appointment's half-open interval collides with the
    identically shaped interval of any other appointment on the same branch whose
    `status` is `SCHEDULED` or `DISPATCHED`, the booking is refused with
    `ERR_WINDOW_OVERLAP` (HTTP 409)".
    PRD §2.10: "then the branch window collision guard (`ERR_WINDOW_OVERLAP`, HTTP 409),
    then the window-ordering guard (`ERR_WINDOW_INVALID`, HTTP 400)".

    Design: Difficulty/priority_pair_validation_conflict/business_safety_versus_business_temporal_on_booking
    """
    branch, live = F.setup_branch_with_live_window()

    response = api_client.create_appointment(
        {
            "branch_id": branch["id"],
            "customer_name": "Bo",
            "postal_code": "78701",
            "window_start_utc": "2026-09-10T11:00:00Z",
            "window_end_utc": "2026-09-10T10:00:00Z",
        },
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_backwards_window_with_no_collision_reports_the_ordering_error(api):
    """PRD §3.3: "When the supplied `window_end_utc` is not strictly later than
    `window_start_utc`, the booking is refused with `ERR_WINDOW_INVALID` (HTTP 400)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_versus_business_temporal_on_booking
    """
    branch, live = F.setup_branch_with_live_window()

    response = api_client.create_appointment(
        {
            "branch_id": branch["id"],
            "customer_name": "Cy",
            "postal_code": "78701",
            "window_start_utc": "2026-09-10T14:00:00Z",
            "window_end_utc": "2026-09-10T13:00:00Z",
        },
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_INVALID)