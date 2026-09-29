"""Drops, the page-space ledger, postal presort, mailing and delivery."""

from flask import Blueprint

import validate as v
from db import db, new_row, now, touch
from errors import ApiError
from middleware import ALL_ROLES, CIRCULATION_PLANNER, NO_BROKER, auth
from response import entity_response, list_response
from services import calc, domain
from routes.plans import find_plan, require_editable

bp = Blueprint("drops", __name__)

PRODUCTION_STATUSES = ("PLANNED", "PRESORTED", "MAILED", "DELIVERED", "CANCELLED")
MEASUREMENT_STATUSES = ("PENDING", "MATCHBACK_OPEN", "MATCHBACK_CLOSED")
PLACEMENT_POSITIONS = ("FRONT_COVER", "HOT_SPOT", "INSIDE", "BACK_COVER")
DECLARED_TIERS = ("FIVE_DIGIT", "THREE_DIGIT", "AADC", "MIXED_AADC")
CHANNELS = ("MAIL", "EMAIL", "DIGITAL")


def find_drop(drop_id):
    drop = db.drops.get(drop_id)
    if drop is None:
        raise ApiError("ERR_DROP_NOT_FOUND")
    return drop


def find_placement(placement_id):
    placement = db.placements.get(placement_id)
    if placement is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND")
    return placement


def require_planned(drop):
    if drop["production_status"] != "PLANNED":
        raise ApiError("ERR_INVALID_DROP_STATE")


@bp.post("/circulation-plans/<plan_id>/drops")
def create_drop(plan_id):
    auth(CIRCULATION_PLANNER)
    plan = find_plan(plan_id)
    body = v.json_body()

    # Ladder step 5 — schema.
    drop_number = v.get_int(body, "drop_number", minimum=1, maximum=99)
    in_home_date = v.get_dt(body, "in_home_date")
    page_count = v.get_int(body, "page_count", minimum=8, maximum=240)
    if page_count % 2 != 0:
        v.invalid("Field 'page_count' must be an even number of pages.")

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 16 — in-home date not in the past.
    if in_home_date < now():
        raise ApiError("ERR_INHOME_DATE_IN_PAST")

    # Ladder step 18 — drop number unique within the plan.
    for existing in domain.drops_of_plan(plan["id"]):
        if existing["drop_number"] == drop_number:
            raise ApiError("ERR_DUPLICATE_DROP_NUMBER")

    season = domain.season_of_plan(plan)
    capacity = calc.square_inch_capacity(page_count, season["usable_sq_in_per_page"])
    row = new_row()
    row.update(
        {
            "circulation_plan_id": plan["id"],
            "drop_number": drop_number,
            "in_home_date": in_home_date,
            "page_count": page_count,
            "weight_oz_milli": calc.weight_oz_milli(
                page_count, season["paper_oz_per_page_milli"]
            ),
            "square_inch_capacity": capacity,
            "allocated_square_inches": 0,
            "unallocated_square_inches": capacity,
            "requested_quantity_total": 0,
            "planned_quantity": 0,
            "print_rebate_bps": 0,
            "printing_cents_per_book": 0,
            "paper_cents_per_book": 0,
            "postage_cents_per_book": 0,
            "cost_per_book_cents": 0,
            "provisional_cost_per_book_cents": 0,
            "postage_total_cents": 0,
            "automation_share_bps": 0,
            "automation_qualified": False,
            "cost_basis": "ESTIMATED_POSTAGE",
            "production_status": "PLANNED",
            "measurement_status": "PENDING",
            "mailed_at": None,
        }
    )
    db.drops[row["id"]] = row
    return entity_response(row, 201)


