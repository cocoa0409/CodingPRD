"""Deterministic calculations (PRD 2.5, 3.1, 3.4, 3.5, 3.7, 3.9)."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db, floor_days

# --- pinned constants -----------------------------------------------------
DAY_PENALTY_CENTS = 250
IMBALANCE_PENALTY_CENTS = 1500
DEFAULT_BALANCE_TOLERANCE_ITEMS = 3
RUSH_SURCHARGE_CENTS = 1200
RUSH_THRESHOLD_DAYS = 3
SUBSIDY_CAP_CENTS = 4000
SUBSIDY_TIERS = (
    (2000, Decimal("0.80")),
    (6000, Decimal("0.60")),
    (12000, Decimal("0.40")),
)
SUBSIDY_TOP_RATE = Decimal("0.25")
COPYRIGHT_RECENCY_YEARS = 5
COPYRIGHT_LIMIT_FREE_FILLS = 5
ROYALTY_BASE_CENTS = 800
ROYALTY_PER_PAGE_CENTS = 65
ROYALTY_MIN_CENTS = 1500
GRACE_DAYS = 2
DAILY_FINE_CENTS = 150
RECALL_BREACH_MULTIPLIER = 3
OVERDUE_FINE_CAP_CENTS = 6000
LENDER_PROCESSING_FEE_CENTS = 2500
DEFAULT_REPLACEMENT_COST_CENTS = 7500
CONSORTIUM_SURCHARGE_PCT = Decimal("0.075")
W_LOST = 25
W_DAMAGED = 12
W_LATE = 6
W_UNCLAIMED = 8
UNPAID_UNIT_CENTS = 1000
W_OVERDUE_IN_FLIGHT = 6
W_ON_TIME_RETURN = 4
STANDING_BLOCK_THRESHOLD = 40
HOLD_SHELF_DAYS = 7
RENEWAL_DAYS = 14
MAX_TOTAL_LOAN_DAYS = 84
DEFAULT_RECALL_GRACE_DAYS = 7
DELIVERY_ACCESS_DAYS = 30
DELIVERY_MAX_DOWNLOADS = 3
TRANSIT_SLA_DAYS = 14
MONTHS_PER_YEAR = 12

PERIOD_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

REQUEST_TERMINAL = (
    "CLOSED",
    "CLOSED_WITH_DAMAGE",
    "CLOSED_LOST",
    "CANCELLED",
    "UNFILLED",
    "FILLED_BY_PURCHASE",
    "UNCLAIMED",
)


def round_half_up(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clamp_score(value):
    return max(0, min(100, value))


# --- copyright ------------------------------------------------------------

def royalty_fee_cents(pages_requested):
    pages = pages_requested or 0
    return max(ROYALTY_MIN_CENTS, ROYALTY_BASE_CENTS + ROYALTY_PER_PAGE_CENTS * pages)


def counts_toward_limit(bib, current_year):
    return bib["publication_year"] > current_year - COPYRIGHT_RECENCY_YEARS


def counted_fill_count(issn, calendar_year):
    total = 0
    for row in db.clearances.values():
        if row["issn"] != issn or row["calendar_year"] != calendar_year:
            continue
        if row["status"] != "ACTIVE":
            continue
        if row["method"] == "CONTU_FREE":
            total += 1
    return total


def copyright_usage(issn, calendar_year):
    counted = 0
    royalty_paid = 0
    pre_window = 0
    for row in db.clearances.values():
        if row["issn"] != issn or row["calendar_year"] != calendar_year:
            continue
        if row["status"] != "ACTIVE":
            continue
        if row["method"] == "CONTU_FREE":
            counted += 1
        elif row["method"] == "ROYALTY_PAID":
            royalty_paid += 1
        elif row["method"] == "PRE_WINDOW_EXEMPT":
            pre_window += 1
    return {
        "issn": issn,
        "calendar_year": calendar_year,
        "counted_fill_count": counted,
        "free_fills_remaining": max(0, COPYRIGHT_LIMIT_FREE_FILLS - counted),
        "royalty_paid_count": royalty_paid,
        "pre_window_exempt_count": pre_window,
    }


def active_royalty_clearance(request_id):
    for row in db.clearances.values():
        if row["request_id"] == request_id and row["status"] == "ACTIVE" \
                and row["method"] == "ROYALTY_PAID":
            return row
    return None


def active_clearances(request_id):
    return [r for r in db.clearances.values()
            if r["request_id"] == request_id and r["status"] == "ACTIVE"]


# --- licensed access ------------------------------------------------------

def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def licensed_access_available(bib, current_year):
    status = bib.get("licensed_access_status")
    if status == "LICENSED_FULL":
        return True
    if status == "LICENSED_EMBARGOED":
        months = bib.get("embargo_months") or 0
        years = ceil_div(months, MONTHS_PER_YEAR)
        return bib["publication_year"] <= current_year - years
    return False


# --- agreements -----------------------------------------------------------

def applicable_agreement(partner_id, at):
    candidates = [a for a in db.agreements.values()
                  if a["partner_id"] == partner_id and a["status"] == "ACTIVE"
                  and a["effective_from"] <= at < a["effective_to"]]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["effective_from"], a["created_at"]))
    best = candidates[-1]
    latest = best["effective_from"]
    tied = [a for a in candidates if a["effective_from"] == latest]
    tied.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return tied[0]


def windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open agreement windows: adjacency is legal."""
    return a_from < b_to and b_from < a_to


