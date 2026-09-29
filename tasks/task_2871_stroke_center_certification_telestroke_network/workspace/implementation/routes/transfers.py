"""Transfer decisions: proposal, congestion projection and handoff (PRD 3.7)."""
from flask import Blueprint

import db
import response as resp
from constants import (
    CASE_TERMINAL,
    DIDO_TARGET_MIN,
    REQUIRED_HANDOFF_PACKET_ITEMS,
    TRANSFER_MODES,
)
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import calculations as calc
from services import derive

bp = Blueprint("transfers", __name__)

CREATE_SPEC = [
    Field("case_id", "str"),
    Field("destination_center_id", "str"),
    Field("mode", "str", enum=TRANSFER_MODES),
    Field("transport_eta_minutes", "int", minimum=1, maximum=600),
]

DECLINE_SPEC = [Field("decline_reason", "str", min_len=1)]

HANDOFF_SPEC = [
    Field("handoff_packet_items", "list", item_kind="str"),
]


def required_packet_items(mode):
    """DRIP_AND_SHIP requires the full set; TRANSFER_ONLY drops HP_LYTIC_RECORD."""
    if mode == "DRIP_AND_SHIP":
        return REQUIRED_HANDOFF_PACKET_ITEMS
    return tuple(i for i in REQUIRED_HANDOFF_PACKET_ITEMS if i != "HP_LYTIC_RECORD")


@bp.route("/transfer-decisions", methods=["POST"])
def create_transfer():
    authenticate(("TransferCoordinator",))
    body = read_body(CREATE_SPEC)
    case = load_ref("cases", body["case_id"])
    destination = load_ref("centers", body["destination_center_id"])
    if case["status"] in CASE_TERMINAL:
        fail("ERR_CASE_NOT_ACTIVE", "The case is %s." % case["status"])
    if case["status"] not in ("ELIGIBILITY_DETERMINED", "THROMBOLYSIS_ADMINISTERED"):
        fail("ERR_CASE_NOT_ACTIVE",
             "No transfer proposal is declared from case status %s." % case["status"])
    mode = body["mode"]
    if mode == "DRIP_AND_SHIP" and case["needle_at"] is None:
        fail("ERR_TRANSFER_MODE_MISMATCH",
             "DRIP_AND_SHIP requires the case's needle_at to be set.")
    if mode == "TRANSFER_ONLY" and case["needle_at"] is not None:
        fail("ERR_TRANSFER_MODE_MISMATCH",
             "TRANSFER_ONLY requires the case's needle_at to be null.")
    if destination["facility_type"] != "THROMBECTOMY_CAPABLE":
        fail("ERR_DESTINATION_NOT_THROMBECTOMY_CAPABLE",
             "The destination's facility_type is %s." % destination["facility_type"])
    if destination["ems_routing_posture"] == "BYPASS":
        fail("ERR_DESTINATION_BYPASS", "The destination facility is on BYPASS.")
    if destination["id"] == case["center_id"]:
        fail("ERR_SELF_REFERRAL_TRANSFER",
             "The destination facility is the case's own facility.")
    # The projection runs in a pinned order and the order is observable.
    snapshot = destination["ems_routing_posture"]
    factor = calc.congestion_factor(snapshot)
    adjusted = calc.adjusted_transport_minutes(body["transport_eta_minutes"], factor)
    record = {
        "case_id": case["id"],
        "origin_center_id": case["center_id"],
        "destination_center_id": destination["id"],
        "mode": mode,
        "transport_eta_minutes": body["transport_eta_minutes"],
        "status": "PROPOSED",
        "destination_posture_at_proposal": snapshot,
        "congestion_factor": factor,
        "adjusted_transport_minutes": adjusted,
        "projected_door_in_door_out_minutes": calc.projected_dido(adjusted, mode),
        "door_in_door_out_minutes": None,
        "handoff_packet_items": [],
        "handoff_packet_complete": False,
        "proposed_at": db.now_raw(),
        "accepted_at": None,
        "handoff_completed_at": None,
        "decline_reason": None,
        "cancellation_reason": None,
    }
    db.insert("transfers", record)
    case["status"] = "TRANSFER_INITIATED"
    case["disposition"] = "DRIP_AND_SHIP" if mode == "DRIP_AND_SHIP" else "TRANSFER_ONLY"
    db.touch(case)
    return resp.object_response(record, 201)


@bp.route("/transfer-decisions/<record_id>", methods=["GET"])
def read_transfer(record_id):
    authenticate("any")
    return resp.object_response(load_path("transfers", record_id))


