"""Findings: classification-driven deadlines, the corrective-action loop and
the version token that guards a resubmission.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import add_days, assert_finding_ledger, assert_total_count
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_NONCONFORMITY_STATE_INVALID,
    ERR_NOT_ASSIGNED_TEAM_MEMBER,
    ERR_RESPONSE_WINDOW_CLOSED,
    ERR_STALE_NONCONFORMITY_VERSION,
)
from test_helpers.constants import (
    APP_IN_ASSESSMENT,
    APP_NC_OPEN,
    EFFECTIVENESS_FAIL,
    EMPLOYMENT_CONTRACT,
    EVIDENCE_FLOOR_CRITICAL,
    NC_CRITICAL,
    NC_MAJOR,
    NC_MINOR,
    NC_OBSERVATION,
    NC_OPEN,
    NC_RESPONSE_ACCEPTED,
    NC_RESPONSE_SUBMITTED,
    PLAN_MODE_HYBRID,
    QUALIFICATION_STATUS_QUALIFIED,
    REVIEW_ACCEPT,
    REVIEW_REJECT,
    ROLE_TYPE_TECHNICAL_EXPERT,
    SCHEME_DEFAULT_CRITICAL_CLOSE_DAYS,
    SCHEME_DEFAULT_MAJOR_CLOSE_DAYS,
    SCHEME_DEFAULT_MINOR_CLOSE_DAYS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER

NORTHLIGHT = {
    "legal_name": "Northlight Testing AB",
    "country_code": "SE",
    "contact_email": "qa@northlight.test",
}

THREE_SCOPE_LINES = [
    "mass calibration 1 mg - 20 kg",
    "temperature calibration -40 C - 250 C",
    "pressure calibration 0 - 700 bar",
]

SITE = "NORTHLIGHT-LAB-1"

CLAUSE_REF = "ISO_IEC_17025:2017 7.2.1"
STATEMENT_METHOD_VALIDATION = "calibration method validation records are incomplete"
STATEMENT_UNCERTAINTY = "calibration certificates lack measurement uncertainty"

ROOT_CAUSE = "method validation backlog"
ACTION_PLAN = "revalidate all five calibration methods and retrain two technicians"
FIRST_ACTION_PLAN = "revalidate the mass calibration method"
SECOND_ACTION_PLAN = "revalidate the mass calibration method and retrain one technician"

RAISED_INSTANT = "2026-09-10T09:00:00Z"
RAISED_DATE = "2026-09-10"
MAJOR_DUE_ON = "2026-11-09"


def test_rejected_response_then_failed_effectiveness_returns_the_finding_to_open(client):
    """The rejection loop and the effectiveness back-edge both land on
    ``OPEN``, and the attempt counter records both passes.

    PRD section 3.7: "A `FAIL` writes `verified_by_assessor_id`,
    `verified_evidence_count` and an `effectiveness_outcome` of `FAIL`, leaves
    `closed_on` null, moves the finding `RESPONSE_ACCEPTED → OPEN`, and bumps
    its `version`. Crucially the cycle's `nc_blocking_open_count` is left
    **unchanged** — the finding never left the blocking set, so nothing has to
    be added back — and the applicant must submit a further response." and "A
    resubmission after a rejecting review supersedes the earlier response text
    and increments `response_round` again — the counter records how many
    attempts were made and is never decremented by a rejection."

    Design: Difficulty/non_linear_state_machine/nonconformity_response_rejection_and_effectiveness_failure_cycles
    """
    ctx = fx.scenario_nc_open(client, "ISO17025-NCF")
    finding_id = ctx["finding_id"]
    assert ctx["finding"]["due_on"] == "2026-10-15"
    first = fx.submit_response(
        client,
        finding_id,
        ctx["applicant_headers"],
        root_cause="Template predates the 2025 reference standard change.",
        action_plan="Rebuild the budget template.",
    )
    assert first["status"] == NC_RESPONSE_SUBMITTED
    assert first["response_round"] == 1
    rejected = fx.review_response(
        client,
        finding_id,
        ctx["lead_headers"],
        REVIEW_REJECT,
        "Action plan omits re-issue of affected certificates.",
    )
    assert rejected["status"] == NC_OPEN
    assert rejected["response_round"] == 1, "A rejection never decrements the counter"
    assert rejected["action_plan"] == "Rebuild the budget template."
    second = fx.submit_response(
        client,
        finding_id,
        ctx["applicant_headers"],
        root_cause="Template predates the 2025 reference standard change.",
        action_plan="Rebuild the template and re-issue 42 affected certificates.",
    )
    assert second["response_round"] == 2
    accepted = fx.review_response(
        client,
        finding_id,
        ctx["lead_headers"],
        REVIEW_ACCEPT,
        "Re-issue commitment closes the gap.",
    )
    assert accepted["status"] == NC_RESPONSE_ACCEPTED

    response = client.verify_effectiveness(
        finding_id,
        f.effectiveness_payload(EFFECTIVENESS_FAIL, EVIDENCE_FLOOR_CRITICAL),
        ctx["tech_headers"],
    )

    finding = validate_success(response, 200)
    assert finding["status"] == NC_OPEN, "The RESPONSE_ACCEPTED -> OPEN back-edge"
    assert finding["effectiveness_outcome"] == EFFECTIVENESS_FAIL
    assert finding["closed_on"] is None
    assert finding["verified_by_assessor_id"] == ctx["tech_id"]
    assert finding["verified_evidence_count"] == EVIDENCE_FLOOR_CRITICAL
    assert finding["response_round"] == 2, (
        "response_round counts only submissions, and the rejection loop consumed one"
    )
    assert finding["reviewed_by_assessor_id"] == ctx["lead_id"]
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_NC_OPEN
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
    assert_total_count(
        client.list_decisions(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 0
    )


def test_reopening_a_finding_that_is_still_open_returns_invalid_state(client):
    """Reopening is defined from ``CLOSED`` only, so the finding's own status
    answers before the cycle's status is ever consulted.

    PRD section 2.9: "The target resource's own status: the action must be
    defined from its current status, and any requested `to_status` must be a
    declared successor of the current status — otherwise
    `ERR_INVALID_STATE_TRANSITION` (HTTP 409)." and section 3.7: "an
    `AssessmentManager` reopens a `CLOSED` finding by supplying a `reason`,
    provided the cycle is in `NC_OPEN` or `DECISION_PENDING`."

    Design: Corner/state_machines/reopen_a_finding_that_is_still_open_returns_invalid_state
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    fx.with_booked_session(
        ctx, "lead", "2026-09-07T08:00:00Z", "2026-09-08T16:00:00Z", site_ref=SITE
    )
    fx.set_clock(client, "2026-09-09T17:00:00Z")
    fx.complete_session(
        client,
        ctx["sessions"][-1]["id"],
        ctx["lead_headers"],
        evidence_note="witnessed two mass calibrations end to end",
    )
    assert fx.read_application(client, ctx["app_id"])["status"] == APP_IN_ASSESSMENT
    fx.with_finding(ctx, NC_MAJOR, clause_ref="7.2.1", statement=STATEMENT_UNCERTAINTY)
    assert ctx["finding"]["due_on"] == "2026-11-08"
    assert ctx["finding"]["reopen_count"] == 0

    response = client.reopen_nonconformity(
        ctx["finding_id"], f.reopen_payload("further evidence surfaced"), ASSESSMENT_MANAGER
    )

    validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)
    stored = fx.read_nonconformity(client, ctx["finding_id"])
    assert stored["status"] == NC_OPEN
    assert stored["due_on"] == add_days("2026-09-09", SCHEME_DEFAULT_MAJOR_CLOSE_DAYS)
    assert stored["reopen_count"] == 0
    assert stored["closed_on"] is None
    assert stored["review_note"] is None, "The rejected reason was never written"
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
    assert application["status"] == APP_IN_ASSESSMENT


