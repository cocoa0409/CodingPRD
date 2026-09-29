"""The plan-level annual return: its fork-join, its snapshot and its guards."""

from typing import Any, Dict

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_AUDIT_NOT_REQUIRED,
    ERR_AUDIT_OPINION_UNACCEPTABLE,
    ERR_AUDITOR_NOT_INDEPENDENT,
    ERR_EMPLOYER_ELECTIONS_INCOMPLETE,
    ERR_FIDELITY_BOND_INSUFFICIENT,
    ERR_FILING_ALREADY_SUBMITTED,
    ERR_FILING_INVALID_STATE,
    ERR_NOT_AN_AUDITOR_FIRM,
    ERR_PLAN_COMPLIANCE_FROZEN,
    ERR_PLAN_LEVEL_TEST_OUTSTANDING,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_percentage,
    assert_plan_control_invariants,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from test_helpers.test_users import (
    auditor_headers,
    regulator_headers,
    service_provider_headers,
)
from prd_bench_local_runner.testing import validate_error

# Seven months after the 2026-12-31 plan year end is July 2027, whose last day
# falls on a Saturday, so the deadline rolls forward to the following Monday.
FILING_DEADLINE_DATE = "2027-08-02"

# Ten percent of the canonical 8500000 of plan assets, well clear of the floor.
BOND_MINIMUM_ON_CANONICAL_ASSETS = 850000

# A single employer that carries the plan over the plan-level audit threshold,
# and one that carries it comfortably past it.
THRESHOLD_LEGAL_NAME = "Cardwell Fabrication Group LLC"
THRESHOLD_EIN = "420000051"
THRESHOLD_SIGNATORY = "D. Cardwell"
OVER_THRESHOLD_LEGAL_NAME = "Ravensworth Industrial Inc"
OVER_THRESHOLD_EIN = "420000052"
OVER_THRESHOLD_SIGNATORY = "H. Ravensworth"

REVERSAL_REASON = (
    "Successor plan trust was never established; assets must return to the "
    "pooled plan."
)
QUARRY_BLACKOUT_START_DATE = "2027-01-04"
QUARRY_BLACKOUT_END_DATE = "2027-01-15"
QUARRY_REQUESTED_EXIT_DATE = "2027-01-29"
QUARRY_SETTLEMENT_CLOCK = "2027-01-20T09:00:00Z"

# The two employers of the frozen-posture walk deliver in the canonical period
# and then both deposit one business day late.
LATE_PAIR_CLOCK = "2026-08-14T09:00:00Z"


def _big_employer(
    api: ApiClient,
    plan: PlanContext,
    legal_name: str,
    ein: str,
    signatory: str,
    participant_count: int,
    hce_count: int,
) -> EmployerContext:
    """Admit one employer large enough to move the plan's audit threshold."""
    payload = f.adopting_employer_payload(
        plan.plan_id,
        legal_name=legal_name,
        ein=ein,
        participant_count=participant_count,
        hce_count=hce_count,
        nhce_count=participant_count - hce_count,
        benefiting_hce_count=hce_count,
        benefiting_nhce_count=participant_count - hce_count,
    )
    return fixtures.active_employer(api, plan, payload, signatory_name=signatory)


def _plan_with_bond(api: ApiClient, fidelity_bond_amount_cents: int) -> PlanContext:
    """Build an ACTIVE plan whose sponsor carries an exactly stated bond."""
    provider = fixtures.registered_provider(
        api,
        f.plan_provider_payload(
            fidelity_bond_amount_cents=fidelity_bond_amount_cents
        ),
    )
    plan_document = fixtures.draft_plan(api, provider)
    recordkeeper = fixtures.engage_provider(
        api, provider["id"], f.recordkeeper_payload(plan_document["id"])
    )
    trustee = fixtures.engage_provider(
        api, provider["id"], f.trustee_payload(plan_document["id"])
    )
    plan_ctx = PlanContext(
        provider=provider,
        plan=plan_document,
        recordkeeper=recordkeeper,
        trustee=trustee,
    )
    plan_ctx.named_fiduciary_allocation = fixtures.acknowledge_role(
        api,
        fixtures.allocate_role(
            api, plan_ctx, recordkeeper["id"], k.FIDUCIARY_NAMED_FIDUCIARY_3_16
        ),
        k.NAMED_FIDUCIARY_ACKNOWLEDGMENT,
    )
    plan_ctx.trustee_allocation = fixtures.acknowledge_role(
        api,
        fixtures.allocate_role(
            api, plan_ctx, trustee["id"], k.FIDUCIARY_TRUSTEE_403A
        ),
        k.TRUSTEE_ACKNOWLEDGMENT,
    )
    plan_ctx.plan = validate_single(
        api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    )
    return plan_ctx


