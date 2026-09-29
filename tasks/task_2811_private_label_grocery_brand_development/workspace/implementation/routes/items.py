"""Product items, their shipment feed, launch, rationalization and complaints."""
from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db, now
from domain import (
    GAP_COUNTERS,
    PROGRAM_COUNTERS,
    TERMINAL_DEV_STATUS,
    capture,
    claims_of_round,
    complaints_of_item,
    get_gap,
    get_item,
    guard_not_frozen,
    guard_program_open,
    maybe_auto_conditional,
    new_row,
    program_of_gap,
    program_of_item,
    recompute_item_trend,
    refresh_active_item_count,
    refresh_cached_composite,
    refresh_gap_slots,
    refresh_supplier_counters,
    release_money,
    runs_of_item,
    specifications_of_item,
    touch,
    touch_if_moved,
)
from errors import fail
from listing import (
    DEFECT_SET,
    DEV_STATUS_SET,
    POSTURE_SET,
    SEVERITY_SET,
    TIER_SET,
    no_query,
    paginate,
)
from middleware import (
    ALL_ROLES,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_QUALITY_AUDITOR,
    ROLE_REGULATORY_REVIEWER,
    ROLE_SOURCING_MANAGER,
    Field,
    authenticate,
    validate_body,
)
from response import object_response

bp = Blueprint("items", __name__)


def _refresh_supplier_chain(item):
    """The complaint chain: item posture -> supplier standing -> held runs."""
    if item["supplier_id"] is None:
        return
    supplier = db.suppliers.get(item["supplier_id"])
    if supplier is None:
        return
    before = capture(supplier, ("weighted_complaint_points", "probation_item_count", "composite_score_cached", "qualification_status"))
    refresh_supplier_counters(supplier)
    refresh_cached_composite(supplier)
    maybe_auto_conditional(supplier)
    touch_if_moved(supplier, before)


@bp.post("/private-label/items")
def create_item():
    authenticate((ROLE_PROGRAM_DIRECTOR, ROLE_SOURCING_MANAGER))
    body = validate_body(
        {
            "gap_id": Field("string", required=True),
            "item_name": Field("string", required=True),
            "tier": Field("string", required=True, enum=TIER_SET),
            "pack_size_desc": Field("string", required=True),
            "trailing_90d_units": Field(
                "integer", check=lambda v: v >= 0, detail="must not be negative"
            ),
        }
    )
    gap = get_gap(body["gap_id"])
    program = program_of_gap(gap)
    guard_program_open(program)
    guard_not_frozen(program)
    if gap["status"] != "TIER_APPROVED":
        fail("ERR_GAP_NOT_TIER_APPROVED")
    if body["tier"] != gap["approved_tier"]:
        fail("ERR_TIER_MISMATCH")
    if gap["slots_open"] <= 0:
        fail("ERR_SHELF_SLOT_QUOTA_EXCEEDED")
    units = body["trailing_90d_units"] if body["trailing_90d_units"] is not None else 0
    row = new_row(
        {
            "gap_id": gap["id"],
            "supplier_id": None,
            "replacement_item_id": None,
            "item_name": body["item_name"],
            "tier": body["tier"],
            "pack_size_desc": body["pack_size_desc"],
            "development_status": "CONCEPT",
            "quality_posture": "GREEN",
            "trailing_90d_units": units,
            "complaint_ppm_90d": calc.D("0.00"),
            "retail_price_cents": None,
            "spec_revision_count": 0,
        }
    )
    db.items[row["id"]] = row
    gap_before = capture(gap, GAP_COUNTERS)
    gap["slots_consumed_lifetime"] += 1
    refresh_gap_slots(gap)
    touch_if_moved(gap, gap_before)
    program_before = capture(program, PROGRAM_COUNTERS)
    refresh_active_item_count(program)
    touch_if_moved(program, program_before)
    return object_response(ser.item_out(row), 201)


@bp.get("/private-label/items/<item_id>")
def read_item(item_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.item_out(get_item(item_id)))


@bp.get("/private-label/items")
def list_items():
    authenticate(ALL_ROLES)
    return paginate(
        db.items,
        {
            "gap_id": "string",
            "supplier_id": "string",
            "replacement_item_id": "string",
            "development_status": DEV_STATUS_SET,
            "quality_posture": POSTURE_SET,
            "tier": TIER_SET,
        },
        ser.item_out,
    )


@bp.post("/private-label/items/<item_id>/shipment-feed")
def post_shipment_feed(item_id):
    authenticate((ROLE_SOURCING_MANAGER, ROLE_QUALITY_AUDITOR))
    body = validate_body(
        {
            "trailing_90d_units": Field(
                "integer", required=True, check=lambda v: v >= 0, detail="must not be negative"
            )
        }
    )
    item = get_item(item_id)
    guard_program_open(program_of_item(item))
    item["trailing_90d_units"] = body["trailing_90d_units"]
    points = 0
    for row in complaints_of_item(item["id"]):
        from db import days_before

        if days_before(90) <= row["received_at"] <= now():
            points += calc.SEVERITY_WEIGHTS[row["severity"]]
    ppm = calc.complaint_ppm(points, item["trailing_90d_units"])
    item["complaint_ppm_90d"] = ppm
    if item["quality_posture"] != "SUSPENDED" and item["development_status"] not in TERMINAL_DEV_STATUS:
        item["quality_posture"] = calc.posture_for_ppm(ppm)
    touch(item)
    _refresh_supplier_chain(item)
    return object_response(ser.item_out(item))


