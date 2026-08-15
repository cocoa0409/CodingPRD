"""Calculation rules (scaffold Table 3): fare_quote, refund_amount, payload,
site_candidacy. All money is integer cents with round-half-up (PRD 2.6)."""
from decimal import Decimal

from db import db
from errors import raise_error, ERR_NO_SUITABLE_SITE
from util import rhu
from services.core import (
    season_tier_for, parse_date,  # noqa: F401  (re-exported convenience)
)

# fare_quote constants
BASE_FARE_PEAK_PER_PERSON_CENTS = 39900
BASE_FARE_REGULAR_PER_PERSON_CENTS = 29900
WEIGHT_SURCHARGE_THRESHOLD_LBS = 200
WEIGHT_SURCHARGE_PER_PERSON_CENTS = 2500
CHARTER_FLAT_SMALL_CENTS = 120000
CHARTER_FLAT_MEDIUM_CENTS = 180000
CHARTER_FLAT_LARGE_CENTS = 250000
CHARTER_PEAK_MULTIPLIER = Decimal("1.25")
PHOTO_ADDON_CENTS = {"NONE": 0, "STANDARD": 4900, "DELUXE": 9900}

# refund_amount constants
REFUND_PCT = {
    "WEATHER_CANCEL": 100,
    "OPERATOR_CANCEL": 100,
    "CUSTOMER_CANCEL_EARLY": 80,
    "CUSTOMER_CANCEL_LATE": 0,
}
GOODWILL_OPERATOR_PCT = 10
CUSTOMER_CANCEL_LATE_HOURS = 24


def fare_quote(flight, balloon, party_size: int, total_party_weight_lbs: int,
               photo_tier: str) -> int:
    """Dual-variant fare (PRD 3.4). The variants differ only in the weight
    source; the caller picks it: declared_weight_lbs (provisional, at booking)
    or the sum of actual Passenger weights (final, at CHECK_IN)."""
    season_tier = season_tier_for(flight["scheduled_date"])
    photo_add = PHOTO_ADDON_CENTS[photo_tier]
    if flight["kind"] == "SHARED":
        base = (BASE_FARE_PEAK_PER_PERSON_CENTS if season_tier == "PEAK"
                else BASE_FARE_REGULAR_PER_PERSON_CENTS)
        # avg weight > 200 (strictly) ⟺ total > 200 * party_size (exact)
        surcharge = (WEIGHT_SURCHARGE_PER_PERSON_CENTS
                     if total_party_weight_lbs > WEIGHT_SURCHARGE_THRESHOLD_LBS * party_size
                     else 0)
        return party_size * (base + surcharge) + photo_add
    # CHARTER: flat keyed on basket capacity; PEAK multiplies by 1.25 (half-up)
    cap = balloon["basket_capacity_passengers"]
    if cap <= 4:
        flat = CHARTER_FLAT_SMALL_CENTS
    elif cap <= 8:
        flat = CHARTER_FLAT_MEDIUM_CENTS
    else:
        flat = CHARTER_FLAT_LARGE_CENTS
    fare = rhu(Decimal(flat) * CHARTER_PEAK_MULTIPLIER) if season_tier == "PEAK" else flat
    return fare + photo_add


def refund_requested_amount(flight_kind: str, paid_cents: int, party_size: int,
                            reason: str):
    """Policy-computed Refund.requested_amount_cents (PRD 3.7).

    Returns None when the policy percentage is 0 (no Refund record created).
    SHARED non-100% policy rounds per passenger FIRST, then multiplies.
    """
    pct = REFUND_PCT[reason]
    if pct == 0:
        return None
    if flight_kind == "CHARTER":
        return rhu(Decimal(paid_cents) * Decimal(pct) / Decimal(100))
    if pct == 100:
        return paid_cents  # full-fare carve-out
    per_passenger_paid = rhu(Decimal(paid_cents) / Decimal(party_size))
    per_passenger_refund = rhu(Decimal(per_passenger_paid) * Decimal(pct) / Decimal(100))
    return per_passenger_refund * party_size


def goodwill_credit(paid_cents: int) -> int:
    """Operator goodwill: 10% of paid, rounded half-up (PRD 3.7)."""
    return rhu(Decimal(paid_cents) * Decimal(GOODWILL_OPERATOR_PCT) / Decimal(100))


# ---------------------------------------------------------------------------
# site_candidacy (PRD 3.3)
# ---------------------------------------------------------------------------

def latest_recorded_briefing(flight_id):
    """At most one RECORDED briefing exists per flight; return it (or None)."""
    rec = None
    for w in db["weather_briefings"].values():
        if w["flight_id"] == flight_id and w["status"] == "RECORDED":
            if rec is None or (w["observed_at"], w["_seq"]) > (rec["observed_at"], rec["_seq"]):
                rec = w
    return rec


def site_candidates(flight):
    """Ranked eligible launch sites for the flight (PRD 3.3).

    Eligibility: permission GRANTED, permission_expires_on >= scheduled_date,
    and (no RECORDED briefing OR the site tolerates the observed winds).
    Ranking: wind_margin_kts DESC (when a briefing exists), then
    permission_granted_at ASC, then created_at ASC.
    """
    briefing = latest_recorded_briefing(flight["id"])
    rows = []
    for s in db["launch_sites"].values():
        if s["permission_status"] != "GRANTED":
            continue
        if s["permission_expires_on"] < flight["scheduled_date"]:
            continue
        margin = None
        if briefing is not None:
            if (s["surface_wind_limit_kts"] < briefing["surface_wind_kts"]
                    or s["aloft_wind_limit_kts"] < briefing["aloft_wind_kts"]):
                continue
            margin = min(
                s["surface_wind_limit_kts"] - briefing["surface_wind_kts"],
                s["aloft_wind_limit_kts"] - briefing["aloft_wind_kts"],
            )
        rows.append({
            "site_id": s["id"],
            "wind_margin_kts": margin,
            "permission_granted_at": s["permission_granted_at"],
            "_created_at": s["created_at"],
            "_seq": s["_seq"],
        })
    if briefing is not None:
        rows.sort(key=lambda r: (-r["wind_margin_kts"],
                                 r["permission_granted_at"] or "",
                                 r["_created_at"], r["_seq"]))
    else:
        rows.sort(key=lambda r: (r["permission_granted_at"] or "",
                                 r["_created_at"], r["_seq"]))
    return rows


def select_site_or_raise(flight):
    rows = site_candidates(flight)
    if not rows:
        raise_error(ERR_NO_SUITABLE_SITE,
                    "no GRANTED, unexpired, wind-compatible launch site available")
    return rows[0]["site_id"]
