"""Legs, the advance-work requirement set and the gates on submitting a trip."""

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


def _legless_trip(api):
    """A trip whose every submit precondition except its itinerary is satisfied."""
    w = fx.bootstrap_world(api)
    w.trip = fx.create_trip(
        api,
        w.dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    w.trip_id = w.trip["id"]
    return w


def test_a_trip_with_no_legs_is_refused_on_the_existence_rule(api):
    """At cardinality zero every leg-quantified rule is vacuous, so only one can fire.

    PRD §3.6: "Second, structure: the trip must have at least one leg, since an empty itinerary cannot be risk-rated at all, and an empty one is rejected with `ERR_TRIP_HAS_NO_LEGS`."

    Design: Difficulty/boundary_precision_check/empty_itinerary_cardinality_boundary_at_submit_for_approval
    """
    w = _legless_trip(api)
    dep = w.dep

    assert w.trip["max_leg_risk_band"] is None
    assert w.trip["required_approval_level"] == c.LEVEL_MANAGER
    _legs, meta = validate_paginated(api.list_trip_legs(w.trip_id, dep.mgr))
    assert meta["total_count"] == 0

    rejected = api.submit_trip_for_approval(w.trip_id, dep.mgr)
    validate_error(rejected, e.ERR_TRIP_HAS_NO_LEGS, 409)

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_DRAFT)
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        0,
        "provisional_security_cost_cents",
    )
    assert trip["next_check_in_due_at"] is None
    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=0, spent=0)


def test_the_same_trip_submits_once_it_carries_a_single_leg(api):
    """Cardinality one clears the boundary on the very trip that failed at zero.

    PRD §3.6: "That provisional figure is the last gate and the fiscal one: `provisional_security_cost_cents` must be less than or equal to the protectee's `remaining_budget_cents`."

    Design: Difficulty/boundary_precision_check/empty_itinerary_cardinality_boundary_at_submit_for_approval
    """
    w = _legless_trip(api)
    dep = w.dep
    validate_error(
        api.submit_trip_for_approval(w.trip_id, dep.mgr), e.ERR_TRIP_HAS_NO_LEGS, 409
    )

    leg = fx.add_leg(api, dep, w.trip_id)
    fx.assign_detail(api, dep, leg["id"], dep.lead_id)
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY, headers=dep.analyst)

    submitted = validate_success(api.submit_trip_for_approval(w.trip_id, dep.mgr))
    a.assert_trip_states(submitted, c.APPROVAL_PENDING_REVIEW)
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    assert submitted["max_leg_risk_band"] == c.BAND_LOW
    assert submitted["required_approval_level"] == c.LEVEL_MANAGER
    assert submitted["check_in_interval_hours"] == 24
    assert submitted["next_check_in_due_at"] == "2026-09-11T00:00:00.000Z"

    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=112_500, spent=0, remaining=99_887_500)


def _draft_assessment_trip(api):
    """A complete trip pointing at an assessment that was never reviewed."""
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep)
    fx.complete_residential_survey(api, dep, exec_row["id"])
    fx.publish_rating(api, dep)
    policy = fx.create_verified_policy(api, dep, exec_row["id"])
    assessment = fx.draft_assessment(api, dep, exec_row["id"])
    trip = fx.create_trip(
        api,
        dep,
        exec_row["id"],
        assessment["id"],
        insurance_policy_id=policy["id"],
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(api, dep, trip["id"])
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY, headers=dep.analyst)
    return fx.Ctx(
        dep=dep,
        exec_id=exec_row["id"],
        ra_id=assessment["id"],
        trip_id=trip["id"],
        leg_id=leg["id"],
    )


