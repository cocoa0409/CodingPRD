"""CreditAssessment bureau-wide endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles
from response import success_object, success_list
from services_common import paginate, public

bp = Blueprint("assessments", __name__)

ROLES = {"BureauCompliance", "BureauTreasury"}


@bp.route("/credit-assessments", methods=["GET"])
def list_assessments():
    auth = authenticate()
    require_roles(auth, ROLES)
    items = list(store.credit_assessments.values())
    cid = request.args.get("client_id")
    if cid is not None:
        items = [a for a in items if a["client_id"] == cid]
    page, limit, offset, total = paginate(items)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/credit-assessments/<assessmentId>", methods=["GET"])
def get_assessment(assessmentId):
    auth = authenticate()
    require_roles(auth, ROLES)
    a = store.credit_assessments.get(assessmentId)
    if not a:
        raise errors.not_found("Credit assessment not found")
    return success_object(public(a))
