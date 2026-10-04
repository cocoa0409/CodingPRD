"""Issuer and underwriter registration plus the issuer notification log
(PRD §3.1, §2.11)."""
from flask import Blueprint, request

import timeutil
from auth import auth, authenticate
from constants import ISSUER_TYPES, ROLE_PLATFORM_ADMIN
from envelope import paginate, parse_pagination, success_array, success_object
from errors import ERR_INVALID_REQUEST, raise_err
from store import db, new_entity
from validators import (
    body,
    get_issuer,
    get_underwriter,
    is_int,
    require_enum,
    require_fields,
)

bp = Blueprint("registry", __name__)


@bp.route("/muni/issuers", methods=["POST"])
def create_issuer():
    auth([ROLE_PLATFORM_ADMIN])
    payload = body()
    require_fields(
        payload, ["legal_name", "state_code", "issuer_type", "fiscal_year_end", "population"]
    )
    require_enum(payload, "issuer_type", ISSUER_TYPES)
    if not timeutil.valid_mm_dd(payload["fiscal_year_end"]):
        raise_err(ERR_INVALID_REQUEST, "fiscal_year_end must be MM-DD")
    if not is_int(payload["population"]):
        raise_err(ERR_INVALID_REQUEST, "population must be an integer")
    ent = new_entity()
    ent.update(
        legal_name=payload["legal_name"],
        state_code=payload["state_code"],
        issuer_type=payload["issuer_type"],
        fiscal_year_end=payload["fiscal_year_end"],
        population=payload["population"],
        credit_balance_cents=0,
        delinquent_flag=False,
    )
    db.issuers[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/issuers", methods=["GET"])
def list_issuers():
    authenticate()
    items = list(db.issuers.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [i for i in items if i["state_code"] == state_code]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/issuers/<issuer_id>", methods=["GET"])
def get_one_issuer(issuer_id):
    authenticate()
    return success_object(get_issuer(issuer_id))


@bp.route("/muni/issuers/<issuer_id>/notifications", methods=["GET"])
def list_notifications(issuer_id):
    authenticate()
    issuer = get_issuer(issuer_id)
    items = [n for n in db.notifications.values() if n["issuer_id"] == issuer["id"]]
    # Emission order: created_at ascending (insertion order tie-break).
    items.sort(key=lambda n: (n["created_at"], n["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/underwriters", methods=["POST"])
def create_underwriter():
    auth([ROLE_PLATFORM_ADMIN])
    payload = body()
    require_fields(payload, ["firm_name", "license_number"])
    ent = new_entity()
    ent.update(
        firm_name=payload["firm_name"],
        license_number=payload["license_number"],
    )
    db.underwriters[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/underwriters/<underwriter_id>", methods=["GET"])
def get_one_underwriter(underwriter_id):
    authenticate()
    return success_object(get_underwriter(underwriter_id))
