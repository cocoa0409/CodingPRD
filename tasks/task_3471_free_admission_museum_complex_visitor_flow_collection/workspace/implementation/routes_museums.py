"""Museum endpoints (PRD 3.1): create, read (with FORWARD screening backlog),
and emergency close-day with the RESERVED -> EXPIRED pass cascade."""

from flask import Blueprint

import db
import serializers
import util
from envelope import success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("museums", __name__)

MUSEUM_READ_ROLES = [
    "PlatformAdmin",
    "VisitorServices",
    "SecurityScreener",
    "ExhibitionManager",
    "ProgramCoordinator",
    "LoansOfficer",
    "Registrar",
    "Curator",
    "CommitteeChair",
    "FinanceOfficer",
    "Docent",
    "Scholar",
    "Member",
    "Public",
]


@bp.post("/campus/museums")
def create_museum():
    _uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = util.body()
    # Request shape (priority 9)
    museum_code = util.req_str(b, "museum_code")
    display_name = util.req_str(b, "display_name")
    requires_timed_pass = util.req_bool(b, "requires_timed_pass")
    quarter_hour_pass_quota = util.req_int(b, "quarter_hour_pass_quota", minimum=1)
    daily_pass_quota = util.req_int(b, "daily_pass_quota", minimum=1)
    screening_rate = util.req_int(b, "screening_rate_per_quarter_hour", minimum=1)
    if daily_pass_quota < quarter_hour_pass_quota:
        fail(
            "ERR_INVALID_REQUEST",
            "daily_pass_quota must be >= quarter_hour_pass_quota",
        )
    for m in db.STORE["museums"].values():
        if m["museum_code"] == museum_code:
            fail("ERR_INVALID_REQUEST", "museum_code must be unique")
    m = db.new_entity(
        {
            "museum_code": museum_code,
            "display_name": display_name,
            "requires_timed_pass": requires_timed_pass,
            "quarter_hour_pass_quota": quarter_hour_pass_quota,
            "daily_pass_quota": daily_pass_quota,
            "screening_rate_per_quarter_hour": screening_rate,
            "closed_dates": [],
        }
    )
    db.STORE["museums"][m["id"]] = m
    return success(serializers.museum(m), 201)


@bp.get("/campus/museums/<mid>")
def get_museum(mid):
    _uid, role = auth()
    require_role(role, MUSEUM_READ_ROLES)
    m = get_or_404("museums", mid, "Museum")
    return success(serializers.museum(m))


@bp.post("/campus/museums/<mid>/close-day")
def close_day(mid):
    _uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    m = get_or_404("museums", mid, "Museum")
    b = util.body()
    closure_date = util.req_date(b, "closure_date")
    if closure_date not in m["closed_dates"]:
        m["closed_dates"].append(closure_date)
    # Cascade: every RESERVED pass at this museum on that date -> EXPIRED.
    for p in db.STORE["timed_entry_passes"].values():
        if (
            p["museum_id"] == m["id"]
            and p["visit_date"] == closure_date
            and p["status"] == "RESERVED"
        ):
            p["status"] = "EXPIRED"
            db.touch(p)
    db.touch(m)
    return success(serializers.museum(m))
