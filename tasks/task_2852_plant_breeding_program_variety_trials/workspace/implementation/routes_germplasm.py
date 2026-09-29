"""Nursery blocks, crossing blocks, breeding lines, nursery plantings and
marker-assisted backcross projects."""

from flask import Blueprint

import auth
import calc
import derive
import lookup
import mut
import store
import validators as v
from envelope import respond, respond_list
from errors import ApiError, bad_request

bp = Blueprint("germplasm", __name__)

BLOCK_STATUSES = ["PLANNED", "POLLINATED", "CLOSED"]
PLANTING_STATUSES = ["SCHEDULED", "PLANTED", "HARVESTED", "FAILED"]
PROJECT_STATUSES = ["ACTIVE", "CONVERTED", "TERMINATED"]


def block_view(block):
    out = dict(block)
    out["occupancy_status"] = derive.block_occupancy_status(block)
    return out


# ===========================================================================
# NurseryBlock
# ===========================================================================
@bp.post("/nursery-blocks")
def create_nursery_block():
    auth.authorize("BreedingScientist")
    body = v.json_body()
    block_code = v.req_str(body, "block_code")
    nursery_type = v.req_enum(body, "nursery_type", v.NURSERY_TYPES)
    location_code = v.req_str(body, "location_code")
    plot_count = v.req_int(body, "plot_count", minimum=1)
    fallow = v.opt_int(body, "fallow_buffer_days", default=14, minimum=0)

    for existing in store.nursery_blocks.values():
        if existing["block_code"] == block_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "block_code '%s' is already registered." % block_code)

    rec = store.new_record()
    rec.update({
        "block_code": block_code,
        "nursery_type": nursery_type,
        "location_code": location_code,
        "plot_count": plot_count,
        "fallow_buffer_days": fallow,
    })
    store.nursery_blocks[rec["id"]] = rec
    return respond(block_view(rec), 201)


@bp.get("/nursery-blocks/<bid>")
def read_nursery_block(bid):
    auth.authorize("PipelineDirector", "BreedingScientist", "DataAnalyst")
    block = lookup.nursery_block(bid)
    return respond(block_view(block))


# ===========================================================================
# CrossingBlock
# ===========================================================================
@bp.post("/crossing-blocks")
def create_crossing_block():
    auth.authorize("BreedingScientist", "ProgramLead")
    body = v.json_body()
    program_id = v.req_id(body, "program_id")
    nursery_block_id = v.req_id(body, "nursery_block_id")
    season_code = v.req_str(body, "season_code")
    planned = v.req_int(body, "planned_cross_count", minimum=1)

    auth.scope(program_id)
    program = lookup.program(program_id)
    block = lookup.nursery_block(nursery_block_id)
    lookup.program_open(program)

    rec = store.new_record()
    rec.update({
        "program_id": program["id"],
        "nursery_block_id": block["id"],
        "season_code": season_code,
        "planned_cross_count": planned,
        "realized_cross_count": 0,
        "progeny_line_count": 0,
        "status": "PLANNED",
    })
    store.crossing_blocks[rec["id"]] = rec
    return respond(rec, 201)


@bp.get("/crossing-blocks/<cid>")
def read_crossing_block(cid):
    auth.authorize("PipelineDirector", "BreedingScientist", "ProgramLead", "DataAnalyst")
    block = lookup.crossing_block(cid)
    auth.scope(block["program_id"])
    return respond(block)


