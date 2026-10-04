"""Business-logic services: rates, tiers, suggestion, licensing fee, payout
computation, disputes, sweeps, cascades. All rounding uses round-half-up per
PRD §2.6; money is integer cents; Decimal is used for fractional
intermediates."""
import math
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import err

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
COMMISSION_RATE = {
    "STANDARD": Decimal("0.25"),
    "SILVER": Decimal("0.20"),
    "GOLD": Decimal("0.15"),
}
SILVER_THRESHOLD_CENTS = 500000
GOLD_THRESHOLD_CENTS = 2000000

FEE_BASE = {"BUSINESS": 50000, "ADVERTISING": 150000}
CHANNEL_FACTOR = {
    "SOCIAL": Decimal("1.0"),
    "WEB": Decimal("1.2"),
    "TV": Decimal("2.0"),
    "OOH": Decimal("1.5"),
}
TERRITORY_MULT = {"DOMESTIC": Decimal("1.0"), "GLOBAL": Decimal("1.5")}
CHANNELS = set(CHANNEL_FACTOR.keys())

MIN_PAYOUT_CENTS = 2500
ACCEPTANCE_WINDOW_HOURS = 48
AUTO_CONFIRM_HOURS = 72
IDENTITY_AUTO_REJECT_HOURS = 72
MAX_RERECORD_PER_ORDER = 2

PERSONAL_RATE_MIN = 100
PERSONAL_RATE_MAX = 10000000
BUSINESS_RATE_FLOOR = 4 * PERSONAL_RATE_MIN     # 400
ADVERTISING_RATE_FLOOR = 8 * PERSONAL_RATE_MIN  # 800
TURNAROUND_MIN = 1
TURNAROUND_MAX = 336

SCREENING_MARKER = "FLAGGED_POLICY_VIOLATION"


