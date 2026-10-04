"""outcome_rate.

The rate is derived from the delivery record: the window is every DOCUMENTED or
BILLED delivery for the report's grant whose service_date falls inside the
closed reporting window. The universe is a set of distinct clients; the base
all_served variant is the one this API evaluates, so denominator_basis is
ALL_SERVED. A denominator below five forces rate_pct to null.
"""

import db
from common import pct2

MIN_DENOMINATOR = 5
RATE_SCALE = 2


def window_deliveries(report):
    start = report.get("reporting_period_start")
    end = report.get("reporting_period_end")
    out = []
    for delivery in db.rows("service_deliveries"):
        if delivery.get("grant_id") != report.get("grant_id"):
            continue
        if delivery.get("status") not in ("DOCUMENTED", "BILLED"):
            continue
        date = delivery.get("service_date")
        if date is None or start is None or end is None:
            continue
        if start <= date <= end:
            out.append(delivery)
    return out


def completed_clients(grant_id):
    done = set()
    for enrollment in db.rows("enrollments"):
        if enrollment.get("grant_id") != grant_id:
            continue
        if enrollment.get("status") == "EXITED" and enrollment.get("exit_reason") == "COMPLETED":
            done.add(enrollment.get("client_id"))
    return done


def denominator_universe(report, variant="all_served"):
    clients = {d.get("client_id") for d in window_deliveries(report)}
    if variant == "completed_only":
        clients = clients & completed_clients(report.get("grant_id"))
    return clients


def compute(report, variant="all_served"):
    """Returns (rate_pct, denominator_basis, denominator_effective)."""
    basis = "COMPLETED_ONLY" if variant == "completed_only" else "ALL_SERVED"
    effective = len(denominator_universe(report, variant))
    if effective < MIN_DENOMINATOR:
        return None, basis, effective
    numerator = report.get("numerator", 0) or 0
    return pct2(numerator / effective * 100), basis, effective
