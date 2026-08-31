"""InjectionBatch endpoints."""

from decimal import Decimal

from flask import Blueprint

import calc
import derived
import store
from auth import authenticate, require_role
from common import r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import batch_out
from validation import Field, parse_body, validate

bp = Blueprint("batches", __name__)

ZERO = Decimal("0")

BATCH_FIELDS = [
    Field("plant_id", "string", required=True),
    Field("interval_start", "datetime", required=True),
    Field("interval_end", "datetime", required=True),
    Field(
        "hourly_volumes_mscf",
        "num_array",
        required=True,
        min_items=1,
        max_items=24,
        item_gte=0,
    ),
    Field("methane_pct", "number", required=True, gte=0, lte=100),
    Field("oxygen_pct", "number", required=True, gte=0, lte=25),
    Field("co2_pct", "number", required=True, gte=0, lte=100),
]


@bp.post("/injection-batches")
def create_batch():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator"])
    body = parse_body()
    data = validate(body, BATCH_FIELDS)

    plant = must_find("plant", data["plant_id"])

    # Priority 56 - whole-hour interval matched by the volume array length.
    seconds = (data["interval_end"] - data["interval_start"]).total_seconds()
    if seconds <= 0 or seconds % 3600 != 0 or int(seconds // 3600) != len(
        data["hourly_volumes_mscf"]
    ):
        fail(
            "ERR_BATCH_INTERVAL_MISMATCH",
            "The interval must span a whole number of hours matching hourly_volumes_mscf.",
        )

    gross = calc.gross_mmbtu(data["hourly_volumes_mscf"], data["methane_pct"])

    row = store.new_row(
        plant_id=plant["id"],
        nomination_id=None,
        interval_start=data["interval_start"],
        interval_end=data["interval_end"],
        hourly_volumes_mscf=data["hourly_volumes_mscf"],
        methane_pct=data["methane_pct"],
        oxygen_pct=data["oxygen_pct"],
        co2_pct=data["co2_pct"],
        gross_mmbtu=gross,
        metered_mmbtu=None,
        status="DRAFT",
        spec_failure_reason="NONE",
        void_reason=None,
    )
    store.injection_batches[row["id"]] = row
    return object_response(batch_out(row), 201)


@bp.get("/injection-batches/<batch_id>")
def read_batch(batch_id):
    caller = authenticate()
    require_role(
        caller, ["ProjectAdmin", "PlantOperator", "CommercialScheduler", "ComplianceOfficer"]
    )
    row = must_find("batch", batch_id)
    return object_response(batch_out(row))


@bp.get("/injection-batches")
def list_batches():
    caller = authenticate()
    require_role(
        caller, ["ProjectAdmin", "PlantOperator", "CommercialScheduler", "ComplianceOfficer"]
    )
    limit, offset = pagination()
    rows = store.ordered(store.injection_batches.values())
    rows = filter_equal(rows, "plant_id", arg("plant_id"))
    rows = filter_equal(rows, "nomination_id", arg("nomination_id"))
    rows = filter_equal(rows, "status", arg("status"))
    return paginate(rows, limit, offset, batch_out)


BATCH_STATUS_FIELDS = [
    Field(
        "to_status",
        "enum",
        required=True,
        values=(
            "DRAFT",
            "PENDING_ANALYSIS",
            "ON_SPEC",
            "OFF_SPEC",
            "NOMINATED",
            "INJECTED",
            "DIVERTED_TO_FLARE",
            "VOIDED",
        ),
    ),
    Field("nomination_id", "string"),
    Field("void_reason", "string", max_len=500),
]

VOIDABLE = ("INJECTED", "DIVERTED_TO_FLARE", "DRAFT", "ON_SPEC", "OFF_SPEC")


