"""Arithmetic read back through the API: input sets, constants and rounding.

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
    assert_index,
    assert_instant_equals,
    assert_is_none,
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
    EscalationStatus,
    FulfillmentStatus,
    LimitationType,
    NetworkTier,
    NqtlItemStatus,
    NqtlType,
    ParityResult,
    ParityTestStatus,
    PlanYearStatus,
    RejectionReason,
    RemedyType,
    StringencyFinding,
    SubClassification,
    SubmissionStatus,
    SubmissionType,
    TestBasis,
)

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


def _run_test(api, classification_id, headers, **overrides):
    """Run one quantitative parity test and return the created record."""
    return validate_success(
        api.create_parity_test(classification_id, f.parity_test_payload(**overrides), headers), 201
    )


# ═══ calculations / parity_test_counts_only_active_rows_of_the_requested_limitation_type ══


def _classification_carrying_a_decoy_visit_limit_row(api):
    """A COPAY baseline of 5,000,000 / 1,500,000 cents beside two rows that must not count.

    The 9,000,000-cent VISIT_LIMIT row is the wrong `limitation_type` for a COPAY
    test and the 800,000-cent MENTAL_HEALTH_SUD row is the wrong `benefit_side`,
    yet both are `ACTIVE` and both sit on the very classification under test — an
    implementation that filters on only one of the two attributes reports a total
    of 15,500,000 or 7,300,000 cents instead of 6,500,000.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    scenario.limitations = fx.add_limitations(
        api,
        scenario.classification_id,
        [
            f.ms_limitation(30, 5000000, 400),
            f.ms_limitation(0, 1500000, 100),
            f.ms_limitation(20, 9000000, 900, limitation_type=LimitationType.VISIT_LIMIT),
            f.mh_limitation(30, 800000, 90),
        ],
    )
    return scenario


def test_a_copay_test_ignores_the_visit_limit_row_and_the_mental_health_row(api, officer_headers):
    """Both sums are drawn from the two medical/surgical COPAY rows and nothing else.

    The denominator is 6,500,000 cents and the numerator 5,000,000 — the level 0
    row is inside the total but outside the subject weight, giving a ratio of
    0.769231 that clears two thirds.  Only the level 30 row carries a positive
    level, so it alone is the predominant level, and a mental-health level equal to
    it passes rather than fails.

    PRD: "The test population is drawn only from the medical/surgical baseline:
    every treatment-limitation row whose `classification_id` is the classification
    in the path, whose `status` is `ACTIVE`, whose `benefit_side` is
    `MEDICAL_SURGICAL` and whose `limitation_type` matches the requested type."

    Design: Corner/calculations/parity_test_counts_only_active_rows_of_the_requested_limitation_type
    """
    scenario = _classification_carrying_a_decoy_visit_limit_row(api)

    parity_test = _run_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert parity_test["status"] == ParityTestStatus.COMPUTED
    assert_cents(parity_test["total_ms_payments_cents"], 6500000, "total_ms_payments_cents")
    assert_cents(parity_test["subject_payments_cents"], 5000000, "subject_payments_cents")
    assert_ratio(parity_test["substantially_all_ratio"], 0.769231, 6, "substantially_all_ratio")
    assert parity_test["substantially_all_met"] is True
    assert parity_test["predominant_level"] == 30
    assert parity_test["mh_level_value"] == 30
    assert parity_test["result"] == ParityResult.PASS
    assert parity_test["advisory_only"] is False

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["failing_parity_test_count"] == 0
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT


def test_the_visit_limit_row_is_a_population_of_its_own_with_no_mental_health_counterpart(
    api, officer_headers
):
    """Asking for the decoy's own type proves the filter cuts both ways.

    A VISIT_LIMIT test sees 9,000,000 cents, all of it subject to the limitation,
    for a ratio of exactly 1.000000 and a predominant level of 20 — none of the
    COPAY money appears.  There is no `ACTIVE` MENTAL_HEALTH_SUD row of that type,
    so `mh_level_value` is null and the verdict is `NOT_APPLICABLE` rather than a
    pass, and the two tests coexist on the classification because they differ in
    `limitation_type`.

    PRD: "`mh_level_value` is that row's `level_value`, or null when the set is
    empty."

    Design: Corner/calculations/parity_test_counts_only_active_rows_of_the_requested_limitation_type
    """
    scenario = _classification_carrying_a_decoy_visit_limit_row(api)
    _run_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )

    visit_test = _run_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.VISIT_LIMIT,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert_cents(visit_test["total_ms_payments_cents"], 9000000, "total_ms_payments_cents")
    assert_cents(visit_test["subject_payments_cents"], 9000000, "subject_payments_cents")
    assert_ratio(visit_test["substantially_all_ratio"], 1.000000, 6, "substantially_all_ratio")
    assert visit_test["substantially_all_met"] is True
    assert visit_test["predominant_level"] == 20
    assert_is_none(visit_test["mh_level_value"], "mh_level_value")
    assert visit_test["result"] == ParityResult.NOT_APPLICABLE

    assert_collection(
        api.list_parity_tests(
            scenario.classification_id, {"status": ParityTestStatus.COMPUTED}, officer_headers
        ),
        2,
        2,
        False,
    )


