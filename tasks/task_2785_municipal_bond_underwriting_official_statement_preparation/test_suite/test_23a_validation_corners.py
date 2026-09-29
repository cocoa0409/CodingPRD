"""Validation corners, first half: schema bounds, natural keys and the MSRB gates.

Every test in this module translates exactly one instance of the CORNER design
index section ``validations`` and carries that instance's name on its
``Design:`` line. Nothing here is a smoke or RBAC probe: each body drives the
world to the precise shape the instance describes and then asserts the outcome
PRD.md uniquely derives for it.
"""

from datetime import timedelta

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CALL_FEATURE_INVALID,
    ERR_DENOMINATION_INVALID,
    ERR_DUPLICATE_MSRB_REGISTRATION,
    ERR_DUPLICATE_RATING_ENGAGEMENT,
    ERR_DUPLICATE_SERIES_DESIGNATION,
    ERR_DUPLICATE_SYNDICATE_MEMBER,
    ERR_FIRM_NOT_FOUND,
    ERR_FIRM_SUSPENDED,
    ERR_INVALID_PAGINATION,
    ERR_MA_UNDERWRITER_CONFLICT,
    ERR_MATURITY_DATE_UNALIGNED,
    ERR_ORDER_PERIOD_WINDOW_CLOSED,
    ERR_PAR_SCHEDULE_MISMATCH,
    ERR_SALE_METHOD_CONFLICT,
    ERR_SENIOR_MANAGER_REQUIRED,
    ERR_TRANCHE_SEQUENCE_CONFLICT,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_money,
    assert_pagination,
    assert_price,
    assert_timestamps_equal,
    assert_whole_denomination,
    ids_of,
)
from test_helpers.constants import (
    BOND_PAR_USD,
    CALL_PRICE_MAX,
    CALL_PRICE_MIN,
    CANONICAL_EXPECTED_PAR_USD,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    CLOCK_EPOCH,
    DATED_DATE,
    DEFAULT_OFFSET,
    LIABILITY_PCT_TOTAL,
    MAX_LIMIT,
    MIN_DENOMINATION_USD,
    MIN_LIMIT,
    TRANCHE_1_MATURITY_DATE,
    TRANCHE_1_YIELD_PCT,
    TRANCHE_2_CALL_PERIODS,
    TRANCHE_2_COUPON_PCT,
    TRANCHE_2_FIRST_CALL_DATE,
    TRANCHE_2_MATURITY_DATE,
    TRANCHE_2_PERIODS,
    TRANCHE_2_YIELD_PCT,
    iso_utc,
    parse_iso,
    plus_days,
    plus_hours,
    plus_semiannual,
)
from test_helpers.test_users import make_issuer_official_headers
from test_helpers.types import (
    DealStatus,
    EngagementStatus,
    FirmType,
    GrossSpreadBasis,
    MemberRole,
    OrderPeriodStatus,
    OrderType,
    PeriodType,
    PriorityPolicy,
    RatingAgency,
    SaleMethod,
    TaxStatus,
)

# --- The calendar the design index uses for the order book ------------------
# The logical clock starts at 2026-08-01T00:00:00Z, so the design index's
# 2026-08-05 book day is four days on (PRD section 2.4).
BOOK_DAY = plus_days(CLOCK_EPOCH, 4)
RETAIL_OPENS_AT = plus_hours(BOOK_DAY, 9)
RETAIL_CLOSES_AT = plus_hours(BOOK_DAY, 12)
INSTITUTIONAL_OPENS_AT = plus_hours(BOOK_DAY, 13)
INSTITUTIONAL_CLOSES_AT = plus_hours(BOOK_DAY, 17)
CLOCK_INSIDE_WINDOW = plus_hours(BOOK_DAY, 14)

# One order of two hundred bonds, a whole multiple of the minimum denomination.
ORDER_PAR_USD = 200 * MIN_DENOMINATION_USD

# --- Maturity dates on and off the semiannual grid --------------------------
ONE_PERIOD_MATURITY_DATE = plus_semiannual(DATED_DATE, 1)
MID_MATURITY_DATE = plus_semiannual(DATED_DATE, 30)
# 2036-09-01: one calendar month past the twentieth semiannual anniversary, so
# a hundred and twenty-one months out and on no six-month grid point at all.
UNALIGNED_DATE = plus_days(TRANCHE_2_FIRST_CALL_DATE, 31)

# A call price one thousandth above the inclusive 103.000 ceiling.
CALL_PRICE_ABOVE_CEILING = CALL_PRICE_MAX + 0.001

# 5,001,000 dollars: a whole multiple of the 1,000-dollar bond but not of the
# 5,000-dollar minimum denomination (PRD section 2.6).
OFF_DENOMINATION_PRINCIPAL_USD = CANONICAL_TRANCHE_PRINCIPAL_USD + BOND_PAR_USD

# A schedule that foots to 9,000,000 against a 10,000,000 authorisation.
SHORT_TRANCHE_PRINCIPAL_USD = 4000000
TOP_UP_TRANCHE_PRINCIPAL_USD = 1000000

# Syndicate shares that keep the ACTIVE liability sum at eighty percent, so no
# fiscal bound is in play when a uniqueness rule fires (PRD section 3.6).
SEATED_LIABILITY_PCT = 60.0000
CHALLENGER_LIABILITY_PCT = 20.0000


def _empty_draft_deal(client, **deal_overrides):
    """A DRAFT deal dated 2026-08-01 whose maturity schedule is still empty."""
    return fx.draft_deal(client, tranches=False, **deal_overrides)


def _one_millisecond_before(instant):
    """The instant one millisecond earlier, at the API's millisecond precision."""
    return iso_utc(parse_iso(instant) - timedelta(milliseconds=1))


def _callable_tranche_payload(sequence_number=1, **overrides):
    """A forty-period maturity carrying whatever call fields the caller supplies."""
    return f.tranche_payload(
        sequence_number,
        TRANCHE_2_MATURITY_DATE,
        coupon_rate_pct=TRANCHE_2_COUPON_PCT,
        yield_pct=TRANCHE_2_YIELD_PCT,
        **overrides,
    )


