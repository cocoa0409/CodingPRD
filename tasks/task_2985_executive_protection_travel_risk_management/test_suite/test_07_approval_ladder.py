"""The two-dimensional trip lifecycle, the approval hops and the money ledger."""

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

NG_RATING = {
    "crime_index": 70.0,
    "political_instability_index": 70.0,
    "medical_infrastructure_index": 40.0,
    "natural_hazard_index": 40.0,
}


def _two_dimension_world(api, budget_cents=100_000_000):
    """A draft trip with one ten-hour leg and no work recorded on it yet."""
    w = fx.bootstrap_world(
        api, executive={"annual_security_budget_cents": budget_cents}
    )
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
    w.trip = trip
    return w


def test_each_write_moves_at_most_one_of_the_two_trip_dimensions(api):
    """Approval and readiness are two independent fields on one row.

    PRD §3.6: "A trip that arrives at `APPROVED` while every one of its legs has both `advance_complete` of true and `lead_agent_covered` of true moves `ADVANCE_IN_PROGRESS → READY`, and `next_check_in_due_at` is set to the later of the trip's `depart_at` and the current clock reading, plus `check_in_interval_hours`."

    Design: Difficulty/non_linear_state_machine/trip_approval_and_readiness_dimensions_advance_independently
    """
    w = _two_dimension_world(api)
    dep = w.dep
    a.assert_trip_states(w.trip, c.APPROVAL_DRAFT, c.READINESS_NOT_READY)

    fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    a.assert_trip_states(
        fx.read_trip(api, dep, w.trip_id), c.APPROVAL_DRAFT, c.READINESS_NOT_READY
    )

    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    a.assert_trip_states(
        fx.read_trip(api, dep, w.trip_id),
        c.APPROVAL_DRAFT,
        c.READINESS_ADVANCE_IN_PROGRESS,
    )

    submitted = fx.submit_trip(api, dep, w.trip_id)
    a.assert_trip_states(
        submitted, c.APPROVAL_PENDING_REVIEW, c.READINESS_ADVANCE_IN_PROGRESS
    )

    acknowledged = fx.ack_briefing(api, w.exec_id, w.trip_id)
    a.assert_trip_states(
        acknowledged, c.APPROVAL_PENDING_REVIEW, c.READINESS_ADVANCE_IN_PROGRESS
    )

    approved = fx.decide_trip(api, dep, w.trip_id, c.DECISION_APPROVE)
    a.assert_trip_states(approved, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert approved["check_in_interval_hours"] == 24


def test_a_release_degrades_readiness_and_a_replacement_restores_it(api):
    """Losing and regaining lead-agent coverage never touches the approval state.

    PRD §3.7: "Recovery resets `check_in_interval_hours` to the plain band-derived value with no degradation floor applied, and decrements the protectee's `open_degraded_trip_count` by one."

    Design: Difficulty/non_linear_state_machine/trip_approval_and_readiness_dimensions_advance_independently
    """
    w = _two_dimension_world(api)
    dep = w.dep
    stand_in = fx.register_staff(api, "Lou Lead", c.STAFF_ROLE_ANALYST, 9_000)
    first = fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    submitted = fx.submit_trip(api, dep, w.trip_id)
    fx.ack_briefing(api, w.exec_id, w.trip_id)
    fx.decide_trip(api, dep, w.trip_id, c.DECISION_APPROVE)

    fx.release_assignment(api, dep, first["id"], c.LEG_DEPART_AT)
    degraded = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(degraded, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert degraded["check_in_interval_hours"] == 2
    leg = fx.read_leg(api, dep, w.leg_id)
    assert leg["lead_agent_covered"] is False
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1

    replacement = validate_success(
        api.create_detail_assignment(
            f.detail_assignment_payload(
                w.leg_id,
                stand_in["id"],
                leg["version"],
                role_on_detail=c.DETAIL_LEAD_AGENT,
                starts_at=c.LEG_ARRIVE_AT,
                ends_at=c.LEG_DEPART_AT,
            ),
            dep.mgr,
        ),
        201,
    )
    assert replacement["status"] == c.ASSIGNMENT_CONFIRMED

    recovered = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(recovered, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert recovered["check_in_interval_hours"] == 24
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 0
    a.assert_cents(
        recovered["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents at submit",
    )


def test_the_state_error_outranks_the_fiscal_error_on_a_resubmit(api):
    """A second submit is both stale and unaffordable, and 409 beats 402.

    PRD §2.7: "**State preconditions** — `ERR_ASSESSMENT_INVALID_STATE`, `ERR_TRIP_INVALID_APPROVAL_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_INCIDENT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` and `ERR_VENDOR_SUSPENDED`, in that relative order."

    Design: Difficulty/priority_pair_validation_conflict/resubmit_over_budget_trip_returns_state_error_not_fiscal_error
    """
    w = _two_dimension_world(api, budget_cents=150_000)
    dep = w.dep
    fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    submitted = fx.submit_trip(api, dep, w.trip_id)
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=112_500,
        spent=0,
        remaining=37_500,
    )
    a.assert_trip_states(submitted, c.APPROVAL_PENDING_REVIEW)

    retry = api.submit_trip_for_approval(w.trip_id, dep.mgr)
    validate_error(retry, e.ERR_TRIP_INVALID_APPROVAL_STATE, 409)

    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=112_500,
        spent=0,
        remaining=37_500,
    )
    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_PENDING_REVIEW)
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )


