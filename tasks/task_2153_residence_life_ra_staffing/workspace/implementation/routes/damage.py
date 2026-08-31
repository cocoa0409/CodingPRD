"""Room inspections, damage assessment and the bursar ledger."""
from flask import Blueprint, g

import calc
import derive
import responses
import services
import store
import validators as V
from auth import endpoint, explicit_touch, require_owner
from constants import (
    API_PREFIX, APPEAL_WINDOW_DAYS, COMPONENT_CODES, INSPECTION_TYPES,
)
from errors import ApiError
from store import DB

bp = Blueprint("damage", __name__)


def _validate_damage_lines(raw):
    lines = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "damage_lines entries must be objects.")
        code = V.s_enum(item, "component_code", COMPONENT_CODES)
        quantity = V.s_int(item, "quantity", 1, 10)
        lines.append({"component_code": code, "quantity": quantity})
    return lines


@bp.route("%s/room-inspections" % API_PREFIX, methods=["POST"])
@endpoint(["ResidentAssistant"])
def create_inspection():
    body = V.body()
    room_id = V.s_id(body, "room_id")
    inspection_type = V.s_enum(body, "inspection_type", INSPECTION_TYPES)
    scheduled_for = V.s_dt(body, "scheduled_for")
    expected_version = V.s_int(body, "expected_room_version", 0)
    ra = services.acting_ra()
    room = store.get("rooms", room_id)
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    if expected_version != room["version"]:
        raise ApiError("ERR_STALE_ROOM_VERSION")
    services.ra_active_gate(ra)
    if ra.get("assigned_floor_id") != room["floor_id"]:
        raise ApiError("ERR_FLOOR_MISMATCH")
    for other in store.all_rows("inspections"):
        if (other["room_id"] == room_id
                and other["inspection_type"] == inspection_type
                and other["status"] == "SCHEDULED"):
            other["status"] = "SUPERSEDED"
    row = store.insert("inspections", "RoomInspection", {
        "room_id": room_id,
        "inspector_ra_id": ra["id"],
        "inspection_type": inspection_type,
        "scheduled_for": store.fmt_iso(scheduled_for),
        "status": "SCHEDULED",
        "condition_score": None,
        "damage_lines": [],
        "responsible_student_id": None,
        "damage_charge_id": None,
        "completed_at": None,
    })
    explicit_touch(room)
    return responses.obj(row, 201)


@bp.route("%s/room-inspections/<inspection_id>/completion" % API_PREFIX, methods=["POST"])
@endpoint(["ResidentAssistant"])
def complete_inspection(inspection_id):
    inspection = V.must_get("RoomInspection", inspection_id)
    require_owner(inspection["inspector_ra_id"])
    body = V.body()
    score = V.s_int(body, "condition_score", 0, 100)
    raw_lines = V.s_list(body, "damage_lines")
    responsible_id = V.s_id(body, "responsible_student_id", required=False)
    lines = _validate_damage_lines(raw_lines)
    if responsible_id is not None and store.get("students", responsible_id) is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    ra = DB["ras"].get(inspection["inspector_ra_id"])
    if ra is None:
        raise ApiError("ERR_RA_NOT_FOUND")
    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    services.ra_certified_gate(ra)
    services.ra_active_gate(ra)
    room = DB["rooms"].get(inspection["room_id"])
    if room is not None and ra.get("assigned_floor_id") != room["floor_id"]:
        raise ApiError("ERR_FLOOR_MISMATCH")

    inspection["status"] = "COMPLETED"
    inspection["condition_score"] = score
    inspection["damage_lines"] = lines
    inspection["completed_at"] = store.now_iso()
    inspection["responsible_student_id"] = responsible_id

    if lines:
        student_id = responsible_id
        if student_id is None and room is not None:
            occupants = [s for s in store.all_rows("students")
                         if s.get("current_room_id") == room["id"]]
            if len(occupants) == 1:
                student_id = occupants[0]["id"]
        inspection["responsible_student_id"] = student_id
        charge = store.insert("charges", "DamageCharge", {
            "inspection_id": inspection["id"],
            "student_id": student_id,
            "provisional_subtotal_cents": calc.provisional_subtotal(lines),
            "assessed_subtotal_cents": None,
            "depreciation_rate": None,
            "admin_fee_cents": None,
            "hardship_relief_cents": None,
            "final_amount_cents": None,
            "status": "PENDING",
            "billed_at": None,
            "appeal_deadline_at": None,
            "appeal_reason": None,
            "appeal_outcome": None,
        })
        inspection["damage_charge_id"] = charge["id"]
    return responses.obj(inspection)


