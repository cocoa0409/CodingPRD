"""Membership savings recompute (settled + optimistic variants)."""
from db import DB
from calc import nonwarranty_lines


def recompute_membership_savings(customer_id):
    from entities import membership_of
    m = membership_of(customer_id)
    if not m:
        return
    settled = 0
    for sale in DB.sales.values():
        if sale["customer_id"] != customer_id:
            continue
        if sale["status"] not in ("COMPLETED", "RETURNED_PARTIAL"):
            continue
        returned = sale.get("returned_line_quantities", {})
        for ln in DB.sale_lines.values():
            if ln["sale_id"] != sale["id"] or ln.get("is_warranty_line"):
                continue
            item = DB.items.get(ln["item_id"])
            if not item:
                continue
            rq = returned.get(ln["id"], 0)
            qty_net = ln["quantity"] - rq
            if qty_net <= 0:
                continue
            diff = item["unit_retail_cents"] - ln["unit_price_cents"]
            if diff > 0:
                settled += diff * qty_net
    optimistic = settled
    for sale in DB.sales.values():
        if sale["customer_id"] != customer_id or sale["status"] != "OPEN":
            continue
        for ln in DB.sale_lines.values():
            if ln["sale_id"] != sale["id"] or ln.get("is_warranty_line"):
                continue
            item = DB.items.get(ln["item_id"])
            if not item:
                continue
            member_price = min(item["member_price_cents"], item["unit_retail_cents"])
            diff = item["unit_retail_cents"] - member_price
            if diff > 0:
                optimistic += diff * ln["quantity"]
    m["settled_savings_cents"] = settled
    m["optimistic_savings_cents"] = optimistic
