"""Business logic: calculations (SCAFFOLD §1.3) and cascading side effects."""
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal

from db import store, new_id, stamp, touch
from util import round2, round3, round_cents, D0

# Calculation constants (SCAFFOLD §1.3)
CURTAILMENT_FACTOR_CRITICAL = Decimal("0.80")
FEE_CENTS_PER_AF = Decimal("3000")
FEE_MULT = {"NORMAL": Decimal("1.00"), "WATCH": Decimal("1.10"), "CRITICAL": Decimal("1.25")}
TIER1_LIMIT_FRACTION = Decimal("0.10")
TIER1_RATE_CENTS = Decimal("10000")
TIER2_RATE_CENTS = Decimal("25000")
LATE_REPORT_FEE_CENTS = 10000
UNMETERED_PUMPING_FEE_CENTS = 50000
MONITORING_RECENCY_DAYS = 90
WATCH_BREACH_PCT = Decimal("25")
CRITICAL_BREACH_PCT = Decimal("50")
WATCH_MEAN_FT = Decimal("100.00")
CRITICAL_MEAN_FT = Decimal("120.00")
CARRYOVER_CAP_FRACTION = Decimal("0.25")
MONTHLY_TRANSFER_CAP_AF = Decimal("5000")
TRANSFER_EXPIRY = timedelta(hours=72)
APPEAL_WINDOW = timedelta(days=30)


# ---------------------------------------------------------------------------
# Official basin condition selector (PRD §2.7)
# ---------------------------------------------------------------------------

def official_selector():
    """Latest PUBLISHED snapshot by computed_at DESC, tie-break created_at DESC
    (then arrival order). Returns the snapshot dict or None."""
    pubs = [s for s in store.snapshots.values() if s["status"] == "PUBLISHED"]
    if not pubs:
        return None
    return max(pubs, key=lambda s: (s["computed_at"], s["created_at"], s["_seq"]))


def official_condition():
    sel = official_selector()
    return sel["condition"] if sel is not None else "NORMAL"


# ---------------------------------------------------------------------------
# Allocation / availability / overdraft (PRD §3.8, SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def effective_allocation(account):
    factor = CURTAILMENT_FACTOR_CRITICAL if official_condition() == "CRITICAL" else Decimal("1.00")
    return round3(account["base_allocation_af"] * factor)


def available_water(account, variant):
    """variant: 'forward_looking' (proposal gate) or 'settled' (settle/overdraft/carryover)."""
    avail = (effective_allocation(account)
             + account["credit_balance_af"]
             - account["extracted_af_ytd"]
             - account["transfer_out_af_ytd"]
             - account["transfer_reserved_af"])
    if variant == "forward_looking":
        avail -= account["pending_extraction_af"]
    return round3(avail)


def compute_overdraft_af(account):
    od = (account["extracted_af_ytd"]
          - effective_allocation(account)
          - account["credit_balance_af"]
          + account["transfer_out_af_ytd"])
    if od < 0:
        od = D0
    return round3(od)


def overdraft_penalty_cents(account, overdraft_af):
    tier1_limit = round3(TIER1_LIMIT_FRACTION * account["base_allocation_af"])
    tier1_af = min(overdraft_af, tier1_limit)
    tier2_af = overdraft_af - tier1_limit
    if tier2_af < 0:
        tier2_af = D0
    mult = FEE_MULT[official_condition()]
    return round_cents((tier1_af * TIER1_RATE_CENTS + tier2_af * TIER2_RATE_CENTS) * mult)


def report_fee_cents(reported_af):
    mult = FEE_MULT[official_condition()]
    return round_cents(reported_af * FEE_CENTS_PER_AF * mult)


# ---------------------------------------------------------------------------
# Extraction-report late flag (SCAFFOLD §1.3 report_late_flag)
# ---------------------------------------------------------------------------

def compute_late_flag(water_year, month):
    if month == 12:
        boundary = datetime(water_year + 1, 1, 16, tzinfo=timezone.utc)
    else:
        boundary = datetime(water_year, month + 1, 16, tzinfo=timezone.utc)
    return store.clock >= boundary


# ---------------------------------------------------------------------------
# Basin condition evaluation (SCAFFOLD §1.3 basin_condition_evaluation)
# ---------------------------------------------------------------------------

