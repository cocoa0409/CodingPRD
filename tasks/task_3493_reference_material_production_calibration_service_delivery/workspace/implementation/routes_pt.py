"""PT rounds / key comparisons and participant results."""

from flask import Blueprint, request

from db import STORE
from domain import bump, make_result, make_round, ser_result, ser_round, units_available
from engine import (
    MIN_KC_RESULTS,
    evaluate_round,
    published_certificate,
    reopen_round,
)
from util import (
    ALL_ROLES,
    ERR_DUPLICATE_PARTICIPATION,
    ERR_INSUFFICIENT_RESULTS,
    ERR_INSUFFICIENT_UNITS,
    ERR_INVALID_ROUND_STATE,
    ERR_LOT_NOT_DISTRIBUTABLE,
    ERR_NO_REFERENCE_CERTIFICATE,
    auth_context,
    body,
    fail,
    get_path,
    get_ref,
    list_page,
    ok_object,
    require_role,
    v_enum,
    v_int,
    v_num,
    v_str,
)

bp = Blueprint("pt", __name__)

ROUND_TYPES = ["PROFICIENCY_TEST", "KEY_COMPARISON"]
ROUND_STATES = ["PLANNING", "SAMPLE_DISTRIBUTION", "ANALYSIS_OPEN", "EVALUATION", "CLOSED"]


@bp.route("/metrology/pt-rounds", methods=["POST"])
def create_round():
    _uid, role = auth_context()
    require_role(role, ["AccreditationOfficer"])
    b = body()
    data = {
        "lot_id": v_str(b, "lot_id"),
        "round_code": v_str(b, "round_code"),
        "round_type": v_enum(b, "round_type", ROUND_TYPES),
        "sample_units_reserved": v_int(b, "sample_units_reserved", minv=1),
    }
    get_ref(STORE["lots"], data["lot_id"], "material lot")
    rec = make_round(data)
    STORE["pt_rounds"][rec["id"]] = rec
    return ok_object(ser_round(rec), 201)


@bp.route("/metrology/pt-rounds/<rid>/transitions", methods=["POST"])
def round_transition(rid):
    _uid, role = auth_context()
    require_role(role, ["AccreditationOfficer"])
    b = body()
    to = v_enum(b, "to", ROUND_STATES)
    rnd = get_path(STORE["pt_rounds"], rid, "PT round")
    lot = STORE["lots"].get(rnd["lot_id"])

    if to == "SAMPLE_DISTRIBUTION":
        if rnd["status"] != "PLANNING":
            fail(
                ERR_INVALID_ROUND_STATE,
                409,
                "only a PLANNING round may enter sample distribution",
            )
        if lot is None or lot["status"] != "IN_DISTRIBUTION":
            fail(ERR_LOT_NOT_DISTRIBUTABLE, 409, "the lot is not in distribution")
        if units_available(lot) < rnd["sample_units_reserved"]:
            fail(
                ERR_INSUFFICIENT_UNITS,
                422,
                "the lot's available units do not cover the reserved samples",
            )
        lot["units_reserved"] += rnd["sample_units_reserved"]
        rnd["status"] = "SAMPLE_DISTRIBUTION"
        bump(rnd)
        bump(lot)
        return ok_object(ser_round(rnd), 200)

    if to == "ANALYSIS_OPEN":
        if rnd["status"] == "SAMPLE_DISTRIBUTION":
            rnd["status"] = "ANALYSIS_OPEN"
            bump(rnd)
            return ok_object(ser_round(rnd), 200)
        if rnd["status"] == "EVALUATION":
            # reopen cycle: unwind evaluation, compensate standings
            reopen_round(rnd)
            rnd["status"] = "ANALYSIS_OPEN"
            bump(rnd)
            return ok_object(ser_round(rnd), 200)
        fail(
            ERR_INVALID_ROUND_STATE,
            409,
            "round status {} does not permit opening analysis".format(
                rnd["status"]
            ),
        )

    if to == "EVALUATION":
        if rnd["status"] != "ANALYSIS_OPEN":
            fail(
                ERR_INVALID_ROUND_STATE,
                409,
                "only an ANALYSIS_OPEN round may be evaluated",
            )
        submitted = [
            r
            for r in STORE["pt_results"].values()
            if r["round_id"] == rnd["id"] and r["status"] == "SUBMITTED"
        ]
        minimum = 1 if rnd["round_type"] == "PROFICIENCY_TEST" else MIN_KC_RESULTS
        if len(submitted) < minimum:
            fail(
                ERR_INSUFFICIENT_RESULTS,
                422,
                "the round has fewer submitted results than its type requires",
            )
        if rnd["round_type"] == "PROFICIENCY_TEST" and (
            lot is None or published_certificate(lot["id"]) is None
        ):
            fail(
                ERR_NO_REFERENCE_CERTIFICATE,
                422,
                "a proficiency test requires a PUBLISHED reference certificate",
            )
        evaluate_round(rnd)
        rnd["status"] = "EVALUATION"
        bump(rnd)
        return ok_object(ser_round(rnd), 200)

    if to == "CLOSED":
        if rnd["status"] != "EVALUATION":
            fail(
                ERR_INVALID_ROUND_STATE,
                409,
                "only an EVALUATION round may be closed",
            )
        if lot is not None:
            lot["units_reserved"] -= rnd["sample_units_reserved"]
            lot["qc_units_consumed"] += rnd["sample_units_reserved"]
            bump(lot)
        rnd["status"] = "CLOSED"
        bump(rnd)
        return ok_object(ser_round(rnd), 200)

    fail(
        ERR_INVALID_ROUND_STATE,
        409,
        "no declared round transition from {} to {}".format(rnd["status"], to),
    )


@bp.route("/metrology/pt-rounds/<rid>/participant-results", methods=["POST"])
def create_participant_result(rid):
    uid, role = auth_context()
    require_role(role, ["Customer"])
    b = body()
    data = {
        "lab_code": v_str(b, "lab_code"),
        "measured_value": v_num(b, "measured_value"),
        "measurement_uncertainty": v_num(b, "measurement_uncertainty", positive=True),
    }
    rnd = get_path(STORE["pt_rounds"], rid, "PT round")
    # the caller's X-User-ID binds to customer_id and must resolve (stage 4.5)
    customer = get_ref(STORE["customers"], uid, "customer")
    if rnd["status"] != "ANALYSIS_OPEN":
        fail(
            ERR_INVALID_ROUND_STATE,
            409,
            "results may only be filed while the round is ANALYSIS_OPEN",
        )
    for r in STORE["pt_results"].values():
        if r["round_id"] == rnd["id"] and r["customer_id"] == customer["id"]:
            fail(
                ERR_DUPLICATE_PARTICIPATION,
                409,
                "the customer already holds a result in this round",
            )
    rec = make_result(rnd["id"], customer["id"], data)
    STORE["pt_results"][rec["id"]] = rec
    return ok_object(ser_result(rec), 201)


@bp.route("/metrology/pt-participant-results/<rid>", methods=["GET"])
def get_participant_result(rid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    rec = get_path(STORE["pt_results"], rid, "participant result")
    return ok_object(ser_result(rec), 200)


@bp.route("/metrology/pt-participant-results", methods=["GET"])
def list_participant_results():
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    round_id = request.args.get("round_id")
    customer_id = request.args.get("customer_id")
    items = list(STORE["pt_results"].values())
    if round_id is not None:
        items = [r for r in items if r["round_id"] == round_id]
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    return list_page(items, ser_result)