@bp.get("/crossing-blocks")
def list_crossing_blocks():
    auth.authorize("PipelineDirector", "BreedingScientist", "ProgramLead", "DataAnalyst")
    limit, offset = v.pagination()
    program_id = v.query_str("program_id")
    nursery_block_id = v.query_str("nursery_block_id")
    status = v.query_enum("status", BLOCK_STATUSES)
    season_code = v.query_str("season_code")
    rows = store.ordered(store.crossing_blocks)
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if nursery_block_id is not None:
        rows = [r for r in rows if r["nursery_block_id"] == nursery_block_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if season_code is not None:
        rows = [r for r in rows if r["season_code"] == season_code]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


@bp.post("/crossing-blocks/<cid>/pollinate")
def pollinate(cid):
    auth.authorize("BreedingScientist")
    body = v.json_body()
    realized = v.req_int(body, "realized_cross_count", minimum=1)

    block = lookup.crossing_block(cid)
    program = store.programs.get(block["program_id"])
    lookup.program_open(program)
    if block["status"] != "PLANNED":
        raise ApiError("ERR_BLOCK_NOT_POLLINATED",
                       "Only a PLANNED crossing block may record pollination.")
    if realized > block["planned_cross_count"]:
        bad_request("realized_cross_count may not exceed planned_cross_count.")

    mut.force(block)
    block["status"] = "POLLINATED"
    block["realized_cross_count"] = realized
    mut.commit()
    return respond(block)


def _read_line_inputs(body):
    """Shared shape validation for the two line-registration routes."""
    return {
        "designation": v.req_str(body, "designation"),
        "generation_number": v.req_int(body, "generation_number", minimum=2),
        "seed_inventory_g": v.opt_int(body, "seed_inventory_g", default=0, minimum=0),
        "disease_resistance_scores": v.opt_score_map(
            body, "disease_resistance_scores", v.DISEASE_TRAITS, 1, 9),
        "quality_trait_values": v.opt_value_map(
            body, "quality_trait_values", v.QUALITY_TRAITS),
    }


def _check_designation_unique(program_id, designation):
    for existing in store.lines.values():
        if existing["program_id"] == program_id and existing["designation"] == designation:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "designation '%s' already exists in this programme." % designation)


def _new_line(program, objective, fields, origin_block_id, female, male):
    rec = store.new_record()
    rec.update({
        "program_id": program["id"],
        "objective_id": objective["id"],
        "origin_block_id": origin_block_id,
        "female_parent_line_id": female,
        "male_parent_line_id": male,
        "designation": fields["designation"],
        "generation_number": fields["generation_number"],
        "pipeline_stage": "NURSERY",
        "stewardship_status": "NOT_REQUIRED",
        "disease_resistance_scores": dict(fields["disease_resistance_scores"]),
        "quality_trait_values": dict(fields["quality_trait_values"]),
        "seed_inventory_g": fields["seed_inventory_g"],
        "cumulative_seed_produced_g": fields["seed_inventory_g"],
        "nursery_cycles_completed": 0,
        "advancement_readiness": "NOT_READY",
        "advancement_index_provisional": None,
        "reserved_seed_g": 0,
        "consumed_seed_g": 0,
        "planned_launch_units_bags": 0,
    })
    rec["advancement_readiness"] = derive.derive_readiness(rec)
    rec["advancement_index_provisional"] = calc.provisional_index(objective, rec, None)
    store.lines[rec["id"]] = rec
    return rec


@bp.post("/crossing-blocks/<cid>/progenies")
def register_progeny(cid):
    auth.authorize("BreedingScientist")
    body = v.json_body()
    objective_id = v.req_id(body, "objective_id")
    fields = _read_line_inputs(body)
    female_id = v.req_id(body, "female_parent_line_id")
    male_id = v.req_id(body, "male_parent_line_id")

    block = lookup.crossing_block(cid)
    objective = lookup.objective(objective_id)
    female = lookup.line(female_id)
    male = lookup.line(male_id)

    program = store.programs.get(block["program_id"])
    lookup.program_open(program)
    if block["status"] != "POLLINATED":
        raise ApiError("ERR_BLOCK_NOT_POLLINATED",
                       "Progeny may only be registered against a POLLINATED crossing block.")
    if objective["program_id"] != program["id"]:
        raise ApiError("ERR_OBJECTIVE_PROGRAM_MISMATCH",
                       "The objective belongs to a different breeding programme.")
    for parent in (female, male):
        if parent["program_id"] != program["id"]:
            raise ApiError("ERR_PARENT_LINE_PROGRAM_MISMATCH",
                           "A parent line belongs to a different breeding programme.")
    _check_designation_unique(program["id"], fields["designation"])

    line = _new_line(program, objective, fields, block["id"], female["id"], male["id"])

    mut.watch(block)
    block["progeny_line_count"] = len(
        [l for l in store.lines.values()
         if l.get("origin_block_id") == block["id"] and l["pipeline_stage"] != "DISCARDED"])
    if block["progeny_line_count"] == block["realized_cross_count"]:
        block["status"] = "CLOSED"
    derive.recompute_program(program)
    mut.commit()
    return respond(line, 201)


