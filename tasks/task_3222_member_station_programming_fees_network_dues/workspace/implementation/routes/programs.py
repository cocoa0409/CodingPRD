"""National programs, local-content licensing hops and the archive ledger."""
from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, bad_request, invalid_state, not_found
from core.middleware import route
from core.response import array_response, object_response
from core.store import STORE
from services import carriage, content

bp = Blueprint("programs", __name__)

PROGRAM_CODE_RE = r"^NP-[0-9]{4}$"
STRANDS = ["NEWS", "CULTURE", "INVESTIGATIVE", "MUSIC", "TALK"]
COUNTED_STATUSES = ("LICENSED", "USED")


def program_or_404(program_id):
    program = STORE.programs.get(program_id)
    if program is None:
        raise not_found("national program")
    return program


def _agreements_for(program_code):
    return [
        a for a in STORE.agreements.values()
        if a.get("program_code") == program_code
    ]


def _recount_licenses(program):
    program["licensed_contribution_count"] = len([
        c for c in STORE.contributions.values()
        if c.get("program_id") == program["id"]
        and c.get("contribution_status") in COUNTED_STATUSES
    ])
    return program["licensed_contribution_count"]


def _decrement_for(program, before, after):
    """Decrement the live-license count by the pieces that left the counted set."""
    now = int(program.get("licensed_contribution_count") or 0)
    program["licensed_contribution_count"] = max(0, now - before + after)
    return program["licensed_contribution_count"]


@bp.route("/network/national-programs", methods=["POST"])
@route("/network/national-programs", "POST")
def create_program():
    body = base.get_body(request.get_json(silent=True))
    code = base.as_text(body.get("program_code"), "program_code", pattern=PROGRAM_CODE_RE)
    for existing in STORE.programs.values():
        if existing.get("program_code") == code:
            raise ApiError("ERR_PROGRAM_CODE_TAKEN")
    title = base.as_text(body.get("program_title"), "program_title")
    strand = base.as_enum(body.get("strand_type"), STRANDS, "strand_type")
    premiere = base.as_instant(body.get("national_premiere_at"), "national_premiere_at")
    clearance_required = base.as_bool(
        body.get("clearance_required"), "clearance_required", required=False
    )
    if clearance_required is None:
        clearance_required = True
    program = new_record(
        "NationalProgram",
        program_code=code,
        program_title=title,
        strand_type=strand,
        production_status="DEVELOPMENT",
        clearance_required=bool(clearance_required),
        national_premiere_at=premiere,
        publication_cycle=0,
        licensed_contribution_count=0,
        preliminary_license_credit_cents=0,
    )
    STORE.put("programs", program)
    return object_response(public(program), 201)


@bp.route("/network/national-programs", methods=["GET"])
@route("/network/national-programs", "GET")
def list_programs():
    args = request.args
    recs = STORE.all("programs")
    for field in ("strand_type", "production_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/national-programs/<pid>", methods=["GET"])
@route("/network/national-programs/<pid>", "GET")
def read_program(pid):
    return object_response(public(program_or_404(pid)))


@bp.route("/network/national-programs/<pid>/contributions", methods=["GET"])
@route("/network/national-programs/<pid>/contributions", "GET")
def program_contributions(pid):
    program_or_404(pid)
    args = request.args
    recs = [c for c in STORE.contributions.values() if c.get("program_id") == pid]
    for field in ("station_id", "contribution_status"):
        want = base.scalar_arg(args, field)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(r) for r in page], meta)


@bp.route("/network/national-programs/<pid>/carriage-agreements", methods=["GET"])
@route("/network/national-programs/<pid>/carriage-agreements", "GET")
def program_agreements(pid):
    program = program_or_404(pid)
    args = request.args
    recs = _agreements_for(program.get("program_code"))
    status = base.scalar_arg(args, "agreement_status")
    if status is not None:
        recs = [r for r in recs if r.get("agreement_status") == status]
    page, meta = base.paginate(recs, args)
    return array_response([carriage.agreement_view(STORE, r) for r in page], meta)


