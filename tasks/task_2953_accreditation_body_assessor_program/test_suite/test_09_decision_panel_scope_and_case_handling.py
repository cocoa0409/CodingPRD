"""The panel, the accredited scope and the cases that follow it: ballots,
surveillance cadence, complaints, appeals and mutual-recognition duties.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import add_days, assert_finding_ledger, assert_total_count
from test_helpers.api_errors import (
    ERR_APPEAL_REVIEWER_CONFLICT,
    ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE,
    ERR_DUPLICATE_PANEL_VOTE,
    ERR_MRA_ESCALATION_NOT_ELIGIBLE,
    ERR_PANEL_INDEPENDENCE_BREACH,
    ERR_PANEL_QUORUM_NOT_MET,
    ERR_SCOPE_LINE_NOT_REQUESTED,
    ERR_SCOPE_NOT_ACTIVE,
    ERR_UNANNOUNCED_NOT_AUTHORIZED,
)
from test_helpers.constants import (
    APP_GRANTED,
    APP_SUBMITTED,
    CASE_KIND_APPEAL,
    CASE_KIND_COMPLAINT,
    CASE_OUTCOME_UPHELD,
    CASE_RECEIVED,
    CASE_UNDER_REVIEW,
    CASE_UPHELD,
    CYCLE_SURVEILLANCE,
    CYCLE_UNANNOUNCED,
    DECISION_DECIDED,
    DECISION_VOTING,
    EFFECTIVENESS_PASS,
    EVIDENCE_FLOOR_CRITICAL,
    EVIDENCE_FLOOR_MAJOR,
    NC_CRITICAL,
    NC_MAJOR,
    NOTICE_DAYS_DEFAULT,
    NOTICE_DAYS_UNANNOUNCED,
    ORG_ACCREDITED,
    ORG_APPLIED,
    PANEL_QUORUM,
    RISK_WEIGHT_CLOSED_LATE,
    RISK_WEIGHT_CRITICAL,
    RISK_WEIGHT_MAJOR,
    RISK_WEIGHT_UPHELD_COMPLAINT,
    ROLE_TYPE_TECHNICAL_EXPERT,
    SCOPE_ACTIVE,
    SCOPE_SUSPENDED,
    VOTE_GRANT,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSESSMENT_MANAGER,
    COMPLAINT_OFFICER,
    SCHEME_MANAGER,
    make_decision_panel_member_headers,
)

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

UNREQUESTED_LINE = "humidity calibration 10 - 90 percent rh"

COMPLAINT_SUMMARY = (
    "The laboratory issued calibration certificates carrying the accreditation "
    "mark for two pressure ranges that are outside its accredited scope."
)
APPEAL_SUMMARY = (
    "The panel weighed the witnessing evidence unfairly and the granted scope "
    "should have carried no conditions at all."
)
FILED_BY = "Vera Lindqvist"
RESOLUTION_NOTE = "scope breach confirmed against two certificates"
SUSPENSION_REASON = "Escalated nonconformity on the mass calibration method."
MRA_BODY = "European co-operation for Accreditation"


def test_upholding_a_complaint_counts_it_and_reprices_the_organization(client):
    """The case walks RECEIVED to UNDER_REVIEW to UPHELD, and only the uphold
    touches the organization.

    PRD section 3.10: "**Assigning an independent reviewer.** A
    `ComplaintOfficer` moves a `RECEIVED` case to `UNDER_REVIEW` by nominating
    a `reviewer_assessor_id`." and "`UPHELD` increments the organization's
    `upheld_complaint_count` by 1 and recomputes the organization's
    `risk_score` under the at-decision variant — which is how a substantiated
    complaint tightens the organization's future surveillance cadence through
    the 730-day lookback window of §3.7."

    Design: Corner/endpoints/complaint_review_and_uphold_action_chain
    """
    ctx = fx.new_context(client, "ISO17025-CMP")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    case = validate_success(
        client.create_complaint(
            f.complaint_payload(ctx["org_id"], COMPLAINT_SUMMARY, FILED_BY),
            COMPLAINT_OFFICER,
        ),
        201,
    )
    assert case["status"] == CASE_RECEIVED
    assert case["kind"] == CASE_KIND_COMPLAINT
    assert case["reviewer_assessor_id"] is None
    under_review = validate_success(
        client.review_complaint(
            case["id"], f.complaint_review_payload(ctx["lead_id"]), COMPLAINT_OFFICER
        ),
        200,
    )
    assert under_review["status"] == CASE_UNDER_REVIEW

    response = client.resolve_complaint(
        case["id"],
        f.complaint_resolution_payload(CASE_OUTCOME_UPHELD, RESOLUTION_NOTE),
        COMPLAINT_OFFICER,
    )

    resolved = validate_success(response, 200)
    assert resolved["status"] == CASE_UPHELD
    assert resolved["reviewer_assessor_id"] == ctx["lead_id"]
    assert resolved["resolved_on"] == fx.CLOCK_BUILD_DATE
    assert resolved["resolution_note"] == RESOLUTION_NOTE
    assert resolved["mra_body"] is None
    assert resolved["mra_escalated_on"] is None
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["upheld_complaint_count"] == 1
    assert organization["risk_score"] == RISK_WEIGHT_UPHELD_COMPLAINT
    assert organization["status"] == ORG_APPLIED, (
        "Resolving a case is not an accreditation event"
    )


def test_mra_escalation_of_an_upheld_complaint_is_rejected(client):
    """Escalation is reserved for appeals, so an upheld complaint discharges no
    mutual-recognition obligation.

    PRD section 3.10: "Escalation is narrowly eligible: the case's `kind` must
    be `APPEAL`, its `status` must be `UPHELD`, and the organization must hold
    at least one scope in `ACTIVE` or `SUSPENDED` status — a case that fails
    any of those three is rejected with `ERR_MRA_ESCALATION_NOT_ELIGIBLE`."

    Design: Corner/endpoints/mra_escalation_of_an_upheld_complaint_rather_than_an_appeal_rejected
    """
    ctx = fx.new_context(client, "ISO17025-MRA")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    case = validate_success(
        client.create_complaint(
            f.complaint_payload(ctx["org_id"], COMPLAINT_SUMMARY, FILED_BY),
            COMPLAINT_OFFICER,
        ),
        201,
    )
    validate_success(
        client.review_complaint(
            case["id"], f.complaint_review_payload(ctx["lead_id"]), COMPLAINT_OFFICER
        ),
        200,
    )
    upheld = validate_success(
        client.resolve_complaint(
            case["id"],
            f.complaint_resolution_payload(CASE_OUTCOME_UPHELD, RESOLUTION_NOTE),
            COMPLAINT_OFFICER,
        ),
        200,
    )
    assert upheld["status"] == CASE_UPHELD

    response = client.escalate_complaint_to_mra(
        case["id"], f.mra_escalation_payload(MRA_BODY), COMPLAINT_OFFICER
    )

    validate_error(response, ERR_MRA_ESCALATION_NOT_ELIGIBLE, 422)
    stored = validate_success(client.get_complaint(case["id"], COMPLAINT_OFFICER), 200)
    assert stored["status"] == CASE_UPHELD
    assert stored["mra_body"] is None
    assert stored["mra_escalated_on"] is None
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["mra_escalation_count"] == 0
    assert organization["active_scope_count"] == 0


def test_appeal_reviewer_who_assessed_or_voted_on_the_cycle_is_rejected(client):
    """The stricter appeal test bars both the assessing team and the panel that
    voted, and it is specific to appeals.

    PRD section 3.10: "For an `APPEAL` there is a further and stricter test:
    the nominee must hold no team assignment in `PROPOSED`, `CONFIRMED` or
    `RECUSED` status on the appealed cycle, and must appear as the
    `voter_assessor_id` of no ballot on any decision record of that cycle. A
    nominee who assessed or voted on the cycle being appealed is rejected with
    `ERR_APPEAL_REVIEWER_CONFLICT`."

    Design: Corner/errors/appeal_reviewer_who_voted_on_the_decision_rejected
    """
    ctx = fx.scenario_granted_scope(
        client, "ISO17025-APL", requested_scope_lines=THREE_SCOPE_LINES
    )
    fx.with_assessor(
        ctx,
        "indep",
        full_name="Ines Solberg",
        email="ines.solberg@ab.test",
        role_type=ROLE_TYPE_TECHNICAL_EXPERT,
    )
    voter_id = ctx["panel"][0]["assessor"]["id"]
    independent_id = ctx["assessors"]["indep"]["assessor"]["id"]
    appeal = validate_success(
        client.create_complaint(
            f.complaint_payload(
                ctx["org_id"],
                APPEAL_SUMMARY,
                FILED_BY,
                kind=CASE_KIND_APPEAL,
                application_id=ctx["app_id"],
            ),
            COMPLAINT_OFFICER,
        ),
        201,
    )

    response = client.review_complaint(
        appeal["id"], f.complaint_review_payload(voter_id), COMPLAINT_OFFICER
    )

    validate_error(response, ERR_APPEAL_REVIEWER_CONFLICT, 422)
    assessed = client.review_complaint(
        appeal["id"], f.complaint_review_payload(ctx["lead_id"]), COMPLAINT_OFFICER
    )
    validate_error(assessed, ERR_APPEAL_REVIEWER_CONFLICT, 422)
    stored = validate_success(client.get_complaint(appeal["id"], COMPLAINT_OFFICER), 200)
    assert stored["status"] == CASE_RECEIVED
    assert stored["reviewer_assessor_id"] is None
    accepted = validate_success(
        client.review_complaint(
            appeal["id"], f.complaint_review_payload(independent_id), COMPLAINT_OFFICER
        ),
        200,
    )
    assert accepted["status"] == CASE_UNDER_REVIEW
    assert accepted["reviewer_assessor_id"] == independent_id
    complaint = validate_success(
        client.create_complaint(
            f.complaint_payload(ctx["org_id"], COMPLAINT_SUMMARY, FILED_BY),
            COMPLAINT_OFFICER,
        ),
        201,
    )
    same_voter = validate_success(
        client.review_complaint(
            complaint["id"], f.complaint_review_payload(voter_id), COMPLAINT_OFFICER
        ),
        200,
    )
    assert same_voter["reviewer_assessor_id"] == voter_id, (
        "The ballot conflict is an appeal-only test"
    )
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["upheld_complaint_count"] == 0


def test_surveillance_on_a_suspended_scope_and_unannounced_without_authority_are_rejected(
    client,
):
    """A follow-on cycle needs a live scope, and an unannounced one needs the
    pinned revision's authority.

    PRD section 3.9: "The scope must be in `status` `ACTIVE`, or the request is
    rejected with `ERR_SCOPE_NOT_ACTIVE`. The same notice-period rule as an
    initial cycle applies — an `UNANNOUNCED` cycle must carry exactly 0
    `notice_days` and any other `cycle_type` at least 14, on pain of
    `ERR_INVALID_NOTICE_PERIOD` — as does the unannounced-authority gate: an
    `UNANNOUNCED` cycle requires the pinned scheme revision's
    `unannounced_authority` to be true, or the request fails with
    `ERR_UNANNOUNCED_NOT_AUTHORIZED`."

    Design: Corner/errors/surveillance_cycle_on_a_suspended_scope_or_unannounced_without_authority_rejected
    """
    ctx = fx.scenario_granted_scope(
        client,
        "ISO17025-SRV",
        requested_scope_lines=THREE_SCOPE_LINES,
        scheme_overrides={"unannounced_authority": False},
    )
    scope_id = ctx["scope_id"]
    suspended = validate_success(
        client.set_scope_status(
            scope_id,
            f.scope_status_payload(SCOPE_SUSPENDED, SUSPENSION_REASON),
            SCHEME_MANAGER,
        ),
        200,
    )
    assert suspended["status"] == SCOPE_SUSPENDED
    assert suspended["mra_notified"] is True

    response = client.open_surveillance_application(
        scope_id,
        f.surveillance_application_payload(CYCLE_SURVEILLANCE),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_SCOPE_NOT_ACTIVE, 422)
    assert_total_count(
        client.list_applications(ASSESSMENT_MANAGER, {"organization_id": ctx["org_id"]}),
        1,
    )
    restored = validate_success(
        client.set_scope_status(
            scope_id, f.scope_status_payload(SCOPE_ACTIVE), SCHEME_MANAGER
        ),
        200,
    )
    assert restored["status"] == SCOPE_ACTIVE
    assert restored["suspension_reason"] is None
    unannounced = client.open_surveillance_application(
        scope_id,
        f.surveillance_application_payload(
            CYCLE_UNANNOUNCED, notice_days=NOTICE_DAYS_UNANNOUNCED
        ),
        ASSESSMENT_MANAGER,
    )
    validate_error(unannounced, ERR_UNANNOUNCED_NOT_AUTHORIZED, 422)
    accepted = validate_success(
        client.open_surveillance_application(
            scope_id,
            f.surveillance_application_payload(CYCLE_SURVEILLANCE),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert accepted["cycle_type"] == CYCLE_SURVEILLANCE
    assert accepted["origin_scope_id"] == scope_id
    assert accepted["status"] == APP_SUBMITTED
    assert accepted["notice_days"] == NOTICE_DAYS_DEFAULT
    assert accepted["requested_scope_lines"] == THREE_SCOPE_LINES, (
        "An omitted list is inherited from the scope"
    )
    assert_total_count(
        client.list_applications(ASSESSMENT_MANAGER, {"organization_id": ctx["org_id"]}),
        2,
    )


def test_panel_ballot_and_grant_shape_rules_guard_the_finalization(client):
    """Independence, quorum, one-ballot-per-member and the grant shape are each
    enforced before the record may be decided.

    PRD section 3.8: "The acting assessor must hold no team assignment of any
    status on the cycle under decision, or the ballot is rejected with
    `ERR_PANEL_INDEPENDENCE_BREACH` — having been proposed and then recused
    does not restore independence. And the acting assessor must not already
    appear as the `voter_assessor_id` of an element of `votes`, or the ballot is
    rejected with `ERR_DUPLICATE_PANEL_VOTE`." and "the record must have at
    least three ballots — the panel quorum — or the request is rejected with
    `ERR_PANEL_QUORUM_NOT_MET`." and "For a `GRANT` or `GRANT_WITH_CONDITIONS`
    outcome, every element of `granted_scope_lines` must appear in the cycle's
    `requested_scope_lines`, or the request is rejected with
    `ERR_SCOPE_LINE_NOT_REQUESTED`; the supplied order is preserved. And the
    shape of the grant must match its label: a `GRANT_WITH_CONDITIONS` outcome
    must carry a `granted_scope_lines` list strictly shorter than
    `requested_scope_lines`, while a `GRANT` outcome must carry the full
    requested list — either mismatch is `ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE`."

    Design: Corner/errors/decision_panel_ballot_and_scope_rules_rejected
    """
    ctx = fx.scenario_in_assessment(
        client, "ISO17025-PAN", requested_scope_lines=THREE_SCOPE_LINES
    )
    fx.with_panel_members(ctx, 3)
    fx.set_clock(client, fx.CLOCK_ASSESSMENT_INSTANT)
    fx.with_closed_assessment(ctx)
    fx.with_voting_decision(ctx)
    decision_id = ctx["decision_id"]
    panel = ctx["panel"]
    rationale = "Witnessing records support the full requested scope."

    response = client.cast_vote(
        decision_id,
        f.vote_payload(VOTE_GRANT, rationale),
        make_decision_panel_member_headers(ctx["lead_id"]),
    )

    validate_error(response, ERR_PANEL_INDEPENDENCE_BREACH, 422)
    record = validate_success(client.get_decision(decision_id, ASSESSMENT_MANAGER), 200)
    assert record["vote_count"] == 0
    fx.cast_ballot(client, decision_id, panel[0]["panel_headers"])
    record = fx.cast_ballot(client, decision_id, panel[1]["panel_headers"])
    assert record["vote_count"] == 2
    short_of_quorum = client.finalize_decision(
        decision_id, f.finalize_payload(THREE_SCOPE_LINES), panel[1]["panel_headers"]
    )
    validate_error(short_of_quorum, ERR_PANEL_QUORUM_NOT_MET, 422)
    record = validate_success(client.get_decision(decision_id, ASSESSMENT_MANAGER), 200)
    assert record["status"] == DECISION_VOTING
    assert record["outcome"] is None
    assert record["vote_count"] < PANEL_QUORUM
    duplicate = client.cast_vote(
        decision_id, f.vote_payload(VOTE_GRANT, rationale), panel[0]["panel_headers"]
    )
    validate_error(duplicate, ERR_DUPLICATE_PANEL_VOTE, 409)
    record = validate_success(client.get_decision(decision_id, ASSESSMENT_MANAGER), 200)
    assert record["vote_count"] == 2
    record = fx.cast_ballot(client, decision_id, panel[2]["panel_headers"])
    assert record["vote_count"] == PANEL_QUORUM
    assert [ballot["vote"] for ballot in record["votes"]] == [VOTE_GRANT] * 3
    unrequested = client.finalize_decision(
        decision_id,
        f.finalize_payload([THREE_SCOPE_LINES[0], UNREQUESTED_LINE]),
        panel[2]["panel_headers"],
    )
    validate_error(unrequested, ERR_SCOPE_LINE_NOT_REQUESTED, 422)
    reduced = client.finalize_decision(
        decision_id,
        f.finalize_payload(THREE_SCOPE_LINES[:2]),
        panel[2]["panel_headers"],
    )
    validate_error(reduced, ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE, 422)

    decided = validate_success(
        client.finalize_decision(
            decision_id, f.finalize_payload(THREE_SCOPE_LINES), panel[2]["panel_headers"]
        ),
        200,
    )
    assert decided["status"] == DECISION_DECIDED
    assert decided["outcome"] == VOTE_GRANT
    assert decided["decided_on"] == fx.CLOCK_ASSESSMENT_DATE
    assert decided["decided_by_user_id"] == panel[2]["assessor"]["id"]
    assert fx.read_application(client, ctx["app_id"])["status"] == APP_GRANTED
    scope = fx.read_only_scope(client, ctx["org_id"])
    assert scope["status"] == SCOPE_ACTIVE
    assert scope["scope_lines"] == THREE_SCOPE_LINES
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["status"] == ORG_ACCREDITED
    assert organization["active_scope_count"] == 1


def test_risk_at_decision_and_at_surveillance_planning_diverge_on_one_scope(client):
    """The score frozen at grant tightens the cadence to 273 days; the
    halved carry-forward at surveillance planning relaxes it back to 365.

    PRD section 3.9: "A risk score of 10 or less is the low band and leaves the
    programme's nominal `surveillance_interval_days` intact at a factor of
    1.00. A risk score above 10 but not above 30 is the medium band and applies
    a factor of 0.75. A risk score above 30 is the high band and applies a
    factor of 0.50 — the body returns twice as often.
    `surveillance_interval_days_effective` is the programme's
    `surveillance_interval_days` multiplied by the band factor and rounded
    **down** to a whole number of days, and `next_surveillance_due` is that
    many days after `effective_from`. `next_reassessment_due`, by contrast, is
    simply the programme's `reassessment_interval_days` after `effective_from`,
    with no risk adjustment at any band." and section 3.7: "The
    **at-surveillance-planning** variant is used when a follow-on cycle is
    opened against a scope. It takes half of the granting cycle's raw score —
    the halving left unrounded — adds the raw score of the surveillance cycle's
    own findings, adds 3 points for each entry in the organization's
    `mra_escalation_count`, rounds the resulting sum **up** to a whole number,
    and then takes the smaller of 100 and that figure."

    Design: Difficulty/dual_variant_calc/organization_risk_at_decision_vs_at_surveillance_planning_diverge
    """
    ctx = fx.scenario_in_assessment(
        client, "ISO17025-DUA", requested_scope_lines=THREE_SCOPE_LINES
    )
    fx.with_panel_members(ctx, 3)
    fx.set_clock(client, fx.CLOCK_ASSESSMENT_INSTANT)
    critical = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_CRITICAL,
        "7.2.1",
        "Uncertainty budget omits the reference standard drift term.",
    )
    major = fx.raise_finding(
        client,
        ctx["app_id"],
        ctx["lead_headers"],
        NC_MAJOR,
        "6.2.5",
        "Two technicians hold no recorded competence authorization.",
    )
    assert critical["due_on"] == "2026-10-15"
    assert major["due_on"] == "2026-11-14"
    fx.with_closed_assessment(ctx)
    fx.submit_response(client, critical["id"], ctx["applicant_headers"])
    fx.review_response(client, critical["id"], ctx["lead_headers"])
    on_time = fx.verify_effectiveness(
        client,
        critical["id"],
        ctx["tech_headers"],
        EFFECTIVENESS_PASS,
        EVIDENCE_FLOOR_CRITICAL,
    )
    assert on_time["closed_on"] == fx.CLOCK_ASSESSMENT_DATE
    fx.submit_response(client, major["id"], ctx["applicant_headers"])
    fx.review_response(client, major["id"], ctx["lead_headers"])
    fx.set_clock(client, "2026-11-20T09:00:00Z")
    late = fx.verify_effectiveness(
        client, major["id"], ctx["tech_headers"], EFFECTIVENESS_PASS, EVIDENCE_FLOOR_MAJOR
    )
    assert late["closed_on"] == "2026-11-20"
    assert late["closed_on"] > late["due_on"], "The major finding closed late"
    application = fx.read_application(client, ctx["app_id"])
    assert_finding_ledger(application, total=2, blocking=0, closed=2, observation=0)
    fx.with_voting_decision(ctx)
    fx.with_unanimous_grant(ctx, THREE_SCOPE_LINES)
    at_grant = ctx["scope"]
    at_decision_score = RISK_WEIGHT_CRITICAL + RISK_WEIGHT_MAJOR + RISK_WEIGHT_CLOSED_LATE
    assert at_decision_score == 12
    assert at_grant["risk_score_at_grant"] == at_decision_score
    assert at_grant["effective_from"] == "2026-11-20"
    assert at_grant["surveillance_interval_days_effective"] == 273, (
        "The medium band floors 365 * 0.75"
    )
    assert at_grant["next_surveillance_due"] == add_days("2026-11-20", 273)
    assert at_grant["surveillance_risk_score"] is None

    response = client.open_surveillance_application(
        at_grant["id"],
        f.surveillance_application_payload(CYCLE_SURVEILLANCE),
        ASSESSMENT_MANAGER,
    )

    validate_success(response, 201)
    scope = validate_success(client.get_scope(at_grant["id"], SCHEME_MANAGER), 200)
    assert scope["risk_score_at_grant"] == 12
    assert scope["surveillance_risk_score"] == 6, "Half of 12, rounded up once"
    assert scope["risk_score_at_grant"] != scope["surveillance_risk_score"]
    assert scope["surveillance_interval_days_effective"] == 365, (
        "6 is inside the low band, so the nominal cadence is intact"
    )
    assert scope["next_surveillance_due"] == "2027-11-20"
    assert scope["next_reassessment_due"] == "2030-11-19"
    assert scope["next_reassessment_due"] == add_days("2026-11-20", 1460), (
        "The reassessment cadence is never risk-adjusted"
    )
    assert scope["effective_from"] == "2026-11-20"
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["risk_score"] == 6
