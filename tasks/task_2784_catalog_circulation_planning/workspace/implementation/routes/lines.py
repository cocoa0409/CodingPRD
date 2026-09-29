"""Circulation lines, the allocation waterfall and line retirement."""

from flask import Blueprint

import validate as v
from db import db, new_row, touch
from errors import ApiError
from middleware import ALL_ROLES, CIRCULATION_PLANNER, auth
from response import entity_response, list_response
from services import domain
from util import whole_days
from routes.drops import find_drop, require_planned
from routes.plans import require_editable

bp = Blueprint("lines", __name__)

AUDIENCE_TYPES = ("HOUSEFILE", "RENTAL")
LINE_STATUSES = ("PROPOSED", "ALLOCATED", "VOIDED", "SUPPRESSED")


def find_line(line_id):
    line = db.lines.get(line_id)
    if line is None:
        raise ApiError("ERR_LINE_NOT_FOUND")
    return line


def _gap_days(first, second):
    """Symmetric whole-day distance between two in-home dates."""
    if first <= second:
        return whole_days(first, second)
    return whole_days(second, first)


@bp.post("/drops/<drop_id>/circulation-lines")
def create_line(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    body = v.json_body()

    # Ladder step 4 — body foreign keys resolve.
    raw_segment = body.get("housefile_segment_id")
    if isinstance(raw_segment, str) and raw_segment.strip() != "":
        if raw_segment not in db.segments:
            raise ApiError("ERR_SEGMENT_NOT_FOUND")
    raw_rental = body.get("prospect_list_rental_id")
    if isinstance(raw_rental, str) and raw_rental.strip() != "":
        if raw_rental not in db.rentals:
            raise ApiError("ERR_RENTAL_NOT_FOUND")

    # Ladder step 5 — schema.
    audience_type = v.get_enum(body, "audience_type", AUDIENCE_TYPES)
    requested_quantity = v.get_int(body, "requested_quantity", minimum=1)
    segment_id = v.get_id(body, "housefile_segment_id", required=False)
    rental_id = v.get_id(body, "prospect_list_rental_id", required=False)
    is_holdout = v.get_bool(body, "is_holdout", default=False)
    holdout_pct_bps = v.get_int(
        body, "holdout_pct_bps", required=False, default=0, minimum=0, maximum=5000
    )
    if holdout_pct_bps != 0 and not is_holdout:
        v.invalid("Field 'holdout_pct_bps' must be 0 when 'is_holdout' is false.")

    # Ladder step 6 — audience specification coherent.
    if segment_id is not None and rental_id is not None:
        raise ApiError("ERR_AUDIENCE_SPEC_INVALID")
    if segment_id is None and rental_id is None:
        raise ApiError("ERR_AUDIENCE_SPEC_INVALID")
    if audience_type == "HOUSEFILE" and segment_id is None:
        raise ApiError("ERR_AUDIENCE_SPEC_INVALID")
    if audience_type == "RENTAL" and rental_id is None:
        raise ApiError("ERR_AUDIENCE_SPEC_INVALID")

    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 9 — the drop must still be PLANNED.
    require_planned(drop)

    season = domain.season_of_drop(drop)

    # Ladder step 12 — a suppression-only segment gets no circulation at all.
    if segment_id is not None:
        segment = db.segments[segment_id]
        if segment["contact_strategy"] == "SUPPRESS_ONLY":
            raise ApiError("ERR_SEGMENT_SUPPRESSED")

    # Ladder step 17 — in-home spacing buffer, symmetric in both directions.
    if segment_id is not None:
        gap = season["min_inhome_gap_days"]
        for other in domain.live_lines_for_segment(segment_id):
            other_drop = db.drops[other["drop_id"]]
            if other_drop["id"] == drop["id"]:
                continue
            if other_drop["production_status"] == "CANCELLED":
                continue
            if _gap_days(drop["in_home_date"], other_drop["in_home_date"]) < gap:
                raise ApiError("ERR_INHOME_SPACING_VIOLATION")

    # Ladder step 20 — no second live line for the same audience on this drop.
    for other in domain.lines_of_drop(drop["id"]):
        if other["status"] not in domain.LIVE_LINE_STATUSES:
            continue
        if segment_id is not None and other["housefile_segment_id"] == segment_id:
            raise ApiError("ERR_DUPLICATE_AUDIENCE_LINE")
        if rental_id is not None and other["prospect_list_rental_id"] == rental_id:
            raise ApiError("ERR_DUPLICATE_AUDIENCE_LINE")

    row = new_row()
    row.update(
        {
            "drop_id": drop["id"],
            "audience_type": audience_type,
            "housefile_segment_id": segment_id,
            "prospect_list_rental_id": rental_id,
            "requested_quantity": requested_quantity,
            "is_holdout": is_holdout,
            "holdout_pct_bps": holdout_pct_bps,
            "status": "PROPOSED",
            "allocation_rank": 0,
            "effective_response_bps": 0,
            "gross_forecast_demand_cents": 0,
            "allocated_quantity": 0,
            "holdout_quantity": 0,
            "mailable_quantity": 0,
            "unit_cost_cents": 0,
            "committed_cost_cents": 0,
            "forecast_demand_cents": 0,
            "gross_margin_cents": 0,
            "circulation_cost_cents": 0,
            "contribution_cents": 0,
        }
    )
    db.lines[row["id"]] = row
    # The planning view: the universe the planner asked for, pre-merge-purge.
    domain.recompute_line_gross_forecast(row, season)
    domain.recompute_drop_quantities(drop)
    domain.plan_structural_recompute(plan)
    return entity_response(row, 201)


@bp.get("/circulation-lines/<line_id>")
def read_line(line_id):
    auth(*ALL_ROLES)
    return entity_response(find_line(line_id))


@bp.get("/circulation-lines")
def list_lines():
    auth(*ALL_ROLES)
    limit, offset = v.pagination()
    drop_id = v.filter_str("drop_id")
    segment_id = v.filter_str("housefile_segment_id")
    rental_id = v.filter_str("prospect_list_rental_id")
    status = v.filter_enum("status", LINE_STATUSES)
    matching = list(db.lines.values())
    if drop_id is not None:
        matching = [l for l in matching if l["drop_id"] == drop_id]
    if segment_id is not None:
        matching = [l for l in matching if l["housefile_segment_id"] == segment_id]
    if rental_id is not None:
        matching = [l for l in matching if l["prospect_list_rental_id"] == rental_id]
    if status is not None:
        matching = [l for l in matching if l["status"] == status]
    # allocation_rank ascending with never-ranked lines last, then created_at.
    matching.sort(
        key=lambda l: (
            1 if l["allocation_rank"] == 0 else 0,
            l["allocation_rank"],
            l["created_at"],
            l["_seq"],
        )
    )
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# 3.5  The allocation waterfall
# ---------------------------------------------------------------------------


@bp.post("/drops/<drop_id>/allocate")
def allocate_drop(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    v.json_body()
    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 9 — the drop must still be PLANNED.
    require_planned(drop)

    proposed = [
        l for l in domain.lines_of_drop(drop["id"]) if l["status"] == "PROPOSED"
    ]

    # Ladder step 12 — no suppression-only segment may be funded.
    for line in proposed:
        if line["housefile_segment_id"] is None:
            continue
        if db.segments[line["housefile_segment_id"]]["contact_strategy"] == "SUPPRESS_ONLY":
            raise ApiError("ERR_SEGMENT_SUPPRESSED")

    # Ladder step 14 — every rental behind a line has been netted.
    for line in proposed:
        if line["prospect_list_rental_id"] is None:
            continue
        if db.rentals[line["prospect_list_rental_id"]]["status"] != "NETTED":
            raise ApiError("ERR_RENTAL_NOT_NETTED")

    # Ladder step 15 — the plan's mailable universe exists.
    if not domain.plan_has_completed_merge_purge(plan["id"]):
        raise ApiError("ERR_MERGE_PURGE_REQUIRED")

    season = domain.season_of_drop(drop)
    proposed.sort(key=domain.waterfall_priority_key)

    # The provisional price is struck off the requested universe, once, and is
    # never recomputed after allocation.
    if drop["provisional_cost_per_book_cents"] == 0:
        drop["provisional_cost_per_book_cents"] = domain.compute_provisional_cost(drop)
    provisional = drop["provisional_cost_per_book_cents"]

    # Ladder step 27 — the top-priority line must afford at least one book.
    if proposed:
        top_unit_cost = domain.line_unit_cost(proposed[0], provisional)
        if top_unit_cost > 0 and plan["uncommitted_budget_cents"] // top_unit_cost < 1:
            raise ApiError("ERR_PLAN_BUDGET_EXHAUSTED")

    walked = set(l["id"] for l in proposed)
    domain.run_allocation_waterfall(drop, plan, season, proposed, provisional)

    domain.recompute_drop_quantities(drop)
    domain.recompute_plan_budget(plan)
    domain.recompute_drop_cost(drop)

    # Every allocated line now gets its committed view of demand and its
    # profitability at the drop's freshly derived cost per book.
    for line in domain.lines_of_drop(drop["id"]):
        if line["status"] != "ALLOCATED":
            continue
        changed = domain.recompute_line_net_forecast(line, season)
        if domain.recompute_line_profitability(line, drop, season):
            changed = True
        if changed and line["id"] not in walked:
            touch(line)

    domain.plan_structural_recompute(plan)
    touch(drop)
    return entity_response(drop)


# ---------------------------------------------------------------------------
# 3.5  Line retirement
# ---------------------------------------------------------------------------


@bp.post("/circulation-lines/<line_id>/void")
def void_circulation_line(line_id):
    auth(CIRCULATION_PLANNER)
    line = find_line(line_id)
    body = v.json_body()
    v.get_optional_text(body, "reason")

    drop = domain.drop_of_line(line)
    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 9 — drop state first, then the line's own state.
    require_planned(drop)
    if line["status"] not in domain.LIVE_LINE_STATUSES:
        raise ApiError("ERR_INVALID_LINE_STATE")

    # Exact credit-back, never a recomputed approximation.
    domain.void_line(line, plan)
    domain.recompute_drop_quantities(drop)
    domain.recompute_drop_cost(drop)
    domain.recompute_allocated_lines_of_drop(drop)
    touch(drop)
    domain.plan_structural_recompute(plan)
    return entity_response(line)
