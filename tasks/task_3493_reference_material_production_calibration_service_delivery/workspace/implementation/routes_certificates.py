"""Certificates of analysis: OCC-guarded DRAFT creation (computes the value
assignment and the uncertainty budget) and the publish/withdraw transitions
with their lot cascades and the supersede rule."""

from flask import Blueprint

from db import STORE
from domain import bump, make_certificate, ser_certificate
from engine import (
    accepted_methods,
    compute_certificate_numbers,
    publish_certificate,
    withdraw_certificate,
)
from util import (
    ERR_INSUFFICIENT_INDEPENDENT_METHODS,
    ERR_INVALID_CERTIFICATE_STATE,
    ERR_INVALID_LOT_STATE,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_STALE_VERSION,
    auth_context,
    body,
    fail,
    get_path,
    get_ref,
    ok_object,
    require_role,
    require_target_role,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("certificates", __name__)

CERT_STATES = ["DRAFT", "PUBLISHED", "EXPIRED", "SUPERSEDED", "WITHDRAWN"]
CERT_TARGET_ROLES = {
    "PUBLISHED": ["CertificationOfficer"],
    "WITHDRAWN": ["CertificationOfficer"],
}

CERTIFIABLE_LOT_STATES = (
    "VALUE_ASSIGNMENT",
    "CERTIFIED",
    "IN_DISTRIBUTION",
    "DISTRIBUTION_HOLD",
)


def _validate_components(b):
    if "uncertainty_components" not in b or b["uncertainty_components"] is None:
        fail(ERR_INVALID_REQUEST, 400, "missing required field: uncertainty_components")
    comps = b["uncertainty_components"]
    if not isinstance(comps, list):
        fail(ERR_INVALID_REQUEST, 400, "uncertainty_components must be a list")
    for item in comps:
        if not isinstance(item, dict):
            fail(ERR_INVALID_REQUEST, 400, "each uncertainty component must be an object")
        label = item.get("label")
        std = item.get("std_uncertainty")
        if not isinstance(label, str) or label == "":
            fail(ERR_INVALID_REQUEST, 400, "uncertainty component label must be a string")
        if isinstance(std, bool) or not isinstance(std, (int, float)) or not (std > 0):
            fail(
                ERR_INVALID_REQUEST,
                400,
                "uncertainty component std_uncertainty must be strictly positive",
            )
    return [{"label": c["label"], "std_uncertainty": c["std_uncertainty"]} for c in comps]


@bp.route("/metrology/certificates", methods=["POST"])
def create_certificate():
    _uid, role = auth_context()
    require_role(role, ["CertificationOfficer"])
    b = body()
    data = {
        "lot_id": v_str(b, "lot_id"),
        "certificate_code": v_str(b, "certificate_code"),
        "value_assignment_variant": v_enum(
            b, "value_assignment_variant", ("WEIGHTED_MEAN", "UNWEIGHTED_MEAN")
        ),
        "uncertainty_components": _validate_components(b),
        "validity_days": v_int(b, "validity_days", minv=1),
    }
    expected_lot_version = v_int(b, "expected_lot_version")
    lot = get_ref(STORE["lots"], data["lot_id"], "material lot")
    if expected_lot_version != lot["version"]:
        fail(
            ERR_STALE_VERSION,
            412,
            "expected_lot_version does not match the current lot version",
        )
    if lot["status"] not in CERTIFIABLE_LOT_STATES:
        fail(
            ERR_INVALID_LOT_STATE,
            409,
            "lot status {} does not permit certificate creation".format(
                lot["status"]
            ),
        )
    if len(accepted_methods(lot["id"])) < 2:
        fail(
            ERR_INSUFFICIENT_INDEPENDENT_METHODS,
            422,
            "at least two ACCEPTED methods are required",
        )
    numbers = compute_certificate_numbers(
        lot, data["value_assignment_variant"], data["uncertainty_components"]
    )
    rec = make_certificate(data, numbers)
    STORE["certificates"][rec["id"]] = rec
    if lot["status"] == "VALUE_ASSIGNMENT":
        lot["status"] = "CERTIFICATION_PENDING"
        bump(lot)
    return ok_object(ser_certificate(rec), 201)


@bp.route("/metrology/certificates/<cid>/transitions", methods=["POST"])
def certificate_transition(cid):
    uid, role = auth_context()
    require_role(role, ["CertificationOfficer"])
    b = body()
    require_target_role(role, b.get("to"), CERT_TARGET_ROLES)
    to = v_enum(b, "to", CERT_STATES)
    cert = get_path(STORE["certificates"], cid, "certificate")

    if to == "PUBLISHED":
        if cert["status"] != "DRAFT":
            fail(
                ERR_INVALID_CERTIFICATE_STATE,
                409,
                "only a DRAFT certificate may be published",
            )
        for m in accepted_methods(cert["lot_id"]):
            if m["analyst_user_id"] == uid:
                fail(
                    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                    403,
                    "the publisher must not be an analyst of the lot's methods",
                )
        publish_certificate(cert, uid)
        return ok_object(ser_certificate(cert), 200)

    if to == "WITHDRAWN":
        if cert["status"] not in ("DRAFT", "PUBLISHED"):
            fail(
                ERR_INVALID_CERTIFICATE_STATE,
                409,
                "only a DRAFT or PUBLISHED certificate may be withdrawn",
            )
        withdraw_certificate(cert)
        return ok_object(ser_certificate(cert), 200)

    fail(
        ERR_INVALID_CERTIFICATE_STATE,
        409,
        "no declared certificate transition from {} to {}".format(
            cert["status"], to
        ),
    )
