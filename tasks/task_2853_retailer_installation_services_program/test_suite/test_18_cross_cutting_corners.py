"""The cross-cutting layers: the four optimistic-concurrency guards, and the inclusive
probation ceiling read in both directions.

Each stale-version guard is exercised on a project or firm whose state precondition is
genuinely satisfied, so nothing but the version counter can explain the refusal.
"""

from test_helpers import (
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    ApiErrorId,
    AssignmentStatus,
    ChangeOrderStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    assert_committed_minutes,
    assert_deposit_buckets,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_scorecard_dimensions,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
    validate_error,
    validate_paginated,
)

DEPOSIT = 51306
QUOTED = 171020
UPCHARGE_TEN_UNITS = 4505
CLOCK = "2026-08-01T00:00:00.000Z"

FIRST_WINDOW = ("2026-09-01T08:00:00.000Z", "2026-09-01T16:00:00.000Z")
SECOND_WINDOW = ("2026-09-05T08:00:00.000Z", "2026-09-05T16:00:00.000Z")


def _booked_then_released(api):
    """A deposited FLOOR-DIRECT project whose first hold has been released, so it is back
    in MEASURED two versions after the view the client still holds."""
    base = fx.deposited_project(api, f.service_category_payload(),
                                f.plain_jurisdiction_payload(),
                                requested_install_date="2026-09-01T13:00:00.000Z")
    network = fx.activated_installer(api, base["jurisdiction"]["id"])
    stale_version = base["project"]["version"]

    assignment = fx.hold_assignment(api, base["project"]["id"],
                                    network["installer"]["id"],
                                    expected_project_version=stale_version,
                                    window_start=FIRST_WINDOW[0],
                                    window_end=FIRST_WINDOW[1])
    released = get_success_data(
        api.release_assignment(assignment["id"],
                               f.release_payload("Installer double-booked by the branch"),
                               PROJECT_COORDINATOR)
    )
    base["installer_id"] = network["installer"]["id"]
    base["stale_version"] = stale_version
    base["released"] = released
    base["fresh"] = fx.read_project(api, base["project"]["id"])
    return base


def test_a_hold_quoting_the_pre_release_version_is_refused(api):
    """Book-then-release leaves the project in MEASURED two versions on, so the state
    machine would admit a second hold and only the version guard refuses it.

    PRD 2.6: "The guard is load-bearing: a project sitting in `MEASURED` legitimately
    accepts an assignment, and a project that took an assignment and then had it
    released is back in `MEASURED`, so the state precondition alone would let a client
    holding an out-of-date view create a second overlapping hold."

    Design: Corner/cross_cutting_complexity_layers/occ_assignment_create_rejects_a_writer_whose_project_view_predates_a_release
    """
    ctx = _booked_then_released(api)
    project_id = ctx["project"]["id"]

    assert ctx["released"]["status"] == AssignmentStatus.RELEASED
    assert ctx["released"]["release_reason"] == "Installer double-booked by the branch"
    assert_project_dimensions(ctx["fresh"], fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)
    # The create and the release each bumped the project once.
    assert_version(ctx["fresh"], ctx["stale_version"] + 2,
                   "the project after the book-then-release round trip")

    response = api.create_assignment(
        f.assignment_payload(project_id, ctx["installer_id"], ctx["stale_version"],
                             window_start=SECOND_WINDOW[0],
                             window_end=SECOND_WINDOW[1]),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.STALE_PROJECT_VERSION)


def test_the_refused_hold_moves_no_capacity_and_the_fresh_one_succeeds(api):
    """A rejected OCC write bumps nothing: capacity is still zero and the project's
    version has not moved. The identical body with the current version then holds.

    PRD 2.6: "Creating an installer assignment requires `expected_project_version` in
    the request body, carrying the client's last observed `version` of the target
    `Project`."

    Design: Corner/cross_cutting_complexity_layers/occ_assignment_create_rejects_a_writer_whose_project_view_predates_a_release
    """
    ctx = _booked_then_released(api)
    project_id = ctx["project"]["id"]
    installer_id = ctx["installer_id"]
    fresh_version = ctx["fresh"]["version"]

    validate_error(
        api.create_assignment(
            f.assignment_payload(project_id, installer_id, ctx["stale_version"],
                                 window_start=SECOND_WINDOW[0],
                                 window_end=SECOND_WINDOW[1]),
            PROJECT_COORDINATOR),
        ApiErrorId.STALE_PROJECT_VERSION)

    assert_committed_minutes(fx.read_installer(api, installer_id), 0)
    after_refusal = fx.read_project(api, project_id)
    assert_version(after_refusal, fresh_version, "the project after the 412")
    assert_project_dimensions(after_refusal, fulfillment=FulfillmentStatus.MEASURED)

    accepted = get_success_data(
        api.create_assignment(
            f.assignment_payload(project_id, installer_id, fresh_version,
                                 window_start=SECOND_WINDOW[0],
                                 window_end=SECOND_WINDOW[1]),
            PROJECT_COORDINATOR))
    assert accepted["status"] == AssignmentStatus.HELD
    assert_committed_minutes(fx.read_installer(api, installer_id), 480)

    after = fx.read_project(api, project_id)
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.SCHEDULED)
    assert_version(after, fresh_version + 1, "the project after the accepted hold")


