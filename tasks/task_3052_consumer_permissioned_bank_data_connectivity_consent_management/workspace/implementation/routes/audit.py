"""Audit log listing."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_list
from services.serializers import audit_out

bp = Blueprint("audit", __name__)


@bp.route("/audit_logs", methods=["GET"])
def list_audit_logs():
    require_role("PlatformAdmin", "ComplianceReviewer")
    limit, offset = parse_limit_offset(request.args)
    f_type = request.args.get("entity_type")
    f_id = request.args.get("entity_id")
    items = list(db.audit_logs.values())
    if f_type:
        items = [a for a in items if a["entity_type"] == f_type]
    if f_id:
        items = [a for a in items if a["entity_id"] == f_id]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([audit_out(a) for a in page], limit, offset, total)
