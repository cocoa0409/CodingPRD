"""Closing findings: the effectiveness gates, the four-hop closure cascade,
the escalation window and the compensating reopen.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import add_days, assert_finding_ledger, assert_total_count
from test_helpers.api_errors import (
    ERR_EFFECTIVENESS_EVIDENCE_INSUFFICIENT,
    ERR_NOT_YET_OVERDUE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.constants import (
    APP_DECISION_PENDING,
    APP_IN_ASSESSMENT,
    APP_NC_OPEN,
    DECISION_DEFERRED,
    DECISION_VOTING,
    EFFECTIVENESS_PASS,
    EVIDENCE_FLOOR_CRITICAL,
    NC_CLOSED,
    NC_MAJOR,
    NC_OBSERVATION,
    NC_OPEN,
    NC_RESPONSE_ACCEPTED,
    ORG_UNDER_ASSESSMENT,
    PLAN_EXECUTED,
    PLAN_MODE_HYBRID,
    RISK_WEIGHT_CRITICAL,
    SCHEME_DEFAULT_MAJOR_CLOSE_DAYS,
    VOTE_DEFER,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER, SCHEME_MANAGER

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

REOPEN_REASON = "Re-issued certificates still carry the old uncertainty budget."


def test_close_assessment_with_only_observation_findings_reaches_decision_pending(client):
    """Two observations leave the blocking set empty, so the close routes to
    the panel rather than to corrective action.

    PRD section 3.6: "When `nc_blocking_open_count` is exactly 0, the cycle
    moves `IN_ASSESSMENT → DECISION_PENDING`, a decision record is created in
    `status` `VOTING` with `round` equal to the cycle's current
    `decision_round` and an empty ballot list, and that record's creation
    recomputes the applicant organization's `risk_score` under the at-decision
    variant described in §3.7 and bumps the organization's `version`." and
    section 3.7: "The raw score for a cycle sums six weighted terms over the
    cycle's findings whose `classification` is not `OBSERVATION`: 5 points for
    each `CRITICAL` finding, 3 for each `MAJOR`, 1 for each `MINOR`, 4 for each
    finding closed late — that is, whose `closed_on` is strictly later than its
    `due_on` — 6 for each finding in status `ESCALATED`, and 2 for each
    qualifying upheld complaint."

    Design: Difficulty/boundary_precision_check/close_assessment_with_only_observation_findings_treats_blocking_set_as_empty
    """
    ctx = fx.new_context(client, "ISO17025-OBS")
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
    )
    fx.with_booked_session(
        ctx,
        "lead",
        "2026-09-09T08:00:00Z",
        "2026-09-09T16:00:00Z",
        site_ref=SITE,
        complete=True,
    )
    fx.set_clock(client, "2026-09-15T09:00:00Z")
    observation_1 = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_OBSERVATION,
        "8.3.2",
        "Document control index would benefit from a revision history column.",
    )
    observation_2 = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_OBSERVATION,
        "6.4.5",
        "Balance handling instructions are informal but effective.",
    )

    response = client.close_assessment(ctx["app_id"], ASSESSMENT_MANAGER)

    application = validate_success(response, 200)
    assert observation_1["due_on"] is None
    assert observation_2["due_on"] is None
    assert_finding_ledger(application, total=2, blocking=0, closed=0, observation=2)
    assert application["status"] == APP_DECISION_PENDING, (
        "An observation-only ledger is an empty blocking set"
    )
    assert application["completed_witness_session_count"] == 2
    assert (
        application["completed_witness_session_count"]
        == ctx["scheme"]["witness_min_count"]
    ), "The session count sits exactly on the pinned floor"
    plan = validate_success(client.get_plan(ctx["plan_id"], ASSESSMENT_MANAGER), 200)
    assert plan["status"] == PLAN_EXECUTED
    rows = assert_total_count(
        client.list_decisions(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 1
    )
    assert rows[0]["status"] == DECISION_VOTING
    assert rows[0]["round"] == 1
    assert rows[0]["vote_count"] == 0
    assert rows[0]["votes"] == []
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["risk_score"] == 0, "Observations carry no weight"


def test_escalating_a_finding_before_its_due_date_is_rejected(client):
    """The escalation window opens strictly after the deadline, so the cascade
    never runs and nothing is frozen.

    PRD section 3.7: "An `AssessmentManager` escalates a finding that is in
    `OPEN` or `RESPONSE_SUBMITTED`, whose `classification` is `CRITICAL` or
    `MAJOR`, and for which the current logical-clock date is strictly after
    `due_on`. An attempt on or before the due date is rejected with
    `ERR_NOT_YET_OVERDUE`; `MINOR` and `OBSERVATION` findings are never
    escalable."

    Design: Corner/validations/escalating_a_finding_before_its_due_date_rejected
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
    fx.with_finding(
        ctx,
        NC_MAJOR,
        clause_ref="7.2.1",
        statement="method validation records incomplete for two procedures",
    )
    assert ctx["finding"]["due_on"] == "2026-11-08"

    response = client.escalate_nonconformity(ctx["finding_id"], ASSESSMENT_MANAGER)

    validate_error(response, ERR_NOT_YET_OVERDUE, 422)
    stored = fx.read_nonconformity(client, ctx["finding_id"])
    assert stored["status"] == NC_OPEN
    assert stored["due_on"] == add_days("2026-09-09", SCHEME_DEFAULT_MAJOR_CLOSE_DAYS)
    assert stored["escalated_on"] is None
    application = fx.read_application(client, ctx["app_id"])
    assert application["suspension_blocked"] is False, "The five-hop cascade never ran"
    assert application["status"] == APP_IN_ASSESSMENT
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["status"] == ORG_UNDER_ASSESSMENT
    assert organization["risk_score"] == 0


