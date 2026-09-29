"""Date-code lot, markdown, label and scan-price-check endpoints."""
from flask import Blueprint

import calc
import services
from db import db, newest_first
from errors import ApiError
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_CLERK, ROLE_MANAGER,
                        actor, authenticate, role)
from records import (department_of_item, item_by_id, item_of_lot,
                     labels_of_lot, ladder_of_department, label_by_id,
                     check_by_id, lot_by_id, new_record, touch)
from response import created, ok, public
from routes.common import (CHECK_OUTCOMES, ENFORCEMENT_ACTIONS, LABEL_REASONS,
                           LABEL_STATUSES, LOT_STATUSES, PRICING_VARIANTS,
                           listing, matches)
from util import (D, OVERCHARGE_ENFORCEMENT_CENTS, fmt_instant, num,
                  parse_instant)
from validate import (MISSING, field_date, field_enum, field_int, field_string,
                      json_body, query_bool, query_enum, query_string)

bp = Blueprint("lots", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR)
WITHDRAWABLE = ("FRESH", "MARKED_DOWN", "DONATION_PENDING")


def _blocked_guard(department):
    if department["compliance_status"] == "BLOCKED":
        raise ApiError(
            "ERR_DEPARTMENT_COMPLIANCE_BLOCKED",
            "The lot's department is BLOCKED by an escalated audit",
        )


# --- lots ------------------------------------------------------------------
@bp.get("/fresh/lots/<lot_id>")
def get_lot(lot_id):
    authenticate(*READ_ROLES)
    return ok(public(lot_by_id(lot_id)))


@bp.get("/fresh/lots")
def list_lots():
    authenticate(*READ_ROLES)
    item_id = query_string("item_id")
    status = query_enum("status", LOT_STATUSES)
    past_date = query_bool("past_date_flag")
    rows = [
        l for l in db.lots.values()
        if matches(l, "item_id", item_id)
        and matches(l, "status", status)
        and matches(l, "past_date_flag", past_date)
    ]
    return listing(rows)


@bp.post("/fresh/lots")
def create_lot():
    authenticate(ROLE_CLERK, ROLE_MANAGER, ROLE_ADMIN)
    body = json_body()
    item_id = field_string(body, "item_id", required=True, max_len=200)
    production_date = field_date(body, "production_date", required=True)
    quantity = field_int(body, "quantity_original", required=True, minimum=1)
    batch_code = field_string(body, "production_batch_code", default=None,
                              nullable=True, min_len=1, max_len=24)
    item = item_by_id(item_id)
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_ITEM_DISCONTINUED",
                       "This item is DISCONTINUED and accepts no new lots")
    department = department_of_item(item)
    shelf_life = calc.effective_shelf_life_days(item, department)
    sell_by = calc.sell_by_instant(production_date, shelf_life)
    lot = new_record(db.lots, {
        "item_id": item["id"],
        "production_date": production_date.isoformat(),
        "production_batch_code": batch_code,
        "sell_by_at": fmt_instant(sell_by),
        "quantity_original": quantity,
        "quantity_on_hand": quantity,
        "units_sold": 0,
        "units_shrunk": 0,
        "units_donated": 0,
        "revenue_cents": 0,
        "markdown_giveback_cents": 0,
        "current_price_cents": item["base_retail_cents"],
        "current_rung_index": -1,
        "total_discount_pct": 0,
        "expected_sell_through_pct": 0,
        "past_date_flag": False,
        "status": "FRESH",
    })
    services.refresh_expected_sell_through(lot)
    services.recompute_liability(department)
    return created(public(lot))