def _prepare(api: ApiClient, plan: PlanContext, filing: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare a return as the plan's recordkeeper."""
    return validate_single(
        api.prepare_plan_filing(filing["id"], plan.recordkeeper_headers)
    )


def _certify(api: ApiClient, plan: PlanContext, filing: Dict[str, Any]) -> Dict[str, Any]:
    """Clear the employer-data branch as the plan's sponsor."""
    return validate_single(
        api.certify_plan_filing_employer_data(filing["id"], plan.provider_headers)
    )


def _attest(
    api: ApiClient,
    filing: Dict[str, Any],
    audit_firm_service_provider_id: str,
    audit_opinion: str = k.OPINION_UNMODIFIED,
):
    """Attest a return as the independent auditor, returning the raw response."""
    return api.attest_plan_filing(
        filing["id"],
        f.attest_filing_payload(audit_firm_service_provider_id, audit_opinion),
        auditor_headers(),
    )


def test_a_small_plan_files_on_one_branch_and_refuses_the_other(
    api: ApiClient, plan, employer, audit_firm
):
    """
    The arity of the fork is decided by a field computed two transitions earlier,
    so the same attest endpoint is illegal here and the single certification alone
    completes the join.

    "`filing_status` runs `DRAFT → PREPARED → PARTIALLY_CLEARED → READY_TO_FILE →
    FILED`, with `FILED` terminal, and `PARTIALLY_CLEARED` is skipped whenever the
    fork degenerates to a single branch."

    "`audit_required` is copied from the plan document's own `audit_required` as
    evaluated at preparation time, so it reflects whether the plan's
    `participant_count` had reached 1000."

    "The filing's `audit_required` must be true, since a plan under the
    1000-participant threshold has no audit branch to clear, and attestation on such
    a filing is rejected with `ERR_AUDIT_NOT_REQUIRED`."

    "Where the filing lands depends on the other branch and on `audit_required`:
    with `audit_required` false the audit branch is pre-cleared and the join
    completes on this single branch, so the filing moves from `PREPARED` directly to
    `READY_TO_FILE`; with `audit_required` true and `audit_attested_at` still null it
    moves from `PREPARED` to `PARTIALLY_CLEARED`; and with the audit branch already
    cleared it moves from `PARTIALLY_CLEARED` to `READY_TO_FILE`."

    "On success `filing_status` moves to `FILED`, `filed_date` is set to the
    logical-clock calendar date, `is_late_filing` is set to true when `filed_date` is
    strictly later than `filing_deadline_date` and false otherwise, an
    `acknowledgment_reference` is minted by the regulator, and the filing's `version`
    is incremented by one."

    Design: Difficulty/non_linear_state_machine/plan_filing_fork_join_conditional_single_branch
    """
    assert_fields(plan.refresh(api), participant_count=13, audit_required=False)
    filing = fixtures.draft_filing(api, plan)

    prepared = _prepare(api, plan, filing)
    assert_fields(
        prepared,
        filing_status=k.FILING_PREPARED,
        audit_required=False,
        fidelity_bond_minimum_cents=k.FIDELITY_BOND_FLOOR_CENTS,
        filing_deadline_date=FILING_DEADLINE_DATE,
        late_deposit_schedule_h_line_cents=0,
        prepared_by_user_id=plan.recordkeeper_id,
    )
    assert_instant_equals(prepared["prepared_at"], k.DEFAULT_CLOCK, "prepared_at")

    validate_error(
        _attest(api, filing, audit_firm["id"]),
        ERR_AUDIT_NOT_REQUIRED,
        expected_status=409,
    )
    refused = validate_single(api.get_plan_filing(filing["id"], plan.provider_headers))
    assert_fields(refused, filing_status=k.FILING_PREPARED)
    assert_null_fields(refused, "audit_attested_at", "audit_opinion")

    assert_fields(employer.election, status=k.ELECTION_APPROVED)
    certified = _certify(api, plan, filing)
    assert_fields(
        certified,
        filing_status=k.FILING_READY_TO_FILE,
        certified_employer_count=1,
        certified_by_user_id=plan.provider_id,
    )
    assert certified["filing_status"] != k.FILING_PARTIALLY_CLEARED, (
        "the degenerate fork skips the partially cleared state entirely"
    )
    assert_instant_equals(
        certified["employer_data_certified_at"], k.DEFAULT_CLOCK,
        "employer_data_certified_at",
    )

    filed = validate_single(api.file_plan_filing(filing["id"], regulator_headers()))
    assert_fields(
        filed,
        filing_status=k.FILING_FILED,
        filed_date=k.DEFAULT_CLOCK_DATE,
        is_late_filing=False,
    )
    assert_null_fields(filed, "audit_attested_at")
    assert filed["acknowledgment_reference"], (
        "the regulator mints an acknowledgment reference on filing"
    )
    assert filed["version"] > certified["version"], (
        "filing increments the return's version"
    )


def test_the_derived_filing_figures_are_all_minted_at_preparation(
    api: ApiClient, plan, employer, second_employer
):
    """
    The same read before and after preparation separates a stored derivation from
    one recomputed per request, and the answer does not depend on who asks.

    "A new filing opens in `DRAFT` with `prepared_by_user_id`, `prepared_at`,
    `audit_attested_at`, `audit_opinion`, `audit_firm_service_provider_id`,
    `employer_data_certified_at`, `certified_by_user_id`,
    `certified_employer_count`, `late_deposit_schedule_h_line_cents`,
    `fidelity_bond_minimum_cents`, `filing_deadline_date`, `filed_date` and
    `acknowledgment_reference` all null, `audit_required` false and `is_late_filing`
    false."

    "`fidelity_bond_minimum_cents` is the minimum ERISA section 412 bond the plan
    requires: take the plan document's `total_assets_cents`, multiply by one tenth
    and round half up to whole cents, then raise the result to 100000 cents if it
    falls below that floor and cap it at 100000000 cents if it exceeds that ceiling."

    "`filing_deadline_date` is derived from the plan document's
    `plan_year_end_date`, not from the filing's own `plan_year`: take the month seven
    months after the month of `plan_year_end_date`, take the last calendar day of
    that month, and if that day is not a business day roll *forward* one day at a
    time until it is."

    "For a `plan_year_end_date` of 2026-12-31 the target month is July 2027, whose
    last day is Saturday 2027-07-31, so the deadline rolls forward to 2027-08-02."

    Design: Corner/endpoints/corner_computed_read_exposes_fields_minted_at_prepare
    """
    assert_fields(
        plan.refresh(api),
        participant_count=employer.employer["participant_count"]
        + second_employer.employer["participant_count"],
        total_assets_cents=0,
    )
    filing = fixtures.draft_filing(api, plan)

    on_the_draft = validate_single(
        api.get_plan_filing(filing["id"], plan.provider_headers)
    )
    assert_fields(
        on_the_draft,
        filing_status=k.FILING_DRAFT,
        plan_year=k.PLAN_YEAR,
        audit_required=False,
        is_late_filing=False,
    )
    assert_null_fields(
        on_the_draft,
        "prepared_by_user_id",
        "prepared_at",
        "audit_attested_at",
        "audit_opinion",
        "audit_firm_service_provider_id",
        "employer_data_certified_at",
        "certified_by_user_id",
        "certified_employer_count",
        "late_deposit_schedule_h_line_cents",
        "fidelity_bond_minimum_cents",
        "filing_deadline_date",
        "filed_date",
        "acknowledgment_reference",
    )

    _prepare(api, plan, filing)
    by_the_sponsor = validate_single(
        api.get_plan_filing(filing["id"], plan.provider_headers)
    )
    assert_fields(
        by_the_sponsor,
        filing_status=k.FILING_PREPARED,
        audit_required=False,
        fidelity_bond_minimum_cents=k.FIDELITY_BOND_FLOOR_CENTS,
        filing_deadline_date=FILING_DEADLINE_DATE,
        late_deposit_schedule_h_line_cents=0,
        prepared_by_user_id=plan.recordkeeper_id,
    )

    by_the_auditor = validate_single(
        api.get_plan_filing(filing["id"], auditor_headers())
    )
    assert by_the_auditor == by_the_sponsor, (
        "the derivation is stored, not computed per reader, so both roles see it "
        "identically"
    )


def test_one_draft_return_is_blocked_first_by_a_test_then_by_the_posture(
    api: ApiClient, plan
):
    """
    The same unchanged POST is refused twice for reasons drawn from two unrelated
    sibling populations, and the second reason is recorded nowhere on the filing
    itself.

    "And no compliance test of the plan with `scope` `PLAN_LEVEL` and the same
    `plan_year` may still be sitting in `SCHEDULED`; an outstanding plan-level test
    is rejected with `ERR_PLAN_LEVEL_TEST_OUTSTANDING`."

    "The plan's `compliance_posture` must not be `FROZEN`; with two or more suspended
    adopting employers the return cannot be prepared at all, and the request is
    rejected with `ERR_PLAN_COMPLIANCE_FROZEN`."

    "From that count the plan's `compliance_posture` follows: zero suspended
    employers means `OPEN`, exactly one means `RESTRICTED`, and two or more means
    `FROZEN`."

    "`ratio_pct` is then `nhce_benefiting_pct` multiplied by one hundred and divided
    by `hce_benefiting_pct`, rounded half up to two decimal places."

    "`late_deposit_schedule_h_line_cents` is the sum of `amount_cents` over every
    remittance deposit of the plan that is `POSTED` and whose `timeliness_status` is
    `LATE`, `CORRECTION_COMPUTED` or `CORRECTED`; a funded correction does not remove
    a deposit from this line."

    Design: Difficulty/cross_entity_state_dependency/filing_preparation_gated_by_outstanding_test_then_frozen_posture
    """
    palisade = fixtures.active_employer(api, plan)
    quarry = fixtures.second_active_employer(
        api,
        plan,
        participant_count=4,
        hce_count=1,
        nhce_count=3,
        benefiting_hce_count=1,
        benefiting_nhce_count=3,
    )
    assert_fields(plan.refresh(api), participant_count=17, compliance_posture=k.POSTURE_OPEN)

    outstanding = fixtures.scheduled_test(api, plan)
    filing = fixtures.draft_filing(api, plan)

    palisade_batch = fixtures.validated_batch(api, palisade)
    quarry_batch = fixtures.validated_batch(
        api,
        quarry,
        payroll_provider_reference=k.QUARRY_PAYROLL_REFERENCE,
        participant_line_count=4,
    )
    fixtures.set_clock(api, LATE_PAIR_CLOCK)
    palisade_deposit = fixtures.pending_deposit(
        api,
        palisade,
        palisade_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-P003",
    )
    quarry_deposit = fixtures.pending_deposit(
        api,
        quarry,
        quarry_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-Q003",
    )

    validate_error(
        api.prepare_plan_filing(filing["id"], plan.recordkeeper_headers),
        ERR_PLAN_LEVEL_TEST_OUTSTANDING,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_plan_filing(filing["id"], plan.provider_headers)),
        filing_status=k.FILING_DRAFT,
    )

    run = fixtures.run_test(api, plan, outstanding)
    assert_fields(run, status=k.TEST_PASSED, scope=k.SCOPE_PLAN_LEVEL)
    assert_percentage(run["hce_benefiting_pct"], 100.00, "hce_benefiting_pct")
    assert_percentage(run["nhce_benefiting_pct"], 92.31, "nhce_benefiting_pct")
    assert_percentage(run["ratio_pct"], 92.31, "ratio_pct")

    for deposit, reference, suspended, posture in (
        (palisade_deposit, "NG-POST-P003", 1, k.POSTURE_RESTRICTED),
        (quarry_deposit, "NG-POST-Q003", 2, k.POSTURE_FROZEN),
    ):
        posted = validate_single(
            api.post_remittance_deposit(
                deposit["id"],
                f.post_deposit_payload(reference),
                plan.recordkeeper_headers,
            )
        )
        assert_fields(posted, timeliness_status=k.TIMELINESS_LATE, late_by_business_days=1)
        assert_fields(
            plan.refresh(api),
            suspended_employer_count=suspended,
            compliance_posture=posture,
        )

    validate_error(
        api.prepare_plan_filing(filing["id"], plan.recordkeeper_headers),
        ERR_PLAN_COMPLIANCE_FROZEN,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_plan_filing(filing["id"], plan.provider_headers)),
        filing_status=k.FILING_DRAFT,
    )

    computed = fixtures.corrected_computation(
        api, quarry, quarry_deposit, recovery_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY
    )
    assert_fields(computed, restoration_cents=2096, excise_tax_cents=0)
    fixtures.funded_correction(api, quarry, quarry_deposit)
    assert_fields(quarry.refresh(api), adoption_status=k.EMPLOYER_ACTIVE)
    assert_fields(
        plan.refresh(api),
        suspended_employer_count=1,
        compliance_posture=k.POSTURE_RESTRICTED,
        total_assets_cents=17002096,
    )

    prepared = _prepare(api, plan, filing)
    assert_fields(
        prepared,
        filing_status=k.FILING_PREPARED,
        prepared_by_user_id=plan.recordkeeper_id,
        late_deposit_schedule_h_line_cents=17000000,
        audit_required=False,
        filing_deadline_date=FILING_DEADLINE_DATE,
        fidelity_bond_minimum_cents=1700210,
    )