def test_a_trip_is_blocked_by_the_status_of_the_assessment_it_points_at(api):
    """Nothing observable on the trip is wrong; the blocking state is on another row.

    PRD §3.6: "Third, intelligence: the assessment named by `risk_assessment_id` must have `status` of `APPROVED`, so a `SUPERSEDED`, `VOIDED`, `SUBMITTED`, `RETURNED` or `DRAFT` assessment blocks the trip even though the reference itself resolves cleanly, and the rejection is `ERR_ASSESSMENT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/trip_submit_gated_on_risk_assessment_status_then_unblocked_by_approval
    """
    w = _draft_assessment_trip(api)
    dep = w.dep

    leg = fx.read_leg(api, dep, w.leg_id)
    assert leg["advance_complete"] is True
    assessment = validate_success(api.get_risk_assessment(w.ra_id, dep.analyst))
    assert assessment["status"] == c.ASSESSMENT_DRAFT

    validate_error(
        api.submit_trip_for_approval(w.trip_id, dep.mgr),
        e.ERR_ASSESSMENT_NOT_APPROVED,
        409,
    )

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_DRAFT)
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        0,
        "provisional_security_cost_cents",
    )
    still_draft = validate_success(api.get_risk_assessment(w.ra_id, dep.analyst))
    assert still_draft["status"] == c.ASSESSMENT_DRAFT
    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=0, spent=0)


def test_approving_the_assessment_unblocks_both_the_detail_and_the_submission(api):
    """Two calls on a different entity are the only mutation between the attempts.

    PRD §3.5: "The owning trip's risk assessment must be in `APPROVED` status, so a detail can never be planned against intelligence that has been superseded, voided or never reviewed; a trip whose assessment is in any other status is rejected with `ERR_ASSESSMENT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/trip_submit_gated_on_risk_assessment_status_then_unblocked_by_approval
    """
    w = _draft_assessment_trip(api)
    dep = w.dep
    validate_error(
        api.submit_trip_for_approval(w.trip_id, dep.mgr),
        e.ERR_ASSESSMENT_NOT_APPROVED,
        409,
    )
    validate_error(
        api.create_detail_assignment(
            f.detail_assignment_payload(
                w.leg_id,
                dep.lead_id,
                fx.leg_version(api, dep, w.leg_id),
                role_on_detail=c.DETAIL_LEAD_AGENT,
            ),
            dep.mgr,
        ),
        e.ERR_ASSESSMENT_NOT_APPROVED,
        409,
    )

    fx.submit_assessment(api, dep, w.ra_id)
    approved = fx.review_assessment(api, dep, w.ra_id, c.REVIEW_APPROVE, "cleared")
    assert approved["status"] == c.ASSESSMENT_APPROVED
    assert approved["approved_by_staff_id"] == dep.dir_id

    assignment = fx.assign_detail(api, dep, w.leg_id, dep.lead_id)
    a.assert_cents(assignment["cost_cents"], 112_500, "cost_cents")

    submitted = validate_success(api.submit_trip_for_approval(w.trip_id, dep.mgr))
    a.assert_trip_states(submitted, c.APPROVAL_PENDING_REVIEW)
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=112_500, spent=0, remaining=99_887_500)


def _returned_assessment_trip(api):
    """A trip with one bare leg whose assessment was returned for rework."""
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep)
    fx.complete_residential_survey(api, dep, exec_row["id"])
    fx.publish_rating(api, dep)
    policy = fx.create_verified_policy(api, dep, exec_row["id"])
    assessment = fx.draft_assessment(api, dep, exec_row["id"])
    fx.submit_assessment(api, dep, assessment["id"])
    returned = fx.review_assessment(
        api, dep, assessment["id"], c.REVIEW_RETURN, "exposure narrative incomplete"
    )
    trip = fx.create_trip(
        api,
        dep,
        exec_row["id"],
        assessment["id"],
        insurance_policy_id=policy["id"],
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(api, dep, trip["id"])
    return fx.Ctx(
        dep=dep,
        exec_id=exec_row["id"],
        returned=returned,
        ra_id=assessment["id"],
        trip_id=trip["id"],
        leg=leg,
        leg_id=leg["id"],
    )


def test_the_safety_rule_outranks_the_intelligence_rule_on_one_request(api):
    """Both rules are violated at once and the advance-work defect is reported.

    PRD §3.6: "First, safety: every leg of the trip must have `advance_complete` of true, and a trip with any leg still short of its required advance work is rejected with `ERR_ADVANCE_WORK_INCOMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/submit_with_no_advance_work_and_returned_assessment_returns_safety_error
    """
    w = _returned_assessment_trip(api)
    dep = w.dep

    assert w.returned["status"] == c.ASSESSMENT_RETURNED
    assert w.returned["revision_round"] == 1
    assert w.leg["required_advance_items"] == [c.ITEM_ROUTE_SURVEY]
    assert w.leg["completed_advance_items"] == []
    assert w.leg["advance_complete"] is False

    rejected = api.submit_trip_for_approval(w.trip_id, dep.mgr)
    validate_error(rejected, e.ERR_ADVANCE_WORK_INCOMPLETE, 409)

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_DRAFT)
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        0,
        "provisional_security_cost_cents",
    )
    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=0, spent=0)


