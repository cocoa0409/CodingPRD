"""Stage-gate advancement decisions, stewardship agreements and seed increase."""

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

bp = Blueprint("gates", __name__)

AGREEMENT_STATUSES = ["DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "SUSPENDED"]
LOT_STATUSES = ["RESERVED", "IN_PRODUCTION", "ON_HOLD", "COMPLETED", "CANCELLED"]

# ADVANCE ladder: current stage -> (next stage, the series stage that carries it)
ADVANCE_LADDER = {
    "NURSERY": ("STAGE_1", "STAGE_1"),
    "STAGE_1": ("STAGE_2", "STAGE_1"),
    "STAGE_2": ("STAGE_3", "STAGE_2"),
    "STAGE_3": ("PRE_COMMERCIAL", "STAGE_3"),
    "PRE_COMMERCIAL": ("COMMERCIAL", "STAGE_3"),
}


# ===========================================================================
# AdvancementDecision
# ===========================================================================
@bp.post("/advancement-decisions")
def create_decision():
    auth.authorize("PipelineDirector")
    body = v.json_body()
    line_id = v.req_id(body, "line_id")
    trial_series_id = v.req_id(body, "trial_series_id")
    decision = v.req_enum(body, "decision", v.DECISIONS)
    granted_plots = v.req_int(body, "granted_plots", minimum=0)
    expected_line_version = v.req_int(body, "expected_line_version", minimum=1)
    rationale = v.opt_str(body, "rationale")
    if decision != "ADVANCE" and granted_plots != 0:
        bad_request("granted_plots must be 0 unless the decision is ADVANCE.")

    line = lookup.line(line_id)
    series = lookup.series(trial_series_id)
    if expected_line_version != line["version"]:
        raise ApiError("ERR_STALE_LINE_VERSION",
                       "expected_line_version does not match the line's current version.")
    program = derive.program_of_line(line)
    lookup.program_open(program)
    lookup.line_not_discarded(line)
    if series["status"] != "ANALYZED":
        raise ApiError("ERR_SERIES_INVALID_STATE",
                       "An advancement decision must rest on an ANALYZED series.")

    from_stage = line["pipeline_stage"]
    to_stage = from_stage
    if decision == "ADVANCE":
        rung = ADVANCE_LADDER.get(from_stage)
        if rung is None:
            raise ApiError("ERR_SERIES_INVALID_STATE",
                           "The line has no further rung to advance to.")
        to_stage, required_series_stage = rung
        if series["stage"] != required_series_stage:
            raise ApiError("ERR_SERIES_INVALID_STATE",
                           "The cited series is at the wrong stage to carry this advance.")
        if to_stage == "COMMERCIAL":
            status = line["stewardship_status"]
            if status in ("NOT_REQUIRED", "PENDING"):
                raise ApiError("ERR_STEWARDSHIP_NOT_APPROVED",
                               "The commercial launch gate needs an APPROVED stewardship package.")
            if status == "SUSPENDED":
                raise ApiError("ERR_STEWARDSHIP_SUSPENDED",
                               "The line's stewardship package has been suspended.")
            if line["planned_launch_units_bags"] < 1:
                raise ApiError("ERR_STEWARDSHIP_NOT_APPROVED",
                               "The commercial launch gate needs a planned launch volume.")
    elif decision == "DISCARD":
        # PRD 3.8: "First the line itself: `pipeline_stage` becomes `DISCARDED`",
        # and `to_stage` records the line's "stage immediately after" the decision.
        to_stage = "DISCARDED"

    has_data = any(e for e in derive.entries_of_series(series["id"])
                   if e["line_id"] == line["id"] and e["status"] == "HARVESTED")
    if not has_data:
        raise ApiError("ERR_NO_TRIAL_DATA",
                       "The line has no HARVESTED entry in the cited series.")

    index_value = derive.cumulative_index_for(line, series["id"])
    objective = store.objectives.get(line["objective_id"])
    if decision == "ADVANCE":
        if from_stage == "NURSERY" and line["advancement_readiness"] != "READY":
            raise ApiError("ERR_LINE_NOT_READY",
                           "The line is not yet READY to leave the nursery.")
        if (objective is not None and index_value is not None
                and index_value < calc.dec(objective["min_advancement_index"])):
            raise ApiError("ERR_INDEX_BELOW_THRESHOLD",
                           "The cumulative advancement index is below the objective's bar.")
        if granted_plots > program["plot_budget_remaining"]:
            raise ApiError("ERR_PROGRAM_PLOT_BUDGET_EXCEEDED",
                           "granted_plots exceeds the programme's remaining plot budget.")

    rec = store.new_record()
    rec.update({
        "line_id": line["id"],
        "trial_series_id": series["id"],
        "decision": decision,
        "granted_plots": granted_plots,
        "decision_index_value": index_value,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "rationale": rationale,
        "is_superseded": False,
        "decided_by_user_id": auth.user_id(),
    })

    for earlier in derive.decisions_of_line(line["id"]):
        if earlier["trial_series_id"] == series["id"] and not earlier["is_superseded"]:
            mut.force(earlier)
            earlier["is_superseded"] = True
    store.decisions[rec["id"]] = rec

    mut.force(line)
    if decision == "ADVANCE":
        line["pipeline_stage"] = to_stage
        line["advancement_readiness"] = "NOT_READY"
    elif decision == "DISCARD":
        derive.discard_cascade(line, program)
    derive.recompute_program(program)
    mut.commit()
    return respond(rec, 201)


@bp.get("/advancement-decisions/<did>")
def read_decision(did):
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst")
    decision = lookup.decision(did)
    line = store.lines.get(decision["line_id"])
    auth.scope(line["program_id"] if line else None)
    return respond(decision)


@bp.get("/advancement-decisions")
def list_decisions():
    auth.authorize("PipelineDirector", "ProgramLead", "DataAnalyst")
    limit, offset = v.pagination()
    line_id = v.query_str("line_id")
    series_id = v.query_str("trial_series_id")
    decision = v.query_enum("decision", v.DECISIONS)
    is_superseded = v.query_bool("is_superseded")
    rows = store.ordered(store.decisions)
    if line_id is not None:
        rows = [r for r in rows if r["line_id"] == line_id]
    if series_id is not None:
        rows = [r for r in rows if r["trial_series_id"] == series_id]
    if decision is not None:
        rows = [r for r in rows if r["decision"] == decision]
    if is_superseded is not None:
        rows = [r for r in rows if r["is_superseded"] == is_superseded]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


# ===========================================================================
# StewardshipAgreement
# ===========================================================================
@bp.post("/breeding-lines/<lid>/stewardship-agreements")
def draft_agreement(lid):
    auth.authorize("RegulatoryOfficer")
    body = v.json_body()
    approved_markets = v.req_str_array(body, "approved_markets", min_items=1)
    dossier = v.req_str(body, "regulatory_dossier_ref")
    grower_ref = v.req_str(body, "grower_agreement_ref")
    effective_from = v.req_date(body, "effective_from")
    effective_to = v.req_date(body, "effective_to")

    line = lookup.line(lid)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    lookup.line_not_discarded(line)
    if effective_from < store.clock_date() or not effective_to > effective_from:
        raise ApiError("ERR_AGREEMENT_DATES_INVALID",
                       "effective_from must not be in the past and effective_to must follow it.")
    for existing in derive.agreements_of_line(line["id"]):
        if existing["status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"):
            raise ApiError("ERR_AGREEMENT_ALREADY_ACTIVE",
                           "The line already holds a live stewardship agreement.")

    rec = store.new_record()
    rec.update({
        "line_id": line["id"],
        "approved_markets": approved_markets,
        "regulatory_dossier_ref": dossier,
        "grower_agreement_ref": grower_ref,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "revision_round": 0,
        "requested_changes": None,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "suspension_reason": None,
        "status": "DRAFT",
    })
    store.agreements[rec["id"]] = rec
    mut.force(line)
    line["stewardship_status"] = "PENDING"
    mut.commit()
    return respond(rec, 201)


@bp.get("/breeding-lines/<lid>/stewardship-agreements")
def list_agreements(lid):
    auth.authorize("PipelineDirector", "RegulatoryOfficer", "ProgramLead", "SupplyPlanner",
                   "DataAnalyst")
    limit, offset = v.pagination()
    status = v.query_enum("status", AGREEMENT_STATUSES)
    line = lookup.line(lid)
    auth.scope(line["program_id"])
    rows = derive.agreements_of_line(line["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


@bp.get("/stewardship-agreements/<aid>")
def read_agreement(aid):
    auth.authorize("PipelineDirector", "RegulatoryOfficer", "ProgramLead", "SupplyPlanner",
                   "DataAnalyst")
    agreement = lookup.agreement(aid)
    line = derive.line_of_agreement(agreement)
    auth.scope(line["program_id"] if line else None)
    return respond(agreement)


@bp.post("/stewardship-agreements/<aid>/submit")
def submit_agreement(aid):
    auth.authorize("RegulatoryOfficer")
    agreement = lookup.agreement(aid)
    line = derive.line_of_agreement(agreement)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if agreement["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "Only a DRAFT or CHANGES_REQUESTED agreement may be submitted.")
    lookup.line_not_discarded(line)

    mut.force(agreement)
    if agreement["status"] == "CHANGES_REQUESTED":
        agreement["revision_round"] = agreement["revision_round"] + 1
    agreement["status"] = "SUBMITTED"
    agreement["requested_changes"] = None
    agreement["submitted_by_user_id"] = auth.user_id()
    mut.commit()
    return respond(agreement)


@bp.post("/stewardship-agreements/<aid>/review")
def review_agreement(aid):
    auth.authorize("RegulatoryOfficer", "PipelineDirector")
    body = v.json_body()
    outcome = v.req_enum(body, "outcome", v.REVIEW_OUTCOMES)
    requested_changes = v.opt_str(body, "requested_changes")
    if outcome == "REQUEST_CHANGES" and (requested_changes is None
                                         or len(requested_changes.strip()) == 0):
        bad_request("requested_changes must be a non-empty string for a REQUEST_CHANGES outcome.")

    agreement = lookup.agreement(aid)
    line = derive.line_of_agreement(agreement)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if agreement["status"] != "SUBMITTED":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "Only a SUBMITTED agreement may be reviewed.")

    mut.force(agreement)
    if outcome == "APPROVE":
        agreement["status"] = "APPROVED"
        agreement["approved_by_user_id"] = auth.user_id()
        mut.force(line)
        line["stewardship_status"] = "APPROVED"
    else:
        agreement["status"] = "CHANGES_REQUESTED"
        agreement["requested_changes"] = requested_changes
    mut.commit()
    return respond(agreement)


@bp.post("/stewardship-agreements/<aid>/suspend")
def suspend_agreement(aid):
    auth.authorize("RegulatoryOfficer", "PipelineDirector")
    body = v.json_body()
    reason = v.req_str(body, "suspension_reason")

    agreement = lookup.agreement(aid)
    line = derive.line_of_agreement(agreement)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if agreement["status"] != "APPROVED":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE",
                       "Only an APPROVED agreement may be suspended.")
    if auth.user_id() == agreement.get("approved_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver of an agreement may not suspend it.")

    mut.force(agreement)
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = reason
    derive.suspension_cascade(agreement, line, program)
    mut.commit()
    return respond(agreement)


# ===========================================================================
# SeedIncreaseLot
# ===========================================================================
def _stewardship_gate(line):
    """Ladder steps 19 and 20."""
    status = line["stewardship_status"]
    if status in ("NOT_REQUIRED", "PENDING"):
        raise ApiError("ERR_STEWARDSHIP_NOT_APPROVED",
                       "The line has no APPROVED stewardship agreement.")
    if status == "SUSPENDED":
        raise ApiError("ERR_STEWARDSHIP_SUSPENDED",
                       "The line's stewardship package has been suspended.")


def _approved_agreement(line):
    for agreement in derive.agreements_of_line(line["id"]):
        if agreement["status"] == "APPROVED":
            return agreement
    return None


@bp.post("/seed-increase-lots")
def reserve_lot():
    auth.authorize("SupplyPlanner")
    body = v.json_body()
    line_id = v.req_id(body, "line_id")
    target_market = v.req_str(body, "target_market")
    allocations = v.req_market_allocations(body, "market_allocations")
    launch_year = v.req_int(body, "launch_year", minimum=1)

    line = lookup.line(line_id)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    lookup.line_not_discarded(line)
    _stewardship_gate(line)
    agreement = _approved_agreement(line)
    if agreement is None or target_market not in agreement["approved_markets"]:
        raise ApiError("ERR_MARKET_NOT_IN_AGREEMENT",
                       "target_market does not appear in the line's approved markets.")

    planned_units_bags, allocated_seed_g = calc.volume_plan(
        [a["demand_kg"] for a in allocations])
    if allocated_seed_g > line["seed_inventory_g"]:
        raise ApiError("ERR_INSUFFICIENT_SEED_INVENTORY",
                       "The lot needs more parent seed than the line has on hand.")

    rec = store.new_record()
    rec.update({
        "line_id": line["id"],
        "target_market": target_market,
        "market_allocations": [dict(a) for a in allocations],
        "launch_year": launch_year,
        "planned_units_bags": planned_units_bags,
        "allocated_seed_g": allocated_seed_g,
        "hold_reason": None,
        "status": "RESERVED",
    })
    store.lots[rec["id"]] = rec

    mut.force(line)
    line["seed_inventory_g"] = line["seed_inventory_g"] - allocated_seed_g
    derive.recompute_line_ledger(line)
    derive.recompute_program(program)
    mut.commit()
    return respond(rec, 201)


@bp.get("/seed-increase-lots/<lot_id>")
def read_lot(lot_id):
    auth.authorize("PipelineDirector", "SupplyPlanner", "ProgramLead", "DataAnalyst")
    lot = lookup.lot(lot_id)
    line = derive.line_of_lot(lot)
    auth.scope(line["program_id"] if line else None)
    return respond(lot)


@bp.get("/breeding-lines/<lid>/seed-increase-lots")
def list_lots(lid):
    auth.authorize("PipelineDirector", "SupplyPlanner", "ProgramLead", "DataAnalyst")
    limit, offset = v.pagination()
    status = v.query_enum("status", LOT_STATUSES)
    launch_year = v.query_int("launch_year")
    line = lookup.line(lid)
    auth.scope(line["program_id"])
    rows = derive.lots_of_line(line["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if launch_year is not None:
        rows = [r for r in rows if r["launch_year"] == launch_year]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


@bp.post("/seed-increase-lots/<lot_id>/start-production")
def start_production(lot_id):
    auth.authorize("SupplyPlanner")
    lot = lookup.lot(lot_id)
    line = derive.line_of_lot(lot)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if lot["status"] != "RESERVED":
        raise ApiError("ERR_LOT_INVALID_STATE", "Only a RESERVED lot may start production.")
    _stewardship_gate(line)

    mut.force(lot)
    lot["status"] = "IN_PRODUCTION"
    derive.recompute_line_ledger(line)
    derive.recompute_program(program)
    mut.commit()
    return respond(lot)


@bp.post("/seed-increase-lots/<lot_id>/complete")
def complete_lot(lot_id):
    auth.authorize("SupplyPlanner")
    lot = lookup.lot(lot_id)
    line = derive.line_of_lot(lot)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if lot["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_LOT_INVALID_STATE", "Only an IN_PRODUCTION lot may be completed.")

    mut.force(lot)
    lot["status"] = "COMPLETED"
    produced = lot["allocated_seed_g"] * calc.FIELD_MULTIPLICATION_FACTOR
    mut.force(line)
    line["seed_inventory_g"] = line["seed_inventory_g"] + produced
    line["cumulative_seed_produced_g"] = line["cumulative_seed_produced_g"] + produced
    derive.recompute_line_ledger(line)
    derive.recompute_program(program)
    mut.commit()
    return respond(lot)


@bp.post("/seed-increase-lots/<lot_id>/cancel")
def cancel_lot(lot_id):
    auth.authorize("SupplyPlanner")
    body = v.json_body()
    hold_reason = v.opt_str(body, "hold_reason")

    lot = lookup.lot(lot_id)
    line = derive.line_of_lot(lot)
    program = derive.program_of_line(line)
    lookup.program_open(program)
    if lot["status"] not in ("RESERVED", "IN_PRODUCTION", "ON_HOLD"):
        raise ApiError("ERR_LOT_INVALID_STATE",
                       "Only a RESERVED, IN_PRODUCTION or ON_HOLD lot may be cancelled.")

    mut.force(lot)
    lot["status"] = "CANCELLED"
    if hold_reason is not None:
        lot["hold_reason"] = hold_reason
    mut.force(line)
    line["seed_inventory_g"] = line["seed_inventory_g"] + lot["allocated_seed_g"]
    derive.recompute_line_ledger(line)
    derive.recompute_program(program)
    mut.commit()
    return respond(lot)