def effective_fee_cents(quoted_fee_cents, agreement):
    if agreement is None:
        return quoted_fee_cents
    mode = agreement.get("fee_waiver_mode")
    if mode == "FULL":
        return 0
    if mode == "CAPPED":
        return max(0, quoted_fee_cents - (agreement.get("capped_waiver_cents") or 0))
    return quoted_fee_cents


def tolerance_items(agreement):
    if agreement is None:
        return DEFAULT_BALANCE_TOLERANCE_ITEMS
    value = agreement.get("balance_tolerance_items")
    return DEFAULT_BALANCE_TOLERANCE_ITEMS if value is None else value


# --- sourcing / pricing ---------------------------------------------------

def days_available(needed_by, at):
    return floor_days(needed_by, at)


def landed_cost(effective_fee, quoted_turnaround_days, days_avail, imbalance_penalty):
    lateness_days = max(0, quoted_turnaround_days - days_avail)
    return effective_fee + DAY_PENALTY_CENTS * lateness_days + imbalance_penalty


def subsidy_rate(gross_cents):
    for ceiling, rate in SUBSIDY_TIERS:
        if gross_cents <= ceiling:
            return rate
    return SUBSIDY_TOP_RATE


def price_request(req):
    """Assemble the patron charge from the pinned snapshots (PRD 3.5)."""
    base = req.get("committed_fee_cents") or 0
    rush = RUSH_SURCHARGE_CENTS if (req.get("days_available_at_source") or 0) \
        <= RUSH_THRESHOLD_DAYS else 0
    clearance = active_royalty_clearance(req["id"])
    royalty = (clearance.get("royalty_cents") or 0) if clearance else 0
    gross = base + rush + royalty
    subsidy = min(SUBSIDY_CAP_CENTS,
                  round_half_up(Decimal(gross) * subsidy_rate(gross)))
    req["rush_surcharge_cents"] = rush
    req["royalty_cents"] = royalty
    req["gross_charge_cents"] = gross
    req["subsidy_cents"] = subsidy
    req["net_patron_charge_cents"] = gross - subsidy
    return req


# --- fines ----------------------------------------------------------------

def overdue_fine_cents(due_at, end_instant, breached):
    overdue_days = max(0, floor_days(end_instant, due_at))
    billable_days = max(0, overdue_days - GRACE_DAYS)
    raw = DAILY_FINE_CENTS * billable_days
    multiplier = RECALL_BREACH_MULTIPLIER if breached else 1
    return min(OVERDUE_FINE_CAP_CENTS, raw * multiplier)


# --- invoicing ------------------------------------------------------------

def surcharged(amount_cents):
    return amount_cents + round_half_up(Decimal(amount_cents) * CONSORTIUM_SURCHARGE_PCT)


def period_bounds(period_month):
    year = int(period_month[0:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end
