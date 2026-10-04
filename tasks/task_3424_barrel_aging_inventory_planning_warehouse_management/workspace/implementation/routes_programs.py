"""Routes: private selection programs, eligible-barrel selector, reservations."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import envelope
import serializers
import store
import validation as v

bp = Blueprint("programs", __name__)

SPIRIT_TYPES = {"BOURBON", "RYE", "TENNESSEE", "SINGLE_MALT"}


def _get_program_or_404(pid):
    program = store.programs.get(pid)
    if program is None:
        raise envelope.err_not_found("Private selection program not found")
    return program


def _get_reservation_or_404(rid):
    reservation = store.reservations.get(rid)
    if reservation is None:
        raise envelope.err_not_found("Reservation not found")
    calc.refresh_reservation(reservation)
    return reservation


@bp.route("/barrel-aging/private-selection-programs", methods=["POST"])
def create_program():
    _, role = v.authenticate()
    v.require_role(role, ["ProgramDirector"])
    body = v.get_body()
    v.check_allowed_fields(body, {
        "name", "spirit_type", "min_quality_score", "required_barrel_count",
        "reservation_window_days",
    })
    name = v.req_str(body, "name")
    spirit_type = v.req_enum(body, "spirit_type", SPIRIT_TYPES)
    min_score = v.req_int(body, "min_quality_score", min_v=0, max_v=100)
    required = v.req_int(body, "required_barrel_count", min_v=1)
    window = v.req_int(body, "reservation_window_days", min_v=1)

    now = store.now()
    program = {
        "id": store.new_id(),
        "name": name,
        "spirit_type": spirit_type,
        "min_quality_score": min_score,
        "required_barrel_count": required,
        "reservation_window_days": window,
        "state": "SELECTION",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.programs[program["id"]] = program
    return envelope.ok_object(serializers.serialize_program(program), status=201)


@bp.route("/barrel-aging/private-selection-programs/<pid>", methods=["GET"])
def get_program(pid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    program = _get_program_or_404(pid)
    for r in calc.program_reservations(pid):
        calc.refresh_reservation(r)
    return envelope.ok_object(serializers.serialize_program(program))


@bp.route("/barrel-aging/private-selection-programs/<pid>/eligible-barrels", methods=["GET"])
def eligible_barrels(pid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    program = _get_program_or_404(pid)
    limit, offset = v.parse_pagination()
    calc.expire_due_reservations()
    candidates = []
    for b in store.barrels.values():
        if calc.barrel_eligible_for_program(b, program):
            candidates.append(b)
    candidates.sort(
        key=lambda b: (-calc.latest_quality_score(b), b["fill_date"], b["created_at"], b["_seq"])
    )
    items = [serializers.serialize_barrel(b) for b in candidates]
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/private-selection-programs/<pid>/reservations", methods=["POST"])
def create_reservation(pid):
    _, role = v.authenticate()
    v.require_role(role, ["ProgramDirector"])
    body = v.get_body()
    v.check_allowed_fields(body, {"barrel_id", "expected_program_version"})
    barrel_id = v.req_str(body, "barrel_id")
    expected = v.req_int(body, "expected_program_version")

    program = _get_program_or_404(pid)
    barrel = store.barrels.get(barrel_id)
    if barrel is None:
        raise envelope.err_not_found("Barrel not found")

    # Lazy expiry may advance the program version before the OCC check.
    for r in calc.program_reservations(pid):
        calc.refresh_reservation(r)

    # Gate 5: OCC on the program version.
    if expected != program["version"]:
        raise envelope.err_stale_program()

    # Gate 6: a LOCKED program accepts no further reservations.
    if program["state"] != "SELECTION":
        raise envelope.err_invalid_state("Program is not in SELECTION")

    # Gate 8: quota is examined before barrel eligibility.
    if calc.available_slots(program) <= 0:
        raise envelope.err_quota()

    if not calc.barrel_eligible_for_program(barrel, program):
        raise envelope.err_barrel_not_eligible()

    now = store.now()
    reservation = {
        "id": store.new_id(),
        "program_id": pid,
        "barrel_id": barrel_id,
        "state": "ACTIVE",
        "expires_at": now + timedelta(days=program["reservation_window_days"]),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.reservations[reservation["id"]] = reservation
    program["version"] += 1
    program["updated_at"] = now
    return envelope.ok_object(serializers.serialize_reservation(reservation), status=201)


@bp.route("/barrel-aging/private-selection-programs/<pid>/reservations", methods=["GET"])
def list_program_reservations(pid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    _get_program_or_404(pid)
    limit, offset = v.parse_pagination()
    state_filter = request.args.get("state")
    res = calc.program_reservations(pid)
    res.sort(key=lambda r: (r["created_at"], r["_seq"]))
    items = []
    for r in res:
        ser = serializers.serialize_reservation(r)
        if state_filter is not None and ser["state"] != state_filter:
            continue
        items.append(ser)
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/reservations/<rid>/consume", methods=["POST"])
def consume_reservation(rid):
    _, role = v.authenticate()
    v.require_role(role, ["ProgramDirector"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    reservation = _get_reservation_or_404(rid)

    if reservation["state"] != "ACTIVE":
        raise envelope.err_invalid_state("Reservation is not ACTIVE")

    # Re-examine the barrel at consume time.
    barrel = store.barrels.get(reservation["barrel_id"])
    if barrel is not None:
        calc.refresh_barrel(barrel)
    if (
        barrel is None
        or barrel["custody_status"] != "BONDED"
        or barrel["maturation_status"] != "MATURE_ELIGIBLE"
        or calc.has_committed_component(barrel["id"])
    ):
        raise envelope.err_barrel_not_eligible()

    now = store.now()
    reservation["state"] = "CONSUMED"
    reservation["version"] += 1
    reservation["updated_at"] = now

    program = store.programs.get(reservation["program_id"])
    if program is not None:
        program["version"] += 1
        program["updated_at"] = now
        # Bubble-up: lock the program when the consumed count hits the quota.
        consumed = sum(
            1 for r in calc.program_reservations(program["id"]) if r["state"] == "CONSUMED"
        )
        if program["state"] == "SELECTION" and consumed >= program["required_barrel_count"]:
            program["state"] = "LOCKED"
            program["version"] += 1
            program["updated_at"] = now
    return envelope.ok_object(serializers.serialize_reservation(reservation))


@bp.route("/barrel-aging/reservations/<rid>/release", methods=["POST"])
def release_reservation(rid):
    _, role = v.authenticate()
    v.require_role(role, ["ProgramDirector"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    reservation = _get_reservation_or_404(rid)

    if reservation["state"] != "ACTIVE":
        raise envelope.err_invalid_state("Reservation is not ACTIVE")

    now = store.now()
    reservation["state"] = "RELEASED"
    reservation["version"] += 1
    reservation["updated_at"] = now
    program = store.programs.get(reservation["program_id"])
    if program is not None:
        program["version"] += 1
        program["updated_at"] = now
    return envelope.ok_object(serializers.serialize_reservation(reservation))
