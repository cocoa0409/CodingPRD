"""Fee disclosures: the net plan expense, the two allocation variants and the guards."""

from typing import Any, Dict

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INVALID_DISCLOSURE_PERIOD,
    ERR_NO_BILLABLE_SERVICE_PROVIDER,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_percentage,
    assert_resource_shape,
    assert_same_object,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from prd_bench_local_runner.testing import validate_error

# Two consecutive quarters of the plan year, and the whole second half.
FIRST_QUARTER_START = "2026-01-01"
FIRST_QUARTER_END = "2026-03-31"
SECOND_QUARTER_START = "2026-04-01"
SECOND_QUARTER_END = "2026-06-30"
SECOND_HALF_START = "2026-07-01"
SECOND_HALF_END = "2026-12-31"

# Three pools: one large enough to extinguish the rebated expense, one that only
# dents it, and one small enough to leave most of the expense standing.
FULL_POOL_CENTS = 1000000
PARTIAL_POOL_CENTS = 300000
SMALL_POOL_CENTS = 50000

# 17 participants at 40000 + 20000 per participant, and the figures the two-tier
# schedule then produces.
GROSS_ON_SEVENTEEN = 1020000
TIER_TWO_REBATE_PCT = 2.0
REBATED_ON_SEVENTEEN = 999600
OFFSET_FIRST_WOULD_YIELD = 20000

# The second employer's census: four participants, one of them highly compensated.
SMALL_PARTICIPANT_COUNT = 4
SMALL_HCE_COUNT = 1
SMALL_NHCE_COUNT = 3

PER_CAPITA_TOTAL_BASIS = 17
PALISADE_PER_CAPITA_PCT = 76.47
QUARRY_PER_CAPITA_PCT = 23.53


def _small_second_employer(api: ApiClient, plan: PlanContext) -> EmployerContext:
    """A second ACTIVE employer with a four-participant census."""
    return fixtures.second_active_employer(
        api,
        plan,
        participant_count=SMALL_PARTICIPANT_COUNT,
        hce_count=SMALL_HCE_COUNT,
        nhce_count=SMALL_NHCE_COUNT,
        benefiting_hce_count=SMALL_HCE_COUNT,
        benefiting_nhce_count=SMALL_NHCE_COUNT,
    )


def _zero_fee_plan(api: ApiClient) -> PlanContext:
    """
    An ACTIVE plan whose two engaged providers both charge nothing per participant.

    Activation only requires the two acknowledged fiduciary functions, so a plan
    can satisfy every activation precondition and still have no billable provider.
    """
    provider = fixtures.registered_provider(api)
    plan = fixtures.draft_plan(api, provider)
    recordkeeper = fixtures.engage_provider(
        api,
        provider["id"],
        f.recordkeeper_payload(plan["id"], direct_fee_cents_per_participant=0),
    )
    trustee = fixtures.engage_provider(
        api,
        provider["id"],
        f.trustee_payload(plan["id"], direct_fee_cents_per_participant=0),
    )
    plan_ctx = PlanContext(
        provider=provider, plan=plan, recordkeeper=recordkeeper, trustee=trustee
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
        fixtures.allocate_role(api, plan_ctx, trustee["id"], k.FIDUCIARY_TRUSTEE_403A),
        k.TRUSTEE_ACKNOWLEDGMENT,
    )
    plan_ctx.plan = validate_single(
        api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    )
    return plan_ctx


def _disclose(api: ApiClient, plan: PlanContext, **overrides: Any) -> Dict[str, Any]:
    """Issue one fee disclosure as the plan's sponsor and return its payload."""
    return validate_created(
        api.create_fee_disclosure(
            f.fee_disclosure_payload(plan.plan_id, **overrides), plan.provider_headers
        )
    )


