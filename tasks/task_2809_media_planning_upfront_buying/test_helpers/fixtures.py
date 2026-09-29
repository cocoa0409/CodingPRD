"""Composite setup helpers.

Every test runs against an empty database, so each helper builds its
preconditions from scratch through the public API.  Setup calls use the lenient
``get_success_data`` validator; the strict validators belong in the tests.

The helpers are layered:

* tier 1 — one call, one row (an advertiser, a seller, a campaign, an avail)
* tier 2 — a short chain (an approved plan, a negotiation waiting on acceptance)
* tier 3 — a buy with unit lines, placed and committing budget
* tier 4 — a buy carrying delivery, a make-good or an invoice
* tier 5 — a whole marketplace with several advertisers or sellers

The entity-backed roles are always addressed through their builders, so a call
made on a seller's behalf carries that seller's own identifier and a call made on
a brand's behalf carries that advertiser's own identifier.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_STARTUP_INPUT, buy_cost_stack, line_commission_cents, line_net_cents
from .test_users import (
    BUYER_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_HEADERS,
    MEASUREMENT_HEADERS,
    PLANNER_HEADERS,
    make_advertiser_client_headers,
    make_seller_rep_headers,
)
from .types import Channel, Daypart, Market, Platform

Json = Dict[str, Any]


# ==========================================================================
# Tier 1 — single rows
# ==========================================================================
def register_advertiser(api: ApiClient, **overrides: Any) -> Json:
    """Register one brand client."""
    return get_success_data(
        api.create_advertiser(f.advertiser_payload(**overrides), CONTROLLER_HEADERS)
    )


def register_seller(api: ApiClient, **overrides: Any) -> Json:
    """Register one media seller."""
    return get_success_data(
        api.create_seller(f.seller_payload(**overrides), CONTROLLER_HEADERS)
    )


def open_campaign(api: ApiClient, advertiser_id: str, **overrides: Any) -> Json:
    """Open one campaign plan shell for the advertiser."""
    return get_success_data(
        api.create_campaign(
            f.campaign_payload(advertiser_id, **overrides), PLANNER_HEADERS
        )
    )


def add_allocation(api: ApiClient, campaign_id: str, **overrides: Any) -> Json:
    """Allocate one share of the campaign budget to a channel."""
    return get_success_data(
        api.create_channel_allocation(
            f.channel_allocation_payload(campaign_id, **overrides), PLANNER_HEADERS
        )
    )


def submit_plan(api: ApiClient, campaign_id: str) -> Json:
    """Submit the plan for client approval."""
    return get_success_data(api.submit_plan(campaign_id, None, PLANNER_HEADERS))


def approve_plan(api: ApiClient, campaign_id: str, advertiser_id: str) -> Json:
    """The owning client approves the plan, locking its allocations."""
    return get_success_data(
        api.approve_plan(campaign_id, None, make_advertiser_client_headers(advertiser_id))
    )


def reject_plan(
    api: ApiClient, campaign_id: str, advertiser_id: str, **overrides: Any
) -> Json:
    """The owning client returns the plan for revision."""
    return get_success_data(
        api.reject_plan(
            campaign_id,
            f.reject_plan_payload(**overrides),
            make_advertiser_client_headers(advertiser_id),
        )
    )


def fund_campaign(
    api: ApiClient, campaign_id: str, advertiser_id: str, amount_cents: int
) -> Json:
    """The owning client deposits cash against the campaign budget."""
    return get_success_data(
        api.fund_campaign(
            campaign_id,
            f.fund_payload(amount_cents),
            make_advertiser_client_headers(advertiser_id),
        )
    )


def file_avail(api: ApiClient, seller_id: str, **overrides: Any) -> Json:
    """The seller files one avail, which begins as a draft."""
    return get_success_data(
        api.create_inventory_forecast(
            f.inventory_forecast_payload(seller_id, **overrides),
            make_seller_rep_headers(seller_id),
        )
    )


def publish_avail(api: ApiClient, forecast_id: str, seller_id: str) -> Json:
    """The owning seller publishes the avail, making it buyable."""
    return get_success_data(
        api.publish_inventory_forecast(
            forecast_id, None, make_seller_rep_headers(seller_id)
        )
    )


def published_avail(api: ApiClient, seller_id: str, **overrides: Any) -> Json:
    """File and publish one avail in a single step."""
    avail = file_avail(api, seller_id, **overrides)
    return publish_avail(api, avail["id"], seller_id)


def open_negotiation(
    api: ApiClient,
    campaign_id: str,
    seller_id: str,
    allocation_id: str,
    **overrides: Any,
) -> Json:
    """Open a negotiation against one channel allocation."""
    return get_success_data(
        api.create_negotiation(
            f.negotiation_payload(campaign_id, seller_id, allocation_id, **overrides),
            BUYER_HEADERS,
        )
    )


def counter(api: ApiClient, negotiation_id: str, seller_id: str, **overrides: Any) -> Json:
    """The owning seller counters the offer on the table."""
    current = read_negotiation(api, negotiation_id)
    overrides.setdefault("expected_negotiation_version", current["version"])
    version = overrides.pop("expected_negotiation_version")
    return get_success_data(
        api.counter_negotiation(
            negotiation_id,
            f.counter_payload(version, **overrides),
            make_seller_rep_headers(seller_id),
        )
    )


def revise(api: ApiClient, negotiation_id: str, **overrides: Any) -> Json:
    """The agency revises its offer after a counter."""
    return get_success_data(
        api.revise_negotiation(negotiation_id, f.revise_payload(**overrides), BUYER_HEADERS)
    )


def accept_negotiation(api: ApiClient, negotiation_id: str) -> Json:
    """The agency accepts the counter on the table, which creates the buy."""
    return get_success_data(api.accept_negotiation(negotiation_id, None, BUYER_HEADERS))


def withdraw_negotiation(api: ApiClient, negotiation_id: str, **overrides: Any) -> Json:
    """The agency withdraws from the negotiation."""
    return get_success_data(
        api.withdraw_negotiation(
            negotiation_id, f.withdraw_payload(**overrides), BUYER_HEADERS
        )
    )


def add_unit(api: ApiClient, buy_id: str, forecast_id: str, **overrides: Any) -> Json:
    """Add one unit line to the buy, holding inventory on the avail."""
    return get_success_data(
        api.add_buy_unit(buy_id, f.buy_unit_payload(forecast_id, **overrides), BUYER_HEADERS)
    )


def place_buy(api: ApiClient, buy_id: str, campaign_id: str, **overrides: Any) -> Json:
    """Place the buy, reading the campaign version the guard requires."""
    version = overrides.pop("expected_campaign_version", None)
    if version is None:
        version = campaign_version(api, campaign_id)
    return get_success_data(
        api.place_buy(buy_id, f.place_payload(version, **overrides), BUYER_HEADERS)
    )


def close_buy(api: ApiClient, buy_id: str) -> Json:
    """Close out stewardship on the buy."""
    return get_success_data(api.close_buy(buy_id, None, CONTROLLER_HEADERS))


def move_clock(api: ApiClient, current_utc: str) -> None:
    """Move the logical clock forward to the named instant."""
    response = api.move_clock_to(current_utc, CONTROLLER_HEADERS)
    assert 200 <= response.status_code < 300, (
        f"moving the clock to {current_utc} failed with HTTP {response.status_code}: "
        f"{response.text}"
    )


def settle_aired(
    api: ApiClient, buy_unit_id: str, seller_id: str, actual_impressions: int
) -> Json:
    """The owning seller settles the line as aired."""
    return get_success_data(
        api.settle_airing(
            buy_unit_id,
            f.settle_aired_payload(actual_impressions),
            make_seller_rep_headers(seller_id),
        )
    )


def settle_preempted(api: ApiClient, buy_unit_id: str, seller_id: str) -> Json:
    """The owning seller settles the line as pre-empted."""
    return get_success_data(
        api.settle_airing(
            buy_unit_id, f.settle_preempted_payload(), make_seller_rep_headers(seller_id)
        )
    )


def file_report(
    api: ApiClient,
    buy_id: str,
    delivered_impressions: int,
    delivered_demo_impressions: int,
    seller_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """File measured delivery, as the owning seller or the measurement vendor."""
    headers = (
        make_seller_rep_headers(seller_id) if seller_id is not None else MEASUREMENT_HEADERS
    )
    return get_success_data(
        api.create_delivery_report(
            f.delivery_report_payload(
                buy_id, delivered_impressions, delivered_demo_impressions, **overrides
            ),
            headers,
        )
    )


def accept_report(api: ApiClient, report_id: str) -> Json:
    """The agency accepts the reported delivery."""
    return get_success_data(api.accept_delivery_report(report_id, None, BUYER_HEADERS))


def dispute_report(api: ApiClient, report_id: str, **overrides: Any) -> Json:
    """The agency disputes the reported delivery."""
    return get_success_data(
        api.dispute_delivery_report(report_id, f.dispute_payload(**overrides), BUYER_HEADERS)
    )


def offer_make_good(
    api: ApiClient,
    make_good_id: str,
    seller_id: str,
    offered_forecast_id: str,
    offered_impressions: int,
    **overrides: Any,
) -> Json:
    """The owning seller offers replacement inventory."""
    return get_success_data(
        api.offer_make_good(
            make_good_id,
            f.make_good_offer_payload(
                offered_forecast_id, offered_impressions, **overrides
            ),
            make_seller_rep_headers(seller_id),
        )
    )


def accept_make_good(api: ApiClient, make_good_id: str) -> Json:
    """The agency accepts the offered make-good, scheduling replacement units."""
    return get_success_data(api.accept_make_good(make_good_id, None, BUYER_HEADERS))


def reject_make_good(api: ApiClient, make_good_id: str, **overrides: Any) -> Json:
    """The agency rejects the offered make-good, reopening it."""
    return get_success_data(
        api.reject_make_good(
            make_good_id, f.make_good_rejection_payload(**overrides), BUYER_HEADERS
        )
    )


def waive_make_good(
    api: ApiClient, make_good_id: str, credit_cents: Optional[int] = None
) -> Json:
    """The controller waives the make-good in exchange for a credit."""
    return get_success_data(
        api.waive_make_good(make_good_id, f.waive_payload(credit_cents), CONTROLLER_HEADERS)
    )


def draft_invoice(api: ApiClient, buy_id: str, **overrides: Any) -> Json:
    """Draft an invoice for one billing period of the buy."""
    return get_success_data(
        api.create_invoice(f.invoice_payload(buy_id, **overrides), CONTROLLER_HEADERS)
    )


def issue_invoice(api: ApiClient, invoice_id: str) -> Json:
    """Issue the invoice, starting the payment-terms clock."""
    return get_success_data(api.issue_invoice(invoice_id, None, CONTROLLER_HEADERS))


def pay_invoice(
    api: ApiClient, invoice_id: str, advertiser_id: str, amount_cents: int
) -> Json:
    """The owning client pays against the issued invoice."""
    return get_success_data(
        api.record_client_payment(
            invoice_id,
            f.client_payment_payload(amount_cents),
            make_advertiser_client_headers(advertiser_id),
        )
    )


def remit_to_seller(api: ApiClient, invoice_id: str, amount_cents: int) -> Json:
    """A controller other than the placing buyer releases cash to the seller."""
    return get_success_data(
        api.remit_seller(
            invoice_id, f.remittance_payload(amount_cents), CONTROLLER_ALT_HEADERS
        )
    )


def create_rights_exercise(api: ApiClient, payload: Json) -> Json:
    """Exercise an option or a cancellation right against the buy."""
    return get_success_data(api.create_rights_exercise(payload, BUYER_HEADERS))


def run_reconciliation(api: ApiClient, payload: Json) -> Json:
    """Compute one unduplicated-reach run for the campaign."""
    return get_success_data(api.create_reconciliation_run(payload, PLANNER_HEADERS))


# ==========================================================================
# Readers — a fresh copy of a resource, and the version guards need
# ==========================================================================
def read_advertiser(api: ApiClient, advertiser_id: str) -> Json:
    return get_success_data(api.get_advertiser(advertiser_id, CONTROLLER_HEADERS))


def read_campaign(api: ApiClient, campaign_id: str) -> Json:
    return get_success_data(api.get_campaign(campaign_id, PLANNER_HEADERS))


def read_allocation(api: ApiClient, allocation_id: str) -> Json:
    return get_success_data(api.get_channel_allocation(allocation_id, PLANNER_HEADERS))


def read_seller(api: ApiClient, seller_id: str) -> Json:
    return get_success_data(api.get_seller(seller_id, CONTROLLER_HEADERS))


def read_avail(api: ApiClient, forecast_id: str) -> Json:
    return get_success_data(api.get_inventory_forecast(forecast_id, BUYER_HEADERS))


def read_negotiation(api: ApiClient, negotiation_id: str) -> Json:
    return get_success_data(api.get_negotiation(negotiation_id, BUYER_HEADERS))


def read_buy(api: ApiClient, buy_id: str) -> Json:
    return get_success_data(api.get_buy(buy_id, BUYER_HEADERS))


def read_unit(api: ApiClient, buy_unit_id: str) -> Json:
    return get_success_data(api.get_buy_unit(buy_unit_id, BUYER_HEADERS))


def read_report(api: ApiClient, report_id: str) -> Json:
    return get_success_data(api.get_delivery_report(report_id, BUYER_HEADERS))


def read_make_good(api: ApiClient, make_good_id: str) -> Json:
    return get_success_data(api.get_make_good(make_good_id, BUYER_HEADERS))


def read_invoice(api: ApiClient, invoice_id: str) -> Json:
    return get_success_data(api.get_invoice(invoice_id, CONTROLLER_HEADERS))


def read_rights_exercise(api: ApiClient, rights_exercise_id: str) -> Json:
    return get_success_data(api.get_rights_exercise(rights_exercise_id, BUYER_HEADERS))


def read_reconciliation_run(api: ApiClient, run_id: str) -> Json:
    return get_success_data(api.get_reconciliation_run(run_id, PLANNER_HEADERS))


def campaign_version(api: ApiClient, campaign_id: str) -> int:
    """The campaign version a placement guard must quote."""
    return read_campaign(api, campaign_id)["version"]


def negotiation_version(api: ApiClient, negotiation_id: str) -> int:
    """The negotiation version a counter guard must quote."""
    return read_negotiation(api, negotiation_id)["version"]


def units_of_buy(api: ApiClient, buy_id: str) -> List[Json]:
    """Every unit line on the buy, oldest first."""
    body = get_success_data(
        api.list_buy_units(BUYER_HEADERS, params={"buy_id": buy_id, "limit": 100})
    )
    return list(body)


def make_goods_of_buy(api: ApiClient, buy_id: str) -> List[Json]:
    """Every make-good raised on the buy, oldest first."""
    body = get_success_data(
        api.list_make_goods(BUYER_HEADERS, params={"buy_id": buy_id, "limit": 100})
    )
    return list(body)


def only_make_good(api: ApiClient, buy_id: str) -> Json:
    """The single make-good the buy carries."""
    rows = make_goods_of_buy(api, buy_id)
    assert len(rows) == 1, f"expected exactly one make-good on the buy, found {len(rows)}"
    return rows[0]


# ==========================================================================
# The baseline plan shape the composites share
# ==========================================================================
#: The linear share of the baseline plan.
PRIMARY_ALLOCATION = {
    "channel": Channel.LINEAR_TV.value,
    "allocation_pct": 60.00,
    "planned_cpm_cents": 2000,
    "planned_market": Market.UPFRONT.value,
    "primary_daypart": Daypart.PRIME.value,
}

#: The digital share that completes the baseline plan to a hundred per cent.
SECONDARY_ALLOCATION = {
    "channel": Channel.DIGITAL_VIDEO.value,
    "allocation_pct": 40.00,
    "planned_cpm_cents": 1500,
    "planned_market": Market.UPFRONT.value,
    "primary_daypart": Daypart.DIGITAL_ANY.value,
}

#: The guarantee the baseline negotiation settles on, and its agreed price.
BASELINE_GUARANTEED_IMPRESSIONS = 40_000_000
BASELINE_AGREED_CPM_CENTS = 2200

#: The cost stack those two figures imply, at the lowest commission tier.
BASELINE_NET_MEDIA_COST_CENTS = 88_000_000
BASELINE_COMMISSION_RATE = 0.0400
BASELINE_AGENCY_COMMISSION_CENTS = 3_520_000
BASELINE_GROSS_COST_CENTS = 91_520_000


def baseline_cost_stack() -> Dict[str, Any]:
    """The cost stack the baseline guarantee and price imply."""
    return buy_cost_stack(BASELINE_GUARANTEED_IMPRESSIONS, BASELINE_AGREED_CPM_CENTS)


# ==========================================================================
# Tier 2 — plans
# ==========================================================================
def drafted_plan(
    api: ApiClient,
    allocations: Optional[List[Json]] = None,
    advertiser: Optional[Json] = None,
    **campaign_overrides: Any,
) -> Json:
    """A campaign in draft carrying whole-plan allocations.

    Returns a world dictionary holding the advertiser, the campaign as last read
    and the allocations in the order they were created.
    """
    if allocations is None:
        allocations = [dict(PRIMARY_ALLOCATION), dict(SECONDARY_ALLOCATION)]
    if advertiser is None:
        advertiser = register_advertiser(api)
    campaign = open_campaign(api, advertiser["id"], **campaign_overrides)
    rows = [add_allocation(api, campaign["id"], **spec) for spec in allocations]
    return {
        "advertiser": advertiser,
        "advertiser_id": advertiser["id"],
        "campaign": read_campaign(api, campaign["id"]),
        "campaign_id": campaign["id"],
        "allocations": rows,
        "allocation": rows[0],
        "allocation_id": rows[0]["id"],
    }


def submitted_plan(api: ApiClient, **kwargs: Any) -> Json:
    """A plan submitted and waiting on the client."""
    world = drafted_plan(api, **kwargs)
    submit_plan(api, world["campaign_id"])
    return _refresh_plan(api, world)


def approved_plan(api: ApiClient, **kwargs: Any) -> Json:
    """A plan the client has approved, with its allocations locked."""
    world = submitted_plan(api, **kwargs)
    approve_plan(api, world["campaign_id"], world["advertiser_id"])
    return _refresh_plan(api, world)


def funded_plan(
    api: ApiClient, funding_cents: int = 200_000_000, **kwargs: Any
) -> Json:
    """An approved plan the client has also funded."""
    world = approved_plan(api, **kwargs)
    fund_campaign(api, world["campaign_id"], world["advertiser_id"], funding_cents)
    return _refresh_plan(api, world)


def _refresh_plan(api: ApiClient, world: Json) -> Json:
    """Re-read the campaign and its allocations in place."""
    world["campaign"] = read_campaign(api, world["campaign_id"])
    world["allocations"] = [
        read_allocation(api, row["id"]) for row in world["allocations"]
    ]
    world["allocation"] = world["allocations"][0]
    return world


# ==========================================================================
# Tier 3 — negotiations, buys and placement
# ==========================================================================
def marketplace(
    api: ApiClient,
    funding_cents: int = 200_000_000,
    seller_overrides: Optional[Json] = None,
    avail_overrides: Optional[Json] = None,
    **plan_kwargs: Any,
) -> Json:
    """A funded plan facing one seller with one published avail."""
    world = funded_plan(api, funding_cents=funding_cents, **plan_kwargs)
    seller = register_seller(api, **(seller_overrides or {}))
    avail = published_avail(api, seller["id"], **(avail_overrides or {}))
    world.update(
        {
            "seller": seller,
            "seller_id": seller["id"],
            "seller_headers": make_seller_rep_headers(seller["id"]),
            "client_headers": make_advertiser_client_headers(world["advertiser_id"]),
            "avail": avail,
            "forecast_id": avail["id"],
        }
    )
    return world


def open_negotiation_world(
    api: ApiClient, negotiation_overrides: Optional[Json] = None, **kwargs: Any
) -> Json:
    """A marketplace with the agency's opening offer on the table."""
    world = marketplace(api, **kwargs)
    negotiation = open_negotiation(
        api,
        world["campaign_id"],
        world["seller_id"],
        world["allocation_id"],
        **(negotiation_overrides or {}),
    )
    world["negotiation"] = negotiation
    world["negotiation_id"] = negotiation["id"]
    return world