def test_finding_due_dates_use_the_close_day_windows_and_skip_observations(client):
    """Three classifications yield three deadlines from one ``raised_on``, and
    the observation gets none.

    PRD section 3.7: "A `CRITICAL` finding is due `critical_nc_close_days`
    calendar days after `raised_on`; a `MAJOR` finding `major_nc_close_days`
    days after; a `MINOR` finding `minor_nc_close_days` days after. An
    `OBSERVATION` gets no deadline at all: `due_on` stays null, it never
    blocks a decision, and it can never be responded to, reviewed, escalated
    or closed." and "It also increments exactly one of two redistributable
    counters: `nc_observation_count` when the `classification` is
    `OBSERVATION`, and `nc_blocking_open_count` otherwise."

    Design: Corner/calculations/finding_due_dates_use_the_pinned_close_day_windows_and_skip_observations
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    fx.with_booked_session(
        ctx,
        "lead",
        "2026-09-07T08:00:00Z",
        "2026-09-08T16:00:00Z",
        site_ref=SITE,
        complete=True,
        evidence_note="witnessed two mass calibrations end to end",
    )
    fx.set_clock(client, "2026-09-15T09:00:00Z")
    critical = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_CRITICAL,
        "7.8.4",
        "uncertainty budgets absent from calibration certificates",
    )
    major = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_MAJOR,
        "7.2.1",
        "method validation records incomplete for two procedures",
    )
    minor = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_MINOR,
        "6.4.13",
        "two reference weights overdue for intermediate checks",
    )

    response = client.raise_nonconformity(
        ctx["app_id"],
        f.nonconformity_payload(
            "8.9.2",
            NC_OBSERVATION,
            "management review agenda could reference the impartiality risk register",
        ),
        ctx["lead_headers"],
    )

    observation = validate_success(response, 201)
    assert critical["raised_on"] == "2026-09-15"
    assert critical["due_on"] == "2026-10-15"
    assert critical["due_on"] == add_days(
        "2026-09-15", SCHEME_DEFAULT_CRITICAL_CLOSE_DAYS
    )
    assert major["due_on"] == "2026-11-14"
    assert major["due_on"] == add_days("2026-09-15", SCHEME_DEFAULT_MAJOR_CLOSE_DAYS)
    assert minor["due_on"] == "2026-12-14"
    assert minor["due_on"] == add_days("2026-09-15", SCHEME_DEFAULT_MINOR_CLOSE_DAYS)
    assert observation["due_on"] is None
    assert observation["status"] == NC_OPEN
    assert critical["raised_by_assessor_id"] == ctx["lead_id"]
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=4, blocking=3, closed=0, observation=1)


def test_raising_a_finding_without_a_confirmed_team_assignment_is_rejected(client):
    """A qualified assessor who is not on the team cannot write a finding
    against the cycle, and the ledger does not move.

    PRD section 2.10: "Raising a finding, recording a witnessing outcome,
    reviewing a corrective action and verifying effectiveness all require a
    `CONFIRMED` team assignment on the cycle, and the required `role_type`
    differs by operation — `LEAD_ASSESSOR` for a corrective-action review, and
    either `LEAD_ASSESSOR` or `TECHNICAL_ASSESSOR` for an effectiveness
    verification. A failure of any of those four is
    `ERR_NOT_ASSIGNED_TEAM_MEMBER` (HTTP 422)."

    Design: Corner/errors/raising_a_finding_without_a_confirmed_team_assignment_rejected
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_assessor(
        ctx,
        "outsider",
        full_name="Ines Solberg",
        email="ines.solberg@ab.test",
        role_type=ROLE_TYPE_TECHNICAL_EXPERT,
        employment_type=EMPLOYMENT_CONTRACT,
    )
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    fx.with_booked_session(
        ctx, "lead", "2026-09-07T08:00:00Z", "2026-09-08T16:00:00Z", site_ref=SITE
    )
    fx.with_booked_session(
        ctx, "lead", "2026-09-09T08:00:00Z", "2026-09-09T16:00:00Z", site_ref=SITE
    )
    fx.set_clock(client, RAISED_INSTANT)
    for session in ctx["sessions"]:
        fx.complete_session(
            client,
            session["id"],
            ctx["lead_headers"],
            evidence_note="calibration witnessing completed as planned",
        )
    before = fx.read_application(client, ctx["app_id"])
    assert before["status"] == APP_IN_ASSESSMENT
    assert before["completed_witness_session_count"] == 2

    response = client.raise_nonconformity(
        ctx["app_id"],
        f.nonconformity_payload(CLAUSE_REF, NC_MAJOR, STATEMENT_METHOD_VALIDATION),
        ctx["outsider_headers"],
    )

    validate_error(response, ERR_NOT_ASSIGNED_TEAM_MEMBER, 422)
    after_rejection = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(after_rejection, total=0, blocking=0, closed=0, observation=0)
    assert_total_count(
        client.list_nonconformities(
            ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}
        ),
        0,
    )
    accepted = validate_success(
        client.raise_nonconformity(
            ctx["app_id"],
            f.nonconformity_payload(CLAUSE_REF, NC_MAJOR, STATEMENT_METHOD_VALIDATION),
            ctx["lead_headers"],
        ),
        201,
    )
    assert accepted["status"] == NC_OPEN
    assert accepted["raised_by_assessor_id"] == ctx["lead_id"]
    assert accepted["raised_on"] == RAISED_DATE
    assert accepted["due_on"] == MAJOR_DUE_ON
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
    assert application["status"] == APP_IN_ASSESSMENT
    outsider = fx.read_assessor(client, ctx["outsider_id"])
    assert outsider["qualification_status"] == QUALIFICATION_STATUS_QUALIFIED, (
        "The rule is about assignment, not about competence"
    )


