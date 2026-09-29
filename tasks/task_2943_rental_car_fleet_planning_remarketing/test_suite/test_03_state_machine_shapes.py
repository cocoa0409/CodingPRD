"""State machines whose shape is not a straight line.

A vehicle carries two orthogonal status dimensions that advance on unrelated
triggers, and a redistribution order re-enters a status it has already left a
bounded number of times.
"""

from test_helpers import (
    FLEET_PLANNER_ALT_ID,
    FLEET_PLANNER_ID,
    ApiErrorId,
    ConditionStatus,
    DamageStatus,
    FleetStatus,
    OrderStatus,
    fixtures,
    make_fleet_planner_headers,
    validate_error,
)
from test_helpers.assertions import (
    assert_no_version_bump,
    assert_redistribution_order,
    assert_version_bump,
)


def _car_with_an_authorized_haul_and_an_open_claim(client, world):
    """An IN_SERVICE car at ATL carrying a signed-off haul and a fresh claim."""
    built = fixtures.setup_in_service_vehicle(
        client, world, market_code="ATL", program_key="PGM"
    )
    vehicle_id = built["vehicle"]["id"]
    order = fixtures.setup_authorized_order(
        client, world, vehicle_id, destination_code="DFW", distance_km=200
    )
    event = fixtures.report_damage(client, world, vehicle_id, 300000, market_code="ATL")
    return {"vehicle_id": vehicle_id, "order_id": order["id"], "event_id": event["id"]}


