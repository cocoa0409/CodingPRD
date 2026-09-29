"""Admission gates on a booking and on a quote: restrictions, rate eligibility,
the booking horizon and the overbooking band.

Each scenario here drives one gate from both sides — the request the contract
refuses, with the exact `error_id` and status the catalogue pairs with it, and the
neighbouring request the contract admits, proved by the derived value the
admission produced: the nightly breakdown, the recomputed pool, the channel
ledger or the `overbooking_overridden` flag. Every scenario is arranged so that
only the gate under test is violated, because the ordered validation of the
contract would otherwise report an earlier rule instead.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    REVENUE_MANAGER_HEADERS,
    ApiErrorId,
    assert_channel_ledger,
    assert_inventory_day,
    assert_nightly_breakdown,
    assert_quoted_rate,
    assert_reservation_totals,
    find_by,
)
from test_helpers import factories, fixtures

# One night of the canonical public plan on a zero-commission channel: the plan's
# resolved base of 25000 sits inside the 18000..40000 band, the channel adjustment
# is 0 and the package inclusion is 0, so the guest pays exactly the base and the
# whole amount is commissionable at 0 basis points.
NIGHT_AT_BASE = {
    "sell_rate_cents": 25000,
    "commissionable_cents": 25000,
    "commission_cents": 0,
}

# An empty lifetime ledger: what a channel that never sold anything still reads.
EMPTY_LEDGER = {
    "gross_revenue_cents": 0,
    "commission_accrued_cents": 0,
    "net_revenue_cents": 0,
    "room_nights_sold": 0,
    "bookings_count": 0,
    "cancellations_count": 0,
}


def _book(
    api,
    channel_id,
    rate_plan_id,
    room_type_id,
    arrival_date=fixtures.STAY_DATE,
    nights=1,
    **overrides,
):
    """Post one booking and hand back the raw response, so a test pins the status."""
    payload = factories.reservation_payload(
        channel_id=channel_id,
        rate_plan_id=rate_plan_id,
        room_type_id=room_type_id,
        arrival_date=arrival_date,
        nights=nights,
        **overrides,
    )
    return api.create_reservation(payload, REVENUE_MANAGER_HEADERS)


def _quote(api, mapping_id, stay_date=fixtures.STAY_DATE, **guest_attributes):
    """Read the quoted rate for one mapping and one night, unwrapped by the caller."""
    query = factories.quoted_rate_params(stay_date=stay_date, **guest_attributes)
    return api.get_quoted_rate(mapping_id, REVENUE_MANAGER_HEADERS, query)


# ── Closed to arrival ──────────────────────────────────────────────────────


def _world_closed_to_arrival(api, world):
    """Three consecutive open nights, the middle one closed to arrivals.

    The booking channel is the direct brand channel, whose commission is 0 and
    whose market list is empty, so nothing but the restriction can refuse a stay.
    """
    brand = fixtures.create_brand_channel(api, world["property_id"])
    fixtures.open_inventory_days(
        api,
        world["room_type_id"],
        [fixtures.STAY_DATE, fixtures.STAY_DATE_2, fixtures.STAY_DATE_3],
    )
    fixtures.create_restriction(
        api,
        world["room_type_id"],
        "CLOSED_TO_ARRIVAL",
        fixtures.STAY_DATE_2,
        fixtures.STAY_DATE_2,
    )
    return brand["channel"]["id"]


def test_closed_to_arrival_refuses_a_stay_arriving_on_the_closed_date(api, world):
    """A scoped ACTIVE CLOSED_TO_ARRIVAL restriction blocks a booking whose
    arrival_date falls inside its closed window, and the refusal is
    ERR_CLOSED_TO_ARRIVAL at HTTP 422 with no unit committed.

    Design: Corner/validations/closed_to_arrival_blocks_an_arrival_but_not_a_stay_that_merely_spans_the_date
    """
    channel_id = _world_closed_to_arrival(api, world)

    response = _book(
        api,
        channel_id,
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=fixtures.STAY_DATE_2,
        nights=1,
    )

    validate_error(response, ApiErrorId.CLOSED_TO_ARRIVAL.value, 422)
    closed_night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE_2)
    assert_inventory_day(closed_night, capacity=10, ceiling=11, committed=0, shared=11)


def test_closed_to_arrival_admits_a_stay_that_only_spans_the_closed_date(api, world):
    """CLOSED_TO_ARRIVAL reads the arrival_date alone, so a stay that merely passes
    through the closed night is admitted, prices all three nights at the plan's
    resolved base, and commits a unit on the closed night all the same.

    Design: Corner/validations/closed_to_arrival_blocks_an_arrival_but_not_a_stay_that_merely_spans_the_date
    """
    channel_id = _world_closed_to_arrival(api, world)

    response = _book(
        api,
        channel_id,
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=3,
    )

    reservation = validate_success(response, 201)
    assert reservation["reservation_state"] == "CONFIRMED"
    assert reservation["departure_date"] == fixtures.STAY_DATE_4
    # 3 nights x 25000 = 75000 gross, commission 0 per night on the brand channel,
    # and gross 75000 >= 70000 puts the stay in the 600 bp loyalty tier:
    # 75000 x 600 / 10000 = 4500.
    assert_reservation_totals(
        reservation, gross=75000, commission=0, net=75000, loyalty_credit=4500
    )
    assert_nightly_breakdown(
        reservation,
        [
            {"stay_date": fixtures.STAY_DATE, **NIGHT_AT_BASE},
            {"stay_date": fixtures.STAY_DATE_2, **NIGHT_AT_BASE},
            {"stay_date": fixtures.STAY_DATE_3, **NIGHT_AT_BASE},
        ],
    )
    closed_night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE_2)
    assert_inventory_day(
        closed_night, capacity=10, ceiling=11, allocated=0, committed=1, shared=10,
        pooled_state="OPEN",
    )


# ── Member-only eligibility ────────────────────────────────────────────────


def _world_member_only_plan(api, world):
    """One open night, a member-only plan, and two channels that differ only in
    whether they are allowed to sell member rates.

    Both channels leave `geo_market_codes` empty, so they serve every market and
    the geo gate can never pre-empt the member gate.
    """
    member_channel = fixtures.create_brand_channel(
        api, world["property_id"], allows_member_rate=True
    )
    plain_channel = fixtures.create_sellable_channel(
        api,
        world["property_id"],
        code="NOMEMBER",
        channel_kind="OTA_PUBLIC",
        commission_bp=1750,
    )
    plan = fixtures.create_active_rate_plan(
        api,
        world["property_id"],
        code="MEMBAR",
        rate_class="PUBLIC",
        base_amount_cents=fixtures.BAR_BASE_CENTS,
        floor_amount_cents=fixtures.BAR_FLOOR_CENTS,
        ceiling_amount_cents=fixtures.BAR_CEILING_CENTS,
        member_only=True,
    )
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    return {
        "member_channel_id": member_channel["channel"]["id"],
        "plain_channel_id": plain_channel["channel"]["id"],
        "rate_plan_id": plan["id"],
    }


def test_member_only_plan_refuses_a_booking_without_the_member_flag(api, world):
    """A member-only plan requires the request's member_flag to be true, so a
    request that omits it is refused with ERR_MEMBER_RATE_NOT_ELIGIBLE at HTTP 422
    even on a channel that does allow member rates.

    Design: Corner/validations/member_only_plan_needs_both_the_member_flag_and_a_member_enabled_channel
    """
    scenario = _world_member_only_plan(api, world)

    response = _book(
        api,
        scenario["member_channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
    )

    validate_error(response, ApiErrorId.MEMBER_RATE_NOT_ELIGIBLE.value, 422)
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_member_only_plan_refuses_a_member_on_a_channel_that_disallows_member_rates(
    api, world
):
    """The member gate reads the channel as well as the guest: a member-only plan on
    a channel whose allows_member_rate is false is refused with
    ERR_MEMBER_RATE_NOT_ELIGIBLE at HTTP 422 however the request is flagged.

    Design: Corner/validations/member_only_plan_needs_both_the_member_flag_and_a_member_enabled_channel
    """
    scenario = _world_member_only_plan(api, world)

    response = _book(
        api,
        scenario["plain_channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
        member_flag=True,
    )

    validate_error(response, ApiErrorId.MEMBER_RATE_NOT_ELIGIBLE.value, 422)
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_member_only_plan_admits_a_member_on_a_member_enabled_channel(api, world):
    """With both halves of the gate satisfied — a true member_flag and a channel that
    allows member rates — the stay is admitted, priced at the plan's resolved base
    and recorded as a member booking.

    Design: Corner/validations/member_only_plan_needs_both_the_member_flag_and_a_member_enabled_channel
    """
    scenario = _world_member_only_plan(api, world)

    response = _book(
        api,
        scenario["member_channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
        member_flag=True,
    )

    reservation = validate_success(response, 201)
    assert reservation["reservation_state"] == "CONFIRMED"
    assert reservation["member_flag"] is True
    # One night at the base of 25000 on a 0 bp channel, and gross 25000 sits under
    # the 50000 loyalty floor, so no credit accrues.
    assert_reservation_totals(
        reservation, gross=25000, commission=0, net=25000, loyalty_credit=0
    )
    assert_nightly_breakdown(reservation, [{"stay_date": fixtures.STAY_DATE, **NIGHT_AT_BASE}])
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(
        night, capacity=10, ceiling=11, allocated=0, committed=1, shared=10,
        pooled_state="OPEN",
    )


# ── Opaque eligibility ─────────────────────────────────────────────────────


def _world_opaque_plan(api, world):
    """An ACTIVE opaque child of the public root, plus the two channels that decide
    whether it may be sold.

    The child takes 25 percent off the root's 25000: 25000 x 7500 / 10000 = 18750,
    inside its own 12000..40000 band. Both channels serve every market.
    """
    plain_channel = fixtures.create_sellable_channel(
        api,
        world["property_id"],
        code="NOOPAQUE",
        channel_kind="OTA_PUBLIC",
        commission_bp=fixtures.OTA_COMMISSION_BP,
    )
    opaque_channel = fixtures.create_opaque_channel(api, world["property_id"])
    plan = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        world["rate_plan_id"],
        code="OPQBAR",
        rate_class="OPAQUE",
        offset_kind="PERCENT",
        offset_bp=-2500,
        floor_amount_cents=12000,
        ceiling_amount_cents=40000,
    )
    plan = fixtures.activate_rate_plan(api, plan["id"])
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    return {
        "plain_channel_id": plain_channel["channel"]["id"],
        "opaque_channel_id": opaque_channel["channel"]["id"],
        "rate_plan_id": plan["id"],
    }


def test_opaque_plan_is_refused_on_a_channel_that_disallows_opaque_rates(api, world):
    """An OPAQUE plan may only be sold on a channel whose allows_opaque_rate is true,
    so booking it on an ordinary public OTA is refused with
    ERR_OPAQUE_RATE_NOT_ALLOWED at HTTP 422 and leaves that channel's ledger empty.

    Design: Corner/validations/opaque_plan_is_bookable_only_on_a_channel_that_allows_opaque_rates
    """
    scenario = _world_opaque_plan(api, world)

    response = _book(
        api,
        scenario["plain_channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
    )

    validate_error(response, ApiErrorId.OPAQUE_RATE_NOT_ALLOWED.value, 422)
    assert_channel_ledger(
        fixtures.read_channel(api, scenario["plain_channel_id"]), EMPTY_LEDGER
    )
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_opaque_plan_is_admitted_and_priced_on_a_channel_that_allows_opaque_rates(
    api, world
):
    """The same opaque plan on an opaque-enabled channel is admitted and charged off
    the derived base, with the channel's 25 percent commission accrued to its
    lifetime ledger.

    Design: Corner/validations/opaque_plan_is_bookable_only_on_a_channel_that_allows_opaque_rates
    """
    scenario = _world_opaque_plan(api, world)
    plan = fixtures.read_rate_plan(api, scenario["rate_plan_id"])
    assert plan["resolved_base_amount_cents"] == 18750
    assert plan["derivation_depth"] == 1

    response = _book(
        api,
        scenario["opaque_channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
    )

    reservation = validate_success(response, 201)
    # One night at 18750, all of it commissionable at 2500 bp:
    # 18750 x 2500 / 10000 = 4687.5, half-up to 4688, leaving 14062 net.
    assert_reservation_totals(
        reservation, gross=18750, commission=4688, net=14062, loyalty_credit=0
    )
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": fixtures.STAY_DATE,
                "sell_rate_cents": 18750,
                "commissionable_cents": 18750,
                "commission_cents": 4688,
            }
        ],
    )
    assert_channel_ledger(
        fixtures.read_channel(api, scenario["opaque_channel_id"]),
        {
            "gross_revenue_cents": 18750,
            "commission_accrued_cents": 4688,
            "net_revenue_cents": 14062,
            "room_nights_sold": 1,
            "bookings_count": 1,
            "cancellations_count": 0,
        },
    )


# ── Negotiated account eligibility ─────────────────────────────────────────


def _world_negotiated_plan(api, world):
    """An ACTIVE negotiated child of the public root, sold on the brand channel.

    The child takes 15 percent off the root's 25000: 25000 x 8500 / 10000 = 21250,
    inside its own 15000..40000 band, and it is tied to the account code ACME.
    """
    brand = fixtures.create_brand_channel(api, world["property_id"])
    plan = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        world["rate_plan_id"],
        code="CORP",
        rate_class="NEGOTIATED",
        offset_kind="PERCENT",
        offset_bp=-1500,
        floor_amount_cents=15000,
        ceiling_amount_cents=40000,
        negotiated_account_code="ACME",
    )
    plan = fixtures.activate_rate_plan(api, plan["id"])
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    return {"channel_id": brand["channel"]["id"], "rate_plan_id": plan["id"]}


def test_negotiated_plan_refuses_a_booking_that_omits_the_account_code(api, world):
    """A NEGOTIATED plan requires the request's negotiated_account_code to equal the
    plan's own, so a request that leaves the field out is refused with
    ERR_NEGOTIATED_ACCOUNT_MISMATCH at HTTP 422.

    Design: Corner/validations/negotiated_plan_requires_the_request_to_echo_the_matching_account_code
    """
    scenario = _world_negotiated_plan(api, world)

    response = _book(
        api, scenario["channel_id"], scenario["rate_plan_id"], world["room_type_id"]
    )

    validate_error(response, ApiErrorId.NEGOTIATED_ACCOUNT_MISMATCH.value, 422)
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_negotiated_plan_refuses_a_booking_quoting_a_different_account_code(api, world):
    """The account codes must match exactly, so a request that names another company's
    account is refused with ERR_NEGOTIATED_ACCOUNT_MISMATCH at HTTP 422 rather than
    falling back to the public rate.

    Design: Corner/validations/negotiated_plan_requires_the_request_to_echo_the_matching_account_code
    """
    scenario = _world_negotiated_plan(api, world)

    response = _book(
        api,
        scenario["channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
        negotiated_account_code="GLOBEX",
    )

    validate_error(response, ApiErrorId.NEGOTIATED_ACCOUNT_MISMATCH.value, 422)
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_negotiated_plan_admits_the_exact_account_code_and_prices_off_the_derived_base(
    api, world
):
    """A request echoing the plan's own account code is admitted, keeps the code on
    the stay, and is charged the negotiated child's resolved base rather than the
    public root's.

    Design: Corner/validations/negotiated_plan_requires_the_request_to_echo_the_matching_account_code
    """
    scenario = _world_negotiated_plan(api, world)

    response = _book(
        api,
        scenario["channel_id"],
        scenario["rate_plan_id"],
        world["room_type_id"],
        negotiated_account_code="ACME",
    )

    reservation = validate_success(response, 201)
    assert reservation["negotiated_account_code"] == "ACME"
    # One night at the negotiated 21250, not the root's 25000, at 0 bp commission,
    # and gross 21250 is under the 50000 loyalty floor.
    assert_reservation_totals(
        reservation, gross=21250, commission=0, net=21250, loyalty_credit=0
    )
    assert_nightly_breakdown(
        reservation,
        [
            {
                "stay_date": fixtures.STAY_DATE,
                "sell_rate_cents": 21250,
                "commissionable_cents": 21250,
                "commission_cents": 0,
            }
        ],
    )
    night = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(
        night, capacity=10, ceiling=11, allocated=0, committed=1, shared=10,
        pooled_state="OPEN",
    )


# ── Geo market eligibility ─────────────────────────────────────────────────


def _world_geo_markets(api, world):
    """Two verified mappings of the same public plan: one on the OTA that serves the
    single market US-CA, one on the brand channel whose market list is empty.

    Neither mapping is opaque, member-only or negotiated, so the geo gate is the
    only eligibility rule that either quote can trip.
    """
    listed_mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    brand = fixtures.create_brand_channel(api, world["property_id"])
    open_mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], brand["channel"]["id"], world["room_type_id"]
    )
    return {"listed_mapping_id": listed_mapping["id"], "open_mapping_id": open_mapping["id"]}


def test_geo_market_gate_refuses_an_unserved_market_on_a_channel_that_lists_markets(
    api, world
):
    """When a channel's geo_market_codes list is non-empty the request's
    geo_market_code must be one of the served markets, so quoting US-NY on a channel
    that serves only US-CA is refused with ERR_GEO_MARKET_NOT_SERVED at HTTP 422.

    Design: Corner/validations/geo_market_gate_applies_only_to_channels_with_a_non_empty_market_list
    """
    scenario = _world_geo_markets(api, world)

    response = _quote(api, scenario["listed_mapping_id"], geo_market_code="US-NY")

    validate_error(response, ApiErrorId.GEO_MARKET_NOT_SERVED.value, 422)


def test_geo_market_gate_admits_a_served_market_on_a_channel_that_lists_markets(
    api, world
):
    """The same mapping quoted from the market it does serve resolves normally: the
    plan's 25000 base survives every step of the resolution untouched, because no
    promotion applies and the channel makes no sell adjustment.

    Design: Corner/validations/geo_market_gate_applies_only_to_channels_with_a_non_empty_market_list
    """
    scenario = _world_geo_markets(api, world)

    response = _quote(api, scenario["listed_mapping_id"], geo_market_code="US-CA")

    quote = validate_success(response, 200)
    # No promotion, so the cap still reports 25000 x 3000 / 10000 = 7500, and the
    # base passes the 18000..40000 clamp unchanged.
    assert_quoted_rate(
        quote,
        {
            "channel_mapping_id": scenario["listed_mapping_id"],
            "stay_date": fixtures.STAY_DATE,
            "base_amount_cents": 25000,
            "promotion_discount_cents": 0,
            "discount_cap_cents": 7500,
            "channel_adjusted_cents": 25000,
            "clamped_cents": 25000,
            "sell_amount_cents": 25000,
            "applied_promotion_codes": [],
        },
    )


def test_geo_market_gate_never_fires_on_a_channel_whose_market_list_is_empty(api, world):
    """A channel with the default empty market list serves every market, so the very
    market code that the listing channel refused quotes successfully here.

    Design: Corner/validations/geo_market_gate_applies_only_to_channels_with_a_non_empty_market_list
    """
    scenario = _world_geo_markets(api, world)

    response = _quote(api, scenario["open_mapping_id"], geo_market_code="US-NY")

    quote = validate_success(response, 200)
    assert_quoted_rate(
        quote,
        {
            "channel_mapping_id": scenario["open_mapping_id"],
            "stay_date": fixtures.STAY_DATE,
            "base_amount_cents": 25000,
            "sell_amount_cents": 25000,
            "applied_promotion_codes": [],
        },
    )


# ── Booking horizon ────────────────────────────────────────────────────────

# The horizon runs forward from the clock's date by the property's
# booking_horizon_days: 2026-08-25 plus 365 days is 2027-08-25, the last date a
# departure may fall on, so the last night that can be sold is 2027-08-24.
HORIZON_EDGE_DATE = fixtures.date_offset(
    fixtures.FIXTURE_TODAY, fixtures.PROPERTY_BOOKING_HORIZON_DAYS
)
LAST_SELLABLE_NIGHT = fixtures.date_offset(
    fixtures.FIXTURE_TODAY, fixtures.PROPERTY_BOOKING_HORIZON_DAYS - 1
)


def _world_arriving_on_the_clock_date(api):
    """A world whose tonight is open for sale, built while tonight was still ahead.

    The night is opened with the clock a day earlier, so that opening it is
    unarguably inside the horizon; the clock is then advanced onto that very night,
    which is the only way to reach a booking whose arrival falls on today.
    """
    fixtures.set_clock(api, fixtures.instant(fixtures.date_offset(fixtures.FIXTURE_TODAY, -1)))
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    brand = fixtures.create_brand_channel(api, property_row["id"])
    plan = fixtures.create_active_rate_plan(
        api,
        property_row["id"],
        code=fixtures.BAR_CODE,
        rate_class="PUBLIC",
        base_amount_cents=fixtures.BAR_BASE_CENTS,
        floor_amount_cents=fixtures.BAR_FLOOR_CENTS,
        ceiling_amount_cents=fixtures.BAR_CEILING_CENTS,
    )
    fixtures.open_inventory_day(api, room_type["id"], fixtures.FIXTURE_TODAY)
    fixtures.set_clock(api, fixtures.FIXTURE_CLOCK)
    return {
        "room_type_id": room_type["id"],
        "channel_id": brand["channel"]["id"],
        "rate_plan_id": plan["id"],
    }


def _world_at_the_horizon_edge(api, world):
    """The last sellable night and the horizon's own date, both open for sale."""
    brand = fixtures.create_brand_channel(api, world["property_id"])
    fixtures.open_inventory_days(
        api, world["room_type_id"], [LAST_SELLABLE_NIGHT, HORIZON_EDGE_DATE]
    )
    return brand["channel"]["id"]


