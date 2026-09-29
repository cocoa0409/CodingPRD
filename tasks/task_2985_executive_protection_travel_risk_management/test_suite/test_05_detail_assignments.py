"""Protective-detail cost arithmetic, the rest buffer and the settlement basis."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _three_line_trip(api):
    """One leg carrying three assignments whose exact products end in half a cent."""
    w = fx.bootstrap_world(api)
    dep = w.dep
    w.driver_id = fx.register_staff(api, "Dee Driver", c.STAFF_ROLE_ANALYST, 9001)["id"]
    w.advance_id = fx.register_staff(api, "Al Advance", c.STAFF_ROLE_ANALYST, 8887)["id"]
    w.agent_id = fx.register_staff(api, "Ann Agent", c.STAFF_ROLE_ANALYST, 7777)["id"]
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at="2026-09-10T06:00:00Z",
        depart_at="2026-09-11T06:00:00Z",
    )
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    w.driver = fx.assign_detail(
        api,
        dep,
        leg["id"],
        w.driver_id,
        c.DETAIL_DRIVER,
        "2026-09-10T06:00:00Z",
        "2026-09-10T09:00:00Z",
    )
    w.advance = fx.assign_detail(
        api,
        dep,
        leg["id"],
        w.advance_id,
        c.DETAIL_ADVANCE,
        "2026-09-10T10:00:00Z",
        "2026-09-10T15:00:00Z",
    )
    w.lead = fx.assign_detail(
        api,
        dep,
        leg["id"],
        w.agent_id,
        c.DETAIL_LEAD_AGENT,
        "2026-09-10T16:00:00Z",
        "2026-09-10T18:00:00Z",
    )
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    return w


def test_each_assignment_rounds_its_own_line_to_a_whole_cent(api):
    """Three half-cent products each round up on their own line.

    PRD §3.5: "`cost_cents` is then computed on the **provisional** basis and `cost_basis` is set to `PROVISIONAL`: the hour count is multiplied by the staff member's `hourly_rate_cents` and then by the position multiplier — 1.25 for `LEAD_AGENT`, 1.00 for `AGENT`, 0.85 for `DRIVER` and 1.10 for `ADVANCE` — and the product is rounded half-up to a whole cent at this line item."

    Design: Difficulty/combinatorial_formula/assignment_cost_per_line_rounding_beats_sum_then_round_by_one_cent
    """
    w = _three_line_trip(api)

    a.assert_cents(w.driver["cost_cents"], 22_953, "driver cost_cents")
    a.assert_cents(w.advance["cost_cents"], 48_879, "advance cost_cents")
    a.assert_cents(w.lead["cost_cents"], 19_443, "lead cost_cents")
    assert w.driver["planned_billable_hours"] == 3
    assert w.advance["planned_billable_hours"] == 5
    assert w.lead["planned_billable_hours"] == 2
    for row in (w.driver, w.advance, w.lead):
        assert row["cost_basis"] == c.COST_BASIS_PROVISIONAL


def test_the_trip_total_is_the_sum_of_rounded_lines_not_a_rounded_sum(api):
    """Summing the exact products and rounding once would be one cent short.

    PRD §3.6: "Every addend is already a whole-cent integer, so the total is never re-rounded."

    Design: Difficulty/combinatorial_formula/assignment_cost_per_line_rounding_beats_sum_then_round_by_one_cent
    """
    w = _three_line_trip(api)

    submitted = validate_success(api.submit_trip_for_approval(w.trip_id, w.dep.mgr))
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        91_275,
        "provisional_security_cost_cents",
    )
    assert submitted["provisional_security_cost_cents"] != 91_274
    a.assert_trip_states(submitted, c.APPROVAL_PENDING_REVIEW)

    executive = fx.read_executive(api, w.dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=91_275, spent=0, remaining=99_908_725)


def _released_trip(api):
    """An approved trip whose single lead agent is released after 1h47m."""
    w = fx.bootstrap_world(api)
    dep = w.dep
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(api, dep, trip["id"])
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    w.assignment = fx.assign_detail(api, dep, leg["id"], dep.lead_id)
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    w.submitted = fx.submit_trip(api, dep, trip["id"])
    fx.ack_briefing(api, w.exec_id, trip["id"])
    w.approved = fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    w.released = fx.release_assignment(
        api, dep, w.assignment["id"], "2026-09-10T09:47:00Z"
    )
    return w


def test_the_minimum_billable_floor_reprices_the_assignment_on_release(api):
    """The same shift is worth ten planned hours and four settled ones.

    PRD §3.5: "`actual_ends_at` is stored, and `final_billable_hours` is computed as the larger of the four-hour minimum and the elapsed whole minutes from `starts_at` to `actual_ends_at` divided by 60 and rounded up to the next whole hour."

    Design: Difficulty/dual_variant_calc/trip_cost_provisional_vs_final_diverge_through_min_billable_floor
    """
    w = _released_trip(api)

    a.assert_cents(
        w.submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    assert w.assignment["planned_billable_hours"] == 10
    assert w.released["final_billable_hours"] == 4
    a.assert_cents(w.released["cost_cents"], 45_000, "cost_cents")
    assert w.released["cost_basis"] == c.COST_BASIS_FINAL
    assert w.released["status"] == c.ASSIGNMENT_RELEASED
    assert w.released["actual_ends_at"] == "2026-09-10T09:47:00.000Z"

    staff = fx.read_staff(api, w.dep, w.dep.lead_id)
    a.assert_staff_hours(staff, committed=0, released=4)


def test_the_closed_trip_settles_on_the_final_basis_and_splits_the_perquisite(api):
    """The provisional and final figures differ by the floor, and the split follows.

    PRD §3.9: "**Step four:** `perquisite_taxable_cents` is `total_security_cost_cents` multiplied by that rate, rounded half-up to a whole cent; `business_borne_cents` is `total_security_cost_cents` less `perquisite_taxable_cents`; and `perquisite_rate_applied` records the rate actually used, pinned for audit, and is therefore always exactly one of 0.00, 0.10, 0.25, 0.40 or 1.00."

    Design: Difficulty/dual_variant_calc/trip_cost_provisional_vs_final_diverge_through_min_billable_floor
    """
    w = _released_trip(api)
    fx.set_clock(api, c.TRIP_RETURN_AT)

    closed = fx.close_trip(api, w.dep, w.trip_id)
    a.assert_cents(
        closed["total_security_cost_cents"], 45_000, "total_security_cost_cents"
    )
    a.assert_cents(
        closed["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    assert (
        closed["provisional_security_cost_cents"] - closed["total_security_cost_cents"]
        == 67_500
    )
    a.assert_decimal_value(
        closed["perquisite_rate_applied"], 0.10, "perquisite_rate_applied"
    )
    a.assert_cents(closed["perquisite_taxable_cents"], 4_500, "perquisite_taxable_cents")
    a.assert_cents(closed["business_borne_cents"], 40_500, "business_borne_cents")
    a.assert_trip_states(closed, c.APPROVAL_APPROVED, c.READINESS_CLOSED)
    assert closed["next_check_in_due_at"] is None


def _rest_buffer_world(api):
    """One agent already committed to an eight-hour shift on a wide leg."""
    w = fx.bootstrap_world(api)
    dep = w.dep
    w.sam_id = fx.register_staff(api, "Sam Agent", c.STAFF_ROLE_ANALYST, 9000)["id"]
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    w.neighbour = fx.assign_detail(
        api,
        dep,
        leg["id"],
        w.sam_id,
        c.DETAIL_AGENT,
        "2026-09-10T08:00:00Z",
        "2026-09-10T16:00:00Z",
    )
    w.leg_v1 = fx.leg_version(api, dep, leg["id"])
    return w


def _candidate(api, w, starts_at, ends_at, version=None):
    return api.create_detail_assignment(
        f.detail_assignment_payload(
            w.leg_id,
            w.sam_id,
            w.leg_v1 if version is None else version,
            role_on_detail=c.DETAIL_AGENT,
            starts_at=starts_at,
            ends_at=ends_at,
        ),
        w.dep.mgr,
    )


def test_the_rest_buffer_excludes_shifts_that_do_not_even_overlap(api):
    """The twelve-hour buffer inflates the exclusion zone on both sides.

    PRD §3.5: "A new assignment is rejected when there exists any other `CONFIRMED` assignment of the same staff member — call it the neighbour — such that the new assignment's `starts_at` falls strictly before the neighbour's `ends_at` plus 12 hours, and the neighbour's `starts_at` falls strictly before the new assignment's `ends_at` plus 12 hours."

    Design: Difficulty/resource_temporal_overlap/staff_rest_buffer_excludes_neighbour_until_exactly_twelve_hours_after
    """
    w = _rest_buffer_world(api)

    assert w.neighbour["status"] == c.ASSIGNMENT_CONFIRMED
    assert w.neighbour["planned_billable_hours"] == 8
    a.assert_cents(w.neighbour["cost_cents"], 72_000, "cost_cents")
    a.assert_staff_hours(fx.read_staff(api, w.dep, w.sam_id), committed=8)

    validate_error(
        _candidate(api, w, "2026-09-10T22:00:00Z", "2026-09-11T06:00:00Z"),
        e.ERR_STAFF_REST_BUFFER_CONFLICT,
        409,
    )
    validate_error(
        _candidate(api, w, "2026-09-11T03:59:00Z", "2026-09-11T11:59:00Z"),
        e.ERR_STAFF_REST_BUFFER_CONFLICT,
        409,
    )

    a.assert_staff_hours(fx.read_staff(api, w.dep, w.sam_id), committed=8)
    _rows, meta = validate_paginated(
        api.list_detail_assignments(w.dep.mgr, staff_id=w.sam_id)
    )
    assert meta["total_count"] == 1, "neither rejected candidate was persisted"


def test_a_shift_starting_exactly_twelve_hours_later_is_accepted(api):
    """Both buffer comparisons are strict, so the boundary instant passes.

    PRD §3.5: "Both comparisons are strict, so a new assignment whose `starts_at` lands exactly on the neighbour's `ends_at` plus 12 hours passes."

    Design: Difficulty/resource_temporal_overlap/staff_rest_buffer_excludes_neighbour_until_exactly_twelve_hours_after
    """
    w = _rest_buffer_world(api)
    validate_error(
        _candidate(api, w, "2026-09-11T03:59:00Z", "2026-09-11T11:59:00Z"),
        e.ERR_STAFF_REST_BUFFER_CONFLICT,
        409,
    )
    assert fx.leg_version(api, w.dep, w.leg_id) == w.leg_v1, (
        "a rejected create advances no version"
    )

    accepted = validate_success(
        _candidate(api, w, "2026-09-11T04:00:00Z", "2026-09-11T12:00:00Z"), 201
    )
    assert accepted["status"] == c.ASSIGNMENT_CONFIRMED
    assert accepted["planned_billable_hours"] == 8
    a.assert_cents(accepted["cost_cents"], 72_000, "cost_cents")

    a.assert_staff_hours(fx.read_staff(api, w.dep, w.sam_id), committed=16)
    _rows, meta = validate_paginated(
        api.list_detail_assignments(w.dep.mgr, staff_id=w.sam_id)
    )
    assert meta["total_count"] == 2


def test_a_second_release_cannot_re_settle_a_released_assignment(api):
    """RELEASED is terminal, so the floored final cost survives the retry.

    PRD §3.5: "Releasing an assignment settles it. The manager supplies `actual_ends_at`, which must be strictly later than the assignment's `starts_at`, and the assignment moves `CONFIRMED → RELEASED`; a release attempted on an assignment that is not `CONFIRMED` is rejected with `ERR_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/state_machines/release_an_already_released_assignment_returns_assignment_invalid_state
    """
    w = fx.bootstrap_world(api)
    dep = w.dep
    driver_id = fx.register_staff(api, "Dee Driver", c.STAFF_ROLE_ANALYST, 9000)["id"]
    trip = fx.create_trip(api, dep, w.exec_id, w.ra_id)
    leg = fx.add_leg(
        api, dep, trip["id"], arrive_at=c.TRIP_DEPART_AT, depart_at=c.TRIP_RETURN_AT
    )
    assignment = fx.assign_detail(
        api,
        dep,
        leg["id"],
        driver_id,
        c.DETAIL_DRIVER,
        "2026-09-10T08:00:00Z",
        "2026-09-10T18:00:00Z",
    )
    released = fx.release_assignment(
        api, dep, assignment["id"], "2026-09-10T10:00:00Z"
    )
    assert released["status"] == c.ASSIGNMENT_RELEASED
    assert released["cost_basis"] == c.COST_BASIS_FINAL
    assert released["final_billable_hours"] == 4
    a.assert_cents(released["cost_cents"], 30_600, "cost_cents")

    retry = api.release_detail_assignment(
        assignment["id"], f.release_payload("2026-09-10T17:00:00Z"), dep.mgr
    )
    validate_error(retry, e.ERR_ASSIGNMENT_INVALID_STATE, 409)

    stored = validate_success(api.get_detail_assignment(assignment["id"], dep.mgr))
    assert stored["actual_ends_at"] == "2026-09-10T10:00:00.000Z"
    assert stored["final_billable_hours"] == 4
    a.assert_cents(stored["cost_cents"], 30_600, "cost_cents")
    assert stored["version"] == released["version"]
    a.assert_staff_hours(fx.read_staff(api, dep, driver_id), committed=0, released=4)


def test_a_certification_lapsing_at_the_detail_end_is_not_good_enough(api):
    """The certification comparison is strict against the shift's own end instant.

    PRD §3.5: "The agent's certification must cover the whole shift: `certification_expires_at` must be strictly later than the request's `ends_at`, and an instant exactly equal to `ends_at` **fails** — a certification that lapses at the very moment the detail ends is not good enough, and the rejection is `ERR_STAFF_CERTIFICATION_EXPIRED`."

    Design: Corner/validations/assignment_whose_certification_expires_at_the_detail_end_is_rejected
    """
    w = fx.bootstrap_world(api)
    dep = w.dep
    lapsing = fx.register_staff(
        api,
        "Lar Lapsing",
        c.STAFF_ROLE_ANALYST,
        9000,
        certification_expires_at="2026-09-10T18:00:00Z",
    )
    covering = fx.register_staff(
        api,
        "Cora Covered",
        c.STAFF_ROLE_ANALYST,
        9000,
        certification_expires_at="2026-09-10T18:00:01Z",
    )
    trip = fx.create_trip(api, dep, w.exec_id, w.ra_id)
    leg = fx.add_leg(
        api, dep, trip["id"], arrive_at=c.TRIP_DEPART_AT, depart_at=c.TRIP_RETURN_AT
    )
    leg_v0 = leg["version"]

    def create(staff_id):
        return api.create_detail_assignment(
            f.detail_assignment_payload(
                leg["id"],
                staff_id,
                leg_v0,
                role_on_detail=c.DETAIL_AGENT,
                starts_at="2026-09-10T08:00:00Z",
                ends_at="2026-09-10T18:00:00Z",
            ),
            dep.mgr,
        )

    validate_error(
        create(lapsing["id"]), e.ERR_STAFF_CERTIFICATION_EXPIRED, 409
    )
    a.assert_staff_hours(fx.read_staff(api, dep, lapsing["id"]), committed=0)
    _rows, meta = validate_paginated(
        api.list_detail_assignments(dep.mgr, trip_leg_id=leg["id"])
    )
    assert meta["total_count"] == 0

    accepted = validate_success(create(covering["id"]), 201)
    assert accepted["planned_billable_hours"] == 10
    a.assert_cents(accepted["cost_cents"], 90_000, "cost_cents")
    a.assert_staff_hours(fx.read_staff(api, dep, covering["id"]), committed=10)
    a.assert_staff_hours(fx.read_staff(api, dep, lapsing["id"]), committed=0)


def test_a_stale_leg_version_is_refused_and_the_refreshed_one_is_accepted(api):
    """The guard is an optimistic-concurrency check, not a state precondition.

    PRD §2.8: "If that value does not equal the leg's current `version`, the create is rejected with `ERR_STALE_TRIP_LEG_VERSION` (HTTP 412). Two assignments for different agents over non-colliding windows on the same leg are both legitimate, so this is not a state precondition"

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_trip_leg_version_is_rejected_then_the_refreshed_one_passes
    """
    w = fx.bootstrap_world(api)
    dep = w.dep
    trip = fx.create_trip(api, dep, w.exec_id, w.ra_id)
    leg = fx.add_leg(
        api, dep, trip["id"], arrive_at=c.TRIP_DEPART_AT, depart_at=c.TRIP_RETURN_AT
    )
    leg_v0 = leg["version"]
    assert leg_v0 == 1

    after_advance = fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    assert after_advance["version"] == 2

    def create(version):
        return api.create_detail_assignment(
            f.detail_assignment_payload(
                leg["id"],
                dep.lead_id,
                version,
                role_on_detail=c.DETAIL_LEAD_AGENT,
                starts_at="2026-09-10T08:00:00Z",
                ends_at="2026-09-10T18:00:00Z",
            ),
            dep.mgr,
        )

    validate_error(create(leg_v0), e.ERR_STALE_TRIP_LEG_VERSION, 412)
    _rows, meta = validate_paginated(
        api.list_detail_assignments(dep.mgr, trip_leg_id=leg["id"])
    )
    assert meta["total_count"] == 0

    refreshed = fx.read_leg(api, dep, leg["id"])
    assert refreshed["version"] == 2
    assert refreshed["lead_agent_covered"] is False

    accepted = validate_success(create(refreshed["version"]), 201)
    assert accepted["status"] == c.ASSIGNMENT_CONFIRMED
    a.assert_cents(accepted["cost_cents"], 112_500, "cost_cents")
    assert accepted["cost_basis"] == c.COST_BASIS_PROVISIONAL
    assert fx.leg_version(api, dep, leg["id"]) == 3
