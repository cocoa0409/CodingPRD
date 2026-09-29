"""Reservation matching: the candidate filter, the ranking, the queue and release.

Covers how a request finds a garment — the eligibility filter, the turns-descending
ranking with its created_at tie-break, the recondition-buffer interval geometry, the
waitlist that absorbs unsatisfiable demand, the four rejections a named preferred
unit can earn, and the release path that hands the unit back to the floor.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_RENTAL_WINDOW,
    ERR_ITEM_SLOTS_EXHAUSTED,
    ERR_SIZE_NOT_IN_SIZE_RUN,
    ERR_UNIT_CONDEMNED,
    ERR_UNIT_NOT_ALLOCATABLE,
    ERR_UNIT_TURNS_EXHAUSTED,
    ERR_UNIT_WINDOW_COLLISION,
    ERR_WINDOW_IN_PAST,
)
from test_helpers.assertions import (
    assert_date,
    assert_depth_fields,
    assert_error,
    assert_fields,
    assert_instant,
    assert_list,
    assert_money,
    assert_null,
    assert_ok,
    assert_position_count_conserved,
    assert_unit_position,
)
from test_helpers.fixtures import (
    Scenario,
    completed_turn,
    finish_reconditioning,
    inspected_turn,
    standard_catalog,
    turn_to_delivery,
    turn_to_receipt,
)


def test_reservation_junction_is_reachable_from_both_the_member_and_the_unit_side(
    scenario: Scenario,
) -> None:
    """The same reservation row answers a member filter and an allocated-unit filter.

    PRD §3.3: "Reservations can be listed with optional `member_id`, `style_id`, `allocated_unit_id`, `superseded_reservation_id` and `state` filters; a `Member` reading that list sees only their own rows."

    Design: Corner/entities/entity_reservation_junction_is_reachable_from_both_the_member_and_the_unit_side
    """
    catalog = standard_catalog(scenario)
    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )
    unit_id = catalog.unit["id"]

    from_member, _ = assert_list(
        scenario.client.list_reservations(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=1,
    )
    from_unit, _ = assert_list(
        scenario.client.list_reservations(scenario.admin, {"allocated_unit_id": unit_id}),
        total_count=1,
    )

    for side in (from_member, from_unit):
        assert_fields(
            side[0],
            id=reservation["id"],
            state=K.RES_MATCHED,
            allocated_unit_id=unit_id,
            member_id=catalog.member_id,
        )


def test_waitlist_promotion_takes_only_the_rank_one_reservation(
    scenario: Scenario,
) -> None:
    """A restocked garment promotes the queue head and leaves the runner-up queued.

    PRD §3.3: "the reservation must be rank 1 by `created_at` ascending among the `WAITLISTED` reservations for the same `style_id` and `requested_size`"

    Design: Corner/state_machines/state_waitlist_promotion_takes_only_the_rank_one_reservation
    """
    catalog = standard_catalog(scenario)
    ilse = scenario.enrol_member(
        catalog.plan["id"], full_name=K.MEMBER_ILSE_NAME, email=K.MEMBER_ILSE_EMAIL
    )
    priya = scenario.enrol_member(
        catalog.plan["id"], full_name=K.MEMBER_PRIYA_NAME, email=K.MEMBER_PRIYA_EMAIL
    )
    turn = turn_to_delivery(scenario, catalog)
    second = scenario.create_reservation(ilse, catalog.style_id, K.WINDOW_AUG_14_18)
    third = scenario.create_reservation(priya, catalog.style_id, K.WINDOW_AUG_14_18)
    assert_fields(second, state=K.RES_WAITLISTED, waitlist_position=1)
    assert_fields(third, state=K.RES_WAITLISTED, waitlist_position=2)
    turn_to_receipt(scenario, catalog, turn)
    scenario.file_inspection(catalog.inspector, turn.job_id)
    finish_reconditioning(scenario, catalog, turn, restock=False)

    restocked = scenario.restock(catalog.repairer, turn.job_id)

    assert_fields(restocked, state=K.JOB_RESTOCKED)
    closed = scenario.read_reservation(turn.reservation_id)
    assert_fields(closed, state=K.RES_CLOSED)
    assert_money(closed, revenue_attributed_cents=K.PLAN_SIG4_BASE_REVENUE_PER_TURN_CENTS)
    promoted = scenario.read_reservation(second["id"])
    assert_fields(
        promoted,
        state=K.RES_MATCHED,
        allocated_unit_id=catalog.unit["id"],
        waitlist_position=None,
    )
    still_queued = scenario.read_reservation(third["id"])
    assert_fields(
        still_queued,
        state=K.RES_WAITLISTED,
        allocated_unit_id=None,
        waitlist_position=1,
    )
    unit = scenario.read_unit(catalog.unit["id"])
    assert_unit_position(unit, availability_state=K.AVAIL_RESERVED)
    assert_fields(unit, turns_completed=1)
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=0,
        active_unit_count=1,
    )


def test_selector_ranks_the_unit_with_the_most_turns_first(scenario: Scenario) -> None:
    """The garment that has already worked hardest is handed out again first.

    PRD §3.3: "The primary ranking is by `turns_completed` descending, so the unit that has already completed the most turns is preferred and the freshest garments are held back."

    Design: Corner/calculations/calc_selector_ranks_the_unit_with_the_most_turns_first
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002)
    )
    worked, fresh = catalog.units[0], catalog.units[1]
    completed_turn(
        scenario, catalog, K.WINDOW_AUG_05_09, preferred_unit_id=worked["id"]
    )

    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_13_17
    )

    assert_fields(
        reservation,
        state=K.RES_MATCHED,
        allocated_unit_id=worked["id"],
        waitlist_position=None,
    )
    assert_instant(reservation["matched_at"], K.CLOCK_AUG_10_0900, "matched_at")
    reused = scenario.read_unit(worked["id"])
    assert_unit_position(reused, availability_state=K.AVAIL_RESERVED)
    assert_fields(reused, turns_completed=1)
    untouched = scenario.read_unit(fresh["id"])
    assert_unit_position(untouched, availability_state=K.AVAIL_IN_STOCK)
    assert_fields(untouched, turns_completed=0)
    assert_depth_fields(
        scenario.read_style(catalog.style_id), floor_ready_unit_count=1
    )