def test_segregation_of_duties_precedes_the_effectiveness_evidence_floor(client):
    """The reviewer who accepted the corrective action is turned away on
    independence, before the evidence count is ever counted.

    PRD section 2.9: "The complete precedence order the server applies to any
    request is the following, and it is normative — an earlier rule always
    masks a later one, so a request that violates several rules reports only
    the earliest:" and section 3.7: "The verifier supplies an `outcome` of
    `PASS` or `FAIL` and a `verified_evidence_count`, which must be at least
    the minimum evidence count for the finding's `classification`: three items
    for a `CRITICAL` finding, two for a `MAJOR`, and one for a `MINOR`. Too few
    items is `ERR_EFFECTIVENESS_EVIDENCE_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_effectiveness_evidence_floor
    """
    ctx = fx.scenario_nc_open(client, "ISO17025-SOD")
    fx.with_accepted_response(ctx)
    finding_id = ctx["finding_id"]

    response = client.verify_effectiveness(
        finding_id, f.effectiveness_payload(EFFECTIVENESS_PASS, 0), ctx["lead_headers"]
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 422)
    stored = fx.read_nonconformity(client, finding_id)
    assert stored["status"] == NC_RESPONSE_ACCEPTED
    assert stored["verified_by_assessor_id"] is None
    assert stored["verified_evidence_count"] == 0
    assert stored["effectiveness_outcome"] is None
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_NC_OPEN
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
    assert_total_count(
        client.list_decisions(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 0
    )
    lower_priority = client.verify_effectiveness(
        finding_id, f.effectiveness_payload(EFFECTIVENESS_PASS, 0), ctx["tech_headers"]
    )
    validate_error(lower_priority, ERR_EFFECTIVENESS_EVIDENCE_INSUFFICIENT, 422)
    assert (
        fx.read_nonconformity(client, finding_id)["status"] == NC_RESPONSE_ACCEPTED
    ), "Neither rejected verification moved the finding"


def test_effectiveness_pass_closes_the_finding_then_the_ledger_then_the_decision(client):
    """One PASS verification walks four hops: the finding, the ledger, the
    cycle plus its decision record, and the organization's risk.

    PRD section 3.7: "A `PASS` writes `verified_by_assessor_id`,
    `verified_evidence_count`, an `effectiveness_outcome` of `PASS` and a
    `closed_on` at the current logical-clock date, moving the finding
    `RESPONSE_ACCEPTED → CLOSED` and bumping its `version`. The ledger then
    redistributes: the cycle's `nc_blocking_open_count` decreases by 1 and
    `nc_closed_count` increases by 1 while `nc_total_count` stays put, and the
    cycle's `version` is bumped. If that closure was the last blocking finding
    — the cycle is in `NC_OPEN` and `nc_blocking_open_count` has reached 0 —
    the cycle advances `NC_OPEN → DECISION_PENDING` and a decision record is
    created in `status` `VOTING` for the cycle's current `decision_round` with
    an empty ballot list"

    Design: Difficulty/transitive_cascade/effectiveness_pass_closes_finding_then_ledger_then_decision_then_risk
    """
    ctx = fx.scenario_nc_open(client, "ISO17025-CAS")
    fx.with_accepted_response(ctx)
    before = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(before, total=1, blocking=1, closed=0, observation=0)

    response = client.verify_effectiveness(
        ctx["finding_id"],
        f.effectiveness_payload(EFFECTIVENESS_PASS, EVIDENCE_FLOOR_CRITICAL),
        ctx["tech_headers"],
    )

    finding = validate_success(response, 200)
    assert finding["status"] == NC_CLOSED
    assert finding["effectiveness_outcome"] == EFFECTIVENESS_PASS
    assert finding["closed_on"] == fx.CLOCK_ASSESSMENT_DATE
    assert finding["verified_by_assessor_id"] == ctx["tech_id"]
    assert finding["verified_evidence_count"] == EVIDENCE_FLOOR_CRITICAL
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=1, blocking=0, closed=1, observation=0)
    assert application["status"] == APP_DECISION_PENDING
    rows = assert_total_count(
        client.list_decisions(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 1
    )
    assert rows[0]["status"] == DECISION_VOTING
    assert rows[0]["round"] == 1
    assert rows[0]["vote_count"] == 0
    assert rows[0]["votes"] == []
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["risk_score"] == RISK_WEIGHT_CRITICAL, (
        "One critical finding closed on time carries no late weight"
    )
    assert organization["status"] == ORG_UNDER_ASSESSMENT, (
        "Recomputing risk does not move the organization"
    )
    plan = validate_success(client.get_plan(ctx["plan_id"], ASSESSMENT_MANAGER), 200)
    assert plan["status"] == PLAN_EXECUTED


def test_reopening_a_closed_finding_restores_the_ledger_and_defers_the_decision(client):
    """The compensating reopen puts every counter back exactly where the
    closure found it and parks the pending decision.

    PRD section 3.7: "This is a compensating action and it reverses exactly
    what the closure did: `reopen_count` increases by 1, `closed_on` and
    `effectiveness_outcome` are cleared to null, the supplied `reason` is
    written into `review_note`, the finding returns `CLOSED → OPEN`, and its
    `version` is bumped. The cycle's `nc_blocking_open_count` increases by 1
    and `nc_closed_count` decreases by 1, with `nc_total_count` again
    untouched. And when the cycle had already reached `DECISION_PENDING`, the
    reopening pulls it back: the cycle moves `DECISION_PENDING → NC_OPEN`, its
    `decision_round` increases by 1, and the decision record of the previous
    round that was still `VOTING` is moved to `DEFERRED` — that record is
    written with an `outcome` of `DEFER` and a `decided_on`, and its ballot
    list is preserved as an audit record rather than discarded."

    Design: Difficulty/compensating_invariant/nonconformity_reopen_restores_the_application_finding_ledger_exactly
    """
    ctx = fx.scenario_decision_pending(client, "ISO17025-REO")
    before = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(before, total=1, blocking=0, closed=1, observation=0)
    assert before["nc_blocking_open_count"] + before["nc_closed_count"] == (
        before["nc_total_count"] - before["nc_observation_count"]
    )
    verified_by = ctx["finding"]["verified_by_assessor_id"]

    response = client.reopen_nonconformity(
        ctx["finding_id"], f.reopen_payload(REOPEN_REASON), ASSESSMENT_MANAGER
    )

    finding = validate_success(response, 200)
    assert finding["status"] == NC_OPEN
    assert finding["reopen_count"] == 1
    assert finding["closed_on"] is None
    assert finding["effectiveness_outcome"] is None
    assert finding["review_note"] == REOPEN_REASON
    assert finding["verified_evidence_count"] == EVIDENCE_FLOOR_CRITICAL, (
        "The failed closure stays on the record as an audit trail"
    )
    assert finding["verified_by_assessor_id"] == verified_by
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=1, blocking=1, closed=0, observation=0)
    assert application["nc_blocking_open_count"] + application["nc_closed_count"] == (
        application["nc_total_count"] - application["nc_observation_count"]
    ), "The ledger invariant holds after the compensation exactly as before"
    assert application["status"] == APP_NC_OPEN
    assert application["decision_round"] == 2
    deferred = validate_success(
        client.get_decision(ctx["decision_id"], ASSESSMENT_MANAGER), 200
    )
    assert deferred["status"] == DECISION_DEFERRED
    assert deferred["outcome"] == VOTE_DEFER
    assert deferred["decided_on"] == fx.CLOCK_ASSESSMENT_DATE
    assert deferred["votes"] == []
    assert deferred["vote_count"] == 0
    remaining = assert_total_count(
        client.list_decisions(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 1
    )
    assert [row["id"] for row in remaining] == [ctx["decision_id"]], (
        "No fresh record until the blocking count returns to zero"
    )
    assert_total_count(
        client.list_scopes(SCHEME_MANAGER, {"organization_id": ctx["org_id"]}), 0
    )
