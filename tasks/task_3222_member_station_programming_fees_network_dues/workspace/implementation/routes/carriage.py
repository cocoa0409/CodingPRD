"""Carriage agreements, broadcast windows and the premiere-embargo sweep."""
from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, bad_request, invalid_state, not_found
from core.middleware import check_station_ownership, route
from core.response import array_response, object_response
from core.store import STORE
from services import carriage, content, fees, governance

bp = Blueprint("carriage", __name__)

PROGRAM_CODE_RE = r"^NP-[0-9]{4}$"
OBLIGATION_TYPES = ["MANDATORY", "OPTIONAL", "DISCRETIONARY"]

WINDOW_TERMINAL = ("BROADCAST", "MISSED", "VIOLATED")
AGREEMENT_TERMINAL = ("EXPIRED", "TERMINATED")


def agreement_or_404(agreement_id):
    agreement = STORE.agreements.get(agreement_id)
    if agreement is None:
        raise not_found("carriage agreement")
    return agreement


def window_or_404(window_id):
    window = STORE.windows.get(window_id)
    if window is None:
        raise not_found("broadcast window")
    return window


def program_for_code(code):
    for program in STORE.programs.values():
        if program.get("program_code") == code:
            return program
    return None


def premiere_of_code(code):
    program = program_for_code(code)
    if program is None:
        return None
    return C.parse_dt(program.get("national_premiere_at"))


def embargo_breach(window, start_dt):
    """window_start before embargo_until, or before a carried program's premiere."""
    embargo = C.parse_dt(window.get("embargo_until"))
    if embargo is not None and start_dt is not None and start_dt < embargo:
        return True
    premiere = premiere_of_code(window.get("program_code"))
    if premiere is not None and start_dt is not None and start_dt < premiere:
        return True
    return False


def _station_or_404(station_id):
    station = STORE.member_stations.get(station_id)
    if station is None:
        raise not_found("member station")
    return station


def _terminated_guard(agreement):
    if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
        raise ApiError("ERR_CARRIAGE_AGREEMENT_TERMINATED")


# --- agreements --------------------------------------------------------------
@bp.route("/network/carriage-agreements", methods=["POST"])
@route("/network/carriage-agreements", "POST")
def create_agreement():
    body = base.get_body(request.get_json(silent=True))
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    station = _station_or_404(station_id)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station["id"])
    if station.get("eligibility_status") not in ("ELIGIBLE", "PROBATION"):
        raise ApiError("ERR_STATION_NOT_ELIGIBLE")
    program_code = base.as_text(body.get("program_code"), "program_code", pattern=PROGRAM_CODE_RE)
    obligation = base.as_enum(body.get("obligation_type"), OBLIGATION_TYPES, "obligation_type")
    deadline = base.as_instant(body.get("clearance_deadline"), "clearance_deadline")
    cap = base.as_cents(body.get("exception_liability_cap_cents"), "exception_liability_cap_cents")
    agreement = new_record(
        "CarriageAgreement",
        station_id=station["id"],
        program_code=program_code,
        obligation_type=obligation,
        agreement_status="DRAFT",
        clearance_deadline=deadline,
        exception_liability_cap_cents=cap,
        published_at=None,
    )
    STORE.put("agreements", agreement)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.agreement_view(STORE, agreement), 201)


@bp.route("/network/carriage-agreements", methods=["GET"])
@route("/network/carriage-agreements", "GET")
def list_agreements():
    args = request.args
    recs = STORE.all("agreements")
    for field in ("program_code", "agreement_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([carriage.agreement_view(STORE, r) for r in page], meta)


@bp.route("/network/carriage-agreements/<aid>", methods=["GET"])
@route("/network/carriage-agreements/<aid>", "GET")
def read_agreement(aid):
    agreement = agreement_or_404(aid)
    return object_response(carriage.agreement_view(STORE, agreement))


@bp.route("/network/carriage-agreements/<aid>/windows", methods=["GET"])
@route("/network/carriage-agreements/<aid>/windows", "GET")
def agreement_windows(aid):
    agreement_or_404(aid)
    args = request.args
    recs = STORE.windows_of(aid)
    status = base.scalar_arg(args, "clearance_status")
    if status is not None:
        recs = [r for r in recs if r.get("clearance_status") == status]
    page, meta = base.paginate(recs, args)
    return array_response([carriage.window_view(STORE, r) for r in page], meta)


def _advance(agreement, to_state):
    agreement["agreement_status"] = to_state
    touch(agreement)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.agreement_view(STORE, agreement))


