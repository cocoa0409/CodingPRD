"""Transitions whose gate lives on a second, differently owned entity.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_empty_collection,
    assert_error,
    assert_index,
    assert_is_none,
    assert_ratio,
)
from test_helpers.constants import (
    AnalysisStatus,
    AppliedTo,
    BenefitCategory,
    CapStatus,
    CompliancePosture,
    DeterminationOutcome,
    FulfillmentStatus,
    NetworkTier,
    NqtlItemStatus,
    NqtlType,
    PlanYearStatus,
    RejectionReason,
    RemedyType,
    ReviewOutcome,
    StringencyFinding,
    SubClassification,
    SubmissionStatus,
    SubmissionType,
)
from test_helpers.test_users import OFFICER_USER_ID_ALT


def _submitted_analysis_with_only_rejected_evidence(api):
    """A submitted analysis whose classification carries one REJECTED submission.

    The production request asks for two denial-rate sets against the item, and the
    first one arrives with no comparator denials at all, so it is persisted but
    rejected.  Nothing on the classification is therefore in `VALIDATED`.
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        nqtl_type=NqtlType.NETWORK_ADMISSION,
        applied_to=AppliedTo.BOTH,
        description="Provider network admission standards for outpatient office visits.",
    )
    scenario.item_id = item["id"]
    analysis = fx.draft_analysis(
        api,
        item["id"],
        item["version"],
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    fx.submit_analysis(api, analysis["id"])
    scenario.analysis_id = analysis["id"]

    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=2,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
        nqtl_item_id=item["id"],
    )
    scenario.vendor_request_id = request["id"]
    scenario.rejected_submission = fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(scenario.classification_id, ms_denials=0),
        scenario.admin_id,
    )
    return scenario


def test_certification_is_refused_while_the_classifications_only_evidence_was_rejected(
    api, officer_alt_headers
):
    """A persisted but rejected submission does not unlock certification.

    The analysis is complete on its own terms — factors recited, both stringency
    findings comparable, self-review satisfied by an independent officer — yet the
    gate sits on a data submission owned by a different resource, and the one that
    exists failed its own validation.

    PRD: "Absent such evidence the request is refused with
    `ERR_IN_OPERATION_DATA_MISSING` (HTTP 409), and a `REJECTED` submission does not
    satisfy the rule."

    Design: Difficulty/cross_entity_state_dependency/certification_requires_a_validated_denial_rates_submission_on_the_classification
    """
    scenario = _submitted_analysis_with_only_rejected_evidence(api)

    rejected = scenario.rejected_submission
    assert rejected["status"] == SubmissionStatus.REJECTED
    assert rejected["rejection_reason"] == RejectionReason.ZERO_COMPARATOR_DENIALS
    assert_is_none(rejected["disparity_ratio"], "disparity_ratio")
    assert rejected["as_applied_flag"] is False

    assert_error(
        api.review_analysis(
            scenario.analysis_id,
            f.review_payload(
                ReviewOutcome.CERTIFIED,
                review_note="Certifying on the strength of the written analysis alone.",
            ),
            officer_alt_headers,
        ),
        ApiErrorId.IN_OPERATION_DATA_MISSING,
    )

    assert fx.read_analysis(api, scenario.analysis_id)["status"] == AnalysisStatus.SUBMITTED
    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["validated_submission_count"] == 0
    assert request["fulfillment_status"] == FulfillmentStatus.OPEN


