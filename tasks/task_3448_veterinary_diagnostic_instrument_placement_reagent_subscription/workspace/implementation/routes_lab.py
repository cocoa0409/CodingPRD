"""Lab test orders and the unified LabResult record: dual IN_CLINIC /
SEND_OUT pipelines with the proficiency cascades."""
from datetime import timedelta

from flask import Blueprint, request

import db
import ser
import services
import util
from constants import PROFICIENCY_TOLERANCE_PCT, QC_VALIDITY_DAYS
from errors import err

bp = Blueprint("lab_orders", __name__)


def _load_test_order(tid):
    o = db.test_orders.get(tid)
    if o is None:
        raise err("ERR_TEST_ORDER_NOT_FOUND", "lab test order does not exist")
    return o


@bp.post("/api/lab-test-orders")
def create_test_order():
    uid, role = util.auth()
    util.require(role, ["ClinicManager"])
    b = util.body()

    clinic_id = b.get("clinic_id")
    if clinic_id is not None and uid != clinic_id:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the body clinic_id")
    if clinic_id is None:
        raise err("ERR_INVALID_REQUEST", "clinic_id is required")
    clinic = db.clinics.get(clinic_id)
    if clinic is None:
        raise err("ERR_CLINIC_NOT_FOUND", "clinic_id does not exist")
    analyzer_id = b.get("analyzer_id")
    an = None
    if analyzer_id is not None:
        an = db.analyzers.get(analyzer_id)
        if an is None:
            raise err("ERR_ANALYZER_NOT_FOUND", "analyzer_id does not exist")

    origin = b.get("origin")
    if origin not in ("IN_CLINIC", "SEND_OUT"):
        raise err("ERR_INVALID_REQUEST", "origin must be IN_CLINIC or SEND_OUT")
    order_kind = b.get("order_kind")
    if order_kind not in ("PATIENT", "PROFICIENCY"):
        raise err("ERR_INVALID_REQUEST",
                  "order_kind must be PATIENT or PROFICIENCY")
    test_code = b.get("test_code")
    if not isinstance(test_code, str) or not test_code:
        raise err("ERR_INVALID_REQUEST", "test_code is required")
    expected = b.get("expected_result")
    if order_kind == "PROFICIENCY":
        if origin != "IN_CLINIC":
            raise err("ERR_INVALID_REQUEST",
                      "PROFICIENCY requires origin IN_CLINIC")
        if expected is None or not util.is_num(expected):
            raise err("ERR_INVALID_REQUEST",
                      "PROFICIENCY requires a numeric expected_result")
    else:
        if expected is not None:
            raise err("ERR_INVALID_REQUEST",
                      "expected_result must be null for PATIENT orders")
    if origin == "IN_CLINIC":
        if analyzer_id is None:
            raise err("ERR_INVALID_REQUEST",
                      "analyzer_id is required for IN_CLINIC orders")
        if an["clinic_id"] != clinic_id:
            raise err("ERR_INVALID_REQUEST",
                      "the analyzer must belong to the ordering clinic")
    else:
        if analyzer_id is not None:
            raise err("ERR_INVALID_REQUEST",
                      "analyzer_id must be null for SEND_OUT orders")

    if clinic["status"] != "ACTIVE":
        raise err("ERR_CLINIC_NOT_ACTIVE", "the clinic must be ACTIVE")

    o = services.stamp({
        "clinic_id": clinic_id,
        "analyzer_id": analyzer_id,
        "origin": origin,
        "order_kind": order_kind,
        "test_code": test_code,
        "expected_result": expected,
        "status": "ORDERED",
        "delivery_status": "NOT_READY",
    })
    db.test_orders[o["id"]] = o
    return util.ok(ser.test_order(o), code=201)


@bp.get("/api/lab-test-orders/<tid>")
def get_test_order(tid):
    util.auth()
    return util.ok(ser.test_order(_load_test_order(tid)))