@bp.route("/transfer-decisions", methods=["GET"])
def list_transfers():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("transfers"), {
        "case_id": "case_id",
        "origin_center_id": "origin_center_id",
        "destination_center_id": "destination_center_id",
        "status": "status",
        "mode": "mode",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/transfer-decisions/<record_id>/accept", methods=["POST"])
def accept_transfer(record_id):
    authenticate(("TransferCoordinator",))
    record = load_path("transfers", record_id)
    read_body([])
    if record["status"] != "PROPOSED":
        fail("ERR_INVALID_TRANSFER_STATE",
             "No acceptance is declared from %s." % record["status"])
    destination = db.get("centers", record["destination_center_id"])
    # Acceptance re-checks the destination against its live state; the frozen
    # snapshot and every figure derived from it keep their values.
    if (destination is None
            or destination["ems_routing_posture"] == "BYPASS"
            or destination["certification_status"] in ("SUSPENDED", "WITHDRAWN")):
        fail("ERR_DESTINATION_BYPASS",
             "The destination facility can no longer receive the patient.")
    record["status"] = "ACCEPTED"
    record["accepted_at"] = db.now_raw()
    db.touch(record)
    derive.recompute_open_case_count(destination)
    derive.recompute_ems_posture(destination)
    return resp.object_response(record)


@bp.route("/transfer-decisions/<record_id>/decline", methods=["POST"])
def decline_transfer(record_id):
    authenticate(("TransferCoordinator",))
    record = load_path("transfers", record_id)
    body = read_body(DECLINE_SPEC)
    if record["status"] != "PROPOSED":
        fail("ERR_INVALID_TRANSFER_STATE",
             "No decline is declared from %s." % record["status"])
    record["status"] = "DECLINED"
    record["decline_reason"] = body["decline_reason"]
    db.touch(record)
    case = db.get("cases", record["case_id"])
    if case is not None:
        # The case unwinds to the node it came from; no open_case_count moves,
        # because a proposed transfer was never counted.
        if record["mode"] == "DRIP_AND_SHIP":
            case["status"] = "THROMBOLYSIS_ADMINISTERED"
            case["disposition"] = "TREATED_LOCAL"
        else:
            case["status"] = "ELIGIBILITY_DETERMINED"
            case["disposition"] = "PENDING"
        db.touch(case)
    return resp.object_response(record)


@bp.route("/transfer-decisions/<record_id>/complete-handoff", methods=["POST"])
def complete_handoff(record_id):
    authenticate(("TransferCoordinator",))
    record = load_path("transfers", record_id)
    body = read_body(HANDOFF_SPEC)
    if record["status"] != "ACCEPTED":
        fail("ERR_INVALID_TRANSFER_STATE",
             "Only an ACCEPTED transfer can be handed off, not a %s one."
             % record["status"])
    case = db.get("cases", record["case_id"])
    items = body["handoff_packet_items"]
    required = required_packet_items(record["mode"])
    missing = [code for code in required if code not in items]
    if missing:
        fail("ERR_HANDOFF_PACKET_INCOMPLETE",
             "The handoff packet is missing %s." % ", ".join(missing))
    # Step 1: measured while the case is still TRANSFER_INITIATED.
    dido = None
    if case is not None:
        dido = db.floor_minutes(db.parse_iso(case["door_at"]), db.now_dt())
        record["door_in_door_out_minutes"] = dido
    # Step 2
    record["handoff_packet_items"] = list(items)
    record["handoff_packet_complete"] = True
    # Step 3
    record["status"] = "HANDOFF_COMPLETE"
    record["handoff_completed_at"] = db.now_raw()
    db.touch(record)
    # Step 4: the case closes retaining the disposition its mode gave it.
    if case is not None:
        case["status"] = "CLOSED"
        db.touch(case)
    # Step 5: both decrements land before any posture is re-derived.
    origin = db.get("centers", record["origin_center_id"])
    destination = db.get("centers", record["destination_center_id"])
    if origin is not None:
        derive.recompute_open_case_count(origin)
    if destination is not None:
        derive.recompute_open_case_count(destination)
    # Step 6: origin first, then destination.
    if origin is not None:
        derive.recompute_ems_posture(origin)
    if destination is not None:
        derive.recompute_ems_posture(destination)
    # Step 7: judged on the realisation, not on the projection.
    if case is not None and dido is not None and dido > DIDO_TARGET_MIN:
        derive.open_system_deviation(
            case, "DIDO_EXCEEDED", "MAJOR",
            "Door-in-door-out time of %d minutes exceeded the %d minute target."
            % (dido, DIDO_TARGET_MIN))
    return resp.object_response(record)
