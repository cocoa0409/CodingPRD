"""Calculation rules (scaffold §1.3 / PRD §3.4, §3.7, §3.8).

Constants are pinned verbatim:
  REFUND_DELTA_STEP_CENTS 100000, MAX_DELTA_STEPS 3, SCORE_CAP 100,
  ANNUAL_RATE_PCT 7.0, DAY_COUNT_BASIS 365, INTEREST_FREE_DAYS 45,
  FILING_DEADLINE tax_year 2026 -> 2027-04-15,
  VELOCITY_WINDOW_DAYS 7, VELOCITY_THRESHOLD 10, ROUTING_THRESHOLD 3,
  DEPENDENT_CREDIT_CENTS 200000, MAX_VERIFICATION_ATTEMPTS 3,
  CASE_DEADLINE_DAYS 30, EXPEDITED_CASE_DEADLINE_DAYS 7,
  EVIDENCE_WINDOW_DAYS 30, REPORT_WINDOW_DAYS 60.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from store import DB, parse_ts

getcontext().prec = 50

REFUND_DELTA_STEP_CENTS = 100000
MAX_DELTA_STEPS = 3
SCORE_CAP = 100
ANNUAL_RATE_PCT = Decimal("7.0")
DAY_COUNT_BASIS = 365
INTEREST_FREE_DAYS = 45
FILING_DEADLINES = {2026: date(2027, 4, 15)}
VELOCITY_WINDOW_DAYS = 7
VELOCITY_THRESHOLD = 10
ROUTING_THRESHOLD = 3
DEPENDENT_CREDIT_CENTS = 200000
MAX_VERIFICATION_ATTEMPTS = 3
CASE_DEADLINE_DAYS = 30
EXPEDITED_CASE_DEADLINE_DAYS = 7
EVIDENCE_WINDOW_DAYS = 30
REPORT_WINDOW_DAYS = 60

DAILY_RATE = ANNUAL_RATE_PCT / Decimal(100) / Decimal(DAY_COUNT_BASIS)

REQUIRED_DOCS = {
    "ONLINE": ["PHOTO_ID", "PRIOR_YEAR_RETURN"],
    "PHONE": ["PHOTO_ID", "SSA_CARD"],
    "IN_PERSON": ["PHOTO_ID", "UTILITY_BILL"],
}


def active_config():
    for cfg in DB.configs.values():
        if cfg["status"] == "ACTIVE":
            return cfg
    return None


def compute_risk_score(ret, taxpayer, cfg):
    """filter_risk_score: weighted signals, clamp to [0, 100].

    Returns (score, reason_codes) with codes in the canonical order
    REFUND_DELTA, BANK_PRODUCT, VICTIM_FLAGGED, INTERACTION.
    """
    delta = abs(ret["claimed_refund_cents"] - taxpayer["prior_year_refund_cents"])
    delta_steps = min(MAX_DELTA_STEPS, delta // REFUND_DELTA_STEP_CENTS)
    victim = 1 if taxpayer["status"] == "VICTIM_FLAGGED" else 0
    bank_rt = 1 if ret["bank_product"] == "REFUND_TRANSFER" else 0
    prep_flagged = 0
    if ret["preparer_id"] is not None:
        for a in DB.alerts.values():
            if a["preparer_id"] == ret["preparer_id"] and a["status"] == "FLAGGED":
                prep_flagged = 1
                break
    dep_contested = 0
    for c in DB.claims.values():
        if c["return_id"] == ret["id"] and c["status"] == "CONTESTED":
            dep_contested = 1
            break
    raw = (
        cfg["w_victim_flagged"] * victim
        + cfg["w_refund_delta"] * delta_steps
        + cfg["w_bank_product"] * bank_rt
        + cfg["w_preparer_flagged"] * prep_flagged
        + cfg["w_dependent_conflict"] * dep_contested
    )
    if victim == 1 and bank_rt == 1:
        raw += cfg["interaction_bonus"]
    score = min(SCORE_CAP, max(0, raw))
    reasons = []
    if delta_steps > 0:
        reasons.append("REFUND_DELTA")
    if bank_rt:
        reasons.append("BANK_PRODUCT")
    if victim:
        reasons.append("VICTIM_FLAGGED")
    if victim and bank_rt:
        reasons.append("INTERACTION")
    return score, reasons


def anchor_date(ret):
    """Later of the return's filing date and the filing deadline for its year."""
    received = parse_ts(ret["received_at"]).date()
    deadline = FILING_DEADLINES.get(ret["tax_year"])
    if deadline is None:
        deadline = date(ret["tax_year"] + 1, 4, 15)
    return max(received, deadline)


def _round_cents(amount):
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def provisional_interest(ret, base_cents, scheduled_at_iso):
    """refund_interest variant PROVISIONAL: simple accrual, single round."""
    days_late = (parse_ts(scheduled_at_iso).date() - anchor_date(ret)).days - INTEREST_FREE_DAYS
    if days_late <= 0:
        return 0
    return _round_cents(Decimal(base_cents) * DAILY_RATE * days_late)


def _component_interest(component_cents, days):
    if days <= 0 or component_cents == 0:
        return 0
    growth = (Decimal(1) + DAILY_RATE) ** days - Decimal(1)
    return _round_cents(Decimal(component_cents) * growth)


def final_interest(ret, disb, released_dt):
    """refund_interest variant FINAL: daily compounding, round per component,
    then sum the rounded components (sum-then-round is explicitly rejected)."""
    anchor = anchor_date(ret)
    rel = released_dt.date()
    days_0 = max(0, (rel - anchor).days - INTEREST_FREE_DAYS)
    total = _component_interest(disb["_sched_base"], days_0)
    free_end = anchor + timedelta(days=INTEREST_FREE_DAYS)
    for ev in disb["_adj_events"]:
        d_i = date.fromisoformat(ev["date"])
        start = max(free_end, d_i)
        days_i = max(0, (rel - start).days)
        total += _component_interest(ev["delta"], days_i)
    return total


def in_velocity_window(received_at_iso, now_dt):
    received = parse_ts(received_at_iso)
    return now_dt - timedelta(days=VELOCITY_WINDOW_DAYS) <= received <= now_dt
