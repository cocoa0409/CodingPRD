"""Waitlist promotion, window sweep helpers, and logical-clock sweeps
(SCAFFOLD §1.3 window_slot_reservation; §3.10 clock sweep)."""
from datetime import datetime, time, timedelta, timezone

from db import DB, parse_iso
from helpers import touch
import calculations as calc


def promote_waitlist(window):
    """Promote eligible WAITLISTED visits on this window greedily.
    Ranking: created_at ASC, tie-break slot_need ASC (never id)."""
    candidates = [
        v
        for v in DB.delivery_visits.values()
        if v["delivery_window_id"] == window["id"] and v["status"] == "WAITLISTED"
    ]
    candidates.sort(key=lambda v: (v["created_at"], v["slot_need"], v.get("_seq", 0)))
    for v in candidates:
        if v["slot_need"] <= window["capacity_slots"] - window["reserved_slots"]:
            v["status"] = "SCHEDULED"
            window["reserved_slots"] += v["slot_need"]
            touch(v)
            touch(window)
            _maybe_order_fulfilling(v)


def _maybe_order_fulfilling(visit):
    """First SCHEDULED visit on an order moves CONFIRMED -> FULFILLING."""
    order = DB.orders.get(visit["order_id"])
    if order is None or order["order_status"] != "CONFIRMED":
        return
    scheduled = [
        x
        for x in DB.delivery_visits.values()
        if x["order_id"] == order["id"] and x["status"] == "SCHEDULED"
    ]
    if scheduled:
        order["order_status"] = "FULFILLING"
        touch(order)


def finalize_sleep_nights(clock_dt):
    """PROVISIONAL -> FINAL when clock >= night_date + 1 day at 12:00Z."""
    for night in list(DB.sleep_nights.values()):
        if night["status"] != "PROVISIONAL":
            continue
        d = datetime.strptime(night["night_date"], "%Y-%m-%d").date()
        cutoff = datetime.combine(d + timedelta(days=1), time(12, 0), tzinfo=timezone.utc)
        if clock_dt >= cutoff:
            night["final_score"] = calc.final_score(
                night["minutes_asleep"], night["restlessness_events"], night["avg_heart_rate"]
            )
            night["status"] = "FINAL"
            touch(night)
            device = DB.devices.get(night["device_id"])
            if device is not None:
                device["final_nights_count"] = device.get("final_nights_count", 0) + 1
                touch(device)


def _add_months(dt, months):
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    # clamp day to month length
    mdays = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
             31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    d = min(dt.day, mdays[m - 1])
    return dt.replace(year=y, month=m, day=d)


def sweep_deferred_interest(clock_dt):
    for plan in list(DB.financing_plans.values()):
        if plan["status"] != "ACTIVE":
            continue
        if plan["offer_type"] != "DEFERRED_INTEREST":
            continue
        if plan.get("retro_interest_posted"):
            continue
        if plan.get("activated_at") is None:
            continue
        activated = parse_iso(plan["activated_at"])
        promo_end = _add_months(activated, plan.get("promo_months", 12))
        if clock_dt >= promo_end and plan["balance_cents"] > 0:
            retro = calc.deferred_retro_interest(
                plan["principal_cents"], plan["apr_bps"], plan.get("promo_months", 12)
            )
            plan["balance_cents"] += retro
            plan["retro_interest_posted"] = True
            touch(plan)


def _installments_due(plan, clock_dt):
    """Installments due = whole months elapsed since activation, capped at term."""
    if plan.get("activated_at") is None:
        return 0
    activated = parse_iso(plan["activated_at"])
    if clock_dt < activated:
        return 0
    months = (clock_dt.year - activated.year) * 12 + (clock_dt.month - activated.month)
    # a full month elapses once we pass the same day-of-month
    if clock_dt.day < activated.day:
        months -= 1
    months = max(0, months)
    return min(months, plan["term_months"])


def sweep_delinquency(clock_dt):
    for plan in list(DB.financing_plans.values()):
        if plan["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        if plan.get("activated_at") is None:
            continue
        due = _installments_due(plan, clock_dt)
        paid = plan["paid_cents"] // plan["monthly_payment_cents"] if plan["monthly_payment_cents"] > 0 else 0
        missed = due - paid
        if missed >= 4 and plan["status"] != "DEFAULTED":
            plan["status"] = "DEFAULTED"
            touch(plan)
        elif missed >= 2 and plan["status"] == "ACTIVE":
            plan["status"] = "DELINQUENT"
            touch(plan)


def sweep_trial_close(clock_dt):
    for order in list(DB.orders.values()):
        if order["order_status"] != "DELIVERED":
            continue
        if order.get("trial_verified_at") is None:
            continue
        open_return = any(
            tr["order_id"] == order["id"] and tr["status"] == "INITIATED"
            for tr in DB.trial_returns.values()
        )
        if open_return:
            continue
        close_at = parse_iso(order["trial_verified_at"]) + timedelta(days=101)
        if clock_dt >= close_at:
            order["order_status"] = "CLOSED"
            touch(order)


def run_clock_sweeps(clock_dt):
    finalize_sleep_nights(clock_dt)
    sweep_deferred_interest(clock_dt)
    sweep_delinquency(clock_dt)
    sweep_trial_close(clock_dt)
