"""Surgery-center blocks and the procedure schedule (PRD 3.9)."""
from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("schedule", __name__)

LOT_FOR_PROCEDURE = {
    "BALLOON_SINUPLASTY": "BALLOON_DEVICE",
    "TYMPANOSTOMY_TUBES": "TYMPANOSTOMY_TUBE",
}
SCOPE_REQUIRED_TYPES = ("BALLOON_SINUPLASTY", "DIAGNOSTIC_ENDOSCOPY")
LIVE_BOOKINGS = ("SCHEDULED", "IN_PROGRESS")


# --- blocks ------------------------------------------------------------------
@bp.post("/surgery-center-blocks")
def create_block():
    common.begin(["PracticeAdmin"])
    values, _provided = shape.read_body([
        ("center_name", True, shape.v_string(1, 120), False),
        ("block_start_at", True, shape.v_instant(), False),
        ("block_end_at", True, shape.v_instant(), False),
        ("max_concurrent_cases", False, shape.v_int(1, 6), False),
        ("overnight_capable", False, shape.v_bool(), False),
    ])
    start = store.parse_instant(values["block_start_at"])
    end = store.parse_instant(values["block_end_at"])
    if end <= start:
        shape.bad("block_end_at must fall strictly after block_start_at")
    rooms = values.get("max_concurrent_cases", 2)
    duration = store.whole_minutes_between(start, end)
    row = common.new_row("surgery_center_blocks", {
        "center_name": values["center_name"],
        "block_start_at": values["block_start_at"],
        "block_end_at": values["block_end_at"],
        "max_concurrent_cases": rooms,
        "overnight_capable": values.get("overnight_capable", False),
        "booked_case_count": 0,
        "booked_minutes": 0,
        "capacity_minutes": duration * rooms,
        "utilization_bps": 0,
        "status": "OPEN",
    })
    return envelope.created(common.public("surgery_center_blocks", row))


