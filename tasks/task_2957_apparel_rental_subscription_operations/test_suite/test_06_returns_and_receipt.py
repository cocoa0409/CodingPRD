"""Return initiation, the warehouse receipt cascade and late-return fees.

The return journey has two operations and they could hardly be less alike.  The
member's return initiation is a single small write that nevertheless mints the
inbound leg, and the warehouse receipt is the densest cascade in the system,
reaching a shipment, a reservation, the fee ledger, the member, the garment, a
brand-new reverse-logistics job and the style's depth counters in one call.  The
lateness arithmetic is pinned on both sides of its inclusive grace edge and at
the point where the daily fee stops growing against its cap.
"""

from __future__ import annotations

from typing import Optional, Sequence

from test_helpers import constants as K
from test_helpers.assertions import (
    assert_common_fields,
    assert_depth_fields,
    assert_fields,
    assert_instant,
    assert_ledger_entry,
    assert_list,
    assert_money,
    assert_null,
    assert_unit_position,
)
from test_helpers.fixtures import (
    Catalog,
    Scenario,
    Turn,
    standard_catalog,
    turn_to_delivery,
)

JsonDict = dict


def _inbound_leg_in_transit(
    scenario: Scenario,
    catalog: Catalog,
    window: Sequence[str],
    outbound_ship_date: str,
    outbound_carrier: str,
    dispatch_clock: str,
    return_clock: str,
    return_ship_date: str,
    inbound_carrier: str,
    preferred_unit_id: Optional[str] = None,
) -> Turn:
    """Run one turn out to the member and hand the garment back to the carrier.

    Everything short of the warehouse receipt, so the receipt itself is the only
    unobserved operation left in whichever test uses this.
    """
    turn = turn_to_delivery(
        scenario,
        catalog,
        window,
        preferred_unit_id=preferred_unit_id,
        planned_ship_date=outbound_ship_date,
        carrier_reference=outbound_carrier,
        dispatch_clock=dispatch_clock,
    )
    scenario.set_clock(return_clock)
    turn.inbound_leg = scenario.initiate_return(
        catalog.member, turn.reservation_id, return_ship_date
    )
    turn.inbound_leg = scenario.dispatch(
        catalog.inspector, turn.inbound_leg["id"], inbound_carrier
    )
    assert_fields(turn.inbound_leg, state=K.LEG_IN_TRANSIT)
    return turn


def test_return_initiation_mints_the_inbound_leg_for_the_reservation(
    scenario: Scenario,
) -> None:
    """The member's return call answers with a brand-new INBOUND leg.

    PRD §3.5: "The reservation moves `IN_POSSESSION → RETURN_INITIATED`, an `INBOUND` shipping leg is created for it in `state` `CREATED` carrying that planned date, and the garment's unit moves `OUT → INBOUND` with its `version` bumped."
    PRD §3.5: "The created leg is what the response returns."

    Design: Corner/endpoints/endpoint_return_initiation_creates_the_inbound_leg_for_the_reservation
    """
    catalog = standard_catalog(scenario)
    turn = turn_to_delivery(scenario, catalog, K.WINDOW_AUG_05_09)
    assert_fields(
        scenario.read_reservation(turn.reservation_id), state=K.RES_IN_POSSESSION
    )
    unit_before = scenario.read_unit(turn.unit_id)
    assert_unit_position(unit_before, availability_state=K.AVAIL_OUT)

    scenario.set_clock(K.CLOCK_AUG_09_1700)
    # The carrier reference is deliberately omitted so the leg's opening value
    # for that field is observable.
    leg = scenario.initiate_return(
        catalog.member, turn.reservation_id, K.SHIP_DATE_AUG_09
    )

    assert_common_fields(leg, expected_version=1)
    assert_fields(
        leg,
        direction=K.DIRECTION_INBOUND,
        state=K.LEG_CREATED,
        reservation_id=turn.reservation_id,
        member_id=catalog.member_id,
        planned_ship_date=K.SHIP_DATE_AUG_09,
        exception_count=0,
    )
    assert_null(leg, "carrier_reference", "dispatched_at", "delivered_at", "received_at")

    assert_fields(
        scenario.read_reservation(turn.reservation_id), state=K.RES_RETURN_INITIATED
    )
    unit_after = scenario.read_unit(turn.unit_id)
    assert_unit_position(unit_after, availability_state=K.AVAIL_INBOUND)
    assert unit_after["version"] == unit_before["version"] + 1

    rows, _meta = assert_list(
        scenario.client.list_shipments(
            scenario.admin, {"reservation_id": turn.reservation_id}
        ),
        total_count=2,
    )
    outbound = [row for row in rows if row["direction"] == K.DIRECTION_OUTBOUND]
    assert len(outbound) == 1
    assert_fields(outbound[0], state=K.LEG_DELIVERED)