def test_certification_counts_the_population_as_it_stands_when_it_succeeds(
    api: ApiClient, plan, employer
):
    """
    The completeness rule is a universal quantifier over a set that grew after the
    return was prepared, so an employer admitted afterwards blocks it and is then
    counted by it.

    "Then every employer of the plan whose `adoption_status` is not `EXITED` must
    hold a plan design election in `APPROVED` status; the return reports
    employer-level data for every employer the plan has admitted and not yet
    released, so an employer still sitting in `APPLIED`, `ELECTIONS_SUBMITTED` or
    `RETURNED_FOR_REVISION` blocks certification just as surely as an `ACTIVE` one
    without an approved election, and the rejection is
    `ERR_EMPLOYER_ELECTIONS_INCOMPLETE`."

    "This is easy to trip after the fact: an employer admitted *after* the filing was
    prepared is in `APPLIED` and will block a certification that would have succeeded
    a moment earlier."

    "On success `employer_data_certified_at` is stamped from the logical clock,
    `certified_by_user_id` is recorded from the acting `X-User-ID`,
    `certified_employer_count` is set to the count of the plan's employers whose
    `adoption_status` is anything other than `EXITED` at that instant, and the
    filing's `version` is incremented by one."

    Design: Corner/validations/corner_certify_requires_every_non_exited_employer_to_have_an_approved_election
    """
    filing = fixtures.draft_filing(api, plan)
    prepared = _prepare(api, plan, filing)
    assert_fields(prepared, filing_status=k.FILING_PREPARED, audit_required=False)

    late_arrival = fixtures.applied_employer(
        api, plan, f.second_adopting_employer_payload(plan.plan_id)
    )
    assert_fields(late_arrival.employer, adoption_status=k.EMPLOYER_APPLIED)
    assert_fields(plan.refresh(api), participant_count=28)

    validate_error(
        api.certify_plan_filing_employer_data(filing["id"], plan.provider_headers),
        ERR_EMPLOYER_ELECTIONS_INCOMPLETE,
        expected_status=409,
    )
    refused = validate_single(api.get_plan_filing(filing["id"], plan.provider_headers))
    assert_fields(refused, filing_status=k.FILING_PREPARED)
    assert_null_fields(
        refused, "employer_data_certified_at", "certified_by_user_id",
        "certified_employer_count",
    )

    fixtures.submitted_election(
        api,
        late_arrival,
        signatory_name=k.QUARRY_SIGNATORY,
        eligibility_min_age=21,
        eligibility_service_months=6,
        vesting_schedule=k.VESTING_GRADED_2_6,
        match_formula_code=k.MATCH_SAFE_HARBOR_ENHANCED,
    )
    approved = validate_single(
        api.approve_design_election(late_arrival.election_id, plan.provider_headers)
    )
    assert_fields(approved, status=k.ELECTION_APPROVED)
    assert_fields(employer.election, status=k.ELECTION_APPROVED)

    certified = _certify(api, plan, filing)
    assert_fields(
        certified,
        filing_status=k.FILING_READY_TO_FILE,
        certified_employer_count=2,
        certified_by_user_id=plan.provider_id,
    )
    assert_instant_equals(
        certified["employer_data_certified_at"], k.DEFAULT_CLOCK,
        "employer_data_certified_at",
    )
    assert certified["version"] > refused["version"], (
        "only the accepted certification advances the return"
    )


