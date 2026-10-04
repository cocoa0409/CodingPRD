"""Flight endpoints (PRD 3.5): filing, data-exchange updates, cancellation,
per-flight slot history."""

from flask import Blueprint, request

from constants import FLIGHT_OPS_UPDATE_TARGETS, ROLE_OPERATOR, ROLES
from errors import ApiError
from ledger import (
    ensure_ledger,
    recompute_fair_shares,
    write_transaction,
)
from serialize import serialize_flight, serialize_slot
from storage import DB, create_entity, get_clock, touch
from util import (
    body_json,
    opt_dt,
    opt_enum,
    paginate,
    req_dt,
    req_int,
    req_str,
    success_object,
)
from validation import (
    auth_context,
    get_facility,
    get_flight,
    get_operator,
    require_roles,
)

bp = Blueprint("flights", __name__)


def _require_operator_owns(operator_id):
    """Priority 3: an Operator caller acts only under its own operator id."""
    user_id = request.headers.get("X-User-ID")
    if user_id != operator_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "X-User-ID must equal the owning operator id",
        )


@bp.route("/atfm/operators/<operator_id>/flights", methods=["POST"])
def file_flight(operator_id):
    auth_context()
    require_roles(ROLE_OPERATOR)
    _require_operator_owns(operator_id)
    operator = get_operator(operator_id)
    body = body_json()
    designator = req_str(body, "designator")
    origin = req_str(body, "origin")
    arrival_facility_id = req_str(body, "arrival_facility_id")
    scheduled_arrival = req_dt(body, "scheduled_arrival")
    estimated_arrival = opt_dt(body, "estimated_arrival")
    facility = get_facility(arrival_facility_id)
    # Priority 16: the arrival facility must be an AIRPORT.
    if facility["facility_type"] != "AIRPORT":
        raise ApiError(
            "ERR_FACILITY_TYPE_NOT_AIRPORT",
            "arrival_facility_id must reference an AIRPORT facility",
        )
    rec = create_entity(
        "flights",
        {
            "operator_id": operator["id"],
            "designator": designator,
            "origin": origin,
            "arrival_facility_id": facility["id"],
            "scheduled_arrival": scheduled_arrival,
            "estimated_arrival": (
                estimated_arrival if estimated_arrival is not None else scheduled_arrival
            ),
            "controlled_arrival": None,
            "last_eta_reported_at": get_clock(),
            "ops_status": "SCHEDULED",
            "control_status": "UNCONTROLLED",
            "is_overflow": False,
            "provisional_delay_minutes": 0,
            "final_delay_minutes": None,
            "_tmi_id": None,
        },
    )
    return success_object(serialize_flight(rec), 201)


@bp.route("/atfm/flights", methods=["GET"])
def list_flights():
    auth_context()
    require_roles(*ROLES)
    operator_filter = request.args.get("operator_id")
    facility_filter = request.args.get("arrival_facility_id")
    ops_filter = request.args.get("ops_status")
    control_filter = request.args.get("control_status")
    rows = [
        f
        for f in DB["flights"].values()
        if (operator_filter is None or f["operator_id"] == operator_filter)
        and (facility_filter is None or f["arrival_facility_id"] == facility_filter)
        and (ops_filter is None or f["ops_status"] == ops_filter)
        and (control_filter is None or f["control_status"] == control_filter)
    ]
    rows.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return paginate([serialize_flight(f) for f in rows])


@bp.route("/atfm/flights/<flight_id>", methods=["GET"])
def fetch_flight(flight_id):
    auth_context()
    require_roles(*ROLES)
    return success_object(serialize_flight(get_flight(flight_id)))


