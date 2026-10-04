"""Sale action endpoints: apply-coupon, complete, void, returns.
Registered as additional rules on the sales blueprint."""
from datetime import timedelta
from flask import request
from db import DB, fmt_iso, parse_iso
from response import success
from middleware import require_roles
from entities import touch, get_or_404, lazy_coupon, effective_member
from errors import raise_err
from calc import basket_cents, coupon_discount_amount, margin_floor_ok, eligible_line
from savings import recompute_membership_savings
from routes.sales import bp, s_view, _sale_lines, _recompute_subtotal, _resolve_price


def _redemption_gate(coupon, sale, discount_preview=None, own_reservation=0):
    """Ordered gate. Returns computed discount on success. own_reservation is
    this sale's already-held reservation (excluded from the budget check when
    the gate re-runs at completion, so it is not double-counted)."""
    lazy_coupon(coupon)
    if coupon["status"] == "EXHAUSTED":
        raise_err("ERR_COUPON_EXHAUSTED", "Coupon exhausted")
    now = DB.now()
    ws = parse_iso(coupon["window_start"])
    we = parse_iso(coupon["window_end"])
    mes = parse_iso(coupon.get("member_early_start")) if coupon.get("member_early_start") else None
    member = effective_member(sale["customer_id"], now)
    start = mes if (member and mes) else ws
    # The time-window rule is the primary key for any at/past-window_end
    # rejection: lazy EXPIRED status is a derived view of the very same rule,
    # so the window check runs before the not-ACTIVE status check to keep
    # ERR_COUPON_OUTSIDE_WINDOW (not ERR_COUPON_NOT_ACTIVE) as the outcome.
    if now < start or now >= we:
        raise_err("ERR_COUPON_OUTSIDE_WINDOW", "Outside redemption window")
    if coupon["status"] != "ACTIVE":
        raise_err("ERR_COUPON_NOT_ACTIVE", "Coupon not ACTIVE")
    if coupon["audience"] == "MEMBERS_ONLY" and not member:
        raise_err("ERR_COUPON_MEMBERS_ONLY", "Members only coupon")
    # per-customer limit: at apply time no completion has consumed this sale's
    # redemption yet; at completion the gate re-runs on an already-applied
    # sale, whose own usage has not been recorded yet either (the count
    # increments only on successful completion), so no exclusion is needed.
    usage = 0
    today = fmt_iso(DB.now())[:10]
    for rec in coupon.get("usage_records", []):
        if rec.get("customer_id") == sale["customer_id"]:
            if coupon["channel"] == "PRINT":
                # per calendar day of redemption: a stale daily count from an
                # earlier day does not count against today
                if rec.get("last_day") == today:
                    usage = rec.get("count_today", 0)
            else:
                usage = rec.get("count", 0)
    if usage >= coupon["per_customer_limit"]:
        raise_err("ERR_COUPON_CUSTOMER_LIMIT_REACHED", "Per-customer limit reached")
    # min basket
    B = basket_cents(sale["id"])
    if B < coupon["min_basket_cents"]:
        raise_err("ERR_COUPON_MIN_BASKET_NOT_MET", "Basket below minimum")
    discount = coupon_discount_amount(coupon, sale["id"]) if discount_preview is None else discount_preview
    if discount + coupon["budget_spent_cents"] + coupon["budget_reserved_cents"] - own_reservation > coupon["budget_cents"]:
        raise_err("ERR_COUPON_BUDGET_EXCEEDED", "Coupon budget exceeded")
    return discount


