"""The restricted secondary market: its back edges and its ownership rule.

Two back edges converge on `OPEN` (a lapsed order reposted by its seller, and a
matched order reposted after a counterparty withdrawal), and because the
Investor role is entity-backed, a stranger holding the same role cannot act on
another investor's order.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_investor_headers, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, create_transfer_order_payload,
    file_verified_authentication, file_verified_provenance, file_circular,
    allocate_offering, get_offering,
)

ISSUER = TEST_USERS["issuer_ops_headers"]


def _allocated_market(holders=2):
    """An allocated offering whose holding clock has never started.

    Each investor holds an accepted position, so the secondary market is open
    and both a seller and a holder-buyer exist.
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon", attribution_status="CONFIRMED",
                           nationality_country_code="ES")
    artwork = create_artwork(artist["id"], title="Cuadro Rojo", creation_year=1963,
                             acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=6_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investors = [create_investor(email=f"holder{i}@x.com", legal_name=f"Holder {i}")
                 for i in range(holders)]
    for investor in investors:
        create_screened_subscription(offering["id"], investor["id"],
                                     requested_shares=8000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    return get_offering(offering["id"]), investors


def _post_order(offering_id, seller_id, **overrides):
    return validate_success(api_client.create_transfer_order(
        create_transfer_order_payload(offering_id, seller_id, **overrides),
        make_investor_headers(seller_id)), 201)


def _accept(order_id, buyer_id, bid_price_cents):
    return validate_success(api_client.accept_transfer_order(
        order_id, {"buyer_id": buyer_id, "bid_price_cents": bid_price_cents},
        make_investor_headers(buyer_id)), 200)


# ── LAPSED -> OPEN ───────────────────────────────────────────────────────────

def test_a_lapsed_order_is_reposted_by_its_seller_back_to_open(api):
    """PRD 3.7: "A resting order that has sat `OPEN` for at least 30 consecutive days
    with no acceptance is moved to `LAPSED` by the server during the offering's
    reconciliation pass, and no shares move as a result. A lapsed order may be reposted
    by its own `seller_id` — the acting investor must be that seller — after which it is
    no longer lapsed."

    Design: Corner/state_machines/lapsed_transfer_order_can_be_reposted_by_its_seller
    """
    offering, investors = _allocated_market()
    seller = investors[0]
    order = _post_order(offering["id"], seller["id"], shares=4000,
                        limit_price_cents=12_000_000)

    set_clock("2027-03-15T00:00:00Z")
    validate_success(api_client.reconcile_cadence(offering["id"], {}, ISSUER), 200)
    lapsed = validate_success(api_client.get_transfer_order(order["id"], ISSUER), 200)
    assert lapsed["status"] == "LAPSED"

    validate_success(api_client.repost_transfer_order(
        order["id"], {}, make_investor_headers(seller["id"])), 200)
    reposted = validate_success(api_client.get_transfer_order(order["id"], ISSUER), 200)
    assert reposted["status"] == "OPEN"


def test_a_repost_preserves_the_orders_size_and_limit_price(api):
    """PRD 3.7: "A lapsed order may be reposted by its own `seller_id` ... after which
    it is no longer lapsed." PRD 3.7: "An `Investor` posts a `TransferOrder` naming the
    `offering_id`, its own `seller_id`, the number of `shares` it is offering, and its
    `limit_price_cents`".

    Design: Corner/state_machines/lapsed_transfer_order_can_be_reposted_by_its_seller
    """
    offering, investors = _allocated_market()
    seller = investors[0]
    order = _post_order(offering["id"], seller["id"], shares=4000,
                        limit_price_cents=12_000_000)
    set_clock("2027-03-15T00:00:00Z")
    validate_success(api_client.reconcile_cadence(offering["id"], {}, ISSUER), 200)

    validate_success(api_client.repost_transfer_order(
        order["id"], {}, make_investor_headers(seller["id"])), 200)
    reposted = validate_success(api_client.get_transfer_order(order["id"], ISSUER), 200)
    assert reposted["shares"] == 4000
    assert reposted["limit_price_cents"] == 12_000_000
    assert reposted["buyer_id"] is None
    assert reposted["bid_price_cents"] is None


def test_a_reposted_order_is_no_longer_matched_or_lapsed(api):
    """PRD 3.7: "A lapsed order may be reposted by its own `seller_id`" — the order
    leaves the LAPSED set and, after a repost from MATCHED, the MATCHED set.

    Design: Corner/state_machines/lapsed_transfer_order_can_be_reposted_by_its_seller
    """
    offering, investors = _allocated_market()
    seller = investors[0]
    order = _post_order(offering["id"], seller["id"], shares=4000,
                        limit_price_cents=12_000_000)
    set_clock("2027-03-15T00:00:00Z")
    validate_success(api_client.reconcile_cadence(offering["id"], {}, ISSUER), 200)
    validate_success(api_client.repost_transfer_order(
        order["id"], {}, make_investor_headers(seller["id"])), 200)

    assert get_success_data(api_client.list_transfer_orders(
        ISSUER, params={"offering_id": offering["id"], "status": "LAPSED"})) == []
    assert get_success_data(api_client.list_transfer_orders(
        ISSUER, params={"offering_id": offering["id"], "status": "MATCHED"})) == []


# ── MATCHED -> OPEN ──────────────────────────────────────────────────────────

def test_a_matched_order_whose_counterparty_withdraws_is_repostable(api):
    """PRD 3.7: "A matched order whose counterparty withdraws before settlement can be
    reposted, which unbinds `buyer_id` and returns it to `OPEN`; a
    `TransferAgent`-side failure has the same remedy."

    Design: Corner/state_machines/lapsed_transfer_order_can_be_reposted_by_its_seller
    """
    offering, investors = _allocated_market()
    seller, buyer = investors[0], investors[1]
    order = _post_order(offering["id"], seller["id"], shares=4000,
                        limit_price_cents=12_000_000)
    matched = _accept(order["id"], buyer["id"], 12_500_000)
    assert matched["status"] == "MATCHED"
    assert matched["buyer_id"] == buyer["id"]

    validate_success(api_client.repost_transfer_order(
        order["id"], {}, make_investor_headers(seller["id"])), 200)
    reposted = validate_success(api_client.get_transfer_order(order["id"], ISSUER), 200)
    assert reposted["status"] == "OPEN"
    assert reposted["buyer_id"] is None


def test_reposting_a_matched_order_clears_the_matched_set(api):
    """PRD 3.7: "A matched order whose counterparty withdraws before settlement can be
    reposted, which unbinds `buyer_id` and returns it to `OPEN`; a
    `TransferAgent`-side failure has the same remedy."

    Design: Corner/state_machines/lapsed_transfer_order_can_be_reposted_by_its_seller
    """
    offering, investors = _allocated_market()
    seller, buyer = investors[0], investors[1]
    order = _post_order(offering["id"], seller["id"], shares=4000,
                        limit_price_cents=12_000_000)
    _accept(order["id"], buyer["id"], 12_500_000)
    assert len(get_success_data(api_client.list_transfer_orders(
        ISSUER, params={"offering_id": offering["id"], "status": "MATCHED"}))) == 1

    validate_success(api_client.repost_transfer_order(
        order["id"], {}, make_investor_headers(seller["id"])), 200)
    assert get_success_data(api_client.list_transfer_orders(
        ISSUER, params={"offering_id": offering["id"], "status": "MATCHED"})) == []


# ── Ownership on the role that is entity-backed ──────────────────────────────

def test_an_investor_cannot_cancel_another_investors_order(api):
    """PRD 2.1: "Ownership checks on any resource that references an `Investor`
    therefore compare the resource's foreign-key field — `investor_id` on a
    subscription, `seller_id` or `buyer_id` on a transfer order — against the value
    supplied in `X-User-ID`. An investor acting on a subscription or transfer order it
    does not own is refused."

    Design: Corner/rbac/an_investor_cannot_cancel_another_investors_transfer_order
    """
    offering, investors = _allocated_market()
    poster = investors[0]
    stranger = create_investor(email="stranger@x.com", legal_name="Emil Sorensen")
    order = _post_order(offering["id"], poster["id"], shares=4000)

    res = api_client.cancel_transfer_order(
        order["id"], {}, make_investor_headers(stranger["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert validate_success(
        api_client.get_transfer_order(order["id"], ISSUER), 200)["status"] == "OPEN"


def test_the_orders_own_seller_may_cancel_it(api):
    """PRD 3.7: "An `Investor` may cancel its own order, and the operations desk may
    cancel a matched order whose settlement failed; both paths land the order in
    terminal `CANCELLED`."

    Design: Corner/rbac/an_investor_cannot_cancel_another_investors_transfer_order
    """
    offering, investors = _allocated_market()
    poster = investors[0]
    order = _post_order(offering["id"], poster["id"], shares=4000)

    validate_success(api_client.cancel_transfer_order(
        order["id"], {}, make_investor_headers(poster["id"])), 200)
    cancelled = validate_success(api_client.get_transfer_order(order["id"], ISSUER), 200)
    assert cancelled["status"] == "CANCELLED"