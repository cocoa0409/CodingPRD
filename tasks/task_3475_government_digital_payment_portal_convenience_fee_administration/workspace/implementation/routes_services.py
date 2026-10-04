"""Service catalog (PRD section 3.2): draft / update (OCC) / activate /
deactivate with quote-voiding cascade."""
from flask import Blueprint, request

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import (
    as_enum,
    as_int,
    as_method_set,
    as_str,
    body,
    opt_field,
    req_field,
)

bp = Blueprint("services", __name__)

FEE_MODELS = {"CONVENIENCE_FEE", "ABSORBED"}
SERVICE_READ_ROLES = {"PlatformAdmin", "AgencyAdmin", "TreasuryOfficer", "ComplianceAuditor", "Payer"}


@bp.route("/portal/services", methods=["POST"])
def create_service():
    caller({"AgencyAdmin"})
    data = body()
    agency_id = as_str(req_field(data, "agency_id"), "agency_id")
    service_code = as_str(req_field(data, "service_code"), "service_code")
    name = as_str(req_field(data, "name"), "name")
    fee_model = opt_field(data, "fee_model")
    allowed_methods = as_method_set(req_field(data, "allowed_methods"), "allowed_methods")
    min_amount = as_int(req_field(data, "min_amount_cents"), "min_amount_cents")
    max_amount = as_int(req_field(data, "max_amount_cents"), "max_amount_cents")
    gl_code = as_str(req_field(data, "gl_code"), "gl_code")
    # priority 3: body foreign key
    agency = helpers.get_agency(agency_id)
    if fee_model is None:
        fee_model = agency["default_fee_model"]
    else:
        fee_model = as_enum(fee_model, "fee_model", FEE_MODELS)
    # priority 8: service_code unique per agency among non-DEACTIVATED
    for svc in store.services.values():
        if (
            svc["agency_id"] == agency_id
            and svc["service_code"] == service_code
            and svc["status"] != "DEACTIVATED"
        ):
            raise_err(
                "ERR_DUPLICATE_SERVICE_CODE",
                409,
                "service_code %s is already used by a live service of this agency"
                % service_code,
            )
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "agency_id": agency_id,
        "service_code": service_code,
        "name": name,
        "fee_model": fee_model,
        "allowed_methods": allowed_methods,
        "min_amount_cents": min_amount,
        "max_amount_cents": max_amount,
        "gl_code": gl_code,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.services[rec["id"]] = rec
    return envelope.obj(serialize.service(rec), 201)


@bp.route("/portal/services/<rid>", methods=["GET"])
def get_service(rid):
    caller(SERVICE_READ_ROLES)
    return envelope.obj(serialize.service(helpers.get_service(rid)))


@bp.route("/portal/agencies/<rid>/services", methods=["GET"])
def list_services(rid):
    caller(SERVICE_READ_ROLES)
    helpers.get_agency(rid)
    status = request.args.get("status")
    items = [s for s in store.services.values() if s["agency_id"] == rid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["created_seq"]))
    return envelope.page([serialize.service(s) for s in items], request.args)


@bp.route("/portal/services/<rid>", methods=["PUT"])
def update_service(rid):
    caller({"AgencyAdmin"})
    svc = helpers.get_service(rid)
    data = body()
    expected = as_int(
        req_field(data, "expected_service_version"), "expected_service_version"
    )
    name = opt_field(data, "name")
    min_amount = opt_field(data, "min_amount_cents")
    max_amount = opt_field(data, "max_amount_cents")
    allowed_methods = opt_field(data, "allowed_methods")
    if name is not None:
        name = as_str(name, "name")
    if min_amount is not None:
        min_amount = as_int(min_amount, "min_amount_cents")
    if max_amount is not None:
        max_amount = as_int(max_amount, "max_amount_cents")
    if allowed_methods is not None:
        allowed_methods = as_method_set(allowed_methods, "allowed_methods")
    # priority 4: OCC on the service's own version, before all state checks
    if expected != svc["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            412,
            "expected_service_version does not match the service's current version",
        )
    if name is not None:
        svc["name"] = name
    if min_amount is not None:
        svc["min_amount_cents"] = min_amount
    if max_amount is not None:
        svc["max_amount_cents"] = max_amount
    if allowed_methods is not None:
        svc["allowed_methods"] = allowed_methods
    # every update bumps the version, invalidating quotes pinned to earlier
    helpers.touch(svc)
    return envelope.obj(serialize.service(svc))


@bp.route("/portal/services/<rid>/activate", methods=["POST"])
def activate_service(rid):
    caller({"PlatformAdmin"})
    svc = helpers.get_service(rid)
    # priority 5: state permission
    if svc["status"] != "DRAFT":
        invalid_state("Only a DRAFT service can be activated")
    agency = helpers.get_agency(svc["agency_id"])
    if agency["status"] != "ACTIVE":
        raise_err(
            "ERR_AGENCY_NOT_ACTIVE",
            409,
            "Service activation requires the agency in ACTIVE status",
        )
    # priority 6: CONVENIENCE_FEE services need in-effect statutory coverage
    if svc["fee_model"] == "CONVENIENCE_FEE" and helpers.covering_authorization(rid) is None:
        raise_err(
            "ERR_NO_STATUTORY_COVERAGE",
            422,
            "No in-effect APPROVED statutory authorization covers this service",
        )
    svc["status"] = "ACTIVE"
    helpers.touch(svc)
    return envelope.obj(serialize.service(svc))


@bp.route("/portal/services/<rid>/deactivate", methods=["POST"])
def deactivate_service(rid):
    caller({"PlatformAdmin"})
    svc = helpers.get_service(rid)
    if svc["status"] not in ("DRAFT", "ACTIVE"):
        invalid_state("Service is already DEACTIVATED")
    helpers.deactivate_service(svc)
    return envelope.obj(serialize.service(svc))
