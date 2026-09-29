"""Admitting adopting employers and reviewing their plan design elections."""

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_CENSUS_INCONSISTENT,
    ERR_ELECTION_INVALID_STATE,
    ERR_ELECTION_WINDOW_CLOSED,
    ERR_ELIGIBILITY_MORE_RESTRICTIVE,
    ERR_EMPLOYER_INVALID_STATE,
    ERR_SIGNATORY_REQUIRED,
    ERR_STALE_EMPLOYER_VERSION,
    ERR_TIER_FIELDS_MISMATCH,
    ERR_TIER_LIMITS_OUT_OF_ORDER,
    ERR_TRANSFER_INVALID_STATE,
    ERR_VESTING_MORE_RESTRICTIVE,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_resource_shape,
    ids_of,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.test_users import regulator_headers
from prd_bench_local_runner.testing import validate_error

RIVERBEND_LEGAL_NAME = "Riverbend Tooling Inc"
RIVERBEND_EIN = "420000043"
RIDGEWAY_SIGNATORY = "K. Ridgeway"


def test_census_arithmetic_is_checked_as_a_unit(api: ApiClient, plan):
    """
    All four census conjuncts are independent, the benefiting comparison is
    inclusive, and only the accepted create moves the plan totals.

    "Census arithmetic is checked as a unit: `benefiting_hce_count` may not
    exceed `hce_count`, `benefiting_nhce_count` may not exceed `nhce_count`,
    `nhce_count` must be at least one, and `hce_count` plus `nhce_count` must
    equal `participant_count` exactly."

    Design: Corner/validations/corner_census_inconsistent_combinations_rejected
    """
    headers = plan.provider_headers

    validate_error(
        api.create_adopting_employer(
            f.adopting_employer_payload(plan.plan_id, benefiting_hce_count=4), headers
        ),
        ERR_CENSUS_INCONSISTENT,
        expected_status=422,
    )
    validate_error(
        api.create_adopting_employer(
            f.adopting_employer_payload(
                plan.plan_id,
                hce_count=13,
                nhce_count=0,
                benefiting_hce_count=13,
                benefiting_nhce_count=0,
                nhce_avg_deferral_pct=0.0,
            ),
            headers,
        ),
        ERR_CENSUS_INCONSISTENT,
        expected_status=422,
    )
    validate_error(
        api.create_adopting_employer(
            f.adopting_employer_payload(plan.plan_id, nhce_count=9), headers
        ),
        ERR_CENSUS_INCONSISTENT,
        expected_status=422,
    )

    admitted = validate_created(
        api.create_adopting_employer(
            f.adopting_employer_payload(plan.plan_id, benefiting_nhce_count=10), headers
        )
    )
    assert_resource_shape(admitted, "AdoptingEmployer")
    assert_fields(
        admitted,
        adoption_status=k.EMPLOYER_APPLIED,
        participant_count=13,
        benefiting_nhce_count=10,
        is_small_plan=True,
        employer_audit_required=False,
    )

    read_plan = plan.refresh(api)
    assert_fields(
        read_plan, participant_count=13, cumulative_enrolled_participant_count=13
    )


