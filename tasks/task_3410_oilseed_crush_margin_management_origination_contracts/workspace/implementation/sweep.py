"""The three-phase deadline sweep (PRD section 3.9), run synchronously on
every logical-clock advance:
  1. force-price DEFERRED contracts whose pricing_deadline has passed;
  2. default lapsed sales contracts with the buyer claim/suspension cascade;
  3. expire ENTERED/CONFIRMED board crush positions past expiry_date.
"""
from decimal import Decimal

from calc import (BUYER_SUSPEND_CLAIM_THRESHOLD, DEFAULT_CLAIM_RATE,
                  pricing_event_accrual, provisional_estimate, round_int)
from quotes import asof
from store import db, get_clock, touch


def _force_price_deferred(clock):
    for c in sorted(db["contracts"].values(), key=lambda r: r["_seq"]):
        if c["contract_type"] != "DEFERRED" or c["pricing_status"] == "PRICED":
            continue
        deadline = c["pricing_deadline"]
        if not (deadline < clock):
            continue
        # Forced election uses the futures quote as-of the DEADLINE date.
        quote = asof("BEAN", c["futures_month"], at=deadline)
        if quote is None:
            continue  # left unpriced; retried on the next sweep
        remaining = Decimal(c["quantity_bushels"]) - Decimal(c["priced_bushels"])
        if remaining <= 0:
            continue
        # Final accrual leg runs last_accrual_date -> pricing_deadline.
        pricing_event_accrual(c, remaining, deadline)
        c["elections"].append({
            "bushels": remaining,
            "unit_price_cents": quote,
            "elected_at": deadline,
            "origin": "FORCED",
        })
        c["priced_bushels"] = Decimal(c["priced_bushels"]) + remaining
        c["priced_value_cents"] += round_int(remaining * quote)
        c["pricing_status"] = "PRICED"
        c["estimated_settlement_cents"] = provisional_estimate(c)
        touch(c)


def _default_sales(clock):
    candidates = [sc for sc in db["sales"].values()
                  if sc["status"] in ("OPEN", "DELIVERING")
                  and sc["delivery_window_end"] < clock
                  and sc["delivered_lbs"] < sc["quantity_lbs"]]
    # Deterministic order: delivery_window_end ASC, tie created_at ASC.
    candidates.sort(key=lambda sc: (sc["delivery_window_end"], sc["_seq"]))
    for sc in candidates:
        sc["status"] = "DEFAULTED"
        sc["claim_cents"] = round_int(
            Decimal(sc["quantity_lbs"] - sc["delivered_lbs"])
            * sc["price_cents_per_lb"] * DEFAULT_CLAIM_RATE)
        touch(sc)
        buyer = db["buyers"].get(sc["buyer_id"])
        if buyer is not None:
            buyer["open_claims_count"] += 1
            if (buyer["open_claims_count"] >= BUYER_SUSPEND_CLAIM_THRESHOLD
                    and buyer["status"] == "ACTIVE"):
                buyer["status"] = "SUSPENDED"
            touch(buyer)


def _expire_positions(clock):
    for p in sorted(db["hedges"].values(), key=lambda r: r["_seq"]):
        if p["status"] in ("ENTERED", "CONFIRMED") and p["expiry_date"] < clock:
            p["status"] = "EXPIRED"
            touch(p)


def run_sweep():
    clock = get_clock()
    _force_price_deferred(clock)
    _default_sales(clock)
    _expire_positions(clock)