def _assert_schedule_is_empty(client, ctx):
    """The deal's maturity schedule holds no rows at all."""
    rows, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert rows == [], f"expected an empty maturity schedule, got {ids_of(rows)}"
    assert_pagination(meta, total_count=0)


def _seat_senior_manager(client, ctx):
    """Seat the underwriting firm as the deal's single SENIOR_MANAGER."""
    ctx.senior_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.advisor_headers,
        MemberRole.SENIOR_MANAGER,
        liability_pct=SEATED_LIABILITY_PCT,
        takedown_share_pct=SEATED_LIABILITY_PCT,
        priority_rank=1,
    )
    return ctx.senior_member


def _assert_single_seat(client, ctx):
    """Exactly one syndicate seat survives on the deal."""
    rows, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, ctx.advisor_headers)
    )
    assert len(rows) == 1, f"expected one syndicate seat, got {ids_of(rows)}"
    assert_pagination(meta, total_count=1)

def test_pagination_bounds_outside_the_inclusive_range_are_rejected(client, compliance):
    """PRD section 2.3: "A `limit` outside the inclusive range 1 through 100, a non-integer `limit`, a negative `offset`, or a non-integer `offset` is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/validations/pagination_parameters_outside_their_bounds_rejected
    """
    fx.register_issuer(client)

    # One row exists, so a working list call would return it: the rejection can
    # only come from the pagination window itself.
    for params in ({"limit": MIN_LIMIT - 1}, {"limit": MAX_LIMIT + 1}, {"offset": -1}):
        response = client.list_issuers(compliance, **params)
        validate_error(response, ERR_INVALID_PAGINATION, 422)


def test_pagination_bounds_at_their_inclusive_edges_are_accepted(client, compliance):
    """PRD section 2.3: "List responses populate `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/validations/pagination_parameters_outside_their_bounds_rejected
    """
    issuer = fx.register_issuer(client)

    # Both ends of the inclusive range are legal and are echoed back verbatim.
    for limit in (MIN_LIMIT, MAX_LIMIT):
        rows, meta = validate_paginated(client.list_issuers(compliance, limit=limit))
        assert ids_of(rows) == [issuer["id"]]
        assert_pagination(
            meta, total_count=1, has_more=False, limit=limit, offset=DEFAULT_OFFSET
        )


def test_msrb_registration_id_is_unique_across_every_firm_type(client, compliance):
    """PRD section 3.1: "A collision on that identifier is rejected with `ERR_DUPLICATE_MSRB_REGISTRATION`."

    Design: Corner/validations/duplicate_msrb_registration_id_rejected
    """
    msrb_id = f.unique_msrb_registration_id()
    seated = fx.register_firm(
        client, FirmType.UNDERWRITER, msrb_registration_id=msrb_id
    )
    assert seated["msrb_registration_id"] == msrb_id

    # A different name and a different firm_type do not buy a second claim on
    # the identifier: uniqueness is system-wide, not per firm_type.
    response = client.create_firm(
        f.firm_payload(FirmType.MUNICIPAL_ADVISOR, msrb_registration_id=msrb_id),
        compliance,
    )
    validate_error(response, ERR_DUPLICATE_MSRB_REGISTRATION, 422)

    rows, meta = validate_paginated(client.list_firms(compliance))
    assert ids_of(rows) == [seated["id"]]
    assert_pagination(meta, total_count=1)


def test_series_designation_collides_within_one_issuer(client, participants):
    """PRD section 3.2: "Creation takes the `issuer_id` of the governmental issuer, a `series_designation` such as `Series 2026A` (one to forty characters, not blank, and unique among the deals of that same issuer — a collision reports `ERR_DUPLICATE_SERIES_DESIGNATION`), a `tax_status` of `TAX_EXEMPT`, `TAXABLE`, or `AMT`, a `dated_date` given as an ISO 8601 UTC instant with three fractional digits, and an `expected_par_amount_usd` that must be strictly positive and a whole multiple of five thousand dollars."

    Design: Corner/validations/duplicate_series_designation_is_scoped_to_the_issuer
    """
    ctx = participants
    designation = f.unique_series_designation()
    first = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        series_designation=designation,
    )

    # Same issuer, same designation, but every other input differs: the natural
    # key is the issuer and the designation together and nothing else.
    response = client.create_deal(
        f.deal_payload(
            ctx.issuer_id,
            series_designation=designation,
            municipal_advisor_firm_id=ctx.advisor_firm_id,
            tax_status=TaxStatus.TAXABLE,
        ),
        ctx.issuer_headers,
    )
    validate_error(response, ERR_DUPLICATE_SERIES_DESIGNATION, 422)

    rows, meta = validate_paginated(client.list_deals(ctx.issuer_headers))
    assert ids_of(rows) == [first["id"]]
    assert_pagination(meta, total_count=1)


def test_series_designation_is_free_on_a_second_issuer(client, participants):
    """PRD section 3.2: "Creation takes the `issuer_id` of the governmental issuer, a `series_designation` such as `Series 2026A` (one to forty characters, not blank, and unique among the deals of that same issuer — a collision reports `ERR_DUPLICATE_SERIES_DESIGNATION`), a `tax_status` of `TAX_EXEMPT`, `TAXABLE`, or `AMT`, a `dated_date` given as an ISO 8601 UTC instant with three fractional digits, and an `expected_par_amount_usd` that must be strictly positive and a whole multiple of five thousand dollars."

    Design: Corner/validations/duplicate_series_designation_is_scoped_to_the_issuer
    """
    ctx = participants
    designation = f.unique_series_designation()
    fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        series_designation=designation,
    )

    # A second governmental issuer may reuse the designation, because the
    # uniqueness scope is the issuer and not the system.
    other_issuer = fx.register_issuer(client)
    data = validate_success(
        client.create_deal(
            f.deal_payload(
                other_issuer["id"],
                series_designation=designation,
                municipal_advisor_firm_id=ctx.advisor_firm_id,
            ),
            make_issuer_official_headers(other_issuer["id"]),
        ),
        201,
    )
    assert data["series_designation"] == designation
    assert data["issuer_id"] == other_issuer["id"]
    assert data["status"] == DealStatus.DRAFT
    assert_common_fields(data, "deal")


