"""Validation-ladder precedence: the first violated tier is the only one reported.

Two category pairs from PRD section 2.5's sixteen-tier ladder are exercised here,
each on a request that violates both tiers at once and each with a control that
isolates the later tier so the ordering is falsifiable in both directions:

* state (tier 11) beats business_constraint (tier 15) on order entry;
* MSRB conduct (tier 12) beats the fiscal rules (tier 16) on a syndicate add.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DENOMINATION_INVALID,
    ERR_LIABILITY_PCT_SUM_INVALID,
    ERR_MA_UNDERWRITER_CONFLICT,
    ERR_ORDER_PERIOD_INVALID_STATE,
)
from test_helpers.assertions import ids_of, to_decimal
from test_helpers.constants import (
    CLOCK_EPOCH,
    LIABILITY_PCT_TOTAL,
    MIN_DENOMINATION_USD,
    TRANCHE_1_YIELD_PCT,
    plus_days,
    plus_hours,
)
from test_helpers.types import (
    MemberRole,
    MemberStatus,
    OrderPeriodStatus,
    OrderType,
    PeriodType,
    PriorityPolicy,
)

# The institutional book of the design index: 2026-08-05T13:00Z to 17:00Z, with
# the logical clock parked at 14:00Z, inside the window (PRD section 3.7).
BOOK_DAY = plus_days(CLOCK_EPOCH, 4)
BOOK_OPENS_AT = plus_hours(BOOK_DAY, 13)
BOOK_CLOSES_AT = plus_hours(BOOK_DAY, 17)
CLOCK_INSIDE_WINDOW = plus_hours(BOOK_DAY, 14)

# 2,001,000 dollars: one thousand dollars above a whole multiple of the
# five-thousand-dollar minimum denomination (PRD section 2.6).
MALFORMED_PAR_USD = 400 * MIN_DENOMINATION_USD + 1000

# A second seat that carries the whole book's liability plus sixty percent more,
# so the ACTIVE liability sum would reach 160.0000 (PRD section 3.6).
SECOND_SEAT_PCT = 60.0000


def _closed_institutional_book(ctx):
    """Schedule, open and close an empty institutional book on a negotiated deal."""
    period = fx.schedule_order_period(
        ctx.client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            BOOK_OPENS_AT,
            BOOK_CLOSES_AT,
            PeriodType.INSTITUTIONAL,
            priority_policy=PriorityPolicy.STANDARD_PRIORITY,
        ),
    )
    ctx.period_id = period["id"]
    fx.set_clock(ctx.client, CLOCK_INSIDE_WINDOW)
    fx.open_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    ctx.period = fx.close_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def _malformed_order_payload(ctx, expected_order_period_version):
    """One order whose `par_requested_usd` is not a whole minimum-denomination multiple."""
    assert MALFORMED_PAR_USD % MIN_DENOMINATION_USD != 0
    return f.order_payload(
        ctx.tranche_ids[0],
        ctx.member_ids[0],
        expected_order_period_version,
        OrderType.INSTITUTIONAL_PRIORITY,
        MALFORMED_PAR_USD,
        price_or_yield_pct=TRANCHE_1_YIELD_PCT,
    )


def _seat_senior_manager_at_whole_liability(ctx):
    """Seat one ACTIVE SENIOR_MANAGER holding the entire 100.0000 percent liability."""
    ctx.senior_member = fx.seat_member(
        ctx.client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.advisor_headers,
        MemberRole.SENIOR_MANAGER,
        liability_pct=LIABILITY_PCT_TOTAL,
        takedown_share_pct=LIABILITY_PCT_TOTAL,
        priority_rank=1,
    )
    ctx.members = [ctx.senior_member]
    ctx.member_ids = [ctx.senior_member["id"]]
    return ctx


def _second_seat_payload(firm_id):
    """A CO_MANAGER seat at sixty percent of liability and takedown, rank two."""
    return f.syndicate_member_payload(
        firm_id,
        MemberRole.CO_MANAGER,
        liability_pct=SECOND_SEAT_PCT,
        takedown_share_pct=SECOND_SEAT_PCT,
        priority_rank=2,
    )


def test_closed_book_reports_state_before_denomination(client, negotiated_deal):
    """PRD section 2.5: "When two conditions in a single request are both unsatisfied, the response always carries the error of the lower-numbered tier; a caller cannot observe the later failure until the earlier one is fixed."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_order_entry
    """
    ctx = _closed_institutional_book(negotiated_deal)
    closed = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert closed["status"] == OrderPeriodStatus.CLOSED
    assert closed["orders_received_count"] == 0

    # The version token is fresh, so tier 10 optimistic concurrency is satisfied
    # and the only live violations are the CLOSED state and the denomination.
    response = client.create_order(
        ctx.period_id,
        _malformed_order_payload(ctx, closed["version"]),
        ctx.underwriter_headers,
    )
    error = validate_error(response, ERR_ORDER_PERIOD_INVALID_STATE)
    assert error["error_id"] != ERR_DENOMINATION_INVALID

    after = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert after["orders_received_count"] == 0
    orders, meta = validate_paginated(
        client.list_period_orders(ctx.period_id, ctx.underwriter_headers)
    )
    assert orders == []
    assert meta["total_count"] == 0


def test_reopened_book_reports_the_denomination_violation(client, negotiated_deal):
    """PRD section 3.7: "`par_requested_usd` must be a positive whole multiple of five thousand United States dollars, or the request is refused with `ERR_DENOMINATION_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_order_entry
    """
    ctx = _closed_institutional_book(negotiated_deal)
    reopened = fx.reopen_period(
        client, ctx.period_id, "Denomination rejection to be re-tested on a live book"
    )
    assert reopened["status"] == OrderPeriodStatus.OPEN

    open_period = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert open_period["status"] == OrderPeriodStatus.OPEN

    # Same body as the refused write above; with tier 11 now satisfied the
    # business constraint at tier 15 is the violation the caller finally sees.
    response = client.create_order(
        ctx.period_id,
        _malformed_order_payload(ctx, open_period["version"]),
        ctx.underwriter_headers,
    )
    error = validate_error(response, ERR_DENOMINATION_INVALID)
    assert error["error_id"] != ERR_ORDER_PERIOD_INVALID_STATE

    after = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert after["orders_received_count"] == 0
    orders, meta = validate_paginated(
        client.list_period_orders(ctx.period_id, ctx.underwriter_headers)
    )
    assert orders == []
    assert meta["total_count"] == 0


def test_advisor_seat_reports_g23_conflict_before_liability_overflow(
    client, structuring_deal, compliance
):
    """PRD section 2.5: "Requests are validated in a fixed sixteen-tier ladder, and **only the first violated tier is reported**."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_syndicate_add
    """
    ctx = _seat_senior_manager_at_whole_liability(structuring_deal)

    # The deal's own municipal advisor firm, seated at a share that would also
    # carry the ACTIVE liability sum to 160.0000: tier 12 against tier 16.
    response = client.create_syndicate_member(
        ctx.deal_id,
        _second_seat_payload(ctx.advisor_firm_id),
        ctx.advisor_headers,
    )
    error = validate_error(response, ERR_MA_UNDERWRITER_CONFLICT)
    assert error["error_id"] != ERR_LIABILITY_PCT_SUM_INVALID

    members, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, compliance)
    )
    assert meta["total_count"] == 1
    assert ids_of(members) == [ctx.senior_member["id"]]
    active = [m for m in members if m["status"] == MemberStatus.ACTIVE]
    assert sum(to_decimal(m["liability_pct"]) for m in active) == to_decimal(
        LIABILITY_PCT_TOTAL
    )


def test_unconflicted_seat_at_the_same_share_reports_liability_overflow(
    client, structuring_deal, compliance
):
    """PRD section 3.6: "Finally the fiscal bound: the sum of `liability_pct` over the deal's `ACTIVE` members may never exceed 100.0000 once the new seat is counted, and the identical bound applies to the sum of `takedown_share_pct`; a breach of either reports `ERR_LIABILITY_PCT_SUM_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_on_syndicate_add
    """
    ctx = _seat_senior_manager_at_whole_liability(structuring_deal)
    unconflicted_firm = fx.register_underwriter_firm(client)

    # Identical shares, but a firm that is not the deal's advisor: with tier 12
    # satisfied the fiscal bound at tier 16 becomes observable.
    response = client.create_syndicate_member(
        ctx.deal_id,
        _second_seat_payload(unconflicted_firm["id"]),
        ctx.advisor_headers,
    )
    error = validate_error(response, ERR_LIABILITY_PCT_SUM_INVALID)
    assert error["error_id"] != ERR_MA_UNDERWRITER_CONFLICT

    members, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, compliance)
    )
    assert meta["total_count"] == 1
    assert ids_of(members) == [ctx.senior_member["id"]]
    active = [m for m in members if m["status"] == MemberStatus.ACTIVE]
    assert sum(to_decimal(m["liability_pct"]) for m in active) == to_decimal(
        LIABILITY_PCT_TOTAL
    )
