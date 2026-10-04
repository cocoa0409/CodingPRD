"""Business services: pricing engine, deposits, savings, cascades, daily cycle."""
from datetime import timedelta

import core
from core import (db, clock_now, fmt_dt, parse_dt, rhu_frac, touch,
                  member_pricing_tier)

MEMBERSHIP_FEE_CENTS = 17500
MEMBERSHIP_PERIOD_DAYS = 365
GRACE_DAYS = 30
CANCEL_REFUND_WINDOW_DAYS = 30
PRINT_LEAD_DAYS = 21
WHITE_GLOVE_FEE_CENTS = 19900
TRADE_WHITE_GLOVE_FEE_CENTS = 14900
FEE_WAIVER_THRESHOLD_CENTS = 1000000
ROUTE_BUFFER_MINUTES = 30
RETURN_WINDOW_DAYS = 30
QUOTE_DAYS = 14
CONSULT_EXTENSION_DAYS = 14

TRADE_PCT = {"TIER_1": "0.30", "TIER_2": "0.40"}


# ---------------------------------------------------------------------------
# Pricing engine
# ---------------------------------------------------------------------------

def order_lines_of(order_id):
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


def recompute_order_pricing(order):
    """Re-run order_line_pricing + order_total for all current lines.

    Recomputes each line's line_charged_cents and deposit_cents from its
    frozen unit_list_price_cents against the current promo set and the
    order's current pricing tier (re-derived from member standing / trade
    account at calculation time).
    """
    # Resolve pricing tier at calculation time.
    if order.get("trade_account_id"):
        order["pricing_tier"] = "TRADE"
    elif order.get("member_id"):
        m = db["members"].get(order["member_id"])
        if m and m["status"] in ("ACTIVE", "GRACE"):
            order["pricing_tier"] = "MEMBER"
        else:
            order["pricing_tier"] = "RETAIL"
    else:
        order["pricing_tier"] = "RETAIL"

    tier = order["pricing_tier"]
    trade_pct = None
    if tier == "TRADE":
        acct = db["trade_accounts"].get(order["trade_account_id"])
        trade_pct = TRADE_PCT[acct["tier"]] if acct and acct.get("tier") else "0.30"

    lines = order_lines_of(order["id"])
    subtotal = 0
    deposit_due = 0
    for line in lines:
        base = line["unit_list_price_cents"]
        product = db["products"].get(line["product_id"])
        promo = bool(product and product.get("promo_active"))
        if promo:
            promo_price = rhu_frac(base, "0.90")
        else:
            promo_price = base
        if tier == "TRADE":
            unit = rhu_frac(base, str(1.0 - float(trade_pct)))
        elif tier == "MEMBER":
            unit = rhu_frac(promo_price, "0.75")
        else:
            unit = promo_price
        line["line_charged_cents"] = unit * line["qty"]
        subtotal += line["line_charged_cents"]
        # Custom deposit
        if line["kind"] == "CUSTOM":
            if tier == "TRADE":
                dep = max(rhu_frac(line["line_charged_cents"], "0.25"), 25000)
            else:
                dep = max(rhu_frac(line["line_charged_cents"], "0.50"), 50000)
            line["deposit_cents"] = dep
            deposit_due += dep
        else:
            line["deposit_cents"] = 0
        touch(line)

    order["subtotal_cents"] = subtotal
    if not lines:
        fee = 0
    elif tier == "TRADE":
        fee = TRADE_WHITE_GLOVE_FEE_CENTS
    else:
        fee = 0 if subtotal >= FEE_WAIVER_THRESHOLD_CENTS else WHITE_GLOVE_FEE_CENTS
    order["white_glove_fee_cents"] = fee
    order["total_cents"] = subtotal + fee
    order["deposit_due_cents"] = deposit_due


# ---------------------------------------------------------------------------
# Gallery derived fields
# ---------------------------------------------------------------------------

