"""Calculation rules from scaffold 1.3."""
from decimal import Decimal, ROUND_HALF_UP
from db import DB
from entities import effective_member


def margin_floor_ok(item, price_cents):
    """Exact rational comparison in hundred-thousandths of a cent.
    Price exactly at floor allowed (>=). Null landed cost passes vacuously."""
    C = item.get("current_landed_unit_cost_cents")
    if C is None:
        return True
    floor_scaled = int(Decimal(str(C)) * (Decimal("1") + Decimal(str(item["floor_margin_pct"]))) * 100000)
    # floor() of the scaled value
    floor_scaled = floor_scaled // 1
    return int(price_cents) * 100000 >= int(floor_scaled)


def provisional_landed_costs(po):
    pool = po["estimated_duty_cents"] + po["estimated_freight_cents"]
    goods = [ln["quantity"] * ln["unit_cost_cents"] for ln in po["lines"]]
    goods_total = sum(goods)
    out = {}
    for i, ln in enumerate(po["lines"]):
        if goods_total > 0 and ln["quantity"] > 0:
            share = (pool * goods[i]) // goods_total
            per_unit = share // ln["quantity"]
        else:
            per_unit = 0
        out[ln["item_id"]] = ln["unit_cost_cents"] + per_unit
    return out


def final_landed_costs(po):
    pool = (po.get("actual_duty_cents") or 0) + (po.get("actual_freight_cents") or 0)
    goods = [ln["quantity"] * ln["unit_cost_cents"] for ln in po["lines"]]
    goods_total = sum(goods)
    running_remainder = 0
    out = {}
    for i, ln in enumerate(po["lines"]):
        if goods_total > 0:
            exact_millicents = (pool * goods[i] * 1000) // goods_total
            share_cents = exact_millicents // 1000
            running_remainder += exact_millicents - share_cents * 1000
            if running_remainder >= 1000:
                share_cents += 1
                running_remainder -= 1000
        else:
            share_cents = 0
        per_unit = share_cents // ln["quantity"] if ln["quantity"] > 0 else 0
        out[ln["item_id"]] = ln["unit_cost_cents"] + per_unit
    return out


def renewal_fee(tier, settled_savings):
    if tier == "CLUB_PLUS":
        return 6999
    if settled_savings >= 20000:
        return 1999
    if settled_savings >= 5000:
        return 2999
    return 3999


def nonwarranty_lines(sale_id):
    return [l for l in DB.sale_lines.values()
            if l["sale_id"] == sale_id and not l.get("is_warranty_line")]


def basket_cents(sale_id):
    return sum(l["line_total_cents"] for l in nonwarranty_lines(sale_id))


def eligible_line(sale_id):
    """Single line whose item has lowest unit_price_cents; tie-break earliest created_at."""
    lines = nonwarranty_lines(sale_id)
    if not lines:
        return None
    return min(lines, key=lambda l: (l["unit_price_cents"], l["created_at"]))


def coupon_discount_amount(coupon, sale_id):
    """Compute discount from current sale state. Does not check min_basket here."""
    B = basket_cents(sale_id)
    dt = coupon["discount_type"]
    dv = coupon["discount_value"]
    if dt in ("PERCENT_OFF_ITEM", "AMOUNT_OFF_ITEM"):
        line = eligible_line(sale_id)
        E = line["line_total_cents"] if line else 0
    else:
        E = B
    if dt in ("PERCENT_OFF_ITEM", "PERCENT_OFF_BASKET"):
        raw = int(Decimal(str(E)) * Decimal(str(dv)) / Decimal("100"))
    else:
        raw = min(int(dv), E)
    if coupon.get("max_discount_cents") is not None:
        return min(raw, coupon["max_discount_cents"])
    return raw


def round4_half_up(num, den):
    if den == 0:
        return 0.0
    q = (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def recompute_claim_rate(item_id):
    from db import DB as _D
    num = 0
    for cl in _D.warranty_claims.values():
        line = _D.sale_lines.get(cl["sale_line_id"])
        if not line:
            continue
        covered = line.get("covered_item_id")
        if covered == item_id and cl["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "SETTLED"):
            num += 1
    den = 0
    for ln in _D.sale_lines.values():
        # Warranty lines are not merchandise rows; the denominator counts the
        # covered item's own (non-warranty) sale lines only.
        if ln["item_id"] == item_id and not ln.get("is_warranty_line"):
            sale = _D.sales.get(ln["sale_id"])
            if sale and sale["status"] in ("COMPLETED", "RETURNED_PARTIAL"):
                den += 1
    return round4_half_up(num, den)
