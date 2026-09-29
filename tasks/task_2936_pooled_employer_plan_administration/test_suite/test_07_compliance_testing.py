"""Coverage and deferral-percentage testing at both scopes, and their guards."""

from typing import Any, Dict, Optional

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_COMPLIANCE_TEST_NOT_FOUND,
    ERR_DUPLICATE_COMPLIANCE_TEST,
    ERR_DUPLICATE_EMPLOYER_EIN,
    ERR_DUPLICATE_FILING_YEAR,
    ERR_EMPLOYER_PLAN_MISMATCH,
    ERR_EXIT_TRANSFER_NOT_FOUND,
    ERR_NO_APPROVED_ELECTION,
    ERR_PLAN_NOT_ACTIVE,
    ERR_REMITTANCE_DEPOSIT_NOT_FOUND,
    ERR_TEST_SCOPE_MISMATCH,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_percentage,
    ids_of,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from test_helpers.test_users import regulator_headers
from prd_bench_local_runner.testing import validate_error

# A syntactically valid identifier that names nothing in any collection.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

ALDER_LEGAL_NAME = "Alder Components LLC"
ALDER_EIN = "420000045"
ALDER_SIGNATORY = "M. Alder"

BIRCHMONT_LEGAL_NAME = "Birchmont Instruments Inc"
BIRCHMONT_EIN = "420000046"
BIRCHMONT_SIGNATORY = "S. Birchmont"

DIVISION_TWO_LEGAL_NAME = "Palisade Machining LLC (Division 2)"
LATER_WINDOW_CLOSE_DATE = "2026-10-31"

# A discretionary tiered election puts an employer on the tested track rather
# than the safe-harbour exempt one.
TIERED_100_AT_3_AND_25_AT_6 = {
    "match_formula_code": k.MATCH_DISCRETIONARY_TIERED,
    "match_tier_1_pct": 100.0,
    "match_tier_1_limit_pct": 3.0,
    "match_tier_2_pct": 25.0,
    "match_tier_2_limit_pct": 6.0,
}


def _electing_employer(
    api: ApiClient,
    plan: PlanContext,
    signatory: str,
    employer_payload: Optional[Dict[str, Any]] = None,
    **election_overrides: Any,
) -> EmployerContext:
    """Admit an employer and approve an election, so it can be tested."""
    emp_ctx = fixtures.applied_employer(api, plan, employer_payload)
    fixtures.submitted_election(
        api, emp_ctx, signatory_name=signatory, **election_overrides
    )
    approved = validate_single(
        api.approve_design_election(emp_ctx.election_id, plan.provider_headers)
    )
    emp_ctx.elections[-1] = approved
    emp_ctx.refresh(api)
    return emp_ctx


