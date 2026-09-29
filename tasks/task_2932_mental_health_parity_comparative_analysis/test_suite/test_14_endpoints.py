"""The declared endpoint surface: filters, windows, action bodies and reads.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_collection,
    assert_empty_collection,
    assert_error,
    assert_fields,
    assert_index,
    assert_is_none,
    assert_ratio,
)
from test_helpers.constants import (
    MISSING_UUID,
    AnalysisStatus,
    AppliedTo,
    BenefitCategory,
    BenefitSide,
    CapStatus,
    CompliancePosture,
    DeterminationOutcome,
    EscalationStatus,
    FulfillmentStatus,
    LimitationStatus,
    LimitationType,
    NetworkTier,
    NqtlItemStatus,
    NqtlType,
    ParityResult,
    ParityTestStatus,
    PlanYearStatus,
    RegulatorRequestStatus,
    RejectionReason,
    RemedyType,
    ReviewOutcome,
    StringencyFinding,
    SubClassification,
    SubmissionStatus,
    SubmissionType,
    TestBasis,
)
from test_helpers.test_users import (
    OFFICER_USER_ID,
    SPONSOR_USER_ID,
    make_administrator_headers,
)

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


# ═══ endpoints / list_endpoints_combine_filters_with_limit_and_offset ════════════


def test_filters_and_the_page_window_act_on_the_same_filtered_population(
    api, officer_headers, regulator_headers
):
    """`total_count` counts the filtered rows, and the window is validated, not clamped.

    Three plan years share one TPA.  A two-row window over them reports the filtered
    population of three and says more remains; the next window returns the last row
    and says it does not.  A status filter matching nothing reports an honest zero,
    and a `benefit_side` filter on the limitation collection picks out one row of the
    two.  Omitting `limit` gives the declared default of ten, and a `limit` of zero is
    a shape failure rather than a silent correction to one.

    PRD: "List responses populate four fields in the envelope's `meta` object:
    `limit` and `offset` echo the effective values used for the page, `total_count`
    reports how many rows match the filters before the page window is applied, and
    `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/list_endpoints_combine_filters_with_limit_and_offset
    """
    admin = fx.register_administrator(api)
    for label, participants in (("2024", 1100), ("2025", 1150), ("2026", 1200)):
        plan_year = fx.open_plan_year(
            api, admin["id"], plan_year_label=label, covered_participant_count=participants
        )
    classification = fx.create_classification(api, plan_year["id"], **OUTPATIENT_SLICE)
    tpa_headers = make_administrator_headers(admin["id"])
    fx.add_limitation(api, classification["id"], f.ms_limitation(20, 2000000, 400), tpa_headers)
    mh_row = fx.add_limitation(
        api, classification["id"], f.mh_limitation(20, 700000, 90), tpa_headers
    )

    first_page, meta = assert_collection(
        api.list_plan_years(
            {"administrator_id": admin["id"], "limit": 2, "offset": 0}, regulator_headers
        ),
        3,
        2,
        True,
    )
    assert (meta["limit"], meta["offset"]) == (2, 0)
    second_page, meta = assert_collection(
        api.list_plan_years(
            {"administrator_id": admin["id"], "limit": 2, "offset": 2}, regulator_headers
        ),
        3,
        1,
        False,
    )
    assert meta["offset"] == 2
    assert {row["id"] for row in first_page}.isdisjoint({row["id"] for row in second_page})

    assert_empty_collection(
        api.list_plan_years(
            {"administrator_id": admin["id"], "status": PlanYearStatus.CLOSED}, regulator_headers
        )
    )

    mh_rows, _ = assert_collection(
        api.list_treatment_limitations(
            classification["id"],
            {"benefit_side": BenefitSide.MENTAL_HEALTH_SUD, "status": LimitationStatus.ACTIVE},
            officer_headers,
        ),
        1,
        1,
        False,
    )
    assert mh_rows[0]["id"] == mh_row["id"]

    assert_error(
        api.list_plan_years({"administrator_id": admin["id"], "limit": 0}, regulator_headers),
        ApiErrorId.VALIDATION,
        422,
    )

    default_window = api.list_plan_years({"administrator_id": admin["id"]}, regulator_headers)
    _, meta = assert_collection(default_window, 3, 3, False)
    assert (meta["limit"], meta["offset"]) == (10, 0)
    assert default_window.json()["response_type"] == "array"


# ═══ endpoints / compliant_determination_returns_the_updated_item_and_issues_no_notice ══


def test_the_compliant_branch_answers_with_the_item_and_mints_no_disclosure(
    api, officer_headers, officer_alt_headers
):
    """The determination endpoint returns the mutated item, and compliance is quiet.

    A denial-rate disparity of 1.9235 on a both-sides prior-authorisation item, less
    a two-factor one-standard documentation credit, indexes at 4.24 — below the
    threshold, so compliance is exactly what the evidence supports.  The response
    body is the NQTL item itself, stamped with the deciding officer.  No participant
    notice exists, because there is nothing to disclose, and the plan year reaches
    COMPLIANT without ever passing through REMEDIATION.

    PRD: "A `COMPLIANT` outcome requires the recomputed index to be strictly below
    5.0; a `VIOLATION` outcome requires it to be at or above 5.0."

    Design: Corner/endpoints/compliant_determination_returns_the_updated_item_and_issues_no_notice
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization applied to both benefit sides for outpatient office visits.",
    )
    fx.with_denial_rate_evidence(
        api,
        scenario,
        mh_denials=137,
        mh_adjudicated_claims=1919,
        ms_denials=71,
        ms_adjudicated_claims=1913,
        nqtl_item_id=item["id"],
    )
    analysis = fx.draft_analysis(
        api,
        item["id"],
        None,
        scenario.sponsor_headers,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    fx.submit_analysis(api, analysis["id"], scenario.sponsor_headers)
    fx.review_analysis(
        api,
        analysis["id"],
        ReviewOutcome.CERTIFIED,
        officer_alt_headers,
        review_note=(
            "Factors and evidentiary standards are comparable and the as-applied data supports it."
        ),
    )
    before_version = fx.plan_year_version(api, scenario.plan_year_id, officer_headers)

    determined = validate_success(
        api.create_determination(
            item["id"],
            f.determination_payload(
                DeterminationOutcome.COMPLIANT,
                before_version,
                rationale=(
                    "Prior authorization is applied comparably and the denial-rate disparity is "
                    "below the threshold."
                ),
            ),
            officer_headers,
        ),
        201,
    )
    assert determined["id"] == item["id"]
    assert determined["status"] == NqtlItemStatus.COMPLIANT
    assert determined["determination_recorded_by_user_id"] == OFFICER_USER_ID
    assert_index(determined["stringency_in_operation_index"], 4.24, "stringency_in_operation_index")
    assert determined["stringency_flag"] is False

    assert_empty_collection(api.list_participant_notices(item["id"], None, officer_headers))

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_fields(
        plan_year,
        open_violation_count=0,
        notified_violation_count=0,
        failing_parity_test_count=0,
        compliance_posture=CompliancePosture.COMPLIANT,
        status=PlanYearStatus.OPEN,
    )
    assert plan_year["version"] > before_version


# ═══ endpoints / vendor_request_naming_an_item_from_another_plan_year_rejected ═══


def test_the_body_links_are_checked_in_declaration_order_administrator_first(
    api, sponsor_headers, officer_headers
):
    """An unknown TPA is a 404 and a mismatched item a 409, and the TPA answers first.

    The offending payload gets both links wrong at once, and the missing
    administrator — declared first in the body — is the one reported.  Naming the
    real TPA leaves only the item, inventoried under the 2025 plan year, pointed at
    from a 2026 request, which is a coherence failure.  Scoped to its own plan year
    the very same item is a legal link, so the 2026 plan year ends with no requests
    at all and the TPA carries exactly one outstanding obligation.

    PRD: "When `nqtl_item_id` is supplied, the item it names must belong to the
    request's `plan_year_id`; a mismatch is rejected with
    `ERR_CROSS_PLAN_YEAR_REFERENCE`."

    Design: Corner/endpoints/vendor_request_naming_an_item_from_another_plan_year_rejected
    """
    admin = fx.register_administrator(api)
    plan_year_a = fx.open_plan_year(
        api, admin["id"], plan_year_label="2025", covered_participant_count=1150
    )
    plan_year_b = fx.open_plan_year(
        api, admin["id"], plan_year_label="2026", covered_participant_count=1200
    )
    classification_a = fx.create_classification(
        api,
        plan_year_a["id"],
        measurement_period_start="2025-01-01",
        measurement_period_end="2025-06-30",
        **OUTPATIENT_SLICE,
    )
    item_a = fx.inventory_item(
        api,
        plan_year_a["id"],
        classification_a["id"],
        headers=officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization inventoried on the 2025 plan year.",
    )

    assert_error(
        api.create_vendor_request(
            f.vendor_request_payload(
                MISSING_UUID,
                plan_year_b["id"],
                requested_item_count=1,
                requested_submission_types=[SubmissionType.DENIAL_RATES],
                nqtl_item_id=item_a["id"],
            ),
            sponsor_headers,
        ),
        ApiErrorId.ADMINISTRATOR_NOT_FOUND,
        404,
    )
    assert_error(
        api.create_vendor_request(
            f.vendor_request_payload(
                admin["id"],
                plan_year_b["id"],
                requested_item_count=1,
                requested_submission_types=[SubmissionType.DENIAL_RATES],
                nqtl_item_id=item_a["id"],
            ),
            sponsor_headers,
        ),
        ApiErrorId.CROSS_PLAN_YEAR_REFERENCE,
        409,
    )

    accepted = validate_success(
        api.create_vendor_request(
            f.vendor_request_payload(
                admin["id"],
                plan_year_a["id"],
                requested_item_count=1,
                requested_submission_types=[SubmissionType.DENIAL_RATES],
                nqtl_item_id=item_a["id"],
            ),
            sponsor_headers,
        ),
        201,
    )
    assert accepted["nqtl_item_id"] == item_a["id"]
    assert accepted["plan_year_id"] == plan_year_a["id"]

    assert_empty_collection(
        api.list_vendor_requests({"plan_year_id": plan_year_b["id"]}, officer_headers)
    )
    assert fx.read_administrator(api, admin["id"], officer_headers)["outstanding_request_count"] == 1


# ═══ endpoints / every_declared_read_endpoint_returns_its_row_or_collection ══════


def _fully_populated_plan_year(api, officer_headers, regulator_headers):
    """One plan year carrying a row of every kind, each with non-trivial derived fields.

    A three-row copay population feeding a passing plan-payments test; an MH/SUD-only
    prior-authorisation item with a threefold denial disparity behind it, a submitted
    analysis and a violation determination; a drafted process-change remedy; and an
    open regulator docket.  The regulator request is opened before the determination
    so that the plan year's move into REMEDIATION is the documented
    `UNDER_REGULATOR_REVIEW` leg rather than an undeclared one.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    fx.add_limitations(
        api,
        scenario.classification_id,
        [
            f.ms_limitation(20, 2000000, 400),
            f.ms_limitation(0, 1000000, 200),
            f.mh_limitation(20, 500000, 100),
        ],
    )
    scenario.parity_test = fx.run_parity_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Prior authorization imposed on MH/SUD outpatient visits only.",
    )
    scenario.item_id = item["id"]
    fx.with_denial_rate_evidence(api, scenario, nqtl_item_id=item["id"])
    analysis = fx.draft_analysis(
        api,
        item["id"],
        None,
        scenario.sponsor_headers,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )
    scenario.analysis_id = analysis["id"]
    fx.submit_analysis(api, analysis["id"], scenario.sponsor_headers)
    request = fx.open_regulator_request(
        api,
        scenario.plan_year_id,
        regulator_headers,
        requested_nqtl_types=[NqtlType.PRIOR_AUTHORIZATION],
        request_reference="DOL-EBSA-2026-0417",
    )
    scenario.regulator_request_id = request["id"]
    fx.record_determination(
        api,
        item["id"],
        scenario.plan_year_id,
        DeterminationOutcome.VIOLATION,
        headers=officer_headers,
        rationale=(
            "Prior authorization applied to MH/SUD benefits only, with a threefold denial-rate "
            "disparity."
        ),
    )
    cap = fx.draft_cap(
        api,
        item["id"],
        officer_headers,
        remedy_type=RemedyType.PROCESS_CHANGE,
        affected_claims_count=880,
        average_claim_cents=3125,
        target_completion_date="2026-12-31",
    )
    scenario.cap_id = cap["id"]
    return scenario


def test_every_remaining_declared_read_returns_its_row_or_its_filtered_collection(
    api, officer_headers, regulator_headers
):
    """The whole read surface, exercised by a regulator against non-trivial rows.

    Each collection honours its declared filters and reports the filtered population
    with the requested window echoed back; each single-row read returns the resource
    directly, carrying the derived figures the write path put there — a
    substantially-all ratio of exactly two thirds, a disparity of 3.0000 over rates
    of 0.300000 and 0.100000, and a process-change liability of 275,000 cents booked
    against nothing yet because the plan is still a draft.

    PRD: "Requests may be read individually, showing the completeness score and the
    current deadline, and listed with optional `plan_year_id` and `status` filters."

    Design: Corner/endpoints/every_declared_read_endpoint_returns_its_row_or_collection
    """
    scenario = _fully_populated_plan_year(api, officer_headers, regulator_headers)

    classifications, _ = assert_collection(
        api.list_plan_year_classifications(
            scenario.plan_year_id,
            {
                "benefit_category": BenefitCategory.OUTPATIENT,
                "network_tier": NetworkTier.IN_NETWORK,
                "limit": 10,
                "offset": 0,
            },
            regulator_headers,
        ),
        1,
        1,
        False,
    )
    assert classifications[0]["id"] == scenario.classification_id

    classification = validate_success(
        api.get_classification(scenario.classification_id, regulator_headers)
    )
    assert_fields(
        classification,
        sub_classification=SubClassification.OFFICE_VISITS,
        measurement_period_start="2026-01-01",
        mh_su_benefits_covered=True,
    )

    tests, _ = assert_collection(
        api.list_parity_tests(
            scenario.classification_id,
            {
                "limitation_type": LimitationType.COPAY,
                "basis": TestBasis.PLAN_PAYMENTS,
                "status": ParityTestStatus.COMPUTED,
                "limit": 10,
                "offset": 0,
            },
            regulator_headers,
        ),
        1,
        1,
        False,
    )
    assert_ratio(tests[0]["substantially_all_ratio"], 0.666667, 6, "substantially_all_ratio")
    assert_fields(
        tests[0],
        substantially_all_met=True,
        predominant_level=20,
        mh_level_value=20,
        result=ParityResult.PASS,
        advisory_only=False,
    )

    analysis = validate_success(api.get_analysis(scenario.analysis_id, regulator_headers))
    assert_fields(
        analysis,
        factor_count=2,
        evidentiary_standard_count=1,
        revision_round=0,
        authored_by_user_id=SPONSOR_USER_ID,
        status=AnalysisStatus.SUBMITTED,
    )
    assert_is_none(analysis["certified_by_user_id"], "certified_by_user_id")

    analyses, _ = assert_collection(
        api.list_analyses(
            {"nqtl_item_id": scenario.item_id, "limit": 10, "offset": 0}, regulator_headers
        ),
        1,
        1,
        False,
    )
    assert analyses[0]["id"] == scenario.analysis_id

    vendor_request = validate_success(
        api.get_vendor_request(scenario.vendor_request_id, regulator_headers)
    )
    assert_fields(
        vendor_request,
        validated_submission_count=1,
        fulfillment_status=FulfillmentStatus.FULFILLED,
        escalation_status=EscalationStatus.NONE,
        is_overdue=False,
    )
    assert vendor_request["due_at"] and vendor_request["regulatory_due_at"]

    vendor_requests, _ = assert_collection(
        api.list_vendor_requests(
            {
                "administrator_id": scenario.admin_id,
                "plan_year_id": scenario.plan_year_id,
                "fulfillment_status": FulfillmentStatus.FULFILLED,
                "limit": 10,
                "offset": 0,
            },
            regulator_headers,
        ),
        1,
        1,
        False,
    )
    assert vendor_requests[0]["id"] == scenario.vendor_request_id

    submissions, _ = assert_collection(
        api.list_data_submissions(
            {
                "vendor_request_id": scenario.vendor_request_id,
                "classification_id": scenario.classification_id,
                "submission_type": SubmissionType.DENIAL_RATES,
                "status": SubmissionStatus.VALIDATED,
                "limit": 10,
                "offset": 0,
            },
            regulator_headers,
        ),
        1,
        1,
        False,
    )
    assert_ratio(submissions[0]["disparity_ratio"], 3.0000, 4, "disparity_ratio")
    assert_ratio(submissions[0]["mh_denial_rate"], 0.300000, 6, "mh_denial_rate")
    assert_ratio(submissions[0]["ms_denial_rate"], 0.100000, 6, "ms_denial_rate")
    assert_fields(
        submissions[0], as_applied_flag=True, rejection_reason=RejectionReason.NONE
    )

    cap = validate_success(api.get_corrective_action_plan(scenario.cap_id, regulator_headers))
    assert cap["status"] == CapStatus.DRAFT
    assert cap["nqtl_item_id"] == scenario.item_id
    assert_is_none(cap["approved_by_user_id"], "approved_by_user_id")
    assert_cents(cap["reprocessing_liability_cents"], 275000, "reprocessing_liability_cents")

    caps, _ = assert_collection(
        api.list_corrective_action_plans(
            {
                "nqtl_item_id": scenario.item_id,
                "status": CapStatus.DRAFT,
                "remedy_type": RemedyType.PROCESS_CHANGE,
                "limit": 10,
                "offset": 0,
            },
            regulator_headers,
        ),
        1,
        1,
        False,
    )
    assert_cents(
        caps[0]["reprocessing_liability_cents"], 275000, "listed reprocessing_liability_cents"
    )

    regulator_request = validate_success(
        api.get_regulator_request(scenario.regulator_request_id, regulator_headers)
    )
    assert_fields(
        regulator_request,
        status=RegulatorRequestStatus.OPEN,
        regulator_round=0,
        requested_nqtl_types=[NqtlType.PRIOR_AUTHORIZATION],
        request_reference="DOL-EBSA-2026-0417",
    )
    assert regulator_request["response_due_at"]

    regulator_requests, _ = assert_collection(
        api.list_regulator_requests(
            {
                "plan_year_id": scenario.plan_year_id,
                "status": RegulatorRequestStatus.OPEN,
                "limit": 10,
                "offset": 0,
            },
            regulator_headers,
        ),
        1,
        1,
        False,
    )
    assert regulator_requests[0]["id"] == scenario.regulator_request_id

    limitations, _ = assert_collection(
        api.list_treatment_limitations(scenario.classification_id, None, regulator_headers), 3, 3, False
    )
    assert all(row["status"] == LimitationStatus.ACTIVE for row in limitations)
