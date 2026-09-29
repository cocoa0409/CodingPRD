"""Cold-chain shipping: preparation, temperature monitoring, dispatch and delivery."""

from flask import Blueprint, request

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("shipments", __name__)

CARRIERS = ("COURIER", "AIR")
SHIPMENT_STATUSES = ("PREPARED", "IN_TRANSIT", "DELIVERED", "REJECTED_ON_ARRIVAL", "RETURNED")
MONITORING_WINDOW_HOURS = 168
DISPATCHABLE_CUSTODY = ("IN_HOUSE", "RETURNED_TO_BANK")
MAJOR_QUARANTINE_REASON = "COLD_CHAIN_EXCURSION_MAJOR"


def _surgeon_of_allocation(allocation):
    req = store.DB["requests"].get(allocation["request_id"])
    if req is None:
        return None
    return store.DB["surgeons"].get(req["surgeon_id"])


@bp.post("/eye-bank/shipments")
def create_shipment():
    auth.authenticate(("EyeBankCoordinator",))
    body = auth.body_dict()

    allocation = validate.resolve_fk(body, "allocation_id", "allocations")
    replaces = validate.resolve_fk(body, "replaces_shipment_id", "shipments")

    validate.req_str(body, "allocation_id")
    carrier = validate.req_enum(body, "carrier", CARRIERS)
    replaces_id = validate.opt_str(body, "replaces_shipment_id")
    if allocation is None:
        raise ApiError("ERR_INVALID_REQUEST", "allocation_id must reference an allocation.")

    if allocation["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_ALLOCATION_STATE_INVALID",
            "A shipment may only be prepared for a CONFIRMED allocation.",
        )

    if replaces_id is not None:
        if (
            replaces is None
            or replaces["status"] != "RETURNED"
            or store.DB["allocations"].get(replaces["allocation_id"], {}).get("tissue_id")
            != allocation["tissue_id"]
        ):
            raise ApiError(
                "ERR_INVALID_REISSUE_SOURCE",
                "replaces_shipment_id must be a RETURNED shipment of the same tissue.",
            )

    row = store.base_row()
    row.update(
        {
            "allocation_id": allocation["id"],
            "replaces_shipment_id": replaces_id,
            "carrier": carrier,
            "shipped_at": None,
            "delivered_at": None,
            "status": "PREPARED",
            "min_temp_c": None,
            "max_temp_c": None,
            "temp_excursion_minutes_over": None,
            "integrity_verdict": None,
        }
    )
    store.DB["shipments"][row["id"]] = row
    return envelope.ok(serialize.shipment(row), 201)


