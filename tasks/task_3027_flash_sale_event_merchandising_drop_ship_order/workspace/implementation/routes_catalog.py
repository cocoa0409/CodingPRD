"""Vendor, Shop, Event and Listing endpoints (SCAFFOLD §1.5)."""

from flask import Blueprint
import auth
import calc
import requtil as R
import services as S
from errors import fail, invalid_request
from response import base_list, created, ok
from store import db, now, stamp, touch
from views import ser, ser_all

bp = Blueprint("catalog", __name__)

VENDOR_TIERS = ("STANDARD", "PREMIER", "STRATEGIC")
SHIP_TIME_QUOTES = (10, 14, 21, 30)
SKU_CAP = 40
LINE_COMMITTED_STATES = (
    "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK",
    "RECEIVED_AT_CROSS_DOCK", "SHIPPED", "SHORT_SHIPPED",
)


# ==========================================================================
# Vendor
# ==========================================================================

@bp.route("/vendors", methods=["POST"])
def create_vendor():
    auth.require_role(["Merchandiser"])
    data = R.body()
    legal_name = R.bstr(data, "legal_name")
    tier = R.benum(data, "vendor_tier", VENDOR_TIERS, required=False) or "STANDARD"
    vendor = {
        "legal_name": legal_name,
        "vendor_tier": tier,
        "standing": "EXCELLENT",
        "fill_rate_floor_pct": 0.9000,
        "rolling_fill_rate_units_shipped": 0,
        "rolling_fill_rate_units_ordered": 0,
        "standing_evaluated_at": None,
    }
    stamp(vendor)
    db.vendors[vendor["id"]] = vendor
    return created(ser("vendors", vendor))


@bp.route("/vendors/<vendor_id>", methods=["GET"])
def read_vendor(vendor_id):
    auth.require_role(["Any"])
    vendor = S.get_or_404("vendors", vendor_id)
    return ok(ser("vendors", vendor))


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    tier = R.q("vendor_tier")
    standing = R.q("standing")
    items = list(db.vendors.values())
    if tier is not None:
        items = [v for v in items if v["vendor_tier"] == tier]
    if standing is not None:
        items = [v for v in items if v["standing"] == standing]
    from store import ordered
    return base_list(ser_all("vendors", ordered(items)), limit, offset)


@bp.route("/vendors/<vendor_id>/shops", methods=["GET"])
def list_vendor_shops(vendor_id):
    auth.require_role(["Any"])
    vendor = S.get_or_404("vendors", vendor_id)
    limit, offset = R.pagination()
    status = R.q("shop_status")
    items = [s for s in db.shops.values() if s["vendor_id"] == vendor["id"]]
    if status is not None:
        items = [s for s in items if s["shop_status"] == status]
    from store import ordered
    return base_list(ser_all("shops", ordered(items)), limit, offset)


@bp.route("/vendors/<vendor_id>/purchase-orders", methods=["GET"])
def list_vendor_pos(vendor_id):
    auth.require_role(["Any"])
    vendor = S.get_or_404("vendors", vendor_id)
    limit, offset = R.pagination()
    status = R.q("po_status")
    event_id = R.q("event_id")
    items = [p for p in db.purchase_orders.values() if p["vendor_id"] == vendor["id"]]
    if status is not None:
        items = [p for p in items if p["po_status"] == status]
    if event_id is not None:
        items = [p for p in items if p["event_id"] == event_id]
    from store import ordered
    return base_list(ser_all("purchase_orders", ordered(items)), limit, offset)


@bp.route("/vendors/<vendor_id>/fill-rate-report", methods=["GET"])
def fill_rate_report(vendor_id):
    auth.require_role(["Any"])
    vendor = S.get_or_404("vendors", vendor_id)
    basis = R.q("basis") or "UNIT_WEIGHTED"
    if basis not in ("UNIT_WEIGHTED", "PO_COUNT"):
        invalid_request("basis must be UNIT_WEIGHTED or PO_COUNT.")
    window_days = R.qint("window_days")
    if window_days is None:
        window_days = calc.WINDOW_DAYS
    unit_rate, count_rate, units_ordered, units_shipped = calc.rolling_fill_rate(
        vendor["id"], window_days
    )
    return ok({
        "vendor_id": vendor["id"],
        "basis": basis,
        "window_days": window_days,
        "units_ordered": units_ordered,
        "units_shipped": units_shipped,
        "unit_weighted_fill_rate": None if unit_rate is None else float(unit_rate),
        "po_count_fill_rate": None if count_rate is None else float(count_rate),
        "standing": vendor["standing"],
        "fill_rate_floor_pct": vendor["fill_rate_floor_pct"],
    })