def round_half_up(d):
    """Round a Decimal to the nearest integer, half-up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Mutation helper — every mutation bumps version and refreshes updated_at
# ---------------------------------------------------------------------------
def touch(rec):
    rec["updated_at"] = db.iso(db.clock_now())
    rec["version"] += 1


def make_record(store, fields):
    now = db.iso(db.clock_now())
    rec = {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}
    rec.update(fields)
    store[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Rate bounds (§3.2)
# ---------------------------------------------------------------------------
def validate_rates(talent, personal, business, advertising):
    """Validate floors, ordering, and suggestion band. Raises ERR_RATE_OUT_OF_BOUNDS."""
    if personal is None or business is None or advertising is None:
        raise err("ERR_RATE_OUT_OF_BOUNDS",
                  "all three rates (personal, business, advertising) must be set")
    if personal < PERSONAL_RATE_MIN or personal > PERSONAL_RATE_MAX:
        raise err("ERR_RATE_OUT_OF_BOUNDS",
                  "personal_rate_cents must be between 100 and 10000000")
    if business < BUSINESS_RATE_FLOOR or business < personal:
        raise err("ERR_RATE_OUT_OF_BOUNDS",
                  "business_rate_cents must be >= 400 and >= personal_rate_cents")
    if advertising < ADVERTISING_RATE_FLOOR or advertising < business:
        raise err("ERR_RATE_OUT_OF_BOUNDS",
                  "advertising_rate_cents must be >= 800 and >= business_rate_cents")
    suggested = talent.get("suggested_personal_rate_cents")
    if suggested is not None:
        lower = math.floor(0.5 * suggested)
        upper = math.ceil(2.0 * suggested)
        if personal < lower or personal > upper:
            raise err("ERR_RATE_OUT_OF_BOUNDS",
                      "personal_rate_cents outside the suggestion acceptance band")


def check_turnaround(turnaround):
    if turnaround is None:
        raise err("ERR_INVALID_REQUEST", "turnaround_hours is required")
    if isinstance(turnaround, bool) or not isinstance(turnaround, int):
        raise err("ERR_INVALID_REQUEST", "turnaround_hours must be an integer")
    if turnaround < TURNAROUND_MIN or turnaround > TURNAROUND_MAX:
        raise err("ERR_INVALID_REQUEST", "turnaround_hours must be between 1 and 336")
    return turnaround


# ---------------------------------------------------------------------------
# Commission tier (§3.5)
# ---------------------------------------------------------------------------
def recompute_tier(talent):
    gmv = talent["trailing_gmv_cents"]
    if gmv >= GOLD_THRESHOLD_CENTS:
        tier = "GOLD"
    elif gmv >= SILVER_THRESHOLD_CENTS:
        tier = "SILVER"
    else:
        tier = "STANDARD"
    talent["commission_tier"] = tier
    return tier


def adjust_gmv(talent, delta_cents):
    """Kept for call-site compatibility: `trailing_gmv_cents` is derived.

    Per PRD §3.5, `trailing_gmv_cents` is defined as a sum over the talent's
    orders whose `CONFIRMED` transition occurred within the trailing 365-day
    window (a rolling window evaluated against the logical clock), minus the
    refund amounts of full/partial refund resolutions; platform-absorbed
    refunds do not subtract.  Because the window rolls, the value is
    re-derived from the order records on every change so that old
    confirmations age out as the logical clock advances.
    """
    refresh_gmv(talent)
    touch(talent)


def refresh_gmv(talent):
    """Re-derive `trailing_gmv_cents` from order records against the current
    logical clock and recompute the tier immediately (PRD §3.5)."""
    now = db.clock_now()
    window_start = db.days(now, -365)
    total = 0
    for o in db.orders.values():
        if o["talent_id"] != talent["id"]:
            continue
        confirmed_at = db.parse_iso(o.get("confirmed_at"))
        if confirmed_at is None:
            continue
        if not (window_start <= confirmed_at <= now):
            continue
        contribution = o["gross_amount_cents"]
        if o["status"] == "REFUNDED" and not o.get("platform_absorbed_cents"):
            # FULL_REFUND sets refund_amount_cents to the gross; PARTIAL_REFUND
            # sets it to the buyer's half.  Both subtract refund_amount_cents.
            contribution -= o["refund_amount_cents"]
        total += contribution
    talent["trailing_gmv_cents"] = total
    recompute_tier(talent)


def commission_for(tier, gross):
    rate = COMMISSION_RATE[tier]
    commission = round_half_up(Decimal(gross) * rate)
    return commission, gross - commission


# ---------------------------------------------------------------------------
# Confirm cascade (payout_computation, §3.5)
# ---------------------------------------------------------------------------
def run_confirm_cascade(order):
    """Runs on every DELIVERED->CONFIRMED (and NO_REFUND resolution) transition:
    freezes commission, creates VIDEO_EARNING line, credits pending balance,
    adds GMV, recomputes tier."""
    talent = db.talents[order["talent_id"]]
    commission, talent_net = commission_for(talent["commission_tier"],
                                            order["gross_amount_cents"])
    order["platform_commission_cents"] = commission
    order["talent_net_cents"] = talent_net
    # Internal bookkeeping for the rolling 365-day trailing window (PRD §3.5);
    # not part of the serialized order resource.
    order["confirmed_at"] = db.iso(db.clock_now())

    make_record(db.payout_lines, {
        "talent_id": talent["id"],
        "order_id": order["id"],
        "kind": "VIDEO_EARNING",
        "amount_cents": talent_net,
        "settlement_status": "UNSETTLED",
        "payout_id": None,
    })

    talent["pending_balance_cents"] += talent_net
    adjust_gmv(talent, order["gross_amount_cents"])  # also touches talent


def refund_to_wallet(order):
    """Full-gross wallet refund used by declines, expiries, cancellations,
    and suspension cascades."""
    buyer = db.buyers[order["buyer_id"]]
    order["refund_amount_cents"] = order["gross_amount_cents"]
    buyer["wallet_credit_cents"] += order["gross_amount_cents"]
    touch(buyer)


def close_open_rerecords(order_id):
    for rr in db.rerecord_requests.values():
        if rr["order_id"] == order_id and rr["status"] == "OPEN":
            rr["status"] = "CLOSED"
            touch(rr)


# ---------------------------------------------------------------------------
# Licensing fee (§3.7)
# ---------------------------------------------------------------------------
def compute_license_fee(license_type, channels, territory, starts_at, ends_at):
    delta = (ends_at - starts_at).total_seconds()
    days = math.ceil(delta / 86400)
    if days < 1:
        days = 1
    base = Decimal(FEE_BASE[license_type])
    channel_sum = sum(CHANNEL_FACTOR[c] for c in channels)
    territory_mult = TERRITORY_MULT[territory]
    if days > 90:
        effective = Decimal(90) + Decimal("0.9") * Decimal(days - 90)
    else:
        effective = Decimal(days)
    raw = base * channel_sum * territory_mult * effective
    return round_half_up(raw)


# ---------------------------------------------------------------------------
# Pricing suggestion (§3.2)
# ---------------------------------------------------------------------------
def compute_suggestion(talent):
    """Run talent_pricing_suggestion and persist suggested rate + seed time."""
    now = db.clock_now()
    window_start = db.days(now, -30)
    demand = 0
    utilization = 0
    for o in db.orders.values():
        if o["talent_id"] != talent["id"]:
            continue
        if o["status"] == "CONFIRMED":
            # trailing-30d window on the order's updated_at [now-30d, now)
            ud = db.parse_iso(o["updated_at"])
            if ud is not None and window_start <= ud < now:
                demand += 1
        if o["status"] in ("ACCEPTED", "RE_RECORD_REQUESTED"):
            utilization += 1
    demand_score = min(Decimal(demand) / Decimal(20), Decimal("1.0"))
    utilization_score = min(Decimal(utilization) / Decimal(5), Decimal("1.0"))
    score = Decimal("0.6") * demand_score + Decimal("0.4") * utilization_score
    raw = Decimal(talent["personal_rate_cents"]) * (Decimal(1) + Decimal("0.5") * score)
    suggested = round_half_up(raw / Decimal(500)) * 500
    talent["suggested_personal_rate_cents"] = suggested
    talent["suggestion_seed_at"] = db.iso(now)
    touch(talent)
    return talent


def suggestion_stale_24h(talent):
    from datetime import timedelta
    seed = talent.get("suggestion_seed_at")
    if seed is None:
        return True
    seed_dt = db.parse_iso(seed)
    if seed_dt is None:
        return True
    return (db.clock_now() - seed_dt) > timedelta(hours=24)
