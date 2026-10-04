"""Institution onboarding, directory, read, and versioned profile PATCH."""
from flask import Blueprint, request

import constants as C
from auth import authenticate, require_liaison_owns, require_role
from calculations import annual_dues_cents, outstanding_dues_cents
from db import STORE
from errors import ERR_INSTITUTION_NOT_FOUND, ERR_STALE_VERSION, raise_err
from helpers import (fetch_or_404, get_body, new_entity, opt_int, opt_string,
                     paginate, req_enum, req_enum_list, req_int, req_string,
                     serialize, touch)
from response import success_list, success_object

bp = Blueprint("institutions", __name__)

ALL_ROLES = ["CommissionAdmin", "CommissionStaff", "InstitutionLiaison", "PeerReviewer"]


def serialize_institution(inst):
    data = serialize(inst)
    data["outstanding_dues_cents"] = outstanding_dues_cents(inst)
    return data


@bp.post("/accreditation/institutions")
def create_institution():
    actor = authenticate()
    require_role(actor, ["CommissionAdmin"])
    body = get_body()
    legal_name = req_string(body, "legal_name")
    legal_status = req_enum(body, "legal_status", C.LEGAL_STATUSES)
    state_code = req_string(body, "state_code")
    fte_enrollment = req_int(body, "fte_enrollment", minimum=0)
    degree_levels = req_enum_list(body, "degree_levels_offered", C.DEGREE_LEVELS, non_empty=True)
    dues = annual_dues_cents(fte_enrollment, degree_levels)
    inst = new_entity({
        "legal_name": legal_name,
        "legal_status": legal_status,
        "state_code": state_code,
        "fte_enrollment": fte_enrollment,
        "degree_levels_offered": list(degree_levels),
        "distance_delivery_approved": False,
        "locations_count": 1,
        "accreditation_status": "PROSPECTIVE",
        "sanction_status": "NONE",
        "candidacy_pathway": None,
        "candidacy_started_at": None,
        "candidacy_expires_at": None,
        "_candidacy_expires_dt": None,
        "accredited_since": None,
        "last_reaffirmed_at": None,
        "current_annual_dues_cents": dues,
        "dues_paid_cents": dues,  # zero arrears at onboarding (PRD §3.1)
        "latest_cfi_value": None,
        "latest_cfi_band": None,
    })
    STORE.institutions[inst["id"]] = inst
    return success_object(serialize_institution(inst), code=201)


@bp.get("/accreditation/institutions")
def list_institutions():
    authenticate()  # all four roles may read
    items = list(STORE.institutions.values())
    for param in ("accreditation_status", "sanction_status", "legal_status"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i[param] == value]
    page, total, limit, offset = paginate_with(items)
    return success_list(page, total, limit, offset)


@bp.get("/accreditation/institutions/<inst_id>")
def get_institution(inst_id):
    actor = authenticate()
    if actor.role == "InstitutionLiaison":
        require_liaison_owns(actor, inst_id)
    inst = fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    return success_object(serialize_institution(inst))


@bp.patch("/accreditation/institutions/<inst_id>")
def patch_institution(inst_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    inst = fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    body = get_body()
    expected = req_int(body, "expected_institution_version")
    if expected != inst["version"]:
        raise_err(ERR_STALE_VERSION, "expected_institution_version does not match current version")
    legal_name = opt_string(body, "legal_name")
    legal_status = opt_enum_local(body, "legal_status", C.LEGAL_STATUSES)
    state_code = opt_string(body, "state_code")
    fte = opt_int(body, "fte_enrollment", minimum=0)
    levels = None
    if "degree_levels_offered" in body and body["degree_levels_offered"] is not None:
        levels = req_enum_list(body, "degree_levels_offered", C.DEGREE_LEVELS, non_empty=True)
    dues_paid = opt_int(body, "dues_paid_cents", minimum=0)
    recompute = False
    if legal_name is not None:
        inst["legal_name"] = legal_name
    if legal_status is not None:
        inst["legal_status"] = legal_status
    if state_code is not None:
        inst["state_code"] = state_code
    if fte is not None:
        inst["fte_enrollment"] = fte
        recompute = True
    if levels is not None:
        inst["degree_levels_offered"] = list(levels)
        recompute = True
    if dues_paid is not None:
        inst["dues_paid_cents"] = dues_paid
    if recompute:
        inst["current_annual_dues_cents"] = annual_dues_cents(
            inst["fte_enrollment"], inst["degree_levels_offered"])
    touch(inst)
    return success_object(serialize_institution(inst))


def opt_enum_local(body, field, allowed):
    if field not in body or body[field] is None:
        return None
    return req_enum(body, field, allowed)


def paginate_with(items):
    # Shared shape with helpers.paginate but keeps institution serialization.
    from helpers import parse_pagination
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = [serialize_institution(e) for e in ordered[offset:offset + limit]]
    return page, total, limit, offset