# ═══ calculations / parity_test_with_a_zero_weight_population_rejected ═════════


def _two_tiers_over_a_weightless_claims_baseline(api):
    """Two classifications, neither of which can be tested on every basis.

    The in-network row holds a medical/surgical COPAY baseline worth 6,500,000
    cents across zero claims, so it has weight under `PLAN_PAYMENTS` and none at
    all under `CLAIMS_COUNT`.  The out-of-network row — a different tier, so the
    buffered measurement-period rule never engages — holds a mental-health row
    only, and therefore has no test population under either basis.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    scenario.classification_a_id = scenario.classification_id
    classification_b = fx.create_classification(
        api,
        scenario.plan_year_id,
        network_tier=NetworkTier.OUT_OF_NETWORK,
        **OUTPATIENT_SLICE,
    )
    scenario.classification_b_id = classification_b["id"]

    fx.add_limitations(
        api,
        scenario.classification_a_id,
        [f.ms_limitation(30, 5000000, 0), f.ms_limitation(0, 1500000, 0)],
    )
    fx.add_limitation(api, scenario.classification_b_id, f.mh_limitation(30, 800000, 90))
    return scenario


def test_the_same_rows_are_testable_by_payments_and_refused_by_claims_count(api, officer_headers):
    """The zero-denominator guard is applied per basis, not per classification.

    The payments-weighted test computes normally from the identical rows, at
    0.769231.  The claims-weighted test over those same rows has a total weight of
    0, so it is refused outright rather than reported with a null ratio, and the
    classification is left holding exactly the one test that could be computed.

    PRD: "When the total weight under the requested basis is 0 there is nothing to
    test and no ratio to compute, and the request is rejected with
    `ERR_EMPTY_TEST_POPULATION` (HTTP 422) rather than dividing by zero; at least
    one `ACTIVE` `MEDICAL_SURGICAL` row of the requested `limitation_type` must
    carry a positive weight under the requested basis."

    Design: Corner/calculations/parity_test_with_a_zero_weight_population_rejected
    """
    scenario = _two_tiers_over_a_weightless_claims_baseline(api)

    payments_test = _run_test(
        api,
        scenario.classification_a_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert_ratio(payments_test["substantially_all_ratio"], 0.769231, 6, "substantially_all_ratio")
    assert payments_test["substantially_all_met"] is True
    assert payments_test["predominant_level"] == 30
    assert_is_none(payments_test["mh_level_value"], "mh_level_value")
    assert payments_test["result"] == ParityResult.NOT_APPLICABLE

    assert_error(
        api.create_parity_test(
            scenario.classification_a_id,
            f.parity_test_payload(
                limitation_type=LimitationType.COPAY, basis=TestBasis.CLAIMS_COUNT
            ),
            officer_headers,
        ),
        ApiErrorId.EMPTY_TEST_POPULATION,
        422,
    )

    assert_collection(
        api.list_parity_tests(scenario.classification_a_id, None, officer_headers), 1, 1, False
    )


def test_a_classification_holding_only_a_mental_health_row_has_nothing_to_test(
    api, officer_headers
):
    """With no medical/surgical baseline at all the test is refused on its own basis.

    The 800,000-cent mental-health row is the only level on the out-of-network
    classification, and mental-health rows never enter either sum, so the payments
    basis is as empty as the claims basis and no record is written for the refusal.

    PRD: "Superseded rows are excluded, and `MENTAL_HEALTH_SUD` rows never enter
    either sum."

    Design: Corner/calculations/parity_test_with_a_zero_weight_population_rejected
    """
    scenario = _two_tiers_over_a_weightless_claims_baseline(api)

    assert_error(
        api.create_parity_test(
            scenario.classification_b_id,
            f.parity_test_payload(
                limitation_type=LimitationType.COPAY, basis=TestBasis.PLAN_PAYMENTS
            ),
            officer_headers,
        ),
        ApiErrorId.EMPTY_TEST_POPULATION,
        422,
    )
    assert_empty_collection(
        api.list_parity_tests(scenario.classification_b_id, None, officer_headers)
    )
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["failing_parity_test_count"] == 0
    ), "a refused test must not be counted anywhere"


# ═══ calculations / claims_count_basis_failure_is_advisory_only ════════════════


def _four_level_baseline_under_a_mid_level_mental_health_copay(api):
    """Four medical/surgical COPAY levels chosen so the two bases diverge.

    Weighted by payments the level 30 row alone covers more than half the subject
    benefits; weighted by claims no level does, so the combination branch runs and
    stops one level lower.  The mental-health copay sits at 25 — between the two
    answers — which is what makes the same rows pass on one basis and fail on the
    other.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    fx.add_limitations(
        api,
        scenario.classification_id,
        [
            f.ms_limitation(30, 5000000, 400),
            f.ms_limitation(20, 3000000, 400),
            f.ms_limitation(10, 1000000, 200),
            f.ms_limitation(0, 1500000, 100),
            f.mh_limitation(25, 700000, 80),
        ],
    )
    return scenario