@bp.route("/sales/<saleId>/apply-coupon", methods=["POST"])
@require_roles("StoreClerk")
def apply_coupon(saleId):
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Sale not OPEN")
    b = request.get_json(silent=True) or {}
    code = b.get("coupon_code")
    if not code:
        raise_err("ERR_VALIDATION", "coupon_code required")
    coupon = None
    for c in DB.coupons.values():
        if c["code"].lower() == str(code).lower():
            coupon = c
            break
    if coupon is None:
        raise_err("ERR_NOT_FOUND", "Coupon not found")
    if sale["applied_coupon_id"]:
        raise_err("ERR_COUPON_ALREADY_APPLIED", "Sale already has a coupon")
    # re-resolve line prices at apply time? No: resolution at line-add and complete.
    discount = _redemption_gate(coupon, sale)
    sale["applied_coupon_id"] = coupon["id"]
    sale["coupon_discount_cents"] = discount
    _recompute_subtotal(sale)
    touch(sale)
    coupon["budget_reserved_cents"] += discount
    touch(coupon)
    return success(s_view(sale))


@bp.route("/sales/<saleId>/complete", methods=["POST"])
@require_roles("StoreClerk")
def complete_sale(saleId):
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Sale not OPEN")
    lines = _sale_lines(sale["id"])
    if len(lines) < 1:
        raise_err("ERR_EMPTY_SALE", "Sale has no lines")
    store = get_or_404(DB.stores, sale["store_id"])
    customer = get_or_404(DB.customers, sale["customer_id"])
    # re-resolve line prices at completion (complete-time value wins)
    for ln in lines:
        if not ln.get("is_warranty_line"):
            item = DB.items.get(ln["item_id"])
            price = _resolve_price(sale["customer_id"], item)
            ln["unit_price_cents"] = price
            ln["line_total_cents"] = price * ln["quantity"]
            touch(ln)
    _recompute_subtotal(sale)
    # assortment check
    for ln in lines:
        if ln["item_id"] not in store["assortment_item_ids"]:
            raise_err("ERR_ITEM_NOT_IN_STORE_ASSORTMENT", "Line item not in store assortment")
    # recall safety gate precedes the item-lifecycle gate at completion:
    # quarantined items fail the lifecycle check, so the safety gate must be
    # evaluated first for its dedicated error to surface (PRD §3.7).
    for ln in lines:
        item = DB.items.get(ln["item_id"])
        for r in DB.recalls.values():
            if (r["item_id"] == item["id"] and r["status"] == "ACTIVE"
                    and r["severity"] in ("STOP_SALE", "HAZARD")):
                raise_err("ERR_SAFETY_HOLD", "Line item under active recall")
    # item lifecycle gate
    for ln in lines:
        item = DB.items.get(ln["item_id"])
        if item["lifecycle_status"] != "ACTIVE":
            raise_err("ERR_ITEM_NOT_ACTIVE", "Line item not ACTIVE")
    # margin floor on non-warranty lines
    for ln in lines:
        if not ln.get("is_warranty_line"):
            item = DB.items.get(ln["item_id"])
            if not margin_floor_ok(item, ln["unit_price_cents"]):
                raise_err("ERR_MARGIN_FLOOR_VIOLATION", "Line price below margin floor")
    # coupon gate re-evaluated
    coupon = None
    discount = 0
    if sale["applied_coupon_id"]:
        coupon = get_or_404(DB.coupons, sale["applied_coupon_id"])
        discount = coupon_discount_amount(coupon, sale["id"])
        _redemption_gate(coupon, sale, discount_preview=discount,
                         own_reservation=sale.get("coupon_discount_cents", 0))
        sale["coupon_discount_cents"] = discount
    b = request.get_json(silent=True) or {}
    sc = b.get("store_credit_applied_cents", 0)
    if not isinstance(sc, int) or sc < 0:
        raise_err("ERR_VALIDATION", "store_credit_applied_cents must be >= 0")
    if sc > customer["store_credit_cents"]:
        raise_err("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit")
    sale["store_credit_applied_cents"] = sc
    sale["status"] = "COMPLETED"
    sale["completed_at"] = fmt_iso(DB.now())
    _recompute_subtotal(sale)
    touch(sale)
    if coupon is not None:
        coupon["budget_reserved_cents"] = max(0, coupon["budget_reserved_cents"] - discount)
        coupon["budget_spent_cents"] += discount
        today = fmt_iso(DB.now())[:10]
        records = coupon["usage_records"]
        found = None
        for rec in records:
            if rec.get("customer_id") == customer["id"]:
                found = rec
                break
        if found is None:
            found = {"customer_id": customer["id"], "count": 0, "count_today": 0,
                     "last_day": today}
            records.append(found)
        found["count"] += 1
        if found.get("last_day") != today:
            found["count_today"] = 0
            found["last_day"] = today
        found["count_today"] += 1
        if coupon["budget_spent_cents"] >= coupon["budget_cents"] and coupon["status"] == "ACTIVE":
            coupon["status"] = "EXHAUSTED"
        touch(coupon)
    if sc:
        customer["store_credit_cents"] -= sc
        touch(customer)
    recompute_membership_savings(customer["id"])
    return success(s_view(sale))


