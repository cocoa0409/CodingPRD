"""Tank fabrication, lining verification and lot release (PRD 3.4)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, period_of, touch
from errors import ApiError
from middleware import actor_id, endpoint
from services import calc
from services.core import cascade_lining_failure, require_unique, resolve, rows

bp = Blueprint("tanklots", __name__)

TANK_LOT_STATUSES = (
    "FAB_QUEUED",
    "WELDED",
    "LINED",
    "LINING_VERIFIED",
    "LINING_REJECTED",
    "RELINE_QUEUED",
    "FOAMED",
    "JACKETED",
    "RELEASED",
    "SCRAPPED",
)
INSPECTION_TYPES = ("ADHESION", "HOLIDAY")
RECORD_STATUSES = ("CURRENT", "SUPERSEDED")

LOT_READ_ROLES = ["PlantOperator", "QualityInspector", "PlantAdmin", "ComplianceEngineer"]
INSPECTION_READ_ROLES = ["QualityInspector", "PlantOperator", "PlantAdmin", "ComplianceEngineer"]


# --------------------------------------------------------------------------
# Tank lots
# --------------------------------------------------------------------------

@bp.post("/tank-lots")
@endpoint(["PlantOperator"])
def create_tank_lot():
    body = validation.json_body()
    product_model_id = validation.string(body, "product_model_id")
    lot_code = validation.string(body, "lot_code", max_length=20)
    planned_quantity = validation.integer(body, "planned_quantity", minimum=1, maximum=1000)

    model = resolve("model", product_model_id)
    require_unique("tank_lot", "lot_code", lot_code)

    row = make_row(
        {
            "product_model_id": model["id"],
            "glass_lining_batch_id": None,
            "lot_code": lot_code,
            "planned_quantity": planned_quantity,
            "wip_quantity": planned_quantity,
            "good_quantity": 0,
            "scrapped_quantity": 0,
            "rework_count": 0,
            "last_scrap_quantity": None,
            "weld_operator_user_id": None,
            "production_period": period_of(db.db.now()),
            "status": "FAB_QUEUED",
            "foam_density_kg_m3": None,
            "foam_thickness_mm": None,
            "achieved_r_value": None,
            "cascade_rejected": False,
        }
    )
    db.db.tank_lots[row["id"]] = row
    return response.created(serializers.tank_lot(row))


@bp.get("/tank-lots/<lid>")
@endpoint(LOT_READ_ROLES)
def read_tank_lot(lid):
    return response.ok(serializers.tank_lot(resolve("tank_lot", lid)))


@bp.get("/tank-lots")
@endpoint(LOT_READ_ROLES)
def list_tank_lots():
    product_model_id = validation.query_string("product_model_id")
    batch_id = validation.query_string("glass_lining_batch_id")
    production_period = validation.query_string("production_period")
    status = validation.query_enum("status", TANK_LOT_STATUSES)
    result = rows("tank_lot")
    if product_model_id is not None:
        result = [r for r in result if r["product_model_id"] == product_model_id]
    if batch_id is not None:
        result = [r for r in result if r.get("glass_lining_batch_id") == batch_id]
    if production_period is not None:
        result = [r for r in result if r["production_period"] == production_period]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.tank_lot)


@bp.post("/tank-lots/<lid>/weld")
@endpoint(["PlantOperator"])
def weld_tank_lot(lid):
    lot = resolve("tank_lot", lid)
    if lot["status"] != "FAB_QUEUED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    model = db.db.models[lot["product_model_id"]]
    if model["release_status"] == "WITHDRAWN":
        raise ApiError("ERR_MODEL_NOT_RELEASED")
    lot["status"] = "WELDED"
    lot["weld_operator_user_id"] = actor_id()
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/apply-lining")
@endpoint(["PlantOperator"])
def apply_lining(lid):
    lot = resolve("tank_lot", lid)
    body = validation.json_body()
    batch_id = validation.string(body, "glass_lining_batch_id")
    batch = resolve("batch", batch_id)

    if lot["status"] not in ("WELDED", "RELINE_QUEUED"):
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    if batch["status"] != "FIRED":
        raise ApiError("ERR_BATCH_NOT_FIRED")

    lot["status"] = "LINED"
    lot["glass_lining_batch_id"] = batch["id"]
    lot["cascade_rejected"] = False
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/authorize-reline")
@endpoint(["PlantOperator"])
def authorize_reline(lid):
    lot = resolve("tank_lot", lid)
    if lot["status"] != "LINING_REJECTED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    if lot["rework_count"] >= 2:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")
    if lot["wip_quantity"] < 1:
        raise ApiError(
            "ERR_INVALID_TANK_LOT_STATE", "No tanks remain in process on this lot."
        )
    lot["status"] = "RELINE_QUEUED"
    lot["last_scrap_quantity"] = None
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/rework-reversal")
@endpoint(["QualityInspector"])
def rework_reversal(lid):
    lot = resolve("tank_lot", lid)
    body = validation.json_body()
    validation.string(body, "reason_code")

    if lot["status"] != "LINING_REJECTED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")

    batch = db.db.batches.get(lot.get("glass_lining_batch_id"))
    if (
        lot.get("cascade_rejected")
        or lot.get("last_scrap_quantity") is None
        or batch is None
        or batch["status"] != "FIRED"
    ):
        raise ApiError("ERR_REWORK_REVERSAL_NOT_ALLOWED")

    scrap = lot["last_scrap_quantity"]
    lot["wip_quantity"] += scrap
    lot["scrapped_quantity"] -= scrap
    lot["last_scrap_quantity"] = None
    lot["rework_count"] -= 1
    lot["status"] = "LINED"
    touch(lot)
    batch["rejected_lot_count"] -= 1
    touch(batch)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/scrap")
@endpoint(["QualityInspector"])
def scrap_tank_lot(lid):
    lot = resolve("tank_lot", lid)
    body = validation.json_body()
    validation.string(body, "reason_code")
    if lot["status"] != "LINING_REJECTED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    lot["scrapped_quantity"] += lot["wip_quantity"]
    lot["wip_quantity"] = 0
    lot["status"] = "SCRAPPED"
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/foam")
@endpoint(["PlantOperator"])
def foam_tank_lot(lid):
    lot = resolve("tank_lot", lid)
    body = validation.json_body()
    foam_density = validation.number(body, "foam_density_kg_m3")
    foam_thickness = validation.integer(body, "foam_thickness_mm")

    if lot["status"] != "LINING_VERIFIED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    # Position 35 precedes position 36.
    if foam_thickness < calc.MIN_FOAM_THICKNESS_MM:
        raise ApiError("ERR_FOAM_THICKNESS_BELOW_MINIMUM")
    achieved = calc.achieved_r_value(foam_thickness)
    model = db.db.models[lot["product_model_id"]]
    if achieved < calc.D(model["insulation_r_value"]):
        raise ApiError("ERR_INSULATION_R_VALUE_SHORTFALL")

    lot["foam_density_kg_m3"] = foam_density
    lot["foam_thickness_mm"] = foam_thickness
    lot["achieved_r_value"] = achieved
    lot["status"] = "FOAMED"
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/jacket")
@endpoint(["PlantOperator"])
def jacket_tank_lot(lid):
    lot = resolve("tank_lot", lid)
    if lot["status"] != "FOAMED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    lot["status"] = "JACKETED"
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


@bp.post("/tank-lots/<lid>/release")
@endpoint(["PlantOperator"])
def release_tank_lot(lid):
    lot = resolve("tank_lot", lid)
    if lot["status"] != "JACKETED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    if lot["wip_quantity"] < 1:
        raise ApiError(
            "ERR_INVALID_TANK_LOT_STATE", "No tanks remain in process on this lot."
        )
    lot["good_quantity"] = lot["wip_quantity"]
    lot["wip_quantity"] = 0
    lot["status"] = "RELEASED"
    touch(lot)
    return response.ok(serializers.tank_lot(lot))


# --------------------------------------------------------------------------
# Lining inspections (immutable records)
# --------------------------------------------------------------------------

def _current_record(lot_id, inspection_type):
    for record in rows("inspection"):
        if (
            record["tank_lot_id"] == lot_id
            and record["inspection_type"] == inspection_type
            and record["record_status"] == "CURRENT"
        ):
            return record
    return None


@bp.post("/lining-inspections")
@endpoint(["QualityInspector"])
def create_inspection():
    body = validation.json_body()
    tank_lot_id = validation.string(body, "tank_lot_id")
    inspection_type = validation.enum(body, "inspection_type", INSPECTION_TYPES)
    sample_size = validation.integer(body, "sample_size", minimum=1)
    expected_version = validation.integer(body, "expected_tank_lot_version")

    if inspection_type == "ADHESION":
        adhesion_class = validation.integer(body, "adhesion_class", minimum=1, maximum=5)
        validation.forbid(
            body,
            "holiday_count",
            "Field 'holiday_count' must be omitted on an ADHESION record.",
        )
        holiday_count = None
    else:
        holiday_count = validation.integer(body, "holiday_count", minimum=0)
        validation.forbid(
            body,
            "adhesion_class",
            "Field 'adhesion_class' must be omitted on a HOLIDAY record.",
        )
        adhesion_class = None
    # The type of scrap_quantity belongs to schema validation; whether it is
    # allowed at all depends on the verdict computed further down the ladder.
    scrap_quantity = validation.integer(body, "scrap_quantity", required=False)

    # Position 5: body foreign keys.
    lot = resolve("tank_lot", tank_lot_id)
    # Position 7: the version pin precedes every state and business check.
    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_PARENT_VERSION")
    # Position 8: only a lined lot can be inspected.
    if lot["status"] != "LINED":
        raise ApiError("ERR_INVALID_TANK_LOT_STATE")
    # Position 10: the welder may not sign off their own work.
    if actor_id() == lot.get("weld_operator_user_id"):
        raise ApiError("ERR_SOD_INSPECTOR_IS_WELDER")
    # Position 19: an inadequate sample never masquerades as a failure.
    required = calc.required_sample_size(lot["planned_quantity"])
    if sample_size < required:
        raise ApiError("ERR_SAMPLE_SIZE_INSUFFICIENT")

    if inspection_type == "HOLIDAY":
        density = calc.holiday_density(holiday_count, sample_size)
        result = calc.holiday_verdict(density)
    else:
        density = None
        result = calc.adhesion_verdict(adhesion_class)

    if result == "FAIL":
        if scrap_quantity is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'scrap_quantity' is required on a failing inspection.",
            )
        if scrap_quantity < 1 or scrap_quantity > lot["wip_quantity"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'scrap_quantity' must be between 1 and the lot's wip_quantity.",
            )
    elif scrap_quantity is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'scrap_quantity' must be omitted on a passing inspection.",
        )

    previous = _current_record(lot["id"], inspection_type)
    if previous is not None:
        previous["record_status"] = "SUPERSEDED"

    record = make_row(
        {
            "tank_lot_id": lot["id"],
            "inspection_type": inspection_type,
            "sample_size": sample_size,
            "holiday_count": holiday_count,
            "adhesion_class": adhesion_class,
            "scrap_quantity": scrap_quantity if result == "FAIL" else None,
            "holidays_per_tank": density,
            "result": result,
            "inspector_user_id": actor_id(),
            "record_status": "CURRENT",
        },
        mutable=False,
    )
    db.db.inspections[record["id"]] = record

    if result == "FAIL":
        # Hop 1: charge the condemned tanks to the lot.
        lot["scrapped_quantity"] += scrap_quantity
        lot["wip_quantity"] -= scrap_quantity
        lot["last_scrap_quantity"] = scrap_quantity
        lot["rework_count"] += 1
        lot["cascade_rejected"] = False
        lot["status"] = "LINING_REJECTED"
        batch = db.db.batches.get(lot.get("glass_lining_batch_id"))
        # Hops 2 to 4 live in the shared cascade helper.
        cascade_lining_failure(lot, batch)
        touch(lot)
    else:
        adhesion = _current_record(lot["id"], "ADHESION")
        holiday = _current_record(lot["id"], "HOLIDAY")
        if (
            adhesion is not None
            and adhesion["result"] == "PASS"
            and holiday is not None
            and holiday["result"] == "PASS"
        ):
            lot["status"] = "LINING_VERIFIED"
        touch(lot)

    return response.created(serializers.lining_inspection(record))


@bp.get("/lining-inspections/<iid>")
@endpoint(INSPECTION_READ_ROLES)
def read_inspection(iid):
    return response.ok(serializers.lining_inspection(resolve("inspection", iid)))


@bp.get("/tank-lots/<lid>/lining-inspections")
@endpoint(INSPECTION_READ_ROLES)
def list_lot_inspections(lid):
    lot = resolve("tank_lot", lid)
    inspection_type = validation.query_enum("inspection_type", INSPECTION_TYPES)
    record_status = validation.query_enum("record_status", RECORD_STATUSES)
    result = [r for r in rows("inspection") if r["tank_lot_id"] == lot["id"]]
    if inspection_type is not None:
        result = [r for r in result if r["inspection_type"] == inspection_type]
    if record_status is not None:
        result = [r for r in result if r["record_status"] == record_status]
    return response.paginate(ordered(result), serializers.lining_inspection)