@bp.route("/network/carriage-agreements/<aid>/submit", methods=["POST"])
@route("/network/carriage-agreements/<aid>/submit", "POST")
def submit_agreement(aid):
    agreement = agreement_or_404(aid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, agreement.get("station_id"))
    if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "DRAFT":
        raise invalid_state("the agreement is not a draft")
    station = STORE.member_stations.get(agreement.get("station_id"))
    if station is None:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if station.get("eligibility_status") in ("SUSPENDED", "WITHDRAWN"):
        raise ApiError("ERR_STATION_SUSPENDED")
    windows = STORE.windows_of(aid)
    if not windows:
        raise invalid_state("the agreement carries no broadcast window")
    for window in windows:
        if window.get("program_code") != agreement.get("program_code"):
            raise ApiError("ERR_PROGRAM_CODE_MISMATCH")
    return _advance(agreement, "SUBMITTED")


@bp.route("/network/carriage-agreements/<aid>/review", methods=["POST"])
@route("/network/carriage-agreements/<aid>/review", "POST")
def review_agreement(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "SUBMITTED":
        raise invalid_state("the agreement is not submitted")
    return _advance(agreement, "UNDER_REVIEW")


@bp.route("/network/carriage-agreements/<aid>/clear", methods=["POST"])
@route("/network/carriage-agreements/<aid>/clear", "POST")
def clear_agreement(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "UNDER_REVIEW":
        raise invalid_state("the agreement is not under review")
    for window in STORE.windows_of(aid):
        if not window.get("is_cleared"):
            raise ApiError("ERR_REVIEW_INCOMPLETE")
    return _advance(agreement, "CLEARED")


@bp.route("/network/carriage-agreements/<aid>/publish", methods=["POST"])
@route("/network/carriage-agreements/<aid>/publish", "POST")
def publish_agreement(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement.get("agreement_status") != "CLEARED":
        raise invalid_state("the agreement is not cleared")
    windows = STORE.windows_of(aid)
    for window in windows:
        if not window.get("is_cleared"):
            raise ApiError("ERR_REVIEW_INCOMPLETE")
    for window in windows:
        if window.get("clearance_status") != "CLEARED":
            continue
        usable = [
            s for s in STORE.slots_for_window(window["id"])
            if s.get("slot_status") in ("RESERVED", "SCHEDULED", "AIRED")
        ]
        if not usable:
            raise invalid_state(
                "a cleared window carries no uplink reservation and cannot be scheduled"
            )
    agreement["agreement_status"] = "CARRIED"
    agreement["published_at"] = C.iso(C.now())
    touch(agreement)
    carried_stations = {}
    for window in windows:
        if window.get("clearance_status") != "CLEARED":
            continue
        window["clearance_status"] = "SCHEDULED"
        carriage.refresh_window_flags(STORE, window)
        touch(window)
        carried_stations[window.get("station_id")] = True
    program = program_for_code(agreement.get("program_code"))
    if program is not None:
        program["publication_cycle"] = int(program.get("publication_cycle") or 0) + 1
        touch(program)
    for station_id in carried_stations:
        station = STORE.member_stations.get(station_id)
        if station is None:
            continue
        schedule = fees.resolve_schedule(STORE, station)
        if schedule is None:
            continue
        final = fees.final_adjusted_fee_cents(station, schedule)
        deduction = fees.station_drive_deduction(STORE, station)
        station["dues_arrears_cents"] = int(station.get("dues_arrears_cents") or 0) + (
            int(final) - int(deduction)
        )
        touch(station)
        governance.upsert_projection(STORE, station)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.agreement_view(STORE, agreement))


@bp.route("/network/carriage-agreements/<aid>/republish", methods=["POST"])
@route("/network/carriage-agreements/<aid>/republish", "POST")
def republish_agreement(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") not in ("CARRIED",):
        if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise invalid_state("the agreement is not carried")
    agreement["agreement_status"] = "CLEARED"
    agreement["published_at"] = None
    touch(agreement)
    for window in STORE.windows_of(aid):
        if window.get("clearance_status") == "SCHEDULED":
            window["clearance_status"] = "CLEARED"
            carriage.refresh_window_flags(STORE, window)
            touch(window)
    program = program_for_code(agreement.get("program_code"))
    if program is not None:
        program["publication_cycle"] = int(program.get("publication_cycle") or 0) + 1
        touch(program)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.agreement_view(STORE, agreement))


@bp.route("/network/carriage-agreements/<aid>/lift-publish-embargo", methods=["POST"])
@route("/network/carriage-agreements/<aid>/lift-publish-embargo", "POST")
def lift_publish_embargo(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") != "EMBARGOED":
        raise invalid_state("the agreement is not embargoed")
    premiere = premiere_of_code(agreement.get("program_code"))
    if premiere is None or C.now() <= premiere:
        raise invalid_state("the program's premiere instant has not passed")
    return _advance(agreement, "CARRIED")


@bp.route("/network/carriage-agreements/<aid>/expire", methods=["POST"])
@route("/network/carriage-agreements/<aid>/expire", "POST")
def expire_agreement(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") != "CARRIED":
        raise invalid_state("the agreement is not carried")
    deadline = C.parse_dt(agreement.get("clearance_deadline"))
    if deadline is None or C.now() <= deadline:
        raise invalid_state("the clearance deadline has not passed")
    agreement["agreement_status"] = "EXPIRED"
    touch(agreement)
    for window in STORE.windows_of(aid):
        if window.get("clearance_status") == "SCHEDULED":
            window["clearance_status"] = "MISSED"
            carriage.accrue(window, "MISSED")
            carriage.refresh_window_flags(STORE, window)
            touch(window)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.agreement_view(STORE, agreement))


@bp.route("/network/carriage-agreements/<aid>/terminate", methods=["POST"])
@route("/network/carriage-agreements/<aid>/terminate", "POST")
def terminate_agreement(aid):
    agreement = agreement_or_404(aid)
    if agreement.get("agreement_status") not in ("CLEARED", "CARRIED"):
        raise invalid_state("the agreement cannot be terminated from its current state")
    body = base.get_body(request.get_json(silent=True))
    reason = base.as_text(body.get("termination_reason"), "termination_reason")
    agreement["agreement_status"] = "TERMINATED"
    agreement["_termination_reason"] = reason
    touch(agreement)
    for window in STORE.windows_of(aid):
        if window.get("clearance_status") in ("DRAFT", "PENDING_CLEARANCE", "CLEARED"):
            window["clearance_status"] = "REJECTED"
            window["rejection_reason"] = reason
            carriage.accrue(window, "REJECTED")
            carriage.refresh_window_flags(STORE, window)
            touch(window)
            for slot in STORE.slots_for_window(window["id"]):
                if slot.get("slot_status") in ("RESERVED", "SCHEDULED"):
                    slot["slot_status"] = "RELEASED"
                    carriage.release_slot(STORE, slot)
                    touch(slot)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.agreement_view(STORE, agreement))


# --- windows -----------------------------------------------------------------
@bp.route("/network/broadcast-windows", methods=["POST"])
@route("/network/broadcast-windows", "POST")
def create_window():
    body = base.get_body(request.get_json(silent=True))
    parent_id = body.get("parent_agreement_id")
    if parent_id is None:
        raise bad_request("parent_agreement_id is required")
    agreement = agreement_or_404(parent_id)
    station_id = body.get("station_id")
    if station_id is None:
        raise bad_request("station_id is required")
    _station_or_404(station_id)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station_id)
    program_code = base.as_text(body.get("program_code"), "program_code", pattern=PROGRAM_CODE_RE)
    start = base.as_instant(body.get("window_start"), "window_start")
    end = base.as_instant(body.get("window_end"), "window_end")
    if C.parse_dt(end) <= C.parse_dt(start):
        raise bad_request("window_end must be after window_start")
    embargo = base.as_instant(body.get("embargo_until"), "embargo_until", required=False)
    if program_code != agreement.get("program_code"):
        raise ApiError("ERR_PROGRAM_CODE_MISMATCH")
    for sibling in STORE.windows_of(agreement["id"]):
        if sibling.get("station_id") != station_id:
            continue
        s_start = C.parse_dt(sibling.get("window_start"))
        s_end = C.parse_dt(sibling.get("window_end"))
        if s_start is None or s_end is None:
            continue
        if C.parse_dt(start) < s_end and s_start < C.parse_dt(end):
            raise ApiError("ERR_WINDOW_OVERLAP")
    probe = {"embargo_until": embargo, "program_code": program_code}
    if embargo_breach(probe, C.parse_dt(start)):
        raise ApiError("ERR_EMBARGO_VIOLATION")
    window = new_record(
        "BroadcastWindow",
        parent_agreement_id=agreement["id"],
        station_id=station_id,
        program_code=program_code,
        window_start=start,
        window_end=end,
        embargo_until=embargo,
        clearance_status="DRAFT",
        is_cleared=False,
        carriage_exception_liability_cents=0,
        rejection_reason=None,
    )
    STORE.put("windows", window)
    carriage.refresh_window_flags(STORE, window)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.window_view(STORE, window), 201)