@bp.post("/private-label/items/<item_id>/launch")
def launch_item(item_id):
    authenticate((ROLE_PROGRAM_DIRECTOR,))
    validate_body({})
    item = get_item(item_id)
    guard_program_open(program_of_item(item))
    if item["development_status"] not in ("SPEC_LOCKED", "RELAUNCH_PENDING"):
        fail("ERR_ITEM_STATE_INVALID")
    if item["quality_posture"] == "SUSPENDED":
        fail("ERR_ITEM_QUALITY_SUSPENDED")
    if item["development_status"] == "SPEC_LOCKED":
        completed = [
            row
            for row in runs_of_item(item["id"])
            if row["run_type"] == "FIRST_PRODUCTION" and row["status"] == "COMPLETED"
        ]
        if not completed:
            fail("ERR_FIRST_PRODUCTION_INCOMPLETE")
    else:
        if not _relaunch_basis_rebuilt(item):
            fail("ERR_RELAUNCH_PRECONDITION_UNMET")
    item["development_status"] = "LAUNCHED"
    touch(item)
    return object_response(ser.item_out(item))


def _relaunch_basis_rebuilt(item):
    for spec in specifications_of_item(item["id"]):
        if spec["status"] != "LOCKED" or spec["revision_no"] != item["spec_revision_count"]:
            continue
        round_row = db.artwork_rounds.get(spec["pinned_artwork_round_id"])
        if round_row is None or round_row["nutrition_status"] != "VALID":
            continue
        blocked = [
            row
            for row in claims_of_round(round_row["id"])
            if row["status"] in ("PENDING", "RESCINDED")
        ]
        if blocked:
            continue
        return True
    return False


@bp.post("/private-label/items/<item_id>/rationalize")
def rationalize_item(item_id):
    authenticate((ROLE_PROGRAM_DIRECTOR,))
    body = validate_body(
        {
            "disposition": Field(
                "string", required=True, enum=frozenset(("REPLACE", "DISCONTINUE"))
            ),
            "replacement_item_id": Field("string"),
        }
    )
    item = get_item(item_id)
    replacement = (
        get_item(body["replacement_item_id"]) if body["replacement_item_id"] is not None else None
    )
    program = program_of_item(item)
    guard_program_open(program)
    if item["development_status"] not in ("LAUNCHED", "RELAUNCH_PENDING"):
        fail("ERR_ITEM_STATE_INVALID")
    if body["disposition"] == "REPLACE":
        if (
            replacement is None
            or replacement["id"] == item["id"]
            or replacement["gap_id"] != item["gap_id"]
            or replacement["development_status"] in TERMINAL_DEV_STATUS
        ):
            fail("ERR_REPLACEMENT_ITEM_INVALID")
        item["replacement_item_id"] = replacement["id"]
        item["development_status"] = "RATIONALIZED"
    else:
        if replacement is not None:
            fail("ERR_REPLACEMENT_ITEM_INVALID")
        item["development_status"] = "DISCONTINUED"
    touch(item)
    gap = get_gap(item["gap_id"])
    gap_before = capture(gap, GAP_COUNTERS)
    gap["slots_released_lifetime"] += 1
    refresh_gap_slots(gap)
    touch_if_moved(gap, gap_before)
    program_before = capture(program, PROGRAM_COUNTERS)
    for run in runs_of_item(item["id"]):
        if run["status"] in ("SCHEDULED", "APPROVED", "HOLD"):
            run["status"] = "CANCELLED"
            release_money(program, run["committed_tooling_cents"])
            touch(run)
    refresh_active_item_count(program)
    touch_if_moved(program, program_before)
    return object_response(ser.item_out(item))


@bp.post("/private-label/complaints")
def create_complaint():
    authenticate((ROLE_QUALITY_AUDITOR, ROLE_REGULATORY_REVIEWER))
    body = validate_body(
        {
            "item_id": Field("string", required=True),
            "defect_category": Field("string", required=True, enum=DEFECT_SET),
            "severity": Field("string", required=True, enum=SEVERITY_SET),
            "lot_code": Field("string", required=True),
            "narrative": Field("string", required=True),
        }
    )
    item = get_item(body["item_id"])
    guard_program_open(program_of_item(item))
    row = new_row(
        {
            "item_id": item["id"],
            "defect_category": body["defect_category"],
            "severity": body["severity"],
            "lot_code": body["lot_code"],
            "narrative": body["narrative"],
        },
        versioned=False,
    )
    row["received_at"] = row["created_at"]
    db.complaints[row["id"]] = row
    recompute_item_trend(item)
    _refresh_supplier_chain(item)
    return object_response(ser.complaint_out(row), 201)


@bp.get("/private-label/complaints/<complaint_id>")
def read_complaint(complaint_id):
    from domain import get_complaint

    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.complaint_out(get_complaint(complaint_id)))


@bp.get("/private-label/complaints")
def list_complaints():
    authenticate(ALL_ROLES)
    return paginate(
        db.complaints,
        {"item_id": "string", "severity": SEVERITY_SET, "defect_category": DEFECT_SET},
        ser.complaint_out,
    )
