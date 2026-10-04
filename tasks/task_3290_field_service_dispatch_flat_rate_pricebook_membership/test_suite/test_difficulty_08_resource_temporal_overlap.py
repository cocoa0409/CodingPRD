"""Depth tests for resource-temporal overlap.

Two instances: half-open interval semantics on the branch calendar, and the
maintenance-interval arithmetic on membership visits.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

DISPATCHER = TEST_USERS["dispatcher_headers"]


# =====================================================================
# branch_window_half_open_overlap
# =====================================================================
def test_a_booking_starting_inside_a_live_window_is_refused(api):
    """PRD §3.3: "When the new appointment's half-open interval collides with the
    identically shaped interval of any other appointment on the same branch whose
    `status` is `SCHEDULED` or `DISPATCHED`, the booking is refused with
    `ERR_WINDOW_OVERLAP` (HTTP 409); appointments that are `COMPLETED` or `CANCELLED`
    no longer occupy the branch's calendar".

    Design: Difficulty/resource_temporal_overlap/branch_window_half_open_overlap
    """
    branch, live = F.setup_branch_with_live_window()

    response = api_client.create_appointment(
        {
            "branch_id": branch["id"],
            "customer_name": "Bo",
            "postal_code": "78701",
            "window_start_utc": "2026-09-10T10:59:59Z",
            "window_end_utc": "2026-09-10T12:00:00Z",
        },
        DISPATCHER,
    )
    validate_error(response, "ERR_WINDOW_OVERLAP")


def test_adjacent_windows_on_the_same_branch_are_not_an_overlap(api):
    """PRD §3.3: "The window is treated as half-open — from its start inclusive to its end
    exclusive — and that convention is what the collision rules below test."

    Design: Difficulty/resource_temporal_overlap/branch_window_half_open_overlap
    """
    branch, live = F.setup_branch_with_live_window()

    response = api_client.create_appointment(
        {
            "branch_id": branch["id"],
            "customer_name": "Bo",
            "postal_code": "78701",
            "window_start_utc": "2026-09-10T11:00:00Z",
            "window_end_utc": "2026-09-10T12:00:00Z",
        },
        DISPATCHER,
    )
    adjacent = validate_success(response, expected_status=201)
    assert adjacent["status"] == "SCHEDULED"


# =====================================================================
# maintenance_visit_interval_with_agreement_alive_clip
# =====================================================================
def test_reschedule_into_a_live_visit_interval_is_refused(api):
    """PRD §3.9: "The visit's new interval is the half-open window from the new
    `scheduled_date` to `scheduled_date` plus the plan's `maintenance_visit_interval_days`.
    That interval must not overlap the identically shaped interval of any other visit on
    the same agreement whose `status` is `SCHEDULED` or `COMPLETED`".
    PRD §3.9: "An overlap is refused with `ERR_VISIT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/maintenance_visit_interval_with_agreement_alive_clip
    """
    branch, plan, agreement, visits = F.setup_membership(
        visit_dates=["2026-10-01T00:00:00Z", "2026-11-05T00:00:00Z"]
    )
    first, second = visits[0], visits[1]

    response = api_client.reschedule_visit(
        first["id"], {"scheduled_date": "2026-10-30T00:00:00Z"}, DISPATCHER
    )
    validate_error(response, "ERR_VISIT_OVERLAP")

    refreshed = [v for v in F.list_visits(agreement["id"]) if v["id"] == first["id"]][0]
    assert refreshed["scheduled_date"].startswith("2026-10-01"), (
        "the refusal must leave the visit's date untouched"
    )


def test_reschedule_into_a_clear_window_succeeds(api):
    """PRD §3.9: "When the reschedule succeeds the visit's `status` returns to `SCHEDULED`
    and its `scheduled_date` is replaced".
    PRD §3.9: "the parent agreement returns to `ACTIVE` when it was `OVERDUE` and no other
    visit on it remains `MISSED`."

    Design: Difficulty/resource_temporal_overlap/maintenance_visit_interval_with_agreement_alive_clip
    """
    branch, plan, agreement, visits = F.setup_membership(
        visit_dates=["2026-10-01T00:00:00Z", "2026-11-05T00:00:00Z"]
    )
    first = visits[0]

    response = api_client.reschedule_visit(
        first["id"], {"scheduled_date": "2026-12-10T00:00:00Z"}, DISPATCHER
    )
    moved = validate_success(response)
    assert moved["status"] == "SCHEDULED"
    assert moved["scheduled_date"].startswith("2026-12-10")
    assert moved["sequence_number"] == 1