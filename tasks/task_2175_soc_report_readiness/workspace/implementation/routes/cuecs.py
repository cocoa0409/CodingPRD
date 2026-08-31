from flask import Blueprint, request

import auth
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("cuecs", __name__)

ACTIONS = ("ARTICULATE", "RETIRE")
EDGES = {
    ("DRAFT", "ARTICULATE"): "ARTICULATED",
    ("ARTICULATED", "RETIRE"): "RETIRED",
    ("DRAFT", "RETIRE"): "RETIRED",
}


@bp.post("/soc/cuecs")
def create_cuec():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    criterion = v.fk(body, "trust_criterion_id", "trust_criteria")
    v.req_id(body, "engagement_id")
    v.req_id(body, "trust_criterion_id")
    statement = v.req_str(body, "statement", 1, 1000)
    topic = v.req_str(body, "deflection_topic", 1, 60)

    if not services.criterion_in_scope(engagement, criterion):
        raise ApiError("ERR_CRITERION_OUT_OF_SCOPE")

    row = store.new_row(
        "cuecs",
        {
            "engagement_id": engagement["id"],
            "trust_criterion_id": criterion["id"],
            "statement": statement,
            "deflection_topic": topic,
            "articulation_status": "DRAFT",
            "articulated_at": None,
        },
    )
    return ok(store.public(row), 201)


@bp.get("/soc/cuecs/<cuec_id>")
def read_cuec(cuec_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("cuecs", cuec_id)
    return ok(store.public(row))


@bp.get("/soc/cuecs")
def list_cuecs():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("cuecs")
    for key in ("engagement_id", "trust_criterion_id", "articulation_status"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/cuecs/<cuec_id>/articulate")
def articulate(cuec_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("cuecs", cuec_id)
    body = auth.body()
    action = v.req_enum(body, "action", ACTIONS)

    engagement = DB["engagements"][row["engagement_id"]]
    if action == "ARTICULATE":
        services.require_phase(engagement, {"READINESS", "OBSERVATION", "FIELDWORK", "REPORTING"})
    else:
        services.require_phase(
            engagement, {"SCOPING", "READINESS", "OBSERVATION", "FIELDWORK", "REPORTING",
                         "ABANDONED"}
        )

    target = EDGES.get((row["articulation_status"], action))
    if target is None:
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if action == "ARTICULATE":
        criterion = DB["trust_criteria"].get(row["trust_criterion_id"])
        if criterion is None or not services.criterion_in_scope(engagement, criterion):
            raise ApiError("ERR_CRITERION_OUT_OF_SCOPE")
        row["articulated_at"] = store.now_iso()

    row["articulation_status"] = target
    store.touch(row)
    return ok(store.public(row))
