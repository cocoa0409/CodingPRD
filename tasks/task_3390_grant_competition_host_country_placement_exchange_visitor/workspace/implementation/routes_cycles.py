"""CompetitionCycle and CountryProgram endpoints."""

from flask import Blueprint

import envelope
import serialize
from auth import auth, require_roles
from constants import ROLE_PLATFORM_ADMIN, READ_ROLES
from errors import ApiError
from store import STORE, stamp_new, bump
from timeutil import fmt
from validate import (
    body,
    check_unknown,
    req,
    as_str,
    as_int,
    as_enum,
    as_dt,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("cycles", __name__)

CYCLE_ACTIONS = ("OPEN", "CLOSE", "BEGIN_SCREENING", "FINALIZE_AWARDS", "COMPLETE")
LANGUAGE_REQUIREMENTS = ("NONE", "BASIC", "PROFICIENT")

PROGRAM_FIELDS = (
    "country_code",
    "slot_quota",
    "min_duration_months",
    "max_duration_months",
    "monthly_stipend_standard_cents",
    "monthly_stipend_high_cents",
    "dependent_allowance_monthly_cents",
    "travel_allowance_cents",
    "health_benefit_monthly_cents",
    "language_requirement",
)

PROGRAM_PATCH_FIELDS = (
    "slot_quota",
    "min_duration_months",
    "max_duration_months",
    "monthly_stipend_standard_cents",
    "monthly_stipend_high_cents",
    "dependent_allowance_monthly_cents",
    "travel_allowance_cents",
    "health_benefit_monthly_cents",
    "language_requirement",
)

PROGRAM_INT_FIELDS = (
    "slot_quota",
    "min_duration_months",
    "max_duration_months",
    "monthly_stipend_standard_cents",
    "monthly_stipend_high_cents",
    "dependent_allowance_monthly_cents",
    "travel_allowance_cents",
    "health_benefit_monthly_cents",
)


# ---------------------------------------------------------------------------
# CompetitionCycle
# ---------------------------------------------------------------------------

@bp.post("/exchange/cycles")
def create_cycle():
    _, role = auth()
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    payload = body()
    check_unknown(payload, {"academic_year", "application_deadline"})
    academic_year = as_str(req(payload, "academic_year"), "academic_year")
    deadline = as_dt(req(payload, "application_deadline"), "application_deadline")
    cycle = {
        "academic_year": academic_year,
        "application_deadline": fmt(deadline),
        "status": "DRAFT",
    }
    stamp_new(cycle)
    STORE.cycles[cycle["id"]] = cycle
    return envelope.ok(serialize.cycle_out(cycle), 201)


@bp.get("/exchange/cycles/<cid>")
def get_cycle(cid):
    _, role = auth()
    require_roles(role, READ_ROLES)
    cycle = STORE.cycles.get(cid)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "No competition cycle with the given id")
    return envelope.ok(serialize.cycle_out(cycle))


