"""Secure material shipments: dispatch, custody events, receipt and seal breaks."""

import auth
import cascades
import clock
import core
from core import app, body, bool_field, insert, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import ok
from validation import require_fk, require_unique, transition_gate


def _append_event(shipment, event_type, seal_intact, verification=None):
    sequence = shipment["custody_sequence_count"] + 1
    event = {
        "event_type": event_type,
        "seal_intact": seal_intact,
        "occurred_at_utc": clock.now_iso(),
        "custody_sequence": sequence,
    }
    if verification is not None:
        event["verification"] = verification
    shipment["custody_event_types"].append(event)
    cascades.recompute_custody_counts(shipment)
    return event


def _chain_is_gap_free(shipment):
    sequences = sorted(e["custody_sequence"] for e in shipment["custody_event_types"])
    expected = list(range(1, len(sequences) + 1))
    return sequences == expected


@app.route("/ap-program/material-shipments", methods=["POST"])
def create_material_shipment():
    auth.authenticate(["PlatformAdmin"])
    payload = body()
    school_id = str_field(payload, "school_id")
    exam_order_id = str_field(payload, "exam_order_id")
    carrier_tracking_id = str_field(payload, "carrier_tracking_id")
    seal_number = str_field(payload, "seal_number")
    require_fk("schools", school_id, "school_id")
    require_fk("exam_orders", exam_order_id, "exam_order_id")
    require_unique("material_shipments", "carrier_tracking_id", carrier_tracking_id)
    shipment = insert("material_shipments", make(
        "material_shipments",
        school_id=school_id,
        exam_order_id=exam_order_id,
        carrier_tracking_id=carrier_tracking_id,
        seal_number=seal_number,
    ))
    return ok(serialize("material_shipments", shipment), status=201)


@app.route("/ap-program/material-shipments/<rid>", methods=["GET"])
def read_material_shipment(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    return ok(serialize("material_shipments", require("material_shipments", rid)))


@app.route("/ap-program/material-shipments/<rid>/custody-events", methods=["POST"])
def append_custody_event(rid):
    auth.authenticate(["SchoolCoordinator", "PlatformAdmin"])
    payload = body()
    shipment = require("material_shipments", rid)
    event_type = str_field(payload, "event_type")
    seal_intact = bool_field(payload, "seal_intact", True)
    event = _append_event(shipment, event_type, seal_intact)
    core.touch(shipment)
    return ok(event, status=201)


@app.route("/ap-program/material-shipments/<rid>/status-transitions", methods=["POST"])
def transition_material_shipment(rid):
    _role, actor = auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    payload = body()
    shipment, to_status = transition_gate("material_shipments", rid, payload, actor=actor)
    school = core.require("schools", shipment["school_id"])
    order = core.require("exam_orders", shipment["exam_order_id"])

    if to_status == "DISPATCHED":
        if not (shipment.get("seal_number") or "").strip():
            fail("ERR_INVALID_STATE", "The shipment carries no seal number.")
        if not school["program_label_authorized"]:
            fail("ERR_INVALID_STATE", "The school holds no program-label authorization.")
        shipment["status"] = "DISPATCHED"
        _append_event(shipment, "DISPATCH", True)
        core.touch(shipment)

    elif to_status == "IN_TRANSIT":
        events = shipment["custody_event_types"]
        if not events or events[-1]["event_type"] != "DISPATCH":
            fail("ERR_INVALID_STATE", "The latest custody event is not the dispatch.")
        shipment["status"] = "IN_TRANSIT"
        _append_event(shipment, "TRANSIT_SCAN", True)
        core.touch(shipment)

    elif to_status == "RECEIVED":
        seal_intact = bool_field(payload, "seal_intact", False)
        if school["seal_required"] and not seal_intact:
            fail("ERR_SEAL_VERIFICATION_FAILED")
        if not _chain_is_gap_free(shipment):
            fail("ERR_CUSTODY_CHAIN_GAP")
        shipment["status"] = "RECEIVED"
        shipment["seal_verified"] = True
        _append_event(shipment, "SEAL_VERIFY", True,
                      verification="VERIFIED" if school["seal_required"] else "NOT_REQUIRED")
        core.touch(shipment)

    elif to_status == "SEAL_BROKEN":
        if bool_field(payload, "seal_intact", True):
            fail("ERR_INVALID_STATE", "A seal-break report requires seal_intact=false.")
        shipment["status"] = "SEAL_BROKEN"
        shipment["seal_verified"] = False
        _append_event(shipment, "SEAL_BREAK_REPORT", False)
        core.touch(shipment)
        if order["status"] == "MATERIALS_SHIPPED":
            cascades.seal_break_cascade(order)

    elif to_status == "RETURNED":
        if shipment["status"] == "RECEIVED":
            for reg in cascades.regs_of_order(order["id"]):
                if reg["status"] == "MATERIAL_ASSIGNED":
                    fail("ERR_INVALID_STATE", "Material is still assigned to a registration.")
        else:
            for case in rows("irregularity_cases"):
                if case["exam_registration_id"] and case["test_center_id"] == shipment["school_id"] \
                        and case["irregularity_type"] == "MATERIAL_COMPROMISE" \
                        and case["status"] not in ("CONFIRMED", "DISMISSED"):
                    fail("ERR_INVALID_STATE", "A seal-break case is still open.")
        shipment["status"] = "RETURNED"
        _append_event(shipment, "RETURN", shipment["seal_verified"])
        core.touch(shipment)

    return ok(serialize("material_shipments", shipment))
