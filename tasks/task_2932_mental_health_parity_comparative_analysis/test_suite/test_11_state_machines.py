"""Declared lifecycles: initial states, refused departures and side effects.

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
    assert_id_set,
    assert_index,
    assert_instant_equals,
    assert_is_none,
    assert_ratio,
    assert_score,
    assert_versioned_resource,
)
from test_helpers.constants import (
    MISSING_UUID,
    AdjudicationOutcome,
    AnalysisStatus,
    AppliedTo,
    CapClosureOutcome,
    CapStatus,
    CompliancePosture,
    DeterminationOutcome,
    LimitationStatus,
    LimitationType,
    NoticeSource,
    NoticeType,
    NqtlItemStatus,
    NqtlType,
    ParityResult,
    ParityTestStatus,
    PlanYearStatus,
    RegulatorRequestStatus,
    StringencyFinding,
    SubClassification,
    SubmissionType,
    TestBasis,
)
from test_helpers.test_users import OFFICER_USER_ID_ALT

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


def test_a_freshly_inventoried_item_starts_un_analysed_and_puts_the_year_at_risk(
    api, officer_headers
):
    """The declared initial state, its zero index, and the posture it forces.

    Nothing has been analysed and no evidence exists, so the item's index is the
    fresh-classification value and no actor has been stamped into the
    determination field.  The plan year itself is still on its own initial state,
    but its verdict has already moved to AT_RISK through the second rung of the
    ladder, which the single inventoried item alone triggers.

    PRD: "A new item is written with `status` `INVENTORIED`, and its
    `stringency_in_operation_index` is computed straight away from whatever
    as-applied evidence already exists for its classification, which for a fresh
    classification means 0.00."

    Design: Corner/state_machines/nqtl_item_starts_in_inventoried_and_plan_year_starts_open
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)

    item = validate_success(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                applied_to=AppliedTo.BOTH,
                description="Prior authorization for outpatient office visits.",
            ),
            officer_headers,
        ),
        201,
    )
    assert_versioned_resource(item)
    assert item["status"] == NqtlItemStatus.INVENTORIED
    assert_index(item["stringency_in_operation_index"], 0.00)
    assert item["stringency_flag"] is False
    assert_is_none(item["determination_recorded_by_user_id"], "determination_recorded_by_user_id")

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK
    assert plan_year["status"] == PlanYearStatus.OPEN
    assert plan_year["open_violation_count"] == 0
    assert plan_year["failing_parity_test_count"] == 0


def test_a_second_submission_of_the_same_analysis_is_refused_rather_than_ignored(
    api, administrator_headers_for
):
    """Submission is not idempotent, and the refusal advances nothing.

    The analysis is already in SUBMITTED, so the transition has no state left to
    depart from — even for the TPA, which is otherwise entitled to submit.  The
    revision counter stays at its initial value, the owning item does not advance
    a second time, and the reopen route is refused too, because reopening departs
    only from INSUFFICIENT.

    PRD: "It requires the analysis to be in `DRAFT` — anything else is refused
    with `ERR_ANALYSIS_NOT_DRAFT` (HTTP 409) — the owning item to be in
    `ANALYSIS_DRAFTED`, and the owning plan year not to be `CLOSED`."

    Design: Corner/state_machines/submitting_an_already_submitted_analysis_rejected
    """
    scenario = fx.item_with_submitted_analysis(
        api,
        factor_count=3,
        evidentiary_standard_count=2,
        applied_to=AppliedTo.BOTH,
        **OUTPATIENT_SLICE,
    )

    assert_error(
        api.submit_analysis(
            scenario.analysis_id, {}, administrator_headers_for(scenario.admin_id)
        ),
        ApiErrorId.ANALYSIS_NOT_DRAFT,
    )

    analysis = fx.read_analysis(api, scenario.analysis_id)
    assert analysis["status"] == AnalysisStatus.SUBMITTED
    assert analysis["revision_round"] == 0
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED

    assert_error(
        api.reopen_analysis(scenario.analysis_id, {}, scenario.sponsor_headers),
        ApiErrorId.ANALYSIS_NOT_INSUFFICIENT,
    )


