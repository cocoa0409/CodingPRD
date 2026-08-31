from decimal import Decimal

from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("audit_exceptions", __name__)

DISPOSITIONS = ("ISOLATED", "PERVASIVE")


@bp.get("/soc/audit-exceptions/<audit_exception_id>")
def read_exception(audit_exception_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("audit_exceptions", audit_exception_id)
    return ok(store.public(row))


@bp.get("/soc/audit-exceptions")
def list_exceptions():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("audit_exceptions")
    for key in ("audit_sample_id", "control_id", "disposition"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/audit-exceptions/<audit_exception_id>/evaluate")
def evaluate(audit_exception_id):
    user_id, _role = auth.authenticate({"Auditor"})
    row = store.get_or_404("audit_exceptions", audit_exception_id)
    body = auth.body()
    disposition = v.req_enum(body, "disposition", DISPOSITIONS)
    v.opt_str(body, "evaluation_note", 0, 2000)

    sample = DB["audit_samples"][row["audit_sample_id"]]
    control = DB["controls"][row["control_id"]]
    engagement = DB["engagements"][control["engagement_id"]]

    services.require_phase(engagement, {"FIELDWORK", "REPORTING"})

    if row["disposition"] != "UNEVALUATED":
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")
    if sample["status"] != "CONCLUDED_EXCEPTIONS":
        raise ApiError("ERR_INVALID_STATE")

    rate = Decimal(str(sample["deviation_rate"]))
    population = sample["population_size_snapshot"]
    upper = calcs.projected_failures_upper(rate, population, control["risk_rating"])
    row["projected_failures_upper"] = upper
    row["pervasive_recommended"] = calcs.pervasive_recommended(upper, population)
    row["evaluated_by_user_id"] = user_id
    row["evaluated_at"] = store.now_iso()
    row["disposition"] = disposition
    row["severity_assigned"] = calcs.DISPOSITION_SEVERITY[disposition]
    store.touch(row)

    if disposition == "PERVASIVE":
        if control["design_status"] == "DESIGN_APPROVED":
            control["design_status"] = "DESIGN_DEFICIENT"
            store.touch(control)
        for gap in services.gaps_of(engagement["id"]):
            if gap["audit_exception_id"] == row["id"]:
                gap["severity"] = "CRITICAL"
                gap["debt_points"] = services.gap_live_points(gap)
                store.touch(gap)

    services.refresh_engagement(engagement)
    return ok(store.public(row))