def _declined_change_order(api):
    """A MEASURED FLOOR-DIRECT project whose first change order the household declined,
    so the project has advanced while returning to the state that admits another one."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    project = fx.sell_project(api, base)
    stale_version = project["version"]

    change_order = fx.raise_change_order(api, project["id"],
                                         [f.primary_line(10.00)],
                                         expected_project_version=stale_version)
    submitted = get_success_data(
        api.submit_change_order(change_order["id"], PROJECT_COORDINATOR))
    declined = get_success_data(
        api.decide_change_order(change_order["id"], f.decision_payload("DECLINE"),
                                make_customer_headers(base["customer"]["id"])))
    base["project"] = project
    base["stale_version"] = stale_version
    base["first"] = change_order
    base["submitted"] = submitted
    base["declined"] = declined
    base["fresh"] = fx.read_project(api, project["id"])
    return base


def test_a_change_order_quoting_the_pre_decision_version_is_refused(api):
    """The declined change order left the project in MEASURED, where a second change
    order is legal again — but the coordinator holding the pre-decision version is
    refused 412, and no second change order is recorded.

    PRD 2.6: "Because a new change order may name `supersedes_change_order_id` and
    legitimately drive an earlier one to `SUPERSEDED`, a client whose view of the project
    predates another accepted change order would otherwise price its lines against a
    scope that no longer exists."

    Design: Corner/cross_cutting_complexity_layers/occ_change_order_create_rejects_a_writer_whose_view_predates_a_decision
    """
    ctx = _declined_change_order(api)
    project_id = ctx["project"]["id"]

    assert_money(ctx["first"]["upcharge_cents"], UPCHARGE_TEN_UNITS, "upcharge_cents")
    assert ctx["submitted"]["status"] == ChangeOrderStatus.PENDING_CUSTOMER
    assert ctx["declined"]["status"] == ChangeOrderStatus.DECLINED
    assert_project_dimensions(ctx["fresh"], fulfillment=FulfillmentStatus.MEASURED)
    assert ctx["fresh"]["version"] > ctx["stale_version"], (
        "submitting and deciding each advanced the project"
    )

    response = api.create_change_order(
        f.change_order_payload(project_id, ctx["stale_version"],
                               [f.primary_line(10.00)]),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.STALE_PROJECT_VERSION)

    rows, meta = validate_paginated(
        api.list_project_change_orders(project_id, PROJECT_COORDINATOR))
    assert meta["total_count"] == 1, "the refused change order was never created"
    assert rows[0]["id"] == ctx["first"]["id"]


def test_the_same_lines_price_identically_once_the_version_is_current(api):
    """Re-read the project and the identical body is accepted, opening a fresh DRAFT at
    the same 4505-cent upcharge while the project stays MEASURED.

    PRD 2.6: "Creating a change order likewise requires `expected_project_version`
    matching the project's current `version`, on pain of `ERR_STALE_PROJECT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_change_order_create_rejects_a_writer_whose_view_predates_a_decision
    """
    ctx = _declined_change_order(api)
    project_id = ctx["project"]["id"]
    fresh_version = ctx["fresh"]["version"]

    validate_error(
        api.create_change_order(
            f.change_order_payload(project_id, ctx["stale_version"],
                                   [f.primary_line(10.00)]),
            PROJECT_COORDINATOR),
        ApiErrorId.STALE_PROJECT_VERSION)

    second = get_success_data(
        api.create_change_order(
            f.change_order_payload(project_id, fresh_version,
                                   [f.primary_line(10.00)]),
            PROJECT_COORDINATOR))
    assert second["status"] == ChangeOrderStatus.DRAFT
    assert second["id"] != ctx["first"]["id"]
    assert_money(second["upcharge_cents"], UPCHARGE_TEN_UNITS,
                 "the re-priced upcharge_cents")

    after = fx.read_project(api, project_id)
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED)
    assert_money(after["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    rows, meta = validate_paginated(
        api.list_project_change_orders(project_id, PROJECT_COORDINATOR))
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [ctx["first"]["id"], second["id"]]


def _cancelled_inside_the_cooling_off_window(api):
    """A deposited FLOOR-MEASURED project cancelled by the coordinator at the programme
    clock, so the cooling-off tier waived everything and the window is still open."""
    base = fx.deposited_project(api, f.measured_never_permit_category_payload(),
                                f.plain_jurisdiction_payload())
    stale_version = base["project"]["version"]
    cancelled = fx.cancel_project(api, base["project"]["id"], PROJECT_COORDINATOR,
                                  reason="Customer withdrew before measurement")
    base["stale_version"] = stale_version
    base["cancelled"] = cancelled
    return base


def test_a_reinstatement_quoting_the_pre_cancellation_version_is_refused(api):
    """The cancellation is itself the write that made the client's view stale, so the
    reinstatement quoting the pre-cancellation version is 412 even though the project is
    genuinely reinstatable.

    PRD 2.6: "Reinstating a cancelled project requires `expected_project_version`
    matching the project's current `version`, again on pain of
    `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_project_reinstate_rejects_the_pre_cancellation_version
    """
    ctx = _cancelled_inside_the_cooling_off_window(api)
    project_id = ctx["project"]["id"]
    cancelled = ctx["cancelled"]

    assert_project_dimensions(cancelled, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.REFUNDED)
    assert_deposit_buckets(cancelled, DEPOSIT, 0, 0, DEPOSIT, 0)
    assert_version(cancelled, ctx["stale_version"] + 1,
                   "the project after the cancellation")

    response = api.reinstate_project(
        project_id, f.reinstate_payload(ctx["stale_version"],
                                        note="Customer changed their mind"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.STALE_PROJECT_VERSION)

    after_refusal = fx.read_project(api, project_id)
    assert_project_dimensions(after_refusal, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.REFUNDED)
    assert_deposit_buckets(after_refusal, DEPOSIT, 0, 0, DEPOSIT, 0)
    assert_version(after_refusal, cancelled["version"], "the project after the 412")


def test_the_post_cancellation_version_restores_every_cent(api):
    """Quoting the version the cancellation produced, the reinstatement pulls all 51306
    refunded cents back into the held bucket and reopens the project at MEASURE_PENDING.

    PRD 3.8: "Reinstatement moves the whole of `deposit_refunded_cents` and
    `deposit_forfeited_cents` back into `deposit_held_cents`, zeroes both, leaves
    `deposit_paid_cents` untouched, and sets `financial_status` to `DEPOSIT_HELD`,
    restoring the pre-cancellation bucket split exactly and with no drift — which is why
    the conservation identity holds before the cancellation, after the cancellation and
    after the reinstatement alike."

    Design: Corner/cross_cutting_complexity_layers/occ_project_reinstate_rejects_the_pre_cancellation_version
    """
    ctx = _cancelled_inside_the_cooling_off_window(api)
    project_id = ctx["project"]["id"]
    fresh_version = ctx["cancelled"]["version"]

    validate_error(
        api.reinstate_project(
            project_id, f.reinstate_payload(ctx["stale_version"]),
            PROJECT_COORDINATOR),
        ApiErrorId.STALE_PROJECT_VERSION)

    reinstated = get_success_data(
        api.reinstate_project(
            project_id, f.reinstate_payload(fresh_version,
                                            note="Customer changed their mind"),
            PROJECT_COORDINATOR))

    assert_project_dimensions(reinstated,
                              fulfillment=FulfillmentStatus.MEASURE_PENDING,
                              financial=FinancialStatus.DEPOSIT_HELD)
    assert_deposit_buckets(reinstated, DEPOSIT, DEPOSIT, 0, 0, 0)
    assert reinstated["cancelled_at"] is None
    assert reinstated["cancel_reason"] is None
    assert_version(reinstated, fresh_version + 1,
                   "the project after the reinstatement")


FOUR_EVENTS = [
    f.scorecard_event_payload("PUNCH_SAFETY", CLOCK),
    f.scorecard_event_payload("PUNCH_MINOR", CLOCK),
    f.csat_event_payload(2, CLOCK),
    f.csat_event_payload(2, CLOCK),
]


def _firm_one_event_short_of_removable(api):
    """An ACTIVE firm carrying four events: quality 67.00, timeliness 82.00, satisfaction
    66.00 and a composite of 71.25 — enough for probation, not for removal."""
    jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    network = fx.activated_installer(api, jurisdiction["id"])
    installer_id = network["installer"]["id"]
    fx.file_events(api, installer_id, FOUR_EVENTS)
    return {"installer_id": installer_id,
            "stale": fx.read_installer(api, installer_id)}


def test_the_event_that_licenses_removal_also_invalidates_the_managers_view(api):
    """A fifth survey drops the composite from 71.25 to exactly 70.00 and flips
    `removal_eligible` — and bumps the firm's version, so the manager who read the firm
    one event ago is refused 412 on a removal that has only just become legal.

    PRD 2.6: "Removing an installer requires `expected_installer_version` matching the
    target `Installer`'s current `version`, on pain of `ERR_STALE_INSTALLER_VERSION` and
    HTTP 412."

    PRD 3.9: "`removal_eligible` becomes true when the rolling `composite_score` is 70.00
    or below **and** `rolling_event_count` is 3 or more, **or** when
    `rolling_no_show_count` is 3 or more, **or** when the number of `PUNCH_SAFETY` events
    inside the rolling window is 2 or more — three independent routes, any one of which
    suffices."

    Design: Corner/cross_cutting_complexity_layers/occ_installer_remove_rejects_a_view_predating_the_event_that_made_removal_legal
    """
    ctx = _firm_one_event_short_of_removable(api)
    installer_id = ctx["installer_id"]
    stale = ctx["stale"]

    assert_score(stale["composite_score"], 71.25, "composite_score after four events")
    assert stale["removal_eligible"] is False
    assert stale["status"] == InstallerStatus.PROBATION

    fx.file_events(api, installer_id, [f.csat_event_payload(2, CLOCK)])
    fresh = fx.read_installer(api, installer_id)
    assert_score(fresh["composite_score"], 70.00, "composite_score after five events")
    assert fresh["removal_eligible"] is True
    assert fresh["rolling_event_count"] == 5
    assert_version(fresh, stale["version"] + 1, "the firm after the fifth event")

    response = api.remove_installer(
        installer_id,
        f.removal_payload(stale["version"], reason="Composite at the removal ceiling"),
        SERVICE_MANAGER)
    validate_error(response, ApiErrorId.STALE_INSTALLER_VERSION)

    after_refusal = fx.read_installer(api, installer_id)
    assert after_refusal["status"] == InstallerStatus.PROBATION
    assert after_refusal["removed_at"] is None
    assert after_refusal["removal_reason"] is None
    assert_version(after_refusal, fresh["version"], "the firm after the 412")


def test_the_re_read_version_removes_the_firm_sitting_on_the_ceiling(api):
    """With the version the eligibility-granting event produced, the same removal lands:
    the firm is REMOVED and stamped at the programme clock.

    PRD 3.9: "A successful removal sets `status` to `REMOVED`, stamps `removed_at` from
    the clock and records `removal_reason`; releases **every** assignment of that firm
    still `HELD` or `CONFIRMED` with `release_reason` `INSTALLER_REMOVED`; reduces the
    firm's `committed_minutes` by each released assignment's `duration_minutes`; reverts
    each affected project from `SCHEDULED` back to `MEASURED` so it can be given to
    somebody else; and increments the firm's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_installer_remove_rejects_a_view_predating_the_event_that_made_removal_legal
    """
    ctx = _firm_one_event_short_of_removable(api)
    installer_id = ctx["installer_id"]

    fx.file_events(api, installer_id, [f.csat_event_payload(2, CLOCK)])
    fresh = fx.read_installer(api, installer_id)

    validate_error(
        api.remove_installer(
            installer_id, f.removal_payload(ctx["stale"]["version"]), SERVICE_MANAGER),
        ApiErrorId.STALE_INSTALLER_VERSION)

    removed = get_success_data(
        api.remove_installer(
            installer_id,
            f.removal_payload(fresh["version"],
                              reason="Composite at the removal ceiling"),
            SERVICE_MANAGER))

    assert removed["status"] == InstallerStatus.REMOVED
    assert_instant(removed["removed_at"], CLOCK, "removed_at")
    assert removed["removal_reason"] == "Composite at the removal ceiling"
    assert_score(removed["composite_score"], 70.00, "composite_score on removal")
    assert_version(removed, fresh["version"] + 1, "the firm after the removal")
    assert_committed_minutes(removed, 0)


THREE_EVENTS = [
    f.scorecard_event_payload("ON_TIME_COMPLETION", CLOCK),
    f.scorecard_event_payload("LATE_COMPLETION", CLOCK),
    f.scorecard_event_payload("PUNCH_MINOR", CLOCK),
]


def _fresh_firm(api):
    """One ACTIVE firm in METRO-02 with an empty ledger, so the composite starts at the
    programme baseline of 85.00."""
    jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    return fx.activated_installer(api, jurisdiction["id"])["installer"]


def test_four_events_land_on_the_ceiling_and_the_inclusive_test_fires(api):
    """Three events leave the composite at 83.20 and the firm ACTIVE; the fourth lands it
    on exactly 78.00, and because the comparison is inclusive the firm goes on probation.

    PRD 3.9: "Separately, a firm at `ACTIVE` is moved to `PROBATION`, with
    `probation_started_at` stamped from the clock, when its rolling `composite_score` is
    78.00 or below and `rolling_event_count` is 3 or more; and a firm at `PROBATION`
    returns to `ACTIVE`, with `probation_started_at` cleared to null, as soon as its
    rolling `composite_score` rises **strictly** above 78.00."

    Design: Corner/cross_cutting_complexity_layers/probation_threshold_fires_at_exactly_seventy_eight_and_resets_above_it
    """
    installer = _fresh_firm(api)
    installer_id = installer["id"]
    assert_score(installer["composite_score"], 85.00, "composite_score at activation")
    assert installer["status"] == InstallerStatus.ACTIVE

    fx.file_events(api, installer_id, THREE_EVENTS)
    after_three = fx.read_installer(api, installer_id)
    # 84.00 * 0.45 + 83.00 * 0.30 + 82.00 * 0.25 = 37.80 + 24.90 + 20.50 = 83.20.
    assert_scorecard_dimensions(after_three, 84.00, 83.00, 82.00, 83.20)
    assert after_three["status"] == InstallerStatus.ACTIVE
    assert after_three["probation_started_at"] is None

    fx.file_events(api, installer_id, [f.scorecard_event_payload("PUNCH_MAJOR", CLOCK)])
    after_four = fx.read_installer(api, installer_id)
    # 76.00 * 0.45 + 81.00 * 0.30 + 78.00 * 0.25 = 34.20 + 24.30 + 19.50 = 78.00.
    assert_scorecard_dimensions(after_four, 76.00, 81.00, 78.00, 78.00)
    assert after_four["status"] == InstallerStatus.PROBATION
    assert_instant(after_four["probation_started_at"], CLOCK, "probation_started_at")
    assert after_four["rolling_event_count"] == 4
    # 78.00 is still well above the removal ceiling of 70.00: probation is not removal.
    assert after_four["removal_eligible"] is False


def test_a_fifth_event_strictly_above_the_ceiling_resets_the_firm(api):
    """One on-time completion lifts the composite from exactly 78.00 to 80.95, strictly
    above the ceiling, and the firm returns to ACTIVE with no operator action at all.

    PRD 3.9: "That recovery needs no operator action at all: the cycle
    `ACTIVE ↔ PROBATION` is driven entirely by the arithmetic, and a firm may pass around
    it any number of times."

    Design: Corner/cross_cutting_complexity_layers/probation_threshold_fires_at_exactly_seventy_eight_and_resets_above_it
    """
    installer_id = _fresh_firm(api)["id"]
    fx.file_events(api, installer_id, THREE_EVENTS)
    fx.file_events(api, installer_id, [f.scorecard_event_payload("PUNCH_MAJOR", CLOCK)])
    on_probation = fx.read_installer(api, installer_id)
    assert on_probation["status"] == InstallerStatus.PROBATION

    fx.file_events(api, installer_id,
                   [f.scorecard_event_payload("ON_TIME_COMPLETION", CLOCK)])
    after_five = fx.read_installer(api, installer_id)

    # 78.00 * 0.45 + 87.00 * 0.30 + 79.00 * 0.25 = 35.10 + 26.10 + 19.75 = 80.95.
    assert_scorecard_dimensions(after_five, 78.00, 87.00, 79.00, 80.95)
    assert after_five["status"] == InstallerStatus.ACTIVE
    assert after_five["probation_started_at"] is None
    assert after_five["rolling_event_count"] == 5
    assert after_five["removal_eligible"] is False
    assert after_five["version"] > on_probation["version"]