def test_a_determination_on_an_un_analysed_item_is_refused_and_discloses_nothing(
    api, officer_headers
):
    """INVENTORIED is a state the determination transitions never depart from.

    The payload, the role and the plan-year version are all correct, so the only
    thing wrong is where the item stands.  Nothing is stamped, the plan year's
    verdict is exactly where the inventory left it, and no participant notice is
    minted by a refused call.

    PRD: "An item in `INVENTORIED`, `ANALYSIS_DRAFTED`, `VIOLATION` or the
    terminal `REMEDIATED` is refused with `ERR_ITEM_NOT_AWAITING_DETERMINATION`
    (HTTP 409)."

    Design: Corner/state_machines/determination_on_an_inventoried_item_rejected
    """
    scenario = fx.inventoried_item(
        api,
        nqtl_type=NqtlType.MEDICAL_NECESSITY_CRITERIA,
        applied_to=AppliedTo.BOTH,
        **OUTPATIENT_SLICE,
    )

    assert_error(
        api.create_determination(
            scenario.item_id,
            f.compliant_determination_payload(
                fx.plan_year_version(api, scenario.plan_year_id, officer_headers),
                rationale="Attempting to close an item that has no comparative analysis on file.",
            ),
            officer_headers,
        ),
        ApiErrorId.ITEM_NOT_AWAITING_DETERMINATION,
    )

    item = fx.read_item(api, scenario.item_id)
    assert item["status"] == NqtlItemStatus.INVENTORIED
    assert_is_none(item["determination_recorded_by_user_id"], "determination_recorded_by_user_id")

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK
    assert plan_year["open_violation_count"] == 0

    assert_empty_collection(api.list_participant_notices(scenario.item_id, None, officer_headers))


def test_a_certified_analysis_can_no_longer_be_superseded(api):
    """Certification is terminal, so the replacement analysis is refused.

    The supersedable set is `DRAFT`, `SUBMITTED` and `INSUFFICIENT`, and the
    target has left it.  The refusal leaves the certified row and its certifying
    officer exactly as they were, and the item still holds a single analysis.  A
    supersedes pointer at an identifier that exists nowhere fails earlier still,
    on the body foreign-key rung, with the analysis 404.

    PRD: "The named analysis must also still be supersedable — its `status` must
    be `DRAFT`, `SUBMITTED` or `INSUFFICIENT` — and a `CERTIFIED` or already
    `WITHDRAWN` analysis cannot be superseded, which is refused with
    `ERR_ANALYSIS_ALREADY_SUPERSEDED` (HTTP 409)."

    Design: Corner/state_machines/superseding_a_certified_analysis_rejected
    """
    scenario = fx.item_with_certified_analysis(
        api, nqtl_type=NqtlType.NETWORK_ADMISSION, applied_to=AppliedTo.BOTH, **OUTPATIENT_SLICE
    )
    item_version = fx.item_version(api, scenario.item_id, scenario.sponsor_headers)

    def replacement(supersedes_analysis_id):
        return f.analysis_payload(
            scenario.item_id,
            item_version,
            factor_count=3,
            evidentiary_standard_count=2,
            stringency_operation_finding=StringencyFinding.COMPARABLE,
            supersedes_analysis_id=supersedes_analysis_id,
        )

    assert_error(
        api.create_analysis(replacement(scenario.analysis_id), scenario.sponsor_headers),
        ApiErrorId.ANALYSIS_ALREADY_SUPERSEDED,
    )
    assert_error(
        api.create_analysis(replacement(MISSING_UUID), scenario.sponsor_headers),
        ApiErrorId.ANALYSIS_NOT_FOUND,
    )

    analysis = fx.read_analysis(api, scenario.analysis_id)
    assert analysis["status"] == AnalysisStatus.CERTIFIED
    assert analysis["certified_by_user_id"] == OFFICER_USER_ID_ALT
    assert_collection(
        api.list_analyses({"nqtl_item_id": scenario.item_id}, scenario.sponsor_headers), 1, 1, False
    )


