"""Endpoint corners: listing filters, action side effects and cross-reference links.

Five instances of the CORNER design index's ``endpoints`` section are translated
here, each pinned to the PRD sentence that derives its outcome:

* ``GET /deals`` filters must AND together and ``total_count`` must describe the
  filtered population rather than the returned page (PRD section 2.3);
* acknowledgement pins the acting analyst to the engagement, so a second analyst
  is refused ``ERR_ROLE_IDENTITY_MISMATCH`` (PRD section 3.5);
* an order is the junction of a period, a maturity tranche and a syndicate seat,
  with body-reference existence checked before single-deal integrity (PRD 2.5);
* the yield-restriction analysis is a POST that behaves as a pure read (PRD 3.8);
* reopening a closed book is conditional on the logical clock, not on the entity,
  and it is the ``ComplianceOfficer``'s exclusive act (PRD section 3.7).
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CROSS_DEAL_REFERENCE,
    ERR_ORDER_PERIOD_WINDOW_CLOSED,
    ERR_ROLE_IDENTITY_MISMATCH,
    ERR_TRANCHE_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_money,
    assert_pagination,
    assert_timestamps_equal,
    assert_version,
    assert_yield_value,
    expected_arbitrage_yield,
    expected_excess_earnings,
    expected_permitted_investment_yield,
    ids_of,
)
from test_helpers.constants import (
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    CLOCK_EPOCH,
    TRANCHE_1_YIELD_PCT,
    plus_days,
    plus_hours,
)
from test_helpers.test_users import RATING_ANALYST_OTHER_ID, RATING_ANALYST_PRIMARY_ID
from test_helpers.types import (
    DealStatus,
    EngagementStatus,
    OrderPeriodStatus,
    OrderStatus,
    OrderType,
    PeriodType,
    PriorityPolicy,
    RatingAgency,
    SaleMethod,
)

# The design index's institutional book: 2026-08-05T13:00Z to 17:00Z, four days
# after the logical clock's epoch of 2026-08-01T00:00:00Z (PRD section 2.4).
BOOK_DAY = plus_days(CLOCK_EPOCH, 4)
BOOK_OPENS_AT = plus_hours(BOOK_DAY, 13)
BOOK_CLOSES_AT = plus_hours(BOOK_DAY, 17)
CLOCK_INSIDE_WINDOW = plus_hours(BOOK_DAY, 14)
CLOCK_ONE_HOUR_BEFORE_CLOSE = plus_hours(BOOK_DAY, 16)

# One order of one million dollars, a whole multiple of the minimum denomination.
ORDER_PAR_USD = 1000000

# The engagement's information request, quoted back in the response.
INFORMATION_REQUEST = "Provide the audited fund balance."

# The reopen reasons of the design index, one inside the window and one after it.
REOPEN_REASON = "Senior manager reported a mis-keyed order."
LATE_REOPEN_REASON = "Second look after the window elapsed."

# The yield-restriction projection: one million dollars of unspent proceeds held
# for a full three-hundred-sixty-day year, once below and once above the
# permitted yield of the single-tranche issue.
UNSPENT_PROCEEDS_USD = 1000000
INVESTMENT_DAYS = 360
PROJECTED_YIELD_BELOW_PERMITTED_PCT = 4.2
PROJECTED_YIELD_ABOVE_PERMITTED_PCT = 5.0


def _two_issuer_deal_population(client):
    """Three deals across two issuers, all sharing one municipal advisory firm.

    The first is driven to PRICING_COMPETITIVE so the ``sale_method`` and
    ``status`` filters each select a different single row of the first issuer.
    """
    ctx = fx.competitive_pricing_deal(client)
    ctx.competitive_deal_id = ctx.deal_id
    ctx.draft_same_issuer = fx.create_deal(
        client, ctx.issuer_id, ctx.advisor_firm_id, ctx.issuer_headers
    )
    ctx.other_issuer = fx.register_issuer(client)
    ctx.other_issuer_id = ctx.other_issuer["id"]
    ctx.draft_other_issuer = fx.create_deal(
        client, ctx.other_issuer_id, ctx.advisor_firm_id
    )
    return ctx


def _requested_engagement(client):
    """A DRAFT deal carrying one REQUESTED MOODYS rating engagement."""
    ctx = fx.draft_deal(client)
    ctx.engagement = fx.request_rating(
        client, ctx.deal_id, ctx.advisor_headers, RatingAgency.MOODYS
    )
    ctx.engagement_id = ctx.engagement["id"]
    return ctx


def _institutional_book(ctx):
    """Schedule the design index's window, park the clock inside it and open."""
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
    ctx.period = fx.open_period(ctx.client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def _open_negotiated_book(client):
    """A PRICING_NEGOTIATED deal whose institutional book is OPEN on the clock."""
    ctx = fx.negotiated_pricing_deal(client)
    _institutional_book(ctx)
    ctx.period = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def _foreign_deal_tranche(ctx):
    """A maturity tranche of a second, separate deal of the same issuer."""
    other_deal = fx.create_deal(
        ctx.client, ctx.issuer_id, ctx.advisor_firm_id, ctx.issuer_headers
    )
    ctx.other_deal_id = other_deal["id"]
    return fx.add_tranche(
        ctx.client, ctx.other_deal_id, ctx.advisor_headers, f.canonical_tranche_1_payload()
    )


def _closed_negotiated_book(client):
    """The same book closed by its underwriter, with the clock at 16:00Z.

    Closing runs the allotment, so ``allotment_run_count`` stands at one and the
    reopen precondition of PRD section 3.7 is satisfied.
    """
    ctx = _open_negotiated_book(client)
    ctx.period = fx.close_period(client, ctx.period_id, ctx.underwriter_headers)
    fx.set_clock(client, CLOCK_ONE_HOUR_BEFORE_CLOSE)
    return ctx


def _single_tranche_structuring_deal(client):
    """A STRUCTURING deal of five million dollars carrying exactly one maturity.

    With a single maturity the bond-year weighting of PRD section 3.8 collapses
    to that maturity's own ``yield_pct``, which is the design index's 4.2500.
    """
    ctx = fx.participants(client)
    deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    ctx.deal_id = deal["id"]
    fx.add_tranche(client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_1_payload())
    ctx.deal = fx.submit_structure(client, ctx.deal_id, ctx.advisor_headers)
    ctx.tranches = fx.list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    ctx.tranche_ids = ids_of(ctx.tranches)
    return ctx


def _analysis_payload(projected_investment_yield_pct):
    """One yield-restriction projection over a full three-hundred-sixty-day year."""
    return f.yield_restriction_payload(
        projected_investment_yield_pct, UNSPENT_PROCEEDS_USD, INVESTMENT_DAYS
    )


def test_deal_filters_and_together_over_the_whole_population(client, compliance):
    """PRD section 3.2: "Deals can be listed with optional `issuer_id`, `municipal_advisor_firm_id`, `status`, and `sale_method` filters, and read individually — the individual read is where a client obtains the deal's `version` before starting an official statement."

    Design: Corner/endpoints/deal_listing_filters_combine_and_paginate
    """
    ctx = _two_issuer_deal_population(client)

    # issuer_id AND sale_method: the issuer's other deal is still UNDETERMINED.
    rows, meta = validate_paginated(
        client.list_deals(
            compliance, issuer_id=ctx.issuer_id, sale_method=SaleMethod.COMPETITIVE
        )
    )
    assert ids_of(rows) == [ctx.competitive_deal_id]
    assert_pagination(meta, total_count=1, has_more=False)

    # issuer_id AND status: the COMPETITIVE deal of the same issuer left DRAFT
    # when its schedule was frozen, so status excludes it.
    rows, meta = validate_paginated(
        client.list_deals(compliance, issuer_id=ctx.issuer_id, status=DealStatus.DRAFT)
    )
    assert ids_of(rows) == [ctx.draft_same_issuer["id"]]
    assert_pagination(meta, total_count=1, has_more=False)

    # The advisory firm spans both issuers, so its filter selects all three.
    rows, meta = validate_paginated(
        client.list_deals(compliance, municipal_advisor_firm_id=ctx.advisor_firm_id)
    )
    assert set(ids_of(rows)) == {
        ctx.competitive_deal_id,
        ctx.draft_same_issuer["id"],
        ctx.draft_other_issuer["id"],
    }
    assert_pagination(meta, total_count=3, has_more=False)


def test_deal_paging_counts_the_filtered_set_and_not_the_page(client, compliance):
    """PRD section 2.3: "`total_count` reports the number of rows matching the request's filters before the pagination window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned window."

    Design: Corner/endpoints/deal_listing_filters_combine_and_paginate
    """
    ctx = _two_issuer_deal_population(client)
    issuer_deal_ids = {ctx.competitive_deal_id, ctx.draft_same_issuer["id"]}

    first, first_meta = validate_paginated(
        client.list_deals(compliance, issuer_id=ctx.issuer_id, limit=1, offset=0)
    )
    assert len(first) == 1
    assert_pagination(first_meta, total_count=2, has_more=True, limit=1, offset=0)

    # The window of the second page exhausts the two filtered rows, so nothing
    # remains beyond it even though the third deal exists on the other issuer.
    second, second_meta = validate_paginated(
        client.list_deals(compliance, issuer_id=ctx.issuer_id, limit=1, offset=1)
    )
    assert len(second) == 1
    assert_pagination(second_meta, total_count=2, has_more=False, limit=1, offset=1)

    assert ids_of(first) != ids_of(second)
    assert set(ids_of(first)) | set(ids_of(second)) == issuer_deal_ids
    assert ctx.draft_other_issuer["id"] not in issuer_deal_ids


def test_acknowledge_moves_the_status_and_writes_the_acting_analyst(client, analyst):
    """PRD section 3.5: "A `RatingAnalyst` acknowledges an engagement whose `status` is `REQUESTED` — any other status reports `ERR_RATING_ENGAGEMENT_INVALID_STATE` — which advances it from `REQUESTED` to `UNDER_REVIEW` and writes the acting `X-User-ID` into `assigned_analyst_user_id`."

    Design: Corner/endpoints/acknowledge_pins_the_analyst_to_the_engagement
    """
    ctx = _requested_engagement(client)
    assert ctx.engagement["status"] == EngagementStatus.REQUESTED
    assert ctx.engagement["assigned_analyst_user_id"] is None
    assert_version(ctx.engagement, 1, "engagement")

    # The action carries no body at all; both side effects must still land.
    acknowledged = validate_success(
        client.acknowledge_engagement(ctx.engagement_id, None, analyst), 200
    )
    assert_common_fields(acknowledged, "engagement")
    assert acknowledged["id"] == ctx.engagement_id
    assert acknowledged["status"] == EngagementStatus.UNDER_REVIEW
    assert acknowledged["assigned_analyst_user_id"] == RATING_ANALYST_PRIMARY_ID
    assert_version(acknowledged, 2, "engagement")
    assert acknowledged["info_request_count"] == 0


def test_only_the_pinned_analyst_may_request_information(
    client, analyst, other_analyst, compliance
):
    """PRD section 3.5: "From that moment the engagement is **pinned**: only the analyst whose identifier matches `assigned_analyst_user_id` may request information on it or assign its rating, and any other `RatingAnalyst` attempting either is refused with `ERR_ROLE_IDENTITY_MISMATCH` even though the role itself is authorised."

    Design: Corner/endpoints/acknowledge_pins_the_analyst_to_the_engagement
    """
    ctx = _requested_engagement(client)
    pinned = fx.acknowledge_engagement(client, ctx.engagement_id, analyst)
    assert pinned["assigned_analyst_user_id"] == RATING_ANALYST_PRIMARY_ID
    assert RATING_ANALYST_OTHER_ID != RATING_ANALYST_PRIMARY_ID

    # A second RatingAnalyst holds the authorised role but not the engagement.
    response = client.request_info(
        ctx.engagement_id, f.information_request_payload(INFORMATION_REQUEST), other_analyst
    )
    validate_error(response, ERR_ROLE_IDENTITY_MISMATCH)

    refused = validate_success(
        client.get_rating_engagement(ctx.engagement_id, compliance), 200
    )
    assert refused["status"] == EngagementStatus.UNDER_REVIEW
    assert refused["info_request_count"] == 0
    assert refused["latest_information_request"] is None
    assert refused["assigned_analyst_user_id"] == RATING_ANALYST_PRIMARY_ID

    # The identical body from the pinned analyst is accepted.
    accepted = validate_success(
        client.request_info(
            ctx.engagement_id, f.information_request_payload(INFORMATION_REQUEST), analyst
        ),
        200,
    )
    assert accepted["status"] == EngagementStatus.INFO_REQUESTED
    assert accepted["info_request_count"] == 1
    assert accepted["latest_information_request"] == INFORMATION_REQUEST


def test_unknown_tranche_in_an_order_body_reports_the_tranche_not_found(
    client, compliance
):
    """PRD section 2.5: "The reported error is the referenced entity's not-found error from tier 4."

    Design: Corner/endpoints/order_links_a_tranche_and_a_syndicate_seat
    """
    ctx = _open_negotiated_book(client)
    assert ctx.period["status"] == OrderPeriodStatus.OPEN

    response = client.create_order(
        ctx.period_id,
        f.order_payload(
            NON_EXISTENT_UUID,
            ctx.member_ids[0],
            ctx.period["version"],
            OrderType.INSTITUTIONAL_PRIORITY,
            ORDER_PAR_USD,
            price_or_yield_pct=TRANCHE_1_YIELD_PCT,
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_TRANCHE_NOT_FOUND)

    orders, meta = validate_paginated(client.list_period_orders(ctx.period_id, compliance))
    assert orders == []
    assert_pagination(meta, total_count=0, has_more=False)
    assert fx.read_period(client, ctx.period_id, compliance)["orders_received_count"] == 0


def test_tranche_of_another_deal_reports_a_cross_deal_reference(client, compliance):
    """PRD section 3.7: "Both referenced entities must belong to the same deal as the order period, or the request is refused with `ERR_CROSS_DEAL_REFERENCE`."

    Design: Corner/endpoints/order_links_a_tranche_and_a_syndicate_seat
    """
    ctx = _open_negotiated_book(client)
    foreign_tranche = _foreign_deal_tranche(ctx)
    assert foreign_tranche["deal_id"] != ctx.deal_id

    # The tranche exists, so tier 7 is satisfied and tier 9 becomes observable.
    response = client.create_order(
        ctx.period_id,
        f.order_payload(
            foreign_tranche["id"],
            ctx.member_ids[0],
            ctx.period["version"],
            OrderType.INSTITUTIONAL_PRIORITY,
            ORDER_PAR_USD,
            price_or_yield_pct=TRANCHE_1_YIELD_PCT,
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_CROSS_DEAL_REFERENCE)

    orders, meta = validate_paginated(client.list_period_orders(ctx.period_id, compliance))
    assert orders == []
    assert_pagination(meta, total_count=0, has_more=False)
    assert fx.read_period(client, ctx.period_id, compliance)["orders_received_count"] == 0


def test_order_links_the_period_the_tranche_and_the_seat(client, compliance):
    """PRD section 3.7: "On success the order is created with `status` `PENDING`, `par_allotted_usd` zero, `cancellation_reason` null, and `submitted_at` set to the current logical clock instant; the period's `orders_received_count` is recomputed as the count of its orders that are not `CANCELLED`, and the period's `version` increments."

    Design: Corner/endpoints/order_links_a_tranche_and_a_syndicate_seat
    """
    ctx = _open_negotiated_book(client)

    order = validate_success(
        client.create_order(
            ctx.period_id,
            f.order_payload(
                ctx.tranche_ids[0],
                ctx.member_ids[0],
                ctx.period["version"],
                OrderType.INSTITUTIONAL_PRIORITY,
                ORDER_PAR_USD,
                price_or_yield_pct=TRANCHE_1_YIELD_PCT,
            ),
            ctx.underwriter_headers,
        ),
        201,
    )
    assert_common_fields(order, "order")
    assert order["order_period_id"] == ctx.period_id
    assert order["maturity_tranche_id"] == ctx.tranche_ids[0]
    assert order["syndicate_member_id"] == ctx.member_ids[0]
    assert order["status"] == OrderStatus.PENDING
    assert_money(order["par_allotted_usd"], 0, "par_allotted_usd")
    assert order["cancellation_reason"] is None

    orders, meta = validate_paginated(client.list_period_orders(ctx.period_id, compliance))
    assert ids_of(orders) == [order["id"]]
    assert_pagination(meta, total_count=1, has_more=False)
    assert fx.read_period(client, ctx.period_id, compliance)["orders_received_count"] == 1


def test_yield_restriction_analysis_reverses_its_verdict_on_the_same_data(
    client, compliance
):
    """PRD section 3.8: "The restriction test is **strict**: `yield_restriction_applies` is true only when `projected_investment_yield_pct` is strictly greater than `permitted_investment_yield_pct`, so a projected yield exactly equal to the permitted yield does not trigger restriction."

    Design: Corner/endpoints/yield_restriction_analysis_computes_without_mutating
    """
    ctx = _single_tranche_structuring_deal(client)
    arbitrage_yield = expected_arbitrage_yield(ctx.tranches)
    permitted_yield = expected_permitted_investment_yield(arbitrage_yield)
    assert PROJECTED_YIELD_BELOW_PERMITTED_PCT < permitted_yield
    assert PROJECTED_YIELD_ABOVE_PERMITTED_PCT > permitted_yield

    below = validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, _analysis_payload(PROJECTED_YIELD_BELOW_PERMITTED_PCT), compliance
        ),
        200,
    )
    assert below["deal_id"] == ctx.deal_id
    assert_yield_value(below["arbitrage_yield_pct"], arbitrage_yield, "arbitrage_yield_pct")
    assert_yield_value(
        below["permitted_investment_yield_pct"],
        permitted_yield,
        "permitted_investment_yield_pct",
    )
    assert_yield_value(
        below["projected_investment_yield_pct"],
        PROJECTED_YIELD_BELOW_PERMITTED_PCT,
        "projected_investment_yield_pct",
    )
    assert below["yield_restriction_applies"] is False
    assert_money(below["excess_earnings_usd"], 0, "excess_earnings_usd")

    # Same stored schedule, same proceeds and days: only the projection moves.
    above = validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, _analysis_payload(PROJECTED_YIELD_ABOVE_PERMITTED_PCT), compliance
        ),
        200,
    )
    assert_yield_value(above["arbitrage_yield_pct"], arbitrage_yield, "arbitrage_yield_pct")
    assert_yield_value(
        above["permitted_investment_yield_pct"],
        permitted_yield,
        "permitted_investment_yield_pct",
    )
    assert above["yield_restriction_applies"] is True
    assert_money(
        above["excess_earnings_usd"],
        expected_excess_earnings(
            UNSPENT_PROCEEDS_USD,
            PROJECTED_YIELD_ABOVE_PERMITTED_PCT,
            permitted_yield,
            INVESTMENT_DAYS,
        ),
        "excess_earnings_usd",
    )


