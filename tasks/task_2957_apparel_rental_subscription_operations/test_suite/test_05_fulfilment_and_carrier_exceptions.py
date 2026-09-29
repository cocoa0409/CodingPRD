"""Outbound fulfilment: leg creation, dispatch, delivery and carrier exceptions.

Physical movement is modelled as shipping legs, and this module walks one leg's
whole life.  It pins the state a leg is born in, the three-resource cascade that
dispatch fires, the two generic state guards on a premature and on a repeated
delivery, the two creation guards — one leg per direction per reservation, and
the plan's shipping cadence measured over a closed window — and finally the
carrier-loss path, where the second exception on a leg retires the garment and
hands the member's reservation back to the waitlist without charging anybody.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_RESOURCE_TERMINAL,
    ERR_SHIPMENT_ALREADY_EXISTS,
    ERR_SHIPMENT_EXCEPTION_CAP_REACHED,
    ERR_SHIPPING_CADENCE_COLLISION,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created,
    assert_depth_fields,
    assert_error,
    assert_fields,
    assert_instant,
    assert_list,
    assert_money,
    assert_not_null,
    assert_null,
    assert_ok,
    assert_unit_position,
)
from test_helpers.fixtures import Catalog, Scenario, standard_catalog

JsonDict = dict


def _matched_reservation(scenario: Scenario, catalog: Catalog) -> JsonDict:
    """One matched reservation on the standard gown, holding the only unit."""
    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )
    assert_fields(reservation, state=K.RES_MATCHED)
    return reservation


def _leg_awaiting_dispatch(scenario: Scenario, catalog: Catalog):
    """A matched reservation and a freshly created outbound leg for it."""
    reservation = _matched_reservation(scenario, catalog)
    leg = scenario.create_outbound_leg(
        reservation["id"], K.SHIP_DATE_AUG_05, K.CARRIER_OUT_AUG_05
    )
    return reservation, leg


def test_a_new_outbound_leg_opens_in_created_with_every_timestamp_null(
    scenario: Scenario,
) -> None:
    """A leg is born in CREATED with no carrier reference and no timestamps.

    PRD §3.4: "The leg's `member_id` is copied from the linked reservation rather than supplied, and the leg opens in `state` `CREATED` with `exception_count` at 0 and `carrier_reference`, `dispatched_at`, `delivered_at`, `received_at` and `exception_reason` all null."

    Design: Corner/state_machines/state_shipment_is_born_in_created_with_no_timestamps
    """
    catalog = standard_catalog(scenario)
    reservation = _matched_reservation(scenario, catalog)

    # The carrier reference is left out of the body so the field's opening
    # value is observable rather than overwritten by the request.
    leg = assert_created(
        scenario.client.create_shipment(
            F.outbound_shipment_payload(reservation["id"], K.SHIP_DATE_AUG_05),
            scenario.admin,
        )
    )
    assert_common_fields(leg, expected_version=1)
    assert_fields(
        leg,
        state=K.LEG_CREATED,
        direction=K.DIRECTION_OUTBOUND,
        exception_count=0,
        reservation_id=reservation["id"],
        member_id=catalog.member_id,
        planned_ship_date=K.SHIP_DATE_AUG_05,
    )
    assert_null(
        leg,
        "carrier_reference",
        "dispatched_at",
        "delivered_at",
        "received_at",
        "exception_reason",
    )

    # The garment has not moved: only the allocation touched it.
    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]),
        availability_state=K.AVAIL_RESERVED,
        condition_state=K.COND_FLOOR_READY,
    )
    assert_fields(scenario.read_reservation(reservation["id"]), state=K.RES_MATCHED)


def test_dispatch_moves_the_leg_the_reservation_and_the_unit_together(
    scenario: Scenario,
) -> None:
    """One dispatch call advances three resources and stamps two instants.

    PRD §3.4: "On an `OUTBOUND` leg only, dispatch cascades: the reservation moves `MATCHED → SHIPPED` with `shipped_at` stamped, and the allocated unit moves `RESERVED → OUT`."

    Design: Corner/state_machines/state_shipment_dispatch_moves_reservation_and_unit_in_the_same_request
    """
    catalog = standard_catalog(scenario)
    reservation, leg = _leg_awaiting_dispatch(scenario, catalog)

    scenario.set_clock(K.CLOCK_AUG_05_0800)
    dispatched = assert_ok(
        scenario.client.dispatch_shipment(
            leg["id"],
            Scenario.tech_headers(catalog.inspector),
            F.dispatch_payload(K.CARRIER_TRACK_99001),
        )
    )
    assert_fields(
        dispatched,
        state=K.LEG_IN_TRANSIT,
        carrier_reference=K.CARRIER_TRACK_99001,
        exception_count=0,
    )
    assert_instant(dispatched["dispatched_at"], K.CLOCK_AUG_05_0800, "dispatched_at")
    assert_null(dispatched, "delivered_at", "received_at", "exception_reason")

    shipped = scenario.read_reservation(reservation["id"])
    assert_fields(shipped, state=K.RES_SHIPPED, allocated_unit_id=catalog.unit["id"])
    assert_instant(shipped["shipped_at"], K.CLOCK_AUG_05_0800, "shipped_at")
    assert_null(shipped, "delivered_at")

    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]),
        availability_state=K.AVAIL_OUT,
        condition_state=K.COND_FLOOR_READY,
    )


def test_delivery_on_a_leg_that_was_never_dispatched_is_an_undeclared_transition(
    scenario: Scenario,
) -> None:
    """Delivery is declared out of IN_TRANSIT only, so a CREATED leg refuses it.

    PRD §2.5: "Ranks 15 and 16 are the two generic state guards, and their order matters: rank 15 rejects a request whose trigger is not a declared transition out of the target resource's **current, non-terminal** state with `ERR_INVALID_STATE_TRANSITION` (409), while rank 16 rejects an action aimed at a resource that already sits in one of its declared terminal states with `ERR_RESOURCE_TERMINAL` (409)."

    Design: Corner/state_machines/state_shipment_delivery_before_dispatch_returns_invalid_state_transition
    """
    catalog = standard_catalog(scenario)
    reservation, leg = _leg_awaiting_dispatch(scenario, catalog)

    assert_error(
        scenario.client.deliver_shipment(
            leg["id"], Scenario.tech_headers(catalog.inspector)
        ),
        ERR_INVALID_STATE_TRANSITION,
    )

    # No side effect of any kind: the leg, the reservation and the garment all
    # sit exactly where they were.
    untouched = scenario.read_shipment(leg["id"])
    assert_common_fields(untouched, expected_version=1)
    assert_fields(untouched, state=K.LEG_CREATED)
    assert_null(untouched, "dispatched_at", "delivered_at")
    assert_fields(scenario.read_reservation(reservation["id"]), state=K.RES_MATCHED)
    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]), availability_state=K.AVAIL_RESERVED
    )


def test_second_delivery_on_a_delivered_leg_reports_terminality(
    scenario: Scenario,
) -> None:
    """DELIVERED is terminal for a leg, so a replayed delivery is not a transition.

    PRD §3.4: "The leg lifecycle runs across `CREATED`, `IN_TRANSIT`, `EXCEPTION`, `DELIVERED` and `RECEIVED`, of which `DELIVERED` and `RECEIVED` are terminal — an action aimed at a leg already in either is refused at rank 16 with `ERR_RESOURCE_TERMINAL`, and an unresolvable leg identifier yields `ERR_SHIPMENT_NOT_FOUND`."

    Design: Corner/state_machines/state_second_delivery_on_a_delivered_shipment_returns_resource_terminal
    """
    catalog = standard_catalog(scenario)
    reservation, leg = _leg_awaiting_dispatch(scenario, catalog)

    scenario.set_clock(K.CLOCK_AUG_05_0800)
    scenario.dispatch(catalog.inspector, leg["id"])
    delivered = scenario.deliver(catalog.inspector, leg["id"])
    assert_fields(delivered, state=K.LEG_DELIVERED)
    assert_instant(delivered["delivered_at"], K.CLOCK_AUG_05_0800, "delivered_at")

    # A later clock would make any second stamp visible if one were applied.
    scenario.set_clock(K.CLOCK_AUG_06_0800)
    assert_error(
        scenario.client.deliver_shipment(
            leg["id"], Scenario.tech_headers(catalog.inspector)
        ),
        ERR_RESOURCE_TERMINAL,
    )

    replayed = scenario.read_shipment(leg["id"])
    assert_fields(replayed, state=K.LEG_DELIVERED, version=delivered["version"])
    assert_instant(replayed["delivered_at"], K.CLOCK_AUG_05_0800, "delivered_at")
    assert_fields(
        scenario.read_reservation(reservation["id"]), state=K.RES_IN_POSSESSION
    )


def test_second_outbound_leg_for_one_reservation_is_refused(scenario: Scenario) -> None:
    """A reservation already holding a CREATED outbound leg cannot get another.

    PRD §3.4: "At rank 39, duplicate legs are refused with `ERR_SHIPMENT_ALREADY_EXISTS` (409): a reservation may never have a second `INBOUND` leg, and for an `OUTBOUND` creation it may not already have an `OUTBOUND` leg in any state other than `EXCEPTION`."

    Design: Corner/validations/validation_second_outbound_shipment_for_one_reservation_is_refused
    """
    catalog = standard_catalog(scenario)
    reservation, first = _leg_awaiting_dispatch(scenario, catalog)
    assert_fields(first, state=K.LEG_CREATED)

    duplicate = scenario.client.create_shipment(
        F.outbound_shipment_payload(
            reservation["id"], K.SHIP_DATE_AUG_05, K.CARRIER_OUT_DUPLICATE
        ),
        scenario.admin,
    )
    # Rank 39 outranks the rank-43 cadence rule that the identical planned date
    # would also trip, so duplication is what the client is told about.
    assert_error(duplicate, ERR_SHIPMENT_ALREADY_EXISTS)

    rows, _meta = assert_list(
        scenario.client.list_shipments(
            scenario.admin, {"reservation_id": reservation["id"]}
        ),
        total_count=1,
    )
    assert_fields(rows[0], id=first["id"], carrier_reference=K.CARRIER_OUT_AUG_05)


def _member_with_one_planned_leg(scenario: Scenario):
    """Two matched reservations for one member, the first already holding a leg.

    The first leg is planned for the 8th, so with the SIG4 cadence of 7 days the
    closed exclusion window runs from the 8th to the 15th inclusive.  Two units
    are stocked so the second reservation matches rather than waitlisting.
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002)
    )
    assert_fields(catalog.plan, shipping_cadence_days=K.PLAN_SIG4_CADENCE_DAYS)

    first = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_10_16
    )
    assert_fields(first, state=K.RES_MATCHED)
    planned = scenario.create_outbound_leg(
        first["id"], K.SHIP_DATE_AUG_08, K.CARRIER_OUT_AUG_08
    )
    assert_fields(
        planned, state=K.LEG_CREATED, planned_ship_date=K.SHIP_DATE_AUG_08
    )

    second = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_20_26
    )
    assert_fields(second, state=K.RES_MATCHED)
    return catalog, planned, second