def test_re_recording_the_same_limitation_level_supersedes_the_prior_row(api, officer_headers):
    """The four-attribute key decides what is replaced and what coexists.

    The incoming level-20 row matches the incumbent on classification, type, side
    and level, so the incumbent leaves the ACTIVE population; the level-0 row
    differs on one attribute and is untouched.  The parity test run afterwards
    reads only the survivors, so the superseded 2,000,000 cents contribute nothing
    and the totals are 4,000,000 against 3,000,000.

    PRD: "When a new row arrives carrying the same `classification_id`,
    `limitation_type`, `benefit_side` **and** `level_value` as an existing
    `ACTIVE` row, that existing row moves `ACTIVE` to `SUPERSEDED`, has its
    `updated_at` refreshed and its `version` incremented by 1, and is excluded
    from every calculation input set from that moment on."

    Design: Corner/state_machines/duplicate_treatment_limitation_supersedes_the_prior_row
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    incumbent, zero_level = fx.add_limitations(
        api,
        scenario.classification_id,
        [f.ms_limitation(20, 2000000, 400), f.ms_limitation(0, 1000000, 200)],
    )

    replacement = validate_success(
        api.create_treatment_limitation(
            scenario.classification_id,
            f.ms_limitation(20, 3000000, 500),
            scenario.sponsor_headers,
        ),
        201,
    )

    active, _ = assert_collection(
        api.list_treatment_limitations(
            scenario.classification_id,
            {"status": LimitationStatus.ACTIVE},
            scenario.sponsor_headers,
        ),
        2,
        2,
        False,
    )
    assert_id_set(active, [zero_level["id"], replacement["id"]])
    superseded, _ = assert_collection(
        api.list_treatment_limitations(
            scenario.classification_id,
            {"status": LimitationStatus.SUPERSEDED},
            scenario.sponsor_headers,
        ),
        1,
        1,
        False,
    )
    assert_id_set(superseded, [incumbent["id"]])

    test = validate_success(
        api.create_parity_test(
            scenario.classification_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.PLAN_PAYMENTS),
            officer_headers,
        ),
        201,
    )
    assert_cents(test["total_ms_payments_cents"], 4000000, "total_ms_payments_cents")
    assert_cents(test["subject_payments_cents"], 3000000, "subject_payments_cents")
    assert_ratio(test["substantially_all_ratio"], 0.750000, 6, "substantially_all_ratio")
    assert test["substantially_all_met"] is True
    assert test["predominant_level"] == 20
    assert_is_none(test["mh_level_value"], "mh_level_value")
    assert test["result"] == ParityResult.NOT_APPLICABLE


def _classification_failing_the_copay_test(api):
    """A classification whose MH/SUD copay of 30 sits above a predominant level of 20.

    The medical/surgical baseline is 2,000,000 cents at level 20 and 1,000,000 at
    level 0, so the subject weight is exactly two thirds of the total and the
    predominant level is 20.  The MH/SUD row is written at level 30, which is the
    more restrictive requirement and therefore fails.
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    fx.add_limitations(
        api,
        scenario.classification_id,
        [
            f.ms_limitation(20, 2000000, 400),
            f.ms_limitation(0, 1000000, 200),
            f.mh_limitation(30, 900000, 120),
        ],
    )
    return scenario