def _census(
    plan: PlanContext,
    legal_name: str,
    ein: str,
    hce_count: int,
    benefiting_hce_count: int,
    nhce_count: int,
    benefiting_nhce_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """An employer whose census is stated explicitly for a compliance test."""
    return f.adopting_employer_payload(
        plan.plan_id,
        legal_name=legal_name,
        ein=ein,
        participant_count=hce_count + nhce_count,
        hce_count=hce_count,
        nhce_count=nhce_count,
        benefiting_hce_count=benefiting_hce_count,
        benefiting_nhce_count=benefiting_nhce_count,
        **overrides,
    )


def test_one_census_passes_as_a_pooled_plan_and_fails_employer_by_employer(
    api: ApiClient, plan
):
    """
    The same two employers give opposite verdicts under the two population
    variants, and the variant is chosen by the scope alone.

    "Under `PLAN_LEVEL` the pooled plan is treated as a single plan and the
    population is every employer of the plan whose `adoption_status` is `ACTIVE` or
    `SUSPENDED`. Under `EMPLOYER_LEVEL` the population is the single employer named
    by `adopting_employer_id`, tested as though it maintained its own plan."

    "`ratio_pct` is then `nhce_benefiting_pct` multiplied by one hundred and divided
    by `hce_benefiting_pct`, rounded half up to two decimal places."

    "The scope difference is observable: two employers with benefiting-over-population
    HCE and NHCE figures of ten out of ten and ninety out of one hundred, and ten out
    of ten and twelve out of twenty, aggregate to a `ratio_pct` of 85.00 and pass at
    `PLAN_LEVEL`, while the second employer tested alone yields 60.00 and fails at
    `EMPLOYER_LEVEL`."

    Design: Difficulty/dual_variant_calc/coverage_ratio_plan_level_versus_employer_level_scope
    """
    _electing_employer(
        api,
        plan,
        ALDER_SIGNATORY,
        _census(plan, ALDER_LEGAL_NAME, ALDER_EIN, 10, 10, 100, 90),
    )
    birchmont = _electing_employer(
        api,
        plan,
        BIRCHMONT_SIGNATORY,
        _census(plan, BIRCHMONT_LEGAL_NAME, BIRCHMONT_EIN, 10, 10, 20, 12),
    )

    plan_wide = fixtures.completed_test(api, plan)
    assert_fields(
        plan_wide,
        scope=k.SCOPE_PLAN_LEVEL,
        population_hce_count=20,
        population_nhce_count=120,
        benefiting_hce_count=20,
        benefiting_nhce_count=102,
        status=k.TEST_PASSED,
    )
    assert_percentage(plan_wide["hce_benefiting_pct"], 100.00, "hce_benefiting_pct")
    assert_percentage(plan_wide["nhce_benefiting_pct"], 85.00, "nhce_benefiting_pct")
    assert_percentage(plan_wide["ratio_pct"], 85.00, "ratio_pct")

    employer_only = fixtures.completed_test(
        api,
        plan,
        f.employer_level_test_payload(plan.plan_id, birchmont.employer_id),
    )
    assert_fields(
        employer_only,
        scope=k.SCOPE_EMPLOYER_LEVEL,
        population_hce_count=10,
        population_nhce_count=20,
        status=k.TEST_FAILED,
        failure_reason=k.FAILURE_RATIO_BELOW_THRESHOLD,
    )
    assert_percentage(employer_only["nhce_benefiting_pct"], 60.00, "nhce_benefiting_pct")
    assert_percentage(employer_only["ratio_pct"], 60.00, "ratio_pct")

    assert_fields(plan.refresh(api), participant_count=140, audit_required=False)


def test_the_seventy_percent_ratio_threshold_is_inclusive_to_the_cent(
    api: ApiClient, plan
):
    """
    Two employer-level tests in one plan are separated by a single participant, and
    that participant is what decides the verdict at exactly 70.00.

    "The verdict is `PASSED` when `ratio_pct` is at least 70.00 and `FAILED` when it
    is below 70.00, in which case `failure_reason` is set to
    `RATIO_BELOW_THRESHOLD`."

    "each of the two benefiting percentages is rounded to two decimals *before* the
    ratio is taken"

    "A scheduled test opens in `status` `SCHEDULED` with `run_at`, `failure_reason`,
    `closed_reason` and every computed population count and percentage null, and
    `exemption_applied` false."

    Design: Difficulty/boundary_precision_check/coverage_ratio_seventy_percent_inclusive_boundary
    """
    on_the_threshold = _electing_employer(
        api,
        plan,
        k.PALISADE_SIGNATORY,
        _census(plan, k.PALISADE_LEGAL_NAME, k.PALISADE_EIN, 10, 10, 100, 70),
    )
    one_participant_short = _electing_employer(
        api,
        plan,
        k.QUARRY_SIGNATORY,
        _census(plan, k.QUARRY_LEGAL_NAME, k.QUARRY_EIN, 10, 10, 100, 69),
    )

    scheduled = fixtures.scheduled_test(
        api,
        plan,
        f.employer_level_test_payload(plan.plan_id, on_the_threshold.employer_id),
    )
    assert_fields(scheduled, status=k.TEST_SCHEDULED, exemption_applied=False)
    assert_null_fields(
        scheduled,
        "run_at",
        "failure_reason",
        "closed_reason",
        "population_hce_count",
        "population_nhce_count",
        "hce_benefiting_pct",
        "nhce_benefiting_pct",
        "ratio_pct",
    )

    passing = fixtures.run_test(api, plan, scheduled)
    assert_fields(
        passing,
        population_hce_count=10,
        population_nhce_count=100,
        status=k.TEST_PASSED,
    )
    assert_null_fields(passing, "failure_reason")
    assert_percentage(passing["hce_benefiting_pct"], 100.00, "hce_benefiting_pct")
    assert_percentage(passing["nhce_benefiting_pct"], 70.00, "nhce_benefiting_pct")
    assert_percentage(passing["ratio_pct"], 70.00, "ratio_pct")

    failing = fixtures.completed_test(
        api,
        plan,
        f.employer_level_test_payload(
            plan.plan_id, one_participant_short.employer_id
        ),
    )
    assert_fields(
        failing,
        population_hce_count=10,
        population_nhce_count=100,
        status=k.TEST_FAILED,
        failure_reason=k.FAILURE_RATIO_BELOW_THRESHOLD,
    )
    assert_percentage(failing["hce_benefiting_pct"], 100.00, "hce_benefiting_pct")
    assert_percentage(failing["nhce_benefiting_pct"], 69.00, "nhce_benefiting_pct")
    assert_percentage(failing["ratio_pct"], 69.00, "ratio_pct")

    assert_fields(plan.refresh(api), participant_count=220)


def test_the_permitted_hce_average_branches_at_the_eight_percent_constant(
    api: ApiClient, plan
):
    """
    Two employer-level deferral tests straddle the upper branch point with
    continuous data, and each population is the single employer named.

    "When the NHCE average is above 2.00 and at most 8.00 percent, `adp_limit_pct`
    is that average plus two percentage points. When the NHCE average is above 8.00
    percent, `adp_limit_pct` is that average multiplied by 1.25."

    "an NHCE average of 2.50 gives 4.50 by the addend branch, not 5.00, and an NHCE
    average of 8.50 gives 10.63 by the 1.25 multiplier branch, not 10.50"

    "The verdict is `PASSED` when `hce_avg_deferral_pct` is at most `adp_limit_pct` —
    the comparison is inclusive, so an HCE average exactly equal to the limit passes
    — and `FAILED` when it exceeds the limit, in which case `failure_reason` is set
    to `HCE_AVERAGE_EXCEEDS_LIMIT`."

    "`hce_benefiting_pct`, `nhce_benefiting_pct` and `ratio_pct` are populated only
    for a coverage test that has been run, and remain null on `ADP` and `ACP` tests."

    Design: Corner/calculations/corner_adp_limit_tier_two_branch_and_inclusive_pass
    """
    on_the_addend_branch = _electing_employer(
        api,
        plan,
        k.PALISADE_SIGNATORY,
        _census(
            plan,
            k.PALISADE_LEGAL_NAME,
            k.PALISADE_EIN,
            3,
            3,
            10,
            9,
            hce_avg_deferral_pct=4.50,
            nhce_avg_deferral_pct=2.50,
        ),
        **TIERED_100_AT_3_AND_25_AT_6,
    )
    on_the_multiplier_branch = _electing_employer(
        api,
        plan,
        k.QUARRY_SIGNATORY,
        _census(
            plan,
            k.QUARRY_LEGAL_NAME,
            k.QUARRY_EIN,
            1,
            1,
            3,
            3,
            hce_avg_deferral_pct=10.64,
            nhce_avg_deferral_pct=8.50,
        ),
        **TIERED_100_AT_3_AND_25_AT_6,
    )
    assert_fields(
        on_the_addend_branch.election,
        nondiscrimination_track=k.TRACK_ADP_ACP_TESTED,
    )

    passing = fixtures.completed_test(
        api,
        plan,
        f.employer_level_test_payload(
            plan.plan_id,
            on_the_addend_branch.employer_id,
            test_type=k.TEST_TYPE_ADP,
        ),
    )
    assert_fields(
        passing,
        status=k.TEST_PASSED,
        exemption_applied=False,
        population_hce_count=3,
        population_nhce_count=10,
    )
    assert_null_fields(passing, "failure_reason", "ratio_pct")
    assert_percentage(passing["nhce_avg_deferral_pct"], 2.50, "nhce_avg_deferral_pct")
    assert_percentage(passing["adp_limit_pct"], 4.50, "adp_limit_pct")
    assert_percentage(passing["hce_avg_deferral_pct"], 4.50, "hce_avg_deferral_pct")
    assert_instant_equals(passing["run_at"], k.DEFAULT_CLOCK, "run_at")

    failing = fixtures.completed_test(
        api,
        plan,
        f.employer_level_test_payload(
            plan.plan_id,
            on_the_multiplier_branch.employer_id,
            test_type=k.TEST_TYPE_ADP,
        ),
    )
    assert_fields(
        failing,
        status=k.TEST_FAILED,
        failure_reason=k.FAILURE_HCE_AVERAGE_EXCEEDS_LIMIT,
        exemption_applied=False,
        population_hce_count=1,
        population_nhce_count=3,
    )
    assert_null_fields(failing, "ratio_pct")
    assert_percentage(failing["nhce_avg_deferral_pct"], 8.50, "nhce_avg_deferral_pct")
    assert_percentage(failing["adp_limit_pct"], 10.63, "adp_limit_pct")
    assert_percentage(failing["hce_avg_deferral_pct"], 10.64, "hce_avg_deferral_pct")
    assert_instant_equals(failing["run_at"], k.DEFAULT_CLOCK, "run_at")


def test_an_unknown_path_id_returns_the_error_of_its_own_collection(api: ApiClient):
    """
    The collection named in the path selects the not-found identifier, so three
    reads of the same unknown id give three different errors in the same envelope.

    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/corner_get_unknown_compliance_test_not_found
    """
    for response, expected in (
        (
            api.get_compliance_test(UNKNOWN_ID, regulator_headers()),
            ERR_COMPLIANCE_TEST_NOT_FOUND,
        ),
        (
            api.get_remittance_deposit(UNKNOWN_ID, regulator_headers()),
            ERR_REMITTANCE_DEPOSIT_NOT_FOUND,
        ),
        (
            api.get_exit_transfer(UNKNOWN_ID, regulator_headers()),
            ERR_EXIT_TRANSFER_NOT_FOUND,
        ),
    ):
        validate_error(response, expected, expected_status=404)
        body = response.json()
        assert body["response_type"] == "error", (
            f"Expected response_type 'error', got {body['response_type']!r}"
        )
        assert set(body["data"]) == {"error_id", "message"}, (
            f"An error payload carries only error_id and message, got "
            f"{sorted(body['data'])}"
        )
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "The error message must be a non-empty string"
        )