def test_selector_tie_break_is_created_at_ascending_never_the_id(
    scenario: Scenario,
) -> None:
    """With both garments untouched, the one bought first wins the tie.

    PRD §3.3: "Ties on `turns_completed` are broken by `created_at` ascending, so the unit that entered the fleet earliest wins."

    Design: Corner/calculations/calc_selector_tie_break_is_created_at_ascending_never_the_id
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002)
    )
    earliest, later = catalog.units[0], catalog.units[1]

    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )

    assert_fields(
        reservation, state=K.RES_MATCHED, allocated_unit_id=earliest["id"]
    )
    assert_unit_position(
        scenario.read_unit(earliest["id"]), availability_state=K.AVAIL_RESERVED
    )
    assert_unit_position(
        scenario.read_unit(later["id"]), availability_state=K.AVAIL_IN_STOCK
    )
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=1,
        active_unit_count=2,
    )


def test_selector_empty_candidate_pool_waitlists_instead_of_erroring(
    scenario: Scenario,
) -> None:
    """A style with no fleet at all queues the request rather than refusing it.

    PRD §3.3: "When the candidate set is empty and the request named no `preferred_unit_id`, there is no error at all."

    Design: Corner/calculations/calc_selector_empty_candidate_pool_waitlists_instead_of_erroring
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    plan = scenario.create_plan()
    style = scenario.create_style(F.dress_style_payload())
    member = scenario.enrol_member(plan["id"])

    reservation = scenario.create_reservation(member, style["id"], K.WINDOW_AUG_05_09)

    assert_fields(
        reservation,
        state=K.RES_WAITLISTED,
        allocated_unit_id=None,
        waitlist_position=1,
        matched_at=None,
    )
    assert_fields(scenario.read_member(member), units_out_count=0)
    assert_depth_fields(
        scenario.read_style(style["id"]), demand_score=4, floor_ready_unit_count=0
    )