def test_certification_stops_short_of_the_join_when_the_audit_branch_is_open(
    api: ApiClient, plan
):
    """
    One endpoint and one empty payload reach two different destination states on two
    different plans, and repeating the accepted call is a refusal rather than a
    no-op.

    "`audit_required` on the plan document is true when the plan's
    `participant_count` is at least 1000 — the plan-level single-audit threshold —
    and false below it."

    "Where the filing lands depends on the other branch and on `audit_required`:
    with `audit_required` false the audit branch is pre-cleared and the join
    completes on this single branch, so the filing moves from `PREPARED` directly to
    `READY_TO_FILE`; with `audit_required` true and `audit_attested_at` still null it
    moves from `PREPARED` to `PARTIALLY_CLEARED`; and with the audit branch already
    cleared it moves from `PARTIALLY_CLEARED` to `READY_TO_FILE`."

    "The filing must be in `PREPARED` or `PARTIALLY_CLEARED` with
    `employer_data_certified_at` still null, failing which the request is rejected
    with `ERR_FILING_INVALID_STATE`."

    "Three conditions apply, in this order: the filing must be in `READY_TO_FILE`,
    failing which the request is rejected with `ERR_FILING_INVALID_STATE`; the plan's
    `compliance_posture` must not be `FROZEN`, failing which it is rejected with
    `ERR_PLAN_COMPLIANCE_FROZEN`; and when `audit_required` is true the recorded
    `audit_opinion` must not be `DISCLAIMER`, failing which it is rejected with
    `ERR_AUDIT_OPINION_UNACCEPTABLE`."

    Design: Corner/endpoints/corner_conditional_action_certify_stops_at_partially_cleared_when_audit_required
    """
    _big_employer(
        api, plan, OVER_THRESHOLD_LEGAL_NAME, OVER_THRESHOLD_EIN,
        OVER_THRESHOLD_SIGNATORY, 1200, 200,
    )
    assert_fields(plan.refresh(api), participant_count=1200, audit_required=True)

    filing = fixtures.draft_filing(api, plan)
    prepared = _prepare(api, plan, filing)
    assert_fields(
        prepared,
        filing_status=k.FILING_PREPARED,
        audit_required=True,
        fidelity_bond_minimum_cents=k.FIDELITY_BOND_FLOOR_CENTS,
    )

    certified = _certify(api, plan, filing)
    assert_fields(
        certified,
        filing_status=k.FILING_PARTIALLY_CLEARED,
        certified_employer_count=1,
        version=3,
    )
    assert certified["filing_status"] != k.FILING_READY_TO_FILE, (
        "the audit branch is still open, so the join cannot complete"
    )
    assert_null_fields(certified, "audit_attested_at")
    assert_instant_equals(
        certified["employer_data_certified_at"], k.DEFAULT_CLOCK,
        "employer_data_certified_at",
    )

    validate_error(
        api.certify_plan_filing_employer_data(filing["id"], plan.provider_headers),
        ERR_FILING_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.file_plan_filing(filing["id"], regulator_headers()),
        ERR_FILING_INVALID_STATE,
        expected_status=409,
    )
    unmoved = validate_single(api.get_plan_filing(filing["id"], plan.provider_headers))
    assert_fields(unmoved, filing_status=k.FILING_PARTIALLY_CLEARED, version=3)
    assert_null_fields(unmoved, "filed_date", "acknowledgment_reference")