def countered_negotiation(
    api: ApiClient,
    counter_cpm_cents: int = BASELINE_AGREED_CPM_CENTS,
    counter_impressions: int = BASELINE_GUARANTEED_IMPRESSIONS,
    **kwargs: Any,
) -> Json:
    """A negotiation with the seller's counter on the table, ready to accept."""
    world = open_negotiation_world(api, **kwargs)
    world["negotiation"] = counter(
        api,
        world["negotiation_id"],
        world["seller_id"],
        counter_cpm_cents=counter_cpm_cents,
        counter_impressions=counter_impressions,
    )
    return world


def accepted_buy(api: ApiClient, **kwargs: Any) -> Json:
    """A buy the acceptance of a counter has just created, still unplaced."""
    world = countered_negotiation(api, **kwargs)
    buy = accept_negotiation(api, world["negotiation_id"])
    world["negotiation"] = read_negotiation(api, world["negotiation_id"])
    world["buy"] = buy
    world["buy_id"] = buy["id"]
    return _refresh_plan(api, world)


def buy_with_units(
    api: ApiClient,
    unit_specs: Optional[List[Json]] = None,
    **kwargs: Any,
) -> Json:
    """A buy carrying enough unit lines to cover its guarantee."""
    world = accepted_buy(api, **kwargs)
    if unit_specs is None:
        unit_specs = [{"projected_impressions": world["buy"]["guaranteed_impressions"]}]
    world["units"] = [
        add_unit(api, world["buy_id"], spec.pop("forecast_id", world["forecast_id"]), **spec)
        for spec in [dict(item) for item in unit_specs]
    ]
    world["unit"] = world["units"][0]
    world["unit_id"] = world["units"][0]["id"]
    world["buy"] = read_buy(api, world["buy_id"])
    world["avail"] = read_avail(api, world["forecast_id"])
    return world


