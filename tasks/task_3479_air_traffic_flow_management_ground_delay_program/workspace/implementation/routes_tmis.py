"""TrafficManagementInitiative endpoints (PRD 3.4, 3.6, 3.9) and TMIRevision
creation/listing."""

from flask import Blueprint, request

from allocation import activate_allocation, reapply_allocation, slots_of
from capacity import enforce_capacity_gate
from constants import ROLE_COMMAND_CENTER_ADMIN, ROLE_FLOW_MANAGER, ROLES, TMI_TYPES
from errors import ApiError
from ledger import (
    delay_minutes_between,
    ensure_ledger,
    recompute_fair_shares,
    write_transaction,
)
from serialize import serialize_revision, serialize_tmi
from storage import DB, create_entity, create_record, get_clock, touch
from util import (
    body_json,
    opt_dt,
    opt_int,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
    success_object,
)
from validation import (
    auth_context,
    check_gdp_rate,
    check_rate_shape,
    check_window,
    get_facility,
    get_tmi,
    require_roles,
    tmi_require_active,
    tmi_terminal_guard,
    windows_overlap,
)

bp = Blueprint("tmis", __name__)

_GDP_FAMILY = ("GROUND_DELAY_PROGRAM", "GROUND_STOP")
_NONTERMINAL = ("PROPOSED", "PUBLISHED", "ACTIVE", "REVISING")


def _check_gdp_family_overlap(facility_id, tmi_type, start, end, exclude_id):
    """Priority 14: no other GDP/GS on the facility in a non-terminal status
    may overlap the candidate's half-open window. AFP/REROUTE are exempt."""
    if tmi_type not in _GDP_FAMILY:
        return
    for other in DB["tmis"].values():
        if (
            other["facility_id"] == facility_id
            and other["id"] != exclude_id
            and other["tmi_type"] in _GDP_FAMILY
            and other["status"] in _NONTERMINAL
            and windows_overlap(
                other["program_start"], other["program_end"], start, end
            )
        ):
            raise ApiError(
                "ERR_TMI_OVERLAP",
                "another non-terminal GDP/GROUND_STOP overlaps this facility window",
            )