@bp.post("/exchange/cycles/<cid>/transition")
def cycle_transition(cid):
    _, role = auth()
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    cycle = STORE.cycles.get(cid)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "No competition cycle with the given id")
    payload = body()
    check_unknown(payload, {"action"})
    action = payload.get("action")
    if not isinstance(action, str) or action not in CYCLE_ACTIONS:
        raise V("Unknown action for cycle transition: %r" % (action,))

    if action == "OPEN":
        if cycle["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT cycle can be opened")
        if not any(p["cycle_id"] == cid for p in STORE.programs.values()):
            raise ApiError(
                "ERR_NO_COUNTRY_PROGRAMS",
                409,
                "Cycle cannot open without at least one country program",
            )
        cycle["status"] = "OPEN"
    elif action == "CLOSE":
        if cycle["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Only an OPEN cycle can be closed")
        cycle["status"] = "CLOSED"
    elif action == "BEGIN_SCREENING":
        if cycle["status"] != "CLOSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only a CLOSED cycle can enter screening")
        cycle["status"] = "SCREENING"
    elif action == "FINALIZE_AWARDS":
        if cycle["status"] != "SCREENING":
            raise ApiError("ERR_INVALID_STATE", 409, "Only a SCREENING cycle can finalize awards")
        pending = any(
            a["cycle_id"] == cid
            and a["status"] in ("CAMPUS_REVIEW", "NATIONAL_SCREENING", "HOST_REVIEW")
            for a in STORE.applications.values()
        )
        if pending:
            raise ApiError(
                "ERR_APPLICATIONS_PENDING",
                409,
                "Applications still under review block awards finalization",
            )
        # Sweeps: DRAFT -> WITHDRAWN, ALTERNATE -> NOT_SELECTED.
        for a in STORE.applications.values():
            if a["cycle_id"] != cid:
                continue
            if a["status"] == "DRAFT":
                a["status"] = "WITHDRAWN"
                bump(a)
            elif a["status"] == "ALTERNATE":
                a["status"] = "NOT_SELECTED"
                bump(a)
        cycle["status"] = "AWARDS_FINALIZED"
    else:  # COMPLETE
        if cycle["status"] != "AWARDS_FINALIZED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only an AWARDS_FINALIZED cycle can complete")
        cycle["status"] = "COMPLETED"

    bump(cycle)
    return envelope.ok(serialize.cycle_out(cycle))


# ---------------------------------------------------------------------------
# CountryProgram
# ---------------------------------------------------------------------------

@bp.post("/exchange/cycles/<cid>/country-programs")
def create_program(cid):
    _, role = auth()
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    cycle = STORE.cycles.get(cid)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "No competition cycle with the given id")
    payload = body()
    check_unknown(payload, set(PROGRAM_FIELDS))
    program = {"cycle_id": cid}
    program["country_code"] = as_str(req(payload, "country_code"), "country_code")
    for field in PROGRAM_INT_FIELDS:
        program[field] = as_int(req(payload, field), field)
    program["language_requirement"] = as_enum(
        req(payload, "language_requirement"), "language_requirement", LANGUAGE_REQUIREMENTS
    )
    stamp_new(program)
    STORE.programs[program["id"]] = program
    return envelope.ok(serialize.program_out(program), 201)


@bp.get("/exchange/cycles/<cid>/country-programs")
def list_programs(cid):
    _, role = auth()
    require_roles(role, READ_ROLES)
    cycle = STORE.cycles.get(cid)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "No competition cycle with the given id")
    limit, offset = pagination()
    items = [p for p in STORE.programs.values() if p["cycle_id"] == cid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.program_out(p) for p in page], total, limit, offset)


@bp.get("/exchange/country-programs/<pid>")
def get_program(pid):
    _, role = auth()
    require_roles(role, READ_ROLES)
    program = STORE.programs.get(pid)
    if program is None:
        raise ApiError("ERR_COUNTRY_PROGRAM_NOT_FOUND", 404, "No country program with the given id")
    return envelope.ok(serialize.program_out(program))


@bp.patch("/exchange/country-programs/<pid>")
def patch_program(pid):
    _, role = auth()
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    program = STORE.programs.get(pid)
    if program is None:
        raise ApiError("ERR_COUNTRY_PROGRAM_NOT_FOUND", 404, "No country program with the given id")
    payload = body()
    check_unknown(payload, set(PROGRAM_PATCH_FIELDS))
    updates = {}
    for field in PROGRAM_PATCH_FIELDS:
        if field not in payload:
            continue
        if field == "language_requirement":
            updates[field] = as_enum(payload[field], field, LANGUAGE_REQUIREMENTS)
        else:
            updates[field] = as_int(payload[field], field)
    cycle = STORE.cycles[program["cycle_id"]]
    if cycle["status"] != "DRAFT":
        raise ApiError(
            "ERR_CYCLE_PHASE_FORBIDS",
            409,
            "Country program edits are only allowed while the cycle is DRAFT",
        )
    program.update(updates)
    bump(program)
    return envelope.ok(serialize.program_out(program))