def test_yield_restriction_analysis_leaves_the_deal_untouched(client, compliance):
    """PRD section 3.8: "It stores nothing whatsoever."

    Design: Corner/endpoints/yield_restriction_analysis_computes_without_mutating
    """
    ctx = _single_tranche_structuring_deal(client)
    before = fx.read_deal(client, ctx.deal_id, compliance)
    assert before["arbitrage_yield_pct"] is None

    validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, _analysis_payload(PROJECTED_YIELD_BELOW_PERMITTED_PCT), compliance
        ),
        200,
    )
    validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, _analysis_payload(PROJECTED_YIELD_ABOVE_PERMITTED_PCT), compliance
        ),
        200,
    )

    # Only the pricing event writes the deal's own arbitrage yield.
    after = fx.read_deal(client, ctx.deal_id, compliance)
    assert after["arbitrage_yield_pct"] is None
    assert after["status"] == DealStatus.STRUCTURING
    assert_version(after, before["version"], "deal")
    assert_timestamps_equal(after["updated_at"], before["updated_at"], "deal.updated_at")


def test_reopen_is_reserved_to_the_compliance_officer(client, compliance):
    """PRD section 3.7: "Reopening is the compensating action for a completed allotment run, and it is reserved to a `ComplianceOfficer`."

    Design: Corner/endpoints/order_period_reopen_is_conditional_on_the_logical_clock
    """
    ctx = _closed_negotiated_book(client)
    assert ctx.period["status"] == OrderPeriodStatus.CLOSED
    assert ctx.period["allotment_run_count"] == 1

    # The underwriter that closed the book cannot undo its own allotment run.
    response = client.reopen_order_period(
        ctx.period_id, f.reopen_payload(REOPEN_REASON), ctx.underwriter_headers
    )
    validate_error(response, ERR_UNAUTHORIZED)

    unchanged = fx.read_period(client, ctx.period_id, compliance)
    assert unchanged["status"] == OrderPeriodStatus.CLOSED
    assert unchanged["reopen_reason"] is None
    assert unchanged["allotment_run_count"] == 1
    assert_version(unchanged, ctx.period["version"], "order period")