class TestVehicleParallelDimensions:
    """Fleet lifecycle and physical condition move on separate triggers."""

    def test_damage_report_moves_the_condition_dimension_only(self, client, world):
        """The claim is filed and the car is still rentable on the fleet axis.

        PRD 2.11: "A `Vehicle` carries **two independent status dimensions on the
        same row**, and they must be evaluated and mutated separately."
        PRD 2.11: "Reporting damage moves `condition_status` and leaves
        `fleet_status` untouched; dispatching a transfer moves `fleet_status` and
        leaves `condition_status` untouched."
        PRD 3.7: "The event is created in `status` `REPORTED` with a null
        `recovery_source`, a null `recovered_cents`, null recovery buckets, a
        null `salvage_proceeds_cents` and a null `total_loss_gain_loss_cents`,
        and the vehicle moves `SOUND → DAMAGE_REPORTED` or `RECONDITIONED →
        DAMAGE_REPORTED` on its condition dimension with its `version`
        incremented by 1 — the vehicle's `fleet_status` is left completely
        untouched."

        Design: Difficulty/non_linear_state_machine/vehicle_fleet_and_condition_dimensions_advance_independently
        """
        built = _car_with_an_authorized_haul_and_an_open_claim(client, world)

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["condition_status"] == ConditionStatus.DAMAGE_REPORTED
        assert vehicle["fleet_status"] == FleetStatus.IN_SERVICE

        event = fixtures.read_damage_event(client, built["event_id"])
        assert event["status"] == DamageStatus.REPORTED
        assert event["total_loss_required"] is False

    def test_depart_moves_the_fleet_dimension_while_the_claim_still_stands(
        self, client, world
    ):
        """The haul leaves with a damaged car and the condition axis does not move.

        PRD 3.6: "Departure stamps `depart_at` from the logical clock, drives the
        vehicle `IN_SERVICE → IN_TRANSIT`, **decrements** the origin market's
        `in_service_unit_count` by 1, and increments both the order's and the
        vehicle's `version` by 1."
        PRD 2.11: "Both dimensions are cyclic: a unit may leave and re-enter
        `IN_SERVICE` through `IN_TRANSIT` and through `HELD_FOR_SALE`, and a car
        may return to `SOUND` after reconditioning and then be damaged again."

        Design: Difficulty/non_linear_state_machine/vehicle_fleet_and_condition_dimensions_advance_independently
        """
        built = _car_with_an_authorized_haul_and_an_open_claim(client, world)

        fixtures.depart_order(client, world, built["order_id"], "ATL")

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        assert vehicle["fleet_status"] == FleetStatus.IN_TRANSIT
        assert vehicle["condition_status"] == ConditionStatus.DAMAGE_REPORTED

    def test_all_four_combined_states_are_observable_across_the_two_axes(
        self, client, world
    ):
        """Settling mid-haul frees the condition axis with the car still in transit.

        PRD 3.7: "**Branch A** opens a recovery: a `RemarketingManager` moves it
        `REPORTED → RECOVERY_PENDING`, supplying a `recovery_source` of
        `CUSTOMER`, `THIRD_PARTY_INSURER` or `OWN_INSURANCE`."
        PRD 3.7: "When an event reaches `RECOVERED` or `WRITTEN_OFF`, the system
        counts the vehicle's remaining damage events whose `status` is
        `REPORTED` or `RECOVERY_PENDING`; if that count is zero **after** the
        triggering transition and the vehicle's `condition_status` is still
        `DAMAGE_REPORTED`, the vehicle moves `DAMAGE_REPORTED → SOUND` with its
        `version` incremented by 1."
        PRD 3.6: "Receipt stamps `receive_at` from the logical clock, stores
        `actual_transport_cost_cents`, rewrites the vehicle's `current_market_id`
        to the order's `destination_market_id`, replaces the vehicle's
        `odometer_km` with the submitted cumulative reading under the
        anti-regression rule, drives the vehicle `IN_TRANSIT → IN_SERVICE`,
        **increments** the destination market's `in_service_unit_count` by 1,
        posts a ledger line of `entry_type` `TRANSPORT_COST` for a positive
        `amount_cents` equal to `actual_transport_cost_cents` with
        `source_entity_type` `RedistributionOrder`, and increments both the
        order's and the vehicle's `version` by 1."

        Design: Difficulty/non_linear_state_machine/vehicle_fleet_and_condition_dimensions_advance_independently
        """
        built = _car_with_an_authorized_haul_and_an_open_claim(client, world)
        observed = []

        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        observed.append((vehicle["fleet_status"], vehicle["condition_status"]))

        fixtures.depart_order(client, world, built["order_id"], "ATL")
        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        observed.append((vehicle["fleet_status"], vehicle["condition_status"]))

        fixtures.open_recovery(client, built["event_id"])
        mid_claim = fixtures.read_vehicle(client, built["vehicle_id"])
        assert fixtures.read_damage_event(client, built["event_id"])["status"] == (
            DamageStatus.RECOVERY_PENDING
        )
        assert mid_claim["fleet_status"] == FleetStatus.IN_TRANSIT
        assert mid_claim["condition_status"] == ConditionStatus.DAMAGE_REPORTED

        fixtures.settle_recovery(client, built["event_id"], 200000)
        assert fixtures.read_damage_event(client, built["event_id"])["status"] == (
            DamageStatus.RECOVERED
        )
        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        observed.append((vehicle["fleet_status"], vehicle["condition_status"]))

        fixtures.receive_order(
            client,
            world,
            built["order_id"],
            "DFW",
            actual_transport_cost_cents=61500,
            odometer_km=200,
        )
        vehicle = fixtures.read_vehicle(client, built["vehicle_id"])
        observed.append((vehicle["fleet_status"], vehicle["condition_status"]))
        assert vehicle["current_market_id"] == world.market_id("DFW")

        assert observed == [
            (FleetStatus.IN_SERVICE, ConditionStatus.DAMAGE_REPORTED),
            (FleetStatus.IN_TRANSIT, ConditionStatus.DAMAGE_REPORTED),
            (FleetStatus.IN_TRANSIT, ConditionStatus.SOUND),
            (FleetStatus.IN_SERVICE, ConditionStatus.SOUND),
        ], "the two dimensions must be stored separately to reach these pairs"