def _second_active_plan(api: ApiClient, plan: PlanContext) -> PlanContext:
    """Bring a second plan document of the same sponsor all the way to ACTIVE."""
    second = fixtures.second_plan(api, plan)
    recordkeeper = fixtures.engage_provider(
        api, plan.provider_id, f.recordkeeper_payload(second["id"])
    )
    trustee = fixtures.engage_provider(
        api, plan.provider_id, f.trustee_payload(second["id"])
    )
    second_ctx = PlanContext(
        provider=plan.provider,
        plan=second,
        recordkeeper=recordkeeper,
        trustee=trustee,
    )
    second_ctx.named_fiduciary_allocation = fixtures.acknowledge_role(
        api,
        fixtures.allocate_role(
            api, second_ctx, recordkeeper["id"], k.FIDUCIARY_NAMED_FIDUCIARY_3_16
        ),
        k.NAMED_FIDUCIARY_ACKNOWLEDGMENT,
    )
    second_ctx.trustee_allocation = fixtures.acknowledge_role(
        api,
        fixtures.allocate_role(
            api, second_ctx, trustee["id"], k.FIDUCIARY_TRUSTEE_403A
        ),
        k.TRUSTEE_ACKNOWLEDGMENT,
    )
    second_ctx.plan = validate_single(
        api.activate_plan_document(second_ctx.plan_id, plan.provider_headers)
    )
    return second_ctx