@bp.route("/sales/<saleId>/void", methods=["POST"])
@require_roles("StoreClerk")
def void_sale(saleId):
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Sale not OPEN")
    if sale["applied_coupon_id"]:
        coupon = DB.coupons.get(sale["applied_coupon_id"])
        if coupon:
            coupon["budget_reserved_cents"] = max(
                0, coupon["budget_reserved_cents"] - sale["coupon_discount_cents"])
            touch(coupon)
    sale["status"] = "VOID"
    touch(sale)
    return success(s_view(sale))


@bp.route("/sales/<saleId>/returns", methods=["POST"])
@require_roles("StoreClerk")
def return_sale(saleId):
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] not in ("COMPLETED", "RETURNED_PARTIAL"):
        raise_err("ERR_INVALID_STATE", "Sale not in a returnable state")
    b = request.get_json(silent=True) or {}
    if not b.get("sale_line_id"):
        raise_err("ERR_VALIDATION", "sale_line_id required")
    line = DB.sale_lines.get(b["sale_line_id"])
    if not line or line["sale_id"] != sale["id"]:
        raise_err("ERR_NOT_FOUND", "Sale line not found")
    qty = b.get("quantity")
    if not isinstance(qty, int) or qty < 1:
        raise_err("ERR_VALIDATION", "quantity must be >= 1")
    returned = sale["returned_line_quantities"]
    already = returned.get(line["id"], 0)
    if already + qty > line["quantity"]:
        raise_err("ERR_RETURN_QUANTITY_EXCEEDED", "Return quantity exceeded")
    customer = get_or_404(DB.customers, sale["customer_id"])
    # hazard recall override
    item = DB.items.get(line["item_id"])
    hazard = any(r["item_id"] == item["id"] and r["status"] == "ACTIVE"
                 and r["severity"] == "HAZARD" for r in DB.recalls.values())
    if not hazard:
        completed_at = parse_iso(sale["completed_at"])
        member = effective_member(customer["id"])
        window_days = 90 if member else 30
        if DB.now() > completed_at + timedelta(days=window_days):
            raise_err("ERR_RETURN_WINDOW_EXPIRED", "Return window expired")
    line_refund = line["unit_price_cents"] * qty
    if sale["applied_coupon_id"]:
        eligible = eligible_line(sale["id"])
        # eligible line determined at coupon application; approximate by current
        if eligible and eligible["id"] == line["id"]:
            clawback = (sale["coupon_discount_cents"] * qty) // line["quantity"]
            line_refund = max(0, line_refund - clawback)
    returned[line["id"]] = already + qty
    customer["store_credit_cents"] += line_refund
    touch(customer)
    # new sale status
    all_lines = _sale_lines(sale["id"])
    full = all(returned.get(l["id"], 0) >= l["quantity"] for l in all_lines)
    sale["status"] = "RETURNED_FULL" if full else "RETURNED_PARTIAL"
    touch(sale)
    recompute_membership_savings(customer["id"])
    return success(s_view(sale))
