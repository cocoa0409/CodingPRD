from flask import Blueprint, request

import auth
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("report_distributions", __name__)

ACTIONS = ("REQUEST_NDA", "APPROVE", "DENY", "DELIVER", "REVOKE")
ACTION_ROLES = {
    "REQUEST_NDA": {"AccountExecutive"},
    "DELIVER": {"AccountExecutive"},
    "APPROVE": {"ComplianceLead"},
    "DENY": {"ComplianceLead"},
    "REVOKE": {"ComplianceLead"},
}
EDGES = {
    ("REQUESTED", "REQUEST_NDA"): "NDA_PENDING",
    ("NDA_PENDING", "APPROVE"): "APPROVED",
    ("REQUESTED", "DENY"): "DENIED",
    ("NDA_PENDING", "DENY"): "DENIED",
    ("APPROVED", "DELIVER"): "DELIVERED",
    ("DELIVERED", "REVOKE"): "REVOKED",
}
LIVE = ("REQUESTED", "NDA_PENDING", "APPROVED", "DELIVERED")


@bp.post("/soc/report-distributions")
def create_distribution():
    auth.authenticate({"AccountExecutive"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    v.req_id(body, "engagement_id")
    recipient_name = v.req_str(body, "recipient_name", 1, 200)
    recipient_email = v.req_str(body, "recipient_email", 1, 200)

    live = [
        r
        for r in DB["report_distributions"].values()
        if r["engagement_id"] == engagement["id"] and r["status"] in LIVE
    ]
    for r in live:
        if r["recipient_name"] == recipient_name:
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    if len(live) >= engagement["max_distribution_recipients"]:
        raise ApiError("ERR_DISTRIBUTION_LIMIT_EXCEEDED")

    row = store.new_row(
        "report_distributions",
        {
            "engagement_id": engagement["id"],
            "recipient_name": recipient_name,
            "recipient_email": recipient_email,
            "nda_reference": None,
            "status": "REQUESTED",
            "delivered_at": None,
            "revoked_at": None,
            "report_period_start": None,
            "report_period_end": None,
        },
    )
    return ok(store.public(row), 201)


@bp.get("/soc/report-distributions/<report_distribution_id>")
def read_distribution(report_distribution_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("report_distributions", report_distribution_id)
    return ok(store.public(row))


@bp.get("/soc/report-distributions")
def list_distributions():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("report_distributions")
    for key in ("engagement_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/report-distributions/<report_distribution_id>/transitions")
def transition_distribution(report_distribution_id):
    _uid, role = auth.authenticate({"AccountExecutive", "ComplianceLead"})
    body = auth.body()
    auth.check_action_role(role, body.get("action"), ACTION_ROLES)
    row = store.get_or_404("report_distributions", report_distribution_id)
    action = v.req_enum(body, "action", ACTIONS)
    nda_reference = v.opt_str(body, "nda_reference", 1, 500)
    v.opt_str(body, "reason", 0, 2000)

    engagement = DB["engagements"][row["engagement_id"]]

    if action == "DELIVER":
        services.require_phase(engagement, {"ISSUED"})
        services.require_not_frozen(engagement)
        services.require_posture_open(engagement)

    target = EDGES.get((row["status"], action))
    if target is None:
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if action == "APPROVE" and nda_reference is None:
        raise ApiError("ERR_INVALID_STATE")

    row["status"] = target
    if action == "APPROVE":
        row["nda_reference"] = nda_reference
    elif action == "DELIVER":
        row["delivered_at"] = store.now_iso()
        row["report_period_start"] = engagement["observation_period_start"]
        row["report_period_end"] = engagement["observation_period_end"]
    elif action == "REVOKE":
        row["revoked_at"] = store.now_iso()
        for q in store.rows("customer_questionnaires"):
            if q["report_distribution_id"] != row["id"] or q["status"] == "CLOSED":
                continue
            q["status"] = "CLOSED"
            q["deflected_by_report_count"] = 0
            q["deflected_by_bridge_count"] = 0
            q["deflected_by_cuec_count"] = 0
            q["manual_response_count"] = q["item_count"]
            q["deflection_ratio"] = 0.0
            q["bridge_letter_id_used"] = None
            store.touch(q)
    store.touch(row)
    return ok(store.public(row))