def test_plan_employer_listing_counts_the_collection_not_the_page(
    api: ApiClient, plan
):
    """
    total_count spans the whole collection and has_more is derived from the
    window rather than from the page length.

    "List results are ordered by `created_at` ascending unless a specific
    listing states otherwise, so pagination is stable across pages."

    Design: Corner/entities/corner_list_plan_adopting_employers_pagination_envelope
    """
    headers = plan.provider_headers
    palisade = fixtures.applied_employer(api, plan)
    quarry = fixtures.applied_employer(
        api, plan, f.second_adopting_employer_payload(plan.plan_id)
    )
    riverbend = fixtures.applied_employer(
        api,
        plan,
        f.adopting_employer_payload(
            plan.plan_id, legal_name=RIVERBEND_LEGAL_NAME, ein=RIVERBEND_EIN
        ),
    )

    first_page, _ = validate_collection(
        api.list_plan_adopting_employers(plan.plan_id, headers, limit=2, offset=0),
        expected_total=3,
        expected_len=2,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=True,
    )
    second_page, _ = validate_collection(
        api.list_plan_adopting_employers(plan.plan_id, headers, limit=2, offset=2),
        expected_total=3,
        expected_len=1,
        expected_limit=2,
        expected_offset=2,
        expected_has_more=False,
    )

    seen = ids_of(first_page) + ids_of(second_page)
    assert sorted(seen) == sorted(
        [palisade.employer_id, quarry.employer_id, riverbend.employer_id]
    ), f"Each employer must appear exactly once across the two pages, got {seen}"

    whole, meta = validate_collection(
        api.list_plan_adopting_employers(plan.plan_id, regulator_headers()),
        expected_total=3,
        expected_len=3,
        expected_limit=k.DEFAULT_LIMIT,
        expected_offset=0,
        expected_has_more=False,
    )
    assert_created_at_ascending(whole)


def test_tier_fields_are_required_only_for_the_tiered_formula(api: ApiClient, plan):
    """
    The tier-field rule forbids as well as requires, and the ordering rule below
    it only becomes reachable once all four fields are present.

    "Either half of that rule failing — a tiered election missing a tier field,
    or a non-tiered election supplying one — is rejected with
    `ERR_TIER_FIELDS_MISMATCH`."

    "the two limit fields `match_tier_1_limit_pct` and `match_tier_2_limit_pct`
    are percentages of eligible compensation between 0.00 and 15.00, and the
    second tier's limit must be greater than or equal to the first tier's limit,
    failing which the request is rejected with `ERR_TIER_LIMITS_OUT_OF_ORDER`."

    Design: Corner/validations/corner_tier_fields_required_only_for_discretionary_tiered
    """
    emp_ctx = fixtures.applied_employer(api, plan)
    headers = emp_ctx.headers
    token = emp_ctx.employer_version

    validate_error(
        api.create_design_election(
            f.design_election_payload(
                emp_ctx.employer_id,
                token,
                match_tier_1_pct=100.0,
                match_tier_1_limit_pct=3.0,
                match_tier_2_pct=25.0,
                match_tier_2_limit_pct=6.0,
            ),
            headers,
        ),
        ERR_TIER_FIELDS_MISMATCH,
        expected_status=422,
    )
    validate_error(
        api.create_design_election(
            f.design_election_payload(
                emp_ctx.employer_id,
                token,
                match_formula_code=k.MATCH_DISCRETIONARY_TIERED,
                match_tier_1_pct=100.0,
                match_tier_1_limit_pct=3.0,
            ),
            headers,
        ),
        ERR_TIER_FIELDS_MISMATCH,
        expected_status=422,
    )
    validate_error(
        api.create_design_election(
            f.tiered_design_election_payload(
                emp_ctx.employer_id, token, 100.0, 3.0, 25.0, 2.0
            ),
            headers,
        ),
        ERR_TIER_LIMITS_OUT_OF_ORDER,
        expected_status=422,
    )

    accepted = validate_created(
        api.create_design_election(
            f.tiered_design_election_payload(
                emp_ctx.employer_id, token, 100.0, 3.0, 25.0, 3.0
            ),
            headers,
        )
    )
    assert_fields(
        accepted,
        status=k.ELECTION_DRAFT,
        match_formula_code=k.MATCH_DISCRETIONARY_TIERED,
        nondiscrimination_track=k.TRACK_ADP_ACP_TESTED,
        election_sequence=1,
    )
    assert_null_fields(accepted, "signatory_name", "return_reason", "deficiency_code",
                       "approved_at")