def test_re_running_a_parity_test_supersedes_the_prior_computation(api, officer_headers):
    """The rerun leaves exactly one COMPUTED test, and only that one is counted.

    The first run fails on the plan-payments basis and drives the plan year into
    VIOLATION and REMEDIATION.  Re-running the same classification, limitation type
    and basis retires the first computation and writes a second; the failing count
    is re-derived rather than accumulated, so it stays at 1 — the superseded
    failure stops counting and the fresh one takes its place.

    PRD: "When a test already exists in status `COMPUTED` for the same
    `classification_id`, `limitation_type` and `basis`, that earlier test moves
    `COMPUTED` to `SUPERSEDED` and has its `version` incremented by 1 — and because
    a superseded failure stops counting, the plan year's `failing_parity_test_count`
    is recomputed and `compliance_posture` re-derived, with the plan year's
    `version` incremented whenever the posture or the count actually changes."

    Design: Corner/state_machines/rerunning_a_parity_test_supersedes_the_prior_computation
    """
    scenario = _classification_failing_the_copay_test(api)

    first = fx.run_parity_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert first["substantially_all_met"] is True
    assert first["predominant_level"] == 20
    assert first["mh_level_value"] == 30
    assert first["result"] == ParityResult.FAIL
    assert first["advisory_only"] is False

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["failing_parity_test_count"] == 1
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION
    assert plan_year["status"] == PlanYearStatus.REMEDIATION

    second = fx.run_parity_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert second["status"] == ParityTestStatus.COMPUTED
    assert second["mh_level_value"] == 30
    assert second["result"] == ParityResult.FAIL

    computed, _ = assert_collection(
        api.list_parity_tests(
            scenario.classification_id,
            {"status": ParityTestStatus.COMPUTED},
            officer_headers,
        ),
        1,
        1,
        False,
    )
    assert_id_set(computed, [second["id"]])
    superseded, _ = assert_collection(
        api.list_parity_tests(
            scenario.classification_id,
            {"status": ParityTestStatus.SUPERSEDED},
            officer_headers,
        ),
        1,
        1,
        False,
    )
    assert_id_set(superseded, [first["id"]])

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["failing_parity_test_count"] == 1
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION


def test_the_failing_test_freezes_the_very_levels_a_rerun_would_correct(api, officer_headers):
    """Remediation is a plan-design freeze, so the correction cannot be recorded.

    The failing plan-payments test has already moved the plan year to REMEDIATION,
    and recording a corrected MH/SUD level is a plan-design write.  It is refused,
    the ACTIVE population is exactly the three rows the baseline started with, and
    a rerun against those unchanged rows fails again.

    PRD: "Creating a benefit classification or a treatment-limitation level
    additionally requires the owning plan year to be exactly `OPEN`; if it sits in
    `UNDER_REGULATOR_REVIEW` or `REMEDIATION` the write is rejected with
    `ERR_PLAN_YEAR_NOT_OPEN` (HTTP 409)."

    Design: Corner/state_machines/rerunning_a_parity_test_supersedes_the_prior_computation
    """
    scenario = _classification_failing_the_copay_test(api)
    fx.run_parity_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert fx.read_plan_year(api, scenario.plan_year_id)["status"] == PlanYearStatus.REMEDIATION

    assert_error(
        api.create_treatment_limitation(
            scenario.classification_id,
            f.mh_limitation(30, 0, 0),
            scenario.sponsor_headers,
        ),
        ApiErrorId.PLAN_YEAR_NOT_OPEN,
    )
    assert_collection(
        api.list_treatment_limitations(
            scenario.classification_id,
            {"status": LimitationStatus.ACTIVE},
            scenario.sponsor_headers,
        ),
        3,
        3,
        False,
    )

    rerun = fx.run_parity_test(
        api,
        scenario.classification_id,
        officer_headers,
        limitation_type=LimitationType.COPAY,
        basis=TestBasis.PLAN_PAYMENTS,
    )
    assert rerun["mh_level_value"] == 30
    assert rerun["result"] == ParityResult.FAIL
    assert fx.read_plan_year(api, scenario.plan_year_id)["failing_parity_test_count"] == 1


