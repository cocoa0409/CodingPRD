"""Logical clock endpoint (PRD 2.4) plus an unauthenticated health probe."""
from flask import Blueprint

from core import body, db, endpoint, f_dt, respond_object

bp = Blueprint("reference", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    # Readiness probe for launchers; not part of the PRD surface.
    return respond_object({"status": "ok"})


@bp.post("/_clock/set_current_utc")
@endpoint("ProgramAdmin")
def set_current_utc():
    payload = body()
    to_iso8601 = f_dt(payload, "to_iso8601")
    db.clock = to_iso8601
    # is_overdue and all clock-dependent computed fields are resolved live at
    # read time, so advancing the clock needs no stored recomputation.
    return respond_object({}, 200)