# --- markdown quote --------------------------------------------------------
@bp.get("/fresh/lots/<lot_id>/markdown-quote")
def markdown_quote(lot_id):
    authenticate(ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK)
    lot = lot_by_id(lot_id)
    item = item_of_lot(lot)
    department = department_of_item(item)
    ladder = ladder_of_department(department)
    remaining = calc.days_remaining(lot)
    base_index = calc.base_rung_index(ladder, remaining)
    if base_index < 0:
        raise ApiError("ERR_RUNG_NOT_REACHED",
                       "days_remaining satisfies no ladder rung")
    expected_pct = calc.expected_sell_through(lot, item, department)
    steps = calc.shortfall_steps(ladder, expected_pct)
    sell_through_index = min(len(ladder["rungs"]) - 1, base_index + steps)
    ladder_price, ladder_discount = calc.price_at_rung(item, ladder, base_index)
    st_price, st_discount = calc.price_at_rung(item, ladder,
                                               sell_through_index)
    return ok({
        "lot_id": lot["id"],
        "days_remaining": remaining,
        "expected_sell_through_pct": expected_pct,
        "sell_through_floor_pct": ladder["sell_through_floor_pct"],
        "cost_floor_price_cents": calc.cost_floor_price_cents(item),
        "max_total_discount_pct": ladder["max_total_discount_pct"],
        "base_rung_index": base_index,
        "ladder_days_rung_index": base_index,
        "ladder_days_price_cents": ladder_price,
        "ladder_days_total_discount_pct": ladder_discount,
        "sell_through_shortfall_steps": steps,
        "sell_through_rung_index": sell_through_index,
        "sell_through_price_cents": st_price,
        "sell_through_total_discount_pct": st_discount,
    })


# --- markdowns -------------------------------------------------------------
@bp.post("/fresh/lots/<lot_id>/markdowns")
def create_markdown(lot_id):
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    body = json_body()
    expected_version = field_int(body, "expected_lot_version", required=True,
                                 minimum=0)
    variant = field_enum(body, "pricing_variant", PRICING_VARIANTS,
                         default="LADDER_DAYS")
    override = field_int(body, "override_price_cents", default=MISSING,
                         minimum=0)
    approver = field_string(body, "approval_manager_user_id", default=MISSING,
                           min_len=1, max_len=200, nullable=True)
    lot = lot_by_id(lot_id)
    if lot["version"] != expected_version:
        raise ApiError("ERR_STALE_LOT_VERSION",
                       "expected_lot_version does not match the lot")
    if lot["status"] not in ("FRESH", "MARKED_DOWN") or lot["quantity_on_hand"] <= 0:
        raise ApiError("ERR_LOT_NOT_PRICEABLE",
                       "The lot's status forbids a markdown")
    item = item_of_lot(lot)
    department = department_of_item(item)
    _blocked_guard(department)
    supplied_approver = approver if approver is not MISSING else None
    if supplied_approver is not None and supplied_approver == actor():
        raise ApiError("ERR_MARKDOWN_SELF_APPROVAL",
                       "A requester may not approve its own markdown")
    ladder = ladder_of_department(department)
    if ladder is None or ladder["status"] != "ACTIVE":
        raise ApiError("ERR_LADDER_NOT_ACTIVE",
                       "The department's ladder is not ACTIVE")
    has_override = override is not MISSING and override is not None
    if has_override:
        effective_index = -1
        to_price = override
        discount = calc.total_discount_pct(item, to_price)
    else:
        remaining = calc.days_remaining(lot)
        base_index = calc.base_rung_index(ladder, remaining)
        if base_index < 0:
            raise ApiError("ERR_RUNG_NOT_REACHED",
                           "days_remaining satisfies no ladder rung")
        if variant == "SELL_THROUGH":
            expected_pct = calc.expected_sell_through(lot, item, department)
            steps = calc.shortfall_steps(ladder, expected_pct)
            effective_index = min(len(ladder["rungs"]) - 1, base_index + steps)
        else:
            effective_index = base_index
        to_price, discount = calc.price_at_rung(item, ladder, effective_index)
    if has_override:
        if to_price >= lot["current_price_cents"]:
            raise ApiError("ERR_RUNG_NOT_DEEPER",
                           "The override price is not below the live price")
    elif effective_index <= lot["current_rung_index"]:
        raise ApiError("ERR_RUNG_NOT_DEEPER",
                       "The re-ladder does not land on a deeper rung")
    needs_approval = has_override or ladder["rungs"][effective_index][
        "requires_manager_approval"]
    if needs_approval:
        if role() != ROLE_MANAGER or supplied_approver is None:
            raise ApiError(
                "ERR_MANAGER_APPROVAL_REQUIRED",
                "This markdown needs a DepartmentManager and a distinct "
                "approval_manager_user_id",
            )
    if D(discount) > D(ladder["max_total_discount_pct"]):
        raise ApiError("ERR_MAX_DISCOUNT_EXCEEDED",
                       "The resulting total discount exceeds the ladder cap")
    if has_override and to_price < calc.cost_floor_price_cents(item):
        raise ApiError("ERR_PRICE_BELOW_COST_FLOOR",
                       "override_price_cents is below the cost floor")
    if has_override:
        reason = "MANUAL_OVERRIDE"
    elif lot["current_rung_index"] >= 0:
        reason = "RE_LADDER"
    elif variant == "SELL_THROUGH":
        reason = "SELL_THROUGH"
    else:
        reason = "LADDER_AUTO"
    label = services.apply_markdown(
        lot, item, to_price, discount, effective_index, reason,
        supplied_approver if needs_approval else None,
    )
    return created(public(label))


