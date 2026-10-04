"""Producer registry and producer licensing (PRD 3.6)."""

from flask import Blueprint

from auth import (
    authenticate,
    require_role,
    forbidden,
    ALL_ROLES,
    ROLE_ASSOCIATION_STAFF,
    ROLE_STATE_REGULATOR,
    ROLE_PRODUCER_USER,
)
from db import store, base_record, touch, state_by_code
from errors import ApiError
from serialize import serialize_producer, serialize_license
from util import get_body, req_str, req_enum, req_ts, ok_object, paginate

bp = Blueprint("licensing", __name__)

LICENSE_CLASSES = {"LIFE", "HEALTH", "PROPERTY_CASUALTY", "PERSONAL_LINES"}


def get_producer_or_404(producer_id):
    p = store.producers.get(producer_id)
    if p is None:
        raise ApiError("ERR_PRODUCER_NOT_FOUND", "Producer not found: %s" % producer_id, 404)
    return p


def get_license_or_404(license_id):
    lic = store.licenses.get(license_id)
    if lic is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND", "License not found: %s" % license_id, 404)
    return lic


@bp.post("/naic/producers")
def create_producer():
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    body = get_body()
    npn = req_str(body, "npn")
    full_name = req_str(body, "full_name")
    # home_state_code is informational only and references nothing (PRD 3.6).
    home_state_code = req_str(body, "home_state_code")
    for p in store.producers.values():
        if p["npn"] == npn:
            raise ApiError("ERR_DUPLICATE_NPN", "Producer npn already exists: %s" % npn, 409)
    rec = base_record()
    rec.update({
        "npn": npn,
        "full_name": full_name,
        "home_state_code": home_state_code,
        "active_license_count": 0,
    })
    store.producers[rec["id"]] = rec
    return ok_object(serialize_producer(rec), 201)


@bp.get("/naic/producers/<producer_id>")
def read_producer(producer_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    return ok_object(serialize_producer(get_producer_or_404(producer_id)), 200)


@bp.post("/naic/licenses")
def apply_license():
    principal = authenticate()
    require_role(principal, {ROLE_PRODUCER_USER})
    body = get_body()
    # Stage 2 ownership (body-derived): producer_id must equal X-User-ID.
    supplied = body.get("producer_id")
    if supplied is not None and supplied != principal.user_id:
        forbidden("producer_id must equal the acting producer's id")
    # Stage 4 body reference: state_code must name a registered state.
    if body.get("state_code") is not None:
        code = body["state_code"]
        found = isinstance(code, str) and state_by_code(code) is not None
        if not found:
            raise ApiError(
                "ERR_STATE_NOT_FOUND", "state_code does not match a registered state", 404
            )
    req_str(body, "producer_id")
    state_code = req_str(body, "state_code")
    license_class = req_enum(body, "license_class", LICENSE_CLASSES)
    effective_from = req_ts(body, "effective_from")
    valid_until = req_ts(body, "valid_until")
    if valid_until <= effective_from:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "valid_until must be strictly after effective_from",
            400,
        )
    # Closed-interval overlap for the same (producer, state, class) in
    # APPLIED/ISSUED; touching endpoints count as overlapping.
    for lic in store.licenses.values():
        if (
            lic["producer_id"] == principal.user_id
            and lic["state_code"] == state_code
            and lic["license_class"] == license_class
            and lic["status"] in ("APPLIED", "ISSUED")
        ):
            if effective_from <= lic["valid_until"] and lic["effective_from"] <= valid_until:
                raise ApiError(
                    "ERR_LICENSE_WINDOW_OVERLAP",
                    "License window intersects an existing APPLIED/ISSUED license",
                    409,
                )
    rec = base_record()
    rec.update({
        "producer_id": principal.user_id,
        "state_code": state_code,
        "license_class": license_class,
        "effective_from": effective_from,
        "valid_until": valid_until,
        "status": "APPLIED",
    })
    store.licenses[rec["id"]] = rec
    return ok_object(serialize_license(rec), 201)


@bp.get("/naic/producers/<producer_id>/licenses")
def list_producer_licenses(producer_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    producer = get_producer_or_404(producer_id)
    lics = [l for l in store.licenses.values() if l["producer_id"] == producer["id"]]
    return paginate(lics, serialize_license)


@bp.post("/naic/licenses/<license_id>/issue")
def issue_license(license_id):
    principal = authenticate()
    require_role(principal, {ROLE_STATE_REGULATOR})
    lic = get_license_or_404(license_id)
    if principal.entity["code"] != lic["state_code"]:
        forbidden("The acting regulator's state must match the license's state_code")
    # PRD 3.6 order: APPLIED gate first, then the suspended-state gate.
    if lic["status"] != "APPLIED":
        raise ApiError(
            "ERR_LICENSE_NOT_APPLIED", "License %s is not APPLIED" % license_id, 409
        )
    state = state_by_code(lic["state_code"])
    if state is not None and state["accreditation_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_STATE_SUSPENDED",
            "The licensing state is SUSPENDED",
            422,
        )
    lic["status"] = "ISSUED"
    touch(lic)
    producer = store.producers.get(lic["producer_id"])
    if producer is not None:
        producer["active_license_count"] += 1
    return ok_object(serialize_license(lic), 200)


@bp.post("/naic/licenses/<license_id>/revoke")
def revoke_license(license_id):
    principal = authenticate()
    require_role(principal, {ROLE_STATE_REGULATOR})
    lic = get_license_or_404(license_id)
    if principal.entity["code"] != lic["state_code"]:
        forbidden("The acting regulator's state must match the license's state_code")
    if lic["status"] != "ISSUED":
        raise ApiError(
            "ERR_LICENSE_NOT_ISSUED", "License %s is not ISSUED" % license_id, 409
        )
    lic["status"] = "REVOKED"
    touch(lic)
    producer = store.producers.get(lic["producer_id"])
    if producer is not None:
        producer["active_license_count"] -= 1
    return ok_object(serialize_license(lic), 200)
