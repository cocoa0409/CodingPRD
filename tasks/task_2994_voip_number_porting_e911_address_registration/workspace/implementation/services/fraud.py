"""Toll-fraud risk scoring and the international spend control (PRD 3.8)."""
from decimal import Decimal

import store
import util

COUNTRY_RISK = {"1": 0, "44": 5, "53": 25, "234": 30, "252": 35}
DEFAULT_COUNTRY_RISK = 20
RATE_TABLE = {"44": 12, "53": 60, "234": 95, "252": 140}
DEFAULT_RATE_CENTS = 75

FRAUD_THRESHOLD = 60
REALTIME_WINDOW_MINUTES = 60
VELOCITY_CAP = 40
REALTIME_VELOCITY_PER_ROW = 4
DAILY_VELOCITY_PER_ROW = 2
REALTIME_SPREAD_PER_EXTRA = 6
DAILY_SPREAD_PER_EXTRA = 4
NOMADIC_POINTS = 10
NEW_DEVICE_HOURS = 72
NEW_DEVICE_MULTIPLIER = Decimal("1.5")
SCORE_CAP = 100
FULL_BLOCK_AT_FRAUD_BLOCKS = 3

SURCHARGE_TIERS = ((5000, 12), (2000, 5), (0, 0))


def country_risk(country_code):
    return COUNTRY_RISK.get(country_code, DEFAULT_COUNTRY_RISK)


def rate_for(country_code):
    return RATE_TABLE.get(country_code, DEFAULT_RATE_CENTS)


def billable_minutes(seconds):
    return max(1, util.ceil_div(seconds, 60))


def _device_attempts(device_id):
    rows = [a for a in store.call_attempts.values() if a["device_id"] == device_id]
    return sorted(rows, key=lambda a: (a["created_at"], a["_seq"]))


def _score(rows, device, velocity_per_row, spread_per_extra, multiplier):
    velocity = min(velocity_per_row * len(rows), VELOCITY_CAP)
    geography = max([country_risk(r["destination_country_code"]) for r in rows], default=0)
    distinct = len({r["destination_country_code"] for r in rows})
    spread = spread_per_extra * (distinct - 1) if distinct > 0 else 0
    nomadism = NOMADIC_POINTS if (
        device["nomadic"] and device["registration_status"] != "REGISTERED") else 0
    raw = velocity + geography + spread + nomadism
    scored = util.round_half_up_decimal(Decimal(raw) * multiplier)
    return min(scored, SCORE_CAP)


def realtime_score(device, pending_country_code):
    """Score the device over the trailing 60 minutes, counting this attempt."""
    now = store.now()
    floor = now - util.minutes(REALTIME_WINDOW_MINUTES)
    rows = [a for a in _device_attempts(device["id"])
            if a["created_at"] > floor and a["created_at"] <= now
            and a["decision"] != "BLOCKED_E911"]
    rows = rows + [{"destination_country_code": pending_country_code}]
    younger = (now - device["created_at"]) < util.hours(NEW_DEVICE_HOURS)
    multiplier = NEW_DEVICE_MULTIPLIER if younger else Decimal("1")
    return _score(rows, device, REALTIME_VELOCITY_PER_ROW, REALTIME_SPREAD_PER_EXTRA,
                  multiplier)


def daily_review_score(device):
    """Score the device from midnight through the clock, discarding fraud blocks."""
    now = store.now()
    floor = util.day_start(now)
    rows = [a for a in _device_attempts(device["id"])
            if a["created_at"] >= floor and a["created_at"] <= now
            and a["decision"] not in ("BLOCKED_FRAUD", "BLOCKED_E911")]
    return _score(rows, device, DAILY_VELOCITY_PER_ROW, DAILY_SPREAD_PER_EXTRA,
                  Decimal("1"))


def surcharge_pct(day_subtotal_cents):
    for minimum, pct in SURCHARGE_TIERS:
        if day_subtotal_cents >= minimum:
            return pct
    return 0


def spend_projection(account, own_base_cents):
    """(day_subtotal_cents, surcharge_pct_applied, projected_day_total_cents)."""
    now = store.now()
    day_from = util.day_start(now)
    day_to = day_from + util.hours(24)
    device_ids = {d["id"] for d in store.devices.values()
                  if d["account_id"] == account["id"]}
    subtotal = own_base_cents
    for attempt in store.call_attempts.values():
        if attempt["device_id"] not in device_ids:
            continue
        if attempt["decision"] != "ALLOWED":
            continue
        if attempt["destination_country_code"] == "1":
            continue
        if not (day_from <= attempt["created_at"] < day_to):
            continue
        subtotal += attempt["estimated_base_cents"]
    pct = surcharge_pct(subtotal)
    surcharge = util.round_half_up(subtotal * pct, 100)
    return subtotal, pct, subtotal + surcharge