def _assert_line(
    line: Dict[str, Any],
    adopting_employer_id: str,
    basis_amount: int,
    basis_share_pct: float,
    credit_cents: int,
    residual_awarded: int,
) -> None:
    """Assert one allocation line field for field."""
    assert_fields(
        line,
        adopting_employer_id=adopting_employer_id,
        basis_amount=basis_amount,
        credit_cents=credit_cents,
        residual_awarded=residual_awarded,
    )
    assert_percentage(line["basis_share_pct"], basis_share_pct, "basis_share_pct")


def test_the_tier_is_read_off_the_gross_before_the_pool_is_ever_subtracted(
    api: ApiClient, plan: PlanContext, employer: EmployerContext
):
    """
    Two disclosures over the same seventeen-participant population differ only in
    the size of the pool, and both prove the pinned order: the rebate tier is chosen
    from the gross, so a pool large enough to extinguish the expense still cannot
    change the tier that produced it.

    "`gross_direct_fees_cents` is the plan document's `participant_count` multiplied
    by the sum of `direct_fee_cents_per_participant` over *every* service provider
    whose `plan_document_id` is this plan, regardless of that provider's
    `provider_type` and regardless of whether it holds a fiduciary role"

    "`expense_rebate_pct` is then selected by a two-tier schedule read off the gross
    figure: 5.0 when `gross_direct_fees_cents` is at least 5000000 cents, 2.0 when it
    is at least 1000000 cents, and 0.0 below that."

    "With a gross of 1020000 cents and a pool of 1000000 cents, reading the tier off
    the gross selects 2.0 percent, produces a rebate of 20400, a rebated amount of
    999600, an offset of 999600 and a `net_plan_expense_cents` of 0."

    "Offsetting first would leave 20000, select the 0.0 percent tier, and report
    20000 instead."

    "Finally, each named employer's `revenue_sharing_credit_cents` increases by its
    `credit_cents`, so that field is a running lifetime total across every disclosure
    the plan has ever issued rather than a single-period figure."

    Design: Difficulty/combinatorial_formula/net_plan_expense_gross_tier_then_rebate_then_offset
    """
    quarry = _small_second_employer(api, plan)
    assert_fields(plan.refresh(api), participant_count=PER_CAPITA_TOTAL_BASIS)

    extinguished = _disclose(
        api,
        plan,
        disclosure_period_start=FIRST_QUARTER_START,
        disclosure_period_end=FIRST_QUARTER_END,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=FULL_POOL_CENTS,
    )
    assert_fields(
        extinguished,
        gross_direct_fees_cents=GROSS_ON_SEVENTEEN,
        revenue_sharing_offset_cents=REBATED_ON_SEVENTEEN,
        net_plan_expense_cents=0,
        eligible_employer_count=2,
        total_revenue_sharing_allocated_cents=FULL_POOL_CENTS,
        residual_cents_distributed=1,
    )
    assert_percentage(
        extinguished["expense_rebate_pct"], TIER_TWO_REBATE_PCT, "expense_rebate_pct"
    )
    assert extinguished["net_plan_expense_cents"] != OFFSET_FIRST_WOULD_YIELD, (
        "netting the pool off the gross before the tier was chosen would report "
        "20000 on this population"
    )
    lines = extinguished["allocation_lines"]
    assert len(lines) == 2, f"Expected one line per eligible employer, got {lines}"
    _assert_line(
        lines[0], employer.employer_id, 13, PALISADE_PER_CAPITA_PCT, 764706, 1
    )
    _assert_line(
        lines[1],
        quarry.employer_id,
        SMALL_PARTICIPANT_COUNT,
        QUARRY_PER_CAPITA_PCT,
        235294,
        0,
    )

    dented = _disclose(
        api,
        plan,
        disclosure_period_start=SECOND_QUARTER_START,
        disclosure_period_end=SECOND_QUARTER_END,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=PARTIAL_POOL_CENTS,
    )
    assert_fields(
        dented,
        gross_direct_fees_cents=GROSS_ON_SEVENTEEN,
        revenue_sharing_offset_cents=PARTIAL_POOL_CENTS,
        net_plan_expense_cents=699600,
        total_revenue_sharing_allocated_cents=PARTIAL_POOL_CENTS,
        residual_cents_distributed=1,
    )
    assert_percentage(
        dented["expense_rebate_pct"], TIER_TWO_REBATE_PCT, "expense_rebate_pct"
    )
    _assert_line(
        dented["allocation_lines"][0],
        employer.employer_id,
        13,
        PALISADE_PER_CAPITA_PCT,
        229412,
        1,
    )
    _assert_line(
        dented["allocation_lines"][1],
        quarry.employer_id,
        SMALL_PARTICIPANT_COUNT,
        QUARRY_PER_CAPITA_PCT,
        70588,
        0,
    )

    assert_fields(employer.refresh(api), revenue_sharing_credit_cents=994118)
    assert_fields(quarry.refresh(api), revenue_sharing_credit_cents=305882)