def test_compliance_reopens_the_closed_book_inside_the_window(client, compliance):
    """PRD section 3.7: "Hop one sets the period's `status` back to `OPEN` and stores the supplied reason in `reopen_reason`."

    Design: Corner/endpoints/order_period_reopen_is_conditional_on_the_logical_clock
    """
    ctx = _closed_negotiated_book(client)

    reopened = validate_success(
        client.reopen_order_period(
            ctx.period_id, f.reopen_payload(REOPEN_REASON), compliance
        ),
        200,
    )
    assert_common_fields(reopened, "order period")
    assert reopened["id"] == ctx.period_id
    assert reopened["status"] == OrderPeriodStatus.OPEN
    assert reopened["reopen_reason"] == REOPEN_REASON
    assert_version(reopened, ctx.period["version"] + 1, "order period")

    live = fx.read_period(client, ctx.period_id, compliance)
    assert live["status"] == OrderPeriodStatus.OPEN
    assert live["reopen_reason"] == REOPEN_REASON


def test_reclosing_the_reopened_book_records_a_second_allotment_run(client, compliance):
    """PRD section 3.7: "Note that `allotment_run_count` is a cumulative counter and is *not* decremented by a reopen — it records that a run happened, which is what the pricing precondition looks for."

    Design: Corner/endpoints/order_period_reopen_is_conditional_on_the_logical_clock
    """
    ctx = _closed_negotiated_book(client)
    reopened = fx.reopen_period(client, ctx.period_id, REOPEN_REASON)
    assert reopened["status"] == OrderPeriodStatus.OPEN
    assert reopened["allotment_run_count"] == 1

    reclosed = validate_success(
        client.close_order_period(ctx.period_id, None, ctx.underwriter_headers), 200
    )
    assert reclosed["status"] == OrderPeriodStatus.CLOSED
    assert reclosed["allotment_run_count"] == 2
    assert reclosed["reopen_reason"] == REOPEN_REASON


