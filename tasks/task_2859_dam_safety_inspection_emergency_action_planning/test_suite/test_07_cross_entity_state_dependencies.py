"""Operations gated by the state of a different entity than the one being written."""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    assert_acre_feet,
    assert_cents,
    assert_cfs,
    assert_instant,
    assert_storage_conservation,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    DECISION_ISSUE,
    DELINQUENCY_CURRENT,
    DRAWDOWN_ACTIVE,
    DRAWDOWN_COORDINATED,
    ENTRY_PAYMENT_RECEIVED,
    EVENT_EMERGENCY,
    EVENT_MONITORING,
    PERMIT_ISSUED,
    PERMIT_TYPE_CONSTRUCTION,
    PERMIT_TYPE_REPAIR,
    PERMIT_UNDER_ENGINEERING_REVIEW,
    REG_REGISTERED,
    SAFETY_UNSATISFACTORY,
)
from test_helpers.test_users import coordinator_headers, make_engineer_headers


# ---------------------------------------------------------------------------
# Drawdown activation depends on the high-water event's state
# ---------------------------------------------------------------------------
@pytest.fixture()
def coordinated_drawdown(program, base):
    """A COORDINATED release whose governing event is still only MONITORING."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    event = program.declare_event(
        base.dam_id,
        declared_at="2026-08-01T00:00:00Z",
        trigger_description="Basin-wide rainfall of 5 inches in 12 hours.",
        declared_inflow_cfs=950,
    )
    order = program.request_drawdown(
        base.dam_id,
        event["id"],
        requested_release_cfs=400,
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    coordinated = program.coordinate_drawdown(order["id"], reach_id=base.reach_id)
    return {"event": event, "order": coordinated}


def test_activation_is_refused_while_the_event_is_only_monitoring(
    api, program, base, coordinated_drawdown
):
    """Capacity may be reserved on a watch, but the gates stay shut.

    PRD 3.7: "It requires the governing event to have reached `EMERGENCY`; an order coordinated under an event still in `MONITORING` cannot be activated, and the attempt is rejected with `ERR_EVENT_NOT_IN_EMERGENCY`."

    Design: Difficulty/cross_entity_state_dependency/drawdown_activation_rejected_until_its_high_water_event_reaches_emergency
    """
    order = coordinated_drawdown["order"]
    assert order["status"] == DRAWDOWN_COORDINATED
    # 400 cfs over six hours: 400 x 6 x 0.0826446 acre-feet.
    assert_acre_feet(order["planned_release_acre_ft"], 198.347, "planned_release_acre_ft")
    assert program.get_event(coordinated_drawdown["event"]["id"])["status"] == (
        EVENT_MONITORING
    )

    response = api.activate_drawdown(order["id"], None, coordinator_headers())
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_IN_EMERGENCY.value, 422)

    unchanged = program.get_drawdown(order["id"])
    assert unchanged["status"] == DRAWDOWN_COORDINATED
    assert unchanged["activated_at"] is None


def test_the_refused_activation_leaves_both_commitments_exactly_as_coordinated(
    api, program, base, coordinated_drawdown
):
    """A rejected activation changes no reach capacity and no reservoir storage.

    PRD 3.7: "Activation moves the order `COORDINATED → ACTIVE`, stamps `activated_at`, and changes no commitment — the reach capacity and dam storage were taken at coordination."

    Design: Difficulty/cross_entity_state_dependency/drawdown_activation_rejected_until_its_high_water_event_reaches_emergency
    """
    order = coordinated_drawdown["order"]
    api.activate_drawdown(order["id"], None, coordinator_headers())

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 400.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 198.347, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1301.653,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)


def test_escalating_the_event_unblocks_the_very_same_activation(
    program, base, coordinated_drawdown
):
    """Once the event auto-escalates the identical request succeeds.

    PRD 3.7: "That is the deliberate coupling between the auto-escalation rule above and the release itself: capacity may be reserved on a watch, but water moves only in an emergency."

    Design: Difficulty/cross_entity_state_dependency/drawdown_activation_rejected_until_its_high_water_event_reaches_emergency
    """
    event_id = coordinated_drawdown["event"]["id"]
    order = coordinated_drawdown["order"]

    program.set_clock("2026-08-01T02:00:00Z")
    program.add_reading(event_id, "2026-08-01T02:00:00Z", 1041.5, observed_inflow_cfs=1100)
    assert program.get_event(event_id)["status"] == EVENT_MONITORING

    program.set_clock("2026-08-01T04:00:00Z")
    program.add_reading(event_id, "2026-08-01T04:00:00Z", 1041.6, observed_inflow_cfs=1250)
    assert program.get_event(event_id)["status"] == EVENT_EMERGENCY

    activated = program.activate_drawdown(order["id"])
    assert activated["status"] == DRAWDOWN_ACTIVE
    assert_instant(activated["activated_at"], "2026-08-01T04:00:00Z", "activated_at")

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1301.653,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)


# ---------------------------------------------------------------------------
# Permit issuance depends on the dam's safety_status
# ---------------------------------------------------------------------------
@pytest.fixture()
def unsatisfactory_dam(program, base):
    """A SIGNIFICANT dam rated UNSATISFACTORY by an accepted inspection."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    inspection = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        inspection["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T09:30:00Z",
        condition_rating=SAFETY_UNSATISFACTORY,
        narrative="Spillway capacity grossly inadequate for the design flood.",
        deficiencies=[],
    )
    program.accept_inspection(inspection["id"], base.engineer_b_headers)
    return base