def test_clearing_the_advance_work_exposes_the_intelligence_defect_underneath(api):
    """The second rule was live all along; only the fixed order hid it.

    PRD §3.6: "It is the single densest gate in the service, and the checks are evaluated in a fixed order so that the reported defect is always the most serious one present."

    Design: Difficulty/priority_pair_validation_conflict/submit_with_no_advance_work_and_returned_assessment_returns_safety_error
    """
    w = _returned_assessment_trip(api)
    dep = w.dep
    validate_error(
        api.submit_trip_for_approval(w.trip_id, dep.mgr),
        e.ERR_ADVANCE_WORK_INCOMPLETE,
        409,
    )

    leg = fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY)
    assert leg["advance_complete"] is True

    second = api.submit_trip_for_approval(w.trip_id, dep.mgr)
    validate_error(second, e.ERR_ASSESSMENT_NOT_APPROVED, 409)

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_DRAFT, c.READINESS_ADVANCE_IN_PROGRESS)


def test_a_public_appearance_adds_a_crowd_plan_to_the_band_derived_set(api):
    """One enum drives both the leg's advance set and the trip's approval level.

    PRD §3.4: "On top of the band-derived set, any leg belonging to a trip whose `trip_purpose` is `PUBLIC_APPEARANCE` additionally requires a crowd plan."

    Design: Corner/calculations/advance_requirement_set_adds_crowd_plan_for_a_public_appearance
    """
    w = fx.bootstrap_world(api)
    dep = w.dep
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        trip_purpose=c.PURPOSE_PUBLIC_APPEARANCE,
    )

    leg = validate_success(
        api.create_trip_leg(
            trip["id"],
            f.trip_leg_payload(
                sequence_no=1,
                arrive_at=c.TRIP_DEPART_AT,
                depart_at=c.TRIP_RETURN_AT,
            ),
            dep.mgr,
        ),
        201,
    )
    assert leg["leg_risk_band"] == c.BAND_LOW
    assert leg["required_advance_items"] == [c.ITEM_ROUTE_SURVEY, c.ITEM_CROWD_PLAN]
    assert fx.read_trip(api, dep, trip["id"])["required_approval_level"] == (
        c.LEVEL_DIRECTOR
    )

    after_route = fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    assert after_route["completed_advance_items"] == [c.ITEM_ROUTE_SURVEY]
    assert after_route["advance_complete"] is False

    after_crowd = fx.record_advance(
        api, dep, leg["id"], c.ITEM_CROWD_PLAN, note="stage perimeter agreed"
    )
    assert after_crowd["completed_advance_items"] == [
        c.ITEM_ROUTE_SURVEY,
        c.ITEM_CROWD_PLAN,
    ]
    assert after_crowd["advance_complete"] is True