def test_blank_signatory_at_submit_is_rejected(api: ApiClient, plan):
    """
    Blankness is checked beyond mere presence, and the refused submit leaves both
    rows where they were.

    "The payload carries `signatory_name`, the name of the employer signatory,
    which is required and may not be blank; its absence is rejected with
    `ERR_SIGNATORY_REQUIRED`."

    Design: Corner/validations/corner_blank_signatory_at_submit_rejected
    """
    emp_ctx = fixtures.applied_employer(api, plan)
    election = fixtures.drafted_election(api, emp_ctx)
    headers = emp_ctx.headers

    validate_error(
        api.submit_design_election(
            election["id"], f.submit_election_payload(""), headers
        ),
        ERR_SIGNATORY_REQUIRED,
        expected_status=422,
    )
    validate_error(
        api.submit_design_election(
            election["id"], f.submit_election_payload("   "), headers
        ),
        ERR_SIGNATORY_REQUIRED,
        expected_status=422,
    )

    untouched = validate_single(api.get_design_election(election["id"], headers))
    assert_fields(untouched, status=k.ELECTION_DRAFT, version=election["version"])
    assert_null_fields(untouched, "signatory_name")
    assert_fields(emp_ctx.refresh(api), adoption_status=k.EMPLOYER_APPLIED)

    submitted = validate_single(
        api.submit_design_election(
            election["id"], f.submit_election_payload(k.PALISADE_SIGNATORY), headers
        )
    )
    assert_fields(
        submitted, status=k.ELECTION_SUBMITTED, signatory_name=k.PALISADE_SIGNATORY
    )
    assert_fields(
        emp_ctx.refresh(api), adoption_status=k.EMPLOYER_ELECTIONS_SUBMITTED
    )


def test_returned_election_resubmits_without_advancing_the_sequence(
    api: ApiClient, plan
):
    """
    The review loop runs backwards and forwards on one row, clearing the return
    fields on the way back and dragging the employer with it.

    "Submitting an election moves it from `DRAFT` to `SUBMITTED`, or from
    `RETURNED` back to `SUBMITTED`, and drags the employer to
    `ELECTIONS_SUBMITTED` in either case — from `APPLIED` on a first submission
    and from `RETURNED_FOR_REVISION` on a resubmission, which is the cycle edge
    `ELECTIONS_SUBMITTED → RETURNED_FOR_REVISION → ELECTIONS_SUBMITTED` that may
    repeat indefinitely."

    "Because a replacement is a fresh row, `election_sequence` advances on
    replacement but never on resubmission of the same row."

    Design: Difficulty/non_linear_state_machine/election_submitted_returned_resubmitted_then_replaced_cycle
    """
    emp_ctx = fixtures.applied_employer(api, plan)
    election = fixtures.submitted_election(api, emp_ctx)

    returned = validate_single(
        api.return_design_election(
            election["id"],
            f.return_election_payload(
                "Tier fields absent for the elected formula.",
                k.DEFICIENCY_TIER_MISMATCH,
            ),
            plan.provider_headers,
        )
    )
    assert_fields(
        returned,
        status=k.ELECTION_RETURNED,
        return_reason="Tier fields absent for the elected formula.",
        deficiency_code=k.DEFICIENCY_TIER_MISMATCH,
        election_sequence=1,
    )
    assert_fields(
        emp_ctx.refresh(api), adoption_status=k.EMPLOYER_RETURNED_FOR_REVISION
    )

    resubmitted = validate_single(
        api.submit_design_election(
            election["id"],
            f.submit_election_payload(k.PALISADE_SIGNATORY),
            emp_ctx.headers,
        )
    )
    assert_fields(
        resubmitted,
        status=k.ELECTION_SUBMITTED,
        election_sequence=1,
        signatory_name=k.PALISADE_SIGNATORY,
    )
    assert_null_fields(resubmitted, "return_reason", "deficiency_code")
    assert_fields(
        emp_ctx.refresh(api), adoption_status=k.EMPLOYER_ELECTIONS_SUBMITTED
    )