def test_corrective_action_outside_the_window_or_after_acceptance_is_rejected(client):
    """The due date itself is inside the window, the day after is not, and an
    accepted finding accepts no further response.

    PRD section 3.7: "The current logical-clock date must be on or before the
    finding's `due_on`; a submission on the due date itself is accepted, a
    submission the day after is rejected with `ERR_RESPONSE_WINDOW_CLOSED`."
    and "The finding must be `OPEN` (`ERR_NONCONFORMITY_STATE_INVALID`), must
    not be an `OBSERVATION`, and the cycle must be in `NC_OPEN` and not
    frozen."

    Design: Corner/errors/corrective_action_response_outside_the_window_or_after_acceptance_rejected
    """
    ctx = fx.scenario_nc_open(client, "ISO17025-NCW", NC_MAJOR, RAISED_INSTANT)
    finding_id = ctx["finding_id"]
    assert ctx["finding"]["due_on"] == MAJOR_DUE_ON
    assert fx.read_application(client, ctx["app_id"])["status"] == APP_NC_OPEN
    version_before = fx.read_nonconformity(client, finding_id)["version"]
    fx.set_clock(client, "2026-11-10T09:00:00Z")

    response = client.submit_response(
        finding_id,
        f.response_payload(version_before, ROOT_CAUSE, ACTION_PLAN),
        ctx["applicant_headers"],
    )

    validate_error(response, ERR_RESPONSE_WINDOW_CLOSED, 422)
    stored = fx.read_nonconformity(client, finding_id)
    assert stored["status"] == NC_OPEN
    assert stored["version"] == version_before
    assert stored["response_round"] == 0
    assert stored["action_plan"] is None
    fx.set_clock(client, "2026-11-09T09:00:00Z")
    submitted = validate_success(
        client.submit_response(
            finding_id,
            f.response_payload(version_before, ROOT_CAUSE, ACTION_PLAN),
            ctx["applicant_headers"],
        ),
        200,
    )
    assert submitted["status"] == NC_RESPONSE_SUBMITTED
    assert submitted["response_submitted_on"] == MAJOR_DUE_ON
    assert submitted["response_round"] == 1
    accepted = fx.review_response(
        client,
        finding_id,
        ctx["lead_headers"],
        REVIEW_ACCEPT,
        "root cause and plan are adequate",
    )
    assert accepted["status"] == NC_RESPONSE_ACCEPTED
    assert accepted["reviewed_by_assessor_id"] == ctx["lead_id"]
    current_version = fx.read_nonconformity(client, finding_id)["version"]

    second = client.submit_response(
        finding_id,
        f.response_payload(
            current_version, ROOT_CAUSE, "second revision of the same plan"
        ),
        ctx["applicant_headers"],
    )

    validate_error(second, ERR_NONCONFORMITY_STATE_INVALID, 409)
    final = fx.read_nonconformity(client, finding_id)
    assert final["status"] == NC_RESPONSE_ACCEPTED
    assert final["action_plan"] == ACTION_PLAN
    assert final["response_round"] == 1


