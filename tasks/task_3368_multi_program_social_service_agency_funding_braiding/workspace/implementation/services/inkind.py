"""in_kind_match_credit.

Eligible population: ACCEPTED rows valued by IRS_STANDARD_RATE or APPRAISAL,
inside the grant's award period, credited to a program whose match_eligible is
true. The per-hour value is capped by Grant.max_in_kind_rate_cents and the
credit is capped by what remains of the grant's matching requirement.
"""

import db
from common import cents

IRS_VOLUNTEER_HOUR_RATE_CENTS = 3390
CREDIT_VALUATIONS = ("IRS_STANDARD_RATE", "APPRAISAL")
ROLLING_WINDOW_DAYS = 7
MAX_DONOR_HOURS = 40


def _in_period(grant, donation):
    start = grant.get("period_start")
    end = grant.get("period_end")
    date = donation.get("donation_date")
    if start is None or end is None or date is None:
        return False
    return start <= date <= end


def program_is_match_eligible(grant):
    program = db.get("programs", grant.get("program_id"))
    return bool(program and program.get("match_eligible") is True)


def eligible_rows(grant):
    if not program_is_match_eligible(grant):
        return []
    out = []
    for donation in db.rows("in_kind_donations"):
        if donation.get("grant_id") != grant["id"]:
            continue
        if donation.get("status") != "ACCEPTED":
            continue
        if donation.get("valuation_method") not in CREDIT_VALUATIONS:
            continue
        if not _in_period(grant, donation):
            continue
        out.append(donation)
    return sorted(out, key=lambda d: (d["created_at"], d["_seq"]))


def requirement_cents(grant):
    return cents(grant.get("matching_requirement_pct", 0) * grant.get("total_award_cents", 0))


def credited_total(grant):
    return sum(row.get("match_credit_cents", 0) for row in eligible_rows(grant))


def match_satisfied(grant):
    return credited_total(grant) >= requirement_cents(grant)


def donor_hours_in_window(donor_reference, donation_date):
    from datetime import timedelta
    window_start = donation_date - timedelta(days=ROLLING_WINDOW_DAYS)
    total = 0
    for donation in db.rows("in_kind_donations"):
        if donation.get("donor_reference") != donor_reference:
            continue
        if donation.get("status") != "ACCEPTED":
            continue
        date = donation.get("donation_date")
        if date is None:
            continue
        if window_start <= date <= donation_date:
            total += donation.get("hours", 0)
    return total


def compute_values(donation, grant, already_credited):
    hour_value = min(donation.get("rate_cents", 0), grant.get("max_in_kind_rate_cents", 0))
    value_cents = cents(donation.get("hours", 0) * hour_value)
    uncapped = cents(donation.get("hours", 0) * donation.get("rate_cents", 0))
    remaining = max(requirement_cents(grant) - already_credited, 0)
    return value_cents, uncapped, min(value_cents, remaining)
