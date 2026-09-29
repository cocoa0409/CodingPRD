"""Declared error codes that no other instance reaches, each in its own right.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_empty_collection,
    assert_error,
    assert_is_none,
    assert_score,
)
from test_helpers.constants import (
    AnalysisStatus,
    AppliedTo,
    BenefitCategory,
    CapDecisionOutcome,
    CapStatus,
    CompliancePosture,
    CooperationStatus,
    EscalationStatus,
    FulfillmentStatus,
    NqtlItemStatus,
    NqtlType,
    PlanYearStatus,
    RemedyType,
    SubClassification,
    SubmissionType,
)
from test_helpers.test_users import (
    OFFICER_USER_ID_ALT,
    make_blank_user_id_headers,
    make_missing_role_headers,
    make_unknown_role_headers,
)

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


# ═══ errors / blank_or_unknown_identity_headers_rejected ═════════════════════════


def test_identity_is_checked_before_routing_and_an_empty_string_counts_as_absent(
    api, sponsor_headers
):
    """Three ways to fail identity, all 401, none of them a 422 and none of them a 403.

    An `X-User-ID` sent as a genuinely empty string is treated as missing, and so is
    an omitted `X-User-Role`; both answer with the missing-headers code.  A role that
    is syntactically fine but is not one of the four declared roles is a different
    code again, and it is the same code on a read-only endpoint as on a write, because
    the guard precedes routing entirely.  Nothing is created along the way.

    PRD: "If either header is absent, or is present but sent as an empty string, the
    request is rejected with `ERR_MISSING_IDENTITY_HEADERS` (HTTP 401); an
    empty-string header is treated exactly as an absent one. If `X-User-Role` carries
    a value that is not one of the four recognised roles, the request is rejected with
    `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/errors/blank_or_unknown_identity_headers_rejected
    """
    payload = f.administrator_payload()

    assert_error(
        api.create_administrator(payload, make_blank_user_id_headers()),
        ApiErrorId.MISSING_IDENTITY_HEADERS,
        401,
    )
    assert_error(
        api.create_administrator(payload, make_missing_role_headers()),
        ApiErrorId.MISSING_IDENTITY_HEADERS,
        401,
    )
    assert_error(
        api.create_administrator(payload, make_unknown_role_headers()),
        ApiErrorId.UNKNOWN_ROLE,
        401,
    )
    assert_error(
        api.list_plan_years(None, make_unknown_role_headers()),
        ApiErrorId.UNKNOWN_ROLE,
        401,
    )

    assert_empty_collection(api.list_plan_years(None, sponsor_headers))


# ═══ errors / reviewing_an_analysis_that_never_reached_submitted_rejected ═════════


def test_each_analysis_action_reports_the_state_it_wanted_and_did_not_find(
    api, officer_alt_headers
):
    """Review and reopen each name the state they wanted, and they do not name the same one.

    A DRAFT analysis authored by the TPA on the sponsor's behalf is not reviewable —
    review wants SUBMITTED — and it is not reopenable either, because reopen wants
    INSUFFICIENT.  Neither refusal touches the row: it is still DRAFT at revision
    round 0 with no certifier, still credited to the administrator who wrote it, and
    the item stands at ANALYSIS_DRAFTED where its creation put it.

    PRD: "**Review** is exclusive to a `ComplianceOfficer`, applies only to an
    analysis in `SUBMITTED` — anything else is refused with
    `ERR_ANALYSIS_NOT_SUBMITTED` (HTTP 409)."

    Design: Corner/errors/reviewing_an_analysis_that_never_reached_submitted_rejected
    """
    scenario = fx.classified_plan(api, benefit_category=BenefitCategory.INPATIENT)
    assert scenario.classification["sub_classification"] == SubClassification.NONE

    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        nqtl_type=NqtlType.CONCURRENT_REVIEW,
        applied_to=AppliedTo.BOTH,
        description="Concurrent review for inpatient admissions.",
    )
    analysis = fx.draft_analysis(
        api,
        item["id"],
        item["version"],
        scenario.admin_headers,
        factor_count=2,
        evidentiary_standard_count=1,
    )

    assert_error(
        api.review_analysis(
            analysis["id"],
            f.review_payload(review_note="Reviewing a draft that was never submitted."),
            officer_alt_headers,
        ),
        ApiErrorId.ANALYSIS_NOT_SUBMITTED,
        409,
    )
    assert_error(
        api.reopen_analysis(analysis["id"], {}, scenario.admin_headers),
        ApiErrorId.ANALYSIS_NOT_INSUFFICIENT,
        409,
    )

    unchanged = fx.read_analysis(api, analysis["id"])
    assert unchanged["status"] == AnalysisStatus.DRAFT
    assert unchanged["revision_round"] == 0
    assert_is_none(unchanged["certified_by_user_id"], "certified_by_user_id")
    assert unchanged["authored_by_user_id"] == scenario.admin_id
    assert fx.read_item(api, item["id"])["status"] == NqtlItemStatus.ANALYSIS_DRAFTED


# ═══ errors / deciding_twice_on_the_same_corrective_plan_rejected ═════════════════


def test_a_second_decision_is_refused_and_the_liability_is_not_booked_twice(
    api, officer_headers, officer_alt_headers
):
    """The decision endpoint is a one-shot on DRAFT, and the ledger proves it.

    An approved process-change plan has already put its 275,000 cents onto the plan
    year.  Trying to reverse that with a rejection is refused because the plan is no
    longer a draft, and the plan keeps both its APPROVED status and the officer who
    approved it.  The ledger still reads 275,000 rather than 550,000, and the item and
    plan year stay exactly where the violation left them.

    PRD: "**Deciding a plan** is exclusive to a `ComplianceOfficer`, takes an
    `outcome` of either `APPROVED` or `REJECTED` plus an optional `decision_note`, and
    requires the plan to be in `DRAFT` — anything else is refused with
    `ERR_CAP_NOT_DRAFT` (HTTP 409)."

    Design: Corner/errors/deciding_twice_on_the_same_corrective_plan_rejected
    """
    scenario = fx.item_in_violation(api, **OUTPATIENT_SLICE)
    cap = fx.draft_cap(
        api,
        scenario.item_id,
        officer_headers,
        remedy_type=RemedyType.PROCESS_CHANGE,
        affected_claims_count=880,
        average_claim_cents=3125,
    )
    approved = fx.decide_cap(
        api,
        cap["id"],
        CapDecisionOutcome.APPROVED,
        officer_alt_headers,
        decision_note="Process change approved by an independent officer.",
    )
    assert approved["status"] == CapStatus.APPROVED
    assert_cents(
        approved["reprocessing_liability_cents"], 275000, "reprocessing_liability_cents"
    )

    assert_error(
        api.decide_corrective_action_plan(
            cap["id"],
            f.cap_decision_payload(
                CapDecisionOutcome.REJECTED,
                decision_note="Trying to reverse an approval through a second decision.",
            ),
            officer_alt_headers,
        ),
        ApiErrorId.CAP_NOT_DRAFT,
        409,
    )

    still_approved = fx.read_cap(api, cap["id"], officer_headers)
    assert still_approved["status"] == CapStatus.APPROVED
    assert still_approved["approved_by_user_id"] == OFFICER_USER_ID_ALT

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_cents(plan_year["remediation_liability_cents"], 275000, "remediation_liability_cents")
    assert plan_year["open_violation_count"] == 1
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION
    assert plan_year["status"] == PlanYearStatus.REMEDIATION
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.VIOLATION


# ═══ errors / breach_declared_request_blocks_production_and_further_escalation_rejected ══


def test_a_declared_breach_shuts_both_the_escalation_ladder_and_the_production_window(
    api, officer_headers
):
    """BREACH_DECLARED is terminal on one axis and closes the other axis entirely.

    Two rungs of escalation take the request from NONE through NOTICE_SENT to
    BREACH_DECLARED at a clock standing more than a week past the contractual
    deadline.  A third escalation has nowhere to go, and the material the TPA finally
    tries to produce is refused because the window is shut — so the request is still
    unfulfilled with nothing validated against it.  The TPA carries one breach and one
    late request, which costs it forty points, and the plan year is dragged to AT_RISK
    through its vendor alone.

    PRD: "From that point the production window is shut: any further data submission
    against that request is refused with `ERR_PRODUCTION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/errors/breach_declared_request_blocks_production_and_further_escalation_rejected
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )
    fx.advance_clock(api, "2026-09-23T00:00:00Z")

    noticed = fx.escalate(api, request["id"], scenario.sponsor_headers)
    assert noticed["escalation_status"] == EscalationStatus.NOTICE_SENT
    breached = fx.escalate(api, request["id"], scenario.sponsor_headers)
    assert breached["escalation_status"] == EscalationStatus.BREACH_DECLARED

    assert_error(
        api.escalate_vendor_request(request["id"], {}, scenario.sponsor_headers),
        ApiErrorId.ESCALATION_ALREADY_DECLARED,
        409,
    )
    assert_error(
        api.create_data_submission(
            request["id"],
            f.denial_rate_submission_payload(scenario.classification_id),
            scenario.admin_headers,
        ),
        ApiErrorId.PRODUCTION_WINDOW_CLOSED,
        409,
    )

    unfulfilled = fx.read_vendor_request(api, request["id"])
    assert unfulfilled["fulfillment_status"] == FulfillmentStatus.OPEN
    assert unfulfilled["validated_submission_count"] == 0

    administrator = fx.read_administrator(api, scenario.admin_id, officer_headers)
    assert administrator["breach_count"] == 1
    assert administrator["late_request_count"] == 1
    assert_score(administrator["cooperation_score"], 60.00, "cooperation_score")
    assert administrator["cooperation_status"] == CooperationStatus.DELINQUENT

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK
    assert plan_year["status"] == PlanYearStatus.OPEN