# ===========================================================================
# BreedingLine
# ===========================================================================
@bp.post("/breeding-lines")
def create_line():
    auth.authorize("BreedingScientist", "ProgramLead")
    body = v.json_body()
    program_id = v.req_id(body, "program_id")
    objective_id = v.req_id(body, "objective_id")
    fields = _read_line_inputs(body)
    female_id = v.opt_id(body, "female_parent_line_id")
    male_id = v.opt_id(body, "male_parent_line_id")

    auth.scope(program_id)
    program = lookup.program(program_id)
    objective = lookup.objective(objective_id)
    female = lookup.line(female_id) if female_id is not None else None
    male = lookup.line(male_id) if male_id is not None else None

    lookup.program_open(program)
    if objective["program_id"] != program["id"]:
        raise ApiError("ERR_OBJECTIVE_PROGRAM_MISMATCH",
                       "The objective belongs to a different breeding programme.")
    for parent in (female, male):
        if parent is not None and parent["program_id"] != program["id"]:
            raise ApiError("ERR_PARENT_LINE_PROGRAM_MISMATCH",
                           "A parent line belongs to a different breeding programme.")
    _check_designation_unique(program["id"], fields["designation"])

    line = _new_line(program, objective, fields, None,
                     female["id"] if female else None,
                     male["id"] if male else None)
    derive.recompute_program(program)
    mut.commit()
    return respond(line, 201)


@bp.get("/breeding-lines/<lid>")
def read_line(lid):
    auth.authorize("PipelineDirector", "BreedingScientist", "ProgramLead", "DataAnalyst",
                   "RegulatoryOfficer", "SupplyPlanner", "TrialAgronomist")
    line = lookup.line(lid)
    auth.scope(line["program_id"])
    return respond(line)


@bp.get("/breeding-lines")
def list_lines():
    auth.authorize("PipelineDirector", "BreedingScientist", "ProgramLead", "DataAnalyst",
                   "RegulatoryOfficer", "SupplyPlanner")
    limit, offset = v.pagination()
    filters = {
        "program_id": v.query_str("program_id"),
        "objective_id": v.query_str("objective_id"),
        "origin_block_id": v.query_str("origin_block_id"),
        "female_parent_line_id": v.query_str("female_parent_line_id"),
        "male_parent_line_id": v.query_str("male_parent_line_id"),
    }
    pipeline_stage = v.query_enum("pipeline_stage", v.PIPELINE_STAGES)
    stewardship_status = v.query_enum("stewardship_status", v.STEWARDSHIP_STATUSES)
    rows = store.ordered(store.lines)
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    if pipeline_stage is not None:
        rows = [r for r in rows if r["pipeline_stage"] == pipeline_stage]
    if stewardship_status is not None:
        rows = [r for r in rows if r["stewardship_status"] == stewardship_status]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


# ===========================================================================
# NurseryPlanting
# ===========================================================================
@bp.post("/nursery-plantings")
def create_planting():
    auth.authorize("BreedingScientist")
    body = v.json_body()
    block_id = v.req_id(body, "nursery_block_id")
    line_id = v.req_id(body, "line_id")
    sow_date = v.req_date(body, "sow_date")
    expected_harvest_date = v.req_date(body, "expected_harvest_date")
    plot_count = v.req_int(body, "plot_count", minimum=1)
    if not expected_harvest_date > sow_date:
        bad_request("expected_harvest_date must be strictly later than sow_date.")

    block = lookup.nursery_block(block_id)
    line = lookup.line(line_id)
    program = store.programs.get(line["program_id"])
    lookup.program_open(program)
    lookup.line_not_discarded(line)

    occupancy_end_date = derive.occupancy_end(expected_harvest_date, block["fallow_buffer_days"])
    if derive.block_intervals_conflict(block["id"], sow_date, occupancy_end_date):
        raise ApiError("ERR_BLOCK_OCCUPANCY_CONFLICT",
                       "The requested occupancy interval overlaps another planting on this block.")
    admissible = v.WINTER_MONTHS if block["nursery_type"] == "WINTER" else v.SUMMER_MONTHS
    if sow_date.month not in admissible:
        raise ApiError("ERR_NURSERY_SEASON_MISMATCH",
                       "The sow_date month is not admissible for a %s nursery block."
                       % block["nursery_type"])
    if sow_date < store.clock_date():
        raise ApiError("ERR_SOW_DATE_IN_PAST", "sow_date may not be earlier than today.")
    if plot_count > block["plot_count"]:
        raise ApiError("ERR_BLOCK_PLOT_COUNT_EXCEEDED",
                       "plot_count exceeds the nursery block's physical plot_count.")
    if plot_count > program["plot_budget_remaining"]:
        raise ApiError("ERR_PROGRAM_PLOT_BUDGET_EXCEEDED",
                       "The planting exceeds the programme's remaining plot budget.")

    rec = store.new_record()
    rec.update({
        "nursery_block_id": block["id"],
        "line_id": line["id"],
        "sow_date": sow_date,
        "expected_harvest_date": expected_harvest_date,
        "occupancy_end_date": occupancy_end_date,
        "plot_count": plot_count,
        "actual_harvest_date": None,
        "harvested_seed_g": None,
        "generation_advanced_to": None,
        "status": "SCHEDULED",
    })
    store.plantings[rec["id"]] = rec
    derive.recompute_program(program)
    mut.commit()
    return respond(rec, 201)