def test_replacement_election_supersedes_the_loop_and_rewinds_the_employer(
    api: ApiClient, plan
):
    """
    A replacement is a sideways edge out of the loop: it supersedes the in-flight
    row, rewinds the employer all the way to APPLIED and takes the next sequence
    number.

    "Creation is also a **reset**: any prior election of the same employer whose
    `status` is `DRAFT`, `SUBMITTED` or `RETURNED` moves to `SUPERSEDED` and has
    its `version` incremented, and if the employer was sitting in
    `ELECTIONS_SUBMITTED` or `RETURNED_FOR_REVISION` it returns to `APPLIED`,
    because the in-flight election that put it there no longer exists."

    "The only edge out of `APPROVED` is `APPROVED → SUPERSEDED`, driven by the
    settlement of that employer's exit; a new election can never displace an
    approved one, because an `ACTIVE` employer may not create one."

    Design: Difficulty/non_linear_state_machine/election_submitted_returned_resubmitted_then_replaced_cycle
    """
    emp_ctx = fixtures.applied_employer(api, plan)
    first = fixtures.submitted_election(api, emp_ctx)
    validate_single(
        api.return_design_election(
            first["id"],
            f.return_election_payload(
                "Tier fields absent for the elected formula.",
                k.DEFICIENCY_TIER_MISMATCH,
            ),
            plan.provider_headers,
        )
    )
    validate_single(
        api.submit_design_election(
            first["id"],
            f.submit_election_payload(k.PALISADE_SIGNATORY),
            emp_ctx.headers,
        )
    )

    replacement = fixtures.drafted_election(
        api,
        emp_ctx,
        vesting_schedule=k.VESTING_GRADED_2_6,
        match_formula_code=k.MATCH_SAFE_HARBOR_ENHANCED,
    )
    assert_fields(
        replacement,
        status=k.ELECTION_DRAFT,
        election_sequence=2,
        nondiscrimination_track=k.TRACK_SAFE_HARBOR_EXEMPT,
    )
    assert_fields(
        validate_single(api.get_design_election(first["id"], emp_ctx.headers)),
        status=k.ELECTION_SUPERSEDED,
    )
    assert_fields(emp_ctx.refresh(api), adoption_status=k.EMPLOYER_APPLIED)

    validate_single(
        api.submit_design_election(
            replacement["id"],
            f.submit_election_payload(k.PALISADE_SIGNATORY),
            emp_ctx.headers,
        )
    )
    approved = validate_single(
        api.approve_design_election(replacement["id"], plan.provider_headers)
    )
    assert_fields(approved, status=k.ELECTION_APPROVED, election_sequence=2)
    assert_fields(emp_ctx.refresh(api), adoption_status=k.EMPLOYER_ACTIVE)
    assert_fields(
        validate_single(api.get_design_election(first["id"], emp_ctx.headers)),
        status=k.ELECTION_SUPERSEDED,
    )


def test_approval_lands_side_effects_on_election_employer_and_plan(
    api: ApiClient, plan
):
    """
    One approve call has to move three rows at once, and the plan's headcount
    control delta must come back to zero.

    "On success the election moves from `SUBMITTED` to `APPROVED` with
    `approved_at` stamped from the logical clock, the employer advances from
    `ELECTIONS_SUBMITTED` to `ACTIVE` with `effective_adoption_date` set to the
    logical-clock calendar date, the plan document's `active_employer_count` is
    recomputed, and both the election's and the employer's `version` are
    incremented by one."

    "Two flags are derived from the census immediately: `is_small_plan` is true
    when the employer's `participant_count` is below 100, which is what selects
    the seven-business-day deposit safe harbour for that employer's payroll, and
    `employer_audit_required` is true when `participant_count` is 100 or more,
    meaning the employer must supply audited employer-level financial data for
    the plan's return."

    Design: Corner/state_machines/corner_election_approval_side_effects_on_employer_and_plan
    """
    emp_ctx = fixtures.applied_employer(api, plan)
    election = fixtures.submitted_election(api, emp_ctx)

    approved = validate_single(
        api.approve_design_election(election["id"], plan.provider_headers)
    )
    assert_fields(
        approved,
        status=k.ELECTION_APPROVED,
        election_sequence=1,
        nondiscrimination_track=k.TRACK_SAFE_HARBOR_EXEMPT,
    )
    assert_instant_equals(approved["approved_at"], k.DEFAULT_CLOCK, "approved_at")

    employer = emp_ctx.refresh(api)
    assert_fields(
        employer,
        adoption_status=k.EMPLOYER_ACTIVE,
        effective_adoption_date=k.DEFAULT_CLOCK_DATE,
        is_small_plan=True,
        employer_audit_required=False,
    )

    read_plan = plan.refresh(api)
    assert_fields(
        read_plan,
        active_employer_count=1,
        suspended_employer_count=0,
        compliance_posture=k.POSTURE_OPEN,
        participant_count=13,
        cumulative_enrolled_participant_count=13,
        transferred_out_participant_count=0,
        headcount_control_delta=0,
        audit_required=False,
        total_validated_contributions_cents=0,
        total_assets_cents=0,
        aggregate_receivable_cents=0,
    )