def test_receipt_exactly_on_the_grace_date_costs_nothing(scenario: Scenario) -> None:
    """A turn ending on the 16th may arrive on the 18th for free.

    PRD §3.5: "`late_days` is the number of whole days by which the receipt date exceeds the due date, and it is floored at zero, so it is positive only when the garment arrives strictly after the grace period has elapsed — a receipt landing exactly on the due date yields `late_days` of 0 and no fee at all."
    PRD §3.5: "When `late_fee_cents` is zero, no ledger entry is written at all."

    Design: Difficulty/boundary_precision_check/late_fee_zero_on_receipt_exactly_at_grace_edge
    """
    catalog = standard_catalog(scenario)
    turn = _inbound_leg_in_transit(
        scenario,
        catalog,
        K.WINDOW_AUG_10_16,
        K.SHIP_DATE_AUG_08,
        K.CARRIER_OUT_AUG_08,
        K.CLOCK_AUG_10_0900,
        K.CLOCK_AUG_16_0900,
        K.SHIP_DATE_AUG_16,
        K.CARRIER_IN_AUG_16,
    )

    # 2026-08-16 plus the two grace days is 2026-08-18, the last free day.
    scenario.set_clock(K.CLOCK_AUG_18_0900)
    received = scenario.receive(catalog.inspector, turn.inbound_leg["id"])
    assert_fields(received, state=K.LEG_RECEIVED)
    assert_instant(received["received_at"], K.CLOCK_AUG_18_0900, "received_at")

    returned = scenario.read_reservation(turn.reservation_id)
    assert_fields(returned, state=K.RES_RETURNED, late_days=0, rental_days=8)
    assert_money(returned, late_fee_cents=0)
    assert_instant(returned["returned_at"], K.CLOCK_AUG_18_0900, "returned_at")

    assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=0,
    )
    member = scenario.read_member(catalog.member)
    assert_fields(member, status=K.MEMBER_ACTIVE, late_return_count=0)
    assert_money(member, outstanding_fee_cents=0)

    assert_unit_position(
        scenario.read_unit(turn.unit_id), availability_state=K.AVAIL_PROCESSING
    )


def test_receipt_one_day_past_the_grace_date_costs_a_single_day(
    scenario: Scenario,
) -> None:
    """The 19th is one whole day past the due date and prices at exactly 500 cents.

    PRD §3.5: "The due date is the reservation's `requested_end_date` extended by a grace period of 2 calendar days."
    PRD §3.5: "`late_fee_cents` is 500 cents for each late day, capped at 5,000 cents, meaning the penalty stops growing after ten late days."

    Design: Difficulty/boundary_precision_check/late_fee_zero_on_receipt_exactly_at_grace_edge
    """
    catalog = standard_catalog(scenario)
    turn = _inbound_leg_in_transit(
        scenario,
        catalog,
        K.WINDOW_AUG_10_16,
        K.SHIP_DATE_AUG_08,
        K.CARRIER_OUT_AUG_08,
        K.CLOCK_AUG_10_0900,
        K.CLOCK_AUG_16_0900,
        K.SHIP_DATE_AUG_16,
        K.CARRIER_IN_AUG_16,
    )

    # One day past the 2026-08-18 due date.
    scenario.set_clock(K.CLOCK_AUG_19_0900)
    scenario.receive(catalog.inspector, turn.inbound_leg["id"])

    returned = scenario.read_reservation(turn.reservation_id)
    assert_fields(returned, state=K.RES_RETURNED, late_days=1, rental_days=9)
    assert_money(returned, late_fee_cents=K.LATE_FEE_PER_DAY_CENTS)

    rows, _meta = assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=1,
    )
    assert_ledger_entry(
        rows[0],
        K.LEDGER_LATE_FEE,
        K.LATE_FEE_PER_DAY_CENTS,
        K.LATE_FEE_PER_DAY_CENTS,
        direction=K.DIRECTION_DEBIT,
    )
    assert_fields(rows[0], reservation_id=turn.reservation_id)

    member = scenario.read_member(catalog.member)
    assert_fields(member, status=K.MEMBER_ACTIVE, late_return_count=1)
    assert_money(member, outstanding_fee_cents=K.LATE_FEE_PER_DAY_CENTS)