def test_a_leg_must_sit_inside_the_trip_window_on_both_inclusive_ends(api):
    """Containment is checked with non-strict comparisons at both boundaries.

    PRD §3.4: "The leg must also sit inside the trip's own window: its `arrive_at` must be at or after the trip's `depart_at` and its own `depart_at` must be at or before the trip's `return_at`, and a leg that pokes out of either end is rejected with `ERR_LEG_OUTSIDE_TRIP_WINDOW`."

    Design: Corner/validations/leg_outside_the_trip_window_is_rejected_while_the_boundary_leg_is_accepted
    """
    w = fx.bootstrap_world(api)
    dep = w.dep
    trip = fx.create_trip(api, dep, w.exec_id, w.ra_id)

    validate_error(
        api.create_trip_leg(
            trip["id"],
            f.trip_leg_payload(
                sequence_no=1,
                arrive_at="2026-09-09T00:00:00Z",
                depart_at="2026-09-11T00:00:00Z",
            ),
            dep.mgr,
        ),
        e.ERR_LEG_OUTSIDE_TRIP_WINDOW,
        422,
    )
    validate_error(
        api.create_trip_leg(
            trip["id"],
            f.trip_leg_payload(
                sequence_no=2,
                arrive_at="2026-09-11T00:00:00Z",
                depart_at="2026-09-13T00:00:00Z",
            ),
            dep.mgr,
        ),
        e.ERR_LEG_OUTSIDE_TRIP_WINDOW,
        422,
    )

    accepted = validate_success(
        api.create_trip_leg(
            trip["id"],
            f.trip_leg_payload(
                sequence_no=3,
                arrive_at=c.TRIP_DEPART_AT,
                depart_at=c.TRIP_RETURN_AT,
            ),
            dep.mgr,
        ),
        201,
    )
    assert accepted["sequence_no"] == 3

    legs, meta = validate_paginated(api.list_trip_legs(trip["id"], dep.mgr))
    assert meta["total_count"] == 1
    assert [row["sequence_no"] for row in legs] == [3]


def test_route_survey_is_unwaivable_and_only_a_director_may_waive_at_all(api):
    """The waiver rule has two independent halves and both refuse with 403.

    PRD §3.4: "Waiving is tightly held: only a `SecurityDirector` may record a `WAIVED` outcome at all, and even a director may never waive `ROUTE_SURVEY` or `CROWD_PLAN`, which are non-waivable by every role."

    Design: Corner/validations/route_survey_is_never_waivable_and_only_a_director_may_waive_anything
    """
    w = fx.bootstrap_world(api)
    dep = w.dep
    trip = fx.create_trip(api, dep, w.exec_id, w.ra_id)
    leg = fx.add_leg(
        api, dep, trip["id"], arrive_at=c.TRIP_DEPART_AT, depart_at=c.TRIP_RETURN_AT
    )

    validate_error(
        api.record_advance_progress(
            leg["id"],
            f.advance_progress_payload(
                item_type=c.ITEM_ROUTE_SURVEY,
                outcome=c.ADVANCE_OUTCOME_WAIVED,
                note="no time to walk it",
            ),
            dep.dir,
        ),
        e.ERR_WAIVER_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.record_advance_progress(
            leg["id"],
            f.advance_progress_payload(
                item_type=c.ITEM_HOTEL_SURVEY,
                outcome=c.ADVANCE_OUTCOME_WAIVED,
                note="known property",
            ),
            dep.mgr,
        ),
        e.ERR_WAIVER_NOT_PERMITTED,
        403,
    )

    untouched = fx.read_leg(api, dep, leg["id"])
    assert untouched["completed_advance_items"] == []
    assert untouched["waived_advance_items"] == []
    assert untouched["advance_complete"] is False
    a.assert_trip_states(
        fx.read_trip(api, dep, trip["id"]), c.APPROVAL_DRAFT, c.READINESS_NOT_READY
    )

    waived = validate_success(
        api.record_advance_progress(
            leg["id"],
            f.advance_progress_payload(
                item_type=c.ITEM_HOTEL_SURVEY,
                outcome=c.ADVANCE_OUTCOME_WAIVED,
                note="known property",
            ),
            dep.dir,
        )
    )
    assert waived["waived_advance_items"] == [c.ITEM_HOTEL_SURVEY]
    assert waived["completed_advance_items"] == []
    assert waived["advance_complete"] is False