def _committed_trip(api):
    """A submitted trip carrying one 112,500-cent commitment and no briefing ack."""
    w = _two_dimension_world(api)
    dep = w.dep
    w.assignment = fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    w.submitted = fx.submit_trip(api, dep, w.trip_id)
    return w


def test_the_denied_trip_returns_the_money_ledger_to_its_opening_identity(api):
    """Submit commits and deny compensates, with nothing routed through spending.

    PRD §2.10: "Submitting a trip for approval adds its provisional cost to the committed figure, and denying that trip subtracts exactly the same amount, restoring the ledger to its pre-submission value."

    Design: Difficulty/compensating_invariant/trip_denial_restores_the_money_ledger_to_its_pre_submit_identity
    """
    w = _two_dimension_world(api)
    dep = w.dep
    opening = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(opening, committed=0, spent=0, remaining=100_000_000)

    fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    submitted = fx.submit_trip(api, dep, w.trip_id)
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=112_500,
        spent=0,
        remaining=99_887_500,
    )

    reason = "destination advisory withdrawn by the insurer"
    denied = fx.decide_trip(api, dep, w.trip_id, c.DECISION_DENY, denied_reason=reason)
    assert denied["approval_state"] == c.APPROVAL_DENIED
    assert denied["denied_reason"] == reason
    assert denied["briefing_ack_at"] is None, "a deny needs no acknowledgement"

    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=0,
        spent=0,
        remaining=100_000_000,
    )
    a.assert_cents(
        denied["provisional_security_cost_cents"],
        112_500,
        "the trip's own frozen figure is not rewritten",
    )


def test_the_denial_cascade_voids_the_assignment_and_the_staff_hours(api):
    """Hops two and three cancel the roster and hand back the committed hours.

    PRD §3.6: "Hop two cancels every `CONFIRMED` protective-detail assignment on every leg of the trip, forcing each `cost_cents` to 0, each `cost_basis` to `VOID`, and each `cancelled_reason` to `TRIP_DENIED`."

    Design: Difficulty/compensating_invariant/trip_denial_restores_the_money_ledger_to_its_pre_submit_identity
    """
    w = _committed_trip(api)
    dep = w.dep

    assert w.assignment["status"] == c.ASSIGNMENT_CONFIRMED
    assert w.assignment["planned_billable_hours"] == 10
    a.assert_cents(w.assignment["cost_cents"], 112_500, "cost_cents")
    assert w.assignment["cost_basis"] == c.COST_BASIS_PROVISIONAL
    a.assert_staff_hours(fx.read_staff(api, dep, dep.lead_id), committed=10, released=0)

    fx.decide_trip(
        api, dep, w.trip_id, c.DECISION_DENY, denied_reason="itinerary withdrawn"
    )

    cancelled = validate_success(
        api.get_detail_assignment(w.assignment["id"], dep.mgr)
    )
    assert cancelled["status"] == c.ASSIGNMENT_CANCELLED
    a.assert_cents(cancelled["cost_cents"], 0, "cost_cents")
    assert cancelled["cost_basis"] == c.COST_BASIS_VOID
    assert cancelled["cancelled_reason"] == c.CANCELLED_REASON_TRIP_DENIED

    a.assert_staff_hours(fx.read_staff(api, dep, dep.lead_id), committed=0, released=0)