@bp.route("/network/broadcast-windows", methods=["GET"])
@route("/network/broadcast-windows", "GET")
def list_windows():
    args = request.args
    recs = STORE.all("windows")
    for field in ("station_id", "program_code", "clearance_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([carriage.window_view(STORE, r) for r in page], meta)


@bp.route("/network/broadcast-windows/<wid>", methods=["GET"])
@route("/network/broadcast-windows/<wid>", "GET")
def read_window(wid):
    window = window_or_404(wid)
    return object_response(carriage.window_view(STORE, window))


@bp.route("/network/broadcast-windows/<wid>/request-clearance", methods=["POST"])
@route("/network/broadcast-windows/<wid>/request-clearance", "POST")
def request_clearance(wid):
    window = window_or_404(wid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, window.get("station_id"))
    agreement = agreement_or_404(window.get("parent_agreement_id"))
    _terminated_guard(agreement)
    if window.get("clearance_status") != "DRAFT":
        raise invalid_state("the window is not a draft")
    start = C.parse_dt(window.get("window_start"))
    end = C.parse_dt(window.get("window_end"))
    if start is None or end is None or start >= end:
        raise invalid_state("the window interval is not positive")
    if embargo_breach(window, start):
        raise ApiError("ERR_EMBARGO_VIOLATION")
    window["clearance_status"] = "PENDING_CLEARANCE"
    carriage.refresh_window_flags(STORE, window)
    touch(window)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.window_view(STORE, window))


