"""PlatformAdmin endpoints: logical clock and the renewal batch sweep."""

from datetime import date

from flask import Blueprint

from auth import require_roles
from db import locked, mint, store, touch
from serializers import term_view  # noqa: F401  (kept for symmetry)
from services import add_years, clock_date, price_term_cents
from util import err, get_body, parse_datetime_lenient, success_object

bp = Blueprint("admin", __name__)


@bp.post("/api/_clock/set_current_utc")
@locked
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 is required and must be an ISO 8601 timestamp")
    parsed = parse_datetime_lenient(raw)
    if parsed is None:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO 8601 timestamp")
    store.clock_dt = parsed
    store.clock_raw = raw
    return success_object({"current_utc": store.clock_raw})


@bp.post("/api/_batch/renewal_run")
@locked
def renewal_run():
    require_roles("PlatformAdmin")
    today = clock_date()
    # Snapshot the expiring ACTIVE terms up front; terms created by this run
    # are not revisited within the same sweep.
    expiring = [
        t
        for t in sorted(store.terms.values(), key=lambda r: r["_seq"])
        if t["status"] == "ACTIVE" and date.fromisoformat(t["end_date"]) <= today
    ]
    renewed_ids = []
    lapsed_ids = []
    for term in expiring:
        household = store.households.get(term["household_id"])
        if household is not None and household["auto_renew_enabled"]:
            term["status"] = "RENEWED"
            touch(term)
            start = date.fromisoformat(term["end_date"])
            new_paid = price_term_cents(term["term_years"], True)
            new_term = mint(store.terms)
            new_term.update(
                {
                    "household_id": term["household_id"],
                    "term_years": term["term_years"],
                    "is_renewal": True,
                    "start_date": start.isoformat(),
                    "end_date": add_years(start, term["term_years"]).isoformat(),
                    "purchased_at": store.clock_raw,
                    "paid_cents": new_paid,
                    "refunded_cents": 0,
                    "cancel_reason": None,
                    "cancelled_at": None,
                    "status": "ACTIVE",
                }
            )
            household["lifetime_collected_cents"] += new_paid
            touch(household)
            renewed_ids.append(term["id"])
        else:
            term["status"] = "LAPSED"
            touch(term)
            lapsed_ids.append(term["id"])
    # Household standing and member in_good_standing are derived at read time,
    # so the recompute happens automatically on the next read.
    return success_object(
        {
            "renewed_count": len(renewed_ids),
            "lapsed_count": len(lapsed_ids),
            "renewed_term_ids": renewed_ids,
            "lapsed_term_ids": lapsed_ids,
        }
    )
