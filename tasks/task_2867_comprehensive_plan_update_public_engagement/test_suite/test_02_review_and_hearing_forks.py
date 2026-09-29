"""Branching lifecycles: the director review loop and the hearing outcome fork.

Two entities in this service leave a status by more than one edge, and which edge is
taken is decided by the history of the row rather than by the caller. A plan element
walks DRAFT → IN_REVIEW → REVISION_REQUESTED → DRAFT as often as the director
sends it back, until the third request lands it in ESCALATED instead. A hearing
leaves OPEN by one of four outcomes whose effects on the parent plan diverge
sharply. Both are exercised here through the public endpoints only.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ESCALATION_OVERRIDE_REQUIRED
from test_helpers.test_users import CLERK, DIRECTOR, DIRECTOR_ID, STAFF


# --------------------------------------------------------------- review loop
def _element_in_review(api):
    """Open a cycle and place one drafted element in front of the director."""
    plan = fx.create_plan(api)
    element = fx.create_element(api, plan["id"], C.ELEMENT_TRANSPORTATION)
    fx.submit_element(api, element["id"])
    return plan, element


def _request_revision(api, element_id, note):
    return validate_success(
        api.record_review_decision(
            element_id,
            f.review_decision_payload(C.DECISION_REQUEST_REVISION, note),
            DIRECTOR,
        )
    )


def _revise(api, element_id, body, headers=STAFF):
    return api.patch_plan_element(element_id, {"draft_body": body}, headers)


def test_first_two_revision_requests_loop_the_element_back_to_drafting(api):
    """Rounds one and two send the chapter back and a revision reopens it.

    PRD: "A revision request that would leave `revision_round` below three moves the
    element `IN_REVIEW → REVISION_REQUESTED`, increments `revision_round` by one and
    stamps `reviewed_by_user_id`."

    Design: Difficulty/non_linear_state_machine/element_revision_cycle_escalates_on_third_request
    """
    plan, element = _element_in_review(api)
    assert element["revision_round"] == 0

    first = _request_revision(api, element["id"], "Round 1: add the sites analysis.")
    assert first["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
    assert first["revision_round"] == 1
    assert first["reviewed_by_user_id"] == DIRECTOR_ID

    reopened = validate_success(
        _revise(api, element["id"], "Sites analysis added to the narrative.")
    )
    assert reopened["status"] == C.ELEMENT_STATUS_DRAFT
    assert reopened["revision_round"] == 1

    fx.submit_element(api, element["id"])
    second = _request_revision(api, element["id"], "Round 2: quantify the constraints.")
    assert second["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
    assert second["revision_round"] == 2

    reopened_again = validate_success(
        _revise(api, element["id"], "Constraints quantified in a new table.")
    )
    assert reopened_again["status"] == C.ELEMENT_STATUS_DRAFT
    assert reopened_again["revision_round"] == 2
    assert fx.read_plan(api, plan["id"])["required_elements_complete_count"] == 0


def test_third_revision_request_escalates_instead_of_looping_again(api):
    """The third decision changes shape: ESCALATED, not another revision round.

    PRD: "when `revision_round` stands at exactly two, so that this decision would be
    the third, the element instead moves `IN_REVIEW → ESCALATED`, its
    `revision_round` is set to three and `reviewed_by_user_id` is stamped."

    Design: Difficulty/non_linear_state_machine/element_revision_cycle_escalates_on_third_request
    """
    plan, element = _element_in_review(api)
    for round_note in ("Round 1: add the sites analysis.", "Round 2: quantify it."):
        sent_back = _request_revision(api, element["id"], round_note)
        assert sent_back["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
        validate_success(_revise(api, element["id"], f"Reworked after: {round_note}"))
        fx.submit_element(api, element["id"])

    third = _request_revision(api, element["id"], "Round 3: unresolved, escalating.")
    assert third["status"] == C.ELEMENT_STATUS_ESCALATED
    assert third["status"] != C.ELEMENT_STATUS_REVISION_REQUESTED
    assert third["revision_round"] == C.MAX_REVISION_ROUNDS == 3
    assert third["reviewed_by_user_id"] == DIRECTOR_ID

    stored = fx.read_element(api, element["id"])
    assert stored["status"] == C.ELEMENT_STATUS_ESCALATED
    assert stored["revision_round"] == 3
    assert fx.read_plan(api, plan["id"])["required_elements_complete_count"] == 0


def test_only_the_director_reopens_an_escalated_element_and_the_round_resets(api):
    """Staff cannot re-enter the loop from ESCALATED; the director's override can.

    PRD: "An element in `ESCALATED` is a special case: it moves `ESCALATED → DRAFT`,
    but only a `PlanningDirector` may perform that revision, and the director's
    override additionally resets `revision_round` back to zero."

    Design: Difficulty/non_linear_state_machine/element_revision_cycle_escalates_on_third_request
    """
    plan, element = _element_in_review(api)
    for round_note in ("Round 1.", "Round 2."):
        _request_revision(api, element["id"], round_note)
        validate_success(_revise(api, element["id"], f"Reworked after {round_note}"))
        fx.submit_element(api, element["id"])
    escalated = _request_revision(api, element["id"], "Round 3: escalating.")
    assert escalated["status"] == C.ELEMENT_STATUS_ESCALATED

    refused = _revise(api, element["id"], "Staff attempt at a rewrite.", STAFF)
    validate_error(refused, ERR_ESCALATION_OVERRIDE_REQUIRED)
    held = fx.read_element(api, element["id"])
    assert held["status"] == C.ELEMENT_STATUS_ESCALATED
    assert held["revision_round"] == 3

    overridden = validate_success(
        _revise(api, element["id"], "Director rewrite of the chapter.", DIRECTOR)
    )
    assert overridden["status"] == C.ELEMENT_STATUS_DRAFT
    assert overridden["revision_round"] == 0
    assert fx.read_plan(api, plan["id"])["status"] == C.PLAN_STATUS_DRAFTING


# ------------------------------------------------------------- hearing outcomes
def _certified_plan_with_scheduled_hearing(api, **overrides):
    """A mandate-ready plan at STATE_CERTIFIED with one commission hearing booked."""
    ctx = fx.state_certified_plan(api)
    assert ctx["plan"]["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert ctx["plan"]["compliance_posture"] == C.POSTURE_CLEAR
    hearing = fx.scheduled_commission_hearing(api, ctx["plan_id"], **overrides)
    return ctx, hearing


def test_continue_outcome_closes_the_hearing_and_leaves_the_plan_where_it_stood(api):
    """A continued commission hearing concludes without moving the plan.

    PRD: "**`CONTINUE`** moves the hearing `OPEN → CONTINUED` and has no plan-level
    effect at all: the plan's status is unchanged and no counter moves."

    Design: Difficulty/non_linear_state_machine/hearing_outcome_fork_continue_versus_recommend_side_effects
    """
    ctx, hearing = _certified_plan_with_scheduled_hearing(api)
    fx.set_clock(api, fx.T_COMMISSION_START)
    fx.open_hearing(api, hearing["id"])

    concluded = validate_success(
        api.record_hearing_outcome(
            hearing["id"],
            f.outcome_payload(C.OUTCOME_CONTINUE, "Continued to the October agenda."),
            CLERK,
        )
    )
    assert concluded["status"] == C.HEARING_STATUS_CONTINUED
    assert concluded["outcome"] == C.OUTCOME_CONTINUE
    assert concluded["closed_at"] == fx.T_COMMISSION_START

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["compliance_posture"] == C.POSTURE_CLEAR
    assert plan["state_review_status"] == C.STATE_REVIEW_CERTIFIED


def test_recommend_outcome_closes_the_hearing_and_advances_the_plan(api):
    """The same endpoint, a different outcome: the plan takes its next step.

    PRD: "On success the plan moves `STATE_CERTIFIED → COMMISSION_RECOMMENDED` and
    the plan's `version` is incremented by one."

    Design: Difficulty/non_linear_state_machine/hearing_outcome_fork_continue_versus_recommend_side_effects
    """
    ctx, hearing = _certified_plan_with_scheduled_hearing(api)
    plan_before = fx.read_plan(api, ctx["plan_id"])
    fx.set_clock(api, fx.T_COMMISSION_START)
    fx.open_hearing(api, hearing["id"])

    concluded = validate_success(
        api.record_hearing_outcome(
            hearing["id"],
            f.outcome_payload(C.OUTCOME_RECOMMEND, "Recommended for council adoption."),
            CLERK,
        )
    )
    assert concluded["status"] == C.HEARING_STATUS_RECOMMENDED
    assert concluded["outcome"] == C.OUTCOME_RECOMMEND
    assert concluded["closed_at"] == fx.T_COMMISSION_START

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_COMMISSION_RECOMMENDED
    assert plan["version"] == plan_before["version"] + 1
    assert plan["compliance_posture"] == C.POSTURE_CLEAR


def test_two_commission_hearings_take_different_edges_out_of_open_in_one_cycle(api):
    """One plan, two sittings: the continued one is inert, the second advances it.

    PRD: "In all four branches the hearing must be `OPEN`, otherwise
    `ERR_HEARING_NOT_OPEN`; in all four the `outcome` field is recorded on the
    hearing, `closed_at` is stamped with the logical clock instant, and the
    hearing's `version` is incremented by one."

    Design: Difficulty/non_linear_state_machine/hearing_outcome_fork_continue_versus_recommend_side_effects
    """
    ctx, first = _certified_plan_with_scheduled_hearing(api)
    second = fx.scheduled_commission_hearing(
        api,
        ctx["plan_id"],
        scheduled_start=fx.T_COUNCIL_START,
        scheduled_end=fx.T_COUNCIL_END,
    )

    fx.set_clock(api, fx.T_COMMISSION_START)
    opened_first = fx.open_hearing(api, first["id"])
    continued = fx.record_outcome(
        api, first["id"], C.OUTCOME_CONTINUE, note="Continued to the October agenda."
    )
    assert continued["status"] == C.HEARING_STATUS_CONTINUED
    assert continued["closed_at"] == fx.T_COMMISSION_START
    assert continued["version"] == opened_first["version"] + 1
    after_continue = fx.read_plan(api, ctx["plan_id"])
    assert after_continue["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert after_continue["compliance_posture"] == C.POSTURE_CLEAR

    fx.set_clock(api, fx.T_COUNCIL_START)
    fx.open_hearing(api, second["id"])
    recommended = fx.record_outcome(
        api, second["id"], C.OUTCOME_RECOMMEND, note="Recommended for council adoption."
    )
    assert recommended["status"] == C.HEARING_STATUS_RECOMMENDED
    assert recommended["closed_at"] == fx.T_COUNCIL_START
    after_recommend = fx.read_plan(api, ctx["plan_id"])
    assert after_recommend["status"] == C.PLAN_STATUS_COMMISSION_RECOMMENDED
    assert after_recommend["compliance_posture"] == C.POSTURE_CLEAR

    # The continued hearing is untouched by its neighbour's outcome.
    settled = validate_success(api.get_hearing(first["id"], CLERK))
    assert settled["status"] == C.HEARING_STATUS_CONTINUED
    assert settled["outcome"] == C.OUTCOME_CONTINUE
