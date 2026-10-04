"""Entity serializers: internal dicts -> public JSON-shaped dicts.

Whitelists fields so internal keys (``_seq``) never leak. Datetimes become
ISO-8601 strings; Decimal weights become int (when integral) or float.
"""
from datetime import datetime
from decimal import Decimal

from clock import iso


def _num(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _ts(v):
    return iso(v) if isinstance(v, datetime) else v


_COMMON = ("id", "created_at", "updated_at", "version")


def _base(e, fields, common=True):
    out = {}
    if common:
        for k in _COMMON:
            out[k] = _ts(e[k])
    else:
        out["id"] = e["id"]
        out["created_at"] = _ts(e["created_at"])
    for k in fields:
        out[k] = e[k]
    return out


def ser_org(o):
    return _base(o, [
        "name", "brand_license_status", "costing_method", "reserve_floor_cents",
        "diversion_floor_bps", "retail_margin_pool_cents", "reserved_cents",
        "margin_health", "contract_revenue_cents",
    ]) | {
        "total_diverted_lbs": _num(o["total_diverted_lbs"]),
        "total_disposed_lbs": _num(o["total_disposed_lbs"]),
        "diversion_rate_bps": o["diversion_rate_bps"],
        "diversion_compliant": o["diversion_compliant"],
        "last_markdown_week": o["last_markdown_week"],
    }


def ser_territory(t):
    out = _base(t, ["member_org_id", "region_code"], common=False)
    out["effective_from"] = _ts(t["effective_from"])
    out["effective_to"] = _ts(t["effective_to"])
    return out


def ser_site(s):
    return _base(s, ["member_org_id", "name", "site_type"], common=False)


def ser_donation(d):
    out = _base(d, [
        "site_id", "donor_name", "donor_email", "item_count_declared", "status",
        "receipt_issued", "receipt_token", "receipt_fmv_total_cents",
    ])
    out["sorted_at"] = _ts(d["sorted_at"])
    return out


def ser_item(it):
    out = _base(it, [
        "donation_id", "category", "condition_grade", "estimated_value_cents",
        "status", "price_cents", "current_selling_price_cents", "color_tag",
        "floor_week", "markdown_step", "priced_standard_id", "unit_cost_cents",
        "salvage_lot_id",
    ])
    out["weight_lbs"] = _num(it["weight_lbs"])
    out["sold_at"] = _ts(it["sold_at"])
    return out


def ser_standard(s):
    return _base(s, [
        "member_org_id", "category", "target_items_per_hour", "hourly_cost_cents",
        "grade_price_map", "price_floor_cents", "price_ceiling_cents", "status",
    ])


def ser_run(r):
    return _base(r, [
        "site_id", "production_standard_id", "category", "status",
        "item_count_processed", "unsalable_count", "labor_minutes",
        "labor_cost_cents", "gross_rate_iph", "net_rate_iph", "variance_bps",
        "performance_flag",
    ])


def ser_lot(l):
    out = _base(l, [
        "member_org_id", "channel", "status", "item_count",
        "sale_revenue_cents",
    ])
    out["total_weight_lbs"] = _num(l["total_weight_lbs"])
    out["sold_at"] = _ts(l["sold_at"])
    return out


def ser_program(p):
    out = _base(p, [
        "member_org_id", "name", "program_type", "funding_goal_cents",
        "funding_disbursed_cents",
    ])
    out["start_date"] = _ts(p["start_date"])
    out["end_date"] = _ts(p["end_date"])
    return out


def ser_allocation(a):
    return _base(a, [
        "mission_program_id", "amount_cents", "created_by_user_id",
        "approved_by_user_id", "status",
    ])


def ser_contract(c):
    out = _base(c, [
        "member_org_id", "funding_agency", "contract_value_cents",
        "enrolled_headcount", "created_by_user_id", "status",
        "compliance_posture", "attested_payout_cents", "missed_count",
    ])
    out["start_date"] = _ts(c["start_date"])
    out["end_date"] = _ts(c["end_date"])
    return out


def ser_milestone(m):
    out = _base(m, [
        "contract_id", "description", "min_headcount", "payout_cents",
        "status", "attested_by_user_id",
    ])
    out["target_date"] = _ts(m["target_date"])
    return out


def ser_ticket(t):
    out = _base(t, ["member_org_id", "material", "cost_cents"], common=False)
    out["weight_lbs"] = _num(t["weight_lbs"])
    return out