def recompute_reserved_production_minutes(gallery_id):
    g = db["galleries"].get(gallery_id)
    if not g:
        return
    total = 0
    for s in db["production_slots"].values():
        if s["gallery_id"] == gallery_id and s["status"] in ("COMMITTED", "IN_PROGRESS"):
            mins = int((parse_dt(s["ends_at"]) - parse_dt(s["starts_at"])).total_seconds() // 60)
            total += mins
    g["reserved_production_minutes"] = total


def booked_minutes(gallery_id, date_str):
    total = 0
    for a in db["appointments"].values():
        if (a["gallery_id"] == gallery_id and a["delivery_date"] == date_str
                and a["status"] in ("SCHEDULED", "OUT_FOR_DELIVERY")):
            total += a["duration_minutes"] + ROUTE_BUFFER_MINUTES
    return total


def sync_booked_route_minutes(gallery_id):
    g = db["galleries"].get(gallery_id)
    if not g:
        return
    m = {}
    for a in db["appointments"].values():
        if a["gallery_id"] == gallery_id and a["status"] in ("SCHEDULED", "OUT_FOR_DELIVERY"):
            m[a["delivery_date"]] = m.get(a["delivery_date"], 0) + a["duration_minutes"] + ROUTE_BUFFER_MINUTES
    g["booked_route_minutes"] = m


# ---------------------------------------------------------------------------
# Quote recompute from remaining completed consultations (Cascade A hop 3)
# ---------------------------------------------------------------------------

def recompute_quote_from_consultations(order):
    """Recompute quote_expires_at = created_at + 14d + 14d * (# COMPLETED
    consultations attached to this order). Also refresh
    consultation_extensions_used. Only applies when order is in QUOTE."""
    if order["status"] != "QUOTE":
        return
    completed = [c for c in db["consultations"].values()
                 if c["order_id"] == order["id"] and c["status"] == "COMPLETED"]
    n = len(completed)
    order["consultation_extensions_used"] = n
    created = parse_dt(order["created_at"])
    order["quote_expires_at"] = fmt_dt(
        created + timedelta(days=QUOTE_DAYS + CONSULT_EXTENSION_DAYS * n))


# ---------------------------------------------------------------------------
# Cascade A: member GRACE -> LAPSED
# ---------------------------------------------------------------------------

def cascade_member_lapsed(member):
    # Hop 2: cancel SCHEDULED consultations of this member
    for c in db["consultations"].values():
        if c["member_id"] == member["id"] and c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            touch(c)
            # Hop 3: recompute attached QUOTE order's quote expiry
            order = db["orders"].get(c["order_id"])
            if order and order["status"] == "QUOTE":
                recompute_quote_from_consultations(order)
                touch(order)
    # Hop 2b: re-price this member's QUOTE orders under RETAIL
    for order in db["orders"].values():
        if order.get("member_id") == member["id"] and order["status"] == "QUOTE":
            recompute_order_pricing(order)
            touch(order)


# ---------------------------------------------------------------------------
# Cascade B: source book release
# ---------------------------------------------------------------------------

def release_source_book(book):
    now = fmt_dt(clock_now())
    # Archive any other RELEASED book; turn off promo for its products that
    # are not in the newly released book.
    new_ids = set(book["product_ids"])
    changed_products = set()
    for other in db["source_books"].values():
        if other["id"] != book["id"] and other["status"] == "RELEASED":
            other["status"] = "ARCHIVED"
            touch(other)
            for pid in other["product_ids"]:
                if pid not in new_ids:
                    p = db["products"].get(pid)
                    if p and p.get("promo_active"):
                        p["promo_active"] = False
                        touch(p)
                        changed_products.add(pid)
    book["status"] = "RELEASED"
    book["released_at"] = now
    touch(book)
    # Hop 2: products in this book get promo_active = true
    for pid in book["product_ids"]:
        p = db["products"].get(pid)
        if p and not p.get("promo_active"):
            p["promo_active"] = True
            touch(p)
            changed_products.add(pid)
    # Hop 3: re-price QUOTE orders containing a product whose promo changed
    for order in db["orders"].values():
        if order["status"] != "QUOTE":
            continue
        lines = order_lines_of(order["id"])
        if any(l["product_id"] in changed_products for l in lines):
            recompute_order_pricing(order)
            touch(order)


# ---------------------------------------------------------------------------
# Daily cycle
# ---------------------------------------------------------------------------

def run_daily_cycle():
    now = clock_now()
    # Step 1: auto-renew ACTIVE members past period end with auto_renew
    for m in db["members"].values():
        if m["status"] == "ACTIVE" and m["auto_renew"] and now > parse_dt(m["current_period_end"]):
            old_end = parse_dt(m["current_period_end"])
            m["fee_paid_total_cents"] += MEMBERSHIP_FEE_CENTS
            m["current_period_start"] = fmt_dt(old_end)
            m["current_period_end"] = fmt_dt(old_end + timedelta(days=MEMBERSHIP_PERIOD_DAYS))
            m["lifetime_net_savings_cents"] = (
                m["lifetime_gross_savings_cents"] - m["fee_paid_total_cents"])
            touch(m)
    # Step 2: ACTIVE -> GRACE for non-auto-renew members past period end
    for m in db["members"].values():
        if m["status"] == "ACTIVE" and now > parse_dt(m["current_period_end"]):
            m["status"] = "GRACE"
            m["grace_end"] = fmt_dt(parse_dt(m["current_period_end"]) + timedelta(days=GRACE_DAYS))
            touch(m)
    # Step 3: GRACE -> LAPSED past grace_end (Cascade A)
    for m in db["members"].values():
        if m["status"] == "GRACE" and m.get("grace_end") and now > parse_dt(m["grace_end"]):
            m["status"] = "LAPSED"
            m["grace_end"] = None
            touch(m)
            cascade_member_lapsed(m)
    # Step 4: release eligible source books (Cascade B)
    for b in db["source_books"].values():
        if b["status"] == "IN_PRINT":
            eligible = parse_dt(b["print_ready_date"]) + timedelta(days=PRINT_LEAD_DAYS)
            if now >= eligible:
                release_source_book(b)
    # Step 5: dispatch due appointments
    today = now.date()
    for a in db["appointments"].values():
        if a["status"] == "SCHEDULED":
            d = core.parse_date(a["delivery_date"])
            if today >= d:
                a["status"] = "OUT_FOR_DELIVERY"
                touch(a)