def test_the_audit_branch_screens_the_named_firm_on_three_separate_grounds(
    api: ApiClient, plan
):
    """
    The firm named for attestation is screened by provider type, by independence and
    by who prepared the return, and the last refusal arrives only after the branch
    has already cleared on a perfectly valid opinion.

    "First, the firm named for attestation must be engaged on the plan and must have
    `provider_type` `AUDITOR_FIRM`; anything else is rejected with
    `ERR_NOT_AN_AUDITOR_FIRM`."

    "Third, the audit firm may not be the same provider that prepared the return:
    when the named `audit_firm_service_provider_id` equals the filing's recorded
    `prepared_by_user_id`, the attestation is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    "Then come the three independence rules of §2.10 in their stated order —
    `ERR_NOT_AN_AUDITOR_FIRM`, then `ERR_AUDITOR_NOT_INDEPENDENT`, then
    `ERR_SEGREGATION_OF_DUTIES`."

    "A `QUALIFIED` opinion is acceptable; only a disclaimer blocks the filing."

    "The filing then moves to `PARTIALLY_CLEARED` if the employer-data branch has not
    yet cleared — that is, if `employer_data_certified_at` is still null — and
    straight to `READY_TO_FILE` if it has."

    Design: Corner/errors/corner_attest_and_file_guards_rejected
    """
    _big_employer(
        api, plan, OVER_THRESHOLD_LEGAL_NAME, OVER_THRESHOLD_EIN,
        OVER_THRESHOLD_SIGNATORY, 1200, 200,
    )
    preparing_firm = fixtures.audit_firm(api, plan)
    attesting_firm = fixtures.audit_firm(
        api, plan, legal_name=k.AUDITOR_SECOND_LEGAL_NAME
    )

    filing = fixtures.draft_filing(api, plan)
    prepared = validate_single(
        api.prepare_plan_filing(
            filing["id"], service_provider_headers(preparing_firm["id"])
        )
    )
    assert_fields(
        prepared,
        filing_status=k.FILING_PREPARED,
        audit_required=True,
        prepared_by_user_id=preparing_firm["id"],
    )
    certified = _certify(api, plan, filing)
    assert_fields(
        certified,
        filing_status=k.FILING_PARTIALLY_CLEARED,
        certified_employer_count=1,
        version=3,
    )

    validate_error(
        _attest(api, filing, plan.recordkeeper_id),
        ERR_NOT_AN_AUDITOR_FIRM,
        expected_status=409,
    )
    validate_error(
        _attest(api, filing, preparing_firm["id"]),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=409,
    )
    still_open = validate_single(
        api.get_plan_filing(filing["id"], regulator_headers())
    )
    assert_fields(
        still_open, filing_status=k.FILING_PARTIALLY_CLEARED, version=3
    )
    assert_null_fields(still_open, "audit_attested_at", "audit_opinion")

    attested = validate_single(
        _attest(api, filing, attesting_firm["id"], k.OPINION_DISCLAIMER)
    )
    assert_fields(
        attested,
        filing_status=k.FILING_READY_TO_FILE,
        audit_opinion=k.OPINION_DISCLAIMER,
        audit_firm_service_provider_id=attesting_firm["id"],
        version=4,
    )
    assert_instant_equals(
        attested["audit_attested_at"], k.DEFAULT_CLOCK, "audit_attested_at"
    )

    validate_error(
        api.file_plan_filing(filing["id"], regulator_headers()),
        ERR_AUDIT_OPINION_UNACCEPTABLE,
        expected_status=409,
    )
    stuck = validate_single(api.get_plan_filing(filing["id"], regulator_headers()))
    assert_fields(
        stuck,
        filing_status=k.FILING_READY_TO_FILE,
        version=4,
        filing_deadline_date=FILING_DEADLINE_DATE,
    )
    assert_null_fields(stuck, "filed_date", "acknowledgment_reference")