def test_reopen_is_refused_once_the_clock_reaches_the_close(client, compliance):
    """PRD section 3.7: "The period must be `CLOSED`, or `ERR_ORDER_PERIOD_INVALID_STATE` is reported; the deal must still be in `PRICING_COMPETITIVE` or `PRICING_NEGOTIATED`, or `ERR_DEAL_INVALID_STATE` is reported; and the logical clock must still be strictly before `closes_at`, or `ERR_ORDER_PERIOD_WINDOW_CLOSED` is reported — a book whose window has elapsed cannot be reopened, only settled or cancelled."

    Design: Corner/endpoints/order_period_reopen_is_conditional_on_the_logical_clock
    """
    ctx = _closed_negotiated_book(client)
    fx.reopen_period(client, ctx.period_id, REOPEN_REASON)
    reclosed = fx.close_period(client, ctx.period_id, ctx.underwriter_headers)
    assert reclosed["status"] == OrderPeriodStatus.CLOSED

    # Nothing about the period changes: only the clock advances to closes_at,
    # which is no longer strictly before it.
    fx.set_clock(client, BOOK_CLOSES_AT)
    response = client.reopen_order_period(
        ctx.period_id, f.reopen_payload(LATE_REOPEN_REASON), compliance
    )
    validate_error(response, ERR_ORDER_PERIOD_WINDOW_CLOSED)

    settled = fx.read_period(client, ctx.period_id, compliance)
    assert settled["status"] == OrderPeriodStatus.CLOSED
    assert settled["allotment_run_count"] == 2
    assert settled["reopen_reason"] == REOPEN_REASON
    assert_version(settled, reclosed["version"], "order period")