def test_stay_arriving_on_the_clock_date_is_outside_the_horizon(api):
    """arrival_date must be strictly after the clock's date, so a stay arriving on the
    clock's own date is refused with ERR_STAY_OUTSIDE_HORIZON at HTTP 422 even though
    the night is open and has every one of its ten rooms free.

    Design: Corner/validations/horizon_check_bounds_the_arrival_strictly_after_today_and_the_departure_at_the_edge
    """
    scenario = _world_arriving_on_the_clock_date(api)

    response = _book(
        api,
        scenario["channel_id"],
        scenario["rate_plan_id"],
        scenario["room_type_id"],
        arrival_date=fixtures.FIXTURE_TODAY,
        nights=1,
    )

    validate_error(response, ApiErrorId.STAY_OUTSIDE_HORIZON.value, 422)
    night = fixtures.inventory_day_on(api, scenario["room_type_id"], fixtures.FIXTURE_TODAY)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_stay_departing_one_day_past_the_horizon_edge_is_refused(api, world):
    """departure_date must be no later than the clock's date plus
    booking_horizon_days, so a one-night stay arriving on the horizon's own date —
    departing one day beyond it — is refused with ERR_STAY_OUTSIDE_HORIZON at 422.

    Design: Corner/validations/horizon_check_bounds_the_arrival_strictly_after_today_and_the_departure_at_the_edge
    """
    channel_id = _world_at_the_horizon_edge(api, world)

    response = _book(
        api,
        channel_id,
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=HORIZON_EDGE_DATE,
        nights=1,
    )

    validate_error(response, ApiErrorId.STAY_OUTSIDE_HORIZON.value, 422)
    night = fixtures.inventory_day_on(api, world["room_type_id"], HORIZON_EDGE_DATE)
    assert_inventory_day(night, capacity=10, ceiling=11, committed=0, shared=11)