@bp.get("/api/lab-test-orders")
def list_test_orders():
    util.auth()
    items = util.sorted_items(db.test_orders.values())
    cid = request.args.get("clinic_id")
    if cid is not None:
        items = [o for o in items if o["clinic_id"] == cid]
    aid = request.args.get("analyzer_id")
    if aid is not None:
        items = [o for o in items if o["analyzer_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    return util.paginate([ser.test_order(o) for o in items])


def _record_result(o, result_value):
    """Shared RECORD_RESULT application: creates the 1:1 LabResult, moves the
    order, and runs the proficiency cascades for IN_CLINIC orders."""
    now = db.now()
    verdict = None
    if o["order_kind"] == "PROFICIENCY":
        expected = util.dec(o["expected_result"])
        diff = abs(util.dec(result_value) - expected)
        verdict = ("PASS"
                   if diff <= PROFICIENCY_TOLERANCE_PCT * expected else "FAIL")
    r = services.stamp({
        "test_order_id": o["id"],
        "source": "IN_CLINIC" if o["origin"] == "IN_CLINIC" else "REFERENCE_LAB",
        "result_value": result_value,
        "expected_value": o["expected_result"],
        "verdict": verdict,
        "resulted_at": util.iso_z(now),
    })
    # LabResult carries only id + created_at as system fields.
    del r["updated_at"], r["version"]
    db.results[r["id"]] = r
    o["status"] = "RESULT_RECORDED"
    o["delivery_status"] = "PENDING"
    services.bump(o)

    if o["origin"] == "IN_CLINIC" and o["order_kind"] == "PROFICIENCY":
        an = db.analyzers.get(o["analyzer_id"])
        if an is not None:
            if verdict == "PASS":
                an["proficiency_standing"] = "CURRENT"
                an["_qc_valid_until"] = now + timedelta(days=QC_VALIDITY_DAYS)
                services.bump(an)
            else:
                if an["proficiency_standing"] != "LAPSED":
                    an["proficiency_standing"] = "LAPSED"
                    services.bump(an)
                services.create_remediation_case(an)
    return r


@bp.patch("/api/lab-test-orders/<tid>")
def patch_test_order(tid):
    uid, role = util.auth()
    util.require(role, ["ClinicManager", "LaboratoryTechnician"])
    o = _load_test_order(tid)
    b = util.body()
    action = b.get("action")

    # Tier 2 action-role matrix.
    if action == "RECEIVE":
        if role != "LaboratoryTechnician":
            util.forbidden("RECEIVE is LaboratoryTechnician-only")
    elif action in ("DELIVER", "CANCEL"):
        if role != "ClinicManager":
            util.forbidden("DELIVER and CANCEL are ClinicManager-only")
    elif action == "RECORD_RESULT":
        needed = ("ClinicManager" if o["origin"] == "IN_CLINIC"
                  else "LaboratoryTechnician")
        if role != needed:
            util.forbidden(
                "RECORD_RESULT belongs to ClinicManager for IN_CLINIC orders "
                "and to LaboratoryTechnician for SEND_OUT orders")
    else:
        raise err("ERR_INVALID_REQUEST",
                  "action must be RECEIVE, RECORD_RESULT, DELIVER or CANCEL")

    # Tier 3 ownership for ClinicManager-driven actions.
    if role == "ClinicManager" and uid != o["clinic_id"]:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the order's clinic_id")

    # Tier 5: result_value must be present for RECORD_RESULT.
    result_value = b.get("result_value")
    if action == "RECORD_RESULT" and (result_value is None
                                      or not util.is_num(result_value)):
        raise err("ERR_INVALID_REQUEST",
                  "result_value is required for RECORD_RESULT")

    if action == "RECEIVE":
        if o["status"] != "ORDERED" or o["origin"] != "SEND_OUT":
            raise err("ERR_TEST_ORDER_INVALID_STATE",
                      "RECEIVE requires an ORDERED SEND_OUT order")
        o["status"] = "RECEIVED"
        services.bump(o)
        return util.ok(ser.test_order(o))

    if action == "RECORD_RESULT" and o["origin"] == "IN_CLINIC":
        if o["status"] != "ORDERED":
            raise err("ERR_TEST_ORDER_INVALID_STATE",
                      "IN_CLINIC RECORD_RESULT requires status ORDERED")
        an = db.analyzers.get(o["analyzer_id"])
        # Tier 7 safety gates, in order: operational, connectivity, proficiency.
        if an is None or an["operational_status"] != "IN_SERVICE":
            raise err("ERR_ANALYZER_INVALID_STATE",
                      "the analyzer must be IN_SERVICE")
        if o["order_kind"] == "PATIENT":
            if an["connectivity_status"] != "ACTIVE":
                raise err("ERR_CONNECTIVITY_NOT_ACTIVE",
                          "PATIENT recording requires connectivity ACTIVE")
            if an["proficiency_standing"] != "CURRENT":
                raise err("ERR_PROFICIENCY_LAPSED",
                          "PATIENT recording requires proficiency CURRENT")
        _record_result(o, result_value)
        return util.ok(ser.test_order(o))

    if action == "RECORD_RESULT":  # SEND_OUT branch
        if o["status"] != "RECEIVED":
            raise err("ERR_TEST_ORDER_INVALID_STATE",
                      "SEND_OUT RECORD_RESULT requires status RECEIVED")
        _record_result(o, result_value)
        return util.ok(ser.test_order(o))

    if action == "DELIVER":
        if o["status"] != "RESULT_RECORDED":
            raise err("ERR_TEST_ORDER_INVALID_STATE",
                      "DELIVER requires status RESULT_RECORDED")
        if o["origin"] == "IN_CLINIC":
            an = db.analyzers.get(o["analyzer_id"])
            if an is None or an["connectivity_status"] != "ACTIVE":
                raise err("ERR_CONNECTIVITY_NOT_ACTIVE",
                          "in-clinic delivery requires connectivity ACTIVE")
        o["status"] = "DELIVERED"
        o["delivery_status"] = "DELIVERED"
        services.bump(o)
        return util.ok(ser.test_order(o))

    # CANCEL
    if o["status"] not in ("ORDERED", "RECEIVED"):
        raise err("ERR_TEST_ORDER_INVALID_STATE",
                  "CANCEL requires status ORDERED or RECEIVED")
    o["status"] = "CANCELLED"
    services.bump(o)
    return util.ok(ser.test_order(o))


@bp.get("/api/lab-test-orders/<tid>/results")
def get_results(tid):
    util.auth()
    o = _load_test_order(tid)
    items = [r for r in util.sorted_items(db.results.values())
             if r["test_order_id"] == o["id"]]
    return util.ok_array([ser.result(r) for r in items])