WINDOW_CLOSE_DAY_CLOCK = "2026-09-30T09:00:00Z"
DAY_AFTER_WINDOW_CLOCK = "2026-10-01T09:00:00Z"


def test_generosity_floors_and_the_window_gate_are_separate_refusals(api: ApiClient):
    """
    An employer may be more generous than the common structure but never
    stricter, on any of the three dimensions, and the window comparison includes
    its closing day.

    "Then the employer's eligibility terms must be no more restrictive than the
    common structure: `eligibility_min_age` must be at most the plan document's
    `base_eligibility_min_age` and `eligibility_service_months` at most its
    `base_eligibility_service_months`, so an employer may always be *more*
    generous than the plan but never stricter; a violation of either is rejected
    with `ERR_ELIGIBILITY_MORE_RESTRICTIVE`."

    "Finally the elected vesting schedule must be at least as generous as the
    plan's base schedule, measured on a generosity rank where `IMMEDIATE` is 0,
    `GRADED_2_6` is 1 and `CLIFF_3YR` is 2: the rank of the election's
    `vesting_schedule` must be at most the rank of the plan's
    `base_vesting_schedule`, and a higher rank is rejected with
    `ERR_VESTING_MORE_RESTRICTIVE`."

    "It must land inside the employer's election window: the logical-clock
    calendar date must be on or before the employer's
    `election_window_close_date`, and a submission on a later date is rejected
    with `ERR_ELECTION_WINDOW_CLOSED`."

    Design: Corner/errors/corner_election_generosity_and_window_gates_rejected
    """
    plan = fixtures.active_plan(
        api,
        base_eligibility_min_age=18,
        base_eligibility_service_months=0,
        base_vesting_schedule=k.VESTING_IMMEDIATE,
    )
    provider_headers = plan.provider_headers

    palisade = fixtures.applied_employer(api, plan)
    quarry = fixtures.applied_employer(
        api, plan, f.second_adopting_employer_payload(plan.plan_id)
    )
    riverbend = fixtures.applied_employer(
        api,
        plan,
        f.adopting_employer_payload(
            plan.plan_id, legal_name=RIVERBEND_LEGAL_NAME, ein=RIVERBEND_EIN
        ),
    )

    older = fixtures.submitted_election(
        api,
        palisade,
        eligibility_min_age=21,
        eligibility_service_months=0,
        vesting_schedule=k.VESTING_IMMEDIATE,
    )
    validate_error(
        api.approve_design_election(older["id"], provider_headers),
        ERR_ELIGIBILITY_MORE_RESTRICTIVE,
        expected_status=409,
    )

    longer = fixtures.submitted_election(
        api,
        quarry,
        signatory_name=k.QUARRY_SIGNATORY,
        eligibility_min_age=18,
        eligibility_service_months=12,
        vesting_schedule=k.VESTING_IMMEDIATE,
    )
    validate_error(
        api.approve_design_election(longer["id"], provider_headers),
        ERR_ELIGIBILITY_MORE_RESTRICTIVE,
        expected_status=409,
    )

    slower = fixtures.submitted_election(
        api,
        riverbend,
        signatory_name=RIDGEWAY_SIGNATORY,
        eligibility_min_age=18,
        eligibility_service_months=0,
        vesting_schedule=k.VESTING_GRADED_2_6,
    )
    validate_error(
        api.approve_design_election(slower["id"], provider_headers),
        ERR_VESTING_MORE_RESTRICTIVE,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_design_election(slower["id"], riverbend.headers)),
        status=k.ELECTION_SUBMITTED,
    )
    assert_fields(
        riverbend.refresh(api), adoption_status=k.EMPLOYER_ELECTIONS_SUBMITTED
    )
    assert_null_fields(riverbend.employer, "effective_adoption_date")

    repaired = fixtures.submitted_election(
        api,
        riverbend,
        signatory_name=RIDGEWAY_SIGNATORY,
        eligibility_min_age=18,
        eligibility_service_months=0,
        vesting_schedule=k.VESTING_IMMEDIATE,
    )
    approved = validate_single(
        api.approve_design_election(repaired["id"], provider_headers)
    )
    assert_fields(approved, status=k.ELECTION_APPROVED, election_sequence=2)
    assert_fields(riverbend.refresh(api), adoption_status=k.EMPLOYER_ACTIVE)

    fixtures.set_clock(api, WINDOW_CLOSE_DAY_CLOCK)
    on_the_closing_day = fixtures.drafted_election(
        api,
        palisade,
        eligibility_min_age=18,
        eligibility_service_months=0,
        vesting_schedule=k.VESTING_IMMEDIATE,
    )
    assert_fields(
        validate_single(
            api.submit_design_election(
                on_the_closing_day["id"],
                f.submit_election_payload(k.PALISADE_SIGNATORY),
                palisade.headers,
            )
        ),
        status=k.ELECTION_SUBMITTED,
    )

    fixtures.set_clock(api, DAY_AFTER_WINDOW_CLOCK)
    too_late = fixtures.drafted_election(
        api,
        quarry,
        eligibility_min_age=18,
        eligibility_service_months=0,
        vesting_schedule=k.VESTING_IMMEDIATE,
    )
    validate_error(
        api.submit_design_election(
            too_late["id"], f.submit_election_payload(k.QUARRY_SIGNATORY), quarry.headers
        ),
        ERR_ELECTION_WINDOW_CLOSED,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_design_election(too_late["id"], quarry.headers)),
        status=k.ELECTION_DRAFT,
        version=too_late["version"],
    )
    assert_fields(quarry.refresh(api), adoption_status=k.EMPLOYER_APPLIED)


