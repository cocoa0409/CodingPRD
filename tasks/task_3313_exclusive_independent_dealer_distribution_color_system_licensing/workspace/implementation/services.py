"""Derived computations, lazy sweeps, and cross-entity cascades."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import (
    EARTH_RADIUS_MILES, LICENSE_TERM_DAYS, CALIBRATION_PERIOD_DAYS,
    CLAIM_WINDOW_DAYS, ATTESTATION_FRESH_DAYS,
)


def round_half_up_int(x):
    """Round a Decimal-compatible value half-up to integer."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(x):
    """Round half-up to two decimal places; returned as float."""
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def haversine_miles(lat1, lon1, lat2, lon2):
    r = EARTH_RADIUS_MILES
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return r * c


# ---------------------------------------------------------------------------
# equipment sweeps / license cascades
# ---------------------------------------------------------------------------

def _sweep_equipment_unit(unit):
    """Lazy CALIBRATED -> CALIBRATION_OVERDUE on a single unit."""
    if unit["status"] == "CALIBRATED":
        due = db.parse_ts(unit.get("calibration_due_on"))
        if due is not None and db.now() > due:
            unit["status"] = "CALIBRATION_OVERDUE"
            db.touch(unit)
            _cascade_license_suspension(unit["dealer_id"], unit["colorant_system_id"])
            return True
    return False


def sweep_equipment(units):
    n = 0
    for u in units:
        if _sweep_equipment_unit(u):
            n += 1
    return n


def _sweep_license(lic):
    if lic["status"] == "ACTIVE":
        exp = db.parse_ts(lic.get("expires_on"))
        if exp is not None and db.now() >= exp:
            lic["status"] = "EXPIRED"
            db.touch(lic)
            return True
    return False


def sweep_licenses(licenses_iter):
    n = 0
    for lic in licenses_iter:
        if _sweep_license(lic):
            n += 1
    return n


def clear_stale_rematch_flags():
    """Clear rematch_pending on formulas whose covering EFFECTIVE change has
    no PENDING tasks."""
    n = 0
    for f in db.formulas.values():
        if not f.get("rematch_pending"):
            continue
        if not _formula_has_pending_task(f["id"]):
            f["rematch_pending"] = False
            db.touch(f)
            n += 1
    return n


def _formula_has_pending_task(formula_id):
    for t in db.rematch_tasks.values():
        if t["color_formula_id"] != formula_id or t["status"] != "PENDING":
            continue
        ch = db.formulation_changes.get(t["formulation_change_id"])
        if ch is not None and ch["status"] == "EFFECTIVE":
            return True
    return False


def _any_calibrated_unit(dealer_id, colorant_system_id):
    for u in db.equipment.values():
        if u["dealer_id"] == dealer_id and u["colorant_system_id"] == colorant_system_id:
            _sweep_equipment_unit(u)
            if u["status"] == "CALIBRATED":
                return True
    return False


def _cascade_license_suspension(dealer_id, colorant_system_id):
    """After a FAIL / overdue sweep / decommission: if no CALIBRATED unit
    remains for the system at this dealer, ACTIVE licenses -> SUSPENDED."""
    if _any_calibrated_unit(dealer_id, colorant_system_id):
        return
    for lic in db.licenses.values():
        if (
            lic["dealer_id"] == dealer_id
            and lic["colorant_system_id"] == colorant_system_id
            and lic["status"] == "ACTIVE"
        ):
            lic["status"] = "SUSPENDED"
            db.touch(lic)


def _cascade_license_activation(dealer_id, colorant_system_id):
    """After a PASS: PENDING -> ACTIVE (full fee) and SUSPENDED -> ACTIVE."""
    if not _any_calibrated_unit(dealer_id, colorant_system_id):
        return
    for lic in db.licenses.values():
        if lic["dealer_id"] != dealer_id:
            continue
        if lic["colorant_system_id"] != colorant_system_id:
            continue
        if lic["status"] == "PENDING":
            cs = db.colorant_systems.get(lic["colorant_system_id"])
            lic["status"] = "ACTIVE"
            lic["started_on"] = db.fmt_ts(db.now())
            lic["expires_on"] = db.fmt_ts(db.now() + timedelta(days=LICENSE_TERM_DAYS))
            lic["fee_basis"] = "FULL"
            lic["fee_charged_cents"] = cs["annual_license_fee_cents"] if cs else 0
            db.touch(lic)
        elif lic["status"] == "SUSPENDED":
            lic["status"] = "ACTIVE"
            db.touch(lic)


# ---------------------------------------------------------------------------
# dealer derived fields
# ---------------------------------------------------------------------------

def refresh_dealer_channel(dealer):
    """Recompute bigbox_share_pct and channel_posture from CONFIRMED events
    in the trailing-12-full-calendar-month window."""
    start, end = db.window_bounds()
    bigbox = 0
    independent = 0
    for ev in db.channel_events.values():
        if ev["dealer_id"] != dealer["id"] or ev["status"] != "CONFIRMED":
            continue
        ps = db.parse_ts(ev["period_start"])
        if ps is None or ps < start or ps > end:
            continue
        if ev["channel"] == "BIGBOX":
            bigbox += ev["sales_cents"]
        else:
            independent += ev["sales_cents"]
    total = bigbox + independent
    share = 0.0 if total == 0 else round_half_up_2dp(Decimal(100) * Decimal(bigbox) / Decimal(total))
    dealer["bigbox_share_pct"] = share
    region = db.regions.get(dealer["region_id"])
    threshold = region["exclusivity_block_threshold_pct"] if region else 100
    half = round_half_up_2dp(Decimal(str(threshold)) / Decimal(2))
    if Decimal(str(share)) >= Decimal(str(threshold)):
        dealer["channel_posture"] = "BLOCKED"
    elif Decimal(str(share)) > Decimal(str(half)):
        dealer["channel_posture"] = "OVERRIDE_REQUIRED"
    else:
        dealer["channel_posture"] = "INDEPENDENT_ONLY"