@bp.post("/fresh/lots/<lot_id>/markdown-void")
def void_markdown(lot_id):
    authenticate(ROLE_MANAGER)
    body = json_body()
    field_string(body, "reason_note", default=None, nullable=True, min_len=1,
                 max_len=240)
    lot = lot_by_id(lot_id)
    if lot["status"] != "MARKED_DOWN":
        raise ApiError("ERR_LOT_NOT_PRICEABLE",
                       "Only a MARKED_DOWN lot has a live markdown to void")
    item = item_of_lot(lot)
    department = department_of_item(item)
    _blocked_guard(department)
    lot["status"] = "FRESH"
    lot["current_price_cents"] = item["base_retail_cents"]
    lot["current_rung_index"] = -1
    lot["total_discount_pct"] = 0
    services.void_open_labels(lot)
    services.refresh_expected_sell_through(lot)
    touch(lot)
    services.recompute_liability(department)
    return ok(public(lot))


@bp.post("/fresh/lots/<lot_id>/sales")
def post_sales(lot_id):
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    body = json_body()
    quantity = field_int(body, "quantity_units", required=True, minimum=1)
    field_string(body, "register_lane_code", default=None, nullable=True,
                 min_len=1, max_len=12)
    lot = lot_by_id(lot_id)
    if lot["status"] not in ("FRESH", "MARKED_DOWN"):
        raise ApiError("ERR_LOT_NOT_PRICEABLE",
                       "Sales may only be posted against a live lot")
    item = item_of_lot(lot)
    department = department_of_item(item)
    _blocked_guard(department)
    if quantity > lot["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_UNITS",
                       "The sale exceeds the units on hand")
    price = lot["current_price_cents"]
    lot["quantity_on_hand"] = lot["quantity_on_hand"] - quantity
    lot["units_sold"] = lot["units_sold"] + quantity
    lot["revenue_cents"] = lot["revenue_cents"] + quantity * price
    lot["markdown_giveback_cents"] = lot["markdown_giveback_cents"] + (
        quantity * (item["base_retail_cents"] - price)
    )
    services.deplete_if_empty(lot)
    services.refresh_expected_sell_through(lot)
    touch(lot)
    services.recompute_liability(department)
    return ok(public(lot))


@bp.post("/fresh/lots/<lot_id>/withdraw")
def withdraw(lot_id):
    authenticate(ROLE_MANAGER, ROLE_AUDITOR)
    body = json_body()
    field_string(body, "reason_note", default=None, nullable=True, min_len=1,
                 max_len=240)
    lot = lot_by_id(lot_id)
    if lot["status"] not in WITHDRAWABLE or lot["quantity_on_hand"] <= 0:
        raise ApiError("ERR_LOT_NOT_PRICEABLE",
                       "This lot cannot be withdrawn from the shelf")
    services.withdraw_lot(lot, actor())
    return ok(public(lot))