def placed_buy(api: ApiClient, **kwargs: Any) -> Json:
    """A placed buy: inventory held, budget committed, stewardship open."""
    world = buy_with_units(api, **kwargs)
    world["buy"] = place_buy(api, world["buy_id"], world["campaign_id"])
    world["units"] = units_of_buy(api, world["buy_id"])
    world["unit"] = world["units"][0]
    world["unit_id"] = world["units"][0]["id"]
    world["avail"] = read_avail(api, world["forecast_id"])
    return _refresh_plan(api, world)


# ==========================================================================
# Tier 4 — delivery, shortfalls, make-goods and billing
# ==========================================================================
#: An instant after every baseline air window has closed.
AFTER_AIR_WINDOW = "2027-01-01T00:00:00Z"

#: An instant after the whole baseline flight has closed.
AFTER_FLIGHT = "2027-03-01T00:00:00Z"


def settled_buy(
    api: ApiClient,
    actual_impressions: int = BASELINE_GUARANTEED_IMPRESSIONS,
    settle_at: str = AFTER_AIR_WINDOW,
    **kwargs: Any,
) -> Json:
    """A placed buy whose single unit line the seller has settled as aired."""
    world = placed_buy(api, **kwargs)
    move_clock(api, settle_at)
    world["unit"] = settle_aired(
        api, world["unit_id"], world["seller_id"], actual_impressions
    )
    world["buy"] = read_buy(api, world["buy_id"])
    return world