def test_late_return_fee_is_clamped_by_the_cap_while_late_days_stays_true(
    scenario: Scenario,
) -> None:
    """Eleven late days would price at 5,500 cents, so the ledger records 5,000.

    PRD §3.5: "`late_fee_cents` is 500 cents for each late day, capped at 5,000 cents, meaning the penalty stops growing after ten late days."

    Design: Corner/calculations/calc_late_return_fee_is_clamped_by_the_cap
    """
    catalog = standard_catalog(scenario)
    turn = _inbound_leg_in_transit(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        K.SHIP_DATE_AUG_05,
        K.CARRIER_OUT_AUG_05,
        K.CLOCK_AUG_05_0800,
        K.CLOCK_AUG_21_1000,
        K.SHIP_DATE_AUG_21,
        K.CARRIER_IN_AUG_21,
    )

    # Due 2026-08-11, received 2026-08-22: eleven whole days late.
    scenario.set_clock(K.CLOCK_AUG_22_0900)
    received = scenario.receive(catalog.inspector, turn.inbound_leg["id"])
    assert_fields(received, state=K.LEG_RECEIVED)
    assert_instant(received["received_at"], K.CLOCK_AUG_22_0900, "received_at")

    returned = scenario.read_reservation(turn.reservation_id)
    assert_fields(returned, state=K.RES_RETURNED, late_days=11, rental_days=17)
    # The uncapped figure would be 11 * 500 = 5,500 cents.
    assert 11 * K.LATE_FEE_PER_DAY_CENTS > K.LATE_FEE_CAP_CENTS
    assert_money(returned, late_fee_cents=K.LATE_FEE_CAP_CENTS)

    rows, _meta = assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=1,
    )
    assert_ledger_entry(
        rows[0],
        K.LEDGER_LATE_FEE,
        K.LATE_FEE_CAP_CENTS,
        K.LATE_FEE_CAP_CENTS,
        direction=K.DIRECTION_DEBIT,
    )
    assert_fields(rows[0], reservation_id=turn.reservation_id)

    member = scenario.read_member(catalog.member)
    assert_fields(member, status=K.MEMBER_ACTIVE, late_return_count=1)
    assert_money(member, outstanding_fee_cents=K.LATE_FEE_CAP_CENTS)

    unit = scenario.read_unit(turn.unit_id)
    assert_unit_position(unit, availability_state=K.AVAIL_PROCESSING)
    assert_instant(unit["last_returned_at"], K.CLOCK_AUG_22_0900, "last_returned_at")


def _late_turn_awaiting_receipt(scenario: Scenario):
    """A turn ending 2026-08-16 whose garment reaches the dock on 2026-08-22.

    Four days past the 2026-08-18 due date, so the receipt must price lateness as
    well as move the garment into reconditioning.
    """
    catalog = standard_catalog(scenario)
    turn = _inbound_leg_in_transit(
        scenario,
        catalog,
        K.WINDOW_AUG_10_16,
        K.SHIP_DATE_AUG_08,
        K.CARRIER_OUT_AUG_08,
        K.CLOCK_AUG_10_0900,
        K.CLOCK_AUG_16_0900,
        K.SHIP_DATE_AUG_16,
        K.CARRIER_IN_AUG_16,
    )
    scenario.set_clock(K.CLOCK_AUG_22_0900)
    return catalog, turn