@bp.patch("/drops/<drop_id>")
def amend_drop(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    body = v.json_body()

    # Ladder step 5 — schema.
    new_in_home = None
    if "in_home_date" in body:
        new_in_home = v.get_dt(body, "in_home_date")
    new_page_count = None
    if "page_count" in body:
        new_page_count = v.get_int(body, "page_count", minimum=8, maximum=240)
        if new_page_count % 2 != 0:
            v.invalid("Field 'page_count' must be an even number of pages.")

    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 9 — the drop must still be PLANNED.
    require_planned(drop)

    # Ladder step 16 — in-home date not in the past.
    if new_in_home is not None and new_in_home < now():
        raise ApiError("ERR_INHOME_DATE_IN_PAST")

    season = domain.season_of_drop(drop)

    # Ladder step 23 — a page-count reduction may not strand committed space.
    if new_page_count is not None:
        capacity = calc.square_inch_capacity(
            new_page_count, season["usable_sq_in_per_page"]
        )
        if capacity < drop["allocated_square_inches"]:
            raise ApiError("ERR_DROP_SQ_IN_CAPACITY_EXCEEDED")
        occupied = [p["page_number"] for p in domain.placements_of_drop(drop["id"])]
        if occupied and new_page_count < max(occupied):
            raise ApiError("ERR_DROP_SQ_IN_CAPACITY_EXCEEDED")

    if new_in_home is not None:
        drop["in_home_date"] = new_in_home
    if new_page_count is not None:
        drop["page_count"] = new_page_count
        drop["weight_oz_milli"] = calc.weight_oz_milli(
            new_page_count, season["paper_oz_per_page_milli"]
        )
        drop["square_inch_capacity"] = calc.square_inch_capacity(
            new_page_count, season["usable_sq_in_per_page"]
        )
        domain.recompute_drop_space(drop)
        domain.recompute_drop_cost(drop)

    domain.plan_structural_recompute(plan)
    touch(drop)
    return entity_response(drop)


@bp.get("/drops/<drop_id>")
def read_drop(drop_id):
    auth(*ALL_ROLES)
    return entity_response(find_drop(drop_id))


@bp.get("/circulation-plans/<plan_id>/drops")
def list_plan_drops(plan_id):
    auth(*ALL_ROLES)
    plan = find_plan(plan_id)
    limit, offset = v.pagination()
    production = v.filter_enum("production_status", PRODUCTION_STATUSES)
    measurement = v.filter_enum("measurement_status", MEASUREMENT_STATUSES)
    matching = [
        d for d in db.drops.values() if d["circulation_plan_id"] == plan["id"]
    ]
    if production is not None:
        matching = [d for d in matching if d["production_status"] == production]
    if measurement is not None:
        matching = [d for d in matching if d["measurement_status"] == measurement]
    matching.sort(key=lambda d: (d["drop_number"], d["created_at"], d["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# 3.4  Page placements and the square-inch ledger
# ---------------------------------------------------------------------------


@bp.post("/drops/<drop_id>/page-placements")
def create_placement(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    body = v.json_body()

    # Ladder step 5 — schema.  page_number's range is a step-22 concern.
    product_sku = v.get_str(body, "product_sku", min_len=1)
    product_name = v.get_str(body, "product_name", min_len=1)
    unit_price_cents = v.get_int(body, "unit_price_cents", minimum=0)
    unit_cogs_cents = v.get_int(body, "unit_cogs_cents", minimum=0)
    demand_per_sq_inch_cents = v.get_int(body, "demand_per_sq_inch_cents", minimum=0)
    page_number = v.get_int(body, "page_number")
    sq_in_offset = v.get_int(body, "sq_in_offset", minimum=0)
    square_inches = v.get_int(body, "square_inches", minimum=1)
    position = v.get_enum(body, "placement_position", PLACEMENT_POSITIONS)

    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 9 — the drop must still be PLANNED.
    require_planned(drop)

    existing_placements = domain.placements_of_drop(drop["id"])

    # Ladder step 19 — SKU unique within the drop.
    for other in existing_placements:
        if other["product_sku"] == product_sku:
            raise ApiError("ERR_DUPLICATE_PLACEMENT_SKU")

    # Ladder step 21 — half-open intervals on the same page may not overlap.
    start = sq_in_offset
    end = sq_in_offset + square_inches
    for other in existing_placements:
        if other["page_number"] != page_number:
            continue
        other_start = other["sq_in_offset"]
        other_end = other_start + other["square_inches"]
        if start < other_end and other_start < end:
            raise ApiError("ERR_PAGE_SPACE_OVERLAP")

    season = domain.season_of_drop(drop)

    # Ladder step 22 — the placement must fit inside one page of the book.
    if end > season["usable_sq_in_per_page"]:
        raise ApiError("ERR_PAGE_CAPACITY_EXCEEDED")
    if page_number < 1 or page_number > drop["page_count"]:
        raise ApiError("ERR_PAGE_CAPACITY_EXCEEDED")

    # Ladder step 23 — the drop's square-inch capacity is conserved.
    if drop["allocated_square_inches"] + square_inches > drop["square_inch_capacity"]:
        raise ApiError("ERR_DROP_SQ_IN_CAPACITY_EXCEEDED")

    multiplier = calc.POSITION_MULTIPLIER_BPS[position]
    forecast = calc.forecast_space_demand_cents(
        square_inches, demand_per_sq_inch_cents, multiplier
    )
    row = new_row()
    row.update(
        {
            "drop_id": drop["id"],
            "product_sku": product_sku,
            "product_name": product_name,
            "unit_price_cents": unit_price_cents,
            "unit_cogs_cents": unit_cogs_cents,
            "demand_per_sq_inch_cents": demand_per_sq_inch_cents,
            "page_number": page_number,
            "sq_in_offset": sq_in_offset,
            "square_inches": square_inches,
            "placement_position": position,
            "position_multiplier_bps": multiplier,
            "forecast_space_demand_cents": forecast,
            "space_productivity_cents_per_sq_in": calc.space_productivity_cents_per_sq_in(
                forecast, square_inches
            ),
        }
    )
    db.placements[row["id"]] = row
    domain.recompute_drop_space(drop)
    touch(drop)
    return entity_response(row, 201)


@bp.get("/drops/<drop_id>/page-placements")
def list_placements(drop_id):
    auth(*NO_BROKER)
    drop = find_drop(drop_id)
    limit, offset = v.pagination()
    page_number = v.filter_int("page_number")
    matching = [p for p in db.placements.values() if p["drop_id"] == drop["id"]]
    if page_number is not None:
        matching = [p for p in matching if p["page_number"] == page_number]
    matching.sort(
        key=lambda p: (p["page_number"], p["sq_in_offset"], p["created_at"], p["_seq"])
    )
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.delete("/page-placements/<placement_id>")
def delete_placement(placement_id):
    auth(CIRCULATION_PLANNER)
    placement = find_placement(placement_id)
    drop = db.drops[placement["drop_id"]]
    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 9 — the drop must still be PLANNED.
    require_planned(drop)

    del db.placements[placement["id"]]
    domain.recompute_drop_space(drop)
    touch(drop)
    # The reconciled parent drop is returned deliberately, not the deleted row.
    return entity_response(drop)


# ---------------------------------------------------------------------------
# 3.7  Postal presort, mailing and delivery
# ---------------------------------------------------------------------------


@bp.post("/drops/<drop_id>/presort-batches")
def create_presort_batch(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    body = v.json_body()

    # Ladder step 5 — schema.
    declared_tier = v.get_enum(body, "declared_tier", DECLARED_TIERS)
    piece_count = v.get_int(body, "piece_count", minimum=1)

    plan = domain.plan_of_drop(drop)

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    effective_tier = calc.effective_tier(declared_tier, piece_count)
    rate = calc.TIER_RATE_CENTS_PER_PIECE[effective_tier]
    surcharge = calc.weight_surcharge_cents_per_piece(drop["weight_oz_milli"])

    # An immutable audit row: no version and no update path.
    row = new_row(with_version=False)
    row.update(
        {
            "drop_id": drop["id"],
            "declared_tier": declared_tier,
            "piece_count": piece_count,
            "effective_tier": effective_tier,
            "rate_cents_per_piece": rate,
            "weight_surcharge_cents_per_piece": surcharge,
            "batch_postage_cents": piece_count * (rate + surcharge),
            "is_automation_qualified": effective_tier in calc.AUTOMATION_TIERS,
        }
    )
    db.batches[row["id"]] = row
    return entity_response(row, 201)


@bp.get("/drops/<drop_id>/presort-batches")
def list_presort_batches(drop_id):
    auth(*NO_BROKER)
    drop = find_drop(drop_id)
    limit, offset = v.pagination()
    declared_tier = v.filter_enum("declared_tier", DECLARED_TIERS)
    effective_tier = v.filter_enum("effective_tier", DECLARED_TIERS)
    matching = [b for b in db.batches.values() if b["drop_id"] == drop["id"]]
    if declared_tier is not None:
        matching = [b for b in matching if b["declared_tier"] == declared_tier]
    if effective_tier is not None:
        matching = [b for b in matching if b["effective_tier"] == effective_tier]
    matching.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/drops/<drop_id>/presort")
def presort_drop(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    v.json_body()
    plan = domain.plan_of_drop(drop)

    # Ladder step 9 — presort is gated on the director's signature first.
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    require_planned(drop)
    if drop["planned_quantity"] <= 0:
        raise ApiError("ERR_INVALID_DROP_STATE")

    batches = domain.batches_of_drop(drop["id"])

    # Ladder step 26 — the mail stream must cover the mailing exactly.
    if sum(b["piece_count"] for b in batches) != drop["planned_quantity"]:
        raise ApiError("ERR_PRESORT_COVERAGE_MISMATCH")

    batch_postage = sum(b["batch_postage_cents"] for b in batches)
    automation_pieces = sum(
        b["piece_count"] for b in batches if b["effective_tier"] in calc.AUTOMATION_TIERS
    )
    share = calc.automation_share_bps(automation_pieces, drop["planned_quantity"])
    qualified = share >= 9000
    discount = 2 * automation_pieces if qualified else 0

    drop["automation_share_bps"] = share
    drop["automation_qualified"] = qualified
    drop["postage_total_cents"] = batch_postage - discount
    domain.recompute_drop_cost(drop, variant="PRESORTED_ACTUAL")
    domain.recompute_allocated_lines_of_drop(drop)
    # The plan's roll-up moves but its status deliberately does not.
    domain.recompute_plan_rollup(plan)
    drop["production_status"] = "PRESORTED"
    touch(drop)
    return entity_response(drop)


@bp.post("/drops/<drop_id>/mail")
def mail_drop(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    v.json_body()

    # Ladder step 9 — PRESORTED -> MAILED, and only once in home.
    if drop["production_status"] != "PRESORTED":
        raise ApiError("ERR_INVALID_DROP_STATE")
    if drop["in_home_date"] > now():
        raise ApiError("ERR_INVALID_DROP_STATE")

    drop["production_status"] = "MAILED"
    drop["mailed_at"] = now()
    # Five hops, each caused by the hop before it rather than by this action.
    domain.run_mail_cascade(drop)
    touch(drop)
    return entity_response(drop)


@bp.post("/drops/<drop_id>/deliver")
def deliver_drop(drop_id):
    auth(CIRCULATION_PLANNER)
    drop = find_drop(drop_id)
    v.json_body()
    if drop["production_status"] != "MAILED":
        raise ApiError("ERR_INVALID_DROP_STATE")
    # The measurement dimension is deliberately untouched.
    drop["production_status"] = "DELIVERED"
    touch(drop)
    return entity_response(drop)


@bp.get("/drops/<drop_id>/contact-events")
def list_drop_contact_events(drop_id):
    auth(*NO_BROKER)
    drop = find_drop(drop_id)
    limit, offset = v.pagination()
    channel = v.filter_enum("channel", CHANNELS)
    matching = [e for e in db.contact_events.values() if e["drop_id"] == drop["id"]]
    if channel is not None:
        matching = [e for e in matching if e["channel"] == channel]
    matching.sort(key=lambda e: (e["contact_date"], e["created_at"], e["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)
