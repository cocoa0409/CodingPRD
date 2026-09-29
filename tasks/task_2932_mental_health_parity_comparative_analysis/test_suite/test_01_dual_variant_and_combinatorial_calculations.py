"""Dual-variant calculations and combinatorial formulas.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_index,
    assert_instant_equals,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    AppliedTo,
    CapDecisionOutcome,
    CapStatus,
    CompliancePosture,
    CooperationStatus,
    DeterminationOutcome,
    FulfillmentStatus,
    LimitationType,
    NqtlItemStatus,
    NqtlType,
    ParityResult,
    ParityTestStatus,
    PlanYearStatus,
    RegulatorRequestStatus,
    RemedyType,
    ReviewOutcome,
    StringencyFinding,
    SubClassification,
    SubmissionType,
    TestBasis,
)
from test_helpers.test_users import OFFICER_USER_ID_ALT


FOUR_LEVEL_MS_BASELINE = (
    (30, 5000000, 400),
    (20, 3000000, 400),
    (10, 1000000, 200),
    (0, 1500000, 100),
)


def _classification_with_four_level_baseline(api):
    """One OFFICE_VISITS classification carrying the four-level MS COPAY baseline.

    Subject weights are 9,000,000 cents and 1,000 claims against totals of
    10,500,000 cents and 1,100 claims, with a mental-health COPAY level of 25.
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    fx.add_limitations(
        api,
        scenario.classification_id,
        [f.ms_limitation(level, cents, claims) for level, cents, claims in FOUR_LEVEL_MS_BASELINE]
        + [f.mh_limitation(25, 900000, 120)],
    )
    return scenario


def test_predominant_level_diverges_between_the_plan_payments_and_claims_count_bases(
    api, officer_headers
):
    """The same four MS COPAY levels take different predominant branches per basis.

    Weighted by plan payments the 30-level alone covers more than half the
    subject benefits and the single-level branch returns 30, so the MH level of
    25 passes.  Weighted by claims the same rows need two levels to pass one
    half, and the combination branch returns 20, so the MH level of 25 fails.

    PRD: "The single-level branch fires when some level's merged weight,
    multiplied by 2, is strictly greater than the denominator — that is, when
    one level alone covers more than one half of the subject benefits."

    Design: Difficulty/dual_variant_calc/qtl_predominant_level_plan_payments_versus_claims_count_diverge
    """
    scenario = _classification_with_four_level_baseline(api)

    pp_test = validate_success(
        api.create_parity_test(
            scenario.classification_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.PLAN_PAYMENTS),
            officer_headers,
        ),
        201,
    )
    cc_test = validate_success(
        api.create_parity_test(
            scenario.classification_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.CLAIMS_COUNT),
            officer_headers,
        ),
        201,
    )

    assert_cents(pp_test["total_ms_payments_cents"], 10500000, "total_ms_payments_cents")
    assert_cents(pp_test["subject_payments_cents"], 9000000, "subject_payments_cents")
    assert_ratio(pp_test["substantially_all_ratio"], 0.857143, 6, "plan-payments ratio")
    assert pp_test["substantially_all_met"] is True
    assert pp_test["predominant_level"] == 30
    assert pp_test["mh_level_value"] == 25
    assert pp_test["result"] == ParityResult.PASS
    assert pp_test["advisory_only"] is False

    assert_ratio(cc_test["substantially_all_ratio"], 0.909091, 6, "claims-count ratio")
    assert cc_test["substantially_all_met"] is True
    assert cc_test["predominant_level"] == 20
    assert cc_test["result"] == ParityResult.FAIL
    assert cc_test["advisory_only"] is True


def test_an_advisory_claims_count_failure_leaves_the_plan_year_compliant(api, officer_headers):
    """A FAIL on the claims-count basis never enters the plan year's counters.

    The two tests differ in `basis`, so neither supersedes the other and both
    stay COMPUTED; only the plan-payments verdict carries compliance weight.

    PRD: "`advisory_only` is true exactly when `basis` is `CLAIMS_COUNT`, and an
    advisory test never feeds `failing_parity_test_count`; the same
    classification can therefore hold a `PASS` on the `PLAN_PAYMENTS` basis and
    a `FAIL` on the `CLAIMS_COUNT` basis without the plan year's posture moving
    at all."

    Design: Difficulty/dual_variant_calc/qtl_predominant_level_plan_payments_versus_claims_count_diverge
    """
    scenario = _classification_with_four_level_baseline(api)

    pp_test = validate_success(
        api.create_parity_test(
            scenario.classification_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.PLAN_PAYMENTS),
            officer_headers,
        ),
        201,
    )
    cc_test = validate_success(
        api.create_parity_test(
            scenario.classification_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.CLAIMS_COUNT),
            officer_headers,
        ),
        201,
    )

    assert pp_test["status"] == ParityTestStatus.COMPUTED
    assert cc_test["status"] == ParityTestStatus.COMPUTED

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["failing_parity_test_count"] == 0
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT


def _administrator_with_two_open_production_windows(api):
    """One TPA on default 45-day terms with one OPEN request per plan year."""
    scenario = fx.registered_plan(api)
    plan_year_b = fx.open_plan_year(
        api,
        scenario.admin_id,
        plan_year_label="2027",
        covered_participant_count=1250,
    )
    request_a = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=2,
        requested_submission_types=[SubmissionType.DENIAL_RATES, SubmissionType.NETWORK_COMPOSITION],
    )
    request_b = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        plan_year_b["id"],
        requested_item_count=1,
        requested_submission_types=[SubmissionType.REIMBURSEMENT_BENCHMARK],
    )
    scenario.plan_year_b = plan_year_b
    scenario.request_a = request_a
    scenario.request_b = request_b
    return scenario


def test_the_two_cooperation_score_variants_diverge_on_their_deadlines(api, sponsor_headers):
    """Forty days past issuance, only the regulatory basis counts the requests late.

    Both requests were issued on the same day against a TPA holding 45
    contractual days, so nothing is late contractually while both have passed
    the fixed 30-day regulatory deadline.

    PRD: "The contractual deadline, `due_at`, is `issued_at` advanced by the
    administrator's `contractual_production_days` calendar days — so a TPA
    registered with the default terms gets 45 days."

    Design: Difficulty/dual_variant_calc/administrator_cooperation_contract_versus_regulatory_basis_diverge
    """
    scenario = _administrator_with_two_open_production_windows(api)

    assert_instant_equals(scenario.request_a["due_at"], "2026-09-15T00:00:00.000Z", "due_at")
    assert_instant_equals(
        scenario.request_a["regulatory_due_at"], "2026-08-31T00:00:00.000Z", "regulatory_due_at"
    )

    fx.advance_clock(api, "2026-09-10T00:00:00Z", sponsor_headers)

    administrator = fx.read_administrator(api, scenario.admin_id, sponsor_headers)
    assert administrator["late_request_count"] == 0
    assert administrator["regulator_reportable_late_count"] == 2
    assert_score(administrator["cooperation_score"], 100.00, "cooperation_score")
    assert_score(
        administrator["regulatory_basis_cooperation_score"],
        70.00,
        "regulatory_basis_cooperation_score",
    )


def test_cooperation_status_follows_the_contractual_variant_alone(api, sponsor_headers):
    """A 70.00 regulatory score does not make the TPA delinquent.

    `cooperation_status` reads the contractual score only, so both requests stay
    outstanding and not overdue and the plan year keeps a COMPLIANT posture.

    PRD: "`cooperation_status` is derived from `cooperation_score` alone:
    `COOPERATIVE` when the score is at least 80, `DELINQUENT` when the score is
    at least 50 but below 80, and `ESCALATED` when the score is below 50."

    Design: Difficulty/dual_variant_calc/administrator_cooperation_contract_versus_regulatory_basis_diverge
    """
    scenario = _administrator_with_two_open_production_windows(api)

    fx.advance_clock(api, "2026-09-10T00:00:00Z", sponsor_headers)

    administrator = fx.read_administrator(api, scenario.admin_id, sponsor_headers)
    assert administrator["cooperation_status"] == CooperationStatus.COOPERATIVE
    assert administrator["outstanding_request_count"] == 2

    request_a = validate_success(api.get_vendor_request(scenario.request_a["id"], sponsor_headers))
    request_b = validate_success(api.get_vendor_request(scenario.request_b["id"], sponsor_headers))
    assert request_a["is_overdue"] is False
    assert request_b["is_overdue"] is False

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT


def _item_with_both_evidence_terms(api, officer_headers):
    """A PRIOR_AUTHORIZATION MH-only item with both kinds of as-applied evidence.

    The denial-rate submission publishes a disparity ratio of 2.0298 and the
    network-composition submission a gap of 0.2800.
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Concurrent prior authorization required for all outpatient MH/SUD office visits.",
    )
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        nqtl_item_id=item["id"],
        requested_item_count=2,
        requested_submission_types=[SubmissionType.DENIAL_RATES, SubmissionType.NETWORK_COMPOSITION],
    )
    denial_submission = fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(
            scenario.classification_id,
            mh_denials=263,
            mh_adjudicated_claims=3491,
            ms_denials=71,
            ms_adjudicated_claims=1913,
        ),
        scenario.admin_id,
    )
    network_submission = fx.produce_submission(
        api,
        request["id"],
        f.network_composition_submission_payload(
            scenario.classification_id,
            mh_in_network_provider_pct=0.34,
            ms_in_network_provider_pct=0.62,
        ),
        scenario.admin_id,
    )
    scenario.item = item
    scenario.item_id = item["id"]
    scenario.vendor_request = request
    scenario.denial_submission = denial_submission
    scenario.network_submission = network_submission
    return scenario


def test_stringency_index_applies_the_pinned_order_of_multiplier_cap_and_clamp(
    api, officer_headers
):
    """Five interacting inputs resolve to 8.45 under the pinned evaluation order.

    A capped documentation credit of 0.25 is subtracted after the 1.5 asymmetry
    multiplier and before the clamp; clamping first would publish 7.50 and an
    uncapped credit would publish 7.45.

    PRD: "Two shortcuts produce different numbers and are both wrong: clamping
    before subtracting the credit, and subtracting an uncapped credit."

    Design: Difficulty/combinatorial_formula/stringency_index_nested_min_max_with_asymmetry_multiplier
    """
    scenario = _item_with_both_evidence_terms(api, officer_headers)

    fx.draft_analysis(
        api,
        scenario.item_id,
        factor_count=4,
        evidentiary_standard_count=5,
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )

    item = fx.read_item(api, scenario.item_id)
    assert_index(item["stringency_in_operation_index"], 8.45, "stringency_in_operation_index")
    assert round(float(item["stringency_in_operation_index"]), 2) != 7.50
    assert round(float(item["stringency_in_operation_index"]), 2) != 7.45
    assert item["stringency_flag"] is True
    assert item["status"] == NqtlItemStatus.ANALYSIS_DRAFTED


def test_the_index_inputs_are_published_on_the_submissions_that_produced_them(
    api, officer_headers
):
    """Both evidence terms are readable at their own published precisions.

    The disparity ratio is rounded once from the unrounded quotients to four
    places, the two raw rates are reported to six, and the network gap to four;
    the second validated submission fulfils the two-item request.

    PRD: "The `disparity_ratio` is then the raw MH/SUD rate divided by the raw
    medical/surgical rate, rounded half up to four decimal places."

    Design: Difficulty/combinatorial_formula/stringency_index_nested_min_max_with_asymmetry_multiplier
    """
    scenario = _item_with_both_evidence_terms(api, officer_headers)

    assert_ratio(scenario.denial_submission["mh_denial_rate"], 0.075337, 6, "mh_denial_rate")
    assert_ratio(scenario.denial_submission["ms_denial_rate"], 0.037114, 6, "ms_denial_rate")
    assert_ratio(scenario.denial_submission["disparity_ratio"], 2.0298, 4, "disparity_ratio")
    assert scenario.denial_submission["as_applied_flag"] is True
    assert_ratio(
        scenario.network_submission["network_composition_gap"],
        0.2800,
        4,
        "network_composition_gap",
    )

    request = validate_success(api.get_vendor_request(scenario.vendor_request["id"], officer_headers))
    assert request["fulfillment_status"] == FulfillmentStatus.FULFILLED


def _two_violations_with_two_drafted_design_changes(api, officer_headers, sponsor_headers):
    """Two items in VIOLATION in one classification, each with a DRAFT design change.

    The determinations are recorded by `user-officer-01`, so `user-officer-02`
    remains independent enough to approve the plans.
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    item_a = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Prior authorization required for outpatient MH/SUD office visits.",
    )
    item_b = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        nqtl_type=NqtlType.MEDICAL_NECESSITY_CRITERIA,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Proprietary MH/SUD medical necessity criteria applied to outpatient office visits.",
    )
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )
    fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(
            scenario.classification_id,
            mh_denials=300,
            mh_adjudicated_claims=1000,
            ms_denials=100,
            ms_adjudicated_claims=1000,
        ),
        scenario.admin_id,
    )

    for item in (item_a, item_b):
        analysis = fx.draft_analysis(
            api,
            item["id"],
            factor_count=2,
            evidentiary_standard_count=1,
            stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
            stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
        )
        fx.submit_analysis(api, analysis["id"])
        fx.record_determination(
            api,
            item["id"],
            scenario.plan_year_id,
            DeterminationOutcome.VIOLATION,
            headers=officer_headers,
        )

    cap_a = fx.draft_cap(
        api,
        item_a["id"],
        sponsor_headers,
        remedy_type=RemedyType.DESIGN_CHANGE,
        affected_claims_count=1327,
        average_claim_cents=4990,
    )
    cap_b = fx.draft_cap(
        api,
        item_b["id"],
        sponsor_headers,
        remedy_type=RemedyType.DESIGN_CHANGE,
        affected_claims_count=881,
        average_claim_cents=3990,
    )
    scenario.item_a = item_a
    scenario.item_b = item_b
    scenario.cap_a = cap_a
    scenario.cap_b = cap_b
    return scenario