def refresh_annual_net_purchase(dealer):
    """Net invoiced DealerOrder value in the trailing 12 full calendar
    months. All orders that have reached INVOICED (i.e. INVOICED or PAID)
    contribute; the window membership is decided by created_at."""
    start, end = db.window_bounds()
    total = 0
    for o in db.orders.values():
        if o["dealer_id"] != dealer["id"] or o["status"] not in ("INVOICED", "PAID"):
            continue
        ca = db.parse_ts(o["created_at"])
        if ca is None or ca < start or ca > end:
            continue
        total += o["invoice_cents"]
    dealer["annual_net_purchase_cents"] = total


# ---------------------------------------------------------------------------
# contractor tier
# ---------------------------------------------------------------------------

TIER_THRESHOLDS = [
    (10000000, "PLATINUM"),
    (4000000, "GOLD"),
    (1000000, "SILVER"),
]

TIER_DISCOUNT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.05"),
    "GOLD": Decimal("0.10"),
    "PLATINUM": Decimal("0.15"),
}


def recompute_contractor_spend(account):
    """Recompute rolling_net_spend_cents and tier for the account."""
    start, end = db.window_bounds()
    spend = 0
    for p in db.purchases.values():
        if p["contractor_account_id"] != account["id"]:
            continue
        if p["status"] == "VOIDED":
            continue
        ca = db.parse_ts(p["created_at"])
        if ca is None or ca < start or ca > end:
            continue
        spend += p["invoice_cents"] - p["refund_cents"] - p["reward_points_redemption_cents"]
    account["rolling_net_spend_cents"] = spend
    tier = "STANDARD"
    for threshold, name in TIER_THRESHOLDS:
        if spend >= threshold:
            tier = name
            break
    account["tier"] = tier


# ---------------------------------------------------------------------------
# rematch helpers
# ---------------------------------------------------------------------------

def recompute_formula_rematch(formula):
    formula["rematch_pending"] = _formula_has_pending_task(formula["id"])


def dealer_has_pending_rematch_for_line(dealer_id, product_line_id):
    """True iff any ACTIVE formula of the line has rematch_pending under an
    EFFECTIVE change and this dealer's task is PENDING."""
    for f in db.formulas.values():
        if f["product_line_id"] != product_line_id or f["status"] != "ACTIVE":
            continue
        if not f.get("rematch_pending"):
            continue
        for t in db.rematch_tasks.values():
            if (
                t["color_formula_id"] == f["id"]
                and t["dealer_id"] == dealer_id
                and t["status"] == "PENDING"
            ):
                ch = db.formulation_changes.get(t["formulation_change_id"])
                if ch is not None and ch["status"] == "EFFECTIVE":
                    return True
    return False


def complete_task_bubble_up(task):
    """After a task becomes DONE: bubble the change to COMPLETED if it was
    the last PENDING task; recompute rematch_pending on affected formulas."""
    change = db.formulation_changes.get(task["formulation_change_id"])
    if change is None:
        return
    pending_left = any(
        t["formulation_change_id"] == change["id"] and t["status"] == "PENDING"
        for t in db.rematch_tasks.values()
    )
    if not pending_left and change["status"] == "EFFECTIVE":
        change["status"] = "COMPLETED"
        db.touch(change)
        # clear rematch_pending on every formula whose tasks are all DONE
        for f in db.formulas.values():
            if f["product_line_id"] == change["product_line_id"] and f.get("rematch_pending"):
                if not _formula_has_pending_task(f["id"]):
                    f["rematch_pending"] = False
                    db.touch(f)
    else:
        f = db.formulas.get(task["color_formula_id"])
        if f is not None:
            recompute_formula_rematch(f)


# ---------------------------------------------------------------------------
# dealer terminate cascade
# ---------------------------------------------------------------------------

def terminate_dealer_cascade(dealer):
    for lic in db.licenses.values():
        if lic["dealer_id"] == dealer["id"] and lic["status"] in ("PENDING", "ACTIVE", "EXPIRED", "SUSPENDED"):
            lic["status"] = "REVOKED"
            db.touch(lic)
    for u in db.equipment.values():
        if u["dealer_id"] == dealer["id"] and u["status"] != "DECOMMISSIONED":
            u["status"] = "DECOMMISSIONED"
            db.touch(u)
    for o in db.orders.values():
        if o["dealer_id"] == dealer["id"] and o["status"] in ("SUBMITTED", "APPROVED"):
            o["status"] = "CANCELLED"
            db.touch(o)
    for c in db.contractors.values():
        if c["dealer_id"] == dealer["id"] and c["status"] == "ACTIVE":
            c["status"] = "CLOSED"
            db.touch(c)
    dealer["coop_balance_cents"] = 0
    dealer["coop_pending_cents"] = 0
    dealer["inventory_minimum_met"] = False
    region = db.regions.get(dealer["region_id"])
    if region is not None:
        region["active_dealer_count"] = max(0, region.get("active_dealer_count", 0) - 1)
        db.touch(region)


# ---------------------------------------------------------------------------
# claim window
# ---------------------------------------------------------------------------

def claim_window_ok(activity_dt):
    now = db.now()
    if activity_dt > now:
        return False
    return (now - activity_dt) <= timedelta(days=CLAIM_WINDOW_DAYS)


def attestation_fresh(attested_on_dt):
    now = db.now()
    return (now - attested_on_dt) <= timedelta(days=ATTESTATION_FRESH_DAYS)