def test_the_two_allocation_methods_redistribute_the_same_pool_differently(
    api: ApiClient, plan: PlanContext, employer: EmployerContext
):
    """
    An identical population and an identical pool diverge on the allocation method
    alone: assets hand everything to the only employer holding a balance, headcount
    splits it seventeen ways with a single residual cent, and neither resizes the
    pool.

    "Each eligible employer's basis is its `account_balance_cents` under
    `PRO_RATA_ASSETS` and its `participant_count` under `PER_CAPITA`."

    "Otherwise each employer's raw share is `revenue_sharing_pool_cents` multiplied
    by its basis divided by the total basis, kept exact and then floored to whole
    cents, with the fractional part retained for ranking; its `basis_share_pct` is
    its basis multiplied by 100 divided by the total basis, rounded half up to two
    decimal places."

    "The eligible employers are ranked by fractional remainder descending, ties
    broken by `created_at` ascending and never by `id`, and one extra cent goes to
    each of the first `residual` employers in that ranking, recorded as
    `residual_awarded` of 1 on the winners and 0 on everyone else."

    "Every eligible employer gets a line even when its credit is zero: a zero-balance
    employer under `PRO_RATA_ASSETS` appears with a `basis_amount` of 0, a
    `basis_share_pct` of 0.00 and a `credit_cents` of 0."

    "the array is ordered by `credit_cents` descending, ties broken by the named
    employer's `created_at` ascending"

    Design: Corner/calculations/corner_revenue_sharing_pro_rata_versus_per_capita_divergence
    """
    quarry = _small_second_employer(api, plan)
    fixtures.timely_deposit(api, employer, fixtures.validated_batch(api, employer))
    assert_fields(
        employer.refresh(api),
        account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        participant_count=13,
    )
    assert_fields(quarry.refresh(api), account_balance_cents=0)

    by_assets = _disclose(
        api,
        plan,
        disclosure_period_start=FIRST_QUARTER_START,
        disclosure_period_end=SECOND_QUARTER_END,
        allocation_method=k.ALLOCATION_PRO_RATA_ASSETS,
        revenue_sharing_pool_cents=FULL_POOL_CENTS,
    )
    assert_fields(
        by_assets,
        allocation_method=k.ALLOCATION_PRO_RATA_ASSETS,
        gross_direct_fees_cents=GROSS_ON_SEVENTEEN,
        revenue_sharing_offset_cents=REBATED_ON_SEVENTEEN,
        net_plan_expense_cents=0,
        eligible_employer_count=2,
        total_revenue_sharing_allocated_cents=FULL_POOL_CENTS,
        residual_cents_distributed=0,
    )
    assert_percentage(
        by_assets["expense_rebate_pct"], TIER_TWO_REBATE_PCT, "expense_rebate_pct"
    )
    asset_lines = by_assets["allocation_lines"]
    assert len(asset_lines) == 2, f"Expected two allocation lines, got {asset_lines}"
    _assert_line(
        asset_lines[0],
        employer.employer_id,
        k.CANONICAL_BATCH_TOTAL_CENTS,
        100.00,
        FULL_POOL_CENTS,
        0,
    )
    _assert_line(asset_lines[1], quarry.employer_id, 0, 0.00, 0, 0)

    by_headcount = _disclose(
        api,
        plan,
        disclosure_period_start=SECOND_HALF_START,
        disclosure_period_end=SECOND_HALF_END,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=FULL_POOL_CENTS,
    )
    assert_fields(
        by_headcount,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        gross_direct_fees_cents=GROSS_ON_SEVENTEEN,
        revenue_sharing_offset_cents=REBATED_ON_SEVENTEEN,
        net_plan_expense_cents=0,
        eligible_employer_count=2,
        total_revenue_sharing_allocated_cents=FULL_POOL_CENTS,
        residual_cents_distributed=1,
    )
    headcount_lines = by_headcount["allocation_lines"]
    _assert_line(
        headcount_lines[0], employer.employer_id, 13, PALISADE_PER_CAPITA_PCT, 764706, 1
    )
    _assert_line(
        headcount_lines[1],
        quarry.employer_id,
        SMALL_PARTICIPANT_COUNT,
        QUARRY_PER_CAPITA_PCT,
        235294,
        0,
    )
    assert asset_lines[0]["credit_cents"] != headcount_lines[0]["credit_cents"], (
        "the two methods must divide the same pool differently over the same "
        "population"
    )

    assert_fields(employer.refresh(api), revenue_sharing_credit_cents=1764706)
    assert_fields(quarry.refresh(api), revenue_sharing_credit_cents=235294)
    assert (
        employer.employer["revenue_sharing_credit_cents"]
        + quarry.employer["revenue_sharing_credit_cents"]
        == 2 * FULL_POOL_CENTS
    ), "the two pools were handed back in full and nothing was created or lost"