def test_actions_aimed_at_the_wrong_state_are_refused_and_change_nothing(
    api: ApiClient, plan, employer
):
    """
    Every trigger checks its own row's state first, and a refused trigger leaves
    both the row and its counterparty exactly as they were.

    "Four checks apply in order: the transfer must be in `APPROVED`, failing
    which it is rejected with `ERR_TRANSFER_INVALID_STATE`; the logical-clock
    calendar date must be strictly after `blackout_end_date`, since assets cannot
    move while the blackout is still open, and a settlement on or before that
    date is rejected with `ERR_BLACKOUT_NOT_ENDED`; the employer must carry no
    `POSTED` deposit whose `timeliness_status` is `LATE` or
    `CORRECTION_COMPUTED`, failing which it is rejected with
    `ERR_OPEN_LATE_DEPOSIT_CORRECTION`; and the employer must have no payroll
    batch left in `VALIDATED` status awaiting remittance, failing which it is
    rejected with `ERR_UNREMITTED_CONTRIBUTIONS`."

    "Submission from any status other than `DRAFT` or `RETURNED` is rejected with
    `ERR_ELECTION_INVALID_STATE`."

    Design: Corner/state_machines/corner_transfer_and_election_actions_from_wrong_state_rejected
    """
    transfer = fixtures.requested_exit(api, employer)
    assert_fields(transfer, status=k.TRANSFER_REQUESTED)

    validate_error(
        api.settle_exit_transfer(transfer["id"], plan.provider_headers),
        ERR_TRANSFER_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.reverse_exit_transfer(
            transfer["id"],
            f.reverse_transfer_payload("Requested in error."),
            plan.provider_headers,
        ),
        ERR_TRANSFER_INVALID_STATE,
        expected_status=409,
    )

    election_id = employer.election_id
    validate_error(
        api.submit_design_election(
            election_id, f.submit_election_payload(k.PALISADE_SIGNATORY), employer.headers
        ),
        ERR_ELECTION_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.return_design_election(
            election_id,
            f.return_election_payload(
                "Please revisit the vesting schedule.", k.DEFICIENCY_VESTING_TOO_RESTRICTIVE
            ),
            plan.provider_headers,
        ),
        ERR_ELECTION_INVALID_STATE,
        expected_status=409,
    )

    still_requested = validate_single(
        api.get_exit_transfer(transfer["id"], employer.headers)
    )
    assert_fields(
        still_requested, status=k.TRANSFER_REQUESTED, version=transfer["version"]
    )
    assert_null_fields(
        still_requested, "approved_at", "settled_at", "reversal_reason"
    )

    still_approved = validate_single(api.get_design_election(election_id, employer.headers))
    assert_fields(still_approved, status=k.ELECTION_APPROVED)
    assert_null_fields(still_approved, "return_reason", "deficiency_code")
    assert_fields(employer.refresh(api), adoption_status=k.EMPLOYER_EXIT_REQUESTED)