@bp.route("/network/national-programs/<pid>/move-to-production", methods=["POST"])
@route("/network/national-programs/<pid>/move-to-production", "POST")
def move_to_production(pid):
    program = program_or_404(pid)
    status = program.get("production_status")
    if status == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("DEVELOPMENT", "RESCHEDULED"):
        raise invalid_state("the program cannot enter production from its current state")
    if not program.get("program_title"):
        raise invalid_state("the program has no title")
    program["production_status"] = "PRODUCTION"
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/schedule", methods=["POST"])
@route("/network/national-programs/<pid>/schedule", "POST")
def schedule_program(pid):
    program = program_or_404(pid)
    status = program.get("production_status")
    if status == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "PRODUCTION":
        raise invalid_state("the program is not in production")
    premiere = C.parse_dt(program.get("national_premiere_at"))
    if premiere is None or premiere <= C.now():
        raise invalid_state("the program's premiere instant is not in the future")
    program["production_status"] = "SCHEDULED"
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/premiere", methods=["POST"])
@route("/network/national-programs/<pid>/premiere", "POST")
def premiere_program(pid):
    program = program_or_404(pid)
    status = program.get("production_status")
    if status == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "SCHEDULED":
        raise invalid_state("the program is not scheduled")
    premiere = C.parse_dt(program.get("national_premiere_at"))
    if premiere is None or C.now() < premiere:
        raise invalid_state("the program's premiere instant has not arrived")
    if program.get("clearance_required"):
        for agreement in _agreements_for(program.get("program_code")):
            for window in STORE.windows_of(agreement["id"]):
                if not window.get("is_cleared"):
                    raise ApiError("ERR_REVIEW_INCOMPLETE")
    program["production_status"] = "RUNNING"
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/publish", methods=["POST"])
@route("/network/national-programs/<pid>/publish", "POST")
def publish_program(pid):
    program = program_or_404(pid)
    status = program.get("production_status")
    if status == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "RUNNING":
        raise invalid_state("the program is not running")
    if int(program.get("licensed_contribution_count") or 0) < 1:
        raise invalid_state("the program holds no licensed contribution")
    program["production_status"] = "PUBLISHED"
    program["publication_cycle"] = int(program.get("publication_cycle") or 0) + 1
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/premiere-embargo", methods=["POST"])
@route("/network/national-programs/<pid>/premiere-embargo", "POST")
def premiere_embargo(pid):
    program = program_or_404(pid)
    if program.get("production_status") != "RUNNING":
        raise invalid_state("the program is not running")
    premiere = C.parse_dt(program.get("national_premiere_at"))
    if premiere is None or premiere <= C.now():
        raise invalid_state("the program's premiere instant has passed")
    agreements = _agreements_for(program.get("program_code"))
    if not agreements:
        raise invalid_state("no carriage agreement carries this program")
    for agreement in agreements:
        for window in STORE.windows_of(agreement["id"]):
            start = C.parse_dt(window.get("window_start"))
            if start is not None and start < premiere:
                if window.get("clearance_status") not in ("BROADCAST", "MISSED"):
                    window["clearance_status"] = "VIOLATED"
                    window["rejection_reason"] = "PREMIERE_EMBARGO"
                    carriage.accrue(window, "VIOLATED")
                    carriage.refresh_window_flags(STORE, window)
                    touch(window)
        if agreement.get("agreement_status") == "CARRIED":
            agreement["agreement_status"] = "EMBARGOED"
            touch(agreement)
        carriage.recompute_agreement_rollup(STORE, agreement)
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/reschedule-airings", methods=["POST"])
@route("/network/national-programs/<pid>/reschedule-airings", "POST")
def reschedule_airings(pid):
    program = program_or_404(pid)
    if program.get("production_status") == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if program.get("production_status") != "PUBLISHED":
        raise invalid_state("the program is not published")
    body = base.get_body(request.get_json(silent=True))
    new_premiere = base.as_instant(body.get("new_premiere_at"), "new_premiere_at")
    if C.parse_dt(new_premiere) <= C.now():
        raise invalid_state("the new premiere instant must lie in the future")
    program["national_premiere_at"] = new_premiere
    program["production_status"] = "RESCHEDULED"
    program["publication_cycle"] = int(program.get("publication_cycle") or 0) + 1
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/return-to-development", methods=["POST"])
@route("/network/national-programs/<pid>/return-to-development", "POST")
def return_to_development(pid):
    program = program_or_404(pid)
    if program.get("production_status") == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if program.get("production_status") != "PUBLISHED":
        raise invalid_state("the program is not published")
    program["production_status"] = "RESCHEDULED"
    program["publication_cycle"] = int(program.get("publication_cycle") or 0) + 1
    for contribution in STORE.contributions.values():
        if contribution.get("program_id") != program["id"]:
            continue
        if contribution.get("contribution_status") in COUNTED_STATUSES:
            contribution["contribution_status"] = "WITHDRAWN"
            touch(contribution)
    _recount_licenses(program)
    touch(program)
    return object_response(public(program))


@bp.route("/network/national-programs/<pid>/retire", methods=["POST"])
@route("/network/national-programs/<pid>/retire", "POST")
def retire_program(pid):
    program = program_or_404(pid)
    status = program.get("production_status")
    if status == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("RESCHEDULED", "PUBLISHED"):
        raise invalid_state("the program cannot be retired from its current state")
    # The ledger is checked at archive time, before the retirement mutates it.
    if not content.conservation_holds(STORE, program):
        raise ApiError("ERR_ARCHIVE_INVARIANT_VIOLATED")
    retiring_from_rescheduled = status == "RESCHEDULED"
    credit_sum = 0
    for contribution in STORE.contributions.values():
        if contribution.get("program_id") != program["id"]:
            continue
        if contribution.get("contribution_status") in (
            "LICENSED", "USED", "DRAFT", "SUBMITTED"
        ):
            credit_sum += int(contribution.get("compensation_credit_cents") or 0)
            contribution["contribution_status"] = "REJECTED"
            touch(contribution)
    if retiring_from_rescheduled:
        program["preliminary_license_credit_cents"] = int(
            program.get("preliminary_license_credit_cents") or 0
        ) + credit_sum
    _recount_licenses(program)
    program["production_status"] = "RETIRED"
    for agreement in _agreements_for(program.get("program_code")):
        if agreement.get("agreement_status") == "CARRIED":
            agreement["agreement_status"] = "TERMINATED"
            touch(agreement)
            for window in STORE.windows_of(agreement["id"]):
                if window.get("clearance_status") != "REJECTED":
                    window["clearance_status"] = "REJECTED"
                    carriage.accrue(window, "REJECTED")
                    carriage.refresh_window_flags(STORE, window)
                    touch(window)
            carriage.recompute_agreement_rollup(STORE, agreement)
    touch(program)
    return object_response(public(program))