def test_stay_departing_exactly_on_the_horizon_edge_is_admitted(api, world):
    """The departure bound is inclusive, so the night immediately before it — the last
    sellable night, departing exactly on the horizon's date — is admitted and commits
    a unit.

    Design: Corner/validations/horizon_check_bounds_the_arrival_strictly_after_today_and_the_departure_at_the_edge
    """
    channel_id = _world_at_the_horizon_edge(api, world)

    response = _book(
        api,
        channel_id,
        world["rate_plan_id"],
        world["room_type_id"],
        arrival_date=LAST_SELLABLE_NIGHT,
        nights=1,
    )

    reservation = validate_success(response, 201)
    assert reservation["reservation_state"] == "CONFIRMED"
    assert reservation["departure_date"] == HORIZON_EDGE_DATE
    assert_reservation_totals(reservation, gross=25000, commission=0, net=25000)
    night = fixtures.inventory_day_on(api, world["room_type_id"], LAST_SELLABLE_NIGHT)
    assert_inventory_day(
        night, capacity=10, ceiling=11, allocated=0, committed=1, shared=10,
        pooled_state="OPEN",
    )


# ── The overbooking band and the override ──────────────────────────────────


def _world_twin_pool(api, world, prefilled_units=0):
    """One open twin night, sold from the shared pool a given number of times.

    The twin room type holds two rooms under its own 50 percent allowance, so its
    ceiling is 2 + floor(2 x 5000 / 10000) = 3: one unit of overbooking band sits
    above physical capacity. Every prefill draw is made without an override, which
    is legitimate because each lands while the night is still below capacity.
    """
    twin = fixtures.create_twin_room_type(api, world["property_id"])
    brand = fixtures.create_brand_channel(api, world["property_id"])
    fixtures.open_inventory_day(api, twin["id"], fixtures.STAY_DATE)
    for _ in range(prefilled_units):
        fixtures.create_reservation(
            api, brand["channel"]["id"], world["rate_plan_id"], twin["id"]
        )
    return {
        "room_type_id": twin["id"],
        "channel_id": brand["channel"]["id"],
        "rate_plan_id": world["rate_plan_id"],
    }