def test_a_single_period_maturity_is_aligned_and_accepted(client):
    """PRD section 3.2: "Two intermediate period counts are stored: `periods_to_maturity` is the whole number of semiannual periods from the deal's `dated_date` to the maturity's `maturity_date`, and `periods_to_call` is the same count taken to `first_call_date`, or null when the maturity is not callable."

    Design: Corner/validations/aligned_maturity_and_call_dates_are_accepted
    """
    ctx = _empty_draft_deal(client)

    # The shortest legal maturity: exactly one six-month period after the dated
    # date, which is the boundary of "strictly after" and "on the grid" at once.
    data = validate_success(
        client.create_maturity_tranche(
            ctx.deal_id,
            f.tranche_payload(1, ONE_PERIOD_MATURITY_DATE),
            ctx.advisor_headers,
        ),
        201,
    )
    assert_timestamps_equal(data["maturity_date"], ONE_PERIOD_MATURITY_DATE)
    assert data["periods_to_maturity"] == 1
    assert data["is_callable"] is False
    assert data["periods_to_call"] is None
    assert data["first_call_date"] is None
    assert data["call_price_pct"] is None


def test_a_call_price_at_the_inclusive_ceiling_is_accepted(client):
    """PRD section 3.2: "When it is true, both `first_call_date` and `call_price_pct` become required, `first_call_date` must land on a semiannual anniversary of the deal's `dated_date` and must fall strictly before `maturity_date`, and `call_price_pct` must lie between 100.000 and 103.000 inclusive."

    Design: Corner/validations/aligned_maturity_and_call_dates_are_accepted
    """
    ctx = _empty_draft_deal(client)

    # A twenty-year maturity callable at its tenth anniversary, priced at the
    # top of the permitted band: both dates on the grid, the call strictly
    # earlier, and the price exactly at the inclusive ceiling.
    data = validate_success(
        client.create_maturity_tranche(
            ctx.deal_id,
            _callable_tranche_payload(
                1,
                is_callable=True,
                first_call_date=TRANCHE_2_FIRST_CALL_DATE,
                call_price_pct=CALL_PRICE_MAX,
            ),
            ctx.advisor_headers,
        ),
        201,
    )
    assert data["is_callable"] is True
    assert_timestamps_equal(data["first_call_date"], TRANCHE_2_FIRST_CALL_DATE)
    assert_price(data["call_price_pct"], CALL_PRICE_MAX, "call_price_pct")
    assert data["periods_to_maturity"] == TRANCHE_2_PERIODS
    assert data["periods_to_call"] == TRANCHE_2_CALL_PERIODS


def test_the_deals_advisor_firm_may_not_take_a_syndicate_seat(client):
    """PRD section 2.8: "The system enforces the prohibition symmetrically in both directions: a firm named as a deal's `municipal_advisor_firm_id` may not be added as a `SyndicateMember` of that deal in any `member_role`, and a deal may not be opened naming as its municipal advisor a firm that already holds a `SyndicateMember` row on that deal."

    Design: Corner/validations/municipal_advisor_firm_may_not_sit_on_the_syndicate
    """
    # A DUAL_REGISTERED firm is licensed to underwrite, so nothing but Rule G-23
    # stands between it and the seat it is asking for.
    ctx = fx.draft_deal(
        client,
        fx.participants(client, advisor_firm_type=FirmType.DUAL_REGISTERED),
        tranches=False,
    )
    assert ctx.advisor_firm["firm_type"] == FirmType.DUAL_REGISTERED
    assert ctx.deal["municipal_advisor_firm_id"] == ctx.advisor_firm_id

    # The least powerful seat in the syndicate is refused just as flatly as the
    # senior manager's would be: the rule holds in any member_role.
    response = client.create_syndicate_member(
        ctx.deal_id,
        f.syndicate_member_payload(
            ctx.advisor_firm_id,
            MemberRole.SELLING_GROUP,
            liability_pct=CHALLENGER_LIABILITY_PCT,
            takedown_share_pct=CHALLENGER_LIABILITY_PCT,
            priority_rank=3,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_MA_UNDERWRITER_CONFLICT, 422)

    rows, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, ctx.advisor_headers)
    )
    assert rows == []
    assert_pagination(meta, total_count=0)


def test_a_suspended_firm_may_not_be_named_as_the_advisor_at_deal_creation(
    client, compliance
):
    """PRD section 2.8: "It may not be engaged as a deal's municipal advisor when the deal is opened, it may not be added to a syndicate, it may not be the advisor of record when a sale method is designated, and it may not be the acting underwriter on a pricing request."

    Design: Corner/validations/suspended_firm_may_not_be_engaged_as_municipal_advisor
    """
    suspended = fx.register_firm(
        client, FirmType.MUNICIPAL_ADVISOR, is_suspended=True
    )
    assert suspended["is_suspended"] is True

    issuer = fx.register_issuer(client)
    issuer_headers = make_issuer_official_headers(issuer["id"])

    # The firm is a perfectly eligible MUNICIPAL_ADVISOR in every respect except
    # its standing, so the suspension is the only live objection.
    response = client.create_deal(
        f.deal_payload(issuer["id"], municipal_advisor_firm_id=suspended["id"]),
        issuer_headers,
    )
    validate_error(response, ERR_FIRM_SUSPENDED, 422)

    rows, meta = validate_paginated(client.list_deals(issuer_headers))
    assert rows == []
    assert_pagination(meta, total_count=0)