# --- scan price checks -----------------------------------------------------
@bp.post("/fresh/lots/<lot_id>/scan-price-checks")
def create_scan_price_check(lot_id):
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    body = json_body()
    lane = field_string(body, "register_lane_code", required=True, min_len=1,
                        max_len=12)
    scanned = field_int(body, "scanned_price_cents", required=True, minimum=0)
    lot = lot_by_id(lot_id)
    expected = lot["current_price_cents"]
    variance = scanned - expected
    if variance == 0:
        outcome = "MATCH"
    elif variance > 0:
        outcome = "OVERCHARGE"
    else:
        outcome = "UNDERCHARGE"
    if outcome == "OVERCHARGE" and variance >= OVERCHARGE_ENFORCEMENT_CENTS:
        enforcement = "LOT_WITHDRAWN"
    elif outcome == "MATCH":
        enforcement = "NONE"
    else:
        enforcement = "PRICE_CORRECTION"
    applied = [l for l in labels_of_lot(lot["id"]) if l["status"] == "APPLIED"]
    barcode = newest_first(applied)[0]["barcode"] if applied else None
    check = new_record(db.checks, {
        "lot_id": lot["id"],
        "register_lane_code": lane,
        "scanned_price_cents": scanned,
        "expected_price_cents": expected,
        "variance_cents": variance,
        "outcome": outcome,
        "enforcement_action": enforcement,
        "label_barcode_snapshot": barcode,
    }, common=False)
    if enforcement == "LOT_WITHDRAWN" and lot["status"] in WITHDRAWABLE:
        services.withdraw_lot(lot, actor())
    return created(public(check))


@bp.get("/fresh/scan-price-checks/<check_id>")
def get_check(check_id):
    authenticate(*READ_ROLES)
    return ok(public(check_by_id(check_id)))


@bp.get("/fresh/scan-price-checks")
def list_checks():
    authenticate(*READ_ROLES)
    lot_id = query_string("lot_id")
    outcome = query_enum("outcome", CHECK_OUTCOMES)
    enforcement = query_enum("enforcement_action", ENFORCEMENT_ACTIONS)
    rows = [
        c for c in db.checks.values()
        if matches(c, "lot_id", lot_id)
        and matches(c, "outcome", outcome)
        and matches(c, "enforcement_action", enforcement)
    ]
    return listing(rows)


# --- markdown labels -------------------------------------------------------
@bp.get("/fresh/markdown-labels/<label_id>")
def get_label(label_id):
    authenticate(*READ_ROLES)
    return ok(public(label_by_id(label_id)))


@bp.get("/fresh/markdown-labels")
def list_labels():
    authenticate(*READ_ROLES)
    lot_id = query_string("lot_id")
    supersedes = query_string("supersedes_label_id")
    status = query_enum("status", LABEL_STATUSES)
    reason = query_enum("reason", LABEL_REASONS)
    rows = [
        l for l in db.labels.values()
        if matches(l, "lot_id", lot_id)
        and matches(l, "supersedes_label_id", supersedes)
        and matches(l, "status", status)
        and matches(l, "reason", reason)
    ]
    return listing(rows)


@bp.post("/fresh/markdown-labels/<label_id>/print")
def print_label(label_id):
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    json_body()
    label = label_by_id(label_id)
    lot = db.lots[label["lot_id"]]
    if label["status"] != "QUEUED":
        raise ApiError("ERR_LABEL_NOT_PRINTED",
                       "Only a QUEUED label may be printed")
    if label["to_price_cents"] != lot["current_price_cents"]:
        raise ApiError(
            "ERR_LABEL_NOT_PRINTED",
            "The label's price no longer matches the lot's live price",
        )
    label["status"] = "PRINTED"
    label["printed_at"] = fmt_instant(db.now())
    touch(label)
    return ok(public(label))


@bp.post("/fresh/markdown-labels/<label_id>/apply")
def apply_label(label_id):
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    json_body()
    label = label_by_id(label_id)
    lot = db.lots[label["lot_id"]]
    if label["status"] != "PRINTED":
        raise ApiError("ERR_LABEL_NOT_PRINTED",
                       "Only a PRINTED label may be applied")
    if lot["status"] not in WITHDRAWABLE:
        raise ApiError("ERR_LOT_NOT_PRICEABLE",
                       "The lot is no longer on the shelf")
    label["status"] = "APPLIED"
    label["applied_at"] = fmt_instant(db.now())
    touch(label)
    services.refresh_expected_sell_through(lot)
    return ok(public(label))


@bp.post("/fresh/markdown-labels/<label_id>/void")
def void_label(label_id):
    authenticate(ROLE_MANAGER)
    json_body()
    label = label_by_id(label_id)
    lot = db.lots[label["lot_id"]]
    if label["status"] == "VOIDED":
        raise ApiError("ERR_LABEL_ALREADY_VOIDED",
                       "This label is already VOIDED")
    label["status"] = "VOIDED"
    touch(label)
    services.refresh_expected_sell_through(lot)
    return ok(public(label))
