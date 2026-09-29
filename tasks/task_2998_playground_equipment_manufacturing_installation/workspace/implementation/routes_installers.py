"""The certified installer network and its membership axis (PRD section 3.8)."""

from flask import Blueprint

import calc
import cascades
import validate as v
from auth import authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import public, public_list, store

bp = Blueprint("installers", __name__)

INSTALLER_READ_ROLES = [
    "ManufacturerAdmin",
    "ComplianceOfficer",
    "DesignConsultant",
    "SafetyAuditor",
    "InstallerOperator",
]
CERTIFICATION_LEVELS = ("APPRENTICE", "CERTIFIED", "MASTER")
MEMBERSHIP_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED")
MEMBERSHIP_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "REVOKED"),
    ("SUSPENDED", "REVOKED"),
}


@bp.route("/playground/installers", methods=["POST"])
def create_installer():
    authenticate(["ManufacturerAdmin"])
    body = v.raw_body()
    company_name = v.string(body, "company_name", min_len=1, max_len=120)
    level = v.enum(body, "certification_level", CERTIFICATION_LEVELS)
    categories = v.enum_array(body, "certified_categories", calc.CATEGORIES, 1, 5)
    capacity = v.integer(body, "crew_capacity_per_day", minimum=1, maximum=200)
    expires_on = v.date_field(body, "certification_expires_on")
    region = v.string(body, "region_code", min_len=2, max_len=2, pattern=r"^[A-Z]{2}$",
                      pattern_hint="exactly two uppercase letters")

    for row in store.all("installer"):
        if row["company_name"] == company_name:
            raise v.bad_request("Company '{}' is already in the network.".format(company_name))

    row = store.insert("installer", {
        "company_name": company_name,
        "certification_level": level,
        "certified_categories": categories,
        "crew_capacity_per_day": capacity,
        "certification_expires_on": expires_on.isoformat(),
        "region_code": region,
        "status": "ACTIVE",
        "open_audit_failures": 0,
        "committed_crew_days": 0,
    })
    return object_response(public(row), 201)


@bp.route("/playground/installers", methods=["GET"])
def list_installers():
    authenticate(INSTALLER_READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("installer"), {
        "status": "status",
        "region_code": "region_code",
        "certification_level": "certification_level",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/installers/<installer_id>", methods=["GET"])
def get_installer(installer_id):
    authenticate(INSTALLER_READ_ROLES)
    return object_response(public(store.require("installer", installer_id)))


@bp.route("/playground/installers/<installer_id>/status", methods=["POST"])
def move_installer_status(installer_id):
    authenticate(["ManufacturerAdmin"])
    installer = store.require("installer", installer_id)
    body = v.raw_body()
    target = v.enum(body, "status", MEMBERSHIP_STATUSES)

    if (installer["status"], target) not in MEMBERSHIP_TRANSITIONS:
        raise ApiError("ERR_INSTALLER_INVALID_STATE")

    if target == "ACTIVE":
        if installer["open_audit_failures"] != 0:
            raise ApiError("ERR_AUDIT_FAILURES_OPEN")
        installer["status"] = "ACTIVE"
        store.touch(installer)
    elif target == "SUSPENDED":
        # An administrative suspension deliberately keeps existing bookings.
        installer["status"] = "SUSPENDED"
        store.touch(installer)
    else:
        installer["status"] = "REVOKED"
        cascades.cancel_installer_jobs(installer)
        store.touch(installer)

    return object_response(public(installer))
