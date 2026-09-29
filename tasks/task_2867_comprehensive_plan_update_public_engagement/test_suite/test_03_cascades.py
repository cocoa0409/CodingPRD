"""Deep write cascades: one call, many rows moved.

Three triggers in this service each fire a chain of effects where every step is
caused by the one before it. Adopting an amendment on the floor rewrites an
element, stales the dependencies pointing at it, drags the plan's posture off
CLEAR and blocks the sittings still on the calendar. A deficient state
determination demotes the named elements, reopens the dependencies that relied on
them and freezes the plan. Closing a workshop credits the plan's engagement
record and can lift an equity hold. Each chain is asserted end to end, alongside
the neighbouring case that must not move.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PLAN_POSTURE_BLOCKED
from test_helpers.assertions import expected_equity_share_pct
from test_helpers.test_users import CLERK, DIRECTOR, DIRECTOR_ID, STAFF, STATE

# Ten sign-ins of which three are in an underrepresented group: 3.0 of 10.0
# weighted units under STANDARD weighting.
ROSTER_EQUITY_30 = [
    {"respondent_ref": "s-01", "demographic_group": C.GROUP_LOW_INCOME},
    {"respondent_ref": "s-02", "demographic_group": C.GROUP_LIMITED_ENGLISH},
    {"respondent_ref": "s-03", "demographic_group": C.GROUP_YOUTH},
    {"respondent_ref": "s-04", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "s-05", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "s-06", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "s-07", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "s-08", "demographic_group": C.GROUP_SENIOR},
    {"respondent_ref": "s-09", "demographic_group": C.GROUP_SENIOR},
    {"respondent_ref": "s-10", "demographic_group": C.GROUP_SENIOR},
]


def _mandate_ready_with_cleared_link(api):
    """Five approved elements plus one reconciled TRANSPORTATION → LAND_USE edge.

    The edge is declared while the transportation chapter is still a draft and
    reconciled before it is approved, so the plan reaches the state with
    `open_consistency_link_count` at zero and one `CLEARED` link on the books.
    """
    ctx = fx.plan_with_adopted_scenario(api)
    plan_id = ctx["plan_id"]
    fx.create_all_allocations(api, plan_id)

    land = fx.approved_element(api, plan_id, C.ELEMENT_LAND_USE)
    transportation = fx.create_element(api, plan_id, C.ELEMENT_TRANSPORTATION)
    link = fx.create_link(
        api,
        transportation["id"],
        land["id"],
        dependency_type=C.DEPENDENCY_CAPACITY_ASSUMPTION,
    )
    link = fx.reconcile_link(
        api, link["id"], note="Level-of-service assumptions aligned with the diagram."
    )
    fx.submit_element(api, transportation["id"])
    transportation = fx.approve_element(api, transportation["id"])
    for element_type in (C.ELEMENT_PARKS, C.ELEMENT_INFRASTRUCTURE, C.ELEMENT_HOUSING):
        fx.approved_element(api, plan_id, element_type)

    fx.completed_workshop(api, plan_id)
    review_ctx = fx.circulated_review(api, plan_id)
    fx.select_preferred(api, review_ctx["review_id"])
    return {
        "plan_id": plan_id,
        "land": land,
        "transportation": transportation,
        "link": link,
        "review_id": review_ctx["review_id"],
    }


def _file_with_state(api, plan_id):
    return validate_success(
        api.submit_plan_to_state(
            plan_id, {"submission_note": "Adoption draft filed for review."}, DIRECTOR
        )
    )


def _read_link(api, link_id):
    return validate_success(api.get_consistency_link(link_id, DIRECTOR))


# ------------------------------------------------------- amendment on the floor
def _open_sitting_with_a_motion(api):
    """A certified plan with one hearing gavelled in, a second still on the
    calendar, and an amendment moved against the land use chapter."""
    ctx = _mandate_ready_with_cleared_link(api)
    plan_id = ctx["plan_id"]
    fx.set_clock(api, fx.T_COMMENT_END_EIR)
    fx.certify_review(api, ctx["review_id"])
    _file_with_state(api, plan_id)
    plan = validate_success(
        api.record_state_determination(
            plan_id,
            f.state_determination_payload(
                C.STATE_REVIEW_CERTIFIED, "Mandate satisfied in full."
            ),
            STATE,
        )
    )
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["compliance_posture"] == C.POSTURE_CLEAR

    first = fx.scheduled_commission_hearing(api, plan_id)
    second = fx.scheduled_commission_hearing(
        api,
        plan_id,
        scheduled_start=fx.T_COUNCIL_START,
        scheduled_end=fx.T_COUNCIL_END,
    )
    fx.set_clock(api, fx.T_COMMISSION_START)
    ctx["open_hearing"] = fx.open_hearing(api, first["id"])
    ctx["calendar_hearing"] = second
    ctx["amendment"] = fx.propose_amendment(
        api,
        first["id"],
        ctx["land"]["id"],
        summary="Add two policies on infill incentives near transit.",
        policy_delta=2,
    )
    return ctx


def test_adopting_an_amendment_stales_the_element_and_every_link_that_relies_on_it(api):
    """The motion carries and the consequences run four rows deep.

    PRD: "Because the element's text moved, every consistency link whose target is
    that element and whose status is `CLEARED` moves `CLEARED → STALE`, recording
    this amendment's id in `staled_by_amendment_id` and incrementing the link's
    `version`."

    Design: Difficulty/transitive_cascade/amendment_adoption_five_link_consistency_cascade
    """
    ctx = _open_sitting_with_a_motion(api)
    amendment = ctx["amendment"]
    assert amendment["status"] == C.AMENDMENT_STATUS_PROPOSED
    assert amendment["applied_policy_count"] is None
    assert amendment["prior_element_status"] is None

    adopted = fx.adopt_amendment(api, amendment["id"])
    assert adopted["status"] == C.AMENDMENT_STATUS_ADOPTED
    assert adopted["prior_element_status"] == C.ELEMENT_STATUS_APPROVED
    assert adopted["applied_policy_count"] == 8

    land = fx.read_element(api, ctx["land"]["id"])
    assert land["policy_count"] == 8
    assert land["consistency_status"] == C.CONSISTENCY_STALE
    assert land["status"] == C.ELEMENT_STATUS_APPROVED

    link = _read_link(api, ctx["link"]["id"])
    assert link["status"] == C.LINK_STATUS_STALE
    assert link["staled_by_amendment_id"] == amendment["id"]

    source = fx.read_element(api, ctx["transportation"]["id"])
    assert source["consistency_status"] == C.CONSISTENCY_STALE

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["open_consistency_link_count"] == 1
    assert plan["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD

    hearing = validate_success(api.get_hearing(ctx["open_hearing"]["id"], CLERK))
    assert hearing["adopted_amendment_count"] == 1
    assert hearing["amendment_count"] == 1


def test_withdrawing_the_same_motion_moves_nothing_but_the_amendment(api):
    """The cheap exit fires no chain: the chapter and the plan stand as they were.

    PRD: "No element field and no plan field changes; in particular the element's
    `policy_count` is untouched, because a withdrawn amendment was never applied."

    Design: Difficulty/transitive_cascade/amendment_adoption_five_link_consistency_cascade
    """
    ctx = _open_sitting_with_a_motion(api)
    land_before = fx.read_element(api, ctx["land"]["id"])
    plan_before = fx.read_plan(api, ctx["plan_id"])

    withdrawn = fx.withdraw_amendment(
        api, ctx["amendment"]["id"], reason="Motion withdrawn by the mover."
    )
    assert withdrawn["status"] == C.AMENDMENT_STATUS_WITHDRAWN
    assert withdrawn["applied_policy_count"] is None

    land_after = fx.read_element(api, ctx["land"]["id"])
    assert land_after["policy_count"] == land_before["policy_count"] == 6
    assert land_after["consistency_status"] == C.CONSISTENCY_CLEARED
    assert land_after["version"] == land_before["version"]

    link = _read_link(api, ctx["link"]["id"])
    assert link["status"] == C.LINK_STATUS_CLEARED
    assert link["staled_by_amendment_id"] is None
    source = fx.read_element(api, ctx["transportation"]["id"])
    assert source["consistency_status"] == C.CONSISTENCY_CLEARED

    plan_after = fx.read_plan(api, ctx["plan_id"])
    assert plan_after["open_consistency_link_count"] == 0
    assert plan_after["compliance_posture"] == C.POSTURE_CLEAR
    assert plan_after["version"] == plan_before["version"]

    calendar = validate_success(api.get_hearing(ctx["calendar_hearing"]["id"], CLERK))
    assert calendar["status"] == C.HEARING_STATUS_SCHEDULED


def test_the_adopted_amendment_blocks_the_calendar_and_bars_a_recommendation(api):
    """The last two rungs of the chain: the October sitting is blocked and the
    open sitting can no longer recommend the plan.

    PRD: "Because the posture left `CLEAR`, every hearing of the plan standing in
    `SCHEDULED` moves `SCHEDULED → BLOCKED`, with each hearing's `version`
    incremented."

    Design: Difficulty/transitive_cascade/amendment_adoption_five_link_consistency_cascade
    """
    ctx = _open_sitting_with_a_motion(api)
    calendar_before = ctx["calendar_hearing"]
    assert calendar_before["status"] == C.HEARING_STATUS_SCHEDULED

    fx.adopt_amendment(api, ctx["amendment"]["id"])

    calendar_after = validate_success(api.get_hearing(calendar_before["id"], CLERK))
    assert calendar_after["status"] == C.HEARING_STATUS_BLOCKED
    assert calendar_after["version"] == calendar_before["version"] + 1
    sitting = validate_success(api.get_hearing(ctx["open_hearing"]["id"], CLERK))
    assert sitting["status"] == C.HEARING_STATUS_OPEN

    refused = api.record_hearing_outcome(
        ctx["open_hearing"]["id"],
        f.outcome_payload(C.OUTCOME_RECOMMEND, "Motion to recommend after the amendment."),
        CLERK,
    )
    validate_error(refused, ERR_PLAN_POSTURE_BLOCKED)

    held = validate_success(api.get_hearing(ctx["open_hearing"]["id"], CLERK))
    assert held["status"] == C.HEARING_STATUS_OPEN
    assert held["outcome"] is None
    assert held["closed_at"] is None
    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD


# ------------------------------------------------------- the state's determination
DEFICIENT_FINDINGS = (
    "The land use element does not demonstrate adequate sites at the assumed densities."
)


def _plan_awaiting_a_determination(api):
    ctx = _mandate_ready_with_cleared_link(api)
    filed = _file_with_state(api, ctx["plan_id"])
    assert filed["status"] == C.PLAN_STATUS_STATE_SUBMITTED
    assert filed["state_review_status"] == C.STATE_REVIEW_SUBMITTED
    assert filed["required_elements_complete_count"] == 5
    assert filed["open_consistency_link_count"] == 0
    return ctx


def test_a_deficient_finding_demotes_the_named_chapter_and_freezes_the_plan(api):
    """One verdict reopens the dependency graph and freezes the whole plan.

    PRD: "Because links were reopened, the plan's `open_consistency_link_count` and
    `required_elements_complete_count` are recomputed and then `compliance_posture`
    is recomputed. The result is `FROZEN`: the deficiency rule sits at the top of
    the posture ladder and dominates the consistency hold that the reopened links
    would otherwise have produced."

    Design: Difficulty/transitive_cascade/state_deficient_determination_four_link_freeze_cascade
    """
    ctx = _plan_awaiting_a_determination(api)
    plan = validate_success(
        api.record_state_determination(
            ctx["plan_id"],
            f.state_determination_payload(
                C.STATE_REVIEW_DEFICIENT, DEFICIENT_FINDINGS, [C.ELEMENT_LAND_USE]
            ),
            STATE,
        )
    )
    assert plan["status"] == C.PLAN_STATUS_STATE_DEFICIENT
    assert plan["state_review_status"] == C.STATE_REVIEW_DEFICIENT
    assert plan["state_findings"] == DEFICIENT_FINDINGS
    assert plan["open_consistency_link_count"] == 1
    assert plan["required_elements_complete_count"] == 4
    assert plan["compliance_posture"] == C.POSTURE_FROZEN

    land = fx.read_element(api, ctx["land"]["id"])
    assert land["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
    assert land["revision_round"] == 1
    assert land["consistency_status"] == C.CONSISTENCY_STALE

    link = _read_link(api, ctx["link"]["id"])
    assert link["status"] == C.LINK_STATUS_OPEN
    assert link["reconciled_by_user_id"] is None
    assert link["reconciliation_note"] is None
    source = fx.read_element(api, ctx["transportation"]["id"])
    assert source["consistency_status"] == C.CONSISTENCY_STALE


def test_only_the_element_types_the_state_named_are_demoted(api):
    """The demotion is scoped by `deficient_element_types`, not by the plan.

    PRD: "every element of the plan whose `element_type` appears in
    `deficient_element_types` and whose status is `APPROVED` moves
    `APPROVED → REVISION_REQUESTED`, has its `revision_round` incremented by one,
    has its `consistency_status` set to `STALE`, and has its `version` incremented."

    Design: Difficulty/transitive_cascade/state_deficient_determination_four_link_freeze_cascade
    """
    ctx = _plan_awaiting_a_determination(api)
    plan = validate_success(
        api.record_state_determination(
            ctx["plan_id"],
            f.state_determination_payload(
                C.STATE_REVIEW_DEFICIENT, DEFICIENT_FINDINGS, [C.ELEMENT_LAND_USE]
            ),
            STATE,
        )
    )
    assert plan["resubmission_count"] == 0

    untouched = fx.rows_of(
        api.list_plan_elements(ctx["plan_id"], DIRECTOR, limit=C.MAX_LIMIT)
    )
    by_type = {row["element_type"]: row for row in untouched}
    assert by_type[C.ELEMENT_LAND_USE]["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
    for element_type in (
        C.ELEMENT_HOUSING,
        C.ELEMENT_TRANSPORTATION,
        C.ELEMENT_PARKS,
        C.ELEMENT_INFRASTRUCTURE,
    ):
        row = by_type[element_type]
        assert row["status"] == C.ELEMENT_STATUS_APPROVED
        assert row["revision_round"] == 0


def test_a_certifying_finding_on_the_same_filing_disturbs_nothing(api):
    """The other branch of the same endpoint leaves the graph exactly as filed.

    PRD: "A `CERTIFIED` determination moves the plan `STATE_SUBMITTED →
    STATE_CERTIFIED`, sets `state_review_status` to `CERTIFIED`, records the
    supplied `findings` in `state_findings`, and recomputes `compliance_posture` — at
    which point a `FROZEN` posture can no longer apply, since the freeze rule keys on
    a deficient state review."

    Design: Difficulty/transitive_cascade/state_deficient_determination_four_link_freeze_cascade
    """
    ctx = _plan_awaiting_a_determination(api)
    plan = validate_success(
        api.record_state_determination(
            ctx["plan_id"],
            f.state_determination_payload(
                C.STATE_REVIEW_CERTIFIED, "Mandate satisfied in full."
            ),
            STATE,
        )
    )
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["state_review_status"] == C.STATE_REVIEW_CERTIFIED
    assert plan["state_findings"] == "Mandate satisfied in full."
    assert plan["open_consistency_link_count"] == 0
    assert plan["required_elements_complete_count"] == 5
    assert plan["compliance_posture"] == C.POSTURE_CLEAR

    land = fx.read_element(api, ctx["land"]["id"])
    assert land["status"] == C.ELEMENT_STATUS_APPROVED
    assert land["revision_round"] == 0
    assert land["consistency_status"] == C.CONSISTENCY_CLEARED

    link = _read_link(api, ctx["link"]["id"])
    assert link["status"] == C.LINK_STATUS_CLEARED
    assert link["reconciled_by_user_id"] == DIRECTOR_ID


# --------------------------------------------------- closing a public workshop
def _plan_awaiting_its_engagement_record(api):
    """A plan whose only outstanding hold is the engagement share."""
    ctx = fx.plan_with_adopted_scenario(api)
    fx.create_all_allocations(api, ctx["plan_id"])
    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["housing_shortfall_total"] == 0
    assert plan["participation_weight_total"] == 0.0
    assert plan["equity_share_pct"] == 0.0
    assert plan["compliance_posture"] == C.POSTURE_EQUITY_HOLD
    ctx["plan"] = plan
    return ctx


def _workshop_with_roster(api, plan_id, roster, start_at=None, end_at=None):
    venue = fx.create_venue(api)
    activity = fx.create_activity(
        api,
        plan_id,
        activity_type=C.ACTIVITY_WORKSHOP,
        venue_id=venue["id"],
        start_at=start_at or fx.T_ACTIVITY_START,
        end_at=end_at or fx.T_ACTIVITY_END,
    )
    fx.add_roster(api, activity["id"], roster)
    return validate_success(api.get_engagement_activity(activity["id"], STAFF))


def test_closing_the_workshop_credits_the_plan_and_lifts_the_equity_hold(api):
    """The sign-in sheet becomes an activity share, a plan share and a clear posture.

    PRD: "Second, the plan's `participation_weight_total` is increased by the
    activity's `total_weighted_count` and its `underrepresented_weight_total` by the
    activity's `underrepresented_weighted_count`. Third, the plan's own
    `equity_share_pct` is recomputed. Fourth, the plan's `compliance_posture` is
    recomputed, so an `EQUITY_HOLD` lifts to `CLEAR` exactly when the new plan-wide
    share reaches 40.0 percent and no higher-precedence hold applies."

    Design: Difficulty/transitive_cascade/activity_completion_four_link_equity_posture_cascade
    """
    ctx = _plan_awaiting_its_engagement_record(api)
    activity = _workshop_with_roster(api, ctx["plan_id"], fx.ROSTER_EQUITY_40)
    assert activity["weighting_variant"] == C.VARIANT_STANDARD

    closed = fx.complete_activity(api, activity["id"])
    assert closed["status"] == C.ACTIVITY_STATUS_COMPLETED
    assert closed["record_count"] == 10
    assert closed["underrepresented_record_count"] == 4
    assert closed["total_weighted_count"] == 10.0
    assert closed["underrepresented_weighted_count"] == 4.0
    assert closed["equity_share_pct"] == expected_equity_share_pct(4.0, 10.0) == 40.0

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["participation_weight_total"] == 10.0
    assert plan["underrepresented_weight_total"] == 4.0
    assert plan["equity_share_pct"] == 40.0 == C.MIN_EQUITY_SHARE_PCT
    assert plan["compliance_posture"] == C.POSTURE_CLEAR


def test_a_workshop_still_on_the_calendar_is_not_credited_to_the_plan(api):
    """The same ten sign-ins, uncounted while the session has not been closed out.

    PRD: "Activities still `SCHEDULED` have not been held and are excluded;
    activities `CANCELLED` have been withdrawn from the engagement record and are
    excluded too."

    Design: Difficulty/transitive_cascade/activity_completion_four_link_equity_posture_cascade
    """
    ctx = _plan_awaiting_its_engagement_record(api)
    activity = _workshop_with_roster(api, ctx["plan_id"], fx.ROSTER_EQUITY_40)

    assert activity["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert activity["record_count"] == 10
    assert activity["underrepresented_record_count"] == 4
    assert activity["total_weighted_count"] == 10.0
    assert activity["underrepresented_weighted_count"] == 4.0
    assert activity["equity_share_pct"] == 0.0

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["participation_weight_total"] == 0.0
    assert plan["underrepresented_weight_total"] == 0.0
    assert plan["equity_share_pct"] == 0.0
    assert plan["compliance_posture"] == C.POSTURE_EQUITY_HOLD


def test_a_second_weaker_workshop_pulls_the_plan_back_below_the_threshold(api):
    """The plan-wide share is a pooled ratio, not a per-session pass mark.

    PRD: "Two completed workshops of ten records each, one with four and one with
    three underrepresented respondents, give 7.0 of 20.0 weighted units, or 35.0
    percent: below the 40.0 threshold even though the first workshop on its own sat
    exactly at it."

    Design: Difficulty/transitive_cascade/activity_completion_four_link_equity_posture_cascade
    """
    ctx = _plan_awaiting_its_engagement_record(api)
    fx.completed_workshop(api, ctx["plan_id"], roster=fx.ROSTER_EQUITY_40)
    after_first = fx.read_plan(api, ctx["plan_id"])
    assert after_first["equity_share_pct"] == 40.0
    assert after_first["compliance_posture"] == C.POSTURE_CLEAR

    second = fx.completed_workshop(
        api,
        ctx["plan_id"],
        roster=ROSTER_EQUITY_30,
        start_at=fx.T_ACTIVITY_2_START,
        end_at=fx.T_ACTIVITY_2_END,
    )
    assert second["total_weighted_count"] == 10.0
    assert second["underrepresented_weighted_count"] == 3.0
    assert second["equity_share_pct"] == 30.0

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["participation_weight_total"] == 20.0
    assert plan["underrepresented_weight_total"] == 7.0
    assert plan["equity_share_pct"] == expected_equity_share_pct(7.0, 20.0) == 35.0
    assert plan["compliance_posture"] == C.POSTURE_EQUITY_HOLD
