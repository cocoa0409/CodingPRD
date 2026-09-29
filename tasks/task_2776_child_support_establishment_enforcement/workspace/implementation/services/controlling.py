"""Controlling-order determination and the CEJ gate (PRD 3.7)."""
import db
from errors import ApiError


def determine(case, referral):
    """Pick the controlling order for a referral, or (None, None)."""
    candidates = [o for o in db.case_orders(case["id"])
                  if o["status"] == "ENTERED" and o["order_type"] == "CURRENT_SUPPORT"]
    if not candidates:
        return None, None
    home = referral.get("child_home_state_code")
    home_orders = [o for o in candidates if o["origin_state_code"] == home]
    # Ties are broken by the earliest created_at, never by id; iterating in
    # created_at order and using a strict comparison keeps the earliest.
    if home_orders:
        winner = home_orders[0]
        for order in home_orders[1:]:
            if order["effective_date"] > winner["effective_date"]:
                winner = order
    else:
        winner = candidates[0]
        for order in candidates[1:]:
            if order["effective_date"] < winner["effective_date"]:
                winner = order
    return winner["id"], winner["origin_state_code"]


def enforce_cej(case):
    """A foreign controlling order closes the gate; no registration leaves it open."""
    registered = [r for r in db.case_referrals(case["id"])
                  if r["status"] in ("REGISTERED", "ENFORCING")
                  and r["controlling_order_state_code"] is not None]
    if not registered:
        return
    for referral in registered:
        if referral["controlling_order_state_code"] != db.HOME_STATE_CODE:
            raise ApiError("ERR_NO_CONTROLLING_ORDER_JURISDICTION")


def live_referrals(case, exclude_id=None):
    return [r for r in db.case_referrals(case["id"])
            if r["id"] != exclude_id and r["status"] != "RETURNED"]