def test_a_claims_weighted_failure_is_recorded_as_advisory_and_moves_no_posture(
    api, officer_headers
):
    """The failing row exists on the record and the plan year does not notice it.

    Claims-weighted, 1,000 of 1,100 claims are subject to a copay, so the ratio is
    0.909091 and the standard is met; no single level covers more than half of the
    1,000, so the descending walk stops at 20 and the mental-health level of 25 is
    strictly more restrictive — a FAIL.  Because the basis is `CLAIMS_COUNT` the
    test is advisory, the plan year still counts zero failing tests and stays
    COMPLIANT and OPEN, and the two cents columns keep reporting the payments sums
    of 10,500,000 and 9,000,000 so the record stays comparable across bases.

    PRD: "`advisory_only` is true exactly when `basis` is `CLAIMS_COUNT`, and an
    advisory test never feeds `failing_parity_test_count`; the same classification
    can therefore hold a `PASS` on the `PLAN_PAYMENTS` basis and a `FAIL` on the
    `CLAIMS_COUNT` basis without the plan year's posture moving at all."

    Design: Corner/calculations/claims_count_basis_failure_is_advisory_only
    """
    scenario = _four_level_baseline_under_a_mid_level_mental_health_copay(api)

    advisory = _run_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.CLAIMS_COUNT,
    )
    assert advisory["basis"] == TestBasis.CLAIMS_COUNT
    assert advisory["advisory_only"] is True
    assert_ratio(advisory["substantially_all_ratio"], 0.909091, 6, "substantially_all_ratio")
    assert advisory["substantially_all_met"] is True
    assert advisory["predominant_level"] == 20
    assert advisory["mh_level_value"] == 25
    assert advisory["result"] == ParityResult.FAIL
    assert_cents(advisory["total_ms_payments_cents"], 10500000, "total_ms_payments_cents")
    assert_cents(advisory["subject_payments_cents"], 9000000, "subject_payments_cents")

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["failing_parity_test_count"] == 0
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT
    assert plan_year["status"] == PlanYearStatus.OPEN


def test_the_payments_weighted_test_over_the_same_rows_carries_the_compliance_weight(
    api, officer_headers
):
    """Only the payments-weighted verdict is allowed to be believed.

    Weighted by cents the level 30 row's 5,000,000 doubles past the 9,000,000
    subject denominator on its own, so the predominant level is 30, the
    mental-health level of 25 is no more restrictive, and the non-advisory test
    passes.  It sits on the classification alongside the advisory failure without
    either superseding the other, and the plan year reads clean.

    PRD: "Because the two bases can take different branches of the predominant
    algorithm, that divergence is expected rather than anomalous."

    Design: Corner/calculations/claims_count_basis_failure_is_advisory_only
    """
    scenario = _four_level_baseline_under_a_mid_level_mental_health_copay(api)
    _run_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.CLAIMS_COUNT,
    )

    binding = _run_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert binding["advisory_only"] is False
    assert_ratio(binding["substantially_all_ratio"], 0.857143, 6, "substantially_all_ratio")
    assert binding["predominant_level"] == 30
    assert binding["mh_level_value"] == 25
    assert binding["result"] == ParityResult.PASS

    rows, _ = assert_collection(
        api.list_parity_tests(
            scenario.classification_id, {"status": ParityTestStatus.COMPUTED}, officer_headers
        ),
        2,
        2,
        False,
    )
    assert {row["result"] for row in rows} == {ParityResult.FAIL, ParityResult.PASS}
    assert fx.read_plan_year(api, scenario.plan_year_id)["failing_parity_test_count"] == 0