def test_a_construction_permit_cannot_be_decided_on_an_unsatisfactory_dam(
    api, program, unsatisfactory_dam
):
    """The bar sits on the dam's condition rating, not on the permit's own state.

    PRD 3.6: "Four further gates then apply, in the order §2.5 fixes: a `CONSTRUCTION` permit on a dam whose `safety_status` is `UNSATISFACTORY` is barred with `ERR_UNSAFE_DAM_PERMIT_BLOCKED` while `REPAIR` and `REMOVAL` work stays permissible on the same dam; a dam whose `hazard_class` is `HIGH` must have a `latest_eap_status` of `APPROVED` or the decision fails with `ERR_EAP_NOT_APPROVED`; the owner must not be delinquent, or the decision fails with `ERR_OWNER_DELINQUENT`; and on a `HIGH`-hazard dam the owner's `financial_assurance_bond_cents` must be at least 25,000,000 cents, or the decision fails with `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE`."

    Design: Difficulty/cross_entity_state_dependency/construction_permit_rejected_while_the_dam_safety_status_is_unsatisfactory
    """
    base = unsatisfactory_dam
    assert program.get_dam(base.dam_id)["safety_status"] == SAFETY_UNSATISFACTORY

    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="Raise the dam crest by 4 feet.",
        estimated_project_cost_cents=8_000_000,
    )
    # Base tier 100,000 plus 0.75 percent of cost uplifted 1.10 for SIGNIFICANT.
    assert_cents(permit["total_fee_cents"], 166000, "total_fee_cents")
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-166000,
        memo="Construction application fee paid.",
    )
    program.assign_permit_review(permit["id"], base.engineer_b_id)

    response = api.decide_permit(
        permit["id"],
        f.permit_decision_payload(
            decision=DECISION_ISSUE, findings="Crest raise design conforms."
        ),
        make_engineer_headers(base.engineer_b_id),
    )
    validate_error(response, ApiErrorId.ERR_UNSAFE_DAM_PERMIT_BLOCKED.value, 422)

    unchanged = program.get_permit(permit["id"])
    assert unchanged["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert unchanged["issued_at"] is None
    assert unchanged["decision_findings"] is None


def test_repair_work_on_the_same_unsatisfactory_dam_is_still_issuable(
    program, unsatisfactory_dam
):
    """The same dam, the same cost and the same reviewer, but repair work passes.

    PRD 3.6: "**Second**, an engineering review fee proportional to the project: the cost is multiplied by the work class's percentage — 0.75 percent for `CONSTRUCTION`, 0.5 percent for `REPAIR`, 0.35 percent for `REMOVAL` — and then by the hazard uplift of 1.25 at `HIGH`, 1.10 at `SIGNIFICANT`, and 1.0 at both `LOW` and `UNCLASSIFIED`; the product is rounded half up to whole cents and then capped at 750,000 cents."

    Design: Difficulty/cross_entity_state_dependency/construction_permit_rejected_while_the_dam_safety_status_is_unsatisfactory
    """
    base = unsatisfactory_dam
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        scope_description="Enlarge the service spillway to pass the design flood.",
        estimated_project_cost_cents=8_000_000,
    )
    assert_cents(permit["base_fee_cents"], 100000, "base_fee_cents")
    assert_cents(
        permit["engineering_review_fee_cents"], 44000, "engineering_review_fee_cents"
    )
    assert_cents(permit["total_fee_cents"], 144000, "total_fee_cents")

    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-144000,
        memo="Repair application fee paid.",
    )
    program.assign_permit_review(permit["id"], base.engineer_b_id)
    issued = program.decide_permit(
        permit["id"],
        base.engineer_b_id,
        decision=DECISION_ISSUE,
        findings="Enlarged spillway passes the design flood with freeboard.",
    )
    assert issued["status"] == PERMIT_ISSUED
    assert_instant(issued["issued_at"], "2026-08-05T13:00:00Z", "issued_at")

    # A REPAIR issuance never moves the regulatory dimension.
    assert program.get_dam(base.dam_id)["regulatory_status"] == REG_REGISTERED
    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT


def test_the_inspecting_engineer_cannot_be_nominated_as_the_reviewer(
    api, program, unsatisfactory_dam
):
    """The engineer of record on the accepted inspection is barred from the review.

    PRD 3.6: "The nominated engineer's `license_status` must be `ACTIVE`, and they must not be the engineer of record on the dam's latest accepted inspection — that collision is `ERR_SEGREGATION_OF_DUTIES`, because an engineer's own condition rating of the structure feeds the very decision they would be making."

    Design: Difficulty/cross_entity_state_dependency/construction_permit_rejected_while_the_dam_safety_status_is_unsatisfactory
    """
    base = unsatisfactory_dam
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        scope_description="Enlarge the service spillway to pass the design flood.",
        estimated_project_cost_cents=8_000_000,
    )

    response = api.assign_permit_review(
        permit["id"],
        f.assign_review_payload(base.engineer_a_id),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    # The other engineer, who only accepted the report, is a legal nomination.
    assigned = program.assign_permit_review(permit["id"], base.engineer_b_id)
    assert assigned["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert assigned["review_engineer_id"] == base.engineer_b_id