def reported_buy(
    api: ApiClient,
    delivered_impressions: int = BASELINE_GUARANTEED_IMPRESSIONS,
    delivered_demo_impressions: Optional[int] = None,
    report_at: str = AFTER_FLIGHT,
    report_overrides: Optional[Json] = None,
    filed_by_seller: bool = False,
    **kwargs: Any,
) -> Json:
    """A placed buy carrying one filed, not yet adjudicated, delivery report."""
    world = placed_buy(api, **kwargs)
    move_clock(api, report_at)
    if delivered_demo_impressions is None:
        delivered_demo_impressions = delivered_impressions
    report = file_report(
        api,
        world["buy_id"],
        delivered_impressions,
        delivered_demo_impressions,
        seller_id=world["seller_id"] if filed_by_seller else None,
        **(report_overrides or {}),
    )
    world["report"] = report
    world["report_id"] = report["id"]
    world["buy"] = read_buy(api, world["buy_id"])
    return world


def accepted_report_world(api: ApiClient, **kwargs: Any) -> Json:
    """A buy whose delivery report the agency has accepted."""
    world = reported_buy(api, **kwargs)
    world["report"] = accept_report(api, world["report_id"])
    world["buy"] = read_buy(api, world["buy_id"])
    world["seller"] = read_seller(api, world["seller_id"])
    return world


