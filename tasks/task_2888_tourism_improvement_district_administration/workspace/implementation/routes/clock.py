"""The logical clock (PRD 2.4) and its three-hop transparency cascade (PRD 3.9)."""
from flask import Blueprint

import envelope
import store
import validate
from auth import authenticate
from routes.common import ADMIN
from services import core
from store import touch

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ADMIN])
    b = validate.body()
    current_utc = validate.instant(b, "current_utc")
    store.state.clock = current_utc.dt

    # Hop one: every SCHEDULED or NOTICED artifact past its deadline goes OVERDUE.
    districts = []
    for rec in store.sorted_records(list(store.state.records.values())):
        if rec["status"] not in ("SCHEDULED", "NOTICED"):
            continue
        if store.state.clock <= rec["required_by"]:
            continue
        rec["status"] = "OVERDUE"
        touch(rec)
        if rec["district_id"] not in districts:
            districts.append(rec["district_id"])

    # Hop two: the district's standing is re-derived from its OVERDUE artifacts.
    for district_id in districts:
        core.rederive_transparency_standing(store.state.districts[district_id])

    return envelope.ok({})
