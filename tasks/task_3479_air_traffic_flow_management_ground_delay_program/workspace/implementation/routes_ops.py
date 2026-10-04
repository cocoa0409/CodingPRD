"""CDM substitution and compression-run endpoints (PRD 3.5)."""

from flask import Blueprint, request

from constants import (
    FLIGHT_DATA_FRESHNESS_SECONDS,
    ROLE_FLOW_MANAGER,
    ROLE_OPERATOR,
    ROLES,
    SUBSTITUTION_MAX_SHIFT_MINUTES,
)
from errors import ApiError
from ops import assigned_slot_of, execute_substitution, run_compression
from serialize import serialize_compression_run, serialize_transaction
from storage import DB
from util import body_json, opt_str, paginate, req_str, success_object
from validation import (
    auth_context,
    get_tmi,
    require_roles,
    tmi_require_active,
)
from storage import get_clock

bp = Blueprint("program_ops", __name__)


@bp.route("/atfm/tmis/<tmi_id>/substitutions", methods=["POST"])
def create_substitution(tmi_id):
    auth_context()
    require_roles(ROLE_OPERATOR)
    body = body_json()
    flight_id_1 = req_str(body, "flight_id_1")
    flight_id_2 = req_str(body, "flight_id_2")
    note = opt_str(body, "note")
    # Priority 3: ownership over every resolvable flight referenced in the body.
    user_id = request.headers.get("X-User-ID")
    flight1 = DB["flights"].get(flight_id_1)
    flight2 = DB["flights"].get(flight_id_2)
    for flight in (flight1, flight2):
        if flight is not None and flight["operator_id"] != user_id:
            raise ApiError(
                "ERR_NOT_RESOURCE_OWNER",
                "substitution flights must be owned by the acting operator",
            )
    # Priority 4: existence — path tmi first, then body flight references.
    tmi = get_tmi(tmi_id)
    if flight1 is None:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", "flight %s not found" % flight_id_1)
    if flight2 is None:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", "flight %s not found" % flight_id_2)
    # Priority 5: substitution needs an ACTIVE TMI.
    tmi_require_active(tmi)
    # Priority 11: CDM data freshness — both flights must have reported within
    # FLIGHT_DATA_FRESHNESS_SECONDS (3600) of the logical clock.
    clock = get_clock()
    for flight in (flight1, flight2):
        age = (clock - flight["last_eta_reported_at"]).total_seconds()
        if age > FLIGHT_DATA_FRESHNESS_SECONDS:
            raise ApiError(
                "ERR_STALE_FLIGHT_DATA",
                "flight %s last ETA report is older than %d seconds"
                % (flight["id"], FLIGHT_DATA_FRESHNESS_SECONDS),
            )
    # Priority 18 sub-order: same-flight, then in-program, then shift.
    if flight_id_1 == flight_id_2:
        raise ApiError(
            "ERR_SUBSTITUTION_SAME_FLIGHT", "flight_id_1 must differ from flight_id_2"
        )
    slot1 = assigned_slot_of(tmi["id"], flight1["id"])
    slot2 = assigned_slot_of(tmi["id"], flight2["id"])
    if slot1 is None or slot2 is None:
        raise ApiError(
            "ERR_FLIGHT_NOT_IN_PROGRAM",
            "both flights must hold ASSIGNED slots in this TMI",
        )
    # Each flight may shift by at most SUBSTITUTION_MAX_SHIFT_MINUTES (120).
    for flight, other_slot in ((flight1, slot2), (flight2, slot1)):
        shift = abs(
            (other_slot["slot_time"] - flight["scheduled_arrival"]).total_seconds()
        )
        if shift > SUBSTITUTION_MAX_SHIFT_MINUTES * 60:
            raise ApiError(
                "ERR_SUBSTITUTION_SHIFT_EXCEEDED",
                "substitution would move flight %s more than %d minutes from schedule"
                % (flight["id"], SUBSTITUTION_MAX_SHIFT_MINUTES),
            )
    txn = execute_substitution(tmi, flight1, flight2, note)
    return success_object(serialize_transaction(txn), 201)


@bp.route("/atfm/tmis/<tmi_id>/compression-runs", methods=["POST"])
def create_compression_run(tmi_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    tmi = get_tmi(tmi_id)
    tmi_require_active(tmi)
    # Compression is slot machinery and exists only on a GROUND_DELAY_PROGRAM.
    if tmi["tmi_type"] != "GROUND_DELAY_PROGRAM":
        raise ApiError(
            "ERR_TMI_TYPE_NOT_GDP",
            "compression runs apply only to a GROUND_DELAY_PROGRAM",
        )
    run = run_compression(tmi)
    return success_object(serialize_compression_run(run), 201)


@bp.route("/atfm/tmis/<tmi_id>/compression-runs", methods=["GET"])
def list_compression_runs(tmi_id):
    auth_context()
    require_roles(*ROLES)
    tmi = get_tmi(tmi_id)
    rows = [r for r in DB["compression_runs"].values() if r["tmi_id"] == tmi["id"]]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))  # oldest first
    return paginate([serialize_compression_run(r) for r in rows])
