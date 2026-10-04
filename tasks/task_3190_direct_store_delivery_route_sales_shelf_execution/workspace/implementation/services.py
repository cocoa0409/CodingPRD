"""Domain services: lot/day recompute, FEFO consumption, settlement ledger,
promo-window expiry. All shared business logic lives here."""

from datetime import date

import db as store
from helpers import get, touch

FRESHNESS_MIN_DAYS = 5
STALE_WINDOW_DAYS = 5
VARIANCE_TOLERANCE_CENTS = 200
SALVAGE_RATE_NUM = 2  # 0.40 as a fraction: 2/5
SALVAGE_RATE_DEN = 5
STALE_WATCH_THRESHOLD = 0.08


# ---------------------------------------------------------------------------
# lots / route-day recompute
# ---------------------------------------------------------------------------

def lot_remaining(lot):
    return (
        lot["loaded_cases"]
        - lot["delivered_cases"]
        - lot["stale_pulled_cases"]
        - lot["returned_cases"]
    )


def day_lots(route_day_id):
    return [l for l in store.db["lots"].values() if l["route_day_id"] == route_day_id]


def recompute_day_totals(day, bump=True):
    lots = day_lots(day["id"])
    day["loaded_cases"] = sum(l["loaded_cases"] for l in lots)
    day["delivered_cases"] = sum(l["delivered_cases"] for l in lots)
    day["stale_pulled_cases"] = sum(l["stale_pulled_cases"] for l in lots)
    if bump:
        touch(day)


def open_lots_for(route_day_id, product_id):
    return [
        l
        for l in day_lots(route_day_id)
        if l["product_id"] == product_id and l["status"] == "OPEN"
    ]


def days_to_expiry(lot, day):
    return (date.fromisoformat(lot["expiration_date"]) - date.fromisoformat(day["service_date"])).days


def fefo_order(lots):
    return sorted(lots, key=lambda l: (l["expiration_date"], l["created_at"], l["id"]))


def freshness_eligible_lots(route_day_id, product_id, day):
    lots = [
        l
        for l in open_lots_for(route_day_id, product_id)
        if lot_remaining(l) > 0 and days_to_expiry(l, day) > FRESHNESS_MIN_DAYS
    ]
    return fefo_order(lots)


def stale_eligible_lots(route_day_id, product_id, day):
    lots = [
        l
        for l in open_lots_for(route_day_id, product_id)
        if lot_remaining(l) > 0 and days_to_expiry(l, day) <= STALE_WINDOW_DAYS
    ]
    return fefo_order(lots)


# ---------------------------------------------------------------------------
# settlement ledger
# ---------------------------------------------------------------------------

def recompute_settlement(st):
    day_id = st["route_day_id"]
    gross = 0
    for order in store.db["orders"].values():
        if order["route_day_id"] == day_id and order["status"] == "DELIVERED":
            gross += order["gross_total_cents"]
    credits = 0
    for credit in store.db["stale_credits"].values():
        if credit["route_day_id"] == day_id and credit["status"] == "APPROVED":
            credits += credit["credit_cents"]
    forward_gross = 0
    for lot in day_lots(day_id):
        sold = lot["loaded_cases"] - lot["stale_pulled_cases"] - lot_remaining(lot)
        if sold:
            product = get("products", lot["product_id"])
            forward_gross += sold * product["case_price_cents"]
    st["gross_delivered_cents"] = gross
    st["credits_cents"] = credits
    st["forward_expected_cents"] = forward_gross - credits
    st["chronological_expected_cents"] = gross - credits
    st["recon_delta_cents"] = st["forward_expected_cents"] - st["chronological_expected_cents"]
    if st["cash_collected_cents"] is not None:
        st["variance_cents"] = st["cash_collected_cents"] - st["chronological_expected_cents"]
    else:
        st["variance_cents"] = None


def ledger_moved(day_id):
    """Recompute the day's settlement (if any) and auto-reopen a BALANCED one."""
    st = find_settlement(day_id)
    if st is None:
        return
    recompute_settlement(st)
    if st["status"] == "BALANCED":
        st["status"] = "OPEN"
    touch(st)


def find_settlement(route_day_id):
    for st in store.db["settlements"].values():
        if st["route_day_id"] == route_day_id:
            return st
    return None


# ---------------------------------------------------------------------------
# promo agreement window lifecycle
# ---------------------------------------------------------------------------

def expire_agreements():
    clock_date = store.clock.date()
    for ag in store.db["promo_agreements"].values():
        if ag["status"] in ("SCHEDULED", "ACTIVE"):
            if date.fromisoformat(ag["window_end"]) <= clock_date:
                ag["status"] = "EXPIRED"
                touch(ag)