def test_override_is_not_recorded_when_the_night_never_reached_the_band(api, world):
    """override_overbooking is only consumed by a unit that lands in the band, so the
    second of two rooms — still below physical capacity when it is sold — is admitted
    with overbooking_overridden false despite the request carrying the override.

    Design: Corner/validations/overbooking_override_is_required_only_once_the_band_is_reached_and_only_then_recorded
    """
    scenario = _world_twin_pool(api, world, prefilled_units=1)

    response = _book(
        api,
        scenario["channel_id"],
        scenario["rate_plan_id"],
        scenario["room_type_id"],
        override_overbooking=True,
    )

    reservation = validate_success(response, 201)
    assert reservation["override_overbooking"] is True
    assert reservation["overbooking_overridden"] is False
    night = fixtures.inventory_day_on(api, scenario["room_type_id"], fixtures.STAY_DATE)
    # Both physical rooms are now committed, so the night is TIGHT: 0 + 2 >= 2, while
    # committed 2 has not yet passed capacity and one band unit is still pooled.
    assert_inventory_day(
        night, capacity=2, ceiling=3, allocated=0, committed=2, shared=1,
        pooled_state="TIGHT",
    )
    assert fixtures.list_restrictions(api, room_type_id=scenario["room_type_id"]) == []


def test_pool_booking_into_the_overbooking_band_is_refused_without_the_override(
    api, world
):
    """Once allocated plus committed units have reached physical capacity, the next
    pool draw lands in the band and needs the override, so a request without it is
    refused with ERR_OVERBOOK_OVERRIDE_REQUIRED at HTTP 409, leaving the night as it
    was.

    Design: Corner/validations/overbooking_override_is_required_only_once_the_band_is_reached_and_only_then_recorded
    """
    scenario = _world_twin_pool(api, world, prefilled_units=2)

    response = _book(
        api,
        scenario["channel_id"],
        scenario["rate_plan_id"],
        scenario["room_type_id"],
    )

    validate_error(response, ApiErrorId.OVERBOOK_OVERRIDE_REQUIRED.value, 409)
    night = fixtures.inventory_day_on(api, scenario["room_type_id"], fixtures.STAY_DATE)
    # The band unit is still pooled, so the ceiling test passed and the override error
    # was the refusal; the refusal itself changed nothing.
    assert_inventory_day(
        night, capacity=2, ceiling=3, allocated=0, committed=2, shared=1,
        pooled_state="TIGHT",
    )


