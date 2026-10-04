"""Audit trail query route."""
from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from services import serialize as ser

bp = Blueprint("audit", __name__)


@bp.get("/ins/audit-events")
def list_audit_events():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "ComplianceOfficer")
    items = list(db.audit_events.values())
    et = request.args.get("entity_type")
    ei = request.args.get("entity_id")
    action = request.args.get("action")
    if et is not None:
        items = [e for e in items if e["entity_type"] == et]
    if ei is not None:
        items = [e for e in items if e["entity_id"] == ei]
    if action is not None:
        items = [e for e in items if e["action"] == action]
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)
