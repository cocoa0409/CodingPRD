"""FundingProgram and Apportionment endpoints (PRD §3.1)."""
from flask import Blueprint, request

from calculations import ACTIVITY_CODES, BASE_SHARE, FUNDING_PROGRAM_CODES
from db import STORE, new_id, now_bookkeeping
from errors import err
from helpers import (
    as_enum,
    as_int,
    as_str,
    get_body,
    paginate,
    query_int,
    req_field,
    resolve_body_fk,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from serializers import serialize_apportionment, serialize_funding_program

bp = Blueprint("funding", __name__)


@bp.route("/federal-aid/funding-programs", methods=["POST"])
@require_roles("PlatformAdmin")
def create_funding_program(user_id, user_role):
    body = get_body()
    code = as_enum(req_field(body, "code"), "code", FUNDING_PROGRAM_CODES)
    name = as_str(req_field(body, "name"), "name")
    eligible = req_field(body, "eligible_activity_codes")
    if not isinstance(eligible, list):
        raise err(
            "ERR_INVALID_REQUEST", "eligible_activity_codes must be an array"
        )
    for entry in eligible:
        if entry not in ACTIVITY_CODES:
            raise err(
                "ERR_INVALID_REQUEST",
                "eligible_activity_codes entries must be recognized activity codes",
            )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "code": code,
        "name": name,
        "eligible_activity_codes": list(eligible),
        "_base_share_dec": BASE_SHARE[code],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["funding_programs"][rec["id"]] = rec
    return success_object(serialize_funding_program(rec), status=201)


@bp.route("/federal-aid/apportionments", methods=["POST"])
@require_roles("FHWADivisionAdmin")
def create_apportionment(user_id, user_role):
    body = get_body()
    # Body FK resolution precedes body well-formedness on plain creates
    # (existence priority 3 before 4; PRD §2.9).
    if "funding_program_id" in body and body["funding_program_id"] is not None:
        resolve_body_fk("funding_programs", body["funding_program_id"], "funding_program_id")
    funding_program_id = as_str(req_field(body, "funding_program_id"), "funding_program_id")
    state_code = as_str(req_field(body, "state_code"), "state_code")
    ffy = as_int(req_field(body, "federal_fiscal_year"), "federal_fiscal_year")
    apportioned = as_int(req_field(body, "apportioned_cents"), "apportioned_cents")
    if apportioned < 0:
        raise err("ERR_INVALID_REQUEST", "apportioned_cents must be >= 0")
    # Uniqueness: one Apportionment per (program, state, FFY) triple.
    for a in STORE["apportionments"].values():
        if (
            a["funding_program_id"] == funding_program_id
            and a["state_code"] == state_code
            and a["federal_fiscal_year"] == ffy
        ):
            raise err(
                "ERR_DUPLICATE_APPORTIONMENT",
                "An Apportionment already exists for this (program, state, FFY) cell",
            )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "funding_program_id": funding_program_id,
        "state_code": state_code,
        "federal_fiscal_year": ffy,
        "apportioned_cents": apportioned,
        "obligated_cents": 0,
        "available_cents": apportioned,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["apportionments"][rec["id"]] = rec
    return success_object(serialize_apportionment(rec), status=201)


@bp.route("/federal-aid/apportionments/<apid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_apportionment(apid, user_id, user_role):
    rec = STORE["apportionments"].get(apid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Apportionment not found")
    return success_object(serialize_apportionment(rec))


@bp.route("/federal-aid/apportionments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_apportionments(user_id, user_role):
    fp_id = request.args.get("funding_program_id")
    state = request.args.get("state_code")
    ffy = query_int("federal_fiscal_year")
    items = list(STORE["apportionments"].values())
    if fp_id is not None:
        items = [a for a in items if a["funding_program_id"] == fp_id]
    if state is not None:
        items = [a for a in items if a["state_code"] == state]
    if ffy is not None:
        items = [a for a in items if a["federal_fiscal_year"] == ffy]
    items.sort(key=lambda a: a["created_at"])  # stable: insertion order breaks ties
    page, total, limit, offset = paginate(items)
    return success_list([serialize_apportionment(a) for a in page], total, limit, offset)