@bp.route("/network/broadcast-windows/<wid>/clear", methods=["POST"])
@route("/network/broadcast-windows/<wid>/clear", "POST")
def clear_window(wid):
    window = window_or_404(wid)
    agreement = agreement_or_404(window.get("parent_agreement_id"))
    _terminated_guard(agreement)
    if window.get("clearance_status") != "PENDING_CLEARANCE":
        raise invalid_state("the window is not pending clearance")
    embargo = C.parse_dt(window.get("embargo_until"))
    if embargo is not None and C.now() < embargo:
        raise ApiError("ERR_EMBARGO_VIOLATION")
    start = C.parse_dt(window.get("window_start"))
    if start is not None and start < C.now():
        raise invalid_state("the window's start instant already lies in the past")
    premiere = premiere_of_code(window.get("program_code"))
    if premiere is not None and start is not None and start < premiere and premiere > C.now():
        raise ApiError("ERR_EMBARGO_VIOLATION")
    window["clearance_status"] = "CLEARED"
    window["is_cleared"] = True
    carriage.refresh_window_flags(STORE, window)
    touch(window)
    for slot in STORE.slots_for_window(window["id"]):
        if slot.get("slot_status") == "RESERVED":
            slot["slot_status"] = "SCHEDULED"
            touch(slot)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.window_view(STORE, window))


