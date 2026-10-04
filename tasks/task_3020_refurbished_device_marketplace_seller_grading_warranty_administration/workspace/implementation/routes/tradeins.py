"""Trade-in submission routes."""

from flask import request

from db import store, public
from errors import fail
from requtils import (
    as_str, body, check_enum, created_asc, filter_eq, opt_str, pagination,
    paginate, range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import tradeins as tradein_svc
from vocab import (
    CARRIER_LOCK_STATUSES,
    COSMETIC_GRADES,
    FUNCTIONAL_GRADES,
)

MEASUREMENT_FIELDS = (
    "inspected_cosmetic_grade",
    "inspected_functional_grade",
    "inspected_battery_health_pct",
    "inspected_carrier_lock_status",
)


def register(app):
    @app.post("/v1/trade-ins")
    def create_trade_in():
        guard("POST", "/v1/trade-ins", ["Consumer"], credentials_optional=True)
        data = body()
        payload = {
            "customer_ref": as_str(required(data, "customer_ref"), "customer_ref"),
            "submitted_model_code": as_str(required(data, "submitted_model_code"),
                                           "submitted_model_code"),
            "self_declared_cosmetic_grade": check_enum(
                as_str(required(data, "self_declared_cosmetic_grade"),
                       "self_declared_cosmetic_grade"), COSMETIC_GRADES,
                "self_declared_cosmetic_grade"),
            "self_declared_functional_grade": check_enum(
                as_str(required(data, "self_declared_functional_grade"),
                       "self_declared_functional_grade"), FUNCTIONAL_GRADES,
                "self_declared_functional_grade"),
            "self_declared_battery_health_pct": range_int(
                required(data, "self_declared_battery_health_pct"),
                "self_declared_battery_health_pct", low=1, high=100),
            "self_declared_carrier_lock_status": check_enum(
                as_str(required(data, "self_declared_carrier_lock_status"),
                       "self_declared_carrier_lock_status"), CARRIER_LOCK_STATUSES,
                "self_declared_carrier_lock_status"),
        }
        submission = tradein_svc.create_submission(payload, store.clock)
        return ok(public(submission), 201)

    @app.get("/v1/trade-ins")
    def list_trade_ins():
        guard("GET", "/v1/trade-ins", ["PlatformAdmin", "TradeInInspector"])
        limit, offset = pagination()
        rows = created_asc(list(store.trade_ins.values()))
        rows = filter_eq(rows, {"submission_state": request.args.get("submission_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/trade-ins/<submission_id>")
    def read_trade_in(submission_id):
        guard("GET", "/v1/trade-ins/{id}", ["PlatformAdmin", "TradeInInspector", "Consumer"])
        return ok(public(_submission_or_404(submission_id)))

    @app.post("/v1/trade-ins/<submission_id>/inspection")
    def inspection(submission_id):
        guard("POST", "/v1/trade-ins/{id}/inspection", ["TradeInInspector"])
        submission = _submission_or_404(submission_id)
        measured = _measurements(body(), require_all=True)
        tradein_svc.record_inspection(submission, measured, store.clock)
        return ok(public(submission))

    @app.post("/v1/trade-ins/<submission_id>/inspection-revision")
    def inspection_revision(submission_id):
        guard("POST", "/v1/trade-ins/{id}/inspection-revision", ["TradeInInspector"])
        submission = _submission_or_404(submission_id)
        measured = _measurements(body(), require_all=False)
        tradein_svc.revise(submission, measured, store.clock)
        return ok(public(submission))

    @app.post("/v1/trade-ins/<submission_id>/accept")
    def accept(submission_id):
        guard("POST", "/v1/trade-ins/{id}/accept", ["Consumer"])
        submission = _submission_or_404(submission_id)
        tradein_svc.accept(submission, store.clock)
        return ok(public(submission))


# ------------------------------------------------------------------ helpers
def _submission_or_404(submission_id):
    row = store.trade_ins.get(submission_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row


def _measurements(data, require_all):
    """All four inspected_* fields; all four are required to complete an
    inspection, and only the supplied ones move on a revision.
    """
    out = {}
    for field in MEASUREMENT_FIELDS:
        if field not in data or data[field] is None:
            if require_all:
                raise fail("ERR_INVALID_REQUEST",
                           "The field '%s' is required to complete an inspection." % field)
            out[field] = None
            continue
        if field == "inspected_cosmetic_grade":
            out[field] = check_enum(as_str(data[field], field), COSMETIC_GRADES, field)
        elif field == "inspected_functional_grade":
            out[field] = check_enum(as_str(data[field], field), FUNCTIONAL_GRADES, field)
        elif field == "inspected_battery_health_pct":
            out[field] = range_int(data[field], field, low=1, high=100)
        else:
            out[field] = check_enum(as_str(data[field], field), CARRIER_LOCK_STATUSES, field)
    return out