@bp.get("/eye-bank/shipments/<shipment_id>")
def get_shipment(shipment_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    row = validate.lookup("shipments", shipment_id)
    return envelope.ok(serialize.shipment(row))


@bp.get("/eye-bank/shipments")
def list_shipments():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    rows = list(store.DB["shipments"].values())
    allocation_id = request.args.get("allocation_id")
    if allocation_id is not None:
        rows = [r for r in rows if r["allocation_id"] == allocation_id]
    replaces_id = request.args.get("replaces_shipment_id")
    if replaces_id is not None:
        rows = [r for r in rows if r["replaces_shipment_id"] == replaces_id]
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, SHIPMENT_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_desc(rows, lambda r: r["created_at"])
    return envelope.paginated(rows, serialize.shipment)


@bp.post("/eye-bank/shipments/<shipment_id>/temperature-readings")
def create_reading(shipment_id):
    auth.authenticate(("EyeBankCoordinator", "Surgeon"))
    shipment = validate.lookup("shipments", shipment_id)
    body = auth.body_dict()

    recorded_at = validate.req_dt(body, "recorded_at")
    temperature_c = validate.req_decimal(body, "temperature_c", -40.0, 60.0)

    if shipment["status"] not in ("PREPARED", "IN_TRANSIT"):
        raise ApiError(
            "ERR_SHIPMENT_STATE_INVALID",
            "Readings may only be appended to a PREPARED or IN_TRANSIT shipment.",
        )

    if recorded_at < shipment["created_at"]:
        raise ApiError(
            "ERR_READING_OUTSIDE_SHIPMENT_WINDOW",
            "recorded_at precedes the shipment's monitoring window.",
        )
    if shipment["shipped_at"] is not None:
        upper = store.add_hours(shipment["shipped_at"], MONITORING_WINDOW_HOURS)
        if recorded_at > upper:
            raise ApiError(
                "ERR_READING_OUTSIDE_SHIPMENT_WINDOW",
                "recorded_at is more than 168 hours after dispatch.",
            )

    row = store.base_row(with_version=False)
    row.update(
        {
            "shipment_id": shipment["id"],
            "recorded_at": recorded_at,
            "temperature_c": temperature_c,
        }
    )
    store.DB["temperature_readings"][row["id"]] = row

    calc.refresh_temperature_envelope(shipment)
    store.touch(shipment)

    return envelope.ok(serialize.temperature_reading(row), 201)


@bp.get("/eye-bank/shipments/<shipment_id>/temperature-readings")
def list_readings(shipment_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    validate.lookup("shipments", shipment_id)
    rows = calc.shipment_readings(shipment_id)
    return envelope.nested_list(rows, serialize.temperature_reading)


@bp.post("/eye-bank/shipments/<shipment_id>/dispatch")
def dispatch(shipment_id):
    auth.authenticate(("EyeBankCoordinator",))
    shipment = validate.lookup("shipments", shipment_id)
    body = auth.body_dict()
    shipped_at = validate.req_dt(body, "shipped_at")

    allocation = store.DB["allocations"].get(shipment["allocation_id"])
    tissue = (
        store.DB["tissues"].get(allocation["tissue_id"]) if allocation is not None else None
    )
    req = store.DB["requests"].get(allocation["request_id"]) if allocation is not None else None
    surgeon = _surgeon_of_allocation(allocation) if allocation is not None else None

    # rung 15 -> 17 -> 18, in the ladder's order.
    if tissue is None or tissue["custody_status"] not in DISPATCHABLE_CUSTODY:
        raise ApiError(
            "ERR_TISSUE_CUSTODY_INVALID", "The tissue is not in the bank's physical custody."
        )
    if allocation["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_ALLOCATION_STATE_INVALID", "Dispatch requires a CONFIRMED allocation."
        )
    if shipment["status"] != "PREPARED":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Only a PREPARED shipment may be dispatched.")

    # rung 25 -> 35 -> 43 -> 47
    if surgeon is None or surgeon["credential_status"] != "ACTIVE":
        raise ApiError("ERR_SURGEON_NOT_CREDENTIALED", "The receiving surgeon is not ACTIVE.")
    if req is not None and tissue["expires_at"] < req["surgery_date"]:
        raise ApiError(
            "ERR_EXPIRY_BEFORE_SURGERY_DATE",
            "The tissue expires before the requested surgery date.",
        )
    if tissue["reissue_generation"] > 1:
        raise ApiError("ERR_REISSUE_LIMIT_REACHED", "This tissue has been returned twice.")
    if not calc.shipment_readings(shipment["id"]):
        raise ApiError(
            "ERR_NO_TEMPERATURE_BASELINE",
            "The shipment carries no pre-dispatch temperature reading.",
        )

    shipment["shipped_at"] = shipped_at
    shipment["status"] = "IN_TRANSIT"
    store.touch(shipment)

    tissue["disposition_status"] = "ISSUED"
    tissue["custody_status"] = "IN_TRANSIT"
    tissue["issue_count"] = tissue["issue_count"] + 1
    store.touch(tissue)

    return envelope.ok(serialize.shipment(shipment))


@bp.post("/eye-bank/shipments/<shipment_id>/deliver")
def deliver(shipment_id):
    actor = auth.authenticate(("Surgeon",))
    shipment = validate.lookup("shipments", shipment_id)
    body = auth.body_dict()
    delivered_at = validate.req_dt(body, "delivered_at")

    allocation = store.DB["allocations"].get(shipment["allocation_id"])
    tissue = (
        store.DB["tissues"].get(allocation["tissue_id"]) if allocation is not None else None
    )
    surgeon = _surgeon_of_allocation(allocation) if allocation is not None else None

    # rung 10: only the surgeon reachable from the shipment's allocation.
    if surgeon is not None and actor.user_id != surgeon["id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "This shipment is addressed to another surgeon."
        )

    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Only an IN_TRANSIT shipment may be delivered.")
    if tissue is None or tissue["custody_status"] != "IN_TRANSIT":
        raise ApiError("ERR_TISSUE_CUSTODY_INVALID", "The tissue is not in transit.")

    min_temp, max_temp, minutes, verdict = calc.shipment_integrity_verdict(
        shipment, shipment["shipped_at"], delivered_at
    )
    shipment["delivered_at"] = delivered_at
    shipment["min_temp_c"] = min_temp
    shipment["max_temp_c"] = max_temp
    shipment["temp_excursion_minutes_over"] = minutes
    shipment["integrity_verdict"] = verdict

    if verdict in ("PASS", "EXCURSION_MINOR"):
        shipment["status"] = "DELIVERED"
        store.touch(shipment)
        tissue["custody_status"] = "AT_SURGEON"
        store.touch(tissue)
    else:
        shipment["status"] = "REJECTED_ON_ARRIVAL"
        store.touch(shipment)
        # reissue_generation is deliberately NOT incremented: the cornea never
        # reached the surgeon's hands.
        tissue["custody_status"] = "RETURNED_TO_BANK"
        tissue["disposition_status"] = "QUARANTINED"
        tissue["quarantine_reason"] = MAJOR_QUARANTINE_REASON
        store.touch(tissue)
        if allocation is not None and allocation["status"] == "CONFIRMED":
            cascade.release_allocation(allocation, MAJOR_QUARANTINE_REASON)

    return envelope.ok(serialize.shipment(shipment))
