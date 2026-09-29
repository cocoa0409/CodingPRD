"""Component assets and nondestructive testing records."""

from flask import Blueprint

import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from reply import computed, made, saved

bp = Blueprint("components", __name__)

COMPONENT_TYPES = ("BRAKE", "LIFT_CHAIN", "RESTRAINT_ACTUATOR", "GEARBOX",
                   "AXLE", "CONTROL_PLC")
CRITICALITIES = ("SAFETY_CRITICAL", "ESSENTIAL", "NON_CRITICAL")
NDT_METHODS = ("MAGNETIC_PARTICLE", "ULTRASONIC", "DYE_PENETRANT",
               "EDDY_CURRENT", "VISUAL")
NDT_RESULTS = ("PASS", "FAIL")


@bp.post("/park-ops/components")
@require_roles("ParkOpsAdmin")
def create_component():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    validate.id_field(data, "attraction_id")
    name = validate.str_field(data, "name")
    component_type = validate.enum_field(data, "component_type",
                                         COMPONENT_TYPES)
    criticality = validate.enum_field(data, "criticality", CRITICALITIES)
    interval_cycles = validate.int_field(data, "ndt_interval_cycles",
                                         minimum=1)
    interval_days = validate.int_field(data, "ndt_interval_days", minimum=1)
    row = store.create(
        "components",
        attraction_id=attraction["id"],
        name=name,
        component_type=component_type,
        criticality=criticality,
        ndt_interval_cycles=interval_cycles,
        ndt_interval_days=interval_days,
        last_ndt_at=store.now_iso(),
        last_ndt_cycles=attraction["cumulative_cycles"],
        last_ndt_method=None,
        condition_flag="OK",
    )
    return made(derive.ser_component, row)


@bp.get("/park-ops/components/<component_id>")
@require_roles(*ALL_ROLES)
def read_component(component_id):
    return computed(derive.ser_component(fetch.component(component_id)))


@bp.get("/park-ops/components")
@require_roles(*ALL_ROLES)
def list_components():
    return list_response(
        store.rows("components"),
        derive.ser_component,
        filters=(
            ("attraction_id", "str"),
            ("criticality", "str"),
            ("ndt_status", "str"),
            ("component_type", "str"),
            ("condition_flag", "str"),
        ),
        order=("created_at",),
    )


@bp.post("/park-ops/components/<component_id>/ndt-records")
@require_roles("QualifiedInspector")
def record_ndt(component_id):
    component = fetch.component(component_id)
    data = validate.body()
    method = validate.enum_field(data, "ndt_method", NDT_METHODS)
    result = validate.enum_field(data, "result", NDT_RESULTS)
    attraction = store.db.attractions.get(component["attraction_id"])
    component["last_ndt_method"] = method
    component["last_ndt_at"] = store.now_iso()
    component["last_ndt_cycles"] = (attraction["cumulative_cycles"]
                                    if attraction else 0)
    component["condition_flag"] = "OK" if result == "PASS" else "FAILED"
    return saved(derive.ser_component, component)
