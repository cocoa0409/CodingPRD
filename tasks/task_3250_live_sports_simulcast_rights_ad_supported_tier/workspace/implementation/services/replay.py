"""Replay assets and property-economics report."""
from db import db
from errors import raise_err, ERR_INVALID_STATE, ERR_NOT_FOUND
from services import calc
import util


def pull_asset(asset):
    if asset["status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE, "replay asset not AVAILABLE")
    win = db.windows.get(asset["window_id"])
    prop = db.properties.get(win["property_id"]) if win else None
    if prop is None or prop["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "owning property not ACTIVE or SUSPENDED")
    asset["status"] = "PULLED"
    util.touch(asset)
    return asset


def property_economics(property_id):
    prop = db.properties.get(property_id)
    if prop is None:
        raise_err(ERR_NOT_FOUND, "property not found")
    amortized = calc.amortized_fee_cents(prop)
    prop["amortized_fee_cents"] = amortized
    win_ids = {w["id"] for w in db.windows.values() if w["property_id"] == prop["id"]}
    slot_ids = {s["id"] for s in db.ad_slots.values() if s["window_id"] in win_ids}
    ad_revenue = sum(i["revenue_cents"] for i in db.impressions.values() if i["slot_id"] in slot_ids)
    subscriber_revenue = sum(
        v.get("marquee_credit_cents", 0) for v in db.viewers.values()
        if v.get("acquisition_window_id") in win_ids
    )
    prov, final = calc.churn_report(prop)
    return {
        "property_id": prop["id"],
        "amortized_fee_cents": amortized,
        "ad_revenue_cents": ad_revenue,
        "subscriber_revenue_cents": subscriber_revenue,
        "net_cents": ad_revenue + subscriber_revenue - amortized,
        "provisional_churn_pct": prov,
        "final_churn_pct": final,
    }
