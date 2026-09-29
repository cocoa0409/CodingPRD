"""The installer capacity identity across a release and a rebooking.

`committed_minutes` is a running total that must always equal the summed length of the
firm's live and completed windows — no more after a release, no less after a rebooking.
"""

from test_helpers import (
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    AssignmentStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    assert_capacity_conservation,
    assert_committed_minutes,
    assert_deposit_buckets,
    assert_money,
    assert_project_dimensions,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_installer_headers,
)

DEPOSIT = 59002
FINAL_CHARGE = 196673
BALANCE = 137671

FIRST_WINDOW = ("2026-08-20T08:00:00.000Z", "2026-08-20T16:00:00.000Z")
SECOND_WINDOW = ("2026-08-25T08:00:00.000Z", "2026-08-25T12:00:00.000Z")
START_CLOCK = "2026-08-25T08:00:00.000Z"
FINISH_CLOCK = "2026-08-25T11:30:00.000Z"


def _eight_hour_hold(api):
    """A deposited project with one eight-hour window held against an active firm."""
    ctx = fx.install_ready(api)
    ctx["assignment"] = fx.hold_assignment(
        api, ctx["project"]["id"], ctx["installer"]["id"],
        fx.project_version(api, ctx["project"]["id"]),
        window_start=FIRST_WINDOW[0], window_end=FIRST_WINDOW[1])
    ctx["installer"] = fx.read_installer(api, ctx["installer"]["id"])
    return ctx


def _release(api, assignment_id):
    return get_success_data(
        api.release_assignment(assignment_id, f.release_payload(), SERVICE_MANAGER)
    )


def test_releasing_a_window_returns_exactly_its_own_duration(api):
    """The release gives back 480 minutes and not a minute more, even though the
    released row still reports the length it held.

    PRD 3.6: "It sets `status` to `RELEASED`, records the reason, reduces the installer's
    `committed_minutes` by exactly `duration_minutes` — which is what keeps the capacity
    identity of §2.10 true before the hold, after the hold and after the release — and
    drives the project `SCHEDULED → MEASURED` so it can be rescheduled, unless the
    project is itself being cancelled in the same request."

    Design: Difficulty/compensating_invariant/installer_committed_minutes_are_conserved_through_release_and_rebooking
    """
    ctx = _eight_hour_hold(api)
    assert ctx["assignment"]["duration_minutes"] == 480
    assert_committed_minutes(ctx["installer"], 480)

    released = _release(api, ctx["assignment"]["id"])
    assert released["status"] == AssignmentStatus.RELEASED
    # The row keeps its own length; only the running total moves.
    assert released["duration_minutes"] == 480
    assert released["release_reason"] == "Crew reassigned to a storm-damage backlog"

    installer = fx.read_installer(api, ctx["installer"]["id"])
    assert_committed_minutes(installer, 0)
    assert_capacity_conservation(
        installer, fx.list_installer_assignments(api, ctx["installer"]["id"]))
    assert_project_dimensions(fx.read_project(api, ctx["project"]["id"]),
                              fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)


def test_the_rebooked_four_hour_window_survives_completion_at_240_minutes(api):
    """The freed 480 minutes are not double-counted: the replacement window contributes
    exactly its own 240, and completion leaves that total in place.

    PRD 3.6: "The installer's `completed_project_count` is recomputed, and its
    `committed_minutes` is recomputed but does not move, because `COMPLETED` assignments
    remain inside that sum."

    Design: Difficulty/compensating_invariant/installer_committed_minutes_are_conserved_through_release_and_rebooking
    """
    ctx = _eight_hour_hold(api)
    installer_id = ctx["installer"]["id"]
    project_id = ctx["project"]["id"]
    _release(api, ctx["assignment"]["id"])

    version_after_release = fx.project_version(api, project_id)
    second = fx.hold_assignment(api, project_id, installer_id, version_after_release,
                                window_start=SECOND_WINDOW[0],
                                window_end=SECOND_WINDOW[1])
    assert second["duration_minutes"] == 240
    assert_committed_minutes(fx.read_installer(api, installer_id), 240)

    confirmed = get_success_data(api.confirm_assignment(second["id"],
                                                        PROJECT_COORDINATOR))
    assert confirmed["status"] == AssignmentStatus.CONFIRMED
    assert_committed_minutes(fx.read_installer(api, installer_id), 240)

    fx.set_clock(api, START_CLOCK)
    get_success_data(api.start_assignment(second["id"],
                                          make_installer_headers(installer_id)))
    fx.set_clock(api, FINISH_CLOCK)
    completed = get_success_data(
        api.complete_assignment(second["id"], f.completion_payload(FINISH_CLOCK),
                                make_installer_headers(installer_id))
    )
    assert completed["status"] == AssignmentStatus.COMPLETED
    assert completed["on_time"] is True

    installer = fx.read_installer(api, installer_id)
    assert_committed_minutes(installer, 240)
    assert_capacity_conservation(
        installer, fx.list_installer_assignments(api, installer_id))
    assert installer["completed_project_count"] == 1
    assert installer["rolling_event_count"] == 1
    assert installer["status"] == InstallerStatus.ACTIVE

    project = fx.read_project(api, project_id)
    assert_money(project["final_labor_cents"], FINAL_CHARGE, "final_labor_cents")
    assert_money(project["total_due_cents"], FINAL_CHARGE, "total_due_cents")
    assert_money(project["balance_due_cents"], BALANCE, "balance_due_cents")
    assert_deposit_buckets(project, paid=DEPOSIT, held=0, applied=DEPOSIT,
                           refunded=0, forfeited=0)
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.INSTALL_COMPLETE,
                              financial=FinancialStatus.BALANCE_DUE)
    # The hold, the start and the completion each mutated the project once; the
    # confirmation touched nothing on it.
    assert_version(project, version_after_release + 3, "project")
