"""Score discovery request endpoints."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, discovery_request,
    body_of, reject_unknown, require_fields, as_str, read_pagination, paginate,
    ordered_rows, now_iso, authenticate, authorize,
)
from errors import ApiError

bp = Blueprint("score_discovery_requests", __name__)

READ_ROLES = ["BureauAdministrator", "ComplianceOfficer", "ScoreConsumer"]


@bp.post("/score-discovery-requests")
def create_discovery_request():
    role, user_id = authenticate(request)
    authorize(role, ["ScoreConsumer", "ComplianceOfficer"])
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")

    body = body_of(request)
    reject_unknown(body, {"tag"})
    require_fields(body, ["tag"])
    tag = as_str(body["tag"], "tag")

    for existing in DB["score_discovery_requests"].values():
        if existing["tag"] == tag and existing["status"] == "REGISTERED":
            raise ApiError("ERR_DUPLICATE_DISCOVERY_TAG")

    rec = new_record()
    rec.update({
        "tag": tag,
        "requested_at": now_iso(),
        "status": "REGISTERED",
        "consumed_score_result_id": None,
    })
    store("score_discovery_requests", rec)
    return ok(rec, 201)


@bp.get("/score-discovery-requests/<request_id>")
def get_discovery_request(request_id):
    resolve_actor(request, READ_ROLES)
    return ok(discovery_request(request_id))


@bp.get("/score-discovery-requests")
def list_discovery_requests():
    resolve_actor(request, READ_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("score_discovery_requests")

    for param in ("status", "consumed_score_result_id", "tag"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)