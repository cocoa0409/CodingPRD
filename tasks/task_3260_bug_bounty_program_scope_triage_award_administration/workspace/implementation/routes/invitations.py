"""Program invitation endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PROGRAM_NOT_ACTIVE, ERR_RESEARCHER_BANNED, ERR_REPUTATION_TOO_LOW,
    ERR_INVITATION_EXPIRED,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
    parse_pagination,
)
from middleware import require_roles, check_researcher_owner
from response import success_object, success_list
from serializers import invitation_out

bp = Blueprint("invitations", __name__)

CREATE_FIELDS = {"program_id", "researcher_id"}
RESPOND_FIELDS = {"decision"}
INVITATION_TTL = timedelta(days=7)


def _get_invitation(iid):
    inv = db.invitations.get(iid)
    if inv is None:
        raise_err(ERR_NOT_FOUND, f"Invitation {iid} not found")
    return inv


@bp.route("/api/invitations", methods=["POST"])
def issue_invitation():
    require_roles({"ProgramAdmin"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["program_id", "researcher_id"])
    program = db.programs.get(body["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, f"Program {body['program_id']} not found")
    researcher = db.researchers.get(body["researcher_id"])
    if researcher is None:
        raise_err(ERR_NOT_FOUND, f"Researcher {body['researcher_id']} not found")
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Program must be ACTIVE to issue invitations")
    if researcher["status"] == "BANNED":
        raise_err(ERR_RESEARCHER_BANNED, "BANNED researcher may not receive invitations")
    if researcher["status"] == "SUSPENDED":
        raise_err(ERR_RESEARCHER_BANNED, "SUSPENDED researcher may not receive invitations")
    from services import reputation as rep_svc
    rep_svc.refresh_reputation(researcher)
    if researcher["reputation_lifetime"] < program["min_reputation"]:
        raise_err(ERR_REPUTATION_TOO_LOW, "Researcher reputation below program minimum")
    now = clock.now()
    inv = base_entity()
    inv.update(
        {
            "program_id": program["id"],
            "researcher_id": researcher["id"],
            "status": "PENDING",
            "issued_at": clock.iso(now),
            "expires_at": clock.iso(now + INVITATION_TTL),
            "reputation_at_issue": researcher["reputation_lifetime"],
        }
    )
    db.invitations[inv["id"]] = inv
    return success_object(invitation_out(inv), 201)


@bp.route("/api/invitations/<invitation_id>", methods=["GET"])
def read_invitation(invitation_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Researcher"})
    return success_object(invitation_out(_get_invitation(invitation_id)))


@bp.route("/api/invitations", methods=["GET"])
def list_invitations():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.invitations.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [i for i in items if i["program_id"] == pid]
    rid = request.args.get("researcher_id")
    if rid is not None:
        items = [i for i in items if i["researcher_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: i["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([invitation_out(i) for i in page], limit, offset, total)


@bp.route("/api/invitations/<invitation_id>/respond", methods=["POST"])
def respond_invitation(invitation_id):
    user_id, role = require_roles({"Researcher"})
    inv = _get_invitation(invitation_id)
    check_researcher_owner(user_id, role, inv["researcher_id"])
    body = get_body()
    reject_unknown_fields(body, RESPOND_FIELDS)
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("ACCEPT", "DECLINE"):
        raise_err(ERR_INVALID_REQUEST, "decision must be ACCEPT or DECLINE")
    now = clock.now()
    if inv["status"] == "EXPIRED":
        raise_err(ERR_INVITATION_EXPIRED, "Invitation expired")
    if inv["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"Invitation is {inv['status']}")
    if now > clock.parse_iso(inv["expires_at"]):
        inv["status"] = "EXPIRED"
        touch(inv)
        raise_err(ERR_INVITATION_EXPIRED, "Invitation expired")
    inv["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    touch(inv)
    return success_object(invitation_out(inv))