def shortfall_world(
    api: ApiClient,
    delivered_impressions: int = 36_000_000,
    **kwargs: Any,
) -> Json:
    """A buy whose accepted delivery fell far enough short to raise a make-good.

    The default delivery is a tenth below the baseline guarantee, which is well
    outside the tolerance band, so a make-good is opened for the whole gap.
    """
    world = accepted_report_world(
        api, delivered_impressions=delivered_impressions, **kwargs
    )
    world["make_good"] = only_make_good(api, world["buy_id"])
    world["make_good_id"] = world["make_good"]["id"]
    return world


#: A second avail the seller keeps back for replacement inventory.
MAKE_GOOD_AVAIL = {
    "program": "Late Edition",
    "window_start": "2027-01-01T00:00:00Z",
    "window_end": "2027-02-28T00:00:00Z",
    "total_impressions": 30_000_000,
}


def make_good_avail(api: ApiClient, seller_id: str, **overrides: Any) -> Json:
    """A published avail the seller can offer replacement inventory from."""
    spec = dict(MAKE_GOOD_AVAIL)
    spec.update(overrides)
    return published_avail(api, seller_id, **spec)


def offered_make_good_world(
    api: ApiClient,
    offered_impressions: Optional[int] = None,
    **kwargs: Any,
) -> Json:
    """A make-good the seller has offered replacement inventory against."""
    world = shortfall_world(api, **kwargs)
    replacement = make_good_avail(api, world["seller_id"])
    world["make_good_avail"] = replacement
    if offered_impressions is None:
        offered_impressions = world["make_good"]["shortfall_impressions"]
    world["make_good"] = offer_make_good(
        api,
        world["make_good_id"],
        world["seller_id"],
        replacement["id"],
        offered_impressions,
        offered_window_start="2027-01-01T00:00:00Z",
        offered_window_end="2027-02-28T00:00:00Z",
    )
    world["buy"] = read_buy(api, world["buy_id"])
    world["seller"] = read_seller(api, world["seller_id"])
    return world