def test_a_test_cannot_name_an_employer_of_the_sponsors_other_plan(
    api: ApiClient, plan
):
    """
    Both identifiers resolve to real rows, so the rejection is the cross-reference
    rule rather than a not-found, and the scope rule is shown to be reached first.

    "Five conditions guard scheduling, in this order."

    "The scope and the employer reference must agree: `adopting_employer_id` must be
    present when `scope` is `EMPLOYER_LEVEL` and must be null when `scope` is
    `PLAN_LEVEL`, and either mismatch is rejected with `ERR_TEST_SCOPE_MISMATCH`."

    "A named employer must belong to the named plan, failing which the request is
    rejected with `ERR_EMPLOYER_PLAN_MISMATCH`."

    "A scheduled test opens in `status` `SCHEDULED` with `run_at`, `failure_reason`,
    `closed_reason` and every computed population count and percentage null, and
    `exemption_applied` false."

    "For every list response the `meta` object carries `limit` (the effective page
    size applied), `offset` (the effective starting position applied), `total_count`
    (the number of rows matching the request before the page window is applied) and
    `has_more` (true when rows remain beyond the current window)."

    Design: Corner/entities/corner_compliance_test_rejects_employer_of_another_plan
    """
    palisade = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    other_plan = _second_active_plan(api, plan)
    assert_fields(
        other_plan.plan, status=k.PLAN_ACTIVE, plan_number=k.PLAN_NUMBER_SECOND
    )

    validate_error(
        api.create_compliance_test(
            f.employer_level_test_payload(other_plan.plan_id, palisade.employer_id),
            plan.provider_headers,
        ),
        ERR_EMPLOYER_PLAN_MISMATCH,
        expected_status=409,
    )
    validate_error(
        api.create_compliance_test(
            f.compliance_test_payload(
                other_plan.plan_id, scope=k.SCOPE_EMPLOYER_LEVEL
            ),
            plan.provider_headers,
        ),
        ERR_TEST_SCOPE_MISMATCH,
        expected_status=422,
    )

    accepted = validate_created(
        api.create_compliance_test(
            f.employer_level_test_payload(plan.plan_id, palisade.employer_id),
            plan.provider_headers,
        )
    )
    assert_fields(
        accepted,
        plan_document_id=plan.plan_id,
        adopting_employer_id=palisade.employer_id,
        scope=k.SCOPE_EMPLOYER_LEVEL,
        status=k.TEST_SCHEDULED,
        exemption_applied=False,
    )
    assert_null_fields(
        accepted,
        "run_at",
        "failure_reason",
        "closed_reason",
        "population_hce_count",
        "population_nhce_count",
        "benefiting_hce_count",
        "benefiting_nhce_count",
        "hce_benefiting_pct",
        "nhce_benefiting_pct",
        "ratio_pct",
        "hce_avg_deferral_pct",
        "nhce_avg_deferral_pct",
        "adp_limit_pct",
    )

    validate_collection(
        api.list_plan_compliance_tests(other_plan.plan_id, plan.provider_headers),
        expected_total=0,
        expected_len=0,
    )
    items, _ = validate_collection(
        api.list_plan_compliance_tests(plan.plan_id, plan.provider_headers),
        expected_total=1,
    )
    assert items[0]["id"] == accepted["id"], (
        "the accepted test belongs to the listing of the plan it names"
    )