def _analyse(batch, plant):
    """Automatic spec evaluation; the batch never rests in PENDING_ANALYSIS."""
    if batch["methane_pct"] < plant["spec_min_methane_pct"]:
        return "OFF_SPEC", "LOW_METHANE"
    if batch["oxygen_pct"] > plant["spec_max_oxygen_pct"]:
        return "OFF_SPEC", "HIGH_OXYGEN"
    if batch["co2_pct"] > plant["spec_max_co2_pct"]:
        return "OFF_SPEC", "HIGH_CO2"
    return "ON_SPEC", "NONE"


@bp.post("/injection-batches/<batch_id>/status")
def batch_status(batch_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator", "CommercialScheduler"])
    batch = must_find("batch", batch_id)
    body = parse_body()
    data = validate(body, BATCH_STATUS_FIELDS)

    target = data["to_status"]
    current = batch["status"]

    if target == "NOMINATED" and data["nomination_id"] is None:
        fail("ERR_VALIDATION", "nomination_id is required when attaching a batch to a nomination.")
    if target == "VOIDED" and data["void_reason"] is None:
        fail("ERR_VALIDATION", "void_reason is required when voiding a batch.")

    # Priority 50 - body foreign key.
    nomination = None
    if data["nomination_id"] is not None:
        nomination = must_find("nomination", data["nomination_id"])

    plant = store.plants.get(batch["plant_id"])

    # Priority 80 - state legality (with the two priority-90 carve-outs).
    if target == "PENDING_ANALYSIS":
        if current != "DRAFT":
            fail("ERR_INVALID_TRANSITION", "%s -> %s is not declared." % (current, target))
    elif target == "NOMINATED":
        if current not in ("ON_SPEC", "OFF_SPEC"):
            fail("ERR_INVALID_TRANSITION", "%s -> %s is not declared." % (current, target))
        if nomination["status"] not in ("CONFIRMED", "SCHEDULED"):
            fail("ERR_INVALID_TRANSITION", "The nomination is not CONFIRMED or SCHEDULED.")
        if nomination["plant_id"] != batch["plant_id"]:
            fail("ERR_INVALID_TRANSITION", "The nomination belongs to a different plant.")
    elif target == "INJECTED":
        if current not in ("NOMINATED", "OFF_SPEC"):
            fail("ERR_INVALID_TRANSITION", "%s -> %s is not declared." % (current, target))
    elif target == "DIVERTED_TO_FLARE":
        if current not in derived.DIVERTIBLE:
            fail("ERR_INVALID_TRANSITION", "%s -> %s is not declared." % (current, target))
    elif target == "VOIDED":
        if current not in VOIDABLE:
            fail("ERR_INVALID_TRANSITION", "%s -> %s is not declared." % (current, target))
    else:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not declared." % (current, target))

    # Priority 90 - process-safety gates.
    if target == "PENDING_ANALYSIS":
        if plant is None or plant["process_mode"] != "UPGRADING":
            fail("ERR_PLANT_NOT_UPGRADING", "The plant is not UPGRADING.")
    elif target == "NOMINATED":
        if current == "OFF_SPEC":
            fail("ERR_BATCH_OFF_SPEC", "An OFF_SPEC batch may not be nominated.")
        if plant is None or plant["process_mode"] != "UPGRADING":
            fail("ERR_PLANT_NOT_UPGRADING", "The plant is not UPGRADING.")
        if plant["spec_status"] != "ON_SPEC":
            fail("ERR_PLANT_OFF_SPEC", "The plant's spec_status is not ON_SPEC.")
    elif target == "INJECTED":
        if current == "OFF_SPEC":
            fail("ERR_BATCH_OFF_SPEC", "An OFF_SPEC batch may not be injected.")
        if plant is None or plant["process_mode"] != "UPGRADING":
            fail("ERR_PLANT_NOT_UPGRADING", "The plant is not UPGRADING.")

    # Priority 130 - nomination volume headroom.
    if target == "NOMINATED":
        if nomination["committed_dth"] + batch["gross_mmbtu"] > nomination["nominated_dth"]:
            fail(
                "ERR_NOMINATION_VOLUME_EXCEEDED",
                "Attaching this batch would exceed the nomination's volume.",
            )

    site = derived.site_of_batch(batch)

    if target == "PENDING_ANALYSIS":
        landed, reason = _analyse(batch, plant)
        derived.apply_changes(batch, {"status": landed, "spec_failure_reason": reason})
        if landed == "OFF_SPEC" and plant["spec_status"] == "ON_SPEC":
            derived.apply_changes(plant, {"spec_status": "OFF_SPEC"})

    elif target == "NOMINATED":
        derived.apply_changes(
            batch, {"status": "NOMINATED", "nomination_id": nomination["id"]}
        )
        changes = {"committed_dth": r2(nomination["committed_dth"] + batch["gross_mmbtu"])}
        if nomination["status"] == "CONFIRMED":
            changes["status"] = "SCHEDULED"
        derived.apply_changes(nomination, changes)

    elif target == "INJECTED":
        gross = batch["gross_mmbtu"]
        derived.apply_changes(batch, {"status": "INJECTED"})
        if site is not None:
            derived.move_energy(site, produced=gross, injected=gross)
        attached = store.nominations.get(batch["nomination_id"]) if batch["nomination_id"] else None
        if attached is not None:
            changes = {"delivered_dth": r2(attached["delivered_dth"] + gross)}
            if attached["status"] == "SCHEDULED" and changes["delivered_dth"] >= attached["nominated_dth"]:
                changes["status"] = "DELIVERED"
            derived.apply_changes(attached, changes)
            contract = store.contracts.get(attached["contract_id"])
            if contract is not None:
                derived.apply_changes(
                    contract,
                    {"delivered_dth_mtd": r2(contract["delivered_dth_mtd"] + gross)},
                )

    elif target == "DIVERTED_TO_FLARE":
        derived.divert_batch(batch)

    else:  # VOIDED
        gross = batch["gross_mmbtu"]
        previous = current
        derived.apply_changes(batch, {"status": "VOIDED", "void_reason": data["void_reason"]})
        if previous == "INJECTED":
            if site is not None:
                derived.move_energy(site, produced=-gross, injected=-gross)
            attached = (
                store.nominations.get(batch["nomination_id"]) if batch["nomination_id"] else None
            )
            if attached is not None:
                derived.apply_changes(
                    attached,
                    {
                        "delivered_dth": r2(attached["delivered_dth"] - gross),
                        "committed_dth": r2(attached["committed_dth"] - gross),
                    },
                )
                contract = store.contracts.get(attached["contract_id"])
                if contract is not None:
                    derived.apply_changes(
                        contract,
                        {"delivered_dth_mtd": r2(contract["delivered_dth_mtd"] - gross)},
                    )
            for attribute in derived.attributes_of_batch(batch["id"]):
                if attribute["status"] in ("PENDING", "GENERATED", "QA_HOLD", "SEPARATED"):
                    derived.reverse_attribute(attribute, "UPSTREAM_BATCH_DIVERTED")
        elif previous == "DIVERTED_TO_FLARE":
            if site is not None:
                derived.move_energy(site, produced=-gross, flared=-gross)

    return object_response(batch_out(batch))


TRUEUP_FIELDS = [Field("metered_mmbtu", "number", required=True, gte=0)]


@bp.post("/injection-batches/<batch_id>/meter-trueup")
def meter_trueup(batch_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "CommercialScheduler"])
    batch = must_find("batch", batch_id)
    body = parse_body()
    data = validate(body, TRUEUP_FIELDS)

    # Priority 80 - the batch must have reached INJECTED.
    if batch["status"] != "INJECTED":
        fail("ERR_INVALID_TRANSITION", "The meter true-up requires an INJECTED batch.")

    derived.apply_changes(batch, {"metered_mmbtu": data["metered_mmbtu"]})
    return object_response(batch_out(batch))