@bp.route("/atfm/facilities/<facility_id>/tmis", methods=["POST"])
def propose_tmi(facility_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    facility = get_facility(facility_id)
    body = body_json()
    tmi_type = req_enum(body, "tmi_type", TMI_TYPES)
    program_start = req_dt(body, "program_start")
    program_end = req_dt(body, "program_end")
    raw_rate = opt_int(body, "controlled_rate", 0)
    # Priority 8 then 9: window well-formed, then program_end in the future.
    check_window(program_start, program_end)
    if not (program_end > get_clock()):
        raise ApiError(
            "ERR_PROGRAM_WINDOW_IN_PAST",
            "program_end must be strictly after the current logical clock",
        )
    # Priority 14: GDP-family exclusivity binds at proposal.
    _check_gdp_family_overlap(facility["id"], tmi_type, program_start, program_end, None)
    # Priority 15: per-type rate shape. REROUTE rates are ignored, stored 0.
    if tmi_type == "REROUTE":
        controlled_rate = 0
    else:
        check_rate_shape(tmi_type, raw_rate)
        controlled_rate = raw_rate
    # Capacity deliberately NOT checked at proposal (PRD 2.6 rule 20).
    rec = create_entity(
        "tmis",
        {
            "facility_id": facility["id"],
            "tmi_type": tmi_type,
            "program_start": program_start,
            "program_end": program_end,
            "controlled_rate": controlled_rate,
            "status": "PROPOSED",
            "proposed_by_user_id": request.headers.get("X-User-ID"),
            "published_by_user_id": None,
            "revision_count": 0,
            "activated_at": None,
            "_slot_count": 0,
            "_reserved_slots": 0,
        },
    )
    return success_object(serialize_tmi(rec), 201)


@bp.route("/atfm/facilities/<facility_id>/tmis", methods=["GET"])
def list_tmis(facility_id):
    auth_context()
    require_roles(*ROLES)
    facility = get_facility(facility_id)
    status_filter = request.args.get("status")
    type_filter = request.args.get("tmi_type")
    rows = [
        t
        for t in DB["tmis"].values()
        if t["facility_id"] == facility["id"]
        and (status_filter is None or t["status"] == status_filter)
        and (type_filter is None or t["tmi_type"] == type_filter)
    ]
    rows.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return paginate([serialize_tmi(t) for t in rows])


@bp.route("/atfm/tmis/<tmi_id>", methods=["GET"])
def fetch_tmi(tmi_id):
    auth_context()
    require_roles(*ROLES)
    return success_object(serialize_tmi(get_tmi(tmi_id)))


@bp.route("/atfm/tmis/<tmi_id>/publish", methods=["POST"])
def publish_tmi(tmi_id):
    auth_context()
    require_roles(ROLE_COMMAND_CENTER_ADMIN)
    tmi = get_tmi(tmi_id)
    # Priority 5: terminal guard, then from-state.
    tmi_terminal_guard(tmi)
    if tmi["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "only a PROPOSED TMI can be published")
    # Priority 6: segregation of duties.
    user_id = request.headers.get("X-User-ID")
    if user_id == tmi["proposed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the publisher must differ from the proposer",
        )
    # Forecast + rate gates bind at publish for the rate-bearing types only
    # (GROUND_STOP and REROUTE are exempt).
    if tmi["tmi_type"] in ("GROUND_DELAY_PROGRAM", "AIRSPACE_FLOW_PROGRAM"):
        facility = get_facility(tmi["facility_id"])
        enforce_capacity_gate(
            facility, tmi, tmi["program_start"], tmi["program_end"], tmi["controlled_rate"]
        )
    tmi["status"] = "PUBLISHED"
    tmi["published_by_user_id"] = user_id
    touch(tmi)
    return success_object(serialize_tmi(tmi))


@bp.route("/atfm/tmis/<tmi_id>/activate", methods=["POST"])
def activate_tmi(tmi_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    tmi = get_tmi(tmi_id)
    tmi_terminal_guard(tmi)
    if tmi["status"] not in ("PUBLISHED", "REVISING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a PUBLISHED or REVISING TMI can be activated",
        )
    facility = get_facility(tmi["facility_id"])
    if tmi["status"] == "PUBLISHED":
        # Priority 5: facility must not be in OUTAGE.
        if facility["status"] == "OUTAGE":
            raise ApiError(
                "ERR_FACILITY_NOT_OPERATIONAL",
                "facility %s is in OUTAGE" % facility["id"],
            )
        # Priority 14: GDP-family exclusivity re-checked at activation.
        _check_gdp_family_overlap(
            facility["id"],
            tmi["tmi_type"],
            tmi["program_start"],
            tmi["program_end"],
            tmi["id"],
        )
        # Priority 20 (+ forecast gate): rate-bearing types only.
        if tmi["tmi_type"] in ("GROUND_DELAY_PROGRAM", "AIRSPACE_FLOW_PROGRAM"):
            enforce_capacity_gate(
                facility,
                tmi,
                tmi["program_start"],
                tmi["program_end"],
                tmi["controlled_rate"],
            )
        if tmi["tmi_type"] == "GROUND_DELAY_PROGRAM":
            activate_allocation(tmi)
        tmi["status"] = "ACTIVE"
        tmi["activated_at"] = get_clock()
        touch(tmi)
        return success_object(serialize_tmi(tmi))

    # REVISING: apply the single pending revision (PRD 3.6).
    pending = [
        r
        for r in DB["revisions"].values()
        if r["tmi_id"] == tmi["id"] and not r["applied"]
    ]
    if len(pending) != 1:
        raise ApiError(
            "ERR_INVALID_STATE",
            "a REVISING TMI must have exactly one unapplied revision",
        )
    if facility["status"] == "OUTAGE":
        raise ApiError(
            "ERR_FACILITY_NOT_OPERATIONAL",
            "facility %s is in OUTAGE" % facility["id"],
        )
    reapply_allocation(tmi, pending[0])
    tmi["status"] = "ACTIVE"
    touch(tmi)
    return success_object(serialize_tmi(tmi))


@bp.route("/atfm/tmis/<tmi_id>/revisions", methods=["POST"])
def create_revision(tmi_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    tmi = get_tmi(tmi_id)
    body = body_json()
    reason = req_str(body, "reason")
    expected_version = req_int(body, "expected_tmi_version")
    new_rate = opt_int(body, "new_controlled_rate")
    new_end = opt_dt(body, "new_program_end")
    # Priority 5: revision creation requires ACTIVE.
    tmi_require_active(tmi)
    # OCC (PRD 2.7): expected_tmi_version must equal the current version.
    if expected_version != tmi["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_tmi_version %s does not match current version %s"
            % (expected_version, tmi["version"]),
            412,
        )
    if new_rate is None and new_end is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "at least one of new_controlled_rate or new_program_end is required",
        )
    if new_end is not None:
        # Priority 8 then 9 on the revised window.
        if not (new_end > tmi["program_start"]):
            raise ApiError(
                "ERR_INVALID_WINDOW",
                "new_program_end must be strictly after program_start",
            )
        if not (new_end > get_clock()):
            raise ApiError(
                "ERR_PROGRAM_WINDOW_IN_PAST",
                "new_program_end must be strictly after the current logical clock",
            )
    if new_rate is not None:
        # Priority 15: a supplied revision rate must satisfy the GDP rate shape.
        check_gdp_rate(new_rate)
        # Priority 20: capacity gate over the post-revision window (the
        # rate-bearing types only; GROUND_STOP/REROUTE are exempt).
        if tmi["tmi_type"] in ("GROUND_DELAY_PROGRAM", "AIRSPACE_FLOW_PROGRAM"):
            facility = get_facility(tmi["facility_id"])
            enforce_capacity_gate(
                facility,
                tmi,
                tmi["program_start"],
                new_end if new_end is not None else tmi["program_end"],
                new_rate,
            )
    revision = create_record(
        "revisions",
        {
            "tmi_id": tmi["id"],
            "revision_index": tmi["revision_count"] + 1,
            "previous_controlled_rate": (
                tmi["controlled_rate"] if new_rate is not None else None
            ),
            "new_controlled_rate": new_rate,
            "previous_program_end": (
                tmi["program_end"] if new_end is not None else None
            ),
            "new_program_end": new_end,
            "origin": "MANUAL",
            "reason": reason,
            "applied": False,
            "applied_at": None,
        },
    )
    tmi["revision_count"] += 1
    tmi["status"] = "REVISING"
    touch(tmi)
    return success_object(serialize_revision(revision), 201)


@bp.route("/atfm/tmis/<tmi_id>/revisions", methods=["GET"])
def list_revisions(tmi_id):
    auth_context()
    require_roles(*ROLES)
    tmi = get_tmi(tmi_id)
    rows = [r for r in DB["revisions"].values() if r["tmi_id"] == tmi["id"]]
    rows.sort(key=lambda r: (r["revision_index"], r["_seq"]))
    return paginate([serialize_revision(r) for r in rows])


def _revert_flight(flight):
    """Release-cascade flight revert (shared by TMI cancel)."""
    flight["controlled_arrival"] = None
    flight["control_status"] = "UNCONTROLLED"
    flight["provisional_delay_minutes"] = 0
    flight["is_overflow"] = False
    flight["_tmi_id"] = None
    touch(flight)


def _expire_pending_ga_requests(tmi_id):
    for req in DB["ga_requests"].values():
        if req["tmi_id"] == tmi_id and req["status"] in ("REQUESTED", "WAITLISTED"):
            req["status"] = "EXPIRED"
            touch(req)


@bp.route("/atfm/tmis/<tmi_id>/cancel", methods=["POST"])
def cancel_tmi(tmi_id):
    auth_context()
    require_roles(ROLE_COMMAND_CENTER_ADMIN)
    tmi = get_tmi(tmi_id)
    tmi_terminal_guard(tmi)
    if tmi["status"] in ("ACTIVE", "REVISING"):
        # Full compensation cascade (PRD 3.9): every ASSIGNED slot -> RELEASED;
        # each release reverts its holder flight and writes a REVERSAL whose
        # delay_delta is the negation of the flight's previously attributed
        # delay; the ledger's attributed_delay_minutes is decremented and its
        # reversed_delay_minutes incremented by that same amount.
        program = [
            f
            for f in DB["flights"].values()
            if f.get("_tmi_id") == tmi["id"] and f["controlled_arrival"] is not None
        ]
        program.sort(key=lambda f: (f["created_at"], f["_seq"]))
        slots_by_flight = {}
        for slot in slots_of(tmi["id"]):
            if slot["status"] == "ASSIGNED" and slot["assigned_flight_id"]:
                slots_by_flight[slot["assigned_flight_id"]] = slot
        for flight in program:
            slot = slots_by_flight.get(flight["id"])
            prior = flight["provisional_delay_minutes"]
            from_time = flight["controlled_arrival"]
            if slot is not None:
                slot["status"] = "RELEASED"
                slot["assigned_flight_id"] = None
                touch(slot)
            _revert_flight(flight)
            write_transaction(
                tmi["id"],
                slot["id"] if slot is not None else None,
                flight["id"],
                flight["operator_id"],
                "REVERSAL",
                from_time,
                None,
                -prior,
            )
            ledger = ensure_ledger(flight["operator_id"], tmi["id"])
            ledger["attributed_delay_minutes"] -= prior
            ledger["reversed_delay_minutes"] += prior
            touch(ledger)
    # PRD 3.7: pending GA requests do not outlive the program — expire them on
    # every non-terminal cancellation, including the PROPOSED/PUBLISHED bare
    # flip (the "bare flip" of PRD 3.9 only waives the allocation unwind).
    _expire_pending_ga_requests(tmi["id"])
    tmi["status"] = "CANCELLED"
    touch(tmi)
    return success_object(serialize_tmi(tmi))


@bp.route("/atfm/tmis/<tmi_id>/complete", methods=["POST"])
def complete_tmi(tmi_id):
    auth_context()
    require_roles(ROLE_COMMAND_CENTER_ADMIN)
    tmi = get_tmi(tmi_id)
    tmi_terminal_guard(tmi)
    if tmi["status"] not in ("ACTIVE", "REVISING"):
        raise ApiError(
            "ERR_INVALID_STATE", "only an ACTIVE or REVISING TMI can be completed"
        )
    # FINAL delay attribution per controlled flight (PRD 3.9): self-inflicted
    # minutes count only when the operator's ETA pushed beyond schedule.
    program = [
        f
        for f in DB["flights"].values()
        if f.get("_tmi_id") == tmi["id"] and f["controlled_arrival"] is not None
    ]
    program.sort(key=lambda f: (f["created_at"], f["_seq"]))
    credited = {}
    for flight in program:
        if flight["estimated_arrival"] > flight["scheduled_arrival"]:
            self_inflicted = delay_minutes_between(
                flight["estimated_arrival"], flight["scheduled_arrival"]
            )
        else:
            self_inflicted = 0
        flight["final_delay_minutes"] = max(
            0, flight["provisional_delay_minutes"] - self_inflicted
        )
        touch(flight)
        credited.setdefault(flight["operator_id"], 0)
        credited[flight["operator_id"]] += flight["final_delay_minutes"]
    for operator_id, minutes in credited.items():
        if minutes:
            operator = DB["operators"].get(operator_id)
            if operator is not None:
                operator["cumulative_delay_minutes"] += minutes
                touch(operator)
    # Wind-down: remaining OPEN/RELEASED slots -> RELEASED; ASSIGNED stay.
    for slot in slots_of(tmi["id"]):
        if slot["status"] in ("OPEN", "RELEASED"):
            slot["status"] = "RELEASED"
            touch(slot)
    _expire_pending_ga_requests(tmi["id"])
    recompute_fair_shares(tmi["id"])
    tmi["status"] = "COMPLETED"
    touch(tmi)
    return success_object(serialize_tmi(tmi))