def test_the_same_review_certifies_once_a_validated_set_lands_on_the_classification(
    api, officer_alt_headers
):
    """The gate opens from the other entity, and the analysis is certified unchanged.

    A second production attempt with a positive comparator validates, publishing a
    disparity ratio of 1.9235.  The identical review call now succeeds, stamps the
    reviewing officer, leaves the owning item in ANALYSIS_SUBMITTED, and the fresh
    evidence has meanwhile lifted the item's index to 1.47 without raising its flag.

    PRD: "The certifying branch moves `SUBMITTED` to `CERTIFIED`, stamps
    `certified_by_user_id` from the acting `X-User-ID`, leaves the owning item's
    status untouched, and additionally requires as-applied evidence to exist: at
    least one data submission in status `VALIDATED` with `submission_type`
    `DENIAL_RATES` must exist for the owning item's `classification_id`, because an
    analysis may not be certified on paper alone."

    Design: Difficulty/cross_entity_state_dependency/certification_requires_a_validated_denial_rates_submission_on_the_classification
    """
    scenario = _submitted_analysis_with_only_rejected_evidence(api)
    api.review_analysis(
        scenario.analysis_id, f.review_payload(ReviewOutcome.CERTIFIED), officer_alt_headers
    )

    validated = fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(scenario.classification_id),
        scenario.admin_id,
    )
    assert validated["status"] == SubmissionStatus.VALIDATED
    assert_ratio(validated["disparity_ratio"], 1.9235, 4, "disparity_ratio")
    assert validated["as_applied_flag"] is False

    certified = validate_success(
        api.review_analysis(
            scenario.analysis_id,
            f.review_payload(
                ReviewOutcome.CERTIFIED,
                review_note="As-applied denial-rate evidence is now on the record.",
            ),
            officer_alt_headers,
        )
    )
    assert certified["status"] == AnalysisStatus.CERTIFIED
    assert certified["certified_by_user_id"] == OFFICER_USER_ID_ALT

    item = fx.read_item(api, scenario.item_id)
    assert item["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED
    assert_index(item["stringency_in_operation_index"], 1.47)
    assert item["stringency_flag"] is False


REMEDY = dict(
    remedy_type=RemedyType.PROCESS_CHANGE,
    affected_claims_count=880,
    average_claim_cents=3125,
    target_completion_date="2026-12-31",
)


def _inpatient_item_one_step_short_of_violation(api):
    """An inpatient prior-authorisation item in ANALYSIS_SUBMITTED with damning evidence.

    Its validated denial-rate evidence reports 300 MH/SUD denials in 1,000 claims
    against 100 in 1,000, and the analysis itself concedes that the limitation is
    more stringent for MH/SUD both as written and in operation — so nothing is
    missing except the determination.
    """
    scenario = fx.classified_plan(
        api, benefit_category=BenefitCategory.INPATIENT, network_tier=NetworkTier.IN_NETWORK
    )
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        description="Prior authorization required for all inpatient MH/SUD admissions.",
    )
    scenario.item_id = item["id"]
    fx.with_denial_rate_evidence(api, scenario, nqtl_item_id=item["id"])

    analysis = fx.draft_analysis(
        api,
        item["id"],
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )
    fx.submit_analysis(api, analysis["id"])
    scenario.analysis_id = analysis["id"]
    return scenario


def test_a_corrective_plan_cannot_be_drafted_for_an_item_not_yet_found_in_violation(api):
    """The remedy is refused on the state of the item it names, not on its own merits.

    Every field of the draft is acceptable and the evidence already published makes
    the eventual violation a formality, but the owning item still sits in
    ANALYSIS_SUBMITTED, and the refusal leaves no plan behind at all.

    PRD: "The owning item must actually be in `VIOLATION`; drafting a plan for an
    item in any other state is refused with `ERR_ITEM_NOT_IN_VIOLATION` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/corrective_action_plan_creation_requires_its_nqtl_item_in_violation
    """
    scenario = _inpatient_item_one_step_short_of_violation(api)

    assert_error(
        api.create_corrective_action_plan(
            f.cap_payload(scenario.item_id, **REMEDY), scenario.sponsor_headers
        ),
        ApiErrorId.ITEM_NOT_IN_VIOLATION,
    )

    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED
    assert_empty_collection(
        api.list_corrective_action_plans(
            {"nqtl_item_id": scenario.item_id}, scenario.sponsor_headers
        )
    )


def test_the_identical_draft_is_accepted_once_the_item_is_in_violation(api, officer_headers):
    """Recording the violation on the other entity is the whole difference.

    The same payload that was refused now creates a DRAFT plan whose exposure is
    frozen at 275,000 cents — 880 claims at 3,125 cents charged at the process-change
    rate of one tenth.  The plan year, already in REMEDIATION from the
    determination's cascade, has booked nothing.

    PRD: "Creating a plan does **not** touch the plan year's
    `remediation_liability_cents`; drafting an expensive remedy costs the plan year
    nothing until somebody approves it."

    Design: Difficulty/cross_entity_state_dependency/corrective_action_plan_creation_requires_its_nqtl_item_in_violation
    """
    scenario = _inpatient_item_one_step_short_of_violation(api)
    fx.record_determination(
        api,
        scenario.item_id,
        scenario.plan_year_id,
        DeterminationOutcome.VIOLATION,
        headers=officer_headers,
        rationale=(
            "Inpatient prior authorization applies to MH/SUD admissions only and denies at "
            "three times the medical/surgical rate."
        ),
    )

    cap = validate_success(
        api.create_corrective_action_plan(
            f.cap_payload(scenario.item_id, **REMEDY), scenario.sponsor_headers
        ),
        201,
    )
    assert cap["status"] == CapStatus.DRAFT
    assert_cents(cap["reprocessing_liability_cents"], 275000, "reprocessing_liability_cents")

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_cents(plan_year["remediation_liability_cents"], 0, "remediation_liability_cents")
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION
    assert plan_year["status"] == PlanYearStatus.REMEDIATION