def scheduled_make_good_world(api: ApiClient, **kwargs: Any) -> Json:
    """A make-good the agency has accepted, scheduling replacement units."""
    world = offered_make_good_world(api, **kwargs)
    world["make_good"] = accept_make_good(api, world["make_good_id"])
    world["buy"] = read_buy(api, world["buy_id"])
    world["units"] = units_of_buy(api, world["buy_id"])
    world["seller"] = read_seller(api, world["seller_id"])
    return world


def drafted_invoice_world(api: ApiClient, **kwargs: Any) -> Json:
    """A placed buy with one drafted invoice covering its billing period."""
    world = kwargs.pop("world", None)
    if world is None:
        world = settled_buy(api, **kwargs)
    invoice = draft_invoice(api, world["buy_id"])
    world["invoice"] = invoice
    world["invoice_id"] = invoice["id"]
    return world


def issued_invoice_world(api: ApiClient, **kwargs: Any) -> Json:
    """An invoice issued to the client, its terms clock running."""
    world = drafted_invoice_world(api, **kwargs)
    world["invoice"] = issue_invoice(api, world["invoice_id"])
    return world


def paid_invoice_world(
    api: ApiClient, amount_cents: Optional[int] = None, **kwargs: Any
) -> Json:
    """An issued invoice the client has paid in full."""
    world = issued_invoice_world(api, **kwargs)
    if amount_cents is None:
        amount_cents = world["invoice"]["net_payable_cents"]
    world["invoice"] = pay_invoice(
        api, world["invoice_id"], world["advertiser_id"], amount_cents
    )
    world["advertiser"] = read_advertiser(api, world["advertiser_id"])
    return world