def test_a_gross_below_the_first_tier_earns_no_rebate_and_a_dead_basis_no_lines(
    api: ApiClient, plan: PlanContext, employer: EmployerContext
):
    """
    A single small employer keeps the gross under the first tier floor, so the whole
    gross survives into the offset step; the audit firm's zero fee is still inside
    the input set, and a population whose every balance is zero is allocated nothing
    at all rather than a row of zeroes.

    "an unengaged auditor firm on the plan still contributes its per-participant fee
    to the gross"

    "`expense_rebate_pct` is then selected by a two-tier schedule read off the gross
    figure: 5.0 when `gross_direct_fees_cents` is at least 5000000 cents, 2.0 when it
    is at least 1000000 cents, and 0.0 below that."

    "`revenue_sharing_offset_cents` is the lesser of `revenue_sharing_pool_cents` and
    the rebated amount, so the pool can extinguish the plan's expense but can never
    push it negative, and `net_plan_expense_cents` is the rebated amount less that
    offset."

    "If the total basis across the population is zero — every eligible employer
    holding a zero balance, say — the pool is not allocated at all: `allocation_lines`
    is the empty array, `total_revenue_sharing_allocated_cents` is 0 and
    `residual_cents_distributed` is 0."

    "it carries `disclosed_at` stamped from the logical clock"

    Design: Corner/calculations/corner_net_plan_expense_zero_rebate_below_first_tier_floor
    """
    auditor = fixtures.audit_firm(api, plan, direct_fee_cents_per_participant=0)
    assert_fields(
        auditor,
        provider_type=k.PROVIDER_TYPE_AUDITOR_FIRM,
        direct_fee_cents_per_participant=0,
        holds_fiduciary_role=False,
    )
    assert_fields(plan.refresh(api), participant_count=13)
    assert_fields(employer.refresh(api), account_balance_cents=0)

    disclosure = _disclose(
        api,
        plan,
        disclosure_period_start=FIRST_QUARTER_START,
        disclosure_period_end=SECOND_QUARTER_END,
        allocation_method=k.ALLOCATION_PRO_RATA_ASSETS,
        revenue_sharing_pool_cents=PARTIAL_POOL_CENTS,
    )
    assert_fields(
        disclosure,
        gross_direct_fees_cents=780000,
        revenue_sharing_offset_cents=PARTIAL_POOL_CENTS,
        net_plan_expense_cents=480000,
        eligible_employer_count=1,
        total_revenue_sharing_allocated_cents=0,
        residual_cents_distributed=0,
        allocation_lines=[],
    )
    assert_percentage(disclosure["expense_rebate_pct"], 0.0, "expense_rebate_pct")
    assert_instant_equals(disclosure["disclosed_at"], k.DEFAULT_CLOCK, "disclosed_at")
    assert_fields(employer.refresh(api), revenue_sharing_credit_cents=0)