def test_independence_is_judged_before_the_bond_on_a_doubly_defective_attestation(
    api: ApiClient,
):
    """
    One attestation violates the independence rule and the bond rule at the same
    time, and the answer is the independence rule; removing that violation alone
    then exposes the bond shortfall underneath it.

    "Second, the named audit firm may hold no fiduciary role allocation on the plan in
    `ALLOCATED` status, and may not be linked by `affiliated_service_provider_id` in
    either direction — neither naming, nor being named by — a provider that holds one;
    a violation is rejected with `ERR_AUDITOR_NOT_INDEPENDENT`."

    "Last, the plan's bond must actually be adequate: the sponsoring provider's
    `fidelity_bond_amount_cents` must be at least the filing's computed
    `fidelity_bond_minimum_cents`, and a shortfall is rejected with
    `ERR_FIDELITY_BOND_INSUFFICIENT`."

    "`fidelity_bond_minimum_cents` is the minimum ERISA section 412 bond the plan
    requires: take the plan document's `total_assets_cents`, multiply by one tenth and
    round half up to whole cents, then raise the result to 100000 cents if it falls
    below that floor and cap it at 100000000 cents if it exceeds that ceiling."

    "A firm's `holds_fiduciary_role` is true exactly when at least one allocation
    naming it is in `ALLOCATED` status."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_auditor_independence_beats_fidelity_bond_on_attest
    """
    plan = _plan_with_bond(api, k.FIDELITY_BOND_FLOOR_CENTS)
    conflicted_firm = fixtures.audit_firm(api, plan)
    clean_firm = fixtures.audit_firm(api, plan, legal_name=k.AUDITOR_SECOND_LEGAL_NAME)
    fixtures.allocate_role(
        api, plan, conflicted_firm["id"], k.FIDUCIARY_INVESTMENT_MANAGER_3_38
    )
    assert_fields(
        validate_single(
            api.get_service_provider(conflicted_firm["id"], plan.provider_headers)
        ),
        holds_fiduciary_role=True,
    )
    assert_fields(
        validate_single(
            api.get_service_provider(clean_firm["id"], plan.provider_headers)
        ),
        holds_fiduciary_role=False,
    )

    employer = _big_employer(
        api, plan, THRESHOLD_LEGAL_NAME, THRESHOLD_EIN, THRESHOLD_SIGNATORY, 1000, 150
    )
    batch = fixtures.validated_batch(api, employer)
    assert_fields(
        fixtures.posted_deposit(api, employer, batch),
        timeliness_status=k.TIMELINESS_TIMELY,
    )
    assert_fields(
        plan.refresh(api),
        participant_count=1000,
        audit_required=True,
        total_assets_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    # `fidelity_bond_amount_cents` is a field of the sponsoring provider, not of
    # the plan document, so the bond the bond rule reads is asserted on the
    # provider row itself.
    assert_fields(
        validate_single(api.get_plan_provider(plan.provider_id, regulator_headers())),
        fidelity_bond_amount_cents=k.FIDELITY_BOND_FLOOR_CENTS,
    )

    filing = fixtures.draft_filing(api, plan)
    prepared = _prepare(api, plan, filing)
    assert_fields(
        prepared,
        filing_status=k.FILING_PREPARED,
        audit_required=True,
        fidelity_bond_minimum_cents=BOND_MINIMUM_ON_CANONICAL_ASSETS,
    )
    assert prepared["fidelity_bond_minimum_cents"] > k.FIDELITY_BOND_FLOOR_CENTS, (
        "the bond the sponsor carries must be short of the computed minimum for "
        "both rules to be violated at once"
    )

    validate_error(
        _attest(api, filing, conflicted_firm["id"]),
        ERR_AUDITOR_NOT_INDEPENDENT,
        expected_status=409,
    )
    validate_error(
        _attest(api, filing, clean_firm["id"]),
        ERR_FIDELITY_BOND_INSUFFICIENT,
        expected_status=409,
    )
    untouched = validate_single(api.get_plan_filing(filing["id"], auditor_headers()))
    assert_fields(untouched, filing_status=k.FILING_PREPARED, version=2)
    assert_null_fields(
        untouched, "audit_attested_at", "audit_opinion",
        "audit_firm_service_provider_id",
    )


def test_a_filed_return_locks_the_settlements_of_its_own_plan_year_only(
    api: ApiClient, plan
):
    """
    Two settled spin-offs of the same plan differ only in the calendar year their
    money moved, and the filed return for one of those years decides which of them
    can still be unwound.

    "`EXITED` looks terminal and is escaped by exactly one route: explicitly
    unwinding the settlement that produced it."

    "Two worked cases: a gross balance of 8500000 cents for 13 participants under
    `SPINOFF_TO_SINGLE_PLAN` applies 16250 and 250000, leaves nothing unrecovered, and
    transfers 8233750; a gross balance of 100000 cents for 4 participants under the
    same exit type applies 5000 and then only 95000 of the flat fee, leaves 155000
    unrecovered, and transfers nothing at all."

    "On success `employer_data_certified_at` is stamped from the logical clock,
    `certified_by_user_id` is recorded from the acting `X-User-ID`,
    `certified_employer_count` is set to the count of the plan's employers whose
    `adoption_status` is anything other than `EXITED` at that instant, and the filing's
    `version` is incremented by one."

    "The transfer must be in `SETTLED`, failing which it is rejected with
    `ERR_TRANSFER_INVALID_STATE`, and no plan filing of the plan may be `FILED` for the
    plan year containing the transfer's `settled_at`; once the return is in, the
    settlement is history and reversal is rejected with
    `ERR_FILING_ALREADY_SUBMITTED`."

    "On success the transfer moves to `REVERSED`, the employer returns from `EXITED` to
    `SPINOFF_IN_PROGRESS`, its `account_balance_cents` is restored to the
    pre-settlement gross and its `exited_at` is cleared, and every plan control total
    is recomputed so that both `headcount_control_delta` and
    `contribution_control_delta_cents` return to exactly zero with no drift."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_cascade_locked_by_a_filed_return_for_that_plan_year
    """
    palisade = fixtures.active_employer(api, plan)
    quarry = fixtures.second_active_employer(api, plan)
    for emp_ctx, reference in (
        (palisade, k.PALISADE_PAYROLL_REFERENCE),
        (quarry, k.QUARRY_PAYROLL_REFERENCE),
    ):
        batch = fixtures.validated_batch(
            api, emp_ctx, payroll_provider_reference=reference
        )
        fixtures.timely_deposit(api, emp_ctx, batch)
        assert_fields(
            emp_ctx.refresh(api),
            account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
            adoption_status=k.EMPLOYER_ACTIVE,
        )

    inside_the_filed_year = fixtures.settled_exit(api, palisade)
    assert_fields(
        inside_the_filed_year,
        status=k.TRANSFER_SETTLED,
        gross_account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        transferred_participant_count=13,
        admin_recovery_cents=16250,
        flat_exit_fee_cents=250000,
        deductions_applied_cents=266250,
        unrecovered_deduction_cents=0,
        transfer_amount_cents=8233750,
        settled_amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )

    after_the_filed_year = fixtures.settled_exit(
        api,
        quarry,
        settle_clock=QUARRY_SETTLEMENT_CLOCK,
        blackout_start_date=QUARRY_BLACKOUT_START_DATE,
        blackout_end_date=QUARRY_BLACKOUT_END_DATE,
        requested_exit_date=QUARRY_REQUESTED_EXIT_DATE,
    )
    assert_fields(
        after_the_filed_year,
        status=k.TRANSFER_SETTLED,
        gross_account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        transferred_participant_count=15,
        admin_recovery_cents=18750,
        transfer_amount_cents=8231250,
    )
    emptied = plan.refresh(api)
    assert_fields(
        emptied,
        participant_count=0,
        transferred_out_participant_count=28,
        active_employer_count=0,
        audit_required=False,
    )
    assert_plan_control_invariants(emptied)

    filing = fixtures.draft_filing(api, plan)
    _prepare(api, plan, filing)
    certified = _certify(api, plan, filing)
    assert_fields(
        certified,
        filing_status=k.FILING_READY_TO_FILE,
        certified_employer_count=0,
        late_deposit_schedule_h_line_cents=0,
        fidelity_bond_minimum_cents=k.FIDELITY_BOND_FLOOR_CENTS,
    )
    filed = validate_single(api.file_plan_filing(filing["id"], regulator_headers()))
    assert_fields(filed, filing_status=k.FILING_FILED, plan_year=k.PLAN_YEAR)

    validate_error(
        api.reverse_exit_transfer(
            inside_the_filed_year["id"],
            f.reverse_transfer_payload(REVERSAL_REASON),
            plan.provider_headers,
        ),
        ERR_FILING_ALREADY_SUBMITTED,
        expected_status=409,
    )
    assert_fields(
        validate_single(
            api.get_exit_transfer(
                inside_the_filed_year["id"], plan.provider_headers
            )
        ),
        status=k.TRANSFER_SETTLED,
        transfer_amount_cents=8233750,
    )
    assert_fields(
        palisade.refresh(api),
        adoption_status=k.EMPLOYER_EXITED,
        account_balance_cents=0,
    )

    unwound = fixtures.reversed_exit(api, quarry, after_the_filed_year, REVERSAL_REASON)
    assert_fields(
        unwound, status=k.TRANSFER_REVERSED, reversal_reason=REVERSAL_REASON
    )
    assert_fields(
        quarry.refresh(api),
        adoption_status=k.EMPLOYER_SPINOFF_IN_PROGRESS,
        account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_null_fields(quarry.employer, "exited_at")
    assert_plan_control_invariants(plan.refresh(api))