def test_outbound_leg_on_the_closing_cadence_day_collides(scenario: Scenario) -> None:
    """The 15th is the last inclusive day of a 7-day window opened on the 8th.

    PRD §3.4: "For an `OUTBOUND` leg, no other `OUTBOUND` leg of the same member whose state is anything other than `EXCEPTION` may have a `planned_ship_date` inside the **closed** window that starts at that other leg's `planned_ship_date` and extends forward by the plan's `shipping_cadence_days`; both endpoints of that window are inclusive."

    Design: Difficulty/resource_temporal_overlap/member_outbound_cadence_window_is_closed_on_both_ends
    """
    catalog, _planned, second = _member_with_one_planned_leg(scenario)

    refused = scenario.client.create_shipment(
        F.outbound_shipment_payload(
            second["id"], K.SHIP_DATE_AUG_15, K.CARRIER_OUT_AUG_15
        ),
        scenario.admin,
    )
    assert_error(refused, ERR_SHIPPING_CADENCE_COLLISION)

    # Nothing was created, so the member still has exactly the one planned leg.
    assert_list(
        scenario.client.list_shipments(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=1,
    )
    assert_list(
        scenario.client.list_shipments(
            scenario.admin, {"reservation_id": second["id"]}
        ),
        total_count=0,
    )


def test_outbound_leg_one_day_past_the_cadence_window_is_accepted(
    scenario: Scenario,
) -> None:
    """The 16th sits one day beyond the closed window and is allowed through.

    PRD §3.4: "For a plan with a cadence of 7 days and an existing leg planned for the 10th of the month, a new leg planned for the 17th collides while one planned for the 18th does not."

    Design: Difficulty/resource_temporal_overlap/member_outbound_cadence_window_is_closed_on_both_ends
    """
    catalog, planned, second = _member_with_one_planned_leg(scenario)

    accepted = assert_created(
        scenario.client.create_shipment(
            F.outbound_shipment_payload(
                second["id"], K.SHIP_DATE_AUG_16, K.CARRIER_OUT_AUG_16
            ),
            scenario.admin,
        )
    )
    assert_common_fields(accepted, expected_version=1)
    assert_fields(
        accepted,
        state=K.LEG_CREATED,
        direction=K.DIRECTION_OUTBOUND,
        planned_ship_date=K.SHIP_DATE_AUG_16,
        reservation_id=second["id"],
        member_id=catalog.member_id,
        exception_count=0,
    )
    assert accepted["id"] != planned["id"]

    assert_list(
        scenario.client.list_shipments(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=2,
    )


def _leg_back_in_transit_after_one_exception(scenario: Scenario):
    """Dispatch a garment, record one carrier exception and re-dispatch the leg.

    The leg lands back in ``IN_TRANSIT`` carrying an ``exception_count`` of 1, so
    exactly one exception is left before the cap of 2 turns the leg into a loss.
    """
    catalog = standard_catalog(scenario)
    reservation, leg = _leg_awaiting_dispatch(scenario, catalog)

    scenario.set_clock(K.CLOCK_AUG_05_0800)
    scenario.dispatch(catalog.inspector, leg["id"])

    excepted = scenario.record_exception(
        catalog.inspector, leg["id"], K.EXCEPTION_REASON_SCAN_GAP
    )
    assert_fields(
        excepted,
        state=K.LEG_EXCEPTION,
        exception_count=1,
        exception_reason=K.EXCEPTION_REASON_SCAN_GAP,
    )
    assert excepted["exception_count"] < K.SHIPMENT_EXCEPTION_CAP

    recovered = scenario.dispatch(catalog.inspector, leg["id"], K.CARRIER_OUT_RETRY_1)
    assert_fields(
        recovered,
        state=K.LEG_IN_TRANSIT,
        exception_count=1,
        carrier_reference=K.CARRIER_OUT_RETRY_1,
    )
    return catalog, reservation, leg


def test_second_exception_retires_the_unit_and_waitlists_the_reservation(
    scenario: Scenario,
) -> None:
    """The exception that reaches the cap is a loss: garment gone, member unbilled.

    PRD §3.4: "The second hop retires the unit: its `availability_state` becomes `RETIRED`, its `retirement_reason` becomes `LOSS`, its `retired_at` is stamped with the current clock, and its `condition_state` becomes `CONDEMNED`."
    PRD §3.4: "On an `OUTBOUND` leg the reservation moves `SHIPPED → WAITLISTED`: its `allocated_unit_id` and `matched_at` are cleared to null and a fresh `waitlist_position` is computed, which closes the reservation cycle `MATCHED → SHIPPED → WAITLISTED → MATCHED` and gives the member another shot at the style without penalty."

    Design: Corner/state_machines/state_shipment_exception_cap_retires_the_unit_and_waitlists_the_reservation
    """
    catalog, reservation, leg = _leg_back_in_transit_after_one_exception(scenario)
    unit_id = catalog.unit["id"]

    scenario.set_clock(K.CLOCK_AUG_07_1200)
    lost = scenario.record_exception(
        catalog.inspector, leg["id"], K.EXCEPTION_REASON_PARCEL_LOST
    )
    assert_fields(
        lost,
        state=K.LEG_EXCEPTION,
        exception_count=K.SHIPMENT_EXCEPTION_CAP,
        exception_reason=K.EXCEPTION_REASON_PARCEL_LOST,
    )

    retired = scenario.read_unit(unit_id)
    assert_unit_position(
        retired,
        availability_state=K.AVAIL_RETIRED,
        condition_state=K.COND_CONDEMNED,
    )
    assert_fields(retired, retirement_reason=K.RETIREMENT_LOSS)
    assert_instant(retired["retired_at"], K.CLOCK_AUG_07_1200, "retired_at")

    waitlisted = scenario.read_reservation(reservation["id"])
    assert_fields(waitlisted, state=K.RES_WAITLISTED, waitlist_position=1)
    assert_null(waitlisted, "allocated_unit_id", "matched_at")

    # The carrier's failure is not the member's debt.
    assert_money(scenario.read_member(catalog.member), outstanding_fee_cents=0)
    assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=0,
    )

    # The fleet just lost a garment, so the style's depth is re-derived.
    assert_depth_fields(
        scenario.read_style(catalog.style_id),
        active_unit_count=0,
        floor_ready_unit_count=0,
        required_depth_units=K.STYLE_GOWN_PLANNED_DEPTH,
        depth_gap_units=K.STYLE_GOWN_PLANNED_DEPTH,
        replenishment_flag=True,
    )


def test_redispatch_is_refused_once_the_exception_cap_is_reached(
    scenario: Scenario,
) -> None:
    """A leg may cycle out of EXCEPTION exactly once; the second recovery fails.

    PRD §3.4: "Re-dispatching out of `EXCEPTION` additionally requires, at rank 38, that the leg's `exception_count` still be strictly below the cap of 2, otherwise `ERR_SHIPMENT_EXCEPTION_CAP_REACHED` (409)."

    Design: Corner/validations/validation_redispatch_is_refused_once_the_exception_cap_is_reached
    """
    catalog, reservation, leg = _leg_back_in_transit_after_one_exception(scenario)

    scenario.set_clock(K.CLOCK_AUG_07_1200)
    at_cap = scenario.record_exception(
        catalog.inspector, leg["id"], K.EXCEPTION_REASON_LOST_IN_TRANSIT
    )
    assert_fields(at_cap, exception_count=K.SHIPMENT_EXCEPTION_CAP)

    refused = scenario.client.dispatch_shipment(
        leg["id"],
        Scenario.tech_headers(catalog.inspector),
        F.dispatch_payload(K.CARRIER_OUT_RETRY_2),
    )
    assert_error(refused, ERR_SHIPMENT_EXCEPTION_CAP_REACHED)

    frozen = scenario.read_shipment(leg["id"])
    assert_fields(
        frozen,
        state=K.LEG_EXCEPTION,
        exception_count=K.SHIPMENT_EXCEPTION_CAP,
        exception_reason=K.EXCEPTION_REASON_LOST_IN_TRANSIT,
        carrier_reference=K.CARRIER_OUT_RETRY_1,
        version=at_cap["version"],
    )
    assert_not_null(frozen, "dispatched_at")
    assert_null(frozen, "delivered_at", "received_at")

    assert_fields(
        scenario.read_reservation(reservation["id"]), state=K.RES_WAITLISTED
    )
    assert_unit_position(
        scenario.read_unit(catalog.unit["id"]),
        availability_state=K.AVAIL_RETIRED,
        condition_state=K.COND_CONDEMNED,
    )
