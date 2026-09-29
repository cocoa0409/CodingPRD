"""Requests that breach two rules at once, where PRD 2.8 fixes which one answers.

The rank order runs state (rank 5) above business-safety (rank 8) above
business-constraint (rank 11) above temporal windows (rank 10) above fiscal limits
(rank 13), and PRD 2.8 requires the server to "evaluate them in that order and
return the first failure it meets, never a later one".
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

EUR_SELL_RATE_MICROS = 878600


def _drained_position_world(api, teller_headers):
    """A branch whose only EUR notes - 2 x 10000 - have already been sold."""
    world = fx.trading_world(
        api, vault_limit_usd_cents=20_000_000, position_mix=[f.denom(10000, 2)]
    )
    txn = fx.settled_deal(
        api, world, denominations=[f.denom(10000, 2)], headers=teller_headers
    )
    assert txn["settled_usd_gross_cents"] == 22763
    assert fx.read_position(api, world["position"]["id"])["total_minor_units"] == 0
    return world, txn


def test_replaying_a_settled_transaction_answers_with_the_state_error(api, teller_headers):
    """A second settle of an already-SETTLED deal breaches both the state rule and
    the inventory rule - the first settle drained the very notes the replay needs -
    and the answer is ERR_TRANSACTION_NOT_AUTHORIZED, not ERR_INSUFFICIENT_INVENTORY.

    Design: Difficulty/priority_pair_validation_conflict/settle_transaction_state_error_beats_insufficient_inventory
    """
    world, txn = _drained_position_world(api, teller_headers)

    response = api.settle_transaction(txn["id"], teller_headers)

    validate_error(response, ApiErrorId.ERR_TRANSACTION_NOT_AUTHORIZED)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_INVENTORY

    unchanged = fx.read_transaction(api, txn["id"])
    assert unchanged["settlement_status"] == "SETTLED"
    assert unchanged["settled_usd_gross_cents"] == 22763
    assert fx.read_position(api, world["position"]["id"])["total_minor_units"] == 0


def test_the_inventory_rule_is_live_for_a_deal_that_is_genuinely_authorized(
    api, teller_headers
):
    """With the state precondition satisfied, the same drained 10000 line does
    surface ERR_INSUFFICIENT_INVENTORY, so the replay above was answered by rank
    rather than by the absence of the fiscal rule.

    Design: Difficulty/priority_pair_validation_conflict/settle_transaction_state_error_beats_insufficient_inventory
    """
    world, _ = _drained_position_world(api, teller_headers)

    second = fx.authorized_deal(
        api, world, denominations=[f.denom(10000, 1)], headers=teller_headers
    )
    assert second["settlement_status"] == "AUTHORIZED"

    validate_error(
        api.settle_transaction(second["id"], teller_headers),
        ApiErrorId.ERR_INSUFFICIENT_INVENTORY,
    )
    assert fx.read_position(api, world["position"]["id"])["total_minor_units"] == 0


def _mad_world(api, id_document_expiry):
    """A branch selling RESTRICTED MAD off a 400-bps card, with one documented
    customer whose passport expiry is supplied by the caller."""
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=20_000_000,
        currency_payload=f.restricted_currency_payload(export_limit_minor_units=200_000),
        mid_rate_micros=10_000_000,
        card_overrides={"sell_spread_bps": 400, "board_display_label": "MAD Dirham"},
        with_position=False,
        customer_overrides={
            "full_name": "Gita Rao",
            "nationality_code": "IN",
            "id_document_number": "IN-99120",
            "id_document_expiry": id_document_expiry,
            "travel_document_reference": "BP-77413",
        },
    )
    assert world["card"]["sell_rate_micros"] == 9_600_000
    return world


def test_an_expired_document_outranks_the_export_limit_on_authorisation(api, teller_headers):
    """30 x 10000 MAD breaches both the identification rule - the passport lapsed on
    2026-07-01 while the clock reads 2026-08-01 - and the 200000-minor-unit export
    limit, and authorisation answers ERR_CUSTOMER_ID_EXPIRED, leaving the deal QUOTED.

    Design: Difficulty/priority_pair_validation_conflict/authorize_customer_id_expired_beats_export_limit_exceeded
    """
    world = _mad_world(api, "2026-07-01T00:00:00Z")
    quote = fx.quote_deal(
        api, world, denominations=[f.denom(10000, 30)], headers=teller_headers
    )
    assert quote["quoted_usd_gross_cents"] == 31250
    assert quote["fx_gross_minor_units"] == 300000

    response = api.authorize_transaction(quote["id"], teller_headers)

    validate_error(response, ApiErrorId.ERR_CUSTOMER_ID_EXPIRED)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_EXPORT_LIMIT_EXCEEDED

    unchanged = fx.read_transaction(api, quote["id"])
    assert unchanged["settlement_status"] == "QUOTED"
    assert unchanged["authorized_by_user_id"] is None
    assert unchanged["quoted_usd_gross_cents"] == 31250


def test_the_export_limit_answers_once_the_document_is_valid(api, teller_headers):
    """The identical 300000-minor-unit MAD request made for a customer whose passport
    runs to 2027-01-01 is refused with ERR_EXPORT_LIMIT_EXCEEDED, proving the
    lower-ranked constraint was live and merely outranked.

    Design: Difficulty/priority_pair_validation_conflict/authorize_customer_id_expired_beats_export_limit_exceeded
    """
    world = _mad_world(api, "2027-01-01T00:00:00Z")
    quote = fx.quote_deal(
        api, world, denominations=[f.denom(10000, 30)], headers=teller_headers
    )

    validate_error(
        api.authorize_transaction(quote["id"], teller_headers),
        ApiErrorId.ERR_EXPORT_LIMIT_EXCEEDED,
    )
    assert fx.read_transaction(api, quote["id"])["settlement_status"] == "QUOTED"


def _route_world(api, daily_capacity_usd_cents, suffix="1", with_currency=True):
    """A southern branch, an EUR line and one narrow-capacity armored route holding a
    09:00-10:00 booking of 4 x 10000 notes."""
    branch = fx.register_branch(api, code=f"BR-CDG-{suffix}", name=f"Paris CDG {suffix}")
    if with_currency:
        fx.register_currency(api)
        fx.record_wholesale_rate(api)
    route = fx.register_route(
        api, code=f"RT-SOUTH-{suffix}", daily_capacity_usd_cents=daily_capacity_usd_cents
    )
    first = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)]
    )
    scheduled = fx.schedule_shipment(
        api,
        first["id"],
        route["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["manifest_usd_equivalent_cents"] == 43478
    second = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)]
    )
    return {"branch": branch, "route": route, "first": scheduled, "second": second}


def test_the_route_gap_outranks_the_route_day_capacity(api, treasury_headers):
    """A 10:00-11:00 window touches the incumbent closed 09:00-10:00 window and so
    breaks the 45-minute gap, while also pushing the route's booked day total to
    86956 cents against an 80000-cent capacity; the answer is
    ERR_ROUTE_WINDOW_CONFLICT and the shipment stays unscheduled.

    Design: Difficulty/priority_pair_validation_conflict/schedule_route_window_conflict_beats_route_capacity_exceeded
    """
    world = _route_world(api, 80_000)

    response = api.schedule_cash_shipment(
        world["second"]["id"],
        f.schedule_shipment_payload(
            world["route"]["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"
        ),
        treasury_headers,
    )

    validate_error(response, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED

    untouched = fx.read_shipment(api, world["second"]["id"])
    a.assert_cash_shipment(untouched)
    assert untouched["status"] == "REQUESTED"
    assert untouched["armored_route_id"] is None
    assert untouched["window_start"] is None
    assert fx.read_shipment(api, world["first"]["id"])["status"] == "SCHEDULED"


def test_the_day_capacity_answers_once_the_gap_is_respected(api, treasury_headers):
    """Moved to 12:00-13:00, well clear of the 45-minute gap, the same second
    shipment is refused with ERR_ROUTE_CAPACITY_EXCEEDED because 43478 + 43478
    overruns the 80000-cent day - and the same window succeeds on a route whose
    capacity is 200000 cents.

    Design: Difficulty/priority_pair_validation_conflict/schedule_route_window_conflict_beats_route_capacity_exceeded
    """
    tight = _route_world(api, 80_000)
    validate_error(
        api.schedule_cash_shipment(
            tight["second"]["id"],
            f.schedule_shipment_payload(
                tight["route"]["id"], "2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z"
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED,
    )
    assert fx.read_shipment(api, tight["second"]["id"])["status"] == "REQUESTED"

    roomy = _route_world(api, 200_000, suffix="2", with_currency=False)
    accepted = validate_success(
        api.schedule_cash_shipment(
            roomy["second"]["id"],
            f.schedule_shipment_payload(
                roomy["route"]["id"], "2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z"
            ),
            treasury_headers,
        )
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["armored_route_id"] == roomy["route"]["id"]
