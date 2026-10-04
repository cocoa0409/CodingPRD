"""Composite setup helpers for the salvage vehicle auction domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_auction_item_payload,
    create_auction_payload,
    create_bid_payload,
    create_condition_payload,
    create_export_document_payload,
    create_gate_pass_payload,
    create_image_payload,
    create_license_payload,
    create_member_payload,
    create_payment_payload,
    create_seller_payload,
    create_title_payload,
    create_vehicle_payload,
    create_yard_payload,
)
from .test_users import TEST_USERS, make_buyer_headers, make_seller_agent_headers

PA = TEST_USERS["platform_admin_headers"]
YO = TEST_USERS["yard_operator_headers"]
AU = TEST_USERS["auctioneer_headers"]
TC = TEST_USERS["title_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def create_yard(**overrides):
    return get_success_data(api.create_yard(create_yard_payload(**overrides), PA))


def create_seller(**overrides):
    return get_success_data(api.create_seller(create_seller_payload(**overrides), PA))


def create_member(**overrides):
    return get_success_data(api.create_member(create_member_payload(**overrides), PA))


def create_license(member_id, **overrides):
    return get_success_data(
        api.create_license(member_id, create_license_payload(**overrides), PA)
    )


def create_vehicle(seller, yard, **overrides):
    """Assign a vehicle as the seller's own SellerAgent."""
    payload = create_vehicle_payload(seller["id"], yard["id"], **overrides)
    return get_success_data(api.create_vehicle(payload, make_seller_agent_headers(seller["id"])))


def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, PA))


def submit_condition(vehicle_id, **overrides):
    return get_success_data(
        api.submit_condition(vehicle_id, create_condition_payload(**overrides), YO)
    )


def add_images(vehicle_id, count=5):
    """Attach `count` condition images one at a time; returns the last response data."""
    data = None
    for _ in range(count):
        data = get_success_data(api.add_vehicle_image(vehicle_id, create_image_payload(), YO))
    return data


def receive_title(vehicle_id, **overrides):
    return get_success_data(api.create_title(vehicle_id, create_title_payload(**overrides), TC))


def mark_ready(vehicle_id):
    """Re-read the vehicle version and mark ready with a fresh OCC value."""
    vehicle = get_success_data(api.get_vehicle(vehicle_id, YO))
    return get_success_data(
        api.mark_ready(vehicle_id, {"expected_vehicle_version": vehicle["version"]}, YO)
    )


# ---------------------------------------------------------------------------
# Tier 2: intake pipeline — vehicle driven to SALE_READY
# ---------------------------------------------------------------------------

def prepare_vehicle(seller, yard, title_type="SALVAGE", image_count=5,
                    condition_overrides=None, **vehicle_overrides):
    """Create a vehicle, submit condition, attach images, receive title, and
    mark ready. Returns the SALE_READY vehicle."""
    vehicle = create_vehicle(seller, yard, **vehicle_overrides)
    submit_condition(vehicle["id"], **(condition_overrides or {}))
    add_images(vehicle["id"], count=image_count)
    receive_title(vehicle["id"], title_type=title_type)
    return mark_ready(vehicle["id"])


def create_auction(scheduled_start="2026-09-01T00:00:00Z", **overrides):
    return get_success_data(
        api.create_auction(create_auction_payload(scheduled_start=scheduled_start, **overrides), AU)
    )


def list_into_auction(auction_id, vehicle_id):
    return get_success_data(
        api.create_auction_item(auction_id, create_auction_item_payload(vehicle_id), AU)
    )


def place_bid(item_id, member, amount_cents):
    """Place a bid as the member's own Buyer identity. Returns raw response data."""
    return get_success_data(
        api.place_bid(create_bid_payload(item_id, amount_cents), make_buyer_headers(member["id"]))
    )


# ---------------------------------------------------------------------------
# Tier 3: live auction — item open in a LIVE auction
# ---------------------------------------------------------------------------

def setup_live_item(scheduled_start="2026-09-01T00:00:00Z", yard_overrides=None,
                    seller_overrides=None, member_overrides=None,
                    title_type="SALVAGE", clock_to=None, **vehicle_overrides):
    """Full pipeline through an open lot in a LIVE auction.

    Returns a dict with yard, seller, member, vehicle, auction, item.
    The lot is LIVE with no bids yet.
    """
    yard = create_yard(**(yard_overrides or {}))
    seller = create_seller(**(seller_overrides or {}))
    member = create_member(**(member_overrides or {}))
    vehicle = prepare_vehicle(seller, yard, title_type=title_type, **vehicle_overrides)
    auction = create_auction(scheduled_start=scheduled_start)
    item = list_into_auction(auction["id"], vehicle["id"])
    if clock_to:
        set_clock(clock_to)
    auction = get_success_data(api.start_auction(auction["id"], AU))
    item = get_success_data(api.open_lot(auction["id"], item["id"], AU))
    return {
        "yard": yard, "seller": seller, "member": member,
        "vehicle": vehicle, "auction": auction, "item": item,
    }


def setup_closed_sale(hammer_cents=1000000, **kwargs):
    """Live item plus one winning live bid, closed. Returns the context dict
    extended with bid and sale (close-lot response data)."""
    ctx = setup_live_item(**kwargs)
    bid = place_bid(ctx["item"]["id"], ctx["member"], hammer_cents)
    sale = get_success_data(api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU))
    ctx.update({"bid": bid, "sale": sale})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: payment and load-out
# ---------------------------------------------------------------------------

def pay_sale(ctx):
    """Pay the exact amount due on the context's sale as the winner."""
    sale = ctx["sale"]
    amount = sale["winning_bid_cents"] + sale["buyer_fee_cents"]
    return get_success_data(
        api.pay_sale(sale["id"], create_payment_payload(amount),
                     make_buyer_headers(ctx["member"]["id"]))
    )


def setup_paid_sale(**kwargs):
    """Closed sale paid by the winner. Returns ctx with paid sale."""
    ctx = setup_closed_sale(**kwargs)
    ctx["sale"] = pay_sale(ctx)
    return ctx


def get_settlement(sale_id):
    rows = get_success_data(api.get_sale_settlement(sale_id, TC))
    assert isinstance(rows, list) and len(rows) == 1, f"expected exactly 1 settlement, got {rows}"
    return rows[0]


def issue_gate_pass(ctx, slot_start="2026-09-02T14:00:00Z", slot_end="2026-09-02T18:00:00Z",
                    as_operator=False):
    """Issue a gate pass on the context's sale. Returns the GatePass."""
    headers = YO if as_operator else make_buyer_headers(ctx["member"]["id"])
    return get_success_data(
        api.create_gate_pass(ctx["sale"]["id"],
                             create_gate_pass_payload(slot_start=slot_start, slot_end=slot_end),
                             headers)
    )


def submit_and_verify_export_document(ctx, document_type="BILL_OF_LADING"):
    """Submit an export document as the winner and verify it as PlatformAdmin."""
    doc = get_success_data(
        api.create_export_document(
            ctx["sale"]["id"],
            create_export_document_payload(
                document_type=document_type,
                destination_country=ctx["member"]["country_code"],
            ),
            make_buyer_headers(ctx["member"]["id"]),
        )
    )
    return get_success_data(api.verify_export_document(doc["id"], PA))