def test_four_uniqueness_gates_and_two_prerequisites_on_one_live_plan(
    api: ApiClient, plan
):
    """
    The employer key is unique per plan, the return unique per plan year and the test
    unique per five-part tuple, and the plan-active gate reads the plan the payload
    names rather than the actor's own live plan.

    "Once the plan document is `ACTIVE`, the pooled plan provider onboards adopting
    employers; onboarding against a plan still in `DRAFT` is rejected with
    `ERR_PLAN_NOT_ACTIVE`."

    "Each employer arrives with `plan_document_id`, its `legal_name` (1 to 200
    characters), its `ein` (exactly nine digits, unique among the employers of that
    same plan — a duplicate is rejected with `ERR_DUPLICATE_EMPLOYER_EIN`), and an
    `election_window_close_date`, the last calendar date on which that employer may
    submit a plan design election."

    "Opening the return is the pooled plan provider's act and needs only
    `plan_document_id` and the `plan_year` covered, an integer between 2020 and 2030
    inclusive that must be unique among that plan's filings; a second filing for the
    same year is rejected with `ERR_DUPLICATE_FILING_YEAR`."

    "At most one test that is not `CLOSED` may exist for a given combination of plan,
    `test_type`, `scope`, `plan_year` and named employer; a second is rejected with
    `ERR_DUPLICATE_COMPLIANCE_TEST`."

    "Finally, an `EMPLOYER_LEVEL` test requires that the named employer hold an
    `APPROVED` election, because otherwise its nondiscrimination track is undefined;
    an employer still in `APPLIED`, `ELECTIONS_SUBMITTED` or `RETURNED_FOR_REVISION`
    is rejected with `ERR_NO_APPROVED_ELECTION`."

    Design: Corner/errors/corner_plan_scoped_duplicate_keys_and_test_prerequisites_rejected
    """
    palisade = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    without_an_election = fixtures.applied_employer(
        api, plan, f.second_adopting_employer_payload(plan.plan_id)
    )
    assert_fields(without_an_election.employer, adoption_status=k.EMPLOYER_APPLIED)
    still_draft_plan = fixtures.second_plan(api, plan)
    assert_fields(still_draft_plan, status=k.PLAN_DRAFT)

    division_two = f.adopting_employer_payload(
        plan.plan_id,
        legal_name=DIVISION_TWO_LEGAL_NAME,
        ein=k.PALISADE_EIN,
        election_window_close_date=LATER_WINDOW_CLOSE_DATE,
        participant_count=5,
        hce_count=1,
        nhce_count=4,
        benefiting_hce_count=1,
        benefiting_nhce_count=4,
        hce_avg_deferral_pct=5.00,
        nhce_avg_deferral_pct=4.00,
    )
    validate_error(
        api.create_adopting_employer(division_two, plan.provider_headers),
        ERR_DUPLICATE_EMPLOYER_EIN,
        expected_status=409,
    )
    validate_error(
        api.create_adopting_employer(
            dict(division_two, plan_document_id=still_draft_plan["id"],
                 legal_name=k.PALISADE_LEGAL_NAME),
            plan.provider_headers,
        ),
        ERR_PLAN_NOT_ACTIVE,
        expected_status=409,
    )

    filing_2026 = validate_created(
        api.create_plan_filing(
            f.plan_filing_payload(plan.plan_id, k.PLAN_YEAR), plan.provider_headers
        )
    )
    assert_fields(filing_2026, plan_year=k.PLAN_YEAR, filing_status=k.FILING_DRAFT)
    validate_error(
        api.create_plan_filing(
            f.plan_filing_payload(plan.plan_id, k.PLAN_YEAR), plan.provider_headers
        ),
        ERR_DUPLICATE_FILING_YEAR,
        expected_status=409,
    )
    filing_2027 = validate_created(
        api.create_plan_filing(
            f.plan_filing_payload(plan.plan_id, k.PLAN_YEAR + 1), plan.provider_headers
        )
    )
    assert_fields(filing_2027, plan_year=k.PLAN_YEAR + 1, filing_status=k.FILING_DRAFT)

    employer_adp = f.employer_level_test_payload(
        plan.plan_id, palisade.employer_id, test_type=k.TEST_TYPE_ADP
    )
    first = validate_created(
        api.create_compliance_test(employer_adp, plan.provider_headers)
    )
    assert_fields(first, test_type=k.TEST_TYPE_ADP, scope=k.SCOPE_EMPLOYER_LEVEL)
    validate_error(
        api.create_compliance_test(employer_adp, plan.provider_headers),
        ERR_DUPLICATE_COMPLIANCE_TEST,
        expected_status=409,
    )
    plan_wide_adp = validate_created(
        api.create_compliance_test(
            f.compliance_test_payload(plan.plan_id, test_type=k.TEST_TYPE_ADP),
            plan.provider_headers,
        )
    )
    assert_fields(
        plan_wide_adp,
        test_type=k.TEST_TYPE_ADP,
        scope=k.SCOPE_PLAN_LEVEL,
        plan_year=k.PLAN_YEAR,
        status=k.TEST_SCHEDULED,
    )
    assert_null_fields(plan_wide_adp, "adopting_employer_id")

    validate_error(
        api.create_compliance_test(
            f.employer_level_test_payload(
                plan.plan_id,
                without_an_election.employer_id,
                test_type=k.TEST_TYPE_ADP,
            ),
            plan.provider_headers,
        ),
        ERR_NO_APPROVED_ELECTION,
        expected_status=409,
    )

    tests, _ = validate_collection(
        api.list_plan_compliance_tests(plan.plan_id, plan.provider_headers),
        expected_total=2,
    )
    assert ids_of(tests) == [first["id"], plan_wide_adp["id"]], (
        "only the two accepted tests exist, in creation order"
    )
    filings, _ = validate_collection(
        api.list_plan_filings(plan.plan_id, plan.provider_headers),
        expected_total=2,
    )
    assert ids_of(filings) == [filing_2026["id"], filing_2027["id"]], (
        "only the two accepted filings exist, in creation order"
    )
