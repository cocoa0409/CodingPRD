"""Entity serializers: stored fields plus PRD-defined computed fields."""

from datetime import date, datetime

from constants import BPS_DENOMINATOR, PROVISIONAL_OFFER_WEIGHT_BPS
from core import fmt_dt, rhu
from ledger import (
    meetings_held_count,
    nominations_used,
    seat_counts,
    training_completed_count,
)


def pub(e):
    """Public view of a stored entity: drops internal keys, renders datetimes."""
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def partner_out(p):
    d = pub(p)
    d["nominations_used"] = nominations_used(p["id"])
    return d


def cohort_out(c):
    d = pub(c)
    committed, outstanding = seat_counts(c["id"])
    d["seats_committed"] = committed
    d["offers_outstanding"] = outstanding
    d["seats_remaining"] = c["cohort_size"] - committed - outstanding
    d["projected_fill_provisional"] = committed + rhu(
        outstanding * PROVISIONAL_OFFER_WEIGHT_BPS, BPS_DENOMINATOR
    )
    d["projected_fill_final"] = committed
    d["meetings_held_count"] = meetings_held_count(c["id"])
    return d


def scholar_out(s):
    d = pub(s)
    d["training_completed_count"] = training_completed_count(s["id"])
    d["alumni_network_access"] = s["enrollment_status"] == "GRADUATED"
    return d