def test_rental_window_below_the_minimum_span_is_rejected(scenario: Scenario) -> None:
    """A one-day booking fails the span rule while a three-day booking matches.

    PRD §3.3: "the end date must be strictly later than the start date and the window length — the number of whole days from the start date to the end date — must be at least 3 days and at most 14 days"

    Design: Corner/validations/validation_rental_window_below_the_minimum_span_is_rejected
    """
    catalog = standard_catalog(scenario)
    headers = Scenario.member_headers(catalog.member)

    too_short = scenario.client.create_reservation(
        F.reservation_payload(catalog.style_id, K.SIZE_M, *K.WINDOW_AUG_05_06), headers
    )
    assert_error(too_short, ERR_INVALID_RENTAL_WINDOW)

    accepted = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_08
    )

    assert_fields(
        accepted, state=K.RES_MATCHED, allocated_unit_id=catalog.unit["id"]
    )
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=1,
    )
    assert_fields(scenario.read_member(catalog.member), units_out_count=1)


def test_rental_window_starting_before_today_is_rejected(scenario: Scenario) -> None:
    """Yesterday is refused and the clock's own day is accepted.

    PRD §3.3: "At rank 41, the start date must not be earlier than the current logical clock date, so a member may book for today or any future day but never for yesterday; otherwise the response is `ERR_WINDOW_IN_PAST` (422)."

    Design: Corner/validations/validation_rental_window_starting_before_today_is_rejected
    """
    catalog = standard_catalog(scenario)
    headers = Scenario.member_headers(catalog.member)

    in_the_past = scenario.client.create_reservation(
        F.reservation_payload(catalog.style_id, K.SIZE_M, *K.WINDOW_AUG_01_05), headers
    )
    assert_error(in_the_past, ERR_WINDOW_IN_PAST)

    accepted = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_03_06
    )

    assert_fields(
        accepted, state=K.RES_MATCHED, allocated_unit_id=catalog.unit["id"]
    )
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=1,
    )
    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]), availability_state=K.AVAIL_RESERVED
    )


def test_requested_size_outside_the_style_size_run_is_rejected(
    scenario: Scenario,
) -> None:
    """A size the style was never cut in is refused before any matching happens.

    PRD §3.3: "Before either of those, at rank 31, the `requested_size` must be a member of the parent style's `size_run`, otherwise `ERR_SIZE_NOT_IN_SIZE_RUN` (422)."

    Design: Corner/validations/validation_requested_size_outside_the_style_size_run_is_rejected
    """
    catalog = standard_catalog(scenario)
    headers = Scenario.member_headers(catalog.member)

    outside_run = scenario.client.create_reservation(
        F.reservation_payload(catalog.style_id, K.SIZE_XL, *K.WINDOW_AUG_05_09), headers
    )
    assert_error(outside_run, ERR_SIZE_NOT_IN_SIZE_RUN)

    accepted = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )

    assert_fields(accepted, state=K.RES_MATCHED)
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=1,
    )