def remitted_invoice_world(
    api: ApiClient, amount_cents: Optional[int] = None, **kwargs: Any
) -> Json:
    """A paid invoice whose seller share a second controller has released."""
    world = paid_invoice_world(api, **kwargs)
    if amount_cents is None:
        amount_cents = world["invoice"]["max_remittable_cents"]
    world["invoice"] = remit_to_seller(api, world["invoice_id"], amount_cents)
    return world


# ==========================================================================
# Tier 5 — several channels, several counterparties
# ==========================================================================
#: A three-way plan whose shares sum to a hundred per cent, one per channel.
THREE_CHANNEL_PLAN: List[Json] = [
    {
        "channel": Channel.LINEAR_TV.value,
        "allocation_pct": 40.00,
        "planned_cpm_cents": 2000,
        "planned_market": Market.UPFRONT.value,
        "primary_daypart": Daypart.PRIME.value,
    },
    {
        "channel": Channel.CTV.value,
        "allocation_pct": 30.00,
        "planned_cpm_cents": 1800,
        "planned_market": Market.UPFRONT.value,
        "primary_daypart": Daypart.DIGITAL_ANY.value,
    },
    {
        "channel": Channel.DIGITAL_VIDEO.value,
        "allocation_pct": 30.00,
        "planned_cpm_cents": 1500,
        "planned_market": Market.UPFRONT.value,
        "primary_daypart": Daypart.DIGITAL_ANY.value,
    },
]

#: The avail shape each channel of that plan is served from.
CHANNEL_INVENTORY: Dict[str, Json] = {
    Channel.LINEAR_TV.value: {
        "platform": Platform.LINEAR.value,
        "daypart": Daypart.PRIME.value,
        "program": "Evening Headlines",
    },
    Channel.CTV.value: {
        "platform": Platform.CTV.value,
        "daypart": Daypart.DIGITAL_ANY.value,
        "program": "Streaming Feature",
    },
    Channel.DIGITAL_VIDEO.value: {
        "platform": Platform.DIGITAL.value,
        "daypart": Daypart.DIGITAL_ANY.value,
        "program": "Web Pre-Roll",
    },
    Channel.AUDIO.value: {
        "platform": Platform.AUDIO.value,
        "daypart": Daypart.DIGITAL_ANY.value,
        "program": "Morning Drive",
    },
}


