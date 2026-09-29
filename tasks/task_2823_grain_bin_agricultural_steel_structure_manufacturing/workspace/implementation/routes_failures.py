"""Field failure investigations and the four determination branches (PRD 3.9)."""
from flask import Blueprint, request

import calc
import serializers
import services
import store
from authz import ALL_ROLES, authorize
from envelope import created, ok, paginated
from errors import ApiError
from routes_orders import find_order
from shape import body, req_enum, req_num, req_str
from store import insert, touch

bp = Blueprint("failures", __name__)

FAILURE_MODES = (
    "SIDEWALL_BUCKLE",
    "ROOF_COLLAPSE",
    "CORROSION_PERFORATION",
    "ANCHOR_PULLOUT",
)


def find_failure(row_id):
    row = store.field_failures.get(row_id)
    if row is None:
        raise ApiError("ERR_FIELD_FAILURE_NOT_FOUND")
    return row


@bp.post("/field-failures")
def open_investigation():
    authorize(("QualityInspector",))
    payload = body()
    order_id = req_str(payload, "dealer_order_id")
    failure_mode = req_enum(payload, "failure_mode", FAILURE_MODES)
    observed_load_kpa = req_num(payload, "observed_load_kpa", minimum="0.0", maximum="500.0")
    measured_coating_loss_pct = req_num(
        payload, "measured_coating_loss_pct", minimum="0.0", maximum="100.0"
    )
    service_years = req_num(payload, "service_years", minimum="0.0", maximum="60.0")

    order = find_order(order_id)

    row = {
        "dealer_order_id": order_id,
        "bin_design_id": order["bin_design_id"],
        "failure_mode": failure_mode,
        "observed_load_kpa": observed_load_kpa,
        "measured_coating_loss_pct": measured_coating_loss_pct,
        "service_years": service_years,
        "structural_verdict": None,
        "corrosion_verdict": None,
        "determined_cause": None,
        "status": "INTAKE",
    }
    insert(store.field_failures, row)
    return created(serializers.field_failure(row))


@bp.get("/field-failures")
def list_failures():
    authorize(ALL_ROLES)
    rows = store.ordered(store.field_failures)
    for field in ("dealer_order_id", "bin_design_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row[field] == value]
    return paginated(rows, serializers.field_failure)


@bp.get("/field-failures/<row_id>")
def read_failure(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.field_failure(find_failure(row_id)))


@bp.post("/field-failures/<row_id>/start-analysis")
def start_analysis(row_id):
    authorize(("QualityInspector",))
    failure = find_failure(row_id)
    if failure["status"] != "INTAKE":
        raise ApiError("ERR_FAILURE_STATE_INVALID")

    design = store.bin_designs[failure["bin_design_id"]]
    coating = store.coating_specs[design["coating_spec_id"]]

    failure["structural_verdict"] = calc.structural_verdict(
        failure["observed_load_kpa"], design["governing_demand_kpa"]
    )
    failure["corrosion_verdict"] = calc.corrosion_verdict(
        failure["measured_coating_loss_pct"], coating["corrosion_class"]
    )
    failure["status"] = "ANALYSIS_IN_PROGRESS"
    touch(failure)
    return ok(serializers.field_failure(failure))


@bp.post("/field-failures/<row_id>/determine")
def determine(row_id):
    authorize(("QualityInspector",))
    failure = find_failure(row_id)
    if failure["status"] != "ANALYSIS_IN_PROGRESS":
        raise ApiError("ERR_FAILURE_STATE_INVALID")

    failure["determined_cause"] = calc.determined_cause(
        failure["failure_mode"], failure["structural_verdict"], failure["corrosion_verdict"]
    )
    failure["status"] = "DETERMINED"
    touch(failure)
    services.apply_determination(failure)
    return ok(serializers.field_failure(failure))
