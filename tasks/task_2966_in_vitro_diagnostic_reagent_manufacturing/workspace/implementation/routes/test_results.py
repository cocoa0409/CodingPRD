"""Analytical measurements against a raw material lot, a finished lot or a
stability timepoint (PRD 3.1, 3.5 and 3.6)."""

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import add_days, create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, Body, SUBJECT_TYPES,
                        authenticate_and_authorize, bool_filter, enum_filter,
                        json_body, pagination, paginate, str_filter)

bp = Blueprint("test_results", __name__)

# Rung 35: the subject fields each subject_type demands and forbids.
_REQUIRED_SUBJECT_FIELDS = {
    "MATERIAL_LOT": ("material_lot_id",),
    "REAGENT_LOT": ("reagent_lot_id", "reference_measured_value"),
    "STABILITY_TIMEPOINT": ("stability_study_id", "month_index"),
}
_FORBIDDEN_SUBJECT_FIELDS = {
    "MATERIAL_LOT": ("reagent_lot_id", "stability_study_id", "month_index",
                     "reference_measured_value"),
    "REAGENT_LOT": ("material_lot_id", "stability_study_id", "month_index"),
    "STABILITY_TIMEPOINT": ("material_lot_id", "reagent_lot_id",
                            "reference_measured_value"),
}


@bp.post("/test-results")
def record_test_result():
    user_id, _role = authenticate_and_authorize(("QCAnalyst",))
    body = Body(json_body())

    # Rung 30 - request shape.
    subject_type = body.req_enum("subject_type", SUBJECT_TYPES)
    test_code = body.req_str("test_code")
    measured_value = body.req_number("measured_value")
    reference_measured_value = body.opt_number("reference_measured_value", gt=0)
    month_index = body.opt_int("month_index")
    material_lot_id = body.opt_str("material_lot_id")
    reagent_lot_id = body.opt_str("reagent_lot_id")
    stability_study_id = body.opt_str("stability_study_id")
    is_retest = body.opt_bool("is_retest", False)

    # Rung 35 - subject-field coherence.
    for field in _REQUIRED_SUBJECT_FIELDS[subject_type]:
        if not body.has(field):
            raise ApiError("ERR_SUBJECT_FIELD_MISMATCH",
                           "A %s record must carry %s." % (subject_type, field))
    for field in _FORBIDDEN_SUBJECT_FIELDS[subject_type]:
        if body.has(field):
            raise ApiError("ERR_SUBJECT_FIELD_MISMATCH",
                           "A %s record must not carry %s." % (subject_type, field))

    # Rung 45 - body foreign keys, in entity field-declaration order.
    material_lot = None
    reagent_lot = None
    study = None
    if subject_type == "MATERIAL_LOT":
        material_lot = lookup.material_lot(material_lot_id)
    elif subject_type == "REAGENT_LOT":
        reagent_lot = lookup.reagent_lot(reagent_lot_id)
    else:
        study = lookup.stability_study(stability_study_id)

    if subject_type == "MATERIAL_LOT":
        return _record_material_result(user_id, material_lot, test_code,
                                       measured_value, is_retest, body)
    if subject_type == "REAGENT_LOT":
        return _record_release_result(user_id, reagent_lot, test_code,
                                      measured_value, reference_measured_value,
                                      is_retest)
    return _record_stability_result(user_id, study, test_code, measured_value,
                                    month_index, is_retest)


def _record_material_result(user_id, lot, test_code, measured_value, is_retest, body):
    spec = db.material_specifications[lot["material_specification_id"]]
    status = lot["qualification_status"]

    # Rung 60 - state precondition.
    if is_retest:
        if status != "OOS_INVESTIGATION":
            raise ApiError("ERR_MATERIAL_LOT_STATE_INVALID",
                           "A retest requires the lot to be in OOS_INVESTIGATION.")
    elif status not in ("RECEIVED", "UNDER_TEST"):
        raise ApiError("ERR_MATERIAL_LOT_STATE_INVALID",
                       "A lot in %s cannot take an acceptance measurement." % status)

    if is_retest:
        # Rung 104 - the retest window; the boundary instant is still inside it.
        if lot["first_oos_at"] is not None:
            deadline = add_days(lot["first_oos_at"], spec["retest_window_days"])
            if now_clock() > deadline:
                raise ApiError("ERR_RETEST_WINDOW_EXPIRED")
        # Rung 106 - the retest budget.
        if lot["retest_count"] >= spec["max_retests"]:
            raise ApiError("ERR_MAX_RETESTS_EXCEEDED")

    # Rung 117 - test code membership.
    if test_code not in spec["required_test_codes"]:
        raise ApiError("ERR_TEST_CODE_NOT_IN_SPEC",
                       "test_code '%s' is not in required_test_codes." % test_code)

    clock = now_clock()
    outcome = calc.material_outcome(spec, test_code, measured_value)
    record = create_row(db.test_results, {
        "subject_type": "MATERIAL_LOT",
        "material_lot_id": lot["id"],
        "reagent_lot_id": None,
        "stability_study_id": None,
        "month_index": None,
        "test_code": test_code,
        "measured_value": measured_value,
        "reference_measured_value": None,
        "is_retest": is_retest,
        "outcome": outcome,
        "bias_pct": None,
        "recovery_pct": None,
        "performed_by_user_id": user_id,
        "performed_at": clock,
    }, common=False)

    if outcome == "FAIL" and lot["first_oos_at"] is None:
        lot["first_oos_at"] = clock
    if is_retest:
        recompute.material_lot_retest_count(lot)
        lot["qualification_status"] = "UNDER_TEST"
    elif lot["qualification_status"] == "RECEIVED":
        lot["qualification_status"] = "UNDER_TEST"
    recompute.material_lot_score(lot)
    recompute.material_lot_quantities(lot)
    touch(lot)
    return created_response(serialize.test_result(record))