@bp.route("/network/broadcast-windows/<wid>/reject", methods=["POST"])
@route("/network/broadcast-windows/<wid>/reject", "POST")
def reject_window(wid):
    window = window_or_404(wid)
    agreement = agreement_or_404(window.get("parent_agreement_id"))
    if window.get("clearance_status") != "PENDING_CLEARANCE":
        raise invalid_state("the window is not pending clearance")
    body = base.get_body(request.get_json(silent=True))
    reason = base.as_text(body.get("rejection_reason"), "rejection_reason")
    window["clearance_status"] = "REJECTED"
    window["rejection_reason"] = reason
    carriage.accrue(window, "REJECTED")
    carriage.refresh_window_flags(STORE, window)
    touch(window)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.window_view(STORE, window))


@bp.route("/network/broadcast-windows/<wid>/remediating", methods=["POST"])
@route("/network/broadcast-windows/<wid>/remediating", "POST")
def remediate_window(wid):
    window = window_or_404(wid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, window.get("station_id"))
    agreement = agreement_or_404(window.get("parent_agreement_id"))
    if agreement.get("agreement_status") in AGREEMENT_TERMINAL:
        raise ApiError("ERR_CARRIAGE_AGREEMENT_TERMINATED")
    # PRD §2.9: "a resource already in a terminal state fails with
    # `ERR_ALREADY_TERMINAL`", and that rule outranks the from-state check for
    # every transition this endpoint does not admit out of a terminal state.
    if window.get("clearance_status") in WINDOW_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if window.get("clearance_status") != "REJECTED":
        raise invalid_state("the window is not rejected")
    window["clearance_status"] = "DRAFT"
    window["rejection_reason"] = None
    carriage.refresh_window_flags(STORE, window)
    touch(window)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.window_view(STORE, window))


@bp.route("/network/broadcast-windows/<wid>/expire", methods=["POST"])
@route("/network/broadcast-windows/<wid>/expire", "POST")
def expire_window(wid):
    window = window_or_404(wid)
    agreement = agreement_or_404(window.get("parent_agreement_id"))
    if window.get("clearance_status") != "SCHEDULED":
        raise invalid_state("the window is not scheduled")
    end = C.parse_dt(window.get("window_end"))
    if end is None or C.now() < end:
        raise invalid_state("the window's end instant has not passed")
    window["clearance_status"] = "MISSED"
    carriage.accrue(window, "MISSED")
    carriage.refresh_window_flags(STORE, window)
    touch(window)
    carriage.recompute_agreement_rollup(STORE, agreement)
    return object_response(carriage.window_view(STORE, window))


# --- premiere embargo sweep --------------------------------------------------
@bp.route("/network/series/embargo-check", methods=["POST"])
@route("/network/series/embargo-check", "POST")
def series_embargo_check():
    touched = []
    affected = {}
    for window in STORE.windows.values():
        if window.get("clearance_status") != "CLEARED":
            continue
        premiere = premiere_of_code(window.get("program_code"))
        if premiere is None or premiere <= C.now():
            continue
        start = C.parse_dt(window.get("window_start"))
        if start is None or start >= premiere:
            continue
        window["clearance_status"] = "VIOLATED"
        window["rejection_reason"] = "PREMIERE_EMBARGO"
        carriage.accrue(window, "VIOLATED")
        carriage.refresh_window_flags(STORE, window)
        touch(window)
        touched.append(window)
        affected[window.get("parent_agreement_id")] = True
    for agreement_id in affected:
        carriage.refresh_agreement_from_windows(STORE, agreement_id)
    return array_response([carriage.window_view(STORE, w) for w in touched])