def _settle_amounts(charge, gross):
    student = DB["students"].get(charge["student_id"])
    hardship = bool(student and student.get("financial_hardship_flag"))
    admin_fee, relief, final_amount = calc.settlement(gross, hardship)
    charge["assessed_subtotal_cents"] = gross
    charge["admin_fee_cents"] = admin_fee
    charge["hardship_relief_cents"] = relief
    charge["final_amount_cents"] = final_amount
    charge["billed_at"] = store.now_iso()
    charge["appeal_deadline_at"] = store.fmt_iso(
        store.now() + store.days(APPEAL_WINDOW_DAYS)
    )


@bp.route("%s/damage-charges/<charge_id>/billing" % API_PREFIX, methods=["POST"])
@endpoint(["BursarOfficer"])
def bill_charge(charge_id):
    charge = V.must_get("DamageCharge", charge_id)
    body = V.body()
    V.s_str(body, "note", required=False)
    if charge["status"] != "PENDING":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    student = DB["students"].get(charge["student_id"])
    if student is not None and derive.student_standing(student) == "SUSPENDED":
        raise ApiError("ERR_STUDENT_ON_PROBATION")
    inspection = DB["inspections"].get(charge["inspection_id"])
    lines = inspection["damage_lines"] if inspection else []
    room = DB["rooms"].get(inspection["room_id"]) if inspection else None
    rate = calc.depreciation_rate(room) if room else calc.Decimal(0)
    charge["depreciation_rate"] = float(rate)
    _settle_amounts(charge, calc.assessed_subtotal(lines, rate))
    charge["status"] = "BILLED"
    return responses.obj(charge)


@bp.route("%s/damage-charges/<charge_id>/appeal" % API_PREFIX, methods=["POST"])
@endpoint(["Student"])
def appeal_charge(charge_id):
    charge = V.must_get("DamageCharge", charge_id)
    require_owner(charge["student_id"])
    body = V.body()
    reason = V.s_str(body, "reason")
    if charge["status"] != "BILLED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    if charge.get("appeal_outcome") is not None:
        raise ApiError("ERR_APPEAL_ALREADY_RESOLVED")
    deadline = charge.get("appeal_deadline_at")
    if deadline is not None and store.now() > store.parse_iso(deadline):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    charge["status"] = "APPEALED"
    charge["appeal_reason"] = reason
    return responses.obj(charge)


@bp.route("%s/damage-charges/<charge_id>/appeal-resolution" % API_PREFIX, methods=["POST"])
@endpoint(["BursarOfficer"])
def resolve_appeal(charge_id):
    charge = V.must_get("DamageCharge", charge_id)
    body = V.body()
    action = V.s_enum(body, "action", ("ADJUST", "UPHOLD"))
    adjusted = None
    if action == "ADJUST":
        adjusted = V.s_int(body, "adjusted_subtotal_cents", 0)
    if charge["status"] != "APPEALED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    if action == "ADJUST":
        if adjusted > (charge["assessed_subtotal_cents"] or 0):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "adjusted_subtotal_cents must not exceed assessed_subtotal_cents.",
            )
        _settle_amounts(charge, adjusted)
        charge["appeal_outcome"] = "ADJUSTED"
    else:
        charge["appeal_outcome"] = "UPHELD"
        charge["billed_at"] = store.now_iso()
        charge["appeal_deadline_at"] = store.fmt_iso(
            store.now() + store.days(APPEAL_WINDOW_DAYS)
        )
    charge["status"] = "BILLED"
    return responses.obj(charge)


@bp.route("%s/damage-charges/<charge_id>/settlement" % API_PREFIX, methods=["POST"])
@endpoint(["BursarOfficer"])
def settle_charge(charge_id):
    charge = V.must_get("DamageCharge", charge_id)
    body = V.body()
    action = V.s_enum(body, "action", ("SETTLE", "WAIVE"))
    V.s_str(body, "note", required=False)
    if action == "SETTLE":
        if charge["status"] != "BILLED":
            raise ApiError("ERR_CHARGE_STATE_INVALID")
        charge["status"] = "SETTLED"
    else:
        if charge["status"] == "BILLED":
            charge["status"] = "WAIVED"
        elif charge["status"] == "PENDING":
            charge["status"] = "VOID"
        else:
            raise ApiError("ERR_CHARGE_STATE_INVALID")
    return responses.obj(charge)
