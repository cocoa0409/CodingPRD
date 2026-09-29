"""Trade-ins: receipt, bench grading, disputes and regrades (PRD 3.9)."""
from flask import Blueprint, g

import calc
import clock
import db
import lookups
import response
import serialize
import validate
from constants import (
    DU_RETURNED, REPORT_INITIAL, REPORT_REGRADE, REPORT_TYPES, ROLE_CUSTOMER,
    ROLE_PROGRAM_ADMIN, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN, SCREEN_GRADES,
    TI_DECLARED, TI_DISPUTED, TI_GRADED, TI_RECEIVED, TI_STATUSES, MAX_DISPUTES,
    UR_TRADE_IN_GRADED,
)
from errors import ApiError
from middleware import require_owner, require_roles
from services import cascades
from services import upgrades as upgrade_service

bp = Blueprint("tradeins", __name__)

READ_ROLES = (ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
              ROLE_PROGRAM_ADMIN)


def _owner(trade_in_id):
    trade_in = db.trade_ins.get(trade_in_id)
    if trade_in is None:
        return None
    request = db.upgrade_requests.get(trade_in["upgrade_request_id"])
    return request["customer_id"] if request is not None else None


def _base_credit(trade_in):
    device = db.device_units.get(trade_in["device_unit_id"])
    model = db.device_models.get(device["device_model_id"]) if device else None
    return model["trade_in_base_credit_cents"] if model is not None else 0


def _window_open(trade_in):
    request = db.upgrade_requests.get(trade_in["upgrade_request_id"])
    if request is None:
        return
    if clock.now() >= clock.parse_iso8601(request["fulfillment_window_end"]):
        raise ApiError("ERR_FULFILLMENT_WINDOW_ELAPSED")


def _measurements(payload):
    return {
        "screen_grade": validate.req_enum(payload, "screen_grade", SCREEN_GRADES),
        "battery_health_pct": validate.req_int(payload, "battery_health_pct",
                                              minimum=0, maximum=100),
        "water_damage_flag": validate.req_bool(payload, "water_damage_flag"),
        "functional_pass": validate.req_bool(payload, "functional_pass"),
    }


@bp.get("/trade-ins")
def list_trade_ins():
    require_roles(*READ_ROLES)
    limit, offset = validate.pagination()
    upgrade_request_id = validate.query_str("upgrade_request_id")
    device_unit_id = validate.query_str("device_unit_id")
    status = validate.query_enum("status", TI_STATUSES)
    rows = db.values(db.trade_ins)
    if upgrade_request_id is not None:
        rows = [r for r in rows if r["upgrade_request_id"] == upgrade_request_id]
    if device_unit_id is not None:
        rows = [r for r in rows if r["device_unit_id"] == device_unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.trade_in(r) for r in page],
                                  limit, offset, total)


@bp.get("/trade-ins/<trade_in_id>")
def read_trade_in(trade_in_id):
    require_roles(*READ_ROLES)
    require_owner(_owner(trade_in_id))
    record = lookups.trade_in(trade_in_id)
    return response.object_response(serialize.trade_in(record))


@bp.post("/trade-ins/<trade_in_id>/receipt")
def receive_trade_in(trade_in_id):
    require_roles(ROLE_SERVICE_TECHNICIAN)
    validate.body()
    trade_in = lookups.trade_in(trade_in_id)
    if trade_in["status"] != TI_DECLARED:
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    _window_open(trade_in)

    trade_in["status"] = TI_RECEIVED
    trade_in["received_at"] = clock.now_iso()
    db.touch(trade_in)
    cascades.set_possession(db.device_units.get(trade_in["device_unit_id"]), DU_RETURNED)
    return response.object_response(serialize.trade_in(trade_in))


@bp.get("/trade-ins/<trade_in_id>/diagnostic-reports")
def list_reports(trade_in_id):
    require_roles(*READ_ROLES)
    require_owner(_owner(trade_in_id))
    limit, offset = validate.pagination()
    report_type = validate.query_enum("report_type", REPORT_TYPES)
    trade_in = lookups.trade_in(trade_in_id)
    rows = upgrade_service.reports_for(trade_in["id"])
    if report_type is not None:
        rows = [r for r in rows if r["report_type"] == report_type]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.diagnostic_report(r) for r in page],
                                  limit, offset, total)


@bp.post("/trade-ins/<trade_in_id>/diagnostic-reports")
def file_diagnostic(trade_in_id):
    require_roles(ROLE_SERVICE_TECHNICIAN)
    payload = validate.body()
    measurements = _measurements(payload)

    trade_in = lookups.trade_in(trade_in_id)
    if trade_in["status"] != TI_RECEIVED:
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    _window_open(trade_in)

    figures = calc.grade_diagnostic(_base_credit(trade_in), **measurements)
    report = db.insert(db.diagnostic_reports, dict(
        trade_in_id=trade_in["id"],
        sequence_no=1,
        report_type=REPORT_INITIAL,
        technician_user_id=g.user_id,
        override_reason=None,
        **measurements,
        **figures), append_only=True)
    upgrade_service.apply_grading(trade_in, figures, 1)

    request = db.upgrade_requests.get(trade_in["upgrade_request_id"])
    if request is not None:
        request["status"] = UR_TRADE_IN_GRADED
        upgrade_service.refresh_funding_projection(request)
        db.touch(request)
    return response.object_response(serialize.diagnostic_report(report), 201)


@bp.post("/trade-ins/<trade_in_id>/dispute")
def dispute_grading(trade_in_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE)
    require_owner(_owner(trade_in_id))
    payload = validate.body()
    dispute_reason = validate.req_str(payload, "dispute_reason")

    trade_in = lookups.trade_in(trade_in_id)
    if trade_in["status"] != TI_GRADED:
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    if trade_in["dispute_count"] >= MAX_DISPUTES:
        raise ApiError("ERR_DISPUTE_LIMIT_REACHED")

    trade_in["status"] = TI_DISPUTED
    trade_in["dispute_count"] = trade_in["dispute_count"] + 1
    trade_in["dispute_reason"] = dispute_reason
    db.touch(trade_in)
    return response.object_response(serialize.trade_in(trade_in))


@bp.post("/trade-ins/<trade_in_id>/regrade")
def regrade(trade_in_id):
    require_roles(ROLE_SERVICE_TECHNICIAN, ROLE_PROGRAM_ADMIN)
    payload = validate.body()
    measurements = _measurements(payload)
    override_reason = validate.req_str(payload, "override_reason")

    trade_in = lookups.trade_in(trade_in_id)
    if trade_in["status"] != TI_DISPUTED:
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    newest = upgrade_service.latest_report(trade_in["id"])
    if newest is not None and newest["technician_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    sequence_no = trade_in["latest_report_sequence_no"] + 1
    figures = calc.grade_diagnostic(_base_credit(trade_in), **measurements)
    report = db.insert(db.diagnostic_reports, dict(
        trade_in_id=trade_in["id"],
        sequence_no=sequence_no,
        report_type=REPORT_REGRADE,
        technician_user_id=g.user_id,
        override_reason=override_reason,
        **measurements,
        **figures), append_only=True)
    upgrade_service.apply_grading(trade_in, figures, sequence_no)

    request = db.upgrade_requests.get(trade_in["upgrade_request_id"])
    if request is not None:
        upgrade_service.refresh_funding_projection(request)
        db.touch(request)
    return response.object_response(serialize.diagnostic_report(report), 201)
