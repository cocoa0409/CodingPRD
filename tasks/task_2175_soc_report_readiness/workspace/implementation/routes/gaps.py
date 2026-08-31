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

bp = Blueprint("gaps", __name__)

SEVERITIES = ("LOW", "MODERATE", "HIGH", "CRITICAL")
ACTIONS = ("PLAN", "REMEDIATE", "VERIFY", "REOPEN", "WITHDRAW")
ACTION_ROLES = {
    "PLAN": {"ComplianceLead"},
    "REMEDIATE": {"ComplianceLead"},
    "WITHDRAW": {"ComplianceLead"},
    "VERIFY": {"Auditor"},
    "REOPEN": {"Auditor"},
}
EDGES = {
    ("OPEN", "PLAN"): "PLANNED",
    ("REOPENED", "PLAN"): "PLANNED",
    ("PLANNED", "REMEDIATE"): "REMEDIATED",
    ("REMEDIATED", "VERIFY"): "VERIFIED",
    ("VERIFIED", "REOPEN"): "REOPENED",
    ("OPEN", "WITHDRAW"): "WITHDRAWN",
    ("PLANNED", "WITHDRAW"): "WITHDRAWN",
    ("REOPENED", "WITHDRAW"): "WITHDRAWN",
}


@bp.post("/soc/gaps")
def create_gap():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    control = v.fk(body, "control_id", "controls")
    criterion = v.fk(body, "trust_criterion_id", "trust_criteria")
    v.req_id(body, "engagement_id")
    severity = v.opt_enum(body, "severity", SEVERITIES, default="MODERATE")
    description = v.opt_str(body, "description", 1, 2000)

    row = services.create_gap(
        engagement,
        "MANUAL",
        severity,
        control_id=control["id"] if control else None,
        trust_criterion_id=criterion["id"] if criterion else None,
        description=description,
    )
    services.refresh_engagement(engagement)
    return ok(store.public(row), 201)


@bp.get("/soc/gaps/<gap_id>")
def read_gap(gap_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("gaps", gap_id)
    return ok(store.public(row))


@bp.get("/soc/gaps")
def list_gaps():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("gaps")
    for key in ("engagement_id", "control_id", "trust_criterion_id", "audit_exception_id",
                "status", "source"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/gaps/<gap_id>/transitions")
def transition_gap(gap_id):
    user_id, role = auth.authenticate({"ComplianceLead", "Auditor"})
    body = auth.body()
    auth.check_action_role(role, body.get("action"), ACTION_ROLES)
    row = store.get_or_404("gaps", gap_id)
    action = v.req_enum(body, "action", ACTIONS)
    owner = v.opt_str(body, "remediation_owner_user_id", 1, 200)
    due = v.opt_dt(body, "remediation_due_date")
    v.opt_str(body, "reason", 0, 2000)

    engagement = DB["engagements"][row["engagement_id"]]
    target = EDGES.get((row["status"], action))
    if target is None:
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if action == "PLAN":
        if owner is None or due is None:
            raise ApiError("ERR_INVALID_STATE")
    elif action == "VERIFY":
        if row["remediation_owner_user_id"] is not None and \
                user_id == row["remediation_owner_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    elif action == "REOPEN":
        if engagement["status"] == "ISSUED":
            raise ApiError("ERR_INVALID_STATE")

    if action == "PLAN":
        row["remediation_owner_user_id"] = owner
        row["remediation_due_date"] = store.fmt_iso(due)
    if action == "REOPEN":
        row["reopen_count"] = row["reopen_count"] + 1

    services.set_gap_status(row, target)
    services.refresh_engagement(engagement)
    return ok(store.public(row))