@bp.route("/atfm/flights/<flight_id>/updates", methods=["POST"])
def update_flight(flight_id):
    auth_context()
    require_roles(ROLE_OPERATOR)
    flight = get_flight(flight_id)
    _require_operator_owns(flight["operator_id"])
    body = body_json()
    expected_version = req_int(body, "expected_flight_version")
    has_eta = "new_eta" in body and body["new_eta"] is not None
    has_ops = "new_ops_status" in body and body["new_ops_status"] is not None
    if not has_eta and not has_ops:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "an update must carry new_eta, new_ops_status, or both",
        )
    new_eta = opt_dt(body, "new_eta") if has_eta else None
    new_ops = (
        opt_enum(body, "new_ops_status", FLIGHT_OPS_UPDATE_TARGETS) if has_ops else None
    )
    # OCC (PRD 2.7): checked before the state preconditions per the flight
    # state machine's listed precondition order.
    if expected_version != flight["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_flight_version %s does not match current version %s"
            % (expected_version, flight["version"]),
            412,
        )
    if new_ops is not None:
        # Ops advance follows the single chain SCHEDULED -> AIRBORNE -> LANDED.
        legal = (
            (new_ops == "AIRBORNE" and flight["ops_status"] == "SCHEDULED")
            or (new_ops == "LANDED" and flight["ops_status"] == "AIRBORNE")
        )
        if not legal:
            raise ApiError(
                "ERR_INVALID_STATE",
                "cannot advance ops_status from %s to %s"
                % (flight["ops_status"], new_ops),
            )
    else:
        # ETA-only reports are legal while SCHEDULED or AIRBORNE.
        if flight["ops_status"] not in ("SCHEDULED", "AIRBORNE"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "updates against a %s flight are rejected" % flight["ops_status"],
            )
    if new_eta is not None:
        flight["estimated_arrival"] = new_eta
        flight["last_eta_reported_at"] = get_clock()
    if new_ops is not None:
        flight["ops_status"] = new_ops
    touch(flight)
    return success_object(serialize_flight(flight))


@bp.route("/atfm/flights/<flight_id>/cancel", methods=["POST"])
def cancel_flight(flight_id):
    auth_context()
    require_roles(ROLE_OPERATOR)
    flight = get_flight(flight_id)
    _require_operator_owns(flight["operator_id"])
    if flight["ops_status"] in ("AIRBORNE", "LANDED"):
        raise ApiError(
            "ERR_FLIGHT_NOT_CANCELLABLE",
            "an %s flight cannot be cancelled" % flight["ops_status"],
        )
    if flight["ops_status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", "only a SCHEDULED flight can be cancelled"
        )
    # Release cascade (PRD 3.5): fires when the cancelled flight holds an
    # ASSIGNED slot.
    if flight["control_status"] == "SLOTTED":
        tmi_id = flight.get("_tmi_id")
        slot = None
        for candidate in DB["slots"].values():
            if (
                candidate["tmi_id"] == tmi_id
                and candidate["status"] == "ASSIGNED"
                and candidate["assigned_flight_id"] == flight["id"]
            ):
                slot = candidate
                break
        prior = flight["provisional_delay_minutes"]
        from_time = flight["controlled_arrival"]
        if slot is not None:
            slot["status"] = "RELEASED"
            slot["assigned_flight_id"] = None
            touch(slot)
        write_transaction(
            tmi_id,
            slot["id"] if slot is not None else None,
            flight["id"],
            flight["operator_id"],
            "RELEASE",
            from_time,
            None,
            -prior,
        )
        flight["controlled_arrival"] = None
        flight["control_status"] = "UNCONTROLLED"
        flight["provisional_delay_minutes"] = 0
        flight["is_overflow"] = False
        flight["_tmi_id"] = None
        ledger = ensure_ledger(flight["operator_id"], tmi_id)
        ledger["attributed_delay_minutes"] -= prior
        ledger["flight_count"] -= 1
        touch(ledger)
        recompute_fair_shares(tmi_id)
    flight["ops_status"] = "CANCELLED"
    touch(flight)
    return success_object(serialize_flight(flight))


@bp.route("/atfm/flights/<flight_id>/slots", methods=["GET"])
def list_flight_slots(flight_id):
    auth_context()
    require_roles(*ROLES)
    flight = get_flight(flight_id)
    rows = [
        s
        for s in DB["slots"].values()
        if s["assigned_flight_id"] == flight["id"]
        or s["original_flight_id"] == flight["id"]
    ]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return paginate([serialize_slot(s) for s in rows])
