"""Member endpoints + provisional risk scoring per PRD §3.2."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_input, ERR_MEMBER_NOT_FOUND,
                    ERR_PROGRAM_NOT_FOUND, ERR_CONTRACT_NOT_FOUND,
                    ERR_PCP_NOT_FOUND, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.calculations import (compute_provisional_burden,
                                   refresh_member_risk,
                                   CHRONIC_CONDITION_CODES)
from services.resources import base_fields
from services.validation import (get_json_body, require_string, require_int,
                                 require_list)

bp = Blueprint("members", __name__)

LIST_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "EngagementSpecialist", "PerformanceAnalyst"]
GET_ROLES = LIST_ROLES + ["Clinician"]


@bp.route("/members", methods=["POST"])
def create_member():
    require_roles(["PlatformAdmin", "EngagementSpecialist"])
    body = get_json_body()
    care_program_id = require_string(body, "care_program_id")
    payer_contract_id = require_string(body, "payer_contract_id")
    member_external_id = require_string(body, "member_external_id")
    full_name = require_string(body, "full_name")
    dob = require_string(body, "date_of_birth")
    address_zip = require_string(body, "address_zip")
    pcp_provider_id = require_string(body, "pcp_provider_id")
    codes = require_list(body, "chronic_condition_codes")
    prior_ed = require_int(body, "prior_ed_visits_12mo")
    prior_ip = require_int(body, "prior_inpatient_admits_12mo")

    # Body-supplied FK existence (validation ladder rung 4)
    if db.care_programs.get(care_program_id) is None:
        raise err_not_found(ERR_PROGRAM_NOT_FOUND, "CareProgram")
    if db.payer_contracts.get(payer_contract_id) is None:
        raise err_not_found(ERR_CONTRACT_NOT_FOUND, "PayerContract")
    if db.pcp_providers.get(pcp_provider_id) is None:
        raise err_not_found(ERR_PCP_NOT_FOUND, "PCPProvider")

    for code in codes:
        if code not in CHRONIC_CONDITION_CODES:
            raise err_input(ERR_INVALID_REQUEST,
                            "Invalid chronic condition code: %r" % code)

    m = base_fields()
    m.update({
        "care_program_id": care_program_id,
        "payer_contract_id": payer_contract_id,
        "member_external_id": member_external_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "address_zip": address_zip,
        "pcp_provider_id": pcp_provider_id,
        "chronic_condition_codes": list(codes),
        "prior_ed_visits_12mo": prior_ed,
        "prior_inpatient_admits_12mo": prior_ip,
        "burden_score_provisional": 0,
        "burden_score_final": None,
        "risk_tier": None,
    })
    m["burden_score_provisional"] = compute_provisional_burden(m)
    refresh_member_risk(m)
    db.members[m["id"]] = m
    return success_object(serializers.member(m), status=201)


@bp.route("/members", methods=["GET"])
def list_members():
    require_roles(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.members.values())
    cp = request.args.get("care_program_id")
    if cp:
        items = [m for m in items if m.get("care_program_id") == cp]
    pc = request.args.get("payer_contract_id")
    if pc:
        items = [m for m in items if m.get("payer_contract_id") == pc]
    pp = request.args.get("pcp_provider_id")
    if pp:
        items = [m for m in items if m.get("pcp_provider_id") == pp]
    rt = request.args.get("risk_tier")
    if rt:
        items = [m for m in items if m.get("risk_tier") == rt]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.member(m) for m in page],
                        limit, offset, total)


@bp.route("/members/<memberId>", methods=["GET"])
def get_member(memberId):
    require_roles(GET_ROLES)
    m = db.members.get(memberId)
    if m is None:
        raise err_not_found(ERR_MEMBER_NOT_FOUND, "Member")
    return success_object(serializers.member(m))