def test_completing_an_approved_remedy_fires_all_four_side_effects_at_once(
    api, officer_alt_headers
):
    """One closure moves the item, mints a notice, clears the ledger and reopens the year.

    The plan itself reaches COMPLETED with its exposure still frozen at the figure
    written at creation.  The item reaches its terminal state, a second notice is
    issued from the closure cascade rather than the determination cascade, the
    booked liability is released in full, and with no violation left the plan year
    leaves REMEDIATION for OPEN with a COMPLIANT verdict.

    PRD: "That move creates exactly one participant notice with `notice_type`
    `CORRECTION_COMPLETED` and `source` `CAP_CLOSURE_CASCADE`, again stamped with
    the plan year's `covered_participant_count` as `recipient_count` and the
    logical clock as `issued_at`."

    Design: Corner/state_machines/cap_closure_completed_remediates_the_item_and_issues_a_correction_notice
    """
    scenario = fx.item_with_approved_cap(api, **OUTPATIENT_SLICE)

    closed = validate_success(
        api.close_corrective_action_plan(
            scenario.cap_id,
            f.cap_closure_payload(
                CapClosureOutcome.COMPLETED,
                closure_note=(
                    "Prior authorization removed for MH/SUD outpatient visits and affected "
                    "claims reprocessed."
                ),
            ),
            officer_alt_headers,
        )
    )
    assert closed["status"] == CapStatus.COMPLETED
    assert_cents(closed["reprocessing_liability_cents"], 275000, "reprocessing_liability_cents")

    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.REMEDIATED

    assert_collection(
        api.list_participant_notices(scenario.item_id, None, officer_alt_headers), 2, 2, False
    )
    corrections, _ = assert_collection(
        api.list_participant_notices(
            scenario.item_id,
            {"notice_type": NoticeType.CORRECTION_COMPLETED},
            officer_alt_headers,
        ),
        1,
        1,
        False,
    )
    assert_fields(
        corrections[0],
        nqtl_item_id=scenario.item_id,
        notice_type=NoticeType.CORRECTION_COMPLETED,
        source=NoticeSource.CAP_CLOSURE_CASCADE,
        recipient_count=1200,
        disclosure_summary="PRIOR_AUTHORIZATION in OUTPATIENT/IN_NETWORK: CORRECTION_COMPLETED",
    )
    assert_instant_equals(
        corrections[0]["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at"
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_cents(plan_year["remediation_liability_cents"], 0, "remediation_liability_cents")
    assert plan_year["open_violation_count"] == 0
    assert plan_year["notified_violation_count"] == 1
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT
    assert plan_year["status"] == PlanYearStatus.OPEN


def test_the_completed_remedy_is_terminal_for_both_the_plan_and_its_item(
    api, officer_headers, officer_alt_headers
):
    """Nothing departs from COMPLETED, and nothing departs from REMEDIATED.

    A second closure of the same plan is refused because the plan is no longer
    APPROVED.  The item, now terminal, admits neither a fresh determination nor a
    fresh corrective plan, and the single correction notice is not duplicated by
    either refused call.

    PRD: "The plan must be in `APPROVED`; closing a plan in any other status,
    including a second closure of one already `COMPLETED` or `ABANDONED`, is
    refused with `ERR_CAP_NOT_APPROVED` (HTTP 409)."

    Design: Corner/state_machines/cap_closure_completed_remediates_the_item_and_issues_a_correction_notice
    """
    scenario = fx.item_with_approved_cap(api, **OUTPATIENT_SLICE)
    fx.close_cap(api, scenario.cap_id, CapClosureOutcome.COMPLETED, officer_alt_headers)

    assert_error(
        api.close_corrective_action_plan(
            scenario.cap_id,
            f.cap_closure_payload(CapClosureOutcome.ABANDONED),
            officer_alt_headers,
        ),
        ApiErrorId.CAP_NOT_APPROVED,
    )
    assert_error(
        api.create_determination(
            scenario.item_id,
            f.violation_determination_payload(
                fx.plan_year_version(api, scenario.plan_year_id, officer_headers)
            ),
            officer_headers,
        ),
        ApiErrorId.ITEM_NOT_AWAITING_DETERMINATION,
    )
    assert_error(
        api.create_corrective_action_plan(
            f.cap_payload(scenario.item_id), scenario.sponsor_headers
        ),
        ApiErrorId.ITEM_NOT_IN_VIOLATION,
    )

    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.REMEDIATED
    assert_collection(
        api.list_participant_notices(scenario.item_id, None, officer_alt_headers), 2, 2, False
    )


def test_an_accepted_response_closes_the_docket_without_absolving_the_plan_year(
    api, officer_headers, regulator_headers
):
    """The docket reaches its terminal state; the AT_RISK plan year does not.

    The response is scored fresh and covers nothing, because the single demanded
    item has no certified analysis: a base of zero lands in the bottom tier and
    earns no evidentiary credit.  The regulator accepts anyway, which closes the
    request for good, but the plan year keeps its verdict and its status — and it
    keeps accepting new inventory, because only CLOSED locks a plan year's
    children.

    PRD: "When the posture is `AT_RISK` or `VIOLATION`, the request closes but the
    plan year's `status` is left exactly as it was — a regulator may accept the
    paperwork for this docket without absolving a plan year that still has an open
    violation or a delinquent vendor."

    Design: Corner/state_machines/adjudicating_accepted_closes_the_plan_year_and_locks_further_writes
    """
    scenario = fx.plan_under_regulator_review(api, **OUTPATIENT_SLICE)

    responded = fx.respond_to_regulator(
        api,
        scenario.regulator_request_id,
        response_note="No certified comparative analysis is on file yet; the inventory is produced as-is.",
    )
    assert responded["status"] == RegulatorRequestStatus.RESPONDED
    assert responded["requested_item_count"] == 1
    assert responded["covered_item_count"] == 0
    assert_score(responded["completeness_score"], 0.00, "completeness_score")
    assert responded["response_sufficient"] is False

    accepted = validate_success(
        api.adjudicate_regulator_request(
            scenario.regulator_request_id,
            f.adjudicate_payload(
                AdjudicationOutcome.ACCEPTED,
                adjudication_note="Production accepted; the file is closed.",
            ),
            regulator_headers,
        )
    )
    assert accepted["status"] == RegulatorRequestStatus.CLOSED
    assert accepted["regulator_round"] == 0

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["status"] == PlanYearStatus.UNDER_REGULATOR_REVIEW
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK

    assert_error(
        api.respond_regulator_request(
            scenario.regulator_request_id, f.respond_payload(), scenario.sponsor_headers
        ),
        ApiErrorId.REGULATOR_REQUEST_NOT_OPEN,
    )
    assert_error(
        api.adjudicate_regulator_request(
            scenario.regulator_request_id,
            f.adjudicate_payload(AdjudicationOutcome.ACCEPTED),
            regulator_headers,
        ),
        ApiErrorId.REGULATOR_REQUEST_NOT_RESPONDED,
    )

    validate_success(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                nqtl_type=NqtlType.STEP_THERAPY,
                applied_to=AppliedTo.BOTH,
                description="Step therapy inventoried after the docket closed.",
            ),
            officer_headers,
        ),
        201,
    )