def _record_release_result(user_id, lot, test_code, measured_value,
                           reference_measured_value, is_retest):
    product = db.product_specifications[lot["product_specification_id"]]

    # Rung 60 - state precondition on the quality axis.
    if lot["disposition_status"] not in ("FILLED", "UNDER_RELEASE_TEST"):
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "A lot in %s cannot take a release measurement."
                       % lot["disposition_status"])

    # Rung 117 - test code membership.
    if test_code not in product["release_test_codes"]:
        raise ApiError("ERR_TEST_CODE_NOT_IN_SPEC",
                       "test_code '%s' is not in release_test_codes." % test_code)

    bias = calc.bias_pct(measured_value, reference_measured_value)
    outcome = "PASS" if bias <= calc.dec(product["max_reference_bias_pct"]) else "FAIL"
    record = create_row(db.test_results, {
        "subject_type": "REAGENT_LOT",
        "material_lot_id": None,
        "reagent_lot_id": lot["id"],
        "stability_study_id": None,
        "month_index": None,
        "test_code": test_code,
        "measured_value": measured_value,
        "reference_measured_value": reference_measured_value,
        "is_retest": is_retest,
        "outcome": outcome,
        "bias_pct": bias,
        "recovery_pct": None,
        "performed_by_user_id": user_id,
        "performed_at": now_clock(),
    }, common=False)

    if lot["disposition_status"] == "FILLED":
        lot["disposition_status"] = "UNDER_RELEASE_TEST"
    recompute.reagent_lot_release_bias(lot)
    touch(lot)
    recompute.bridging_studies_touching_lot(lot["id"])
    return created_response(serialize.test_result(record))


def _record_stability_result(user_id, study, test_code, measured_value,
                             month_index, is_retest):
    # Rung 60 - state precondition.
    if study["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise ApiError("ERR_STABILITY_STUDY_STATE_INVALID",
                       "A study in %s cannot take a timepoint." % study["status"])

    # Rung 70 - the triple is unique across test results.
    for existing in calc.stability_results(study["id"]):
        if existing["month_index"] == month_index and \
                existing["test_code"] == test_code:
            raise ApiError("ERR_DUPLICATE_TIMEPOINT")

    # Rung 121 - planned timepoint membership.
    if month_index not in study["planned_timepoints_months"]:
        raise ApiError("ERR_TIMEPOINT_NOT_PLANNED")

    recovery = calc.recovery_pct(measured_value, study["baseline_value"])
    outcome = "PASS" if recovery >= calc.STABILITY_RECOVERY_FLOOR else "FAIL"
    record = create_row(db.test_results, {
        "subject_type": "STABILITY_TIMEPOINT",
        "material_lot_id": None,
        "reagent_lot_id": None,
        "stability_study_id": study["id"],
        "month_index": month_index,
        "test_code": test_code,
        "measured_value": measured_value,
        "reference_measured_value": None,
        "is_retest": is_retest,
        "outcome": outcome,
        "bias_pct": None,
        "recovery_pct": recovery,
        "performed_by_user_id": user_id,
        "performed_at": now_clock(),
    }, common=False)

    if study["status"] == "APPROVED":
        study["status"] = "IN_PROGRESS"
    recompute.stability_study_figures(study)
    touch(study)
    return created_response(serialize.test_result(record))


@bp.get("/test-results/<record_id>")
def read_test_result(record_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.test_result(record_id)
    return object_response(serialize.test_result(row))


@bp.get("/test-results")
def list_test_results():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    subject_type = enum_filter("subject_type", SUBJECT_TYPES)
    material_lot_id = str_filter("material_lot_id")
    reagent_lot_id = str_filter("reagent_lot_id")
    stability_study_id = str_filter("stability_study_id")
    test_code = str_filter("test_code")
    is_retest = bool_filter("is_retest")
    items = rows(db.test_results)
    if subject_type is not None:
        items = [r for r in items if r["subject_type"] == subject_type]
    if material_lot_id is not None:
        items = [r for r in items if r["material_lot_id"] == material_lot_id]
    if reagent_lot_id is not None:
        items = [r for r in items if r["reagent_lot_id"] == reagent_lot_id]
    if stability_study_id is not None:
        items = [r for r in items if r["stability_study_id"] == stability_study_id]
    if test_code is not None:
        items = [r for r in items if r["test_code"] == test_code]
    if is_retest is not None:
        items = [r for r in items if r["is_retest"] == is_retest]
    page = paginate(items, limit, offset)
    return list_response([serialize.test_result(r) for r in page],
                         limit, offset, len(items))