def test_stale_nonconformity_version_on_a_resubmitted_response_is_rejected(client):
    """After a rejecting review the finding is legally ``OPEN`` again, so only
    the version token separates a resubmission from a blind one.

    PRD section 2.6: "That request must carry
    `expected_nonconformity_version`, a non-optional integer field whose value
    is the `Nonconformity` `version` the client last read. If it does not equal
    the finding's current `version`, the submission is rejected with
    `ERR_STALE_NONCONFORMITY_VERSION` (HTTP 412)." and section 3.7: "`REJECT`
    sends it back `RESPONSE_SUBMITTED → OPEN` while leaving `response_round`,
    `root_cause` and `action_plan` exactly as submitted, so the applicant can
    see what was rejected and may resubmit for as long as the due date has not
    passed."

    Design: Corner/cross_cutting_complexity_layers/stale_nonconformity_version_on_a_resubmitted_response_rejected
    """
    ctx = fx.scenario_nc_open(client, "ISO17025-NCV", NC_MAJOR, RAISED_INSTANT)
    finding_id = ctx["finding_id"]
    first_version = validate_success(
        client.get_nonconformity(finding_id, ctx["applicant_headers"]), 200
    )["version"]
    validate_success(
        client.submit_response(
            finding_id,
            f.response_payload(first_version, ROOT_CAUSE, FIRST_ACTION_PLAN),
            ctx["applicant_headers"],
        ),
        200,
    )
    rejected = fx.review_response(
        client,
        finding_id,
        ctx["lead_headers"],
        REVIEW_REJECT,
        "the plan covers one method of five",
    )
    assert rejected["status"] == NC_OPEN

    response = client.submit_response(
        finding_id,
        f.response_payload(first_version, ROOT_CAUSE, SECOND_ACTION_PLAN),
        ctx["applicant_headers"],
    )

    validate_error(response, ERR_STALE_NONCONFORMITY_VERSION, 412)
    stale_state = fx.read_nonconformity(client, finding_id)
    assert stale_state["status"] == NC_OPEN, (
        "The state was not the obstacle: OPEN is a legal state for this write"
    )
    assert stale_state["action_plan"] == FIRST_ACTION_PLAN
    assert stale_state["response_round"] == 1
    current_version = validate_success(
        client.get_nonconformity(finding_id, ctx["applicant_headers"]), 200
    )["version"]
    assert current_version == first_version + 2, (
        "One increment for the submission and one for the rejecting review"
    )
    resubmitted = validate_success(
        client.submit_response(
            finding_id,
            f.response_payload(current_version, ROOT_CAUSE, ACTION_PLAN),
            ctx["applicant_headers"],
        ),
        200,
    )
    assert resubmitted["status"] == NC_RESPONSE_SUBMITTED
    assert resubmitted["action_plan"] == ACTION_PLAN
    assert resubmitted["response_round"] == 2
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