def test_an_accepted_response_closes_a_compliant_plan_year_and_locks_its_children(
    api, officer_headers, regulator_headers
):
    """The one terminal move a plan year has, and the lockdown that follows it.

    The demanded item carries a certified analysis, so the response covers it in
    full: a base of 100 in the top tier, plus the tier's credit scaled by the one
    evidentiary standard behind it, capped at 100.00.  Because the plan year's
    verdict is COMPLIANT at that instant, the acceptance carries it to CLOSED —
    after which inventorying a limitation, which REMEDIATION and regulator review
    both permitted, is refused.

    PRD: "What it does to the plan year depends on the plan year's own posture at
    that instant: when `compliance_posture` is `COMPLIANT`, the plan year moves
    from `UNDER_REGULATOR_REVIEW` to `CLOSED`, refreshing `updated_at` and
    incrementing `version` by 1, and every subsequent child mutation against it is
    refused with `ERR_PLAN_YEAR_CLOSED`."

    Design: Corner/state_machines/adjudicating_accepted_closes_the_plan_year_and_locks_further_writes
    """
    scenario = fx.item_with_certified_analysis(api, **OUTPATIENT_SLICE)
    fx.record_determination(
        api,
        scenario.item_id,
        scenario.plan_year_id,
        DeterminationOutcome.COMPLIANT,
        headers=officer_headers,
        rationale="The recomputed in-operation index is well below the violation threshold.",
    )
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.COMPLIANT
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["compliance_posture"]
        == CompliancePosture.COMPLIANT
    )

    request = fx.open_regulator_request(
        api,
        scenario.plan_year_id,
        requested_nqtl_types=[NqtlType.PRIOR_AUTHORIZATION],
        request_reference="DOL-EBSA-2026-00733",
    )
    responded = fx.respond_to_regulator(
        api, request["id"], response_note="The certified comparative analysis is produced in full."
    )
    assert responded["requested_item_count"] == 1
    assert responded["covered_item_count"] == 1
    assert_score(responded["completeness_score"], 100.00, "completeness_score")
    assert responded["response_sufficient"] is True

    accepted = fx.adjudicate_regulator_request(
        api, request["id"], AdjudicationOutcome.ACCEPTED, regulator_headers
    )
    assert accepted["status"] == RegulatorRequestStatus.CLOSED

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["status"] == PlanYearStatus.CLOSED
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT

    assert_error(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                nqtl_type=NqtlType.STEP_THERAPY,
                applied_to=AppliedTo.BOTH,
                description="Step therapy inventoried after the file closed.",
            ),
            officer_headers,
        ),
        ApiErrorId.PLAN_YEAR_CLOSED,
    )
    assert_error(
        api.create_vendor_request(
            f.vendor_request_payload(
                scenario.admin_id,
                scenario.plan_year_id,
                requested_submission_types=[SubmissionType.NETWORK_COMPOSITION],
            ),
            scenario.sponsor_headers,
        ),
        ApiErrorId.PLAN_YEAR_CLOSED,
    )