def test_a_missing_advisor_firm_outranks_the_suspension_gate(client):
    """PRD section 2.5: "Every foreign key supplied in a body names an existing row — `issuer_id`, `municipal_advisor_firm_id`, `firm_id`, `maturity_tranche_id`, `syndicate_member_id`, `refunded_tranche_id`, `parent_section_id`, and every member of `insured_tranche_ids`."

    Design: Corner/validations/suspended_firm_may_not_be_engaged_as_municipal_advisor
    """
    issuer = fx.register_issuer(client)
    issuer_headers = make_issuer_official_headers(issuer["id"])

    # A firm that does not exist cannot be examined for suspension: existence at
    # tier 7 is reported before MSRB conduct at tier 12.
    response = client.create_deal(
        f.deal_payload(issuer["id"], municipal_advisor_firm_id=NON_EXISTENT_UUID),
        issuer_headers,
    )
    error = validate_error(response, ERR_FIRM_NOT_FOUND, 404)
    assert error["error_id"] != ERR_FIRM_SUSPENDED

    rows, meta = validate_paginated(client.list_deals(issuer_headers))
    assert rows == []
    assert_pagination(meta, total_count=0)


def test_competitive_designation_succeeds_with_an_independent_advisor(
    client, structuring_deal
):
    """PRD section 3.6: "The deal's `municipal_advisor_firm_id` must be non-null and the firm it names must have a `firm_type` of `MUNICIPAL_ADVISOR` or `DUAL_REGISTERED`; a missing or ineligible advisor is refused with `ERR_MA_ENGAGEMENT_REQUIRED`."

    Design: Corner/validations/competitive_designation_requires_an_engaged_municipal_advisor
    """
    ctx = structuring_deal
    assert ctx.deal["municipal_advisor_firm_id"] == ctx.advisor_firm_id
    assert ctx.advisor_firm["firm_type"] in FirmType.ADMITS_ADVISOR
    assert ctx.advisor_firm["is_suspended"] is False
    before = ctx.deal["version"]

    # An engaged, eligible, unsuspended advisor and no syndicate: every guard on
    # the competitive branch is satisfied, so the designation carries.
    data = validate_success(
        client.designate_sale_method(
            ctx.deal_id,
            f.sale_method_payload(SaleMethod.COMPETITIVE),
            ctx.issuer_headers,
        ),
        200,
    )
    assert data["status"] == DealStatus.PRICING_COMPETITIVE
    assert data["sale_method"] == SaleMethod.COMPETITIVE
    assert data["gross_spread_basis"] == GrossSpreadBasis.COMPETITIVE
    assert data["requires_notice_of_sale"] is True
    assert data["requires_g17_letter"] is False
    assert data["version"] == before + 1


def test_negotiated_designation_needs_a_senior_manager_not_merely_a_syndicate(
    client, structuring_deal
):
    """PRD section 3.6: "It therefore requires the syndicate to have a head: exactly one `SyndicateMember` on the deal with `member_role` `SENIOR_MANAGER` and `status` `ACTIVE` must exist, and neither zero nor more than one satisfies the rule; a failure is refused with `ERR_SENIOR_MANAGER_REQUIRED`."

    Design: Corner/validations/negotiated_designation_requires_exactly_one_senior_manager
    """
    ctx = structuring_deal
    # A syndicate exists and is ACTIVE, but its only seat is a co-manager: the
    # count of SENIOR_MANAGER seats is zero, which the rule rejects.
    fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.advisor_headers,
        MemberRole.CO_MANAGER,
        liability_pct=SEATED_LIABILITY_PCT,
        takedown_share_pct=SEATED_LIABILITY_PCT,
        priority_rank=1,
    )

    response = client.designate_sale_method(
        ctx.deal_id, f.sale_method_payload(SaleMethod.NEGOTIATED), ctx.advisor_headers
    )
    validate_error(response, ERR_SENIOR_MANAGER_REQUIRED, 422)

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert deal["status"] == DealStatus.STRUCTURING
    assert deal["sale_method"] == SaleMethod.UNDETERMINED
    assert deal["gross_spread_basis"] == GrossSpreadBasis.UNDETERMINED
    assert deal["requires_g17_letter"] is False
    assert deal["version"] == ctx.deal["version"]


def test_competitive_designation_is_barred_by_a_pre_arranged_syndicate(
    client, structuring_deal
):
    """PRD section 3.6: "And no `SyndicateMember` row may exist on the deal at all, since a pre-arranged syndicate is incompatible with a competitive bid; an existing seat is refused with `ERR_SALE_METHOD_CONFLICT`."

    Design: Corner/validations/sale_method_may_not_be_re_designated_and_competitive_bars_a_syndicate
    """
    ctx = structuring_deal
    _seat_senior_manager(client, ctx)

    # The advisor is engaged and eligible, so the single surviving objection is
    # the seat that a competitive bid cannot tolerate.
    response = client.designate_sale_method(
        ctx.deal_id, f.sale_method_payload(SaleMethod.COMPETITIVE), ctx.advisor_headers
    )
    validate_error(response, ERR_SALE_METHOD_CONFLICT, 422)

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert deal["status"] == DealStatus.STRUCTURING
    assert deal["sale_method"] == SaleMethod.UNDETERMINED
    assert deal["requires_notice_of_sale"] is False
    assert deal["version"] == ctx.deal["version"]


def test_a_designated_deal_may_not_be_re_designated(client, competitive_deal):
    """PRD section 3.6: "A deal whose `sale_method` is already `COMPETITIVE` or `NEGOTIATED` may not be re-designated; a second designation is refused with `ERR_SALE_METHOD_CONFLICT`."

    Design: Corner/validations/sale_method_may_not_be_re_designated_and_competitive_bars_a_syndicate
    """
    ctx = competitive_deal
    assert ctx.deal["sale_method"] == SaleMethod.COMPETITIVE
    assert ctx.deal["status"] == DealStatus.PRICING_COMPETITIVE

    # The branching decision is taken once and for all: naming the other branch
    # afterwards is refused, and the first designation survives untouched.
    response = client.designate_sale_method(
        ctx.deal_id, f.sale_method_payload(SaleMethod.NEGOTIATED), ctx.advisor_headers
    )
    validate_error(response, ERR_SALE_METHOD_CONFLICT, 422)

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert deal["sale_method"] == SaleMethod.COMPETITIVE
    assert deal["gross_spread_basis"] == GrossSpreadBasis.COMPETITIVE
    assert deal["status"] == DealStatus.PRICING_COMPETITIVE
    assert deal["requires_notice_of_sale"] is True
    assert deal["requires_g17_letter"] is False
    assert deal["version"] == ctx.deal["version"]