class TestRedistributionRevisionCycle:
    """The propose/reject loop re-enters PROPOSED at most three times."""

    def _drafted_haul(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client, world, market_code="ATL", program_key="PGM"
        )
        order = fixtures.draft_order(
            client, built["vehicle"]["id"], world.market_id("DFW"), distance_km=200
        )
        return order

    def test_the_first_proposal_is_not_a_revision(self, client, world):
        """DRAFT to PROPOSED leaves the counter at zero, and so does the rejection.

        PRD 3.6: "A `FleetPlanner` proposes a `DRAFT` order, moving it `DRAFT →
        PROPOSED`; the order must be in `DRAFT` and the vehicle must still be
        `IN_SERVICE`, and the transition writes `proposed_by_user_id` from the
        acting operator and increments `version` by 1."
        PRD 3.6: "A `FleetController` may then reject it, moving it `PROPOSED →
        REJECTED` with a `rejection_reason` taken from the request body and
        `version` incremented by 1."

        Design: Difficulty/non_linear_state_machine/redistribution_reject_repropose_cycle_capped_at_three_revisions
        """
        order = self._drafted_haul(client, world)
        assert_redistribution_order(
            order, {"status": OrderStatus.DRAFT, "revision_count": 0}
        )

        proposed = fixtures.propose_order(client, order["id"])
        assert proposed["status"] == OrderStatus.PROPOSED
        assert proposed["revision_count"] == 0
        assert proposed["proposed_by_user_id"] is not None
        assert_version_bump(order, proposed)

        rejected = fixtures.reject_order(
            client, order["id"], reason="Haul window collides with the DFW intake."
        )
        assert rejected["status"] == OrderStatus.REJECTED
        assert rejected["revision_count"] == 0
        assert rejected["rejection_reason"] == "Haul window collides with the DFW intake."
        assert_version_bump(proposed, rejected)

    def test_each_reproposal_advances_the_counter_and_clears_the_reason(
        self, client, world
    ):
        """The counter only advances on the REJECTED to PROPOSED re-entry edge.

        PRD 3.6: "A rejected order may be re-proposed by a `FleetPlanner`, moving
        it `REJECTED → PROPOSED`: the order must be in `REJECTED`, its
        `revision_count` must be strictly less than three, and the vehicle must
        still be `IN_SERVICE`."
        PRD 3.6: "Re-proposal increments `revision_count` by 1, **rewrites**
        `proposed_by_user_id` to the acting operator, clears `rejection_reason`
        back to null, and increments `version` by 1."

        Design: Difficulty/non_linear_state_machine/redistribution_reject_repropose_cycle_capped_at_three_revisions
        """
        order = self._drafted_haul(client, world)
        fixtures.propose_order(client, order["id"])
        fixtures.reject_order(client, order["id"], reason="First look.")

        for expected_count in (1, 2, 3):
            reproposed = fixtures.propose_order(client, order["id"])
            assert reproposed["status"] == OrderStatus.PROPOSED
            assert reproposed["revision_count"] == expected_count
            assert reproposed["rejection_reason"] is None
            fixtures.reject_order(
                client, order["id"], reason=f"Look number {expected_count + 1}."
            )

    def test_the_fourth_reproposal_is_refused_and_leaves_the_order_in_rejected(
        self, client, world
    ):
        """The refused re-entry parks the order in REJECTED with no partial state.

        PRD 3.6: "The loop is therefore bounded: an order may be rejected and
        re-proposed three times, and the fourth re-proposal attempt — made while
        `revision_count` already reads 3 — is refused with
        `ERR_REVISION_LIMIT_REACHED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/redistribution_reject_repropose_cycle_capped_at_three_revisions
        """
        order = self._drafted_haul(client, world)
        fixtures.propose_order(client, order["id"])
        fixtures.reject_order(client, order["id"], reason="First look.")
        for round_number in (1, 2, 3):
            fixtures.propose_order(client, order["id"])
            fixtures.reject_order(client, order["id"], reason=f"Look {round_number}.")

        before = fixtures.read_order(client, order["id"])
        assert before["revision_count"] == 3

        validate_error(
            client.propose_order(order["id"], make_fleet_planner_headers()),
            ApiErrorId.REVISION_LIMIT_REACHED,
        )

        after = fixtures.read_order(client, order["id"])
        assert after["status"] == OrderStatus.REJECTED
        assert after["revision_count"] == 3
        assert_no_version_bump(before, after)

    def test_the_latest_proposer_is_the_segregation_subject_after_a_revision(
        self, client, world
    ):
        """Re-proposal rewrites the proposer, so the two-man check follows it.

        PRD 3.6: "Because `proposed_by_user_id` is rewritten each time, the
        segregation-of-duties subject for authorization is always the **latest**
        proposer."

        Design: Difficulty/non_linear_state_machine/redistribution_reject_repropose_cycle_capped_at_three_revisions
        """
        order = self._drafted_haul(client, world)
        first = fixtures.propose_order(client, order["id"])
        fixtures.reject_order(client, order["id"], reason="First look.")
        second = fixtures.propose_order(
            client, order["id"], planner_id=FLEET_PLANNER_ALT_ID
        )

        assert first["proposed_by_user_id"] == FLEET_PLANNER_ID
        assert second["proposed_by_user_id"] == FLEET_PLANNER_ALT_ID
        assert second["revision_count"] == 1
