"""Business calculations per SCAFFOLD section 1.3 and PRD section 3."""

import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from services_common import now_dt


def round_half_up_cents(value):
    """value is a Decimal or float-ish; round half up to integer cents."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quarter_of(date_dt):
    """Return quarter string like '2026-Q3' for a date."""
    q = (date_dt.month - 1) // 3 + 1
    return f"{date_dt.year}-Q{q}"


def quarter_bounds(period):
    """Given '2026-Q3' return (start_date, end_date) datetimes (00:00:00Z start, end of last day)."""
    year, qpart = period.split("-Q")
    year = int(year)
    q = int(qpart)
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    last_day = calendar.monthrange(year, end_month)[1]
    start = datetime(year, start_month, 1, tzinfo=timezone.utc)
    end = datetime(year, end_month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def annual_bounds(period):
    year = int(period)
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def period_bounds(period):
    if "-Q" in period:
        return quarter_bounds(period)
    return annual_bounds(period)


def quarter_end_date(period):
    """End-of-quarter date (date precision) for a quarterly period string."""
    start, end = quarter_bounds(period)
    return end.date()


def deposit_due_date(frequency, pay_date):
    """Compute statutory due_date per deposit_due_date. pay_date is aware datetime (00:00:00Z).
    Returns datetime normalized to 23:59:59Z on the due date."""
    p = pay_date.date()
    if frequency == "SEMIWEEKLY":
        wd = p.weekday()  # Mon=0 .. Sun=6
        if wd in (2, 3, 4):  # Wed/Thu/Fri -> next Wednesday strictly after P
            days = (2 - wd) % 7
            if days == 0:
                days = 7
            due = p + timedelta(days=days)
        else:  # Sat/Sun/Mon/Tue -> next Friday strictly after P
            days = (4 - wd) % 7
            if days == 0:
                days = 7
            due = p + timedelta(days=days)
    elif frequency == "MONTHLY":
        if p.month == 12:
            due = datetime(p.year + 1, 1, 15, tzinfo=timezone.utc).date()
        else:
            due = datetime(p.year, p.month + 1, 15, tzinfo=timezone.utc).date()
    elif frequency == "QUARTERLY":
        q = (p.month - 1) // 3 + 1
        if q == 1:
            due = datetime(p.year, 4, 30, tzinfo=timezone.utc).date()
        elif q == 2:
            due = datetime(p.year, 7, 31, tzinfo=timezone.utc).date()
        elif q == 3:
            due = datetime(p.year, 10, 31, tzinfo=timezone.utc).date()
        else:
            due = datetime(p.year + 1, 1, 31, tzinfo=timezone.utc).date()
    else:
        due = p
    return datetime(due.year, due.month, due.day, 23, 59, 59, tzinfo=timezone.utc)


def late_penalty(amount_cents, late_days, jurisdiction):
    """late_deposit_penalty: tiered by late_days, round half up."""
    if late_days <= 0:
        return 0
    if late_days <= 5:
        rate = jurisdiction["penalty_tier1_rate"]
    elif late_days <= 15:
        rate = jurisdiction["penalty_tier2_rate"]
    else:
        rate = jurisdiction["penalty_tier3_rate"]
    return round_half_up_cents(Decimal(amount_cents) * Decimal(str(rate)))


def compute_late_fields(deposit, jurisdiction):
    """Compute late_days and penalty_exposure_cents for a deposit."""
    confirmed_at = deposit.get("confirmed_at")
    if not confirmed_at:
        return 0, 0
    from services_common import parse_datetime
    due = parse_datetime(deposit["due_date"])
    conf = parse_datetime(confirmed_at)
    days = (conf.date() - due.date()).days
    late_days = max(0, days)
    return late_days, late_penalty(deposit["amount_cents"], late_days, jurisdiction)


def bureau_books_liability(client_id, period):
    """Sum total_tax_cents of client's PayrollRuns with period_end inside the period and
    status in {SUBMITTED, IMPOUNDED, SETTLED}."""
    from services_common import parse_datetime
    start, end = period_bounds(period)
    total = 0
    for run in store.payroll_runs.values():
        if run["client_id"] != client_id:
            continue
        if run["status"] not in ("SUBMITTED", "IMPOUNDED", "SETTLED"):
            continue
        pe = parse_datetime(run["period_end"])
        if pe is None:
            continue
        if start <= pe <= end:
            total += run["total_tax_cents"]
    return total


def agency_confirmed_liability(client_id, jurisdiction_id, period):
    """Sum amount_cents of client's CONFIRMED TaxDeposits for the jurisdiction whose quarter
    falls inside the return period."""
    start, end = period_bounds(period)
    total = 0
    for dep in store.deposits.values():
        if dep["client_id"] != client_id:
            continue
        if dep["jurisdiction_id"] != jurisdiction_id:
            continue
        if dep["status"] != "CONFIRMED":
            continue
        q = dep["quarter"]
        try:
            qs, qe = quarter_bounds(q)
        except Exception:
            continue
        # quarter falls inside the return period if its start is within [start, end]
        if start <= qs <= end:
            total += dep["amount_cents"]
    return total


def shortfall_penalty(ret, jurisdiction):
    """shortfall_penalty for QUARTERLY returns at file time. ret must already have
    expected_liability_cents computed (bureau-books variant)."""
    period = ret["period"]
    if "-Q" not in period:
        return 0
    confirmed_total = 0
    for dep in store.deposits.values():
        if dep["client_id"] == ret["client_id"] \
                and dep["jurisdiction_id"] == ret["jurisdiction_id"] \
                and dep["quarter"] == period \
                and dep["status"] == "CONFIRMED":
            confirmed_total += dep["amount_cents"]
    if confirmed_total >= jurisdiction["underpayment_threshold_cents"]:
        return 0
    shortfall = ret["expected_liability_cents"] - confirmed_total
    if shortfall <= 0:
        return 0
    from services_common import parse_datetime
    qend = quarter_end_date(period)
    filed = parse_datetime(ret["filed_at"]).date()
    days = (filed - qend).days
    if days <= 5:
        rate = jurisdiction["penalty_tier1_rate"]
    elif days <= 15:
        rate = jurisdiction["penalty_tier2_rate"]
    else:
        rate = jurisdiction["penalty_tier3_rate"]
    return round_half_up_cents(Decimal(shortfall) * Decimal(str(rate)))


def recompute_risk_posture(client):
    """client_credit_risk_posture: weighted base + count of unresolved events."""
    unresolved = [e for e in store.funding_failures.values()
                  if e["client_id"] == client["id"] and e.get("resolved_at") is None]
    base = sum(2 if e["kind"] == "NSF_RETURN" else 1 for e in unresolved)
    count = len(unresolved)
    client["funding_failure_count"] = count
    if base >= 4:
        posture = "HIGH"
    elif base >= 2:
        posture = "ELEVATED"
    else:
        posture = "NORMAL"
    client["risk_posture"] = posture
    return posture, count


def registration_for(client_id, jurisdiction_id):
    """Find the JurisdictionRegistration for (client, jurisdiction), if any.
    Prefers the most recently created."""
    regs = [r for r in store.registrations.values()
            if r["client_id"] == client_id and r["jurisdiction_id"] == jurisdiction_id]
    if not regs:
        return None
    return sorted(regs, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))[-1]
