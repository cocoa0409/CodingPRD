"""Cascades that travel several aggregates away from the call that started them.

Voiding one rejection unwinds a bad-order stamp, a reclaim, a segment's money, a
settled cycle and a railroad's exposure; a return at the wrong junction reaches
the routing dimension, a penalty, a reclaim lock and the exposure figure.
"""

from test_helpers import (
    ApiClient,
    assert_hours,
    closed_movement_of,
    assert_instant_equals,
    assert_money,
    exposure,
    ledger_entries,
    read_cycle,
    read_movement,
    two_junction_world,
    validate_success,
    void_cascade_world,
)
import test_helpers.factories as f
from test_helpers.fixtures import confirmed_correction, set_clock  # noqa: F401


def _apply_the_void(api, world, rejection):
    """File, confirm and apply the ERRONEOUS_EVENT_VOID over the rejection."""
    payload = f.erroneous_void_payload(rejection["car_id"], rejection["junction_id"],
                                       world.cx, rejection["id"],
                                       filing_note="The car was never refused")
    filed, confirmed = confirmed_correction(api, world, payload, world.bn, world.cx)
    applied = validate_success(
        api.apply_correction_request(filed["id"], {}, world.clerk(world.bn))
    )
    return filed, applied


class TestErroneousVoidCascade:
    """One void reaches the event log, the segment, the claim, the cycle and exposure."""

    def test_the_void_clears_the_stamp_and_disallows_the_claim(self, api: ApiClient):
        """The rejection becomes VOID, the bad-order band vanishes and the credit goes.

        PRD: "Layer four re-examines evidence: any `ALLOWED` reclaim claim whose supporting bad-order stamp has disappeared moves `ALLOWED → DISALLOWED` with `disallow_reason` set to `SUPPORTING_EVENT_VOIDED` and its credit removed from the segment, exactly as described in §3.5."

        Design: Difficulty/transitive_cascade/erroneous_event_void_cascades_five_levels_from_event_to_railroad_exposure
        """
        world, movement, rejection, claim, settled = void_cascade_world(api)
        assert_money(movement["reclaim_credit_cents"], 2843, "reclaim_credit_cents")
        assert_money(movement["net_hire_cents"], 8621, "net_hire_cents")
        assert settled["status"] == "SETTLED"

        filed, applied = _apply_the_void(api, world, rejection)
        assert applied["status"] == "APPLIED"

        voided = validate_success(api.get_interchange_event(rejection["id"],
                                                          world.clerk(world.bn)))
        assert voided["status"] == "VOID"

        decided = validate_success(api.get_reclaim_claim(claim["id"],
                                                       world.accountant(world.bn)))
        assert decided["status"] == "DISALLOWED"
        assert decided["disallow_reason"] == "SUPPORTING_EVENT_VOIDED"
        assert_money(decided["credit_cents"], 0, "credit_cents")

        repriced = read_movement(api, world, movement["id"])
        assert repriced["bad_order_from"] is None
        assert repriced["bad_order_to"] is None
        assert_hours(repriced["chargeable_hours"], 92.00, "chargeable_hours")
        assert_money(repriced["gross_hire_cents"], 11464, "gross_hire_cents")
        assert_money(repriced["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(repriced["net_hire_cents"], 11464, "net_hire_cents")
        assert repriced["recompute_count"] == 1

    def test_the_void_reopens_the_settled_cycle_and_rewrites_exposure(self, api: ApiClient):
        """The cycle returns to REOPENED at 11464 and BN's exposure follows it up.

        PRD: "Layer five reaches the ledger and the statements: for every affected segment already stamped into a cycle a `CORRECTION_ADJUSTMENT` entry is minted for the new net minus the old net, each affected cycle recomputes its money fields — a `SETTLED` cycle being taken back to `REOPENED` first — and both railroads' `per_diem_exposure_cents` and `foreign_car_balance` are refreshed."

        Design: Difficulty/transitive_cascade/erroneous_event_void_cascades_five_levels_from_event_to_railroad_exposure
        """
        world, movement, rejection, claim, settled = void_cascade_world(api)
        assert_money(settled["pre_fee_net_cents"], 8621, "pre_fee_net_cents")
        assert_money(settled["clearinghouse_fee_cents"], 43, "clearinghouse_fee_cents")
        assert_money(settled["net_settlement_cents"], 8578, "net_settlement_cents")

        _apply_the_void(api, world, rejection)

        reopened = read_cycle(api, world, settled["id"])
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert_money(reopened["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(reopened["pre_fee_net_cents"], 11464, "pre_fee_net_cents")
        assert_money(reopened["clearinghouse_fee_cents"], 57, "clearinghouse_fee_cents")
        assert_money(reopened["net_settlement_cents"], 11407, "net_settlement_cents")

        adjustments = sorted(
            row["amount_cents"]
            for row in ledger_entries(api, world.accountant(world.bn))
            if row["entry_type"] == "CORRECTION_ADJUSTMENT"
        )
        assert adjustments == [2843, 8578]

        bn = exposure(api, world, world.bn)
        assert_money(bn["exposure_cents"], 11464, "exposure_cents")
        assert bn["open_movement_count"] == 0


VIOLATING_RETURN_AT = "2026-08-26T06:00:00Z"


def _return_empty(api, world, car_id, junction_id):
    """BN hands the empty car back to CX at the named junction."""
    return validate_success(api.create_interchange_event(
        f.delivery_event_payload(car_id, junction_id, world.bn, world.cx,
                                 VIOLATING_RETURN_AT, 500, "EMPTY"),
        world.clerk(world.bn)), 201)


class TestWrongJunctionReturnCascade:
    """Missing the prescribed junction charges a penalty and locks out reclaims."""

    def test_returning_at_the_wrong_junction_penalises_and_locks_the_segment(self, api: ApiClient):
        """A return at JCT-STL violates the obligation, adds 1950 and nets 9750.

        PRD: "The segment that this delivery has just closed — the violating handling road's own segment — is charged a `reverse_route_penalty_cents` equal to its `time_component_cents` multiplied by 25 percent and rounded half up, so a segment whose time component is 7800 carries a penalty of 1950 and, with no reclaims, nets 9750 rather than 7800."

        Design: Difficulty/transitive_cascade/wrong_junction_empty_return_cascades_to_obligation_penalty_and_reclaim_lock
        """
        world, violator, control = two_junction_world(api)
        before = validate_success(api.get_car(violator, world.owner(world.cx)))
        assert before["routing_status"] == "OBLIGATION_ACTIVE"
        assert before["prescribed_return_junction_id"] == world.jct

        set_clock(api, VIOLATING_RETURN_AT, world)
        _return_empty(api, world, violator, world.junctions["JCT-STL"])

        car = validate_success(api.get_car(violator, world.owner(world.cx)))
        assert car["routing_status"] == "OBLIGATION_VIOLATED"

        segment = closed_movement_of(api, violator, world.bn,
                                    world.accountant(world.bn))
        assert_instant_equals(segment["end_at"], VIOLATING_RETURN_AT, "end_at")
        assert_hours(segment["chargeable_hours"], 50.00, "chargeable_hours")
        assert segment["chargeable_days"] == 3
        assert_money(segment["time_component_cents"], 7800, "time_component_cents")
        assert_money(segment["mileage_component_cents"], 0, "mileage_component_cents")
        assert_money(segment["reverse_route_penalty_cents"], 1950,
                     "reverse_route_penalty_cents")
        assert_money(segment["gross_hire_cents"], 7800, "gross_hire_cents")
        assert_money(segment["net_hire_cents"], 9750, "net_hire_cents")
        assert segment["reclaim_locked"] is True

    def test_the_compliant_return_carries_no_penalty_and_clears_the_obligation(self, api: ApiClient):
        """The car returned at JCT-CHI nets 7800 while its stablemate nets 9750.

        PRD: "When a car standing at `OBLIGATION_ACTIVE` is delivered with `load_status` `EMPTY` at the prescribed junction, to its owner road, at an instant at or before `obligation_due_at`, the routing dimension moves `OBLIGATION_ACTIVE → OBLIGATION_MET` and `prescribed_return_junction_id`, `obligation_issued_at` and `obligation_due_at` are all cleared to null."

        Design: Difficulty/transitive_cascade/wrong_junction_empty_return_cascades_to_obligation_penalty_and_reclaim_lock
        """
        world, violator, control = two_junction_world(api)
        set_clock(api, VIOLATING_RETURN_AT, world)
        _return_empty(api, world, violator, world.junctions["JCT-STL"])
        _return_empty(api, world, control, world.jct)

        car = validate_success(api.get_car(control, world.owner(world.cx)))
        assert car["routing_status"] == "OBLIGATION_MET"
        assert car["prescribed_return_junction_id"] is None
        assert car["obligation_issued_at"] is None
        assert car["obligation_due_at"] is None

        compliant = closed_movement_of(api, control, world.bn,
                                      world.accountant(world.bn))
        assert_money(compliant["time_component_cents"], 7800, "time_component_cents")
        assert_money(compliant["reverse_route_penalty_cents"], 0,
                     "reverse_route_penalty_cents")
        assert_money(compliant["net_hire_cents"], 7800, "net_hire_cents")
        assert compliant["reclaim_locked"] is False

        penalised = closed_movement_of(api, violator, world.bn,
                                      world.accountant(world.bn))
        assert_money(penalised["net_hire_cents"], 9750, "net_hire_cents")

        bn = exposure(api, world, world.bn)
        assert_money(bn["exposure_cents"], 17550, "exposure_cents")
        assert bn["open_movement_count"] == 0
