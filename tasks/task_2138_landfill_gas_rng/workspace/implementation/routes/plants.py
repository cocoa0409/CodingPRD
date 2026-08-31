"""ProcessingPlant endpoints and its two independent state dimensions."""

from decimal import Decimal

from flask import Blueprint

import derived
import store
from auth import authenticate, deny_role, require_role
from common import r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import plant_out
from validation import Field, parse_body, peek_body, validate

bp = Blueprint("plants", __name__)

ZERO = Decimal("0")

PLANT_FIELDS = [
    Field("site_id", "string", required=True),
    Field("plant_code", "string", required=True, max_len=20),
    Field("receipt_point_code", "string", required=True, max_len=20),
    Field("receipt_point_mdq_dth_per_day", "number", required=True, gt=0),
    Field("min_feed_scfm", "number", required=True, gt=0),
    Field("spec_min_methane_pct", "number", default=Decimal("96.0")),
    Field("spec_max_oxygen_pct", "number", default=Decimal("0.2")),
    Field("spec_max_co2_pct", "number", default=Decimal("2.0")),
]

PROCESS_MODES = ("STARTUP", "UPGRADING", "FLARING", "DOWN", "DECOMMISSIONED")
SPEC_STATUSES = ("ON_SPEC", "OFF_SPEC", "QUARANTINE")

PROCESS_TRANSITIONS = {
    ("STARTUP", "UPGRADING"),
    ("STARTUP", "FLARING"),
    ("UPGRADING", "FLARING"),
    ("UPGRADING", "DOWN"),
    ("FLARING", "UPGRADING"),
    ("FLARING", "DOWN"),
    ("DOWN", "STARTUP"),
    ("DOWN", "DECOMMISSIONED"),
}

SPEC_TRANSITIONS = {
    ("OFF_SPEC", "QUARANTINE"),
    ("QUARANTINE", "ON_SPEC"),
}


@bp.post("/plants")
def create_plant():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin"])
    body = parse_body()
    data = validate(body, PLANT_FIELDS)

    site = must_find("site", data["site_id"])

    row = store.new_row(
        site_id=site["id"],
        plant_code=data["plant_code"],
        receipt_point_code=data["receipt_point_code"],
        receipt_point_mdq_dth_per_day=data["receipt_point_mdq_dth_per_day"],
        min_feed_scfm=data["min_feed_scfm"],
        spec_min_methane_pct=data["spec_min_methane_pct"],
        spec_max_oxygen_pct=data["spec_max_oxygen_pct"],
        spec_max_co2_pct=data["spec_max_co2_pct"],
        process_mode="STARTUP",
        spec_status="ON_SPEC",
        availability_factor_pct=r2(Decimal("100")),
        downtime_minutes_mtd=r2(ZERO),
        flare_minutes_mtd=r2(ZERO),
    )
    store.plants[row["id"]] = row
    return object_response(plant_out(row), 201)


@bp.get("/plants/<plant_id>")
def read_plant(plant_id):
    caller = authenticate()
    require_role(
        caller, ["ProjectAdmin", "PlantOperator", "CommercialScheduler", "ComplianceOfficer"]
    )
    row = must_find("plant", plant_id)
    return object_response(plant_out(row))


@bp.get("/plants")
def list_plants():
    caller = authenticate()
    require_role(
        caller, ["ProjectAdmin", "PlantOperator", "CommercialScheduler", "ComplianceOfficer"]
    )
    limit, offset = pagination()
    rows = store.ordered(store.plants.values())
    rows = filter_equal(rows, "site_id", arg("site_id"))
    rows = filter_equal(rows, "process_mode", arg("process_mode"))
    rows = filter_equal(rows, "spec_status", arg("spec_status"))
    return paginate(rows, limit, offset, plant_out)


PLANT_STATUS_FIELDS = [
    Field("process_mode", "enum", values=PROCESS_MODES),
    Field("spec_status", "enum", values=SPEC_STATUSES),
]


@bp.post("/plants/<plant_id>/status")
def plant_status(plant_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator"])

    peeked = peek_body()
    # Only a PlantOperator moves the spec dimension.
    if caller.role == "ProjectAdmin" and peeked.get("spec_status") is not None:
        deny_role("Only a PlantOperator may move the spec_status dimension.")
    # Only a ProjectAdmin may retire the plant.
    if caller.role == "PlantOperator" and peeked.get("process_mode") == "DECOMMISSIONED":
        deny_role("Only a ProjectAdmin may decommission a plant.")

    plant = must_find("plant", plant_id)
    body = parse_body()
    data = validate(body, PLANT_STATUS_FIELDS)

    process_target = data["process_mode"]
    spec_target = data["spec_status"]
    if process_target is None and spec_target is None:
        fail("ERR_VALIDATION", "At least one of process_mode or spec_status is required.")

    process_current = plant["process_mode"]
    spec_current = plant["spec_status"]

    # Priority 80 - state legality.
    if process_current == "DECOMMISSIONED":
        fail("ERR_INVALID_TRANSITION", "A decommissioned plant accepts no further transition.")
    if process_target is not None and (process_current, process_target) not in PROCESS_TRANSITIONS:
        fail(
            "ERR_INVALID_TRANSITION",
            "%s -> %s is not a declared process_mode transition." % (process_current, process_target),
        )
    if spec_target is not None and (spec_current, spec_target) not in SPEC_TRANSITIONS:
        fail(
            "ERR_INVALID_TRANSITION",
            "%s -> %s is not a declared spec_status transition." % (spec_current, spec_target),
        )

    # Priority 90 - process-safety gates.
    effective_spec = spec_target if spec_target is not None else spec_current
    site = derived.site_of_plant(plant)
    if process_target == "UPGRADING":
        if effective_spec != "ON_SPEC":
            fail("ERR_PLANT_OFF_SPEC", "The plant must be ON_SPEC to upgrade.")
        if site is not None and site["collected_flow_scfm"] < plant["min_feed_scfm"]:
            fail(
                "ERR_INSUFFICIENT_FEED_FLOW",
                "The site's collected flow is below the plant's minimum feed.",
            )
    if spec_target == "ON_SPEC":
        for batch in derived.batches_of_plant(plant["id"]):
            if batch["status"] == "OFF_SPEC":
                fail(
                    "ERR_OFF_SPEC_BATCH_UNRESOLVED",
                    "An injection batch of this plant is still OFF_SPEC.",
                )

    # Apply the spec dimension first, then the process dimension.
    if spec_target is not None:
        derived.apply_changes(plant, {"spec_status": spec_target})

    if process_target is not None:
        if process_current == "UPGRADING" and process_target == "FLARING":
            derived.plant_to_flaring(plant, automatic=False)
        elif process_current == "FLARING" and process_target == "UPGRADING":
            derived.plant_to_upgrading(plant)
        elif process_current == "UPGRADING" and process_target == "DOWN":
            derived.apply_changes(plant, {"process_mode": "DOWN"})
            derived.divert_in_flight_batches(plant)
        else:
            derived.apply_changes(plant, {"process_mode": process_target})

    return object_response(plant_out(plant))