def test_a_retail_period_is_refused_on_a_competitive_deal(client, competitive_deal):
    """PRD section 3.7: "Scheduling imposes no deal-state precondition of its own — the deal-state gate arrives when the book is opened — but a `RETAIL` period may not be scheduled on a deal whose `sale_method` is `COMPETITIVE`, and such an attempt is refused with `ERR_SALE_METHOD_CONFLICT`."

    Design: Corner/validations/retail_order_period_rejected_on_a_competitive_deal
    """
    ctx = competitive_deal
    response = client.create_order_period(
        ctx.deal_id,
        f.order_period_payload(
            RETAIL_OPENS_AT,
            RETAIL_CLOSES_AT,
            PeriodType.RETAIL,
            priority_policy=PriorityPolicy.RETAIL_ONLY,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_SALE_METHOD_CONFLICT, 422)

    # The identical window is legal for the institutional class, so the
    # rejection turns on `period_type` alone and not on the calendar.
    data = validate_success(
        client.create_order_period(
            ctx.deal_id,
            f.order_period_payload(
                INSTITUTIONAL_OPENS_AT,
                INSTITUTIONAL_CLOSES_AT,
                PeriodType.INSTITUTIONAL,
                priority_policy=PriorityPolicy.STANDARD_PRIORITY,
            ),
            ctx.advisor_headers,
        ),
        201,
    )
    assert data["period_type"] == PeriodType.INSTITUTIONAL
    assert data["status"] == OrderPeriodStatus.SCHEDULED

    rows, meta = validate_paginated(
        client.list_deal_order_periods(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [data["id"]]
    assert_pagination(meta, total_count=1)


def test_a_retail_period_is_accepted_on_a_negotiated_deal(client, negotiated_deal):
    """PRD section 3.6: "A negotiated deal may run both `RETAIL` and `INSTITUTIONAL` order periods."

    Design: Corner/validations/retail_order_period_rejected_on_a_competitive_deal
    """
    ctx = negotiated_deal
    assert ctx.deal["sale_method"] == SaleMethod.NEGOTIATED

    # The same retail window the competitive deal refused is scheduled without
    # objection here, which is what makes the branch-specific rule falsifiable.
    data = validate_success(
        client.create_order_period(
            ctx.deal_id,
            f.order_period_payload(
                RETAIL_OPENS_AT,
                RETAIL_CLOSES_AT,
                PeriodType.RETAIL,
                priority_policy=PriorityPolicy.RETAIL_ONLY,
            ),
            ctx.advisor_headers,
        ),
        201,
    )
    assert data["period_type"] == PeriodType.RETAIL
    assert data["priority_policy"] == PriorityPolicy.RETAIL_ONLY
    assert data["status"] == OrderPeriodStatus.SCHEDULED
    assert data["orders_received_count"] == 0
    assert_common_fields(data, "order_period")


def test_an_order_at_exactly_closes_at_is_refused(client, negotiated_deal):
    """PRD section 3.7: "The period must be `OPEN`, or `ERR_ORDER_PERIOD_INVALID_STATE` is reported, and the logical clock must be strictly before `closes_at`, or `ERR_ORDER_PERIOD_WINDOW_CLOSED` is reported — an open period whose window has expired on the clock accepts nothing further even though its `status` still reads `OPEN`."

    Design: Corner/validations/order_placed_after_the_window_closes_rejected
    """
    ctx = negotiated_deal
    period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            INSTITUTIONAL_OPENS_AT,
            INSTITUTIONAL_CLOSES_AT,
            PeriodType.INSTITUTIONAL,
            priority_policy=PriorityPolicy.STANDARD_PRIORITY,
        ),
    )
    fx.set_clock(client, CLOCK_INSIDE_WINDOW)
    fx.open_period(client, period["id"], ctx.underwriter_headers)

    # One millisecond before the close the clock is still strictly earlier, so
    # the book accepts the order and stamps it with that very instant.
    last_instant = _one_millisecond_before(INSTITUTIONAL_CLOSES_AT)
    fx.set_clock(client, last_instant)
    accepted = fx.place_order(
        client,
        period["id"],
        ctx.tranche_ids[0],
        ctx.member_ids[0],
        ctx.underwriter_headers,
        OrderType.INSTITUTIONAL_PRIORITY,
        ORDER_PAR_USD,
        price_or_yield_pct=TRANCHE_1_YIELD_PCT,
    )
    assert_timestamps_equal(accepted["submitted_at"], last_instant)

    # At `closes_at` itself the clock is no longer strictly before it, and the
    # boundary is exclusive.
    fx.set_clock(client, INSTITUTIONAL_CLOSES_AT)
    live = fx.read_period(client, period["id"], ctx.underwriter_headers)
    response = client.create_order(
        period["id"],
        f.order_payload(
            ctx.tranche_ids[0],
            ctx.member_ids[0],
            live["version"],
            OrderType.INSTITUTIONAL_PRIORITY,
            ORDER_PAR_USD,
            price_or_yield_pct=TRANCHE_1_YIELD_PCT,
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_ORDER_PERIOD_WINDOW_CLOSED, 422)

    after = fx.read_period(client, period["id"], ctx.underwriter_headers)
    assert after["status"] == OrderPeriodStatus.OPEN
    assert after["orders_received_count"] == 1


def test_a_maturity_date_off_the_semiannual_grid_is_refused(client):
    """PRD section 3.2: "The `maturity_date` itself must be strictly after the deal's `dated_date` and must land exactly on a semiannual anniversary of it — that is, a whole number of six-month periods after the dated date, never a fraction of one; a date that misses the anniversary is rejected with `ERR_MATURITY_DATE_UNALIGNED`."

    Design: Corner/validations/unaligned_maturity_date_rejected
    """
    ctx = _empty_draft_deal(client)

    # One calendar month past a genuine anniversary: comfortably after the dated
    # date and a whole number of months out, but a fraction of a period off.
    response = client.create_maturity_tranche(
        ctx.deal_id, f.tranche_payload(1, UNALIGNED_DATE), ctx.advisor_headers
    )
    validate_error(response, ERR_MATURITY_DATE_UNALIGNED, 422)
    _assert_schedule_is_empty(client, ctx)


def test_an_unaligned_first_call_date_reports_the_temporal_error(client):
    """PRD section 3.2: "Any breach of that symmetry — a missing call field on a callable maturity, a stray call field on a non-callable one, a call date not before maturity, or a call price outside the permitted band — is rejected with `ERR_CALL_FEATURE_INVALID`, while a misaligned `first_call_date` is reported as `ERR_MATURITY_DATE_UNALIGNED` under the earlier temporal tier."

    Design: Corner/validations/unaligned_maturity_date_rejected
    """
    ctx = _empty_draft_deal(client)

    # The maturity itself is on the grid and the call price is inside the band,
    # so the only defect is the call date's alignment — reported by the temporal
    # tier, not by the structural call-coherence rule.
    response = client.create_maturity_tranche(
        ctx.deal_id,
        _callable_tranche_payload(
            1,
            is_callable=True,
            first_call_date=UNALIGNED_DATE,
            call_price_pct=CALL_PRICE_MIN,
        ),
        ctx.advisor_headers,
    )
    error = validate_error(response, ERR_MATURITY_DATE_UNALIGNED, 422)
    assert error["error_id"] != ERR_CALL_FEATURE_INVALID
    _assert_schedule_is_empty(client, ctx)


def test_a_callable_maturity_without_call_fields_is_refused(client):
    """PRD section 3.2: "When it is true, both `first_call_date` and `call_price_pct` become required, `first_call_date` must land on a semiannual anniversary of the deal's `dated_date` and must fall strictly before `maturity_date`, and `call_price_pct` must lie between 100.000 and 103.000 inclusive."

    Design: Corner/validations/incoherent_call_feature_rejected
    """
    ctx = _empty_draft_deal(client)
    response = client.create_maturity_tranche(
        ctx.deal_id, _callable_tranche_payload(1, is_callable=True), ctx.advisor_headers
    )
    validate_error(response, ERR_CALL_FEATURE_INVALID, 422)
    _assert_schedule_is_empty(client, ctx)


def test_a_call_price_above_the_band_is_refused(client):
    """PRD section 3.2: "Any breach of that symmetry — a missing call field on a callable maturity, a stray call field on a non-callable one, a call date not before maturity, or a call price outside the permitted band — is rejected with `ERR_CALL_FEATURE_INVALID`, while a misaligned `first_call_date` is reported as `ERR_MATURITY_DATE_UNALIGNED` under the earlier temporal tier."

    Design: Corner/validations/incoherent_call_feature_rejected
    """
    ctx = _empty_draft_deal(client)

    # One thousandth of a point above the inclusive ceiling that the previous
    # accepted case sat exactly on.
    response = client.create_maturity_tranche(
        ctx.deal_id,
        _callable_tranche_payload(
            1,
            is_callable=True,
            first_call_date=TRANCHE_2_FIRST_CALL_DATE,
            call_price_pct=CALL_PRICE_ABOVE_CEILING,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_CALL_FEATURE_INVALID, 422)
    _assert_schedule_is_empty(client, ctx)


def test_a_call_date_equal_to_the_maturity_date_is_refused(client):
    """PRD section 3.2: "Any breach of that symmetry — a missing call field on a callable maturity, a stray call field on a non-callable one, a call date not before maturity, or a call price outside the permitted band — is rejected with `ERR_CALL_FEATURE_INVALID`, while a misaligned `first_call_date` is reported as `ERR_MATURITY_DATE_UNALIGNED` under the earlier temporal tier."

    Design: Corner/validations/incoherent_call_feature_rejected
    """
    ctx = _empty_draft_deal(client)

    # An anniversary date, so the temporal tier is satisfied, but not *strictly*
    # before maturity: the boundary of "before" is exclusive.
    response = client.create_maturity_tranche(
        ctx.deal_id,
        _callable_tranche_payload(
            1,
            is_callable=True,
            first_call_date=TRANCHE_2_MATURITY_DATE,
            call_price_pct=CALL_PRICE_MIN,
        ),
        ctx.advisor_headers,
    )
    error = validate_error(response, ERR_CALL_FEATURE_INVALID, 422)
    assert error["error_id"] != ERR_MATURITY_DATE_UNALIGNED
    _assert_schedule_is_empty(client, ctx)


def test_stray_call_fields_on_a_non_callable_maturity_are_refused(client):
    """PRD section 3.2: "When `is_callable` is false, both `first_call_date` and `call_price_pct` must be absent, and both remain null on the stored row."

    Design: Corner/validations/incoherent_call_feature_rejected
    """
    ctx = _empty_draft_deal(client)

    # Both call fields are individually impeccable — an anniversary date and a
    # price at the floor of the band — but the maturity is not callable at all.
    response = client.create_maturity_tranche(
        ctx.deal_id,
        _callable_tranche_payload(
            1,
            is_callable=False,
            first_call_date=TRANCHE_2_FIRST_CALL_DATE,
            call_price_pct=CALL_PRICE_MIN,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_CALL_FEATURE_INVALID, 422)
    _assert_schedule_is_empty(client, ctx)


def test_a_principal_off_the_minimum_denomination_is_refused(client):
    """PRD section 2.6: "The **minimum denomination** in which par may be requested or allotted is USD 5,000: a maturity's `principal_amount_usd` and an order's `par_requested_usd` must each be a positive whole multiple of five thousand dollars, as must a deal's `expected_par_amount_usd`, and every allotted amount the waterfall produces is likewise an exact multiple of five thousand."

    Design: Corner/validations/par_amounts_off_the_minimum_denomination_rejected
    """
    ctx = _empty_draft_deal(client)

    # 5,001,000 is a whole number of thousand-dollar bonds, so only the stricter
    # five-thousand-dollar denomination can be what refuses it.
    assert OFF_DENOMINATION_PRINCIPAL_USD % BOND_PAR_USD == 0
    assert OFF_DENOMINATION_PRINCIPAL_USD % MIN_DENOMINATION_USD != 0
    response = client.create_maturity_tranche(
        ctx.deal_id,
        f.tranche_payload(
            1,
            TRANCHE_1_MATURITY_DATE,
            principal_amount_usd=OFF_DENOMINATION_PRINCIPAL_USD,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_DENOMINATION_INVALID, 422)
    _assert_schedule_is_empty(client, ctx)

    # The same maturity at a whole multiple is accepted, so the rejection turned
    # on the thousand-dollar remainder and nothing else.
    data = validate_success(
        client.create_maturity_tranche(
            ctx.deal_id,
            f.tranche_payload(
                1,
                TRANCHE_1_MATURITY_DATE,
                principal_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
            ),
            ctx.advisor_headers,
        ),
        201,
    )
    assert_money(
        data["principal_amount_usd"],
        CANONICAL_TRANCHE_PRINCIPAL_USD,
        "principal_amount_usd",
    )
    assert_whole_denomination(data["principal_amount_usd"], "principal_amount_usd")


def _under_funded_schedule(client):
    """A DRAFT deal whose two maturities foot to 9,000,000 against 10,000,000."""
    ctx = _empty_draft_deal(client)
    assert_money(
        ctx.deal["expected_par_amount_usd"],
        CANONICAL_EXPECTED_PAR_USD,
        "expected_par_amount_usd",
    )
    fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.tranche_payload(1, TRANCHE_1_MATURITY_DATE),
    )
    fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.tranche_payload(
            2,
            MID_MATURITY_DATE,
            principal_amount_usd=SHORT_TRANCHE_PRINCIPAL_USD,
        ),
    )
    return ctx


def test_a_schedule_that_does_not_foot_to_the_authorisation_is_refused(client):
    """PRD section 3.2: "It requires at least one maturity on the deal, and it requires the schedule to foot to the authorisation exactly: the sum of `principal_amount_usd` over the deal's maturities must equal `expected_par_amount_usd` to the dollar, and any discrepancy in either direction is rejected with `ERR_PAR_SCHEDULE_MISMATCH`."

    Design: Corner/validations/par_schedule_must_match_the_authorized_amount
    """
    ctx = _under_funded_schedule(client)

    # Every individual maturity is legal; it is the sum that is a million short.
    response = client.submit_structure(ctx.deal_id, None, ctx.advisor_headers)
    validate_error(response, ERR_PAR_SCHEDULE_MISMATCH, 422)

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert deal["status"] == DealStatus.DRAFT
    assert_money(deal["par_amount_usd"], 0, "par_amount_usd")
    assert deal["version"] == ctx.deal["version"]


def test_a_schedule_topped_up_to_the_authorisation_is_accepted(client):
    """PRD section 3.2: "`Deal.par_amount_usd` is set to the sum of the maturities' `principal_amount_usd`."

    Design: Corner/validations/par_schedule_must_match_the_authorized_amount
    """
    ctx = _under_funded_schedule(client)

    # The missing million closes the gap to the dollar, and the same request that
    # was refused now carries.
    fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.tranche_payload(
            3,
            TRANCHE_2_MATURITY_DATE,
            principal_amount_usd=TOP_UP_TRANCHE_PRINCIPAL_USD,
            coupon_rate_pct=TRANCHE_2_COUPON_PCT,
            yield_pct=TRANCHE_2_YIELD_PCT,
        ),
    )
    data = validate_success(
        client.submit_structure(ctx.deal_id, None, ctx.advisor_headers), 200
    )
    assert data["status"] == DealStatus.STRUCTURING
    assert_money(data["par_amount_usd"], CANONICAL_EXPECTED_PAR_USD, "par_amount_usd")
    assert data["version"] == ctx.deal["version"] + 1


def _one_maturity_deal(client):
    """A DRAFT deal holding a single maturity at sequence one, thirty periods out."""
    ctx = _empty_draft_deal(client)
    ctx.first_tranche = fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.tranche_payload(1, MID_MATURITY_DATE),
    )
    return ctx


def test_a_reused_sequence_number_is_refused(client):
    """PRD section 3.2: "Each maturity carries a `sequence_number` from 1 through 40 that must be unique within the deal, and the schedule must be monotone: `maturity_date` has to increase strictly as `sequence_number` increases."

    Design: Corner/validations/tranche_sequence_and_maturity_order_must_agree
    """
    ctx = _one_maturity_deal(client)

    # A later maturity date, so monotonicity would be satisfied: the sole defect
    # is the sequence number the schedule already holds.
    response = client.create_maturity_tranche(
        ctx.deal_id,
        f.tranche_payload(
            1,
            TRANCHE_2_MATURITY_DATE,
            coupon_rate_pct=TRANCHE_2_COUPON_PCT,
            yield_pct=TRANCHE_2_YIELD_PCT,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_TRANCHE_SEQUENCE_CONFLICT, 422)

    rows, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [ctx.first_tranche["id"]]
    assert_pagination(meta, total_count=1)


def test_a_later_sequence_maturing_earlier_is_refused(client):
    """PRD section 3.2: "A reused sequence number or an out-of-order maturity date is rejected with `ERR_TRANCHE_SEQUENCE_CONFLICT`."

    Design: Corner/validations/tranche_sequence_and_maturity_order_must_agree
    """
    ctx = _one_maturity_deal(client)

    # A free sequence number, an aligned date and a legal principal: only the
    # monotonicity of date against sequence is broken.
    response = client.create_maturity_tranche(
        ctx.deal_id,
        f.tranche_payload(2, TRANCHE_1_MATURITY_DATE),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_TRANCHE_SEQUENCE_CONFLICT, 422)

    rows, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [ctx.first_tranche["id"]]
    assert_pagination(meta, total_count=1)


def test_a_firm_may_not_hold_two_seats_on_one_deal(client, draft_deal):
    """PRD section 3.6: "Uniqueness is enforced three ways — a firm may not hold more than one seat on the deal that is not `RESIGNED`, a deal may have at most one `SENIOR_MANAGER`, and `priority_rank` may not collide among `ACTIVE` members — and all three report `ERR_DUPLICATE_SYNDICATE_MEMBER`."

    Design: Corner/validations/duplicate_syndicate_seat_and_second_senior_manager_rejected
    """
    ctx = draft_deal
    seated = _seat_senior_manager(client, ctx)

    # A different role and a free priority_rank, and the two shares together
    # come to eighty percent, so no fiscal bound is in play.
    assert SEATED_LIABILITY_PCT + CHALLENGER_LIABILITY_PCT <= LIABILITY_PCT_TOTAL
    response = client.create_syndicate_member(
        ctx.deal_id,
        f.syndicate_member_payload(
            ctx.underwriter_firm_id,
            MemberRole.CO_MANAGER,
            liability_pct=CHALLENGER_LIABILITY_PCT,
            takedown_share_pct=CHALLENGER_LIABILITY_PCT,
            priority_rank=2,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_DUPLICATE_SYNDICATE_MEMBER, 422)

    rows, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [seated["id"]]
    assert_pagination(meta, total_count=1)


def test_a_second_senior_manager_is_refused(client, draft_deal):
    """PRD section 3.6: "Uniqueness is enforced three ways — a firm may not hold more than one seat on the deal that is not `RESIGNED`, a deal may have at most one `SENIOR_MANAGER`, and `priority_rank` may not collide among `ACTIVE` members — and all three report `ERR_DUPLICATE_SYNDICATE_MEMBER`."

    Design: Corner/validations/duplicate_syndicate_seat_and_second_senior_manager_rejected
    """
    ctx = draft_deal
    seated = _seat_senior_manager(client, ctx)
    challenger_firm = fx.register_underwriter_firm(client)

    # A firm with no seat at all and a free priority_rank: the head of the
    # syndicate is the only thing in contention.
    response = client.create_syndicate_member(
        ctx.deal_id,
        f.syndicate_member_payload(
            challenger_firm["id"],
            MemberRole.SENIOR_MANAGER,
            liability_pct=CHALLENGER_LIABILITY_PCT,
            takedown_share_pct=CHALLENGER_LIABILITY_PCT,
            priority_rank=2,
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_DUPLICATE_SYNDICATE_MEMBER, 422)

    rows, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [seated["id"]]
    assert_pagination(meta, total_count=1)


def test_a_colliding_priority_rank_is_refused(client, draft_deal):
    """PRD section 3.6: "Uniqueness is enforced three ways — a firm may not hold more than one seat on the deal that is not `RESIGNED`, a deal may have at most one `SENIOR_MANAGER`, and `priority_rank` may not collide among `ACTIVE` members — and all three report `ERR_DUPLICATE_SYNDICATE_MEMBER`."

    Design: Corner/validations/duplicate_syndicate_seat_and_second_senior_manager_rejected
    """
    ctx = draft_deal
    seated = _seat_senior_manager(client, ctx)
    challenger_firm = fx.register_underwriter_firm(client)

    # A new firm in a junior role: both other uniqueness limbs are satisfied and
    # only the rank collides with the ACTIVE seat already taken.
    response = client.create_syndicate_member(
        ctx.deal_id,
        f.syndicate_member_payload(
            challenger_firm["id"],
            MemberRole.CO_MANAGER,
            liability_pct=CHALLENGER_LIABILITY_PCT,
            takedown_share_pct=CHALLENGER_LIABILITY_PCT,
            priority_rank=seated["priority_rank"],
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_DUPLICATE_SYNDICATE_MEMBER, 422)

    rows, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [seated["id"]]
    assert_pagination(meta, total_count=1)


def test_a_second_live_engagement_with_the_same_agency_is_refused(client, draft_deal):
    """PRD section 3.5: "A deal may hold at most one engagement per agency that is not `WITHDRAWN`, so a second live request to the same agency is refused with `ERR_DUPLICATE_RATING_ENGAGEMENT`; once an engagement has been withdrawn, that agency may be re-engaged."

    Design: Corner/validations/duplicate_rating_engagement_per_agency_rejected
    """
    ctx = draft_deal
    first = fx.request_rating(
        client, ctx.deal_id, ctx.advisor_headers, RatingAgency.MOODYS
    )
    assert first["status"] == EngagementStatus.REQUESTED

    # The first engagement is still live and the requester is a different role
    # on the same deal, which changes nothing: the agency is already engaged.
    response = client.create_rating_engagement(
        ctx.deal_id, f.rating_engagement_payload(RatingAgency.MOODYS), ctx.issuer_headers
    )
    validate_error(response, ERR_DUPLICATE_RATING_ENGAGEMENT, 422)

    rows, meta = validate_paginated(
        client.list_deal_rating_engagements(ctx.deal_id, ctx.advisor_headers)
    )
    assert ids_of(rows) == [first["id"]]
    assert_pagination(meta, total_count=1)


def test_a_second_agency_on_the_same_deal_is_accepted(client, draft_deal):
    """PRD section 3.5: "A new engagement starts with `status` `REQUESTED`, `assigned_analyst_user_id` null, `info_request_count` at zero, and `latest_information_request`, `assigned_rating`, and `outlook` all null."

    Design: Corner/validations/duplicate_rating_engagement_per_agency_rejected
    """
    ctx = draft_deal
    first = fx.request_rating(
        client, ctx.deal_id, ctx.advisor_headers, RatingAgency.MOODYS
    )

    # The uniqueness scope is the deal and the agency together, so a second
    # agency is engaged on the same deal without objection.
    data = validate_success(
        client.create_rating_engagement(
            ctx.deal_id, f.rating_engagement_payload(RatingAgency.SP), ctx.advisor_headers
        ),
        201,
    )
    assert data["agency"] == RatingAgency.SP
    assert data["status"] == EngagementStatus.REQUESTED
    assert data["assigned_analyst_user_id"] is None
    assert data["info_request_count"] == 0
    assert data["latest_information_request"] is None
    assert data["assigned_rating"] is None
    assert data["outlook"] is None

    rows, meta = validate_paginated(
        client.list_deal_rating_engagements(ctx.deal_id, ctx.advisor_headers)
    )
    assert sorted(ids_of(rows)) == sorted([first["id"], data["id"]])
    assert_pagination(meta, total_count=2)
