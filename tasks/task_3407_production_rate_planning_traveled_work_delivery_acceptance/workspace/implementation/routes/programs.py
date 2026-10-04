"""Production programs and rate cases (PRD 3.1, 3.2)."""
from flask import Blueprint

import calc
import svc
from core import (
    ALL_ROLES,
    ApiError,
    body,
    db,
    endpoint,
    f_int,
    f_month,
    f_str,
    logical_month,
    month_add,
    new_row,
    paginate,
    parse_month,
    raw_int,
    respond_object,
    sort_created,
    touch,
    q_enum,
)

bp = Blueprint("programs", __name__, url_prefix="/api")

RATE_CASE_STATUSES = ("DRAFT", "ANNOUNCED", "GATED_REVIEW", "COMMITTED", "SHELVED")


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
@bp.post("/programs")
@endpoint("ProgramAdmin")
def create_program():
    payload = body()
    # rung 8 -- uniqueness (model_code) fires before body-shape checks
    candidate = payload.get("model_code")
    if isinstance(candidate, str) and any(
        p["model_code"] == candidate for p in db.programs.values()
    ):
        raise ApiError("ERR_DUPLICATE_CODE")
    # rung 10 -- body shape
    model_code = f_str(payload, "model_code")
    current_rate_per_month = f_int(payload, "current_rate_per_month", minimum=1)
    required_component_codes = f_int(payload, "required_component_codes", minimum=1)
    rework_budget_total_cents = f_int(payload, "rework_budget_total_cents", minimum=0)
    program = new_row(
        "ProductionProgram",
        model_code=model_code,
        current_rate_per_month=current_rate_per_month,
        required_component_codes=required_component_codes,
        rework_budget_total_cents=rework_budget_total_cents,
    )
    db.programs[program["id"]] = program
    return respond_object(svc.dump_program(program), 201)


@bp.get("/programs/<program_id>")
@endpoint(*ALL_ROLES)
def get_program(program_id):
    program = svc.need_program(program_id)
    # Live recomputation of readiness, reserve, fees, posture (PRD 2.9).
    return respond_object(svc.dump_program(program))


