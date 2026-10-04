"""Business calculations: mileage overage, provider selection, SLA targets,
interclub line amounts, settlement sweep/assessment, prorations, commissions."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import DB, CLOCK, fmt_ts

COURTESY_BONUS_MILES = 3
HOOK_FEE_CENTS = 5500
PER_MILE_CENTS = 240
TERM_DAYS = 365
FEDERATION_ASSESSMENT_RATE = Decimal("0.045")
REFUND_WINDOW_DAYS = 30
GRACE_DAYS = 30
REINSTATEMENT_WINDOW_DAYS = 90
HOUSEHOLD_MAX_ACTIVE = 4
CHILD_MAX_AGE = 21

PARTS_PRICE_BOOK_CENTS = {
    "BAT-G24": 14500,
    "BAT-G35": 16900,
    "TIRE-SPO": 9900,
    "FUEL-CAN": 1200,
    "LOCK-KIT": 0,
}

TIER_FLAT_SCHEDULE = {
    "CLASSIC": {"TOW": 8900, "BATTERY": 6200, "LOCKOUT": 5500, "TIRE": 4800, "FUEL": 4100, "WINCH": 12400},
    "PLUS": {"TOW": 12900, "BATTERY": 6800, "LOCKOUT": 5500, "TIRE": 4800, "FUEL": 4100, "WINCH": 13900},
    "PREMIER": {"TOW": 21500, "BATTERY": 7400, "LOCKOUT": 5500, "TIRE": 4800, "FUEL": 4100, "WINCH": 16800},
}

NON_TERMINAL_CALL_STATES = {"REQUESTED", "DISPATCHED", "EN_ROUTE", "ON_SCENE"}
NON_TERMINAL_DISPATCH_STATES = {"ASSIGNED", "ACCEPTED", "EN_ROUTE", "ARRIVED"}

SERVICE_TYPES = {"TOW", "BATTERY", "LOCKOUT", "TIRE", "FUEL", "WINCH"}
TIER_CODES = {"CLASSIC", "PLUS", "PREMIER"}


def round_half_up_int(value):
    """Round a Decimal/int to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_by_code(code):
    for t in DB.tiers.values():
        if t["code"] == code:
            return t
    return None


def club_by_id(cid):
    return DB.clubs.get(cid)


# ---------------------------------------------------------------- mileage ---

def effective_miles(miles):
    return max(0, miles - COURTESY_BONUS_MILES)


def mileage_charge(miles, tier, benefit_eligible):
    """mileage_overage: provisional/final variants share the same formula;
    only the input miles differ. Returns integer cents."""
    rate = tier["overage_rate_cents_per_mile"]
    eff = effective_miles(miles)
    if benefit_eligible:
        overage = max(0, eff - tier["included_tow_miles"])
        return overage * rate
    # member-pay: no included-mile deduction
    return eff * rate


def parts_charge(parts_used):
    total = 0
    for p in parts_used or []:
        total += PARTS_PRICE_BOOK_CENTS.get(p["part_sku"], 0) * p["quantity"]
    return total


# ------------------------------------------------------- provider selection ---

def provider_open_window(provider, now):
    start = provider["shift_start_minute"]
    end = provider["shift_end_minute"]
    if start == end:
        return True  # 24x7
    minute_of_day = now.hour * 60 + now.minute
    return start <= minute_of_day < end


def provider_load(provider_id):
    count = 0
    for d in DB.dispatches.values():
        if d["provider_id"] == provider_id and d["status"] in NON_TERMINAL_DISPATCH_STATES:
            count += 1
    return count


def select_provider(call, exclude_provider_id=None):
    """dispatch_provider_selection. Returns provider row or None (empty pool)."""
    club = DB.clubs.get(call["servicing_club_id"])
    if club is None:
        return None
    now = CLOCK.now()
    candidates = []
    for p in DB.providers.values():
        if p["status"] != "ACTIVE":
            continue
        if p["servicing_club_id"] != call["servicing_club_id"]:
            continue
        if call["service_type"] not in p["capabilities"]:
            continue
        if p["home_base_state_code"] not in club["territory_state_codes"]:
            continue
        if not provider_open_window(p, now):
            continue
        if provider_load(p["id"]) >= p["max_concurrent_dispatches"]:
            continue
        if exclude_provider_id is not None and p["id"] == exclude_provider_id:
            continue
        candidates.append(p)
    if not candidates:
        return None

    def sort_key(p):
        kind_rank = 0 if p["provider_kind"] == "OWNED" else 1
        return (kind_rank, provider_load(p["id"]), p["created_at"])

    candidates.sort(key=sort_key)
    return candidates[0]


