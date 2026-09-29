"""Role-based access control: who may author what, and who may only read.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_collection,
    assert_empty_collection,
    assert_error,
    assert_id_set,
    assert_index,
    assert_instant_equals,
    assert_is_none,
    assert_ratio,
)
from test_helpers.constants import (
    AnalysisStatus,
    AppliedTo,
    CompliancePosture,
    DeterminationOutcome,
    FulfillmentStatus,
    FundingArrangement,
    NqtlItemStatus,
    NqtlType,
    ParityResult,
    ParityTestStatus,
    PlanYearStatus,
    StringencyFinding,
    SubClassification,
    SubmissionType,
    TestBasis,
)
from test_helpers.test_users import SPONSOR_USER_ID

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


# ═══ rbac / regulator_cannot_author_plan_data ════════════════════════════════════


def test_the_regulator_reads_the_whole_plan_and_is_barred_from_writing_any_of_it(
    api, regulator_headers
):
    """Read access to everything, authoring access to nothing — and the 403 lands first.

    A regulator may open a plan of its own no more than it may inventory an NQTL on
    somebody else's or record a limitation level inside their classification: all three
    writes are refused for the role, and refused before the bodies they carry are ever
    resolved — the plan-year create names a real administrator and the item create names
    a genuinely matching plan year and classification, so nothing in those payloads
    could have produced the refusal.  The same identity then reads the plan year
    happily, because every GET in this specification is open to all four roles.  The
    collections prove the writes left no residue: one plan year, the sponsor's, and not
    a single NQTL item or limitation row anywhere.

    PRD: "A `Regulator` is state or federal regulatory staff: it opens requests for a
    plan year's comparative analyses and adjudicates the sponsor's response, and it may
    read every resource in the system but may not author plan data."

    Design: Corner/rbac/regulator_cannot_author_plan_data
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)

    assert_error(
        api.create_plan_year(
            f.plan_year_payload(
                scenario.admin_id,
                plan_name="Regulator-authored plan",
                funding_arrangement=FundingArrangement.INSURED,
                covered_participant_count=900,
                remediation_liability_cap_cents=1000000,
            ),
            regulator_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.create_nqtl_item(
            f.nqtl_item_payload(
                scenario.plan_year_id,
                scenario.classification_id,
                applied_to=AppliedTo.BOTH,
                description="Regulator attempting to inventory an NQTL.",
            ),
            regulator_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.create_treatment_limitation(
            scenario.classification_id,
            f.ms_limitation(20, 2000000, 400),
            regulator_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    plan_year = validate_success(
        api.get_plan_year(scenario.plan_year_id, regulator_headers)
    )
    assert plan_year["id"] == scenario.plan_year_id
    assert plan_year["status"] == PlanYearStatus.OPEN
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT

    rows, _ = assert_collection(api.list_plan_years(None, regulator_headers), 1, 1, False)
    assert_id_set(rows, [scenario.plan_year_id])
    assert_empty_collection(
        api.list_nqtl_items({"plan_year_id": scenario.plan_year_id}, regulator_headers)
    )
    assert_empty_collection(
        api.list_treatment_limitations(
            scenario.classification_id, None, regulator_headers
        )
    )


# ═══ rbac / administrator_cannot_determine_or_open_a_regulator_request ════════════


def test_the_tpa_authors_analyses_and_touches_nothing_that_belongs_to_another_owner(
    api, officer_headers
):
    """One caller, three foreign owners, three 403s — and the state guards never speak.

    The TPA is a genuine author in this system, yet the determination endpoint belongs
    to the compliance officer, the corrective plan to the sponsor and the officer, and
    the regulator request to the regulator alone.  Each of those payloads would have
    tripped a state guard too — a determination against an `INVENTORIED` item and a
    corrective plan for an item that is not in violation are both refused on state — but
    the role check sits above every one of them on the ladder, so the answer is the role
    failure and only the role failure.  Nothing moves: the item is still inventoried
    with no determiner stamped on it, neither collection has a row, and the plan year
    keeps the exact version it carried before the three attempts.  The TPA's own
    capability is intact, and drafting an analysis proves it.

    PRD: "The role is permitted on this endpoint — otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/administrator_cannot_determine_or_open_a_regulator_request
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        applied_to=AppliedTo.BOTH,
        description="Prior authorization for outpatient office visits.",
    )
    py_version = fx.plan_year_version(api, scenario.plan_year_id, scenario.admin_headers)

    assert_error(
        api.create_determination(
            item["id"],
            f.determination_payload(
                DeterminationOutcome.COMPLIANT,
                py_version,
                rationale="The TPA attempting to certify its own administration as compliant.",
            ),
            scenario.admin_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.create_corrective_action_plan(
            f.cap_payload(item["id"]), scenario.admin_headers
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.create_regulator_request(
            f.regulator_request_payload(
                scenario.plan_year_id, request_reference="SELF-SERVED-0001"
            ),
            scenario.admin_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    unchanged = fx.read_item(api, item["id"], scenario.admin_headers)
    assert unchanged["status"] == NqtlItemStatus.INVENTORIED
    assert_is_none(
        unchanged["determination_recorded_by_user_id"],
        "determination_recorded_by_user_id",
    )
    assert_empty_collection(
        api.list_corrective_action_plans(
            {"nqtl_item_id": item["id"]}, scenario.admin_headers
        )
    )
    assert_empty_collection(
        api.list_regulator_requests(
            {"plan_year_id": scenario.plan_year_id}, scenario.admin_headers
        )
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id, scenario.admin_headers)
    assert plan_year["status"] == PlanYearStatus.OPEN
    assert plan_year["version"] == py_version
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK

    authored = fx.draft_analysis(
        api, item["id"], unchanged["version"], scenario.admin_headers
    )
    assert authored["status"] == AnalysisStatus.DRAFT
    assert authored["authored_by_user_id"] == scenario.admin_id


# ═══ rbac / plan_sponsor_cannot_review_and_compliance_officer_cannot_produce_data ══


def test_both_halves_of_the_peer_boundary_are_role_failures_not_identity_failures(
    api, sponsor_headers, officer_alt_headers
):
    """The sponsor cannot review at all, and the officer cannot manufacture the evidence.

    The sponsor who authored and submitted this analysis is refused review for its role,
    not for its identity: the self-review prohibition is an officer-only rule that a
    sponsor never reaches, so the answer is the authorisation code and not the
    self-certification code.  Symmetrically, the officer who will one day certify the
    analysis cannot produce the as-applied data the certification depends on, because
    production belongs to the TPA alone.  The third attempt aims a sponsor at an
    officer-only closure endpoint using an identifier that is not a corrective plan at
    all, and it still answers on the role — the role check outranks path resolution, so
    the not-found code the identifier deserves is never reached.  Afterwards the
    analysis is still awaiting a reviewer, the production window is still empty, and the
    item's in-operation index still reads zero because no evidence was ever admitted.

    PRD: "Producing material against an open production window is the
    `Administrator`'s exclusive capability."

    Design: Corner/rbac/plan_sponsor_cannot_review_and_compliance_officer_cannot_produce_data
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        nqtl_type=NqtlType.NETWORK_ADMISSION,
        applied_to=AppliedTo.BOTH,
        description="Provider network admission standards for outpatient office visits.",
    )
    analysis = fx.draft_analysis(
        api,
        item["id"],
        item["version"],
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    fx.submit_analysis(api, analysis["id"])
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        nqtl_item_id=item["id"],
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )

    assert_error(
        api.review_analysis(
            analysis["id"],
            f.review_payload(review_note="The sponsor certifying its own submission."),
            sponsor_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.create_data_submission(
            request["id"],
            f.denial_rate_submission_payload(scenario.classification_id),
            officer_alt_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_error(
        api.close_corrective_action_plan(
            analysis["id"],
            f.cap_closure_payload(
                closure_note="Sponsor attempting an officer-only closure."
            ),
            sponsor_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    still_submitted = fx.read_analysis(api, analysis["id"])
    assert still_submitted["status"] == AnalysisStatus.SUBMITTED
    assert_is_none(still_submitted["certified_by_user_id"], "certified_by_user_id")
    assert still_submitted["authored_by_user_id"] == SPONSOR_USER_ID

    unfulfilled = fx.read_vendor_request(api, request["id"])
    assert unfulfilled["fulfillment_status"] == FulfillmentStatus.OPEN
    assert unfulfilled["validated_submission_count"] == 0
    assert_empty_collection(
        api.list_data_submissions({"vendor_request_id": request["id"]}, sponsor_headers)
    )

    unscored = fx.read_item(api, item["id"])
    assert_index(
        unscored["stringency_in_operation_index"],
        0.00,
        "stringency_in_operation_index",
    )
    assert unscored["stringency_flag"] is False


# ═══ rbac / shared_operations_work_for_every_declared_owner ═══════════════════════


def test_every_shared_write_is_open_to_each_of_the_owners_declared_for_it(
    api, sponsor_headers, officer_headers, regulator_headers
):
    """Each shared write exercised from both of its owners, and the clock from all four.

    A limitation level is the sponsor's to record and the TPA's alike, so the same
    classification takes one row from each and lists two.  An NQTL item is the sponsor's
    to inventory and the officer's alike, so the inventory takes one type from each and
    lists two.  A parity test is the sponsor's to run and the officer's alike, so the
    same classification carries the plan-payments variant from one and the claims-count
    variant from the other — and because the baseline splits two thirds to one third on
    both weightings, the two computations agree on a ratio of exactly 0.666667, on a
    predominant level of 20 and, with nothing imposed on the mental-health side at all,
    on a verdict of `NOT_APPLICABLE`.  Only the plan-payments variant carries compliance
    weight; the claims-count one is advisory, and neither is a failure, so the year's
    failing-test count stays at zero and its posture is dragged to `AT_RISK` by the two
    un-analysed limitations alone.  The logical clock, finally, moves three times under
    three different roles, none of them the sponsor.

    PRD: "A test-driving capability, available to all four roles, sets the clock to a
    supplied `current_utc` instant."

    Design: Corner/rbac/shared_operations_work_for_every_declared_owner
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    classification_id = scenario.classification_id

    by_sponsor = fx.add_limitation(
        api, classification_id, f.ms_limitation(20, 2000000, 400), sponsor_headers
    )
    by_tpa = fx.add_limitation(
        api, classification_id, f.ms_limitation(0, 1000000, 200), scenario.admin_headers
    )
    limitation_rows, _ = assert_collection(
        api.list_treatment_limitations(classification_id, None, regulator_headers),
        2,
        2,
        False,
    )
    assert_id_set(limitation_rows, [by_sponsor["id"], by_tpa["id"]])

    item_by_sponsor = fx.inventory_item(
        api,
        scenario.plan_year_id,
        classification_id,
        sponsor_headers,
        nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
        applied_to=AppliedTo.BOTH,
        description="Inventoried by the sponsor.",
    )
    item_by_officer = fx.inventory_item(
        api,
        scenario.plan_year_id,
        classification_id,
        officer_headers,
        nqtl_type=NqtlType.STEP_THERAPY,
        applied_to=AppliedTo.BOTH,
        description="Inventoried by the compliance officer.",
    )
    assert item_by_sponsor["nqtl_type"] == NqtlType.PRIOR_AUTHORIZATION
    assert item_by_officer["nqtl_type"] == NqtlType.STEP_THERAPY
    item_rows, _ = assert_collection(
        api.list_nqtl_items({"classification_id": classification_id}, regulator_headers),
        2,
        2,
        False,
    )
    assert_id_set(item_rows, [item_by_sponsor["id"], item_by_officer["id"]])

    test_by_sponsor = fx.run_parity_test(
        api, classification_id, sponsor_headers, basis=TestBasis.PLAN_PAYMENTS
    )
    test_by_officer = fx.run_parity_test(
        api, classification_id, officer_headers, basis=TestBasis.CLAIMS_COUNT
    )
    assert test_by_sponsor["basis"] == TestBasis.PLAN_PAYMENTS
    assert test_by_officer["basis"] == TestBasis.CLAIMS_COUNT
    for parity_test in (test_by_sponsor, test_by_officer):
        assert parity_test["status"] == ParityTestStatus.COMPUTED
        assert_ratio(
            parity_test["substantially_all_ratio"],
            0.666667,
            6,
            "substantially_all_ratio",
        )
        assert parity_test["substantially_all_met"] is True
        assert parity_test["predominant_level"] == 20
        assert_is_none(parity_test["mh_level_value"], "mh_level_value")
        assert parity_test["result"] == ParityResult.NOT_APPLICABLE
    assert test_by_sponsor["advisory_only"] is False
    assert test_by_officer["advisory_only"] is True

    for actor, instant in (
        (scenario.admin_headers, "2026-08-02T00:00:00.000Z"),
        (officer_headers, "2026-08-03T00:00:00.000Z"),
        (regulator_headers, "2026-08-04T00:00:00.000Z"),
    ):
        report = validate_success(api.set_clock(f.clock_payload(instant), actor))
        assert_instant_equals(report["current_utc"], instant, "current_utc")

    plan_year = fx.read_plan_year(api, scenario.plan_year_id, regulator_headers)
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK
    assert plan_year["failing_parity_test_count"] == 0
    assert plan_year["status"] == PlanYearStatus.OPEN