def test_each_plan_freezes_its_own_rounded_liability_before_the_ledger_sums_them(
    api, officer_headers, sponsor_headers, officer_alt_headers
):
    """Two half-cent design changes round individually, then sum to 2,534,231.

    Rounding each plan at its own creation and summing the rounded amounts is
    the pinned order; summing the raw products and rounding once would publish
    2,534,230.

    PRD: "The aggregation order is pinned: each plan's amount is rounded to whole
    cents at its own creation, and the already-rounded amounts are then summed."

    Design: Difficulty/combinatorial_formula/remediation_liability_rounded_per_plan_then_summed
    """
    scenario = _two_violations_with_two_drafted_design_changes(api, officer_headers, sponsor_headers)

    assert_cents(scenario.cap_a["reprocessing_liability_cents"], 1655433, "cap A liability")
    assert_cents(scenario.cap_b["reprocessing_liability_cents"], 878798, "cap B liability")

    fx.decide_cap(api, scenario.cap_a["id"], CapDecisionOutcome.APPROVED, officer_alt_headers)
    fx.decide_cap(api, scenario.cap_b["id"], CapDecisionOutcome.APPROVED, officer_alt_headers)

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_cents(plan_year["remediation_liability_cents"], 2534231, "remediation_liability_cents")
    assert plan_year["remediation_liability_cents"] != 2534230