def test_an_insufficient_adjudication_reopens_the_docket_and_extends_its_deadline(
    api, regulator_headers
):
    """The regulator cycle is traversable, and every round is scored fresh.

    The first production covers nothing and is found insufficient, which returns
    the request to a respondable state, ratchets the round counter and pushes the
    30-day deadline out by a further fortnight.  The plan year stays under review
    rather than closing, and the second production is scored from scratch against
    the same uncovered item.

    PRD: "An `INSUFFICIENT` adjudication moves `RESPONDED` to
    `INSUFFICIENT_RESPONSE`, increments `regulator_round` by 1, and extends
    `response_due_at` by a further 14 calendar days — every insufficient
    adjudication grants that extension, so a request adjudicated insufficient
    twice has had 28 days added to its original 30."

    Design: Corner/state_machines/adjudicating_insufficient_reopens_the_regulator_request_for_a_second_round
    """
    scenario = fx.plan_under_regulator_review(api, **OUTPATIENT_SLICE)
    assert_instant_equals(
        scenario.regulator_request["response_due_at"],
        "2026-08-31T00:00:00.000Z",
        "response_due_at",
    )
    fx.respond_to_regulator(
        api, scenario.regulator_request_id, response_note="First production."
    )

    insufficient = validate_success(
        api.adjudicate_regulator_request(
            scenario.regulator_request_id,
            f.adjudicate_payload(
                AdjudicationOutcome.INSUFFICIENT,
                adjudication_note=(
                    "The production omits the in-operation stringency comparison; supplement "
                    "within the extended window."
                ),
            ),
            regulator_headers,
        )
    )
    assert insufficient["status"] == RegulatorRequestStatus.INSUFFICIENT_RESPONSE
    assert insufficient["regulator_round"] == 1
    assert_instant_equals(
        insufficient["response_due_at"], "2026-09-14T00:00:00.000Z", "response_due_at"
    )
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["status"]
        == PlanYearStatus.UNDER_REGULATOR_REVIEW
    )

    second = fx.respond_to_regulator(
        api,
        scenario.regulator_request_id,
        response_note="Second production including the in-operation comparison.",
    )
    assert second["status"] == RegulatorRequestStatus.RESPONDED
    assert second["regulator_round"] == 1
    assert second["requested_item_count"] == 1
    assert second["covered_item_count"] == 0
    assert_score(second["completeness_score"], 0.00, "completeness_score")
    assert second["response_sufficient"] is False
