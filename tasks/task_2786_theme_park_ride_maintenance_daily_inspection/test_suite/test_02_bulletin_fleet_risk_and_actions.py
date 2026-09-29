"""Fleet risk scoring and the parts gate on fleet-action verification.

The two risk figures are computed over one evaluated set but treat deferral
differently, and an action linked to an outstanding requisition cannot be closed
out until the part is physically in the shop.
"""

import pytest

from test_helpers import (
    MANAGER,
    TECHNICIAN,
    api_client,
    assert_bulletin_risk_shape,
    fixtures,
    make_qualified_inspector_headers,
    validate_error,
    validate_success,
)

FLEET_MANUFACTURER = "Intamin"
FLEET_MODEL = "MegaLite-3"


def _overdue_mandatory_fleet():
    """Three matching units, one action started and one deferred, five days overdue."""
    unit_one = fixtures.create_attraction(
        name="Thunder Spiral",
        park_area="SKYLINE",
        manufacturer=FLEET_MANUFACTURER,
        model_code=FLEET_MODEL,
        ride_class="THRILL",
        theoretical_hourly_capacity=900,
        min_operators_required=3,
        parts_budget_cents=1000000,
    )
    unit_two = fixtures.create_attraction(
        name="Lagoon Skimmer",
        park_area="LAGOON",
        manufacturer=FLEET_MANUFACTURER,
        model_code=FLEET_MODEL,
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    unit_three = fixtures.create_attraction(
        name="Cove Hopper",
        park_area="KIDS_COVE",
        manufacturer=FLEET_MANUFACTURER,
        model_code=FLEET_MODEL,
        ride_class="KIDDIE",
        theoretical_hourly_capacity=400,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    bundle = fixtures.acknowledged_bulletin_with_actions(
        bulletin_ref="SB-2026-118",
        manufacturer=FLEET_MANUFACTURER,
        model_code=FLEET_MODEL,
        severity="MANDATORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-08-05",
        attractions=[unit_one, unit_two, unit_three],
    )
    actions = bundle["actions"]
    fixtures.start_action(actions[1]["id"])
    fixtures.defer_action(
        actions[2]["id"], "Retrofit kit backordered", "2026-08-04"
    )
    fixtures.set_clock("2026-08-10T00:00:00.000Z")
    return bundle


def test_per_unit_max_score_is_the_worst_single_action_and_ignores_escalation():
    """The committee figure is the greatest individual score, escalation excluded.

    PRD §3.6: "`per_unit_max_score` is the number the safety committee uses to
    decide whether a single unit must be pulled: it is simply the greatest
    individual action score in the set, and it ignores the escalation factor
    entirely."
    PRD §3.6: "The raw score is the severity base multiplied by the ride-class
    factor multiplied by the status factor, with the overdue points added
    afterwards."

    Design: Difficulty/dual_variant_calc/bulletin_risk_fleet_aggregate_escalation_vs_per_unit_max
    """
    bundle = _overdue_mandatory_fleet()

    data = validate_success(
        api_client.get_bulletin_risk(bundle["bulletin"]["id"], MANAGER)
    )
    assert_bulletin_risk_shape(data)

    assert data["per_unit_max_score"] == pytest.approx(55.50, abs=0.01), (
        "the PENDING thrill unit scores 40 * 1.2 * 1.0 plus 7.5 overdue points"
    )


def test_the_fleet_aggregate_multiplies_the_rounded_mean_by_the_escalation_factor():
    """Deferral raises the dashboard number through the escalation factor alone.

    PRD §3.6: "The `escalation_factor` reflects how much of the fleet has been
    deferred: it is 1 plus 0.05 for each action in the evaluated set whose `status`
    is `DEFERRED`, so `deferred_action_count` deferrals give a factor of 1 plus five
    hundredths times that count."
    PRD §3.6: "first the arithmetic mean of the per-action scores — their sum
    divided by the number of actions in the set — is rounded half up to 2 decimal
    places, then that rounded mean is multiplied by the `escalation_factor`, that
    product is rounded half up to 2 decimal places, and the result is capped at the
    ceiling of 100."

    Design: Difficulty/dual_variant_calc/bulletin_risk_fleet_aggregate_escalation_vs_per_unit_max
    """
    bundle = _overdue_mandatory_fleet()

    data = validate_success(
        api_client.get_bulletin_risk(bundle["bulletin"]["id"], MANAGER)
    )

    assert data["evaluated_action_count"] == 3
    assert data["deferred_action_count"] == 1
    assert data["escalation_factor"] == pytest.approx(1.05, abs=0.01)
    assert data["fleet_aggregate_score"] == pytest.approx(43.16, abs=0.01)


def test_divergence_separates_the_dashboard_number_from_the_worst_unit():
    """The two figures diverge because only one of them is escalated.

    PRD §3.6: "`divergence` is `per_unit_max_score` less `fleet_aggregate_score`,
    rounded half up to 2 decimal places."
    PRD §3.6: "The overdue points are then those days overdue multiplied by 1.5
    points per day, capped at 30 points — which is to say the penalty stops growing
    after twenty days past deadline."

    Design: Difficulty/dual_variant_calc/bulletin_risk_fleet_aggregate_escalation_vs_per_unit_max
    """
    bundle = _overdue_mandatory_fleet()

    data = validate_success(
        api_client.get_bulletin_risk(bundle["bulletin"]["id"], MANAGER)
    )

    assert data["divergence"] == pytest.approx(12.34, abs=0.01)


def _mine_train_action_awaiting_a_part():
    """One acknowledged advisory action whose linked requisition is only RESERVED."""
    attraction = fixtures.create_attraction(
        name="Prospector Mine Train",
        park_area="FRONTIER",
        manufacturer="Arrow",
        model_code="MT-77",
        ride_class="FAMILY",
        theoretical_hourly_capacity=760,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    bundle = fixtures.acknowledged_bulletin_with_actions(
        bulletin_ref="SB-2026-204",
        manufacturer="Arrow",
        model_code="MT-77",
        severity="ADVISORY",
        issued_date="2026-07-20",
        compliance_deadline_date="2026-09-30",
        attractions=[attraction],
    )
    action = bundle["actions"][0]
    requisition = fixtures.create_requisition(
        attraction["id"],
        part_number="KIT-204",
        quantity=1,
        unit_cost_cents=50000,
        needed_by_date="2026-09-15",
        bulletin_action_id=action["id"],
    )
    requisition = fixtures.walk_requisition_to(requisition, "RESERVED")
    bundle["attraction"] = attraction
    bundle["action"] = fixtures.start_action(action["id"])
    bundle["requisition"] = requisition
    return bundle


def test_verification_is_refused_while_the_linked_requisition_is_unreceived():
    """An action with an outstanding requisition is not ready to verify.

    PRD §3.6: "The `required_part_received` flag on a fleet action deserves its own
    sentence, because its default is counter-intuitive: it reads true when at least
    one part requisition naming this action has reached `RECEIVED`, **and also**
    when no part requisition references this action at all."
    PRD §3.6: "Verification requires the action's `required_part_received` to be
    true; otherwise it is refused with `ERR_PART_NOT_RECEIVED`."

    Design: Difficulty/cross_entity_state_dependency/bulletin_action_verify_gated_by_linked_requisition_then_bubbles_bulletin_to_completed
    """
    bundle = _mine_train_action_awaiting_a_part()
    action_id = bundle["action"]["id"]
    assert bundle["action"]["status"] == "IN_WORK"
    assert bundle["action"]["required_part_received"] is False

    response = api_client.verify_bulletin_action(
        action_id, make_qualified_inspector_headers("insp-2")
    )
    validate_error(response, "ERR_PART_NOT_RECEIVED", 409)

    still = validate_success(api_client.get_bulletin_action(action_id, MANAGER))
    assert still["status"] == "IN_WORK"
    assert still["verified_by_user_id"] is None


def test_receiving_the_linked_part_flips_the_flag_without_moving_the_ledger():
    """Receiving crosses a status boundary while committing no further money.

    PRD §3.5: "The committed budget does not change, because `RECEIVED` stays inside
    the committed set — this is the one status transition in the requisition
    lifecycle that moves money not at all despite crossing a boundary."
    PRD §3.5: "When the requisition names a `bulletin_action_id`, that fleet
    action's `required_part_received` becomes true, which is what unlocks its
    verification."

    Design: Difficulty/cross_entity_state_dependency/bulletin_action_verify_gated_by_linked_requisition_then_bubbles_bulletin_to_completed
    """
    bundle = _mine_train_action_awaiting_a_part()
    attraction_id = bundle["attraction"]["id"]

    before = fixtures.read_attraction(attraction_id)
    assert before["parts_budget_committed_cents"] == 50000

    received = fixtures.walk_requisition_to(bundle["requisition"], "RECEIVED")
    assert received["status"] == "RECEIVED"

    after = fixtures.read_attraction(attraction_id)
    assert after["parts_budget_committed_cents"] == 50000

    action = validate_success(
        api_client.get_bulletin_action(bundle["action"]["id"], MANAGER)
    )
    assert action["required_part_received"] is True


def test_verification_stamps_the_inspector_and_bubbles_the_bulletin_to_completed():
    """The last verification completes the parent bulletin.

    PRD §3.6: "Verification stamps `verified_by_user_id` with the inspector's badge
    and `verified_at` with the current logical clock instant, and increments the
    parent bulletin's `action_verified_count` by one."
    PRD §3.6: "When that increment makes `action_verified_count` equal
    `action_total_count` — and the parent has at least one non-cancelled action —
    the parent bulletin bubbles up `ACKNOWLEDGED` → `COMPLETED`, and no further
    action rows may be created for it."

    Design: Difficulty/cross_entity_state_dependency/bulletin_action_verify_gated_by_linked_requisition_then_bubbles_bulletin_to_completed
    """
    bundle = _mine_train_action_awaiting_a_part()
    fixtures.walk_requisition_to(bundle["requisition"], "RECEIVED")

    verified = validate_success(
        api_client.verify_bulletin_action(
            bundle["action"]["id"], make_qualified_inspector_headers("insp-2")
        )
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == "insp-2"
    assert verified["verified_at"] is not None

    bulletin = validate_success(
        api_client.get_bulletin(bundle["bulletin"]["id"], TECHNICIAN)
    )
    assert bulletin["action_verified_count"] == 1
    assert bulletin["action_total_count"] == 1
    assert bulletin["status"] == "COMPLETED"