def test_business_only_allocation_needs_a_business_travel_purpose(api, dep):
    """Neither field is wrong alone; only the combination is refused.

    PRD §3.4: "Choosing `BUSINESS_ONLY` is permitted only when `trip_purpose` is `BUSINESS_TRAVEL`; requesting it for a public appearance or a board event is rejected with `ERR_ALLOCATION_METHOD_NOT_PERMITTED`."

    Design: Corner/validations/business_only_allocation_is_permitted_only_for_business_travel
    """
    fx.publish_rating(api, dep)
    exec_row = fx.register_executive(api, dep)
    assessment = fx.draft_assessment(api, dep, exec_row["id"])

    def create(trip_purpose, allocation, depart_at, return_at):
        return api.create_trip(
            f.trip_payload(
                exec_row["id"],
                dep.mgr_id,
                assessment["id"],
                trip_purpose=trip_purpose,
                cost_allocation_method=allocation,
                depart_at=depart_at,
                return_at=return_at,
            ),
            dep.mgr,
        )

    rejected = create(
        c.PURPOSE_BOARD_EVENT,
        c.ALLOCATION_BUSINESS_ONLY,
        c.TRIP_DEPART_AT,
        c.TRIP_RETURN_AT,
    )
    validate_error(rejected, e.ERR_ALLOCATION_METHOD_NOT_PERMITTED, 422)

    board_prorata = validate_success(
        create(
            c.PURPOSE_BOARD_EVENT,
            c.ALLOCATION_PRORATA,
            c.TRIP_DEPART_AT,
            c.TRIP_RETURN_AT,
        ),
        201,
    )
    assert board_prorata["trip_purpose"] == c.PURPOSE_BOARD_EVENT
    assert board_prorata["cost_allocation_method"] == c.ALLOCATION_PRORATA

    business_only = validate_success(
        create(
            c.PURPOSE_BUSINESS_TRAVEL,
            c.ALLOCATION_BUSINESS_ONLY,
            "2026-09-20T00:00:00Z",
            "2026-09-22T00:00:00Z",
        ),
        201,
    )
    assert business_only["trip_purpose"] == c.PURPOSE_BUSINESS_TRAVEL
    assert business_only["cost_allocation_method"] == c.ALLOCATION_BUSINESS_ONLY

    _rows, meta = validate_paginated(
        api.list_trips(dep.mgr, executive_id=exec_row["id"])
    )
    assert meta["total_count"] == 2, "the rejected create wrote no row"


def test_an_approve_needs_the_briefing_acknowledgement_and_a_deny_does_not(api):
    """The acknowledgement gate is keyed on the decision, not on the stage.

    PRD §3.6: "An `APPROVE` decision additionally requires that `briefing_ack_at` is non-null, or it is rejected with `ERR_BRIEFING_NOT_ACKNOWLEDGED`; a `DENY` decision carries no such requirement, because denying an un-briefed trip is entirely sensible."

    Design: Corner/errors/approving_a_trip_without_a_briefing_acknowledgement_is_rejected
    """
    w = fx.bootstrap_world(
        api,
        coverage_cents=50_000_000,
        policy_overrides={
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-12-31T00:00:00Z",
        },
    )
    dep = w.dep
    trip = fx.create_trip(
        api, dep, w.exec_id, w.ra_id, insurance_policy_id=w.policy_id
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    submitted = fx.submit_trip(api, dep, trip["id"])
    a.assert_trip_states(
        submitted, c.APPROVAL_PENDING_REVIEW, c.READINESS_ADVANCE_IN_PROGRESS
    )
    assert submitted["briefing_ack_at"] is None
    assert submitted["required_approval_level"] == c.LEVEL_MANAGER
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id), committed=0, spent=0
    )

    blocked = api.decide_trip(
        trip["id"], f.trip_decision_payload(c.DECISION_APPROVE), dep.dir
    )
    validate_error(blocked, e.ERR_BRIEFING_NOT_ACKNOWLEDGED, 409)
    a.assert_trip_states(
        fx.read_trip(api, dep, trip["id"]),
        c.APPROVAL_PENDING_REVIEW,
        c.READINESS_ADVANCE_IN_PROGRESS,
    )

    denied = fx.decide_trip(
        api, dep, trip["id"], c.DECISION_DENY, denied_reason="itinerary withdrawn"
    )
    a.assert_trip_states(
        denied, c.APPROVAL_DENIED, c.READINESS_ADVANCE_IN_PROGRESS
    )
    assert denied["denied_reason"] == "itinerary withdrawn"


