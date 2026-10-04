"""Calculation engine per PRD §3 formulas (pinned rounding and order)."""
from decimal import Decimal, ROUND_HALF_UP
from math import floor

from db import DB
from util import filter_safe, filter_standard, iso_ms, touch

RATINGS = ("ALL", "NINE_PLUS", "THIRTEEN_PLUS", "SEVENTEEN_PLUS")
AGE_BANDS = ("CHILD", "TEEN", "ADULT")

ENGAGEMENT_RATES = {
    "ALL": 2,
    "NINE_PLUS": 3,
    "THIRTEEN_PLUS": 4,
    "SEVENTEEN_PLUS": 5,
}


def _half_up(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- Age / clock (PRD §3.1, age_band_compute) ---

def compute_age_years(dob, at_dt):
    """Whole-year count between dob (date) and at_dt, avg year 365.2425."""
    dob_dt = dob if hasattr(dob, "hour") else None
    if dob_dt is None:
        from datetime import datetime, timezone

        dob_dt = datetime(dob.year, dob.month, dob.day, tzinfo=timezone.utc)
    delta_days = (at_dt - dob_dt).total_seconds() / 86400.0
    return int(floor(delta_days / 365.2425))


def age_band_for_years(age_years):
    if age_years < 13:
        return "CHILD"
    if age_years < 18:
        return "TEEN"
    return "ADULT"


def recompute_user_temporal(user):
    """Recompute account_age_days and age_band (and cascade chat_filter_level)."""
    created = user.get("_created_dt")
    if created is not None:
        delta_days = (DB.current_utc - created).total_seconds() / 86400.0
        user["account_age_days"] = max(0, int(floor(delta_days)))
    new_band = age_band_for_years(compute_age_years(user["_dob"], DB.current_utc))
    if user.get("age_band") != new_band:
        user["age_band"] = new_band
        recompute_chat_filter(user)
        touch(user)


def get_pc(child_id):
    for pc in DB.parental_controls.values():
        if pc["child_user_id"] == child_id:
            return pc
    return None


def recompute_chat_filter(user):
    band = user.get("age_band")
    pc = get_pc(user["id"])
    if band == "CHILD" or (pc is not None and pc.get("chat_mode") == "RESTRICTED"):
        user["chat_filter_level"] = "SAFE"
    elif band == "TEEN":
        user["chat_filter_level"] = "STANDARD"
    else:
        user["chat_filter_level"] = "ADULT"


# --- Experience view (PRD §3.10: descriptions filtered for CHILD viewers) ---

def view_experience(exp, viewer):
    out = {k: v for k, v in exp.items() if not k.startswith("_")}
    if viewer is not None:
        recompute_user_temporal(viewer)
        if viewer.get("age_band") == "CHILD":
            out["description"] = filter_safe(out.get("description") or "")
    return out


# --- User view (PRD §3.2: is_devex_eligible recomputed on read) ---

def latest_iv(user_id):
    ivs = [v for v in DB.identity_verifications.values() if v["user_id"] == user_id]
    if not ivs:
        return None
    ivs.sort(key=lambda v: (v.get("created_at", ""), v["id"]))
    return ivs[-1]


def latest_td(user_id):
    tds = [t for t in DB.tax_documents.values() if t["user_id"] == user_id]
    if not tds:
        return None
    tds.sort(key=lambda t: (t.get("created_at", ""), t["id"]))
    return tds[-1]


def check_iv_expiry(user_id):
    """PENDING/VERIFIED verifications expire once current_utc > expiry_date."""
    for iv in DB.identity_verifications.values():
        if iv["user_id"] != user_id:
            continue
        exp = iv.get("_expiry_dt")
        if exp is not None and iv["status"] in ("PENDING", "VERIFIED"):
            if DB.current_utc > exp:
                iv["status"] = "EXPIRED"
                if iv.get("reviewed_at") is None:
                    iv["reviewed_at"] = iso_ms(DB.current_utc)
                touch(iv)


def devex_eligible(user):
    if user.get("status") != "ACTIVE":
        return False
    recompute_user_temporal(user)
    if user.get("age_band") != "ADULT":
        return False
    check_iv_expiry(user["id"])
    iv = latest_iv(user["id"])
    if iv is None or iv["status"] != "VERIFIED":
        return False
    td = latest_td(user["id"])
    if td is None or td["status"] != "ACCEPTED":
        return False
    if user.get("account_age_days", 0) < 30:
        return False
    if user.get("earned_robux_lifetime", 0) < 30000:
        return False
    return True


def view_user(user):
    recompute_user_temporal(user)
    out = {k: v for k, v in user.items() if not k.startswith("_")}
    out["is_devex_eligible"] = devex_eligible(user)
    return out


# --- Age rating access (PRD §3.9) ---

def rating_required_ok(viewer, rating):
    """True iff viewer may access content at the given rating (band comparison)."""
    age_years = compute_age_years(viewer["_dob"], DB.current_utc)
    if rating == "ALL":
        return True
    if rating == "NINE_PLUS":
        return age_years >= 9
    if rating == "THIRTEEN_PLUS":
        return viewer["age_band"] in ("TEEN", "ADULT")
    if rating == "SEVENTEEN_PLUS":
        return viewer["age_band"] == "ADULT"
    return False


def allowed_for_child(child, rating):
    """Age-band access narrowed (never widened) by parental whitelist."""
    if not rating_required_ok(child, rating):
        return False
    pc = get_pc(child["id"])
    if pc is not None:
        allowed = pc.get("allowed_age_ratings") or []
        if allowed and rating not in allowed:
            return False
    return True


# --- Currency exchange (PRD §3.3, currency_exchange_tiered) ---

def tiered_exchange_robux(fiat_cents):
    # Tiers are unit-count marginal: tier 1 covers cents 0-999 (999 units at 0.80),
    # tier 2 cents 1000-4999 (4000 units at 0.90), tier 3 cents 5000-19999
    # (15000 units at 1.00), tier 4 cents >= 20000 (at 1.10).
    tiers = [(999, Decimal("0.80")), (4999, Decimal("0.90")), (19999, Decimal("1.00"))]
    remaining = int(fiat_cents)
    lower = 0
    total = Decimal("0")
    for upper, rate in tiers:
        if remaining <= 0:
            break
        take = min(remaining, upper - lower)
        total += Decimal(take) * rate
        remaining -= take
        lower = upper
    if remaining > 0:
        total += Decimal(remaining) * Decimal("1.10")
    return _half_up(total)


def apply_promo(tiered_robux):
    return _half_up(Decimal(tiered_robux) * Decimal("1.10"))


# --- Marketplace split (PRD §3.7, marketplace_split) ---

def split_non_limited(price):
    fee = _half_up(Decimal(price) * Decimal("0.30"))
    return fee, price - fee


def split_resale(price, royalty_pct):
    fee = _half_up(Decimal(price) * Decimal("0.30"))
    gross_seller = price - fee
    royalty = _half_up(Decimal(gross_seller) * Decimal(royalty_pct) / Decimal(100))
    return fee, gross_seller - royalty, royalty


# --- DevEx ladder & withholding (PRD §3.12) ---

def devex_ladder_cents(robux):
    brackets = [(30000, Decimal("0.35")), (100000, Decimal("0.38")), (1000000, Decimal("0.40"))]
    remaining = int(robux)
    lower = 0
    total = Decimal("0")
    for upper, rate in brackets:
        if remaining <= 0:
            break
        take = min(remaining, upper - lower)
        total += Decimal(take) * rate
        remaining -= take
        lower = upper
    if remaining > 0:
        total += Decimal(remaining) * Decimal("0.42")
    return _half_up(total)


def withholding_cents(usd_payout_cents, form_type):
    total = Decimal("0")
    if form_type == "W9":
        brackets = [(10000, Decimal("0")), (50000, Decimal("0.10")), (200000, Decimal("0.24"))]
        remaining = int(usd_payout_cents)
        lower = 0
        for upper, rate in brackets:
            if remaining <= 0:
                break
            take = min(remaining, upper - lower)
            total += Decimal(take) * rate
            remaining -= take
            lower = upper
        if remaining > 0:
            total += Decimal(remaining) * Decimal("0.30")
    else:  # W8BEN / W8BENE: flat 30%
        total = Decimal(int(usd_payout_cents)) * Decimal("0.30")
    return _half_up(total)


# --- Engagement payout (PRD §3.8) ---

def engagement_payout_robux(minutes_engaged, rating):
    rate = ENGAGEMENT_RATES.get(rating or "ALL", 2)
    return (int(minutes_engaged) // 60) * rate


# --- Resale floor (PRD §3.6) ---

def resale_floor(price_robux):
    return floor(price_robux * 0.5)


# --- Chat filtering (PRD §3.10) ---

def apply_chat_filter(text, level):
    if level == "SAFE":
        return filter_safe(text)
    if level == "STANDARD":
        return filter_standard(text)
    return text
