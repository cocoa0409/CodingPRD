"""Collective bargaining agreements."""

from flask import Blueprint, request

from db import db
from domain import agreement_for_season, base_fields, serialize
from errors import raise_err
from middleware import endpoint
from response import ok, ok_list
from validate import body, check_body_fks, opt_int, paginate, req_int, req_str

bp = Blueprint("union", __name__)


@bp.route("/orchestra/union-agreements", methods=["POST"])
@endpoint(["OrchestraManager"])
def create_agreement():
    data = body()
    check_body_fks(data, ["season_id"])
    season = db.seasons.get(data.get("season_id"))
    if season is None:
        req_str(data, "season_id")
        raise_err("ERR_SEASON_NOT_FOUND")

    scale = req_int(data, "scale_service_fee_cents", minv=1)
    max_minutes = opt_int(data, "max_service_minutes", 150, minv=1)
    overtime_rate = opt_int(data, "overtime_rate_cents_per_minute", 400, minv=0)
    min_rest = opt_int(data, "min_rest_minutes_between_services", 90, minv=0)
    max_per_day = opt_int(data, "max_services_per_day", 2, minv=1)
    doubling = opt_int(data, "doubling_premium_bp", 1250, minv=0)
    mandatory_break = opt_int(data, "mandatory_break_minutes", 20, minv=0)
    principal = opt_int(data, "principal_premium_bp", 2000, minv=0)

    if agreement_for_season(season["id"]) is not None:
        raise_err("ERR_UNION_AGREEMENT_DUPLICATE")

    agreement = base_fields()
    agreement.update({
        "season_id": season["id"],
        "scale_service_fee_cents": scale,
        "max_service_minutes": max_minutes,
        "overtime_rate_cents_per_minute": overtime_rate,
        "min_rest_minutes_between_services": min_rest,
        "max_services_per_day": max_per_day,
        "doubling_premium_bp": doubling,
        "mandatory_break_minutes": mandatory_break,
        "principal_premium_bp": principal,
    })
    db.agreements[agreement["id"]] = agreement
    return ok(serialize(agreement), 201)


@bp.route("/orchestra/union-agreements/<agreement_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager"])
def read_agreement(agreement_id):
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise_err("ERR_SERVICE_NOT_FOUND")
    return ok(serialize(agreement))


@bp.route("/orchestra/union-agreements", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager"])
def list_agreements():
    season_id = request.args.get("season_id")
    records = [a for a in db.agreements.values()
               if season_id is None or a["season_id"] == season_id]
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)
