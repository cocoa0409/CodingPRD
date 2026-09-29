"""Breeding programmes, objectives, the pipeline report and the logical clock."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import derive
import lookup
import mut
import store
import validators as v
from envelope import respond, respond_list
from errors import bad_request

bp = Blueprint("program", __name__)

STAGES = ["NURSERY", "STAGE_1", "STAGE_2", "STAGE_3", "PRE_COMMERCIAL", "COMMERCIAL", "DISCARDED"]


# ---------------------------------------------------------------------------
# POST /breeding-programs
# ---------------------------------------------------------------------------
@bp.post("/breeding-programs")
def create_program():
    auth.authorize("PipelineDirector")
    body = v.json_body()
    name = v.req_str(body, "name", min_len=1, max_len=120)
    crop_code = v.req_enum(body, "crop_code", v.CROP_CODES)
    market_zone = v.req_str(body, "market_zone")
    total_plot_budget = v.req_int(body, "total_plot_budget", minimum=1)
    total_budget_usd = calc.rhu(v.req_num(body, "total_budget_usd", gt=0), 2)

    rec = store.new_record()
    rec.update({
        "name": name,
        "crop_code": crop_code,
        "market_zone": market_zone,
        "total_plot_budget": total_plot_budget,
        "total_budget_usd": total_budget_usd,
        "status": "ACTIVE",
        "committed_plot_count": 0,
        "plot_budget_remaining": total_plot_budget,
        "committed_budget_usd": Decimal("0.00"),
        "active_line_count": 0,
        "pre_commercial_units_bags": 0,
    })
    store.programs[rec["id"]] = rec
    return respond(rec, 201)


# ---------------------------------------------------------------------------
# GET /breeding-programs/{id}
# ---------------------------------------------------------------------------
@bp.get("/breeding-programs/<pid>")
def read_program(pid):
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst")
    program = lookup.program(pid)
    auth.scope(program["id"])
    return respond(program)


# ---------------------------------------------------------------------------
# POST /breeding-programs/{id}/close
# ---------------------------------------------------------------------------
@bp.post("/breeding-programs/<pid>/close")
def close_program(pid):
    auth.authorize("PipelineDirector")
    program = lookup.program(pid)
    lookup.program_open(program)
    mut.force(program)
    program["status"] = "CLOSED"
    mut.commit()
    return respond(program)


# ---------------------------------------------------------------------------
# POST /breeding-programs/{id}/objectives
# ---------------------------------------------------------------------------
@bp.post("/breeding-programs/<pid>/objectives")
def create_objective(pid):
    auth.authorize("ProgramLead", "PipelineDirector")
    body = v.json_body()
    market_segment = v.req_str(body, "market_segment")
    target_yield = v.req_num(body, "target_yield_kg_per_ha", gt=0)
    resistances = body.get("required_disease_resistances")
    if resistances is None:
        resistances = []
    else:
        resistances = v.opt_enum_array(body, "required_disease_resistances", v.DISEASE_TRAITS)
    min_resistance_score = v.req_int(body, "min_resistance_score", minimum=1, maximum=9)
    quality_specs = v.opt_value_map(body, "quality_trait_specs", v.QUALITY_SPECS)
    yield_weight = v.req_num(body, "yield_weight", ge=0, le=1)
    disease_weight = v.req_num(body, "disease_weight", ge=0, le=1)
    quality_weight = v.req_num(body, "quality_weight", ge=0, le=1)
    if yield_weight + disease_weight + quality_weight != Decimal("1.00"):
        bad_request("yield_weight, disease_weight and quality_weight must sum to exactly 1.00.")
    min_advancement_index = v.req_num(body, "min_advancement_index", ge=0)
    min_generation_number = v.req_int(body, "min_generation_number", minimum=2)

    program = lookup.program(pid)
    auth.scope(program["id"])
    lookup.program_open(program)

    rec = store.new_record()
    rec.update({
        "program_id": program["id"],
        "market_segment": market_segment,
        "target_yield_kg_per_ha": target_yield,
        "required_disease_resistances": resistances,
        "min_resistance_score": min_resistance_score,
        "quality_trait_specs": quality_specs,
        "yield_weight": yield_weight,
        "disease_weight": disease_weight,
        "quality_weight": quality_weight,
        "min_advancement_index": min_advancement_index,
        "min_generation_number": min_generation_number,
    })
    store.objectives[rec["id"]] = rec
    return respond(rec, 201)


# ---------------------------------------------------------------------------
# GET /breeding-programs/{id}/objectives
# ---------------------------------------------------------------------------
@bp.get("/breeding-programs/<pid>/objectives")
def list_objectives(pid):
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst", "BreedingScientist")
    limit, offset = v.pagination()
    program = lookup.program(pid)
    auth.scope(program["id"])
    rows = [o for o in store.ordered(store.objectives) if o["program_id"] == program["id"]]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /breeding-objectives/{id}
# ---------------------------------------------------------------------------
@bp.get("/breeding-objectives/<oid>")
def read_objective(oid):
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst", "BreedingScientist")
    objective = lookup.objective(oid)
    auth.scope(objective["program_id"])
    return respond(objective)


# ---------------------------------------------------------------------------
# GET /breeding-programs/{id}/trial-series
# ---------------------------------------------------------------------------
@bp.get("/breeding-programs/<pid>/trial-series")
def list_program_series(pid):
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst", "TrialAgronomist")
    limit, offset = v.pagination()
    stage = v.query_enum("stage", v.SERIES_STAGES)
    status = v.query_enum("status", ["PLANNING", "PLANTED", "DATA_COMPLETE", "ANALYZED", "CLOSED"])
    program = lookup.program(pid)
    auth.scope(program["id"])
    rows = [s for s in store.ordered(store.series) if s["program_id"] == program["id"]]
    if stage is not None:
        rows = [s for s in rows if s["stage"] == stage]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /breeding-programs/{id}/pipeline-report
# ---------------------------------------------------------------------------
@bp.get("/breeding-programs/<pid>/pipeline-report")
def pipeline_report(pid):
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst")
    program = lookup.program(pid)
    auth.scope(program["id"])

    lines = derive.lines_of_program(program["id"])
    lines_by_stage = {stage: 0 for stage in STAGES}
    approved = 0
    suspended = 0
    for line in lines:
        lines_by_stage[line["pipeline_stage"]] = lines_by_stage.get(line["pipeline_stage"], 0) + 1
        if line["stewardship_status"] == "APPROVED":
            approved += 1
        elif line["stewardship_status"] == "SUSPENDED":
            suspended += 1

    active = sum(1 for ln in lines if ln["pipeline_stage"] not in ("DISCARDED", "COMMERCIAL"))
    discarded = sum(1 for ln in lines if ln["pipeline_stage"] == "DISCARDED")
    committed_usd = calc.dec(program["committed_budget_usd"])
    report = {
        "program_id": program["id"],
        "status": program["status"],
        "lines_by_stage": lines_by_stage,
        "active_line_count": active,
        "discarded_line_count": discarded,
        "committed_plot_count": program["committed_plot_count"],
        "plot_budget_remaining": program["plot_budget_remaining"],
        "total_plot_budget": program["total_plot_budget"],
        "committed_budget_usd": committed_usd,
        "budget_remaining_usd": calc.rhu(calc.dec(program["total_budget_usd"]) - committed_usd, 2),
        "pre_commercial_units_bags": program["pre_commercial_units_bags"],
        "stewardship_approved_line_count": approved,
        "stewardship_suspended_line_count": suspended,
    }
    return respond(report)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authorize(*auth.ALL_ROLES)
    body = v.json_body()
    moment = v.req_instant(body, "current_utc")
    store.set_clock(moment)
    return respond({"current_utc": store.fmt_instant(moment)})