def test_preferred_unit_at_its_turn_cap_is_refused(scenario: Scenario) -> None:
    """A garment that has spent its planned life cannot be named again.

    PRD §3.3: "at rank 33, a unit whose `turns_completed` has already reached the style's `expected_rental_turns_per_unit` yields `ERR_UNIT_TURNS_EXHAUSTED` (409)"

    Design: Corner/validations/validation_preferred_unit_at_its_turn_cap_is_refused
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_CAPE_001,), style_payload=F.cape_style_payload()
    )
    turn = completed_turn(scenario, catalog, K.WINDOW_AUG_05_09)
    headers = Scenario.member_headers(catalog.member)

    preferred = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            *K.WINDOW_AUG_20_24,
            preferred_unit_id=catalog.unit["id"],
        ),
        headers,
    )
    assert_error(preferred, ERR_UNIT_TURNS_EXHAUSTED)

    unpreferred = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_20_24
    )

    assert_fields(
        unpreferred,
        state=K.RES_WAITLISTED,
        allocated_unit_id=None,
        waitlist_position=1,
    )
    exhausted = scenario.read_unit(catalog.unit["id"])
    assert_unit_position(
        exhausted,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
    )
    assert_fields(exhausted, turns_completed=1)
    assert_fields(scenario.read_reservation(turn.reservation_id), state=K.RES_CLOSED)


def test_a_condemned_unit_cannot_be_named_as_the_preferred_unit(
    scenario: Scenario,
) -> None:
    """Condemnation is the most specific rejection a named unit can earn.

    PRD §3.3: "at rank 21, a unit whose `condition_state` is `CONDEMNED` yields `ERR_UNIT_CONDEMNED` (409)"

    Design: Corner/validations/validation_a_condemned_unit_cannot_be_named_as_the_preferred_unit
    """
    catalog = standard_catalog(scenario)
    turn = inspected_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        soil_level=K.SOIL_NONE,
        damage_severity=K.DAMAGE_LOSS,
        condition_grade_after=K.GRADE_D,
        biohazard_flag=False,
    )
    headers = Scenario.member_headers(catalog.member)

    preferred = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            *K.WINDOW_AUG_20_24,
            preferred_unit_id=catalog.unit["id"],
        ),
        headers,
    )
    assert_error(preferred, ERR_UNIT_CONDEMNED)

    unpreferred = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_20_24
    )

    assert_fields(unpreferred, state=K.RES_WAITLISTED, waitlist_position=1)
    condemned = scenario.read_unit(catalog.unit["id"])
    assert_unit_position(
        condemned,
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_CONDEMNED,
    )
    assert_null(condemned, "retired_at")
    job = scenario.read_job(catalog.inspector, turn.job_id)
    assert_fields(job, state=K.JOB_CONDEMNED_HOLD, condemned=True)
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=0,
        active_unit_count=1,
    )


def test_preferred_unit_of_another_style_is_not_allocatable(scenario: Scenario) -> None:
    """Naming a garment from a different style is a not-allocatable rejection.

    PRD §3.3: "at rank 32, a unit that belongs to another style, carries a different size, is not simultaneously `IN_STOCK` and `FLOOR_READY`, or sits on quarantine hold yields `ERR_UNIT_NOT_ALLOCATABLE` (409)"

    Design: Corner/validations/validation_preferred_unit_of_another_style_is_not_allocatable
    """
    catalog = standard_catalog(scenario)
    other_style = scenario.create_style(F.knit_style_payload())
    other_unit = scenario.add_unit(
        other_style["id"], K.UNIT_KNIT_001, acquisition_cost_cents=K.STYLE_KNIT_ACQUISITION_CENTS
    )
    headers = Scenario.member_headers(catalog.member)

    crossed = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            *K.WINDOW_AUG_05_09,
            preferred_unit_id=other_unit["id"],
        ),
        headers,
    )
    assert_error(crossed, ERR_UNIT_NOT_ALLOCATABLE)

    accepted = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )

    assert_fields(
        accepted, state=K.RES_MATCHED, allocated_unit_id=catalog.unit["id"]
    )
    assert_unit_position(
        scenario.read_unit(other_unit["id"]), availability_state=K.AVAIL_IN_STOCK
    )
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=1,
    )


def test_release_from_matched_returns_the_unit_to_the_floor(scenario: Scenario) -> None:
    """Giving up a matched reservation clears the allocation and frees the garment.

    PRD §3.3: "A `MATCHED` reservation moves `MATCHED → RELEASED`; as a second hop its allocated unit moves `RESERVED → IN_STOCK` and the reservation's `allocated_unit_id` is set back to null"

    Design: Corner/endpoints/endpoint_release_from_matched_returns_the_unit_to_the_floor
    """
    catalog = standard_catalog(scenario)
    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )
    headers = Scenario.member_headers(catalog.member)

    released = assert_ok(
        scenario.client.release_reservation(reservation["id"], headers)
    )

    assert_fields(released, state=K.RES_RELEASED, allocated_unit_id=None)
    freed = scenario.read_unit(catalog.unit["id"])
    assert_unit_position(
        freed,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
    )
    assert_null(freed, "occupied_until_date")
    assert_fields(freed, turns_completed=0)
    assert_money(freed, realized_revenue_cents=0)
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=1,
        active_unit_count=1,
    )
    assert_fields(scenario.read_member(catalog.member), units_out_count=0)


def _solo_member_with_a_closed_turn_and_a_waitlisted_slot(scenario: Scenario):
    """One-slot member: a CLOSED turn still inside its buffer, and the slot spent."""
    catalog = standard_catalog(scenario, plan_payload=F.solo1_plan_payload())
    completed_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_10,
        return_clock=K.CLOCK_AUG_10_0900,
        receipt_clock=K.CLOCK_AUG_11_0900,
    )
    bare_style = scenario.create_style(F.dress_style_payload())
    waitlisted = scenario.create_reservation(
        catalog.member, bare_style["id"], K.WINDOW_AUG_15_19
    )
    assert_fields(waitlisted, state=K.RES_WAITLISTED, waitlist_position=1)
    return catalog


def test_unit_window_collision_outranks_slot_exhaustion_on_a_preferred_unit(
    scenario: Scenario,
) -> None:
    """The buffer collision is reported even though the member's only slot is spent.

    PRD §3.3: "at rank 42, a unit whose existing commitments overlap the requested window under the buffer geometry above yields `ERR_UNIT_WINDOW_COLLISION` (409)"

    Design: Difficulty/priority_pair_validation_conflict/unit_window_collision_outranks_slot_exhaustion_on_preferred_unit
    """
    catalog = _solo_member_with_a_closed_turn_and_a_waitlisted_slot(scenario)
    headers = Scenario.member_headers(catalog.member)

    response = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            *K.WINDOW_AUG_11_15,
            preferred_unit_id=catalog.unit["id"],
        ),
        headers,
    )

    assert_error(response, ERR_UNIT_WINDOW_COLLISION)
    held = scenario.read_unit(catalog.unit["id"])
    assert_date(held["occupied_until_date"], "2026-08-12", "occupied_until_date")
    assert_fields(held, turns_completed=1)
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=2,
    )


def test_slot_exhaustion_surfaces_once_the_preferred_unit_clears_the_buffer(
    scenario: Scenario,
) -> None:
    """Clearing the buffer lets the slot ceiling, which was merely outranked, fire.

    PRD §3.3: "At rank 50, before any unit is allocated, the member's `units_out_count` plus the count of their `WAITLISTED` reservations must be strictly less than the plan's `item_slots`; a member on a three-slot plan who already has two garments out and one on the waitlist is refused with `ERR_ITEM_SLOTS_EXHAUSTED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/unit_window_collision_outranks_slot_exhaustion_on_preferred_unit
    """
    catalog = _solo_member_with_a_closed_turn_and_a_waitlisted_slot(scenario)
    headers = Scenario.member_headers(catalog.member)

    response = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            *K.WINDOW_AUG_12_16,
            preferred_unit_id=catalog.unit["id"],
        ),
        headers,
    )

    assert_error(response, ERR_ITEM_SLOTS_EXHAUSTED)
    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]),
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
    )
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=2,
    )


def _catalog_with_a_closed_turn_inside_its_buffer(scenario: Scenario):
    """A single-unit fleet whose only turn is CLOSED but still occupying to 08-12."""
    catalog = standard_catalog(scenario)
    turn = completed_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_10,
        return_clock=K.CLOCK_AUG_10_0900,
        receipt_clock=K.CLOCK_AUG_11_0900,
    )
    before = scenario.read_unit(catalog.unit["id"])
    assert_date(before["occupied_until_date"], "2026-08-12", "occupied_until_date")
    assert_unit_position(before, availability_state=K.AVAIL_IN_STOCK)
    assert_fields(before, turns_completed=1)
    return catalog, turn


def test_unit_reallocation_is_allowed_exactly_at_the_recondition_buffer_edge(
    scenario: Scenario,
) -> None:
    """A start date sitting on the buffer edge re-books the very same garment.

    PRD §3.3: "Touching exactly at the buffer edge does not collide: a request whose `requested_start_date` equals the prior reservation's `requested_end_date` plus the two buffer days is accepted."

    Design: Difficulty/resource_temporal_overlap/unit_reallocation_allowed_exactly_at_recondition_buffer_edge
    """
    catalog, turn = _catalog_with_a_closed_turn_inside_its_buffer(scenario)

    reservation = scenario.create_reservation(
        catalog.member,
        catalog.style_id,
        K.WINDOW_AUG_12_16,
        preferred_unit_id=catalog.unit["id"],
    )

    assert_fields(
        reservation, state=K.RES_MATCHED, allocated_unit_id=catalog.unit["id"]
    )
    rebooked = scenario.read_unit(catalog.unit["id"])
    assert_unit_position(rebooked, availability_state=K.AVAIL_RESERVED)
    assert_date(rebooked["occupied_until_date"], "2026-08-18", "occupied_until_date")
    assert_fields(scenario.read_member(catalog.member), units_out_count=1)
    assert_depth_fields(
        scenario.read_style(catalog.style_id), floor_ready_unit_count=0
    )
    assert_fields(
        scenario.read_reservation(turn.reservation_id),
        state=K.RES_CLOSED,
        allocated_unit_id=catalog.unit["id"],
    )


def test_unit_reallocation_one_day_inside_the_buffer_still_collides(
    scenario: Scenario,
) -> None:
    """A start date one day short of the buffer edge is a window collision.

    PRD §3.3: "A collision exists when the new request's start date is earlier than that extended end **and** the new request's end date is later than the prior reservation's start date."

    Design: Difficulty/resource_temporal_overlap/unit_reallocation_allowed_exactly_at_recondition_buffer_edge
    """
    catalog, turn = _catalog_with_a_closed_turn_inside_its_buffer(scenario)
    headers = Scenario.member_headers(catalog.member)

    response = scenario.client.create_reservation(
        F.reservation_payload(
            catalog.style_id,
            K.SIZE_M,
            *K.WINDOW_AUG_11_15,
            preferred_unit_id=catalog.unit["id"],
        ),
        headers,
    )

    assert_error(response, ERR_UNIT_WINDOW_COLLISION)
    untouched = scenario.read_unit(catalog.unit["id"])
    assert_unit_position(untouched, availability_state=K.AVAIL_IN_STOCK)
    assert_date(untouched["occupied_until_date"], "2026-08-12", "occupied_until_date")
    assert_fields(scenario.read_member(catalog.member), units_out_count=0)
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=1,
    )


def test_allocation_moves_one_unit_off_the_floor_without_changing_active_depth(
    scenario: Scenario,
) -> None:
    """Reserving a garment spends floor-ready depth but not active depth.

    PRD §3.3: "The second hop moves the chosen unit's `availability_state` from `IN_STOCK` to `RESERVED` and recomputes its `occupied_until_date`, which is the latest `requested_end_date` plus the two buffer days across all reservations holding that unit whose `state` is not `RELEASED`, `CANCELLED` or `SUPERSEDED`, and which is null when no such reservation exists."

    Design: Difficulty/compensating_invariant/unit_position_count_conserved_across_allocate_then_release
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002)
    )
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        active_unit_count=2,
        floor_ready_unit_count=2,
    )

    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_10_16
    )

    assert_fields(reservation, state=K.RES_MATCHED)
    allocated_id = reservation["allocated_unit_id"]
    assert allocated_id is not None, "a matched reservation must name its unit"
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        active_unit_count=2,
        floor_ready_unit_count=1,
    )
    assert_fields(scenario.read_member(catalog.member), units_out_count=1)
    allocated = scenario.read_unit(allocated_id)
    assert_unit_position(allocated, availability_state=K.AVAIL_RESERVED)
    assert_date(allocated["occupied_until_date"], "2026-08-18", "occupied_until_date")