def test_approving_both_plans_stamps_the_approver_and_keeps_the_plan_year_in_remediation(
    api, officer_headers, sponsor_headers, officer_alt_headers
):
    """Approval is the leg that books liability, and both violations stay open.

    Neither approval remediates an item, so `open_violation_count` remains 2 and
    the plan year keeps the REMEDIATION status its first violation imposed.

    PRD: "Approval moves the plan `DRAFT` to `APPROVED`, stamps
    `approved_by_user_id` from the acting `X-User-ID`, increments the plan's
    `version` by 1, adds exactly the plan's frozen `reprocessing_liability_cents`
    to the plan year's `remediation_liability_cents`, and increments the plan
    year's `version` by 1."

    Design: Difficulty/combinatorial_formula/remediation_liability_rounded_per_plan_then_summed
    """
    scenario = _two_violations_with_two_drafted_design_changes(api, officer_headers, sponsor_headers)

    decided_a = fx.decide_cap(
        api, scenario.cap_a["id"], CapDecisionOutcome.APPROVED, officer_alt_headers
    )
    fx.decide_cap(api, scenario.cap_b["id"], CapDecisionOutcome.APPROVED, officer_alt_headers)

    assert_fields(
        decided_a,
        status=CapStatus.APPROVED,
        approved_by_user_id=OFFICER_USER_ID_ALT,
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["open_violation_count"] == 2
    assert plan_year["status"] == PlanYearStatus.REMEDIATION


def _four_demanded_items_three_of_them_certified(api, officer_headers, officer_alt_headers):
    """Four inventoried NQTL types, three carrying CERTIFIED analyses (E total 8)."""
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )
    fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(
            scenario.classification_id,
            mh_denials=137,
            mh_adjudicated_claims=1919,
            ms_denials=71,
            ms_adjudicated_claims=1913,
        ),
        scenario.admin_id,
    )

    demanded_types = [
        NqtlType.PRIOR_AUTHORIZATION,
        NqtlType.NETWORK_ADMISSION,
        NqtlType.REIMBURSEMENT_RATE,
        NqtlType.MEDICAL_NECESSITY_CRITERIA,
    ]
    items = [
        fx.inventory_item(
            api,
            scenario.plan_year_id,
            scenario.classification_id,
            officer_headers,
            nqtl_type=nqtl_type,
            applied_to=AppliedTo.BOTH,
            description=f"{nqtl_type} applied to outpatient office visits on both benefit sides.",
        )
        for nqtl_type in demanded_types
    ]

    for item, (factors, standards) in zip(items[:3], ((3, 3), (3, 3), (2, 2))):
        analysis = fx.draft_analysis(
            api,
            item["id"],
            factor_count=factors,
            evidentiary_standard_count=standards,
            stringency_written_finding=StringencyFinding.COMPARABLE,
            stringency_operation_finding=StringencyFinding.COMPARABLE,
        )
        fx.submit_analysis(api, analysis["id"])
        fx.review_analysis(api, analysis["id"], ReviewOutcome.CERTIFIED, officer_alt_headers)

    regulator_request = fx.open_regulator_request(
        api,
        scenario.plan_year_id,
        requested_nqtl_types=demanded_types,
        request_reference="DOL-EBSA-2026-00417",
    )
    scenario.items = items
    scenario.regulator_request = regulator_request
    return scenario


def test_completeness_tier_is_read_from_the_base_before_any_credit_is_added(
    api, officer_headers, officer_alt_headers, sponsor_headers
):
    """Three covered items of four give base 75.00, tier B and a score of 81.00.

    Eight evidentiary standards earn tier B's full credit of 6 points, and 81.00
    stays below the sufficiency threshold; re-reading the tier from the credited
    figure would promote the response to tier A and 85.00.

    PRD: "The tier must be read from the base before any credit is added;
    re-deriving the tier from the credited figure, or iterating to a fixed point,
    is forbidden and can promote a response across the sufficiency threshold that
    should have failed it."

    Design: Difficulty/combinatorial_formula/regulator_completeness_tier_selected_from_base_before_credit
    """
    scenario = _four_demanded_items_three_of_them_certified(api, officer_headers, officer_alt_headers)

    responded = fx.respond_to_regulator(
        api,
        scenario.regulator_request["id"],
        sponsor_headers,
        response_note="Three of four demanded comparative analyses are certified and produced.",
    )

    assert_score(responded["completeness_score"], 81.00, "completeness_score")
    assert round(float(responded["completeness_score"]), 2) != 85.00
    assert responded["response_sufficient"] is False


def test_the_response_counts_only_certified_analyses_as_coverage(
    api, officer_headers, officer_alt_headers, sponsor_headers
):
    """Four items are demanded, three are covered, and the deadline is unchanged.

    The item with no analysis at all contributes nothing to coverage, the request
    moves to RESPONDED, and the plan year remains frozen under regulator review.

    PRD: "`covered_item_count` is the subset of those items having at least one
    comparative analysis in status `CERTIFIED`; analyses in `WITHDRAWN`, `DRAFT`,
    `SUBMITTED` or `INSUFFICIENT` do not cover an item."

    Design: Difficulty/combinatorial_formula/regulator_completeness_tier_selected_from_base_before_credit
    """
    scenario = _four_demanded_items_three_of_them_certified(api, officer_headers, officer_alt_headers)

    responded = fx.respond_to_regulator(
        api,
        scenario.regulator_request["id"],
        sponsor_headers,
        response_note="Three of four demanded comparative analyses are certified and produced.",
    )

    assert responded["requested_item_count"] == 4
    assert responded["covered_item_count"] == 3
    assert responded["status"] == RegulatorRequestStatus.RESPONDED
    assert_instant_equals(
        responded["response_due_at"], "2026-08-31T00:00:00.000Z", "response_due_at"
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["status"] == PlanYearStatus.UNDER_REGULATOR_REVIEW