# ==========================================================================
# Shop
# ==========================================================================

@bp.route("/shops", methods=["POST"])
def create_shop():
    auth.require_role(["Merchandiser"])
    data = R.body()
    vendor_id = R.bstr(data, "vendor_id")
    shop_name = R.bstr(data, "shop_name")
    vendor = S.get_or_404("vendors", vendor_id)
    if vendor["standing"] == "SUSPENDED":
        fail("ERR_VENDOR_SUSPENDED")
    shop = {
        "vendor_id": vendor["id"],
        "shop_name": shop_name,
        "shop_status": "DRAFT",
        "curated_sku_count": 0,
    }
    stamp(shop)
    db.shops[shop["id"]] = shop
    return created(ser("shops", shop))


@bp.route("/shops/<shop_id>", methods=["GET"])
def read_shop(shop_id):
    auth.require_role(["Any"])
    shop = S.get_or_404("shops", shop_id)
    return ok(ser("shops", shop))


@bp.route("/shops", methods=["GET"])
def list_shops():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    vendor_id = R.q("vendor_id")
    status = R.q("shop_status")
    items = list(db.shops.values())
    if vendor_id is not None:
        items = [s for s in items if s["vendor_id"] == vendor_id]
    if status is not None:
        items = [s for s in items if s["shop_status"] == status]
    from store import ordered
    return base_list(ser_all("shops", ordered(items)), limit, offset)


@bp.route("/shops/<shop_id>/events", methods=["GET"])
def list_shop_events(shop_id):
    auth.require_role(["Any"])
    shop = S.get_or_404("shops", shop_id)
    limit, offset = R.pagination()
    status = R.q("event_status")
    items = [e for e in db.events.values() if e["shop_id"] == shop["id"]]
    if status is not None:
        items = [e for e in items if e["event_status"] == status]
    from store import ordered
    return base_list(ser_all("events", ordered(items)), limit, offset)


# ==========================================================================
# Event
# ==========================================================================

@bp.route("/events", methods=["POST"])
def create_event():
    auth.require_role(["Merchandiser"])
    data = R.body()
    shop_id = R.bstr(data, "shop_id")
    title = R.bstr(data, "event_title")
    starts_at = R.btime(data, "starts_at")
    ends_at = R.btime(data, "ends_at")
    ship_days = R.bint(data, "ship_time_quote_days")
    shop = S.get_or_404("shops", shop_id)
    # The disclosed ship-time expectation is fixed at creation and is one of the
    # four declared figures (PRD §3.1).
    if ship_days not in SHIP_TIME_QUOTES:
        invalid_request("ship_time_quote_days must be one of 10, 14, 21 or 30.")
    # The window itself is constrained (PRD §3.1): ends_at strictly after
    # starts_at, and the span no longer than 72 hours.
    if not (ends_at > starts_at):
        invalid_request("ends_at must be strictly after starts_at.")
    if (ends_at - starts_at).total_seconds() > 72 * 3600:
        invalid_request("The event window may not exceed 72 hours.")
    event = {
        "shop_id": shop["id"],
        "event_title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "ship_time_quote_days": ship_days,
        "event_status": "DRAFT",
        "checkpoint_index": 0,
        "units_ordered_total": 0,
        "units_po_committed_total": 0,
        "oversell_units_total": 0,
        "net_contribution_cents": None,
        "net_contribution_variant": None,
        "closed_at": None,
        "open_event_for_shop": False,
    }
    stamp(event)
    db.events[event["id"]] = event
    return created(ser("events", event))


@bp.route("/events/<event_id>", methods=["GET"])
def read_event(event_id):
    auth.require_role(["Any"])
    event = S.get_or_404("events", event_id)
    # Derived-field reconciliation (\u00a72.12).  Every writer already recomputes
    # the totals and the contribution, so this repairs silently; see the note on
    # the order read for why a spurious drift alarm would be the worse failure.
    calc.reconcile_event(event)
    calc.refresh_event_contribution(event)
    return ok(ser("events", event))


@bp.route("/events", methods=["GET"])
def list_events():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    shop_id = R.q("shop_id")
    status = R.q("event_status")
    items = list(db.events.values())
    if shop_id is not None:
        items = [e for e in items if e["shop_id"] == shop_id]
    if status is not None:
        items = [e for e in items if e["event_status"] == status]
    from store import ordered
    return base_list(ser_all("events", ordered(items)), limit, offset)


