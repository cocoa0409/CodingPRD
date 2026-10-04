"""Regulatory license routes: file, list, read, transition (grant/deny/revoke)."""
from flask import Blueprint, g, request

from calc import GRANT_THRESHOLD, composite_score
from cascade import revoke_cascade
from envelope import success, success_list
from errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_FOUND,
    ERR_LICENSE_SCORE_TOO_LOW,
    ERR_MISSION_NOT_FOUND,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unprocessable,
)
from middleware import require_roles
from serialize import ser_license
from store import bump, db, new_entity, now
from validate import (
    as_dt,
    as_enum,
    as_int_range,
    as_str,
    body_json,
    opt_enum_filter,
    opt_field,
    paginate,
    parse_pagination,
    req_field,
)

bp = Blueprint("licenses", __name__)

SUBJECT_TYPES = {"MISSION", "CUSTOMER"}
KINDS = {"LAUNCH_AUTHORIZATION", "PAYLOAD_OPERATOR"}
LICENSE_STATUSES = {"SUBMITTED", "GRANTED", "DENIED", "REVOKED", "EXPIRED"}
TRANSITION_TARGETS = {"GRANTED", "DENIED", "REVOKED"}


@bp.post("/rideshare/licenses")
@require_roles("MissionOps", "Customer")
def create_license():
    body = body_json()
    subject_type = as_enum(req_field(body, "subject_type"), "subject_type", SUBJECT_TYPES)
    kind = as_enum(req_field(body, "kind"), "kind", KINDS)
    valid_until = as_dt(req_field(body, "valid_until"), "valid_until")
    debris = as_int_range(req_field(body, "debris_score"), "debris_score", 0, 100)
    spectrum = as_int_range(req_field(body, "spectrum_score"), "spectrum_score", 0, 100)
    history = as_int_range(
        req_field(body, "operator_history_score"), "operator_history_score", 0, 100
    )
    mission_id = opt_field(body, "mission_id", None)
    customer_id = opt_field(body, "customer_id", None)
    if mission_id is not None:
        mission_id = as_str(mission_id, "mission_id")
    if customer_id is not None:
        customer_id = as_str(customer_id, "customer_id")

    # subject/kind coherence with the matching FK present (request shape)
    if subject_type == "MISSION":
        if kind != "LAUNCH_AUTHORIZATION":
            raise bad_request("MISSION subjects require kind LAUNCH_AUTHORIZATION")
        if mission_id is None:
            raise bad_request("MISSION subjects require mission_id")
    else:  # CUSTOMER
        if kind != "PAYLOAD_OPERATOR":
            raise bad_request("CUSTOMER subjects require kind PAYLOAD_OPERATOR")
        if customer_id is None:
            raise bad_request("CUSTOMER subjects require customer_id")
    if not valid_until > now():
        raise bad_request("valid_until must be strictly in the future")

    # role-subject binding: launch authorizations are filed by MissionOps;
    # payload-operator licenses by the Customer itself (X-User-ID == customer_id)
    if subject_type == "MISSION" and g.user_role != "MissionOps":
        raise forbidden("MISSION licenses are filed by MissionOps")
    if subject_type == "CUSTOMER" and (
        g.user_role != "Customer" or g.user_id != customer_id
    ):
        raise forbidden("a customer may file PAYLOAD_OPERATOR licenses only for itself")

    # existence of the referenced subject
    if subject_type == "MISSION":
        if mission_id not in db["missions"]:
            raise not_found(ERR_MISSION_NOT_FOUND, f"mission {mission_id} not found")
    else:
        if customer_id not in db["customers"]:
            raise not_found(
                ERR_CUSTOMER_NOT_FOUND, f"customer {customer_id} not found"
            )

    lic = new_entity()
    lic.update(
        {
            "subject_type": subject_type,
            "mission_id": mission_id if subject_type == "MISSION" else None,
            "customer_id": customer_id if subject_type == "CUSTOMER" else None,
            "kind": kind,
            "debris_score": debris,
            "spectrum_score": spectrum,
            "operator_history_score": history,
            "composite_score": composite_score(debris, spectrum, history),
            "valid_until": valid_until,
            "status": "SUBMITTED",
        }
    )
    db["licenses"][lic["id"]] = lic
    return success(ser_license(lic), 201)


@bp.get("/rideshare/licenses")
@require_roles("Regulator", "MissionOps", "Customer")
def list_licenses():
    status = opt_enum_filter(request.args, "status", LICENSE_STATUSES)
    kind = opt_enum_filter(request.args, "kind", KINDS)
    mission_id = request.args.get("mission_id")
    customer_id = request.args.get("customer_id")
    limit, offset = parse_pagination(request.args)

    if g.user_role == "Customer":
        customer_id = g.user_id  # auto-filter to the caller's own filings
    rows = list(db["licenses"].values())
    if customer_id is not None:
        rows = [l for l in rows if l["customer_id"] == customer_id]
    if mission_id is not None:
        rows = [l for l in rows if l["mission_id"] == mission_id]
    if kind is not None:
        rows = [l for l in rows if l["kind"] == kind]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_license(l) for l in page], limit, offset, total)


@bp.get("/rideshare/licenses/<lid>")
@require_roles("Regulator", "MissionOps", "Customer")
def get_license(lid):
    lic = db["licenses"].get(lid)
    if g.user_role == "Customer":
        # customer scoping: another customer's license is invisible
        if lic is None or lic["customer_id"] != g.user_id:
            raise not_found(ERR_CONTRACT_NOT_FOUND, f"license {lid} not found")
    if lic is None:
        raise not_found(ERR_LICENSE_NOT_FOUND, f"license {lid} not found")
    return success(ser_license(lic))


@bp.post("/rideshare/licenses/<lid>/transition")
@require_roles("Regulator")
def transition_license(lid):
    body = body_json()
    to_state = as_enum(req_field(body, "to_state"), "to_state", TRANSITION_TARGETS)
    lic = db["licenses"].get(lid)
    if lic is None:
        raise not_found(ERR_LICENSE_NOT_FOUND, f"license {lid} not found")

    allowed = (
        (lic["status"] == "SUBMITTED" and to_state in ("GRANTED", "DENIED"))
        or (lic["status"] == "GRANTED" and to_state == "REVOKED")
    )
    if not allowed:
        raise conflict(
            ERR_INVALID_STATE,
            f"cannot move license from {lic['status']} to {to_state}",
        )
    if to_state == "GRANTED" and lic["composite_score"] < GRANT_THRESHOLD:
        raise unprocessable(
            ERR_LICENSE_SCORE_TOO_LOW,
            f"composite_score {lic['composite_score']} < {GRANT_THRESHOLD}",
        )
    lic["status"] = to_state
    if to_state == "REVOKED":
        revoke_cascade(lic)
    bump(lic)
    return success(ser_license(lic))
