"""Layered-access audit routes (PRD §4)."""

from flask import Blueprint

import middleware
import response
import validate
from services import audits, common

bp = Blueprint("access_audits", __name__)


@bp.post("/platform/access-audits")
def open_audit():
    actor = middleware.require("SecurityAuditor")
    b = validate.body()
    audit = audits.create_audit(actor, b)
    return response.ok(_ser(audit), 201)


@bp.post("/platform/access-audits/<audit_id>/close")
def close_audit(audit_id):
    actor = middleware.require("SecurityAuditor")
    common.get_access_audit(audit_id)
    b = validate.body()
    audit = audits.close_audit(actor, audit_id, b)
    return response.ok(_ser(audit))


def _ser(row):
    from serializers import access_audit

    return access_audit(row)