def evaluate_basin():
    now = store.clock
    cutoff = now - timedelta(days=MONITORING_RECENCY_DAYS)
    latest = []  # (well, reading) pairs, one per eligible well
    for w in store.wells.values():
        if w["well_type"] != "MONITORING" or w["status"] != "ACTIVE":
            continue
        rs = [r for r in store.readings.values() if r["well_id"] == w["id"]]
        if not rs:
            continue
        newest = max(rs, key=lambda r: (r["measured_at"], r["created_at"], r["_seq"]))
        if newest["measured_at"] > now or newest["measured_at"] < cutoff:
            continue
        latest.append((w, newest))
    eligible = len(latest)
    if eligible == 0:
        return {
            "eligible_well_count": 0,
            "breached_well_count": 0,
            "breach_pct": None,
            "rolling_mean_depth_ft": None,
            "condition": "NORMAL",
            "mean_condition": None,
        }
    breached = sum(1 for (w, r) in latest if r["depth_to_water_ft"] > w["minimum_threshold_ft"])
    breach_pct = round2(Decimal(100 * breached) / Decimal(eligible))
    if breach_pct >= CRITICAL_BREACH_PCT:
        condition = "CRITICAL"
    elif breach_pct >= WATCH_BREACH_PCT:
        condition = "WATCH"
    else:
        condition = "NORMAL"
    mean = round2(sum(r["depth_to_water_ft"] for _, r in latest) / Decimal(eligible))
    if mean >= CRITICAL_MEAN_FT:
        mean_condition = "CRITICAL"
    elif mean >= WATCH_MEAN_FT:
        mean_condition = "WATCH"
    else:
        mean_condition = "NORMAL"
    return {
        "eligible_well_count": eligible,
        "breached_well_count": breached,
        "breach_pct": breach_pct,
        "rolling_mean_depth_ft": mean,
        "condition": condition,
        "mean_condition": mean_condition,
    }


# ---------------------------------------------------------------------------
# Transfer window helpers (half-open [start, end))
# ---------------------------------------------------------------------------

def months_in_window(start, end):
    """Calendar months intersected by the half-open window [start, end)."""
    last = end - timedelta(days=1)
    cur = date(start.year, start.month, 1)
    while cur <= last:
        yield (cur.year, cur.month)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)


def _month_span(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def window_intersects_month(start, end, year, month):
    ms, me = _month_span(year, month)
    return start < me and end > ms


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def expire_order(t):
    """PROPOSED -> EXPIRED with seller reservation release."""
    t["status"] = "EXPIRED"
    t["version"] += 1
    touch(t)
    seller = store.accounts[t["seller_account_id"]]
    seller["transfer_reserved_af"] = round3(seller["transfer_reserved_af"] - t["quantity_af"])
    seller["version"] += 1
    touch(seller)


def sweep_expired_transfers(now):
    """Clock sweep: PROPOSED orders whose expires_at is strictly before now."""
    for t in list(store.transfers.values()):
        if t["status"] == "PROPOSED" and t["expires_at"] < now:
            expire_order(t)


def cascade_close_account(account):
    """Account-close cascade: wells decommission; outbound open transfers end."""
    for w in store.wells.values():
        if w["account_id"] == account["id"] and w["status"] != "DECOMMISSIONED":
            w["status"] = "DECOMMISSIONED"
            w["version"] += 1
            touch(w)
    for t in store.transfers.values():
        if t["seller_account_id"] == account["id"] and t["status"] in ("PROPOSED", "ACCEPTED"):
            t["status"] = "CANCELLED" if t["status"] == "PROPOSED" else "REJECTED"
            t["version"] += 1
            touch(t)
            account["transfer_reserved_af"] = round3(
                account["transfer_reserved_af"] - t["quantity_af"])


def new_assessment(account, reason, water_year, overdraft_af, amount_cents, assessed_by):
    a = {
        "id": new_id(),
        "account_id": account["id"],
        "reason": reason,
        "water_year": water_year,
        "overdraft_af": overdraft_af,
        "amount_cents": amount_cents,
        "reduced_amount_cents": None,
        "paid_amount_cents": None,
        "assessed_by": assessed_by,
        "decided_by": None,
        "status": "ASSESSED",
    }
    stamp(a)
    store.assessments[a["id"]] = a
    return a