# ---------------------------------------------------------------------------
# Rate cases
# ---------------------------------------------------------------------------
@bp.post("/programs/<program_id>/rate-cases")
@endpoint("ProductionPlanner")
def create_rate_case(program_id):
    program = svc.need_program(program_id)
    payload = body()
    # rung 4 -- OCC: expected_program_version vs the program's current version
    expected = payload.get("expected_program_version")
    if raw_int(expected) and expected != program["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # rung 7 -- effective_month not earlier than the current logical month
    month = parse_month(payload.get("effective_month"))
    if month is not None and month < logical_month():
        raise ApiError("ERR_WINDOW_INVALID")
    # rung 8 -- proposed_rate must differ from the committed rate
    proposed = payload.get("proposed_rate")
    if raw_int(proposed) and proposed == program["current_rate_per_month"]:
        raise ApiError("ERR_RATE_UNCHANGED")
    # rung 10 -- body shape
    proposed_rate = f_int(payload, "proposed_rate", minimum=1)
    effective_month = f_month(payload, "effective_month")
    demand_backlog_units = f_int(payload, "demand_backlog_units", minimum=0)
    f_int(payload, "expected_program_version")
    case = new_row(
        "RateCase",
        program_id=program["id"],
        proposed_rate=proposed_rate,
        effective_month=effective_month,
        demand_backlog_units=demand_backlog_units,
        supply_readiness_snapshot_pct=None,
        workforce_readiness_snapshot_pct=None,
        burden_penalty_snapshot=None,
        readiness_index_snapshot=None,
        gating_verdict=None,
        status="DRAFT",
    )
    db.rate_cases[case["id"]] = case
    # Creating the case itself advances the program's version (PRD 3.2).
    touch(program)
    return respond_object(svc.dump_rate_case(case), 201)


@bp.get("/programs/<program_id>/rate-cases")
@endpoint("ProgramAdmin", "ProductionPlanner")
def list_rate_cases(program_id):
    svc.need_program(program_id)
    status = q_enum("status", RATE_CASE_STATUSES)
    rows = [rc for rc in db.rate_cases.values() if rc["program_id"] == program_id]
    if status is not None:
        rows = [rc for rc in rows if rc["status"] == status]
    return paginate(sort_created(rows), svc.dump_rate_case)


@bp.post("/rate-cases/<case_id>/announce")
@endpoint("ProductionPlanner")
def announce_rate_case(case_id):
    case = svc.need_rate_case(case_id)
    if case["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_TRANSITION")
    case["status"] = "ANNOUNCED"
    touch(case)
    program = svc.need_program(case["program_id"])
    # program.announced_target_rate is computed live; the announce advances the
    # program's version (PRD 3.2).
    touch(program)
    return respond_object(svc.dump_rate_case(case))


@bp.post("/rate-cases/<case_id>/request-gating-review")
@endpoint("ProductionPlanner")
def request_gating_review(case_id):
    case = svc.need_rate_case(case_id)
    if case["status"] != "ANNOUNCED":
        raise ApiError("ERR_INVALID_TRANSITION")
    program = svc.need_program(case["program_id"])
    # Freeze the evidence against the proposed rate (PRD 3.2).
    case["supply_readiness_snapshot_pct"] = calc.supply_pct(program, case["proposed_rate"])
    case["workforce_readiness_snapshot_pct"] = calc.workforce_pct(program)
    case["burden_penalty_snapshot"] = calc.burden_penalty(program)
    index = calc.readiness_index(program, case["proposed_rate"])
    case["readiness_index_snapshot"] = index
    case["gating_verdict"] = (
        "PASS"
        if index >= calc.GATING_THRESHOLD_INDEX
        and calc.open_escape_count(program["id"]) == 0
        else "FAIL"
    )
    case["status"] = "GATED_REVIEW"
    touch(case)
    return respond_object(svc.dump_rate_case(case))


@bp.post("/rate-cases/<case_id>/commit")
@endpoint("ProductionPlanner")
def commit_rate_case(case_id):
    case = svc.need_rate_case(case_id)
    if case["status"] != "GATED_REVIEW":
        raise ApiError("ERR_INVALID_TRANSITION")
    if case["gating_verdict"] != "PASS":
        raise ApiError("ERR_GATING_CRITERIA_UNMET")
    program = svc.need_program(case["program_id"])
    # Cascade link 1: the committed rate becomes the program's current rate.
    program["current_rate_per_month"] = case["proposed_rate"]
    touch(program)
    # Cascade link 2: commitments re-rate against the new assumption.
    for commitment in calc.program_commitments(program["id"]):
        assumed = commitment["assumed_rate_at_order"]
        if assumed is None:
            continue
        if commitment["status"] == "ORDERED" and assumed > case["proposed_rate"]:
            commitment["status"] = "AT_RISK"
            touch(commitment)
        elif commitment["status"] == "AT_RISK" and assumed <= case["proposed_rate"]:
            commitment["status"] = "ORDERED"
            touch(commitment)
    case["status"] = "COMMITTED"
    touch(case)
    # Cascade link 3: reserve recomputes live; link 4: on DISTRESSED posture every
    # other case of this program still in GATED_REVIEW is auto-shelved.
    if calc.posture(program) == "DISTRESSED":
        for other in db.rate_cases.values():
            if (
                other["program_id"] == program["id"]
                and other["id"] != case["id"]
                and other["status"] == "GATED_REVIEW"
            ):
                other["status"] = "SHELVED"
                touch(other)
    return respond_object(svc.dump_rate_case(case))


@bp.post("/rate-cases/<case_id>/shelve")
@endpoint("ProductionPlanner")
def shelve_rate_case(case_id):
    case = svc.need_rate_case(case_id)
    if case["status"] not in ("DRAFT", "ANNOUNCED", "GATED_REVIEW"):
        raise ApiError("ERR_INVALID_TRANSITION")
    case["status"] = "SHELVED"
    touch(case)
    # announced_target_rate falls back over the remaining live cases (computed).
    return respond_object(svc.dump_rate_case(case))