@bp.route("/events/<event_id>/listings", methods=["GET"])
def list_event_listings(event_id):
    auth.require_role(["Any"])
    event = S.get_or_404("events", event_id)
    limit, offset = R.pagination()
    status = R.q("listing_status")
    items = [l for l in db.listings.values() if l["event_id"] == event["id"]]
    if status is not None:
        items = [l for l in items if l["listing_status"] == status]
    from store import ordered
    return base_list(ser_all("listings", ordered(items)), limit, offset)


@bp.route("/events/<event_id>/schedule", methods=["POST"])
def schedule_event(event_id):
    auth.require_role(["Merchandiser"])
    event = S.get_or_404("events", event_id)
    if event["event_status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    # window validity
    if not (event["ends_at"] > event["starts_at"]):
        invalid_request("ends_at must be strictly after starts_at.")
    if (event["ends_at"] - event["starts_at"]).total_seconds() > 72 * 3600:
        invalid_request("The event window may not exceed 72 hours.")
    if event["ship_time_quote_days"] not in SHIP_TIME_QUOTES:
        invalid_request("ship_time_quote_days must be one of 10, 14, 21 or 30.")
    # At least one listing that is (or, on this transition, becomes) ACTIVE.
    # Since POST /listings always starts a listing in DRAFT, the gate is read as
    # "a listing already ACTIVE, or one whose reveal_at the clock has reached"
    # — the same re-evaluation the transition performs as a side effect.
    revealable = [
        l for l in calc.listings_of_event(event["id"])
        if l["listing_status"] == "ACTIVE"
        or (l["reveal_at"] <= now() and l["allocation_units"] > 0)
    ]
    if not revealable:
        fail("ERR_INVALID_STATE")
    shop = S.get_or_404("shops", event["shop_id"])
    if shop["shop_status"] not in ("DRAFT", "SCHEDULED"):
        fail("ERR_SHOP_SUSPENDED")
    if calc.brand_window_blocker(event, shop["id"]) is not None:
        fail("ERR_BRAND_WINDOW_OVERLAP")
    event["event_status"] = "SCHEDULED"
    touch(event)
    # bubble the shop
    if not S.shop_has_committed_event(shop["id"], exclude_event_id=event["id"]):
        if shop["shop_status"] == "DRAFT":
            vendor = db.vendors.get(shop["vendor_id"])
            if vendor is None or vendor["standing"] not in ("EXCELLENT", "GOOD"):
                fail("ERR_VENDOR_STANDING_BLOCKED")
            shop["shop_status"] = "SCHEDULED"
            touch(shop)
    # re-evaluate listings against the clock
    for listing in calc.listings_of_event(event["id"]):
        if (listing["listing_status"] == "DRAFT" and listing["reveal_at"] <= now()
                and listing["allocation_units"] > 0):
            listing["listing_status"] = "ACTIVE"
            touch(listing)
    S.recompute_curated(shop)
    return ok(ser("events", event))


@bp.route("/events/<event_id>/launch", methods=["POST"])
def launch_event(event_id):
    auth.require_role(["Merchandiser"])
    event = S.get_or_404("events", event_id)
    if event["event_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    if now() < event["starts_at"]:
        fail("ERR_EVENT_NOT_STARTED")
    shop = S.get_or_404("shops", event["shop_id"])
    if shop["shop_status"] not in ("SCHEDULED", "OPEN"):
        fail("ERR_SHOP_SUSPENDED")
    event["event_status"] = "LIVE"
    event["open_event_for_shop"] = True
    touch(event)
    shop["shop_status"] = "OPEN"
    touch(shop)
    for listing in calc.listings_of_event(event["id"]):
        if (listing["listing_status"] == "DRAFT" and listing["reveal_at"] <= now()
                and listing["allocation_units"] > 0):
            listing["listing_status"] = "ACTIVE"
            touch(listing)
    S.recompute_curated(shop)
    calc.refresh_event_contribution(event)
    return ok(ser("events", event))


@bp.route("/events/<event_id>/close", methods=["POST"])
def close_event(event_id):
    auth.require_role(["Merchandiser"])
    data = R.body()
    cancel_pending = R.bbool(data, "cancel_pending_aggregations", False)
    event = S.get_or_404("events", event_id)
    if event["event_status"] != "LIVE":
        fail("ERR_INVALID_STATE")
    listing_ids = {l["id"] for l in calc.listings_of_event(event["id"])}
    pending = [
        c for c in calc.all_confirmations()
        if c["listing_id"] in listing_ids and c["confirmation_status"] == "PENDING_AGGREGATION"
    ]
    if pending and not cancel_pending:
        fail("ERR_INVALID_STATE")

    event["event_status"] = "CLOSED"
    event["open_event_for_shop"] = False
    event["closed_at"] = now()
    touch(event)

    # CASCADE 1 -> 2: unplaced lines cancelled
    touched_orders = []
    for line in pending:
        S.cancel_line(line, "EVENT_CLOSED")
        if line["customer_order_id"] not in touched_orders:
            touched_orders.append(line["customer_order_id"])

    # CASCADE 2 -> 3: orders whose every line is terminal with >=1 CANCELLED
    for order_id in touched_orders:
        order = db.orders.get(order_id)
        if order is None:
            continue
        lines = calc.lines_of_order(order_id)
        if not lines:
            continue
        if all(l["confirmation_status"] in calc.TERMINAL_LINE_STATES for l in lines) and any(
            l["confirmation_status"] == "CANCELLED" for l in lines
        ):
            order["order_status"] = "CANCELLED"
            # CASCADE 3 -> 4
            refunded = 0
            for line in lines:
                if line["confirmation_status"] == "CANCELLED":
                    refunded += (line.get("line_unit_price_cents") or 0) * line["quantity"]
            order["payment_status"] = "REFUNDED"
            order["refund_due_cents"] = refunded
            order["refunded_amount_cents"] = refunded
            touch(order)
            if refunded > 0:
                row, _ = S.ledger_issue(
                    order["customer_id"], "CANCELLATION", order["id"], refunded,
                    settle=True,
                )
                S.set_settled(row)
            S.reconcile_customer(db.customers.get(order["customer_id"]))
        else:
            S.refresh_order_derived(order)
            touch(order)

    calc.recompute_event_totals(event)
    for listing in calc.listings_of_event(event["id"]):
        listing["listing_status"] = (
            "SOLD_OUT" if listing["units_ordered"] > 0 else "WITHDRAWN"
        )
        touch(listing)
    calc.refresh_event_contribution(event)

    shop = db.shops.get(event["shop_id"])
    if shop is not None and not S.shop_has_committed_event(shop["id"], exclude_event_id=event["id"]):
        shop["shop_status"] = "CLOSED"
        shop["curated_sku_count"] = 0
        touch(shop)
    if shop is not None:
        S.recompute_curated(shop)
    return ok(ser("events", event))


@bp.route("/events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    auth.require_role(["Merchandiser"])
    data = R.body()
    R.bstr(data, "reason_code", required=False)
    event = S.get_or_404("events", event_id)
    status = event["event_status"]
    if status not in ("DRAFT", "SCHEDULED", "LIVE"):
        fail("ERR_INVALID_STATE")
    shop = db.shops.get(event["shop_id"])
    if status == "SCHEDULED" and shop is not None and shop["shop_status"] == "CLOSED":
        fail("ERR_SHOP_SUSPENDED")
    if status == "LIVE":
        if event["units_po_committed_total"] != 0:
            fail("ERR_INVALID_STATE")
        if event["oversell_units_total"] != 0:
            fail("ERR_INVALID_STATE")

    listing_ids = {l["id"] for l in calc.listings_of_event(event["id"])}
    lines = [c for c in calc.all_confirmations() if c["listing_id"] in listing_ids]

    event["event_status"] = "CANCELLED"
    if status == "LIVE":
        event["open_event_for_shop"] = False
    touch(event)

    if status == "LIVE":
        affected = []
        for line in lines:
            if line["confirmation_status"] == "SHIPPED":
                continue
            if S.cancel_line(line, "EVENT_CANCELLED"):
                if line["customer_order_id"] not in affected:
                    affected.append(line["customer_order_id"])
        for order_id in affected:
            order = db.orders.get(order_id)
            if order is None:
                continue
            calc.recompute_order_total(order)
            # CASCADE 1->2 of the Confirmation machine: the parent order moves
            # to CANCELLED once every one of its lines is terminal.
            order_lines = calc.lines_of_order(order_id)
            if order_lines and all(
                l["confirmation_status"] in calc.TERMINAL_LINE_STATES for l in order_lines
            ):
                order["order_status"] = "CANCELLED"
            order["payment_status"] = "REFUNDED"
            refunded = 0
            for line in calc.lines_of_order(order_id):
                if line["confirmation_status"] == "CANCELLED":
                    refunded += (line.get("line_unit_price_cents") or 0) * line["quantity"]
            order["refund_due_cents"] = refunded
            touch(order)
            if refunded > 0:
                row, _ = S.ledger_issue(
                    order["customer_id"], "CANCELLATION", order["id"], refunded,
                    settle=True,
                )
                S.set_settled(row)
            customer = db.customers.get(order["customer_id"])
            if customer is not None:
                S.reconcile_customer(customer)

    for listing in calc.listings_of_event(event["id"]):
        listing["listing_status"] = "WITHDRAWN"
        touch(listing)
    calc.recompute_event_totals(event)

    if shop is not None:
        if status == "SCHEDULED" or status == "LIVE":
            if not S.shop_has_committed_event(shop["id"], exclude_event_id=event["id"]):
                shop["shop_status"] = "CLOSED"
                shop["curated_sku_count"] = 0
                touch(shop)
        S.recompute_curated(shop)
    return ok(ser("events", event))


@bp.route("/events/<event_id>/run-event-checkpoint", methods=["POST"])
def run_checkpoint(event_id):
    auth.require_role(["Merchandiser"])
    event = S.get_or_404("events", event_id)
    event["checkpoint_index"] = event["checkpoint_index"] + 1
    touch(event)
    calc.refresh_event_contribution(event)
    S.rescore_vendors_in_scope()
    S.lapse_return_escalations()
    S.restrict_over_cancellers()
    calc.reconcile_event(event)
    return ok(ser("events", event))


# ==========================================================================
# Listing
# ==========================================================================

@bp.route("/listings", methods=["POST"])
def create_listing():
    auth.require_role(["Merchandiser"])
    data = R.body()
    event_id = R.bstr(data, "event_id")
    vendor_sku = R.bstr(data, "vendor_sku")
    unit_price = R.bint(data, "unit_price_cents")
    vendor_cost = R.bint(data, "vendor_unit_cost_cents")
    allocation = R.bint(data, "allocation_units")
    reveal_at = R.btime(data, "reveal_at")
    event = S.get_or_404("events", event_id)
    if unit_price <= 0:
        invalid_request("unit_price_cents must be strictly positive.")
    if vendor_cost < 0 or allocation < 0:
        invalid_request("Money and allocation fields may not be negative.")
    # vendor_sku unique within the event
    for listing in calc.listings_of_event(event["id"]):
        if listing["vendor_sku"] == vendor_sku:
            fail("ERR_DUPLICATE_VENDOR_SKU")
    listing = {
        "event_id": event["id"],
        "vendor_sku": vendor_sku,
        "unit_price_cents": unit_price,
        "vendor_unit_cost_cents": vendor_cost,
        "allocation_units": allocation,
        "units_ordered": 0,
        "oversell_units": 0,
        "listing_status": "DRAFT",
        "reveal_at": reveal_at,
    }
    # PRD §3.2: neither adding a fresh listing nor reviving a sold-out one may push
    # the shop's curated_sku_count above 40 active listings across its SCHEDULED and
    # LIVE events. A listing merchandised into a DRAFT event does not consume the
    # ceiling, because such an event's listings are not counted at all.
    shop = db.shops.get(event["shop_id"])
    if shop is not None and event["event_status"] in ("SCHEDULED", "LIVE"):
        if S.recompute_curated(shop) + 1 > SKU_CAP:
            fail("ERR_SHOP_SKU_LIMIT_EXCEEDED")
    stamp(listing)
    db.listings[listing["id"]] = listing
    if shop is not None:
        S.recompute_curated(shop)
    return created(ser("listings", listing))


@bp.route("/listings/<listing_id>", methods=["GET"])
def read_listing(listing_id):
    auth.require_role(["Any"])
    listing = S.get_or_404("listings", listing_id)
    calc.reconcile_listing_units(listing)
    return ok(ser("listings", listing))


@bp.route("/listings", methods=["GET"])
def list_listings():
    auth.require_role(["Any"])
    limit, offset = R.pagination()
    event_id = R.q("event_id")
    status = R.q("listing_status")
    items = list(db.listings.values())
    if event_id is not None:
        items = [l for l in items if l["event_id"] == event_id]
    if status is not None:
        items = [l for l in items if l["listing_status"] == status]
    from store import ordered
    return base_list(ser_all("listings", ordered(items)), limit, offset)


@bp.route("/listings/<listing_id>/oversell-preview", methods=["GET"])
def oversell_preview(listing_id):
    auth.require_role(["Merchandiser"])
    listing = S.get_or_404("listings", listing_id)
    allocation = listing["allocation_units"]
    excess = max(0, listing["units_ordered"] - allocation) if allocation > 0 else 0
    splits = calc.oversell_split(listing, "cancel_newest_first")
    ordered_lines = calc.order_candidates(calc.candidate_lines(listing), "cancel_newest_first")
    payload = []
    for line in ordered_lines:
        payload.append({
            "confirmation_id": line["id"],
            "quantity": line["quantity"],
            "line_unit_price_cents": line.get("line_unit_price_cents"),
            "confirmed_at": None if line.get("confirmed_at") is None else
                __import__("store").iso(line["confirmed_at"]),
            "oversold_units": splits.get(line["id"], 0),
        })
    return ok({
        "listing_id": listing["id"],
        "allocation_units": allocation,
        "units_ordered": listing["units_ordered"],
        "excess_units": excess,
        "provisional_variant": "cancel_newest_first",
        "provisional_splits": payload,
    })


@bp.route("/listings/<listing_id>/reallocate", methods=["POST"])
def reallocate(listing_id):
    auth.require_role(["Merchandiser"])
    data = R.body()
    listing = S.get_or_404("listings", listing_id)
    expected = data.get("expected_listing_version")
    if expected is None:
        invalid_request("expected_listing_version is required.")
    if not isinstance(expected, int) or isinstance(expected, bool):
        invalid_request("expected_listing_version must be an integer.")
    if expected != listing["version"]:
        fail("ERR_STALE_VERSION")
    event = S.get_or_404("events", listing["event_id"])
    if event["event_status"] != "LIVE":
        fail("ERR_INVALID_STATE")
    new_allocation = R.bint(data, "allocation_units")
    if new_allocation <= listing["units_ordered"]:
        fail("ERR_ALLOCATION_EXCEEDED")
    # 20% oversell bound applies to the resulting watermark
    shop = db.shops.get(event["shop_id"])
    if event["event_status"] in ("SCHEDULED", "LIVE"):
        prospective = S.recompute_curated(shop)
        if listing["listing_status"] != "ACTIVE" and prospective + 1 > SKU_CAP:
            fail("ERR_SHOP_SKU_LIMIT_EXCEEDED")
    listing["allocation_units"] = new_allocation
    if listing["listing_status"] == "SOLD_OUT":
        listing["listing_status"] = "ACTIVE"
    touch(listing)
    calc.apply_oversell_watermark(listing, "fifo_by_confirmed_at")
    calc.recompute_event_totals(event)
    if shop is not None:
        S.recompute_curated(shop)
    return ok(ser("listings", listing))


@bp.route("/listings/<listing_id>/withdraw", methods=["POST"])
def withdraw(listing_id):
    auth.require_role(["Merchandiser"])
    listing = S.get_or_404("listings", listing_id)
    if listing["listing_status"] not in ("ACTIVE", "SOLD_OUT"):
        fail("ERR_INVALID_STATE")
    for line in calc.lines_of_listing(listing["id"]):
        if line["confirmation_status"] in LINE_COMMITTED_STATES:
            fail("ERR_INVALID_STATE")
    was_active = listing["listing_status"] == "ACTIVE"
    listing["listing_status"] = "WITHDRAWN"
    touch(listing)
    if was_active:
        for line in calc.lines_of_listing(listing["id"]):
            if line["confirmation_status"] == "PENDING_VENDOR":
                S.cancel_line(line, "LISTING_WITHDRAWN")
                order = db.orders.get(line["customer_order_id"])
                if order is not None:
                    S.refresh_order_derived(order)
                    touch(order)
    event = db.events.get(listing["event_id"])
    shop = db.shops.get(event["shop_id"]) if event else None
    if shop is not None:
        S.recompute_curated(shop)
    return ok(ser("listings", listing))


@bp.route("/listings/<listing_id>/purchase-order-lines", methods=["GET"])
def listing_polines(listing_id):
    auth.require_role(["Any"])
    listing = S.get_or_404("listings", listing_id)
    limit, offset = R.pagination()
    status = R.q("poline_status")
    items = [l for l in db.polines.values() if l["listing_id"] == listing["id"]]
    if status is not None:
        items = [l for l in items if l["poline_status"] == status]
    from store import ordered
    return base_list(ser_all("polines", ordered(items)), limit, offset)


def drift(payload):
    """A read that repaired a field surfaces ERR_DERIVED_FIELD_DRIFT."""
    from response import drift_response
    return drift_response()