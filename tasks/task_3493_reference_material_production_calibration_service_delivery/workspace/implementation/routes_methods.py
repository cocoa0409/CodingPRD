"""Value-assignment methods: submit (Metrologist), accept/reject
(CertificationOfficer), resubmit (owning Metrologist)."""

from flask import Blueprint

from db import STORE
from domain import bump, make_method, ser_method
from util import (
    ERR_DUPLICATE_ANALYST_METHOD,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_LOT_STATE,
    ERR_INVALID_METHOD_STATE,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    auth_context,
    body,
    fail,
    get_path,
    get_ref,
    ok_object,
    require_role,
    require_target_role,
    v_enum,
    v_num,
    v_str,
)

bp = Blueprint("methods", __name__)

METHOD_STATES = ["DATA_SUBMITTED", "ACCEPTED", "REJECTED"]

METHOD_TARGET_ROLES = {
    "ACCEPTED": ["CertificationOfficer"],
    "REJECTED": ["CertificationOfficer"],
    "DATA_SUBMITTED": ["Metrologist"],
}

# lot states in which an ACCEPT adjudication is lawful
ACCEPTABLE_LOT_STATES = (
    "VALUE_ASSIGNMENT",
    "CERTIFICATION_PENDING",
    "CERTIFIED",
    "IN_DISTRIBUTION",
    "DISTRIBUTION_HOLD",
)


@bp.route("/metrology/value-assignment-methods", methods=["POST"])
def create_method():
    uid, role = auth_context()
    require_role(role, ["Metrologist"])
    b = body()
    data = {
        "lot_id": v_str(b, "lot_id"),
        "method_code": v_str(b, "method_code"),
        "method_mean": v_num(b, "method_mean", positive=True),
        "method_std_uncertainty": v_num(b, "method_std_uncertainty", positive=True),
    }
    lot = get_ref(STORE["lots"], data["lot_id"], "material lot")
    if lot["status"] != "VALUE_ASSIGNMENT":
        fail(
            ERR_INVALID_LOT_STATE,
            409,
            "methods may only be submitted while the lot is in VALUE_ASSIGNMENT",
        )
    for m in STORE["methods"].values():
        if (
            m["lot_id"] == lot["id"]
            and m["analyst_user_id"] == uid
            and m["status"] in ("DATA_SUBMITTED", "ACCEPTED")
        ):
            fail(
                ERR_DUPLICATE_ANALYST_METHOD,
                409,
                "analyst already holds an open method on this lot",
            )
    rec = make_method(data, uid)
    STORE["methods"][rec["id"]] = rec
    return ok_object(ser_method(rec), 201)


@bp.route("/metrology/value-assignment-methods/<mid>/transitions", methods=["POST"])
def method_transition(mid):
    uid, role = auth_context()
    require_role(role, ["CertificationOfficer", "Metrologist"])
    b = body()
    require_target_role(role, b.get("to"), METHOD_TARGET_ROLES)
    to = v_enum(b, "to", METHOD_STATES)

    payload = {}
    if to == "DATA_SUBMITTED":
        payload["method_mean"] = v_num(b, "method_mean", positive=True)
        payload["method_std_uncertainty"] = v_num(
            b, "method_std_uncertainty", positive=True
        )
    rejection_reason = b.get("rejection_reason")
    if rejection_reason is not None and not isinstance(rejection_reason, str):
        fail("ERR_INVALID_REQUEST", 400, "rejection_reason must be a string")

    method = get_path(STORE["methods"], mid, "value-assignment method")

    if to == "DATA_SUBMITTED":
        # ownership: only the original analyst may resubmit (stage 4.6)
        if method["analyst_user_id"] != uid:
            fail(
                ERR_FORBIDDEN_OWNERSHIP,
                403,
                "only the method's analyst may resubmit it",
            )
        if method["status"] != "REJECTED":
            fail(
                ERR_INVALID_METHOD_STATE,
                409,
                "only a REJECTED method may be resubmitted",
            )
        method["method_mean"] = payload["method_mean"]
        method["method_std_uncertainty"] = payload["method_std_uncertainty"]
        method["rejection_reason"] = None
        method["status"] = "DATA_SUBMITTED"
        bump(method)
        return ok_object(ser_method(method), 200)

    if method["status"] != "DATA_SUBMITTED":
        fail(
            ERR_INVALID_METHOD_STATE,
            409,
            "method status {} does not permit adjudication".format(
                method["status"]
            ),
        )

    if to == "ACCEPTED":
        lot = STORE["lots"].get(method["lot_id"])
        if lot is not None and lot["status"] not in ACCEPTABLE_LOT_STATES:
            fail(
                ERR_INVALID_LOT_STATE,
                409,
                "lot status {} does not permit method acceptance".format(
                    lot["status"]
                ),
            )
        if method["analyst_user_id"] == uid:
            fail(
                ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                403,
                "the method's analyst may not accept it",
            )
        method["status"] = "ACCEPTED"
        bump(method)
        return ok_object(ser_method(method), 200)

    # to == "REJECTED"
    if method["analyst_user_id"] == uid:
        fail(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
            "the method's analyst may not reject it",
        )
    method["rejection_reason"] = rejection_reason
    method["status"] = "REJECTED"
    bump(method)
    return ok_object(ser_method(method), 200)