def test_a_disclosure_is_an_event_row_that_a_later_correction_never_restates(
    api: ApiClient, plan: PlanContext, employer: EmployerContext
):
    """
    The disclosure carries no version and no updated_at, and issuing a second one for
    the next period leaves the first byte for byte where it was — the running credit
    lives on the employer, not on the row.

    "A `FeeDisclosure` is an immutable event row: it carries only `id` and
    `created_at`, has neither `updated_at` nor `version`, and has no update capability
    of any kind."

    "Everything a disclosure asserts is computed once, at issue time, and never
    restated."

    "A disclosure is an immutable event row: it carries `disclosed_at` stamped from
    the logical clock, is readable afterwards by the regulator, the pooled plan
    provider and adopting employers, and — as noted in §2.4 — has no `updated_at` and
    no `version`, because nothing ever amends it."

    "Correcting a disclosure means issuing another one; nothing prevents two
    disclosures covering the same period, and each allocates its own pool on top of
    the last."

    Design: Corner/entities/corner_fee_disclosure_is_immutable_with_no_version_field
    """
    quarry = _small_second_employer(api, plan)
    first = _disclose(
        api,
        plan,
        disclosure_period_start=FIRST_QUARTER_START,
        disclosure_period_end=SECOND_QUARTER_END,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=FULL_POOL_CENTS,
    )
    assert_resource_shape(first, "FeeDisclosure")
    assert_instant_equals(first["disclosed_at"], k.DEFAULT_CLOCK, "disclosed_at")
    assert_fields(
        first,
        eligible_employer_count=2,
        total_revenue_sharing_allocated_cents=FULL_POOL_CENTS,
        residual_cents_distributed=1,
    )
    _assert_line(
        first["allocation_lines"][0],
        employer.employer_id,
        13,
        PALISADE_PER_CAPITA_PCT,
        764706,
        1,
    )
    _assert_line(
        first["allocation_lines"][1],
        quarry.employer_id,
        SMALL_PARTICIPANT_COUNT,
        QUARRY_PER_CAPITA_PCT,
        235294,
        0,
    )

    read_by_employer = validate_single(
        api.get_fee_disclosure(first["id"], employer.headers)
    )
    assert_same_object(read_by_employer, first)

    second = _disclose(
        api,
        plan,
        disclosure_period_start=SECOND_HALF_START,
        disclosure_period_end=SECOND_HALF_END,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=PARTIAL_POOL_CENTS,
    )
    assert_resource_shape(second, "FeeDisclosure")
    assert_fields(
        second,
        total_revenue_sharing_allocated_cents=PARTIAL_POOL_CENTS,
        residual_cents_distributed=1,
    )
    _assert_line(
        second["allocation_lines"][0],
        employer.employer_id,
        13,
        PALISADE_PER_CAPITA_PCT,
        229412,
        1,
    )
    _assert_line(
        second["allocation_lines"][1],
        quarry.employer_id,
        SMALL_PARTICIPANT_COUNT,
        QUARRY_PER_CAPITA_PCT,
        70588,
        0,
    )
    assert second["id"] != first["id"], (
        "a correction is a new row, not an amendment of the old one"
    )

    assert_same_object(
        validate_single(api.get_fee_disclosure(first["id"], plan.provider_headers)),
        first,
    )
    assert_fields(employer.refresh(api), revenue_sharing_credit_cents=994118)
    assert_fields(quarry.refresh(api), revenue_sharing_credit_cents=305882)