def test_neither_approval_role_may_act_at_the_other_role_stage(api):
    """A TIER_1 HIGH-band trip has two hops, each confined to its own role.

    PRD §2.9: "A `SecurityDirector` may take a trip decision only while the trip's `approval_state` is `PENDING_REVIEW`; a `ComplianceOfficer` may take one only while it is `PENDING_COMPLIANCE`."

    Design: Corner/rbac/each_approval_hop_requires_the_role_that_owns_that_stage
    """
    w = fx.bootstrap_world(
        api,
        country_code=c.COUNTRY_NG,
        rating=NG_RATING,
        executive={"full_name": "Tara Tier One", "tier": c.TIER_1, "role_title": "Chair"},
        coverage_cents=200_000_000,
        policy_overrides={
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-12-31T00:00:00Z",
        },
    )
    dep = w.dep
    a.assert_decimal_value(
        w.rating["composite_destination_score"], 62.00, "composite_destination_score"
    )
    assert w.rating["rating_band"] == c.BAND_HIGH
    a.assert_cents(
        w.rating["insurance_required_coverage_cents"],
        150_000_000,
        "insurance_required_coverage_cents",
    )
    a.assert_decimal_value(
        w.assessment["composite_risk_score"], 13.20, "composite_risk_score"
    )

    trip = fx.create_trip(
        api, dep, w.exec_id, w.ra_id, insurance_policy_id=w.policy_id,
        primary_destination_country_code=c.COUNTRY_NG,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        destination_country_code=c.COUNTRY_NG,
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    assert leg["leg_risk_band"] == c.BAND_HIGH
    final_leg = fx.complete_required_advance_work(api, dep, leg["id"])
    assert final_leg["advance_complete"] is True
    submitted = fx.submit_trip(api, dep, trip["id"])
    assert submitted["required_approval_level"] == c.LEVEL_DIRECTOR_AND_COMPLIANCE
    fx.ack_briefing(api, w.exec_id, trip["id"])

    early_officer = api.decide_trip(
        trip["id"], f.trip_decision_payload(c.DECISION_APPROVE), dep.officer
    )
    validate_error(early_officer, e.ERR_APPROVAL_LEVEL_MISMATCH, 409)
    a.assert_trip_states(
        fx.read_trip(api, dep, trip["id"]), c.APPROVAL_PENDING_REVIEW
    )

    first_hop = fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    a.assert_trip_states(first_hop, c.APPROVAL_PENDING_COMPLIANCE)

    late_director = api.decide_trip(
        trip["id"], f.trip_decision_payload(c.DECISION_APPROVE), dep.dir
    )
    validate_error(late_director, e.ERR_APPROVAL_LEVEL_MISMATCH, 409)

    second_hop = fx.decide_trip(
        api, dep, trip["id"], c.DECISION_APPROVE, headers=dep.officer
    )
    a.assert_trip_states(
        second_hop, c.APPROVAL_APPROVED, c.READINESS_ADVANCE_IN_PROGRESS
    )
    assert second_hop["check_in_interval_hours"] == 8
    assert second_hop["next_check_in_due_at"] == "2026-09-10T08:00:00.000Z"


def test_the_fiscal_rule_the_resubmit_hid_still_fires_on_its_own(api):
    """Priority 49 is real: a fresh over-budget submit is refused with 402.

    PRD §3.6: "Exact equality passes; a one-cent excess is rejected with `ERR_SECURITY_BUDGET_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/resubmit_over_budget_trip_returns_state_error_not_fiscal_error
    """
    w = _two_dimension_world(api, budget_cents=150_000)
    dep = w.dep
    fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    fx.submit_trip(api, dep, w.trip_id)
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=112_500,
        spent=0,
        remaining=37_500,
    )

    def draftable_trip(driver_id, role, depart_at, return_at):
        trip = fx.create_trip(
            api,
            dep,
            w.exec_id,
            w.ra_id,
            insurance_policy_id=w.policy_id,
            depart_at=depart_at,
            return_at=return_at,
        )
        leg = fx.add_leg(
            api,
            dep,
            trip["id"],
            arrive_at=depart_at,
            depart_at=return_at,
        )
        assignment = fx.assign_detail(
            api, dep, leg["id"], driver_id, role, depart_at, return_at
        )
        fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
        return trip, assignment

    driver = fx.register_staff(api, "Dee Driver", c.STAFF_ROLE_ANALYST, 9_000)
    over, over_assignment = draftable_trip(
        driver["id"], c.DETAIL_DRIVER, "2026-09-20T08:00:00Z", "2026-09-20T18:00:00Z"
    )
    a.assert_cents(over_assignment["cost_cents"], 76_500, "cost_cents")

    refused = api.submit_trip_for_approval(over["id"], dep.mgr)
    validate_error(refused, e.ERR_SECURITY_BUDGET_EXCEEDED, 402)
    a.assert_trip_states(fx.read_trip(api, dep, over["id"]), c.APPROVAL_DRAFT)
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=112_500,
        spent=0,
        remaining=37_500,
    )

    agent = fx.register_staff(api, "Ann Agent", c.STAFF_ROLE_ANALYST, 3_750)
    exact, exact_assignment = draftable_trip(
        agent["id"], c.DETAIL_AGENT, "2026-10-01T08:00:00Z", "2026-10-01T18:00:00Z"
    )
    a.assert_cents(exact_assignment["cost_cents"], 37_500, "cost_cents")

    submitted = fx.submit_trip(api, dep, exact["id"])
    a.assert_trip_states(submitted, c.APPROVAL_PENDING_REVIEW)
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id),
        committed=150_000,
        spent=0,
        remaining=0,
    )
