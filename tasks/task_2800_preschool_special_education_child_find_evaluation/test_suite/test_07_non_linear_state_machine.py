"""State movement that is not a single forward march.

The referral carries two orthogonal state dimensions that advance independently
(PRD §3.3), the evaluation report loops through a bounded revision cycle that
terminates at two rounds (PRD §3.7), the case has exactly one backward edge out of
`DOMAINS_COMPLETE` (PRD §3.5), and a determination of `NOT_ELIGIBLE` forks the new
service plan straight past `PENDING_PARENT_CONSENT` into a terminal status within
one request (PRD §3.7).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_composite_profile,
    assert_delay_figures,
    assert_fields_absent,
    assert_instant,
)
from test_helpers.constants import ts
from test_helpers.test_users import TEST_USERS

# ---------------------------------------------------------------- local helpers
# Five STANDARDIZED results for a child of 36 completed months at the assessment
# windows: COMMUNICATION lands on 33.3 percent and COGNITIVE on 36.1 percent, so
# two domains qualify and the recommendation is 60 + 60 = 120 minutes.
_STANDARDIZED_AGE_EQUIVALENTS = {
    "COMMUNICATION": 24,
    "COGNITIVE": 23,
    "PHYSICAL_MOTOR": 30,
    "SOCIAL_EMOTIONAL": 33,
    "ADAPTIVE": 34,
}


def _standardized_case(api):
    """A DOMAINS_COMPLETE case recommending 120 weekly minutes."""
    child = fx.register_child_aged(api, 36)
    return fx.setup_case_with_five_completed_domains(
        api,
        child["id"],
        assessment_protocol="STANDARDIZED",
        method="STANDARDIZED",
        age_equivalents=dict(_STANDARDIZED_AGE_EQUIVALENTS),
    )


# ------------------------ referral: two dimensions that do not move in lock step
def test_superseding_referral_moves_only_the_intake_dimension(api):
    """A displaced referral changes intake status while consent stays untouched.

    PRD §3.3: "When a new referral is created for a child — whether by a coordinator
    or by the system behind a screening outcome — every earlier referral of that same
    child whose `intake_status` is `RECEIVED`, `CONSENT_PENDING` or
    `EVALUATION_AUTHORIZED` is moved to `SUPERSEDED`, with `superseded_by_referral_id`
    set to the new referral's identifier and its `version` incremented."
    PRD §3.3: "Displacing a referral from `RECEIVED` does nothing further."
    PRD §3.3: "The consent dimension is only ever moved off `NOT_REQUESTED` by the
    issuance of a notice, and only ever moved from `REQUESTED` to `GRANTED` or
    `REFUSED`, or from `GRANTED` to `REVOKED`, by a decision on the referral's
    evaluation-consent record."

    Design: Difficulty/non_linear_state_machine/referral_intake_dimension_advances_while_consent_dimension_stays_put
    """
    child = fx.register_child(api)
    first = fx.create_referral(api, child["id"])
    assert first["intake_status"] == "RECEIVED"
    assert first["consent_status"] == "NOT_REQUESTED"

    second = fx.create_referral(api, child["id"])

    displaced = fx.read_referral(api, first["id"])
    assert displaced["intake_status"] == "SUPERSEDED"
    # No notice was ever issued on this referral, so the consent dimension is inert.
    assert displaced["consent_status"] == "NOT_REQUESTED"
    assert displaced["superseded_by_referral_id"] == second["id"]
    assert displaced["version"] == first["version"] + 1

    assert second["intake_status"] == "RECEIVED"
    assert second["consent_status"] == "NOT_REQUESTED"
    assert second["age_months_at_referral"] == 33
    assert second["eligibility_pathway"] == "STANDARD_60_DAY"
    assert_fields_absent(second, "superseded_by_referral_id")

    assert fx.read_child(api, child["id"])["status"] == "REFERRED"


def test_granted_consent_survives_supersession_of_the_intake_dimension(api):
    """The one state pair the consent dimension cannot explain is reachable.

    PRD §3.4: "This is carve-out B of §2.5 rung 11: on evaluation-case creation the
    intake dimension is inspected **only** when `consent_status` is `GRANTED`, and the
    single state pair the consent dimension cannot explain is a referral whose consent
    is `GRANTED` but whose `intake_status` has since become `SUPERSEDED` by a newer
    referral for the same child, which alone yields `ERR_INVALID_REFERRAL_STATE` on
    that endpoint."
    PRD §3.3: "Displacing one from `EVALUATION_AUTHORIZED` additionally cancels that
    referral's evaluation case, provided that case has not already reached
    `ELIGIBILITY_DETERMINED` or `CANCELLED`, which in turn triggers the assessment and
    provider-rollup chain described in §3.5."

    Design: Difficulty/non_linear_state_machine/referral_intake_dimension_advances_while_consent_dimension_stays_put
    """
    context = fx.setup_case(api)
    original = context["referral"]
    assert original["intake_status"] == "EVALUATION_AUTHORIZED"
    assert original["consent_status"] == "GRANTED"

    replacement = fx.create_referral(api, context["child"]["id"])

    displaced = fx.read_referral(api, original["id"])
    assert displaced["intake_status"] == "SUPERSEDED"
    # The consent decision itself is history and is not rewritten.
    assert displaced["consent_status"] == "GRANTED"
    assert displaced["superseded_by_referral_id"] == replacement["id"]
    assert displaced["evaluation_due_date"] == original["evaluation_due_date"]

    assert fx.read_case(api, context["case"]["id"])["status"] == "CANCELLED"
    assert fx.read_child(api, context["child"]["id"])["status"] == "REFERRED"


def test_notice_and_decision_each_move_both_dimensions_in_one_request(api):
    """The dimensions advance together only where the PRD says they do.

    PRD §3.3: "A successful issuance moves both dimensions of the referral in the same
    request: `intake_status` advances `RECEIVED → CONSENT_PENDING` and
    `consent_status` advances `NOT_REQUESTED → REQUESTED`."
    PRD §3.3: "A referral may legitimately sit at `intake_status` of `CONSENT_PENDING`
    with `consent_status` of `REQUESTED`."

    Design: Difficulty/non_linear_state_machine/referral_intake_dimension_advances_while_consent_dimension_stays_put
    """
    referral = fx.create_referral(api)
    consent = fx.issue_evaluation_notice(api, referral["id"])
    assert consent["decision"] == "PENDING"

    requested = fx.read_referral(api, referral["id"])
    assert requested["intake_status"] == "CONSENT_PENDING"
    assert requested["consent_status"] == "REQUESTED"
    assert_fields_absent(requested, "evaluation_due_date")

    fx.decide_consent(api, consent["id"], "GRANTED")
    authorized = fx.read_referral(api, referral["id"])
    assert authorized["intake_status"] == "EVALUATION_AUTHORIZED"
    assert authorized["consent_status"] == "GRANTED"


# ------------------------------ report revision: a loop that terminates at two
def test_third_revision_request_is_refused_at_the_two_round_ceiling(api):
    """The revision loop is bounded, and the bound is enforced on the third request.

    PRD §3.7: "A case may absorb at most two revision rounds; once `revision_round`
    has reached 2, a third request is refused with `ERR_REVISION_LIMIT_REACHED`."
    PRD §3.7: "The chair closes the loop by drafting again, which moves the case
    `REVISIONS_REQUESTED → REPORT_DRAFTED`, replaces `report_narrative_summary` with
    the new narrative, re-stamps `report_drafted_at`, and again requires the chair's
    own identity and all five domains complete."

    Design: Difficulty/non_linear_state_machine/evaluation_case_report_revision_cycle_terminates_at_two_rounds
    """
    context = fx.setup_case_with_five_completed_domains(api)
    case_id = context["case"]["id"]
    chair_id = context["chair"]["id"]

    fx.draft_report(api, case_id, chair_id)
    fx.request_revision(api, case_id, revision_note="Add the parent interview.")
    fx.draft_report(api, case_id, chair_id, report_narrative_summary="Draft two.")
    second = fx.request_revision(
        api, case_id, revision_note="Clarify play-based observations."
    )
    assert second["revision_round"] == 2
    fx.draft_report(api, case_id, chair_id, report_narrative_summary="Draft three.")

    refused = api.request_revision(
        case_id,
        f.revision_request_payload(revision_note="One more pass, please."),
        TEST_USERS["placement_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)

    case = fx.read_case(api, case_id)
    # The refusal leaves the loop exactly where the second round left it.
    assert case["status"] == "REPORT_DRAFTED"
    assert case["revision_round"] == 2
    assert case["last_revision_note"] == "Clarify play-based observations."
    assert case["report_narrative_summary"] == "Draft three."


def test_each_revision_round_returns_the_case_to_report_drafted(api):
    """The case revisits `REPORT_DRAFTED` once per round rather than moving on.

    PRD §3.7: "This is available only from `REPORT_DRAFTED` — asking for a revision at
    any other status is `ERR_INVALID_CASE_STATE` — and it moves the case
    `REPORT_DRAFTED → REVISIONS_REQUESTED`, increments `revision_round` by one, stores
    the note in `last_revision_note`, and increments the case's `version`."
    PRD §3.7: "The chair closes the loop by drafting again, which moves the case
    `REVISIONS_REQUESTED → REPORT_DRAFTED`, replaces `report_narrative_summary` with
    the new narrative, re-stamps `report_drafted_at`, and again requires the chair's
    own identity and all five domains complete."
    PRD §3.4: "A new case is written at `PLANNED` with `revision_round` at 0 and
    `required_domain_count` fixed by the system at 5 — the five developmental domains
    the team must cover."

    Design: Difficulty/non_linear_state_machine/evaluation_case_report_revision_cycle_terminates_at_two_rounds
    """
    context = fx.setup_case_with_five_completed_domains(api)
    case_id = context["case"]["id"]
    chair_id = context["chair"]["id"]

    first_draft = fx.draft_report(api, case_id, chair_id)
    assert first_draft["status"] == "REPORT_DRAFTED"
    assert first_draft["revision_round"] == 0
    assert_instant(first_draft["report_drafted_at"], ts("2026-08-01T00:00:00Z"))

    sent_back = fx.request_revision(api, case_id, revision_note="Expand cognition.")
    assert sent_back["status"] == "REVISIONS_REQUESTED"
    assert sent_back["revision_round"] == 1
    assert sent_back["last_revision_note"] == "Expand cognition."
    assert sent_back["version"] == first_draft["version"] + 1

    fx.set_clock(api, ts("2026-08-20T12:00:00Z"))
    second_draft = fx.draft_report(
        api, case_id, chair_id, report_narrative_summary="Draft two."
    )
    assert second_draft["status"] == "REPORT_DRAFTED"
    assert second_draft["report_narrative_summary"] == "Draft two."
    assert_instant(second_draft["report_drafted_at"], ts("2026-08-20T12:00:00Z"))
    # Closing the loop does not reset the counter that bounds it.
    assert second_draft["revision_round"] == 1

    reopened = fx.request_revision(api, case_id, revision_note="Tighten the summary.")
    assert reopened["status"] == "REVISIONS_REQUESTED"
    assert reopened["revision_round"] == 2
    assert reopened["last_revision_note"] == "Tighten the summary."


def test_revision_cannot_be_requested_while_the_case_is_already_being_revised(api):
    """The loop only ever re-enters from `REPORT_DRAFTED`.

    PRD §3.7: "This is available only from `REPORT_DRAFTED` — asking for a revision at
    any other status is `ERR_INVALID_CASE_STATE` — and it moves the case
    `REPORT_DRAFTED → REVISIONS_REQUESTED`, increments `revision_round` by one, stores
    the note in `last_revision_note`, and increments the case's `version`."

    Design: Difficulty/non_linear_state_machine/evaluation_case_report_revision_cycle_terminates_at_two_rounds
    """
    context = fx.setup_case_with_five_completed_domains(api)
    case_id = context["case"]["id"]

    fx.draft_report(api, case_id, context["chair"]["id"])
    sent_back = fx.request_revision(api, case_id, revision_note="Expand cognition.")
    assert sent_back["revision_round"] == 1

    # One round has been used, so this is not the ceiling being enforced.
    refused = api.request_revision(
        case_id,
        f.revision_request_payload(revision_note="And again."),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_CASE_STATE.value)

    case = fx.read_case(api, case_id)
    assert case["status"] == "REVISIONS_REQUESTED"
    assert case["revision_round"] == 1
    assert case["version"] == sent_back["version"]


# ------------------- the one backward edge: DOMAINS_COMPLETE back to IN_PROGRESS
def test_invalidating_a_completed_assessment_reverts_the_case_to_in_progress(api):
    """The case walks backwards out of `DOMAINS_COMPLETE` and drops its recommendation.

    PRD §3.5: "That recomputation has one — and only one — reversion edge. When the
    invalidation drops the case's `completed_domain_count` below
    `required_domain_count` and the case was standing at `DOMAINS_COMPLETE`, the case
    reverts `DOMAINS_COMPLETE → IN_PROGRESS`, its
    `composite_eligibility_recommendation` returns to `INDETERMINATE`, and its
    `version` increments."
    PRD §3.6: "If `completed_domain_count` is below five, the recommendation is
    `INDETERMINATE` regardless of anything else."

    Design: Difficulty/non_linear_state_machine/domains_complete_reverts_to_in_progress_when_an_assessment_is_invalidated
    """
    context = _standardized_case(api)
    case = context["case"]
    assert case["status"] == "DOMAINS_COMPLETE"
    assert_composite_profile(case, 5, 2, 36.1, "ELIGIBLE_RECOMMENDED", 120)

    cognitive = context["assessments"]["COGNITIVE"]
    invalidated = fx.invalidate_assessment(
        api, cognitive["id"], context["evaluators"]["COGNITIVE"]["id"]
    )
    assert invalidated["status"] == "INVALIDATED"

    reverted = fx.read_case(api, case["id"])
    assert reverted["status"] == "IN_PROGRESS"
    # The surviving qualifying domain is COMMUNICATION at 33.3 percent, worth 60.
    assert_composite_profile(reverted, 4, 1, 33.3, "INDETERMINATE", 60)
    assert reverted["version"] == case["version"] + 1


def test_an_invalidated_row_keeps_its_figures_but_leaves_the_aggregates(api):
    """The row is history; the case aggregates are recomputed without it.

    PRD §3.5: "Invalidation from `COMPLETED` does the same and, in addition, retains
    `percent_delay`, `weighted_percent_delay` and `qualifies_delay` on the row as
    historical values while removing the row from every case aggregate, then recomputes
    the parent case's aggregates."
    PRD §3.6: "`completed_domain_count` is the number of **distinct** `domain` values
    among the completed assessments."

    Design: Difficulty/non_linear_state_machine/domains_complete_reverts_to_in_progress_when_an_assessment_is_invalidated
    """
    context = _standardized_case(api)
    cognitive = context["assessments"]["COGNITIVE"]
    fx.invalidate_assessment(
        api,
        cognitive["id"],
        context["evaluators"]["COGNITIVE"]["id"],
        reason="Protocol administered out of window.",
    )

    row = fx.read_assessment(api, cognitive["id"])
    assert row["status"] == "INVALIDATED"
    assert row["invalidation_reason"] == "Protocol administered out of window."
    # The strongest delay in the case is still recorded on the row it belonged to.
    assert_delay_figures(row, 36.1, 36.1, True)

    # But the case no longer counts it anywhere.
    case = fx.read_case(api, context["case"]["id"])
    assert case["completed_domain_count"] == 4
    assert case["qualifying_domain_count"] == 1
    assert case["max_weighted_percent_delay"] == 33.3


def test_a_drafted_report_is_not_retracted_but_determination_is_refused(api):
    """From `REPORT_DRAFTED` the same invalidation moves no status at all.

    PRD §3.5: "When the case was standing at `REPORT_DRAFTED` or
    `REVISIONS_REQUESTED`, the status is deliberately left untouched — the drafted
    report is not retracted — even though `completed_domain_count` has now fallen below
    five."
    PRD §3.7: "Determination is available only from `REPORT_DRAFTED` — and, as the
    self-loop below describes, from `ELIGIBILITY_DETERMINED` — with any other status
    refused as `ERR_INVALID_CASE_STATE`; and it independently requires all five domains
    still to stand `COMPLETED`, refusing with `ERR_DOMAINS_INCOMPLETE` otherwise, which
    is the refusal a mid-flight invalidation of a completed assessment produces."

    Design: Difficulty/non_linear_state_machine/domains_complete_reverts_to_in_progress_when_an_assessment_is_invalidated
    """
    context = _standardized_case(api)
    case_id = context["case"]["id"]
    drafted = fx.draft_report(api, case_id, context["chair"]["id"])
    assert drafted["status"] == "REPORT_DRAFTED"

    fx.invalidate_assessment(
        api,
        context["assessments"]["ADAPTIVE"]["id"],
        context["evaluators"]["ADAPTIVE"]["id"],
    )

    standing = fx.read_case(api, case_id)
    assert standing["status"] == "REPORT_DRAFTED"
    assert standing["completed_domain_count"] == 4
    assert standing["composite_eligibility_recommendation"] == "INDETERMINATE"
    assert standing["report_narrative_summary"] == drafted["report_narrative_summary"]

    refused = api.determine_eligibility(
        case_id,
        f.eligible_determination_payload(standing["version"]),
        TEST_USERS["placement_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_DOMAINS_INCOMPLETE.value)
    assert fx.read_case(api, case_id)["status"] == "REPORT_DRAFTED"


# ------------- the plan fork: DRAFT to a terminal status inside a single request
def test_not_eligible_determination_closes_the_new_plan_in_the_same_request(api):
    """The plan never waits for a parent; it forks straight to its terminal status.

    PRD §3.7: "When the decision was `NOT_ELIGIBLE` the new plan is written at `DRAFT`
    and immediately moved by the system to `CLOSED_NOT_ELIGIBLE`, incrementing its
    `version`, and the child's derived `status` becomes `NOT_ELIGIBLE`."
    PRD §3.7: "When `eligibility_decision` is `NOT_ELIGIBLE`, both `setting` and
    `disability_category` must be absent."
    PRD §3.7: "A successful determination moves the case to `ELIGIBILITY_DETERMINED`,
    increments the case's `version`, and creates a `ServicePlan` at `DRAFT` that copies
    `evaluation_case_id`, copies `child_id` from the case, copies the case's
    `recommended_weekly_minutes` onto its own `recommended_weekly_minutes` so that the
    recommendation can later be compared against what was actually bought, stamps
    `determined_by_user_id` from the caller's `X-User-ID`, and starts with
    `assigned_weekly_minutes` at 0, `start_date` and `exit_date` absent,
    `kindergarten_transition_status` at `NOT_STARTED`, and `transition_conference_date`
    and `receiving_school_code` both absent."
    PRD §3.7: "And whenever the decision contradicts the team's own
    `composite_eligibility_recommendation` — a decision of `ELIGIBLE` against a
    recommendation of `NOT_ELIGIBLE_RECOMMENDED`, or a decision of `NOT_ELIGIBLE`
    against a recommendation of `ELIGIBLE_RECOMMENDED` — a non-empty
    `override_justification` is required, and its absence is refused with
    `ERR_ELIGIBILITY_OVERRIDE_JUSTIFICATION_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/service_plan_forks_to_closed_not_eligible_instead_of_pending_consent
    """
    context = _standardized_case(api)
    case_id = context["case"]["id"]
    site = fx.register_site(api)
    fx.draft_report(api, case_id, context["chair"]["id"])
    drafted = fx.read_case(api, case_id)
    assert drafted["composite_eligibility_recommendation"] == "ELIGIBLE_RECOMMENDED"

    plan = fx.determine_not_eligible(
        api,
        case_id,
        override_justification="Team judged the delays situational after the parent conference.",
    )
    assert plan["status"] == "CLOSED_NOT_ELIGIBLE"
    assert plan["eligibility_decision"] == "NOT_ELIGIBLE"
    assert plan["evaluation_case_id"] == case_id
    assert plan["child_id"] == context["child"]["id"]
    # No placement was bought, so neither setting nor category may be recorded.
    assert_fields_absent(plan, "setting", "disability_category", "start_date", "exit_date")
    assert plan["assigned_weekly_minutes"] == 0
    # The recommendation is still copied across for later comparison.
    assert plan["recommended_weekly_minutes"] == 120
    assert plan["kindergarten_transition_status"] == "NOT_STARTED"
    # Created at version 1, then moved once inside the same request.
    assert plan["version"] == 2

    assert fx.read_case(api, case_id)["status"] == "ELIGIBILITY_DETERMINED"
    assert fx.read_child(api, context["child"]["id"])["status"] == "NOT_ELIGIBLE"
    assert fx.read_site(api, site["id"])["reserved_iep_seat_count"] == 0


def test_eligible_determination_leaves_the_plan_waiting_at_draft(api):
    """The other branch of the same fork does not move the plan at all.

    PRD §3.7: "When the decision was `ELIGIBLE` the plan stays at `DRAFT`, waiting for
    service lines."
    PRD §3.1: "Otherwise, if the child has any plan at `DRAFT` or
    `PENDING_PARENT_CONSENT`, the status is again `IN_EVALUATION` — a plan the family
    has not consented to is not a service, so the child stays in evaluation even though
    the case behind it has already left the five in-evaluation statuses for
    `ELIGIBILITY_DETERMINED`."

    Design: Difficulty/non_linear_state_machine/service_plan_forks_to_closed_not_eligible_instead_of_pending_consent
    """
    context = _standardized_case(api)
    case_id = context["case"]["id"]
    fx.draft_report(api, case_id, context["chair"]["id"])

    plan = fx.determine_eligible(api, case_id)
    assert plan["status"] == "DRAFT"
    assert plan["eligibility_decision"] == "ELIGIBLE"
    assert plan["setting"] == "ITINERANT_ONLY"
    assert plan["disability_category"] == "DEVELOPMENTAL_DELAY"
    assert plan["assigned_weekly_minutes"] == 0
    assert plan["recommended_weekly_minutes"] == 120
    # Nothing moved it after creation.
    assert plan["version"] == 1

    assert fx.read_case(api, case_id)["status"] == "ELIGIBILITY_DETERMINED"
    assert fx.read_child(api, context["child"]["id"])["status"] == "IN_EVALUATION"


def test_a_closed_not_eligible_plan_is_terminal_on_arrival(api):
    """Having skipped `PENDING_PARENT_CONSENT`, the plan can no longer reach it.

    PRD §3.8: "Lines may only be added to a plan that is still at `DRAFT`; adding one to
    any other plan is refused with `ERR_INVALID_PLAN_STATE`."
    PRD §3.9: "Submitting a plan that is not at `DRAFT` is `ERR_INVALID_PLAN_STATE`, as
    is submitting a plan whose `eligibility_decision` is not `ELIGIBLE` or whose
    `setting` is absent."

    Design: Difficulty/non_linear_state_machine/service_plan_forks_to_closed_not_eligible_instead_of_pending_consent
    """
    context = _standardized_case(api)
    case_id = context["case"]["id"]
    fx.draft_report(api, case_id, context["chair"]["id"])
    plan = fx.determine_not_eligible(
        api,
        case_id,
        override_justification="Team judged the delays situational after the parent conference.",
    )
    assert plan["status"] == "CLOSED_NOT_ELIGIBLE"

    no_lines = api.add_service_line(
        plan["id"], f.service_line_payload(), TEST_USERS["placement_headers"]
    )
    validate_error(no_lines, ApiErrorId.ERR_INVALID_PLAN_STATE.value)

    no_consent = api.submit_plan_for_consent(
        plan["id"], f.consent_submission_payload(), TEST_USERS["placement_headers"]
    )
    validate_error(no_consent, ApiErrorId.ERR_INVALID_PLAN_STATE.value)

    unchanged = fx.read_plan(api, plan["id"])
    assert unchanged["status"] == "CLOSED_NOT_ELIGIBLE"
    assert unchanged["assigned_weekly_minutes"] == 0
    assert unchanged["version"] == plan["version"]