def channel_buy(
    api: ApiClient,
    world: Json,
    allocation: Json,
    seller_id: str,
    guaranteed_impressions: int = 20_000_000,
    agreed_cpm_cents: int = 2000,
    avail_impressions: int = 40_000_000,
    place: bool = True,
) -> Json:
    """Place one buy on the named allocation, served from a matching avail.

    Returns a dictionary holding the avail, the negotiation, the buy and its
    single unit line.  The avail restates the channel's platform and daypart, and
    the unit line covers the whole guarantee.
    """
    inventory = dict(CHANNEL_INVENTORY[allocation["channel"]])
    inventory["total_impressions"] = avail_impressions
    inventory["forecast_cpm_cents"] = agreed_cpm_cents
    avail = published_avail(api, seller_id, **inventory)
    negotiation = open_negotiation(
        api,
        world["campaign_id"],
        seller_id,
        allocation["id"],
        channel=allocation["channel"],
        requested_impressions=guaranteed_impressions,
        opening_cpm_cents=agreed_cpm_cents,
    )
    counter(
        api,
        negotiation["id"],
        seller_id,
        counter_cpm_cents=agreed_cpm_cents,
        counter_impressions=guaranteed_impressions,
    )
    buy = accept_negotiation(api, negotiation["id"])
    unit = add_unit(
        api,
        buy["id"],
        avail["id"],
        daypart=inventory["daypart"],
        program=inventory["program"],
        platform=inventory["platform"],
        projected_impressions=guaranteed_impressions,
        unit_rate_cents=int(guaranteed_impressions * agreed_cpm_cents / 1000 / 100),
    )
    if place:
        buy = place_buy(api, buy["id"], world["campaign_id"])
    else:
        buy = read_buy(api, buy["id"])
    return {
        "channel": allocation["channel"],
        "allocation": read_allocation(api, allocation["id"]),
        "avail": read_avail(api, avail["id"]),
        "negotiation": read_negotiation(api, negotiation["id"]),
        "buy": buy,
        "buy_id": buy["id"],
        "unit": read_unit(api, unit["id"]),
        "unit_id": unit["id"],
        "seller_id": seller_id,
    }


def multi_channel_campaign(
    api: ApiClient,
    plan: Optional[List[Json]] = None,
    channels: Optional[List[str]] = None,
    funding_cents: int = 200_000_000,
    **kwargs: Any,
) -> Json:
    """A funded three-way plan with one placed buy on each named channel."""
    plan = plan if plan is not None else [dict(row) for row in THREE_CHANNEL_PLAN]
    world = funded_plan(api, allocations=plan, funding_cents=funding_cents, **kwargs)
    seller = register_seller(api)
    world["seller"] = seller
    world["seller_id"] = seller["id"]
    world["seller_headers"] = make_seller_rep_headers(seller["id"])
    world["client_headers"] = make_advertiser_client_headers(world["advertiser_id"])
    wanted = channels if channels is not None else [row["channel"] for row in plan]
    legs: Dict[str, Json] = {}
    for allocation in world["allocations"]:
        if allocation["channel"] in wanted:
            legs[allocation["channel"]] = channel_buy(
                api, world, allocation, seller["id"]
            )
    world["legs"] = legs
    return _refresh_plan(api, world)


def multi_channel_delivery(
    api: ApiClient,
    delivered_by_channel: Optional[Dict[str, int]] = None,
    report_at: str = AFTER_FLIGHT,
    **kwargs: Any,
) -> Json:
    """A multi-channel campaign whose every leg carries an accepted report."""
    world = multi_channel_campaign(api, **kwargs)
    move_clock(api, report_at)
    delivered_by_channel = delivered_by_channel or {}
    for channel, leg in world["legs"].items():
        delivered = delivered_by_channel.get(
            channel, leg["buy"]["guaranteed_impressions"]
        )
        report = file_report(api, leg["buy_id"], delivered, delivered)
        leg["report"] = accept_report(api, report["id"])
        leg["report_id"] = report["id"]
        leg["buy"] = read_buy(api, leg["buy_id"])
    return _refresh_plan(api, world)


def two_advertiser_world(api: ApiClient) -> Json:
    """Two brands in the same category, each with an approved plan.

    Category separation is asserted against this world: both advertisers declare
    the same category code, so a competing occupancy is one placement away.
    """
    first = drafted_plan(api)
    submit_plan(api, first["campaign_id"])
    approve_plan(api, first["campaign_id"], first["advertiser_id"])
    second_advertiser = register_advertiser(api, name="Southwind Beverages")
    second = drafted_plan(api, advertiser=second_advertiser, name="Southwind Winter")
    submit_plan(api, second["campaign_id"])
    approve_plan(api, second["campaign_id"], second["advertiser_id"])
    return {
        "first": _refresh_plan(api, first),
        "second": _refresh_plan(api, second),
    }


# ==========================================================================
# Small conveniences
# ==========================================================================
def reset_clock(api: ApiClient) -> None:
    """Return the logical clock to the instant the API starts from."""
    move_clock(api, CLOCK_STARTUP_INPUT)


def expected_line_money(
    units: int, unit_rate_cents: int, commission_rate: float
) -> Dict[str, int]:
    """The three money figures one unit line carries."""
    net = line_net_cents(units, unit_rate_cents)
    commission = line_commission_cents(net, commission_rate)
    return {
        "line_net_cents": net,
        "line_commission_cents": commission,
        "line_gross_cents": net + commission,
    }