# ═══ calculations / stringency_index_ignores_rejected_submissions ═══════════════


def _network_admission_item_with_one_validated_denial_set(api, officer_headers):
    """A NETWORK_ADMISSION item whose classification holds one usable denial-rate set.

    The request asks for three items across both evidence types, so it can absorb
    the two failures the test is about without ever reaching `FULFILLED`.  The one
    good set reports 137 MH/SUD denials in 1,919 claims against 71 in 1,913 — a
    disparity ratio of 1.9235, exactly the PRD's worked network-facing example.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        headers=officer_headers,
        nqtl_type=NqtlType.NETWORK_ADMISSION,
        applied_to=AppliedTo.BOTH,
        description="Provider network admission standards for outpatient office visits.",
    )
    scenario.item_id = item["id"]
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=3,
        requested_submission_types=[
            SubmissionType.DENIAL_RATES,
            SubmissionType.NETWORK_COMPOSITION,
        ],
        nqtl_item_id=item["id"],
    )
    scenario.vendor_request_id = request["id"]
    scenario.validated_submission = fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(scenario.classification_id),
        scenario.admin_id,
    )
    return scenario


def test_a_rejected_production_attempt_is_kept_without_publishing_any_of_its_numbers(
    api, officer_headers, administrator_headers_for
):
    """Two failed submissions are persisted with every derived number left null.

    The first reports 300 denials in 1,000 MH/SUD claims against a comparator that
    denied nothing at all, which would have implied an enormous disparity had it
    validated; it is rejected for the missing comparator denials instead.  The
    second omits the medical/surgical provider share and is rejected for that.
    Neither advances the fulfilment dimension, so the request still reports one
    validated submission and sits in PARTIAL rather than FULFILLED.

    PRD: "A rejected submission is still persisted, because the TPA's production
    attempt belongs on the record, but it leaves every computed rate, ratio and gap
    null, and it advances neither `validated_submission_count` nor
    `fulfillment_status`."

    Design: Corner/calculations/stringency_index_ignores_rejected_submissions
    """
    scenario = _network_admission_item_with_one_validated_denial_set(api, officer_headers)
    admin_headers = administrator_headers_for(scenario.admin_id)

    good = scenario.validated_submission
    assert good["status"] == SubmissionStatus.VALIDATED
    assert_ratio(good["mh_denial_rate"], 0.071391, 6, "mh_denial_rate")
    assert_ratio(good["ms_denial_rate"], 0.037114, 6, "ms_denial_rate")
    assert_ratio(good["disparity_ratio"], 1.9235, 4, "disparity_ratio")
    assert good["as_applied_flag"] is False

    zero_comparator = validate_success(
        api.create_data_submission(
            scenario.vendor_request_id,
            f.denial_rate_submission_payload(
                scenario.classification_id,
                mh_denials=300,
                mh_adjudicated_claims=1000,
                ms_denials=0,
                ms_adjudicated_claims=1000,
            ),
            admin_headers,
        ),
        201,
    )
    assert zero_comparator["status"] == SubmissionStatus.REJECTED
    assert zero_comparator["rejection_reason"] == RejectionReason.ZERO_COMPARATOR_DENIALS
    assert_is_none(zero_comparator["disparity_ratio"], "disparity_ratio")
    assert zero_comparator["as_applied_flag"] is False

    missing_pct = validate_success(
        api.create_data_submission(
            scenario.vendor_request_id,
            f.network_composition_submission_payload(
                scenario.classification_id,
                mh_in_network_provider_pct=0.30,
                ms_in_network_provider_pct=f.OMIT,
            ),
            admin_headers,
        ),
        201,
    )
    assert missing_pct["status"] == SubmissionStatus.REJECTED
    assert missing_pct["rejection_reason"] == RejectionReason.MISSING_NETWORK_PCT
    assert_is_none(missing_pct["network_composition_gap"], "network_composition_gap")

    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["validated_submission_count"] == 1
    assert request["fulfillment_status"] == FulfillmentStatus.PARTIAL
    assert request["escalation_status"] == EscalationStatus.NONE


def test_the_index_stands_exactly_where_the_single_validated_submission_left_it(
    api, officer_headers, administrator_headers_for
):
    """The rejected rows contribute neither a disparity nor a network gap.

    With only the validated set on the record the network-facing weights give a
    base of 0.3 times 0.9235, or 2.7705 once scaled, and the item reads 2.77 before
    any analysis exists.  Drafting an analysis that documents two factors and one
    evidentiary standard subtracts a scaled credit of 1.3 and leaves exactly 1.47 —
    the PRD's own worked figure — with the flag still false, because the rejected
    denial-rate row never raises the disparity input and the rejected
    network-composition row never lifts the network term off zero.

    PRD: "Submissions in `RECEIVED` or `REJECTED` are excluded from both."

    Design: Corner/calculations/stringency_index_ignores_rejected_submissions
    """
    scenario = _network_admission_item_with_one_validated_denial_set(api, officer_headers)
    admin_headers = administrator_headers_for(scenario.admin_id)
    api.create_data_submission(
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(
            scenario.classification_id,
            mh_denials=300,
            mh_adjudicated_claims=1000,
            ms_denials=0,
            ms_adjudicated_claims=1000,
        ),
        admin_headers,
    )
    api.create_data_submission(
        scenario.vendor_request_id,
        f.network_composition_submission_payload(
            scenario.classification_id,
            mh_in_network_provider_pct=0.30,
            ms_in_network_provider_pct=f.OMIT,
        ),
        admin_headers,
    )

    before_analysis = fx.read_item(api, scenario.item_id)
    assert_index(before_analysis["stringency_in_operation_index"], 2.77)
    assert before_analysis["stringency_flag"] is False

    fx.draft_analysis(
        api,
        scenario.item_id,
        factor_count=2,
        evidentiary_standard_count=1,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )

    item = fx.read_item(api, scenario.item_id)
    assert_index(item["stringency_in_operation_index"], 1.47)
    assert item["stringency_flag"] is False


# ═══ calculations / remedy_rate_constants_and_the_approved_only_liability_set ════


def _violation_under_a_twenty_million_cent_cap(api, officer_headers):
    """A MH/SUD-only prior-authorisation item in VIOLATION under a 20,000,000-cent cap.

    The generous cap keeps the ledger arithmetic away from the cap check, so the
    only thing that can move `remediation_liability_cents` is the set of approved
    plans.  The 300-in-1,000 against 100-in-1,000 denial evidence gives a disparity
    of 3.0000 which, weighted for utilisation management and multiplied by the
    MH/SUD-only asymmetry, clamps the index at its ceiling.  `user-officer-01`
    records the determination, leaving `user-officer-02` free to decide the plans.
    """
    scenario = fx.registered_plan(api, remediation_liability_cap_cents=20000000)
    classification = fx.create_classification(api, scenario.plan_year_id, **OUTPATIENT_SLICE)
    scenario.classification_id = classification["id"]
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        description="Prior authorization imposed on MH/SUD outpatient visits only.",
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
    fx.record_determination(
        api,
        item["id"],
        scenario.plan_year_id,
        DeterminationOutcome.VIOLATION,
        headers=officer_headers,
        rationale=(
            "MH/SUD-only prior authorization denies at three times the medical/surgical rate."
        ),
    )
    return scenario


def _draft(api, scenario, remedy_type, target_completion_date):
    return validate_success(
        api.create_corrective_action_plan(
            f.cap_payload(
                scenario.item_id,
                remedy_type=remedy_type,
                affected_claims_count=1327,
                average_claim_cents=4990,
                target_completion_date=target_completion_date,
            ),
            scenario.sponsor_headers,
        ),
        201,
    )


def test_identical_claim_inputs_freeze_at_different_amounts_under_the_two_remedy_rates(
    api, officer_headers
):
    """1,327 claims at 4,990 cents is charged in full once and at a quarter once.

    Retrospective reprocessing takes the whole allowed amount, 6,621,730 cents.
    The design change takes one quarter of it, which is 1,655,432.50 cents before
    rounding and freezes at 1,655,433 — an implementation that truncates reports
    1,655,432.  Neither plan is decided yet, so both are DRAFT with no approver
    stamped on them.

    PRD: "A design change covering 1,327 affected claims at an average of 4,990
    cents produces 1,655,432.50 cents before rounding and freezes at 1,655,433
    cents; the same inputs under retrospective claims reprocessing freeze at
    6,621,730 cents."

    Design: Corner/calculations/remedy_rate_constants_and_the_approved_only_liability_set
    """
    scenario = _violation_under_a_twenty_million_cent_cap(api, officer_headers)

    retrospective = _draft(
        api, scenario, RemedyType.RETROSPECTIVE_CLAIMS_REPROCESSING, "2026-12-31"
    )
    design_change = _draft(api, scenario, RemedyType.DESIGN_CHANGE, "2027-03-31")

    assert_cents(
        retrospective["reprocessing_liability_cents"], 6621730, "reprocessing_liability_cents"
    )
    assert_cents(
        design_change["reprocessing_liability_cents"], 1655433, "reprocessing_liability_cents"
    )
    assert retrospective["status"] == CapStatus.DRAFT
    assert design_change["status"] == CapStatus.DRAFT
    assert_is_none(design_change["approved_by_user_id"], "approved_by_user_id")
    assert_cents(
        fx.read_plan_year(api, scenario.plan_year_id)["remediation_liability_cents"],
        0,
        "remediation_liability_cents",
    )


def test_the_ledger_totals_the_approved_plan_alone_and_leaves_the_draft_off_it(
    api, officer_headers, officer_alt_headers
):
    """Approving one of the two plans books exactly that plan's frozen amount.

    The plan year reads 6,621,730 cents — the approved retrospective plan and
    nothing else — while the drafted design change stays DRAFT with a null
    approver, even though its own 1,655,433 cents would still have fitted inside
    the 20,000,000-cent cap.  The item is in VIOLATION with its index clamped at
    the 10.00 ceiling rather than reported as the 16.7 the raw arithmetic produces.

    PRD: "`remediation_liability_cents` on a plan year is the sum of
    `reprocessing_liability_cents` over the corrective action plans whose `status`
    is `APPROVED` and whose owning NQTL item belongs to that plan year, and it is 0
    when no such plan exists."

    Design: Corner/calculations/remedy_rate_constants_and_the_approved_only_liability_set
    """
    scenario = _violation_under_a_twenty_million_cent_cap(api, officer_headers)
    retrospective = _draft(
        api, scenario, RemedyType.RETROSPECTIVE_CLAIMS_REPROCESSING, "2026-12-31"
    )
    design_change = _draft(api, scenario, RemedyType.DESIGN_CHANGE, "2027-03-31")

    approved = validate_success(
        api.decide_corrective_action_plan(
            retrospective["id"],
            f.cap_decision_payload(
                CapDecisionOutcome.APPROVED,
                decision_note="Retrospective reprocessing approved.",
            ),
            officer_alt_headers,
        )
    )
    assert approved["status"] == CapStatus.APPROVED
    assert_cents(
        approved["reprocessing_liability_cents"], 6621730, "reprocessing_liability_cents"
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_cents(
        plan_year["remediation_liability_cents"], 6621730, "remediation_liability_cents"
    )
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION
    assert plan_year["status"] == PlanYearStatus.REMEDIATION

    still_drafted = fx.read_cap(api, design_change["id"])
    assert still_drafted["status"] == CapStatus.DRAFT
    assert_is_none(still_drafted["approved_by_user_id"], "approved_by_user_id")

    item = fx.read_item(api, scenario.item_id)
    assert_index(item["stringency_in_operation_index"], 10.00)
    assert item["status"] == NqtlItemStatus.VIOLATION


# ═══ calculations / cooperation_score_baseline_for_an_administrator_with_no_late_requests ══


def _tpa_on_default_terms_with_one_open_request(api, sponsor_headers):
    """A newly registered TPA on 45-day terms holding one two-item request.

    The logical clock is left untouched at its 2026-08-01T00:00:00.000Z start, so
    neither deadline derived at issuance has passed and nothing has been produced.
    """
    administrator = validate_success(
        api.create_administrator(f.administrator_payload(), sponsor_headers), 201
    )
    plan_year = fx.open_plan_year(api, administrator["id"], sponsor_headers)
    request = validate_success(
        api.create_vendor_request(
            f.vendor_request_payload(
                administrator["id"],
                plan_year["id"],
                requested_item_count=2,
                requested_submission_types=[SubmissionType.DENIAL_RATES],
            ),
            sponsor_headers,
        ),
        201,
    )
    scenario = fx.Scenario(
        administrator=administrator,
        admin_id=administrator["id"],
        plan_year=plan_year,
        plan_year_id=plan_year["id"],
        vendor_request=request,
        vendor_request_id=request["id"],
    )
    return scenario


def test_a_tpa_sits_at_the_perfect_baseline_both_before_and_after_being_asked(
    api, sponsor_headers, officer_headers
):
    """Registration alone publishes 100.00 on both bases, and issuance does not dent it.

    Every counter starts at 0 and both scores start from a perfect 100 because
    there is nothing to subtract.  Issuing the request adds one outstanding
    obligation and triggers a recomputation, and that recomputation must arrive at
    the same 100.00 on both bases — the clock has not passed either deadline, and
    lateness is a strictly-later comparison.

    PRD: "Each score starts from a perfect 100, subtracts 15 points for every late
    request on that basis, subtracts 25 points for every declared breach, and is
    floored at 0 before rounding, so the score never goes negative however many
    breaches accumulate; the result is then rounded half up to two decimal places
    and can never exceed 100.00."

    Design: Corner/calculations/cooperation_score_baseline_for_an_administrator_with_no_late_requests
    """
    scenario = _tpa_on_default_terms_with_one_open_request(api, sponsor_headers)

    at_birth = scenario.administrator
    assert_score(at_birth["cooperation_score"], 100.00, "cooperation_score at registration")
    assert_score(
        at_birth["regulatory_basis_cooperation_score"],
        100.00,
        "regulatory_basis_cooperation_score at registration",
    )
    assert at_birth["cooperation_status"] == CooperationStatus.COOPERATIVE
    assert at_birth["late_request_count"] == 0
    assert at_birth["regulator_reportable_late_count"] == 0
    assert at_birth["breach_count"] == 0
    assert at_birth["outstanding_request_count"] == 0

    after_issuance = fx.read_administrator(api, scenario.admin_id, officer_headers)
    assert after_issuance["outstanding_request_count"] == 1
    assert after_issuance["late_request_count"] == 0
    assert after_issuance["regulator_reportable_late_count"] == 0
    assert after_issuance["breach_count"] == 0
    assert_score(after_issuance["cooperation_score"], 100.00, "cooperation_score after issuance")
    assert_score(
        after_issuance["regulatory_basis_cooperation_score"],
        100.00,
        "regulatory_basis_cooperation_score after issuance",
    )
    assert after_issuance["cooperation_status"] == CooperationStatus.COOPERATIVE


def test_both_deadlines_are_derived_once_at_issuance_from_the_contract_and_the_regulation(
    api, sponsor_headers
):
    """45 contractual days and a fixed 30 regulatory days from the same instant.

    The request is stamped at the clock's start value, so the contractual deadline
    lands on 2026-09-15 and the regulatory deadline a fortnight earlier on
    2026-08-31, and the two disagree on purpose.  Nothing has been produced and no
    deadline has passed, so the request is OPEN, unescalated, not overdue and
    holding no validated submissions, and the plan year of a cooperative TPA with
    nothing inventoried reads COMPLIANT.

    PRD: "The contractual deadline, `due_at`, is `issued_at` advanced by the
    administrator's `contractual_production_days` calendar days — so a TPA
    registered with the default terms gets 45 days."

    Design: Corner/calculations/cooperation_score_baseline_for_an_administrator_with_no_late_requests
    """
    scenario = _tpa_on_default_terms_with_one_open_request(api, sponsor_headers)

    request = scenario.vendor_request
    assert_instant_equals(request["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at")
    assert_instant_equals(request["due_at"], "2026-09-15T00:00:00.000Z", "due_at")
    assert_instant_equals(
        request["regulatory_due_at"], "2026-08-31T00:00:00.000Z", "regulatory_due_at"
    )
    assert request["is_overdue"] is False
    assert request["fulfillment_status"] == FulfillmentStatus.OPEN
    assert request["escalation_status"] == EscalationStatus.NONE
    assert request["validated_submission_count"] == 0

    plan_year = fx.read_plan_year(api, scenario.plan_year_id, sponsor_headers)
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT
    assert plan_year["status"] == PlanYearStatus.OPEN