def test_override_admits_the_band_booking_and_tips_the_night_oversold(api, world):
    """The same draw carrying override_overbooking true is admitted, records
    overbooking_overridden true because the override was actually consumed, tips the
    night to OVERSOLD, and raises the automatic stop-sell guard on it.

    Design: Corner/validations/overbooking_override_is_required_only_once_the_band_is_reached_and_only_then_recorded
    """
    scenario = _world_twin_pool(api, world, prefilled_units=2)

    response = _book(
        api,
        scenario["channel_id"],
        scenario["rate_plan_id"],
        scenario["room_type_id"],
        override_overbooking=True,
    )

    reservation = validate_success(response, 201)
    assert reservation["reservation_state"] == "CONFIRMED"
    assert reservation["overbooking_overridden"] is True
    night = fixtures.inventory_day_on(api, scenario["room_type_id"], fixtures.STAY_DATE)
    # The third unit exhausts the band: committed 3 exceeds the capacity of 2, which
    # is OVERSOLD, and the shared pool is empty at the ceiling of 3.
    assert_inventory_day(
        night, capacity=2, ceiling=3, allocated=0, committed=3, shared=0,
        pooled_state="OVERSOLD",
    )
    # One guard restriction per ACTIVE rate plan on the property, and this property
    # has exactly one, covering the single oversold night.
    guards = fixtures.list_restrictions(api, room_type_id=scenario["room_type_id"])
    assert len(guards) == 1
    guard = find_by(
        guards,
        restriction_type="STOP_SELL",
        origin="AUTO_OVERBOOK_GUARD",
        rate_plan_id=scenario["rate_plan_id"],
    )
    assert guard["restriction_state"] == "ACTIVE"
    assert guard["start_date"] == fixtures.STAY_DATE
    assert guard["end_date"] == fixtures.STAY_DATE
    assert guard["lifted_at"] is None
