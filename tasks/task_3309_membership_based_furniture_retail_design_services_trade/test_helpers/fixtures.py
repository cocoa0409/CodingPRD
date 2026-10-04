"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints
(the runner restarts the server before every test, so nothing carries over).
Setup calls use get_success_data() so a failure surfaces as a clear
"Setup step failed" error instead of a confusing assertion failure.

Identity threading: Member/TradeDesigner roles are entity-backed, so every
ownership-gated call builds headers with the real entity id.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_member_payload,
    create_trade_account_payload,
    create_gallery_payload,
    create_product_payload,
    create_source_book_payload,
    create_order_payload,
    add_order_line_payload,
    create_production_slot_payload,
    create_design_consultation_payload,
    create_delivery_appointment_payload,
    create_return_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_trade_designer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]
REVIEWER = TEST_USERS["trade_reviewer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
HUB = TEST_USERS["hub_operator_headers"]
ANON = TEST_USERS["anonymous_headers"]

_COUNTER = [0]


def _uniq(prefix: str) -> str:
    _COUNTER[0] += 1
    return f"{prefix}-{_COUNTER[0]}-{uuid.uuid4().hex[:8]}"


def _uniq_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


# ---------------------------------------------------------------------------
# Base builders
# ---------------------------------------------------------------------------

def setup_gallery(**overrides):
    """Create a gallery. Returns the gallery dict."""
    overrides.setdefault("name", _uniq("Gallery"))
    payload = create_gallery_payload(**overrides)
    return get_success_data(api_client.create_gallery(payload, ADMIN))


def setup_product(list_price_cents=10000, line_kind="STOCK", **overrides):
    """Create a product. Returns the product dict."""
    payload = create_product_payload(
        sku=_uniq("SKU"), list_price_cents=list_price_cents, line_kind=line_kind, **overrides
    )
    return get_success_data(api_client.create_product(payload, ADMIN))


def setup_member(auto_renew=False, **overrides):
    """Enroll a member. Returns the member dict (as returned by POST /members)."""
    overrides.setdefault("email", _uniq_email())
    payload = create_member_payload(auto_renew=auto_renew, **overrides)
    return get_success_data(api_client.create_member(payload, ANON))


def setup_trade_account(**overrides):
    """Apply for a trade account. Returns the APPLIED account."""
    overrides.setdefault("email", _uniq_email())
    payload = create_trade_account_payload(**overrides)
    return get_success_data(api_client.create_trade_account(payload, ANON))


def verify_trade_account(account_id, tier="TIER_1"):
    """APPLIED -> VERIFIED with the supplied tier. Returns the account."""
    return get_success_data(
        api_client.verify_trade_account(account_id, {"decision": "APPROVE", "tier": tier}, REVIEWER)
    )


def reject_trade_account(account_id):
    """APPLIED -> REJECTED. Returns the account."""
    return get_success_data(
        api_client.verify_trade_account(account_id, {"decision": "REJECT"}, REVIEWER)
    )


def set_clock(to_iso8601):
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_daily_cycle():
    get_success_data(api_client.run_daily_cycle(ADMIN))


# ---------------------------------------------------------------------------
# Order builders (three creation shapes)
# ---------------------------------------------------------------------------

def create_retail_quote(gallery_id, headers=ASSOCIATE):
    """Retail guest QUOTE order (no customer reference). Returns order dict."""
    return get_success_data(api_client.create_order(create_order_payload(gallery_id), headers))


def create_member_quote(gallery_id, member_id):
    """Member QUOTE order; member_id must equal the caller's X-User-ID."""
    headers = make_member_headers(member_id)
    return get_success_data(
        api_client.create_order(create_order_payload(gallery_id, member_id=member_id), headers)
    )


def create_trade_quote(gallery_id, trade_account_id):
    """Trade QUOTE order; trade_account_id must equal the caller's X-User-ID."""
    headers = make_trade_designer_headers(trade_account_id)
    return get_success_data(
        api_client.create_order(
            create_order_payload(gallery_id, trade_account_id=trade_account_id), headers
        )
    )


def add_line(order_id, product_id, qty=1, headers=ASSOCIATE, **overrides):
    """Add a line. Returns the created OrderLine."""
    payload = add_order_line_payload(product_id, qty=qty, **overrides)
    return get_success_data(api_client.add_order_line(order_id, payload, headers))


def confirm_order(order_id, payload=None, headers=ASSOCIATE):
    """Confirm an order (supply deposit_payment_cents in payload when due)."""
    return get_success_data(api_client.confirm_order(order_id, payload or {}, headers))


def read_order(order_id, headers=ADMIN):
    return get_success_data(api_client.get_order(order_id, headers))


# ---------------------------------------------------------------------------
# Delivery lifecycle
# ---------------------------------------------------------------------------

def schedule_appointment(order_id, gallery_id, delivery_date="2026-09-05",
                         duration_minutes=60, headers=ASSOCIATE, **overrides):
    """Create a SCHEDULED delivery appointment. Returns the appointment."""
    payload = create_delivery_appointment_payload(
        order_id, gallery_id,
        delivery_date=delivery_date, duration_minutes=duration_minutes, **overrides
    )
    return get_success_data(api_client.create_delivery_appointment(payload, headers))


def deliver_order(order_id, gallery_id, delivery_date="2026-09-05", duration_minutes=60):
    """Walk a READY_FOR_DELIVERY order to DELIVERED: schedule an appointment,
    advance the clock to the delivery date, run the cycle to dispatch it
    (SCHEDULED -> OUT_FOR_DELIVERY), then record COMPLETED.

    Returns (appointment, order). Order must already be READY_FOR_DELIVERY.
    """
    appointment = schedule_appointment(order_id, gallery_id, delivery_date=delivery_date,
                                       duration_minutes=duration_minutes)
    set_clock(f"{delivery_date}T08:00:00Z")
    run_daily_cycle()
    get_success_data(
        api_client.record_appointment_outcome(
            appointment["id"], {"outcome": "COMPLETED", "packaging_removed": True}, HUB
        )
    )
    return appointment, read_order(order_id)


def setup_delivered_stock_order(list_price_cents=10000, qty=1, member=None,
                                delivery_date="2026-09-05"):
    """Gallery + stock product + QUOTE order with `qty` of one line, confirmed,
    then delivered on `delivery_date`. When `member` (a member dict) is given the
    order is a member order; otherwise a retail guest order.

    Returns dict with keys: gallery, product, order, line, appointment
    (order reflects post-delivery state)."""
    gallery = setup_gallery()
    product = setup_product(list_price_cents=list_price_cents, line_kind="STOCK")
    if member is not None:
        order = create_member_quote(gallery["id"], member["id"])
        headers = make_member_headers(member["id"])
    else:
        order = create_retail_quote(gallery["id"])
        headers = ASSOCIATE
    line = add_line(order["id"], product["id"], qty=qty, headers=headers)
    confirm_order(order["id"], headers=headers)
    appointment, order = deliver_order(order["id"], gallery["id"], delivery_date=delivery_date)
    return {
        "gallery": gallery,
        "product": product,
        "order": order,
        "line": line,
        "appointment": appointment,
    }


# ---------------------------------------------------------------------------
# Custom production lifecycle
# ---------------------------------------------------------------------------

def setup_confirmed_custom_order(list_price_cents=120000, qty=1, member=None,
                                 num_lines=1, deposit_total=None):
    """Gallery + CUSTOM product + QUOTE order with `num_lines` custom lines,
    confirmed with an exact deposit. For a retail/member order the per-line
    deposit of a 120000-cent custom line is 60000, so the default deposit total
    is num_lines * (rate on the charged amount, floored) computed for 120000.

    Returns dict with keys: gallery, product, order, lines, headers.
    Caller may pass deposit_total explicitly when it knows the exact due."""
    gallery = setup_gallery()
    product = setup_product(list_price_cents=list_price_cents, line_kind="CUSTOM")
    if member is not None:
        order = create_member_quote(gallery["id"], member["id"])
        headers = make_member_headers(member["id"])
    else:
        order = create_retail_quote(gallery["id"])
        headers = ASSOCIATE
    lines = []
    for _ in range(num_lines):
        lines.append(add_line(order["id"], product["id"], qty=qty, headers=headers))
    if deposit_total is None:
        due = read_order(order["id"])["deposit_due_cents"]
    else:
        due = deposit_total
    order = confirm_order(order["id"], {"deposit_payment_cents": due}, headers=headers)
    return {
        "gallery": gallery,
        "product": product,
        "order": order,
        "lines": lines,
        "headers": headers,
        "deposit_total": due,
    }


def commit_line_to_slot(order_id, line_id, gallery_id,
                        starts_at="2026-09-10T09:00:00Z", ends_at="2026-09-10T12:00:00Z"):
    """Open a production slot and commit it to a DEPOSIT_PAID custom line.
    Returns the (now COMMITTED) slot."""
    slot = get_success_data(
        api_client.create_production_slot(
            create_production_slot_payload(gallery_id, starts_at=starts_at, ends_at=ends_at),
            PLANNER,
        )
    )
    get_success_data(
        api_client.schedule_production(order_id, line_id,
                                       {"production_slot_id": slot["id"]}, PLANNER)
    )
    return get_success_data(api_client.get_production_slot(slot["id"], PLANNER))


def setup_in_production_custom_order(list_price_cents=120000):
    """Retail guest CONFIRMED order with one custom line committed to a slot and
    the slot advanced to IN_PROGRESS. Returns the setup dict plus `slot`."""
    setup = setup_confirmed_custom_order(list_price_cents=list_price_cents)
    line = setup["lines"][0]
    slot = commit_line_to_slot(setup["order"]["id"], line["id"], setup["gallery"]["id"])
    get_success_data(api_client.advance_production_slot(slot["id"], {"to_state": "IN_PROGRESS"}, PLANNER))
    setup["slot"] = get_success_data(api_client.get_production_slot(slot["id"], PLANNER))
    setup["order"] = read_order(setup["order"]["id"])
    return setup


def setup_delivered_custom_order(list_price_cents=120000, delivery_date="2026-09-05"):
    """Retail guest custom order taken all the way to DELIVERED: confirmed with
    deposit, slot committed and advanced IN_PROGRESS -> CONSUMED (bubbling the
    order to READY_FOR_DELIVERY), then delivered. Returns the setup dict."""
    setup = setup_in_production_custom_order(list_price_cents=list_price_cents)
    get_success_data(
        api_client.advance_production_slot(setup["slot"]["id"], {"to_state": "CONSUMED"}, PLANNER)
    )
    appointment, order = deliver_order(setup["order"]["id"], setup["gallery"]["id"],
                                       delivery_date=delivery_date)
    setup["order"] = order
    setup["appointment"] = appointment
    return setup


# ---------------------------------------------------------------------------
# Consultations
# ---------------------------------------------------------------------------

def setup_member_quote_with_consultation(list_price_cents=10000):
    """Member + gallery + stock product + member QUOTE order with one line +
    a SCHEDULED consultation attached. Returns dict of all pieces."""
    gallery = setup_gallery()
    member = setup_member()
    product = setup_product(list_price_cents=list_price_cents, line_kind="STOCK")
    order = create_member_quote(gallery["id"], member["id"])
    headers = make_member_headers(member["id"])
    line = add_line(order["id"], product["id"], headers=headers)
    consultation = get_success_data(
        api_client.create_design_consultation(
            create_design_consultation_payload(member["id"], order["id"]), headers
        )
    )
    return {
        "gallery": gallery,
        "member": member,
        "product": product,
        "order": order,
        "line": line,
        "consultation": consultation,
        "headers": headers,
    }


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

def extend_quote_via_consultation(order_id, member_id=None, days=14, headers=None):
    """Book and complete a consultation attached to a QUOTE order, extending
    `quote_expires_at` by 14 days per completion (PRD §3.6).

    Each completed consultation on an order still in QUOTE moves the expiry
    out by 14 days, so repeat calls stack. `days` must be a multiple of 14.
    Booking uses the member's own headers when `member_id` is given (PRD
    §3.6 ownership rule); completion is recorded by a GalleryAssociate.
    """
    if days % 14 != 0:
        raise ValueError("days must be a multiple of 14")
    for _ in range(days // 14):
        if member_id is not None:
            payload = create_design_consultation_payload(member_id, order_id)
            book_headers = headers or make_member_headers(member_id)
        else:
            # Retail guest orders cannot take member consultations per PRD §3.6
            # (booking names a member_id), so book on behalf of a fresh member.
            m = setup_member()
            payload = create_design_consultation_payload(m["id"], order_id)
            book_headers = ASSOCIATE
        consultation = get_success_data(
            api_client.create_design_consultation(payload, book_headers)
        )
        get_success_data(
            api_client.complete_design_consultation(
                consultation["id"], {"design_plan_notes": "notes"}, ASSOCIATE
            )
        )


def setup_requested_return(list_price_cents=10000, num_lines=1, qty=1):
    """Delivered retail guest stock order with `num_lines` identical lines, and a
    REQUESTED return over all of them. Returns dict with gallery/product/order/
    lines/return."""
    gallery = setup_gallery()
    product = setup_product(list_price_cents=list_price_cents, line_kind="STOCK")
    order = create_retail_quote(gallery["id"])
    lines = [add_line(order["id"], product["id"], qty=qty) for _ in range(num_lines)]
    confirm_order(order["id"])
    appointment, order = deliver_order(order["id"], gallery["id"])
    ret = get_success_data(
        api_client.create_return(
            create_return_payload(order["id"], [l["id"] for l in lines]), ASSOCIATE
        )
    )
    return {
        "gallery": gallery,
        "product": product,
        "order": order,
        "lines": lines,
        "appointment": appointment,
        "return": ret,
    }