def test_release_restores_the_unit_position_count_with_no_residue(
    scenario: Scenario,
) -> None:
    """Allocate then release returns the fleet to exactly its opening position.

    PRD §3.3: "Both branches also re-derive the affected style's depth fields."

    Design: Difficulty/compensating_invariant/unit_position_count_conserved_across_allocate_then_release
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002)
    )
    headers = Scenario.member_headers(catalog.member)
    before, _ = assert_list(
        scenario.client.list_rental_units(
            scenario.planner, {"style_id": catalog.style_id, "size": K.SIZE_M}
        ),
        total_count=2,
    )
    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_10_16
    )
    allocated_id = reservation["allocated_unit_id"]

    released = assert_ok(
        scenario.client.release_reservation(reservation["id"], headers)
    )

    assert_fields(released, state=K.RES_RELEASED)
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        active_unit_count=2,
        floor_ready_unit_count=2,
    )
    after, _ = assert_list(
        scenario.client.list_rental_units(
            scenario.planner, {"style_id": catalog.style_id, "size": K.SIZE_M}
        ),
        total_count=2,
    )
    assert_position_count_conserved(before, after)
    for row in after:
        assert_unit_position(
            row,
            availability_state=K.AVAIL_IN_STOCK,
            condition_state=K.COND_FLOOR_READY,
        )
    restored = scenario.read_unit(allocated_id)
    assert_fields(restored, turns_completed=0)
    assert_money(restored, realized_revenue_cents=0)
    assert_null(restored, "occupied_until_date")
    assert_fields(
        scenario.read_member(catalog.member),
        units_out_count=0,
        swaps_used_current_month=0,
    )
