"""The logical clock (PRD 2.4). Mounted at the server root, not under /design-system."""

from flask import Blueprint

from auth import clock_roles
from responses import ok
from store import store, iso
from validation import body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@clock_roles
def set_current_utc():
    payload = body()
    target = req_datetime(payload, "to_iso8601")

    store.clock = target

    due = [g for g in store.grants.values()
           if g["state"] == "APPROVED" and g["_expires_dt"] <= target]
    due.sort(key=lambda g: (g["created_at"], g["_seq"]))

    expired_ids = []
    for grant in due:
        grant["state"] = "EXPIRED"
        store.touch(grant)
        expired_ids.append(grant["id"])

    return ok({
        "current_utc": iso(store.clock),
        "expired_exception_grant_ids": expired_ids,
        "expired_count": len(expired_ids),
    })