def test_receipt_cascades_through_the_leg_the_turn_and_the_members_balance(
    scenario: Scenario,
) -> None:
    """One receipt call closes the leg, measures the turn and bills the lateness.

    PRD §3.5: "The second hop advances the reservation `RETURN_INITIATED → RETURNED`, stamping its `returned_at` and computing its `rental_days` as the number of whole days from the `delivered_at` calendar date to the `returned_at` calendar date, counting the start day and not counting the return day; `rental_days` is null until the reservation reaches `RETURNED`."
    PRD §3.5: "When `late_fee_cents` is greater than zero, a fee-ledger entry of `kind` `LATE_FEE` is appended for the member with that amount as a debit, the member's `outstanding_fee_cents` is recomputed, and — as the third hop of that ledger append — the member may be tipped `ACTIVE → DELINQUENT` with the full unwinding cascade of §3.2."

    Design: Difficulty/transitive_cascade/inbound_receipt_cascades_shipment_to_job_creation
    """
    catalog, turn = _late_turn_awaiting_receipt(scenario)
    expected_fee = 4 * K.LATE_FEE_PER_DAY_CENTS

    received = scenario.receive(catalog.inspector, turn.inbound_leg["id"])
    assert_fields(received, state=K.LEG_RECEIVED, direction=K.DIRECTION_INBOUND)
    assert_instant(received["received_at"], K.CLOCK_AUG_22_0900, "received_at")

    returned = scenario.read_reservation(turn.reservation_id)
    assert_fields(returned, state=K.RES_RETURNED, rental_days=12, late_days=4)
    assert_instant(returned["returned_at"], K.CLOCK_AUG_22_0900, "returned_at")
    assert expected_fee < K.LATE_FEE_CAP_CENTS
    assert_money(returned, late_fee_cents=expected_fee)

    rows, _meta = assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=1,
    )
    assert_ledger_entry(
        rows[0],
        K.LEDGER_LATE_FEE,
        expected_fee,
        expected_fee,
        direction=K.DIRECTION_DEBIT,
    )
    assert_fields(rows[0], reservation_id=turn.reservation_id)

    member = scenario.read_member(catalog.member)
    assert_money(member, outstanding_fee_cents=expected_fee)
    # 2,000 cents is far below the 15,000-cent delinquency threshold.
    assert expected_fee < K.DELINQUENCY_THRESHOLD_CENTS
    assert_fields(member, status=K.MEMBER_ACTIVE, late_return_count=1)


def test_receipt_cascades_into_the_garment_a_new_job_and_the_style_depth(
    scenario: Scenario,
) -> None:
    """The same call turns the garment over to reverse logistics and re-derives depth.

    PRD §3.5: "The third hop of the receipt turns the garment over to reverse logistics: the unit moves `INBOUND → PROCESSING`, its `last_returned_at` is stamped with the current logical clock instant, and a reverse-logistics job is created for that unit and reservation in `state` `RECEIVED`."
    PRD §3.5: "The fourth hop re-derives the style's `floor_ready_unit_count`, `required_depth_units`, `depth_gap_units` and `replenishment_flag`."

    Design: Difficulty/transitive_cascade/inbound_receipt_cascades_shipment_to_job_creation
    """
    catalog, turn = _late_turn_awaiting_receipt(scenario)

    scenario.receive(catalog.inspector, turn.inbound_leg["id"])

    unit = scenario.read_unit(turn.unit_id)
    assert_unit_position(
        unit,
        availability_state=K.AVAIL_PROCESSING,
        condition_state=K.COND_FLOOR_READY,
    )
    assert_instant(unit["last_returned_at"], K.CLOCK_AUG_22_0900, "last_returned_at")
    # A turn is only counted when the garment is back on the floor.
    assert_fields(unit, turns_completed=0)

    job = scenario.job_for_reservation(catalog.inspector, turn.reservation_id)
    assert_common_fields(job, expected_version=1)
    assert_fields(
        job,
        state=K.JOB_RECEIVED,
        rental_unit_id=turn.unit_id,
        reservation_id=turn.reservation_id,
        cleaning_required=False,
        repair_required=False,
        repair_attempts=0,
        condemned=False,
    )
    assert_money(job, servicing_cost_cents=0)
    assert_null(
        job,
        "inspecting_technician_id",
        "cleaning_completed_at",
        "repair_completed_at",
        "photographed_at",
    )

    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        floor_ready_unit_count=0,
        active_unit_count=1,
        required_depth_units=K.STYLE_GOWN_PLANNED_DEPTH,
        depth_gap_units=K.STYLE_GOWN_PLANNED_DEPTH - 1,
        replenishment_flag=True,
    )

    # Revenue is attributed only when the reservation reaches CLOSED.
    assert_money(
        scenario.read_reservation(turn.reservation_id), revenue_attributed_cents=0
    )