@bp.get("/surgery-center-blocks/<block_id>")
def read_block(block_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("surgery_center_blocks", block_id)
    return envelope.ok(common.public("surgery_center_blocks", row))


@bp.get("/surgery-center-blocks")
def list_blocks():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "status": shape.q_enum(calc.BLOCK_STATUSES),
        "overnight_capable": shape.q_bool(),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("surgery_center_blocks",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("surgery_center_blocks", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/surgery-center-blocks/<block_id>/close")
def close_block(block_id):
    common.begin(["PracticeAdmin"])
    shape.no_body()
    block = common.find("surgery_center_blocks", block_id)
    if block["status"] not in ("OPEN", "FULL"):
        raise ApiError("ERR_BLOCK_STATE_INVALID")
    block["status"] = "CLOSED"
    common.touch(block)
    return envelope.ok(common.public("surgery_center_blocks", block))


# --- booking helpers ---------------------------------------------------------
def _scope_bookings(scope_id, exclude_id=None):
    out = []
    for booking in store.rows("procedure_bookings"):
        if booking["endoscope_asset_id"] != scope_id:
            continue
        if booking["status"] not in LIVE_BOOKINGS:
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        out.append(booking)
    return out


def _check_scope_intervals(scope_id, start, end):
    others = _scope_bookings(scope_id)
    for booking in others:
        other_start = store.parse_instant(booking["start_at"])
        other_end = store.parse_instant(booking["end_at"])
        # both endpoints inclusive: bookings that merely touch already conflict
        if start <= other_end and other_start <= end:
            raise ApiError("ERR_SCOPE_INTERVAL_CONFLICT")
    prior_end = None
    next_start = None
    for booking in others:
        other_start = store.parse_instant(booking["start_at"])
        other_end = store.parse_instant(booking["end_at"])
        if other_end < start and (prior_end is None or other_end > prior_end):
            prior_end = other_end
        if other_start > end and (next_start is None or other_start < next_start):
            next_start = other_start
    buffer_minutes = calc.REPROCESSING_BUFFER_MINUTES
    if prior_end is not None and start < store.plus_minutes(prior_end, buffer_minutes):
        raise ApiError("ERR_REPROCESSING_BUFFER_VIOLATION")
    if next_start is not None and store.plus_minutes(end, buffer_minutes) > next_start:
        raise ApiError("ERR_REPROCESSING_BUFFER_VIOLATION")


def _check_block_capacity(block, start, end, duration, exclude_id=None):
    if block["booked_minutes"] + duration > block["capacity_minutes"]:
        raise ApiError("ERR_BLOCK_CAPACITY_EXCEEDED")
    intervals = []
    for booking in store.rows("procedure_bookings"):
        if booking["surgery_center_block_id"] != block["id"]:
            continue
        if booking["status"] not in calc.BLOCK_COUNTED_BOOKINGS:
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        other_start = store.parse_instant(booking["start_at"])
        other_end = store.parse_instant(booking["end_at"])
        if other_start < end and start < other_end:
            intervals.append((other_start, other_end))
    instants = [start]
    for other_start, _other_end in intervals:
        if start < other_start < end:
            instants.append(other_start)
    for instant in instants:
        live = 1
        for other_start, other_end in intervals:
            if other_start <= instant < other_end:
                live += 1
        if live > block["max_concurrent_cases"]:
            raise ApiError("ERR_BLOCK_CAPACITY_EXCEEDED")


def _lot_blocked(lot):
    if lot["status"] == "QUARANTINED":
        return True
    expires = store.parse_instant(lot["expires_at"])
    return expires is not None and store.now() >= expires


def _self_pay(case):
    patient = store.db["patients"][case["patient_id"]]
    policy = common.policy_of_patient(patient)
    return not policy["requires_prior_auth"]


# --- bookings ----------------------------------------------------------------
@bp.post("/procedure-bookings")
def create_booking():
    common.begin(["PracticeAdmin", "Otolaryngologist"])
    values, provided = shape.read_body([
        ("patient_id", True, shape.v_ref(), False),
        ("procedure_type", True, shape.v_enum(calc.PROCEDURE_TYPES), False),
        ("venue", True, shape.v_enum(calc.VENUES), False),
        ("start_at", True, shape.v_instant(), False),
        ("end_at", True, shape.v_instant(), False),
        ("physician_user_id", True, shape.v_string(1, 120), False),
        ("sinuplasty_case_id", False, shape.v_ref(), True),
        ("endoscope_asset_id", False, shape.v_ref(), True),
        ("surgery_center_block_id", False, shape.v_ref(), True),
        ("supply_lot_id", False, shape.v_ref(), True),
        ("planned_device_count", False, shape.v_int(0, 6), False),
    ])
    start = store.parse_instant(values["start_at"])
    end = store.parse_instant(values["end_at"])
    if end <= start:
        shape.bad("end_at must fall strictly after start_at")
    procedure_type = values["procedure_type"]
    planned = values.get("planned_device_count", 0)

    case_id = values.get("sinuplasty_case_id")
    scope_id = values.get("endoscope_asset_id")
    block_id = values.get("surgery_center_block_id")
    lot_id = values.get("supply_lot_id")

    def presence(name, value, required):
        if required and value is None:
            shape.bad("%s is required for this request" % name)
        if not required and value is not None:
            shape.bad("%s must be null for this request" % name)

    presence("sinuplasty_case_id", case_id,
             procedure_type == "BALLOON_SINUPLASTY")
    presence("endoscope_asset_id", scope_id,
             procedure_type in SCOPE_REQUIRED_TYPES)
    presence("surgery_center_block_id", block_id,
             values["venue"] == "SURGERY_CENTER")
    presence("supply_lot_id", lot_id, planned > 0)

    # rung 5, in the order the input list declares the references
    patient = common.find_ref("patients", values["patient_id"])
    case = None
    scope = None
    block = None
    lot = None
    if case_id is not None:
        case = common.find_ref("sinuplasty_cases", case_id)
    if scope_id is not None:
        scope = common.find_ref("endoscope_assets", scope_id)
    if block_id is not None:
        block = common.find_ref("surgery_center_blocks", block_id)
    if lot_id is not None:
        lot = common.find_ref("supply_lots", lot_id)

    # rung 7
    if case is not None:
        if case["status"] == "AUTHORIZED":
            pass
        elif case["status"] == "DOCUMENTED" and _self_pay(case):
            pass
        else:
            raise ApiError("ERR_CASE_STATE_INVALID")
    if lot is not None and _lot_blocked(lot):
        raise ApiError("ERR_LOT_STATE_INVALID")
    if scope is not None and scope["status"] == "RETIRED":
        raise ApiError("ERR_SCOPE_STATE_INVALID")

    # rung 10
    overnight = (procedure_type == "TONSILLECTOMY"
                 and calc.age_months(patient) < calc.PEDIATRIC_VENUE_AGE_MONTHS)
    if overnight and block is not None and not block["overnight_capable"]:
        raise ApiError("ERR_OVERNIGHT_CAPABILITY_REQUIRED")

    # rung 11
    if scope is not None:
        _check_scope_intervals(scope["id"], start, end)
    if block is not None:
        block_start = store.parse_instant(block["block_start_at"])
        block_end = store.parse_instant(block["block_end_at"])
        if start < block_start or end > block_end:
            raise ApiError("ERR_BLOCK_WINDOW_EXCEEDED")
    if (procedure_type == "BALLOON_SINUPLASTY" and case is not None
            and case["status"] == "AUTHORIZED"):
        expires = store.parse_instant(case["auth_expires_at"])
        if expires is not None and store.now() >= expires:
            # the one rejection that writes before it refuses
            case["status"] = "AUTH_EXPIRED"
            common.touch(case)
            raise ApiError("ERR_AUTHORIZATION_EXPIRED")

    # rung 12
    if lot is not None:
        expected_item = LOT_FOR_PROCEDURE.get(procedure_type)
        if expected_item is not None and lot["item_type"] != expected_item:
            raise ApiError("ERR_LOT_ITEM_TYPE_MISMATCH")
    if case is not None and case["patient_id"] != patient["id"]:
        raise ApiError("ERR_CASE_PATIENT_MISMATCH")

    # rung 13
    if case is not None and case["candidacy_status"] != "ELIGIBLE":
        raise ApiError("ERR_CANDIDACY_NOT_ELIGIBLE")
    if (procedure_type in ("TONSILLECTOMY", "TYMPANOSTOMY_TUBES")
            and values["venue"] == "IN_OFFICE_SUITE"
            and calc.age_months(patient) < calc.PEDIATRIC_VENUE_AGE_MONTHS):
        raise ApiError("ERR_PEDIATRIC_VENUE_REQUIRED")

    # rung 14
    duration = store.whole_minutes_between(start, end)
    if lot is not None and calc.lot_available(lot) < planned:
        raise ApiError("ERR_SUPPLY_EXHAUSTED")
    if (procedure_type == "BALLOON_SINUPLASTY" and case is not None
            and planned > case["authorized_device_count"]):
        raise ApiError("ERR_DEVICE_COUNT_EXCEEDS_AUTHORIZATION")
    if block is not None:
        _check_block_capacity(block, start, end, duration)
        if block["status"] in ("FULL", "CLOSED"):
            raise ApiError("ERR_BLOCK_NOT_OPEN")

    row = common.new_row("procedure_bookings", {
        "patient_id": patient["id"],
        "sinuplasty_case_id": case_id,
        "endoscope_asset_id": scope_id,
        "surgery_center_block_id": block_id,
        "supply_lot_id": lot_id,
        "procedure_type": procedure_type,
        "venue": values["venue"],
        "start_at": values["start_at"],
        "end_at": values["end_at"],
        "duration_minutes": duration,
        "physician_user_id": values["physician_user_id"],
        "planned_device_count": planned,
        "devices_used_count": 0,
        "overnight_observation_required": overnight,
        "requires_physician_presence":
            patient["supervision_tier"] == "PHYSICIAN_PRESENT",
        "attending_physician_user_id": None,
        "scope_reassignment_required": False,
        "supply_shortfall_flag": False,
        "status": "SCHEDULED",
        "cancel_reason": None,
    })

    if lot is not None:
        common.lot_exhaustion_check(lot)
        common.touch(lot)
    if block is not None:
        calc.recompute_block(block)
        common.touch(block)
    if case is not None and procedure_type == "BALLOON_SINUPLASTY":
        case["_pre_schedule_status"] = case["status"]
        case["status"] = "SCHEDULED"
        common.touch(case)
    return envelope.created(common.public("procedure_bookings", row))


@bp.get("/procedure-bookings/<booking_id>")
def read_booking(booking_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("procedure_bookings", booking_id)
    return envelope.ok(common.public("procedure_bookings", row))


@bp.get("/procedure-bookings")
def list_bookings():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "patient_id": shape.q_string(),
        "sinuplasty_case_id": shape.q_string(),
        "endoscope_asset_id": shape.q_string(),
        "surgery_center_block_id": shape.q_string(),
        "supply_lot_id": shape.q_string(),
        "status": shape.q_enum(calc.BOOKING_STATUSES),
        "procedure_type": shape.q_enum(calc.PROCEDURE_TYPES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("procedure_bookings",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("procedure_bookings", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/procedure-bookings/<booking_id>/start")
def start_booking(booking_id):
    ctx = common.begin(["Otolaryngologist"])
    values, provided = shape.read_body([
        ("attending_physician_user_id", False, shape.v_string(1, 120), True),
    ])
    booking = common.find("procedure_bookings", booking_id)
    # rung 7
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_BOOKING_STATE_INVALID")
    # rung 9
    if ctx.user_id != booking["physician_user_id"]:
        raise ApiError("ERR_PHYSICIAN_MISMATCH")
    attending = values.get("attending_physician_user_id")
    # rung 10
    if booking["requires_physician_presence"] and not attending:
        raise ApiError("ERR_ATTENDING_PHYSICIAN_REQUIRED")

    scope = None
    if booking["endoscope_asset_id"] is not None:
        scope = store.db["endoscope_assets"][booking["endoscope_asset_id"]]
        # rung 11
        if not calc.scope_shelf_valid(scope):
            raise ApiError("ERR_HLD_EXPIRED")
        # rung 12 — RETIRED is deliberately excluded and handled one rung higher
        if scope["status"] != "READY" and scope["status"] != "RETIRED":
            raise ApiError("ERR_SCOPE_NOT_READY")
    # rung 13
    if booking["scope_reassignment_required"]:
        raise ApiError("ERR_SCOPE_REASSIGNMENT_REQUIRED")
    if booking["procedure_type"] == "BALLOON_SINUPLASTY":
        case = store.db["sinuplasty_cases"][booking["sinuplasty_case_id"]]
        patient = store.db["patients"][case["patient_id"]]
        policy = common.policy_of_patient(patient)
        if case["pinned_policy_version"] != policy["version"]:
            raise ApiError("ERR_POLICY_VERSION_DRIFT")

    booking["status"] = "IN_PROGRESS"
    if attending is not None:
        booking["attending_physician_user_id"] = attending
    common.touch(booking)
    if scope is not None:
        scope["status"] = "IN_USE"
        scope["last_used_by_user_id"] = booking["physician_user_id"]
        common.touch(scope)
    return envelope.ok(common.public("procedure_bookings", booking))


@bp.post("/procedure-bookings/<booking_id>/complete")
def complete_booking(booking_id):
    common.begin(["Otolaryngologist"])
    values, _provided = shape.read_body([
        ("devices_used_count", True, shape.v_int(0, 6), False),
    ])
    booking = common.find("procedure_bookings", booking_id)
    if booking["status"] != "IN_PROGRESS":
        raise ApiError("ERR_BOOKING_STATE_INVALID")
    used = values["devices_used_count"]
    if used > booking["planned_device_count"]:
        raise ApiError("ERR_BOOKING_STATE_INVALID")

    booking["status"] = "COMPLETED"
    booking["devices_used_count"] = used
    common.touch(booking)

    if booking["supply_lot_id"] is not None:
        lot = store.db["supply_lots"][booking["supply_lot_id"]]
        lot["quantity_on_hand"] = lot["quantity_on_hand"] - used
        lot["quantity_consumed"] = lot["quantity_consumed"] + used
        common.lot_replenish_check(lot)
        common.touch(lot)
    if booking["endoscope_asset_id"] is not None:
        scope = store.db["endoscope_assets"][booking["endoscope_asset_id"]]
        scope["status"] = "SOILED"
        scope["hld_expires_at"] = None
        common.touch(scope)
    if booking["sinuplasty_case_id"] is not None:
        case = store.db["sinuplasty_cases"][booking["sinuplasty_case_id"]]
        if case["status"] == "SCHEDULED":
            case["status"] = "COMPLETED"
            common.touch(case)
    return envelope.ok(common.public("procedure_bookings", booking))


@bp.post("/procedure-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    common.begin(["PracticeAdmin", "Otolaryngologist"])
    values, _provided = shape.read_body([
        ("cancel_reason", True, shape.v_enum(calc.CANCEL_REASONS), False),
    ])
    booking = common.find("procedure_bookings", booking_id)
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_BOOKING_STATE_INVALID")

    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = values["cancel_reason"]
    common.touch(booking)

    if booking["supply_lot_id"] is not None:
        lot = store.db["supply_lots"][booking["supply_lot_id"]]
        common.lot_replenish_check(lot)
        common.touch(lot)
    if booking["surgery_center_block_id"] is not None:
        block = store.db["surgery_center_blocks"][booking["surgery_center_block_id"]]
        calc.recompute_block(block)
        common.touch(block)
    if booking["sinuplasty_case_id"] is not None:
        case = store.db["sinuplasty_cases"][booking["sinuplasty_case_id"]]
        if case["status"] == "SCHEDULED":
            origin = case.get("_pre_schedule_status")
            if origin not in ("AUTHORIZED", "DOCUMENTED"):
                origin = "DOCUMENTED" if _self_pay(case) else "AUTHORIZED"
            case["status"] = origin
            common.touch(case)
    return envelope.ok(common.public("procedure_bookings", booking))