# ------------------------------------------------------------------- SLA ---

def effective_arrival_target_minutes(club, provider):
    product = Decimal(str(club["default_arrival_target_minutes"])) * Decimal(
        str(provider["sla_multiplier"])
    )
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ interclub ---

def interclub_gross(servicing_club, benefit_tier_code, service_type,
                    actual_tow_miles, parts_charge_cents):
    policy = servicing_club.get("billing_policy") or "SCHEDULE"
    if policy == "ACTUAL":
        eff = effective_miles(actual_tow_miles) if service_type == "TOW" else 0
        return HOOK_FEE_CENTS + eff * PER_MILE_CENTS + parts_charge_cents
    return TIER_FLAT_SCHEDULE[benefit_tier_code][service_type]


# ------------------------------------------------------------ settlement ---

def settle_fee(gross_amount_cents):
    """Per-line federation assessment fee: round_half_up(gross * 0.045)."""
    fee = Decimal(gross_amount_cents) * FEDERATION_ASSESSMENT_RATE
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -------------------------------------------------------------- proration ---

def elapsed_days(membership, now):
    term_start = membership["_term_start_dt"]
    delta = now - term_start
    seconds = delta.total_seconds()
    if seconds < 0:
        return 0
    return int(seconds // 86400)


def tier_change_proration(membership, old_tier, new_tier, now):
    """Returns (charge_cents, credit_cents): exactly one is > 0 depending on
    upgrade/downgrade direction; both computed from individually rounded factors."""
    rem = TERM_DAYS - elapsed_days(membership, now)
    prorated_new = round_half_up_int(
        Decimal(new_tier["annual_dues_cents"]) * Decimal(rem) / Decimal(TERM_DAYS)
    )
    prorated_old = round_half_up_int(
        Decimal(old_tier["annual_dues_cents"]) * Decimal(rem) / Decimal(TERM_DAYS)
    )
    return prorated_new, prorated_old


def household_proration_credit(membership, tier, now):
    rem = TERM_DAYS - elapsed_days(membership, now)
    return round_half_up_int(
        Decimal(tier["household_member_price_cents"]) * Decimal(rem) / Decimal(TERM_DAYS)
    )


def ancillary_commission_cents(price_cents, commission_bps):
    return round_half_up_int(
        Decimal(price_cents) * Decimal(commission_bps) / Decimal(10000)
    )


# ------------------------------------------------------------- sweeps ---

def membership_sweep(now):
    """Advance ACTIVE->GRACE and GRACE->LAPSED per the logical clock."""
    from services.events import append_event

    for m in DB.memberships.values():
        if m["status"] == "ACTIVE":
            if now > m["_term_end_dt"]:
                m["status"] = "GRACE"
                append_event(m["id"], "LAPSE", m["tier_code"], None,
                             "GRACE_ENTERED (30-day grace opens)")
                _touch_membership(m)
        if m["status"] == "GRACE":
            grace_deadline = m["_term_end_dt"] + timedelta(days=GRACE_DAYS)
            if now > grace_deadline:
                m["status"] = "LAPSED"
                m["_lapse_dt"] = now
                m["lapse_at"] = fmt_ts(now)
                append_event(m["id"], "LAPSE", m["tier_code"], None, "LAPSED")
                _touch_membership(m)
        # waiting period satisfied event
        if m.get("_tier_upgrade_effective_dt") is not None and not m.get("_waiting_satisfied_logged"):
            if now >= m["_tier_upgrade_effective_dt"]:
                append_event(m["id"], "WAITING_PERIOD_SATISFIED", m["tier_code"],
                             m["tier_code"], "")
                m["_waiting_satisfied_logged"] = True


def service_call_sweep(now):
    for c in DB.service_calls.values():
        if c["status"] == "REQUESTED":
            expiry = c["_created_dt"] + timedelta(hours=24)
            if now > expiry:
                c["status"] = "EXPIRED"
                _touch_call(c)


def _touch_membership(m):
    from db import touch
    touch(m)


def _touch_call(c):
    from db import touch
    touch(c)
