"""Classifications: list, get, activate."""
from flask import Blueprint, request

import db
from cascade import activate_classification
from errors import fail
from middleware import auth, require_role
from response import ok, ok_list
from util import body, need, v_date, pagination_params, page_of

bp = Blueprint("classification", __name__)

NON_TERMINAL_APPEAL = ("FILED", "DATA_VERIFICATION")


@bp.route("/ppc/classifications", methods=["GET"])
def list_classifications():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("classifications")
    for f in ("community_id", "cycle_id", "score_sheet_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(c) for c in page], total, limit, offset)


@bp.route("/ppc/classifications/<classificationId>", methods=["GET"])
def get_classification(classificationId):
    auth()
    cl = db.find("classifications", classificationId)
    if cl is None:
        fail("ERR_CLASSIFICATION_NOT_FOUND", "classification does not exist")
    return ok(db.pub(cl))


@bp.route("/ppc/classifications/<classificationId>/activate", methods=["POST"])
def activate(classificationId):
    uid, role = auth()
    require_role(role, "ClassRegistrar")
    cl = db.find("classifications", classificationId)
    if cl is None:
        fail("ERR_CLASSIFICATION_NOT_FOUND", "classification does not exist")
    if cl["status"] != "PUBLISHED":
        fail("ERR_CLASSIFICATION_INVALID_STATE",
             "classification must be PUBLISHED to activate, not %s" % cl["status"])
    for a in db.all_of("appeals"):
        if a["classification_id"] == cl["id"] and a["status"] in NON_TERMINAL_APPEAL:
            fail("ERR_APPEAL_PENDING", "a non-terminal appeal exists on the classification")
    b = body()
    effective = v_date(need(b, "effective_from"), "effective_from")
    if effective < db.clock_date():
        fail("ERR_INVALID_REQUEST", "effective_from must not precede the logical clock date")
    cycle = db.find("cycles", cl["cycle_id"])
    if cycle is None or cycle["status"] in ("EFFECTIVE", "WITHDRAWN"):
        fail("ERR_CYCLE_INVALID_STATE",
             "the classification's cycle is not the community's active cycle")
    activate_classification(cl, effective.isoformat())
    return ok(db.pub(cl))