def test_each_accepted_write_burns_the_employer_version_token(api: ApiClient, plan):
    """
    The token is single-use: every accepted write advances the employer, so a
    replayed token is refused, and the refusal outranks the employer's own state
    precondition.

    "If that value does not equal the employer's current `version`, the create is
    rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412)."

    "A successful create advances the employer's `version`, so a second create
    still carrying the previously observed value is rejected."

    "Priorities 8 and 9 are the two optimistic-concurrency checks of §2.7:
    `ERR_STALE_EMPLOYER_VERSION` then `ERR_STALE_PLAN_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_employer_version_rejected_and_token_lifetime
    """
    emp_ctx = fixtures.applied_employer(api, plan)
    stale_token = emp_ctx.employer_version

    first = validate_created(
        api.create_design_election(
            f.design_election_payload(emp_ctx.employer_id, stale_token), emp_ctx.headers
        )
    )
    assert_fields(first, status=k.ELECTION_DRAFT, election_sequence=1)

    validate_error(
        api.create_design_election(
            f.design_election_payload(emp_ctx.employer_id, stale_token), emp_ctx.headers
        ),
        ERR_STALE_EMPLOYER_VERSION,
        expected_status=412,
    )
    validate_collection(
        api.list_employer_design_elections(emp_ctx.employer_id, emp_ctx.headers),
        expected_total=1,
    )
    assert_fields(
        validate_single(api.get_design_election(first["id"], emp_ctx.headers)),
        status=k.ELECTION_DRAFT,
        version=first["version"],
    )

    fresh_token = emp_ctx.refresh(api)["version"]
    assert fresh_token != stale_token, (
        "An accepted election create must advance the employer's version"
    )
    replacement = validate_created(
        api.create_design_election(
            f.design_election_payload(emp_ctx.employer_id, fresh_token), emp_ctx.headers
        )
    )
    assert_fields(replacement, status=k.ELECTION_DRAFT, election_sequence=2)
    assert_fields(
        validate_single(api.get_design_election(first["id"], emp_ctx.headers)),
        status=k.ELECTION_SUPERSEDED,
    )

    validate_single(
        api.submit_design_election(
            replacement["id"],
            f.submit_election_payload(k.PALISADE_SIGNATORY),
            emp_ctx.headers,
        )
    )
    validate_single(api.approve_design_election(replacement["id"], plan.provider_headers))
    active_token = emp_ctx.refresh(api)["version"]

    validate_error(
        api.create_design_election(
            f.design_election_payload(emp_ctx.employer_id, stale_token), emp_ctx.headers
        ),
        ERR_STALE_EMPLOYER_VERSION,
        expected_status=412,
    )
    validate_error(
        api.create_design_election(
            f.design_election_payload(emp_ctx.employer_id, active_token), emp_ctx.headers
        ),
        ERR_EMPLOYER_INVALID_STATE,
        expected_status=409,
    )