@bp.get("/nursery-plantings/<pid>")
def read_planting(pid):
    auth.authorize("PipelineDirector", "BreedingScientist", "DataAnalyst")
    return respond(lookup.planting(pid))


@bp.get("/nursery-plantings")
def list_plantings():
    auth.authorize("PipelineDirector", "BreedingScientist", "DataAnalyst")
    limit, offset = v.pagination()
    block_id = v.query_str("nursery_block_id")
    line_id = v.query_str("line_id")
    status = v.query_enum("status", PLANTING_STATUSES)
    rows = store.ordered(store.plantings)
    if block_id is not None:
        rows = [r for r in rows if r["nursery_block_id"] == block_id]
    if line_id is not None:
        rows = [r for r in rows if r["line_id"] == line_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


@bp.post("/nursery-plantings/<pid>/plant")
def plant_planting(pid):
    auth.authorize("BreedingScientist")
    planting = lookup.planting(pid)
    line = store.lines.get(planting["line_id"])
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if planting["status"] != "SCHEDULED":
        raise ApiError("ERR_PLANTING_INVALID_STATE",
                       "Only a SCHEDULED planting may be marked as sown.")
    lookup.line_not_discarded(line)

    mut.force(planting)
    planting["status"] = "PLANTED"
    derive.recompute_program(program)
    mut.commit()
    return respond(planting)


@bp.post("/nursery-plantings/<pid>/harvest")
def harvest_planting(pid):
    auth.authorize("BreedingScientist")
    body = v.json_body()
    actual_harvest_date = v.req_date(body, "actual_harvest_date")
    harvested_seed_g = v.req_int(body, "harvested_seed_g", minimum=0)

    planting = lookup.planting(pid)
    line = store.lines.get(planting["line_id"])
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if planting["status"] != "PLANTED":
        raise ApiError("ERR_PLANTING_INVALID_STATE",
                       "Only a PLANTED planting may be harvested.")
    if actual_harvest_date < planting["sow_date"]:
        bad_request("actual_harvest_date may not be earlier than sow_date.")

    mut.force(planting, line)
    planting["actual_harvest_date"] = actual_harvest_date
    planting["harvested_seed_g"] = harvested_seed_g
    # both branches bank the seed
    line["seed_inventory_g"] = line["seed_inventory_g"] + harvested_seed_g
    line["cumulative_seed_produced_g"] = line["cumulative_seed_produced_g"] + harvested_seed_g
    if harvested_seed_g >= calc.MIN_ADVANCE_SEED_G:
        planting["status"] = "HARVESTED"
        line["generation_number"] = line["generation_number"] + 1
        line["nursery_cycles_completed"] = line["nursery_cycles_completed"] + 1
        planting["generation_advanced_to"] = line["generation_number"]
        line["advancement_readiness"] = derive.derive_readiness(line)
    else:
        planting["status"] = "FAILED"
        planting["generation_advanced_to"] = None
    derive.recompute_program(program)
    mut.commit()
    return respond(planting)


# ===========================================================================
# BackcrossProject
# ===========================================================================
def _write_genome_pct(project):
    project["recurrent_genome_pct"] = calc.marker_recovery_pct(
        project["bc_generation"], project["marker_assisted"], project["target_marker_present"])


@bp.post("/backcross-projects")
def create_project():
    auth.authorize("BreedingScientist")
    body = v.json_body()
    recurrent_id = v.req_id(body, "recurrent_line_id")
    donor_id = v.req_id(body, "donor_line_id")
    target_trait_code = v.req_enum(body, "target_trait_code", v.DISEASE_TRAITS)
    marker_assisted = v.req_bool(body, "marker_assisted")
    if recurrent_id == donor_id:
        bad_request("donor_line_id must differ from recurrent_line_id.")

    recurrent = lookup.line(recurrent_id)
    donor = lookup.line(donor_id)
    program = derive.program_of_line(recurrent)
    lookup.program_open(program)
    lookup.line_not_discarded(recurrent)
    lookup.line_not_discarded(donor)
    if donor["program_id"] != recurrent["program_id"]:
        raise ApiError("ERR_PARENT_LINE_PROGRAM_MISMATCH",
                       "The donor line belongs to a different breeding programme.")

    rec = store.new_record()
    rec.update({
        "recurrent_line_id": recurrent["id"],
        "donor_line_id": donor["id"],
        "target_trait_code": target_trait_code,
        "marker_assisted": marker_assisted,
        "bc_generation": 1,
        "target_marker_present": False,
        "status": "ACTIVE",
    })
    _write_genome_pct(rec)
    store.projects[rec["id"]] = rec
    return respond(rec, 201)


@bp.get("/backcross-projects/<bid>")
def read_project(bid):
    auth.authorize("PipelineDirector", "BreedingScientist", "ProgramLead", "DataAnalyst")
    project = lookup.project(bid)
    line = store.lines.get(project["recurrent_line_id"])
    auth.scope(line["program_id"] if line else None)
    return respond(project)


@bp.get("/backcross-projects")
def list_projects():
    auth.authorize("PipelineDirector", "BreedingScientist", "ProgramLead", "DataAnalyst")
    limit, offset = v.pagination()
    recurrent_line_id = v.query_str("recurrent_line_id")
    donor_line_id = v.query_str("donor_line_id")
    status = v.query_enum("status", PROJECT_STATUSES)
    target_trait_code = v.query_enum("target_trait_code", v.DISEASE_TRAITS)
    rows = store.ordered(store.projects)
    if recurrent_line_id is not None:
        rows = [r for r in rows if r["recurrent_line_id"] == recurrent_line_id]
    if donor_line_id is not None:
        rows = [r for r in rows if r["donor_line_id"] == donor_line_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if target_trait_code is not None:
        rows = [r for r in rows if r["target_trait_code"] == target_trait_code]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


@bp.post("/backcross-projects/<bid>/marker-cycle")
def marker_cycle(bid):
    auth.authorize("BreedingScientist")
    body = v.json_body()
    marker_present = v.req_bool(body, "target_marker_present")

    project = lookup.project(bid)
    recurrent = store.lines.get(project["recurrent_line_id"])
    program = derive.program_of_line(recurrent)
    lookup.program_open(program)
    if project["status"] != "ACTIVE":
        raise ApiError("ERR_PROJECT_NOT_ACTIVE",
                       "Only an ACTIVE backcross project may run another marker cycle.")
    lookup.line_not_discarded(recurrent)

    mut.force(project)
    project["bc_generation"] = project["bc_generation"] + 1
    project["target_marker_present"] = marker_present
    _write_genome_pct(project)

    if project["recurrent_genome_pct"] >= calc.CONVERSION_THRESHOLD_PCT and marker_present:
        project["status"] = "CONVERTED"
        scores = dict(recurrent["disease_resistance_scores"])
        existing = scores.get(project["target_trait_code"])
        if existing is None or existing < calc.CONVERTED_TRAIT_SCORE:
            scores[project["target_trait_code"]] = calc.CONVERTED_TRAIT_SCORE
        mut.force(recurrent)
        recurrent["disease_resistance_scores"] = scores
        derive.recompute_provisional_index(recurrent)
    mut.commit()
    return respond(project)