def test_a_plan_with_nothing_to_bill_is_refused_before_its_dates_are_read(
    api: ApiClient
):
    """
    An ACTIVE plan whose every engaged provider charges nothing per participant has
    nothing to disclose, and it says so even when the requested period is reversed as
    well; engaging one billable firm moves the same request down the ladder to the
    date check and then to a 201.

    "When a request violates more than one rule, exactly one error is returned: the
    violation with the lowest priority number in the ladder below."

    "at least one service provider engaged on the plan must charge a
    `direct_fee_cents_per_participant` greater than zero, since a plan whose every
    provider charges no direct fee has nothing to disclose and gives the rebate no
    base to reduce, and such a request is rejected with
    `ERR_NO_BILLABLE_SERVICE_PROVIDER`"

    "and `disclosure_period_end` must fall on or after `disclosure_period_start`,
    failing which it is rejected with `ERR_INVALID_DISCLOSURE_PERIOD`"

    Design: Corner/errors/corner_fee_disclosure_requires_a_billable_provider_before_period_check
    """
    zero_fee = _zero_fee_plan(api)
    assert_fields(zero_fee.plan, status=k.PLAN_ACTIVE)
    employer = fixtures.active_employer(api, zero_fee)
    assert_fields(zero_fee.refresh(api), participant_count=13)

    well_ordered = f.fee_disclosure_payload(
        zero_fee.plan_id,
        disclosure_period_start=FIRST_QUARTER_START,
        disclosure_period_end=SECOND_QUARTER_END,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=SMALL_POOL_CENTS,
    )
    reversed_period = f.fee_disclosure_payload(
        zero_fee.plan_id,
        disclosure_period_start=SECOND_QUARTER_END,
        disclosure_period_end=FIRST_QUARTER_START,
        allocation_method=k.ALLOCATION_PER_CAPITA,
        revenue_sharing_pool_cents=SMALL_POOL_CENTS,
    )

    validate_error(
        api.create_fee_disclosure(well_ordered, zero_fee.provider_headers),
        ERR_NO_BILLABLE_SERVICE_PROVIDER,
        expected_status=409,
    )
    validate_error(
        api.create_fee_disclosure(reversed_period, zero_fee.provider_headers),
        ERR_NO_BILLABLE_SERVICE_PROVIDER,
        expected_status=409,
    )

    tpa = fixtures.engage_provider(
        api, zero_fee.provider_id, f.tpa_payload(zero_fee.plan_id)
    )
    assert_fields(
        tpa,
        provider_type=k.PROVIDER_TYPE_TPA,
        direct_fee_cents_per_participant=k.TPA_FEE_CENTS,
    )
    validate_error(
        api.create_fee_disclosure(reversed_period, zero_fee.provider_headers),
        ERR_INVALID_DISCLOSURE_PERIOD,
        expected_status=422,
    )

    disclosure = validate_created(
        api.create_fee_disclosure(well_ordered, zero_fee.provider_headers)
    )
    assert_fields(
        disclosure,
        gross_direct_fees_cents=195000,
        revenue_sharing_offset_cents=SMALL_POOL_CENTS,
        net_plan_expense_cents=145000,
        eligible_employer_count=1,
        total_revenue_sharing_allocated_cents=SMALL_POOL_CENTS,
        residual_cents_distributed=0,
    )
    assert_percentage(disclosure["expense_rebate_pct"], 0.0, "expense_rebate_pct")
    assert len(disclosure["allocation_lines"]) == 1, (
        f"Expected a single allocation line, got {disclosure['allocation_lines']}"
    )
    _assert_line(
        disclosure["allocation_lines"][0],
        employer.employer_id,
        13,
        100.00,
        SMALL_POOL_CENTS,
        0,
    )
