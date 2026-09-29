"""Personnel registry and the logical shop clock."""

import re

from flask import Blueprint

import db
import response
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import derive

bp = Blueprint("personnel", __name__)

ROLE_CODES = ("DESIGN_ENGINEER", "WELDING_ENGINEER", "QC_INSPECTOR",
              "AUTHORIZED_INSPECTOR")
_INITIALS_RE = re.compile(r"^[A-Z]{2,4}$")


@bp.post("/personnel")
@guard(["ShopAdmin"], resolve_identity=False)
def create_personnel(ctx):
    body = validation.body()
    full_name = validation.string_field(body, "full_name")
    role_code = validation.enum_field(body, "role_code", ROLE_CODES)
    stamp_initials = validation.string_field(body, "stamp_initials")
    if not _INITIALS_RE.match(stamp_initials):
        fail("ERR_INVALID_REQUEST", "Field 'stamp_initials' must be 2 to 4 uppercase letters.")
    ai_agency = validation.string_field(body, "ai_agency", required=False)
    if role_code == "AUTHORIZED_INSPECTOR":
        if ai_agency is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'ai_agency' is required for an AUTHORIZED_INSPECTOR.")
    elif ai_agency is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'ai_agency' must be omitted or null for this role_code.")

    for person in db.all_of("personnel"):
        if person["stamp_initials"] == stamp_initials:
            fail("ERR_DUPLICATE_STAMP_INITIALS",
                 "Stamp initials '%s' are already registered." % stamp_initials)

    record = db.insert("personnel", {
        "full_name": full_name,
        "role_code": role_code,
        "stamp_initials": stamp_initials,
        "ai_agency": ai_agency,
    }, versioned=False)
    return common.created("personnel", record)


@bp.get("/personnel/<personnel_id>")
@guard(ALL_ROLES)
def get_personnel(ctx, personnel_id):
    record = common.must_exist("personnel", personnel_id)
    return common.one("personnel", record)


@bp.get("/personnel")
@guard(ALL_ROLES)
def list_personnel(ctx):
    return common.listing("personnel", ["role_code"])


@bp.post("/_clock/set_current_utc")
@guard(["ShopAdmin"], resolve_identity=False)
def set_clock(ctx):
    body = validation.body()
    current_utc = validation.instant_field(body, "current_utc")
    db.clock_set(current_utc)

    qualifications_recomputed = 0
    for qualification in db.all_of("qualifications"):
        if derive.sync_qualification(qualification):
            qualifications_recomputed += 1

    certificates_recomputed = 0
    for certificate in db.all_of("certificates"):
        if derive.sync_certificate(certificate):
            certificates_recomputed += 1
        derive.sync_certificate_reports(certificate)

    return response.object_response({
        "current_utc": db.now_iso(),
        "welder_qualifications_recomputed": qualifications_recomputed,
        "certificates_recomputed": certificates_recomputed,
    })
