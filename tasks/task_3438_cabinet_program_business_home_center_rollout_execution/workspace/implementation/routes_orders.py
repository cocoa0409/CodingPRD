"""Order endpoints (PRD 3.3, 3.4, 3.6)."""
from flask import Blueprint, request

from auth import get_body, require_roles
from db import bump, new_entity, store
from envelope import ok, paginate
from errors import api_error
from services import (commit_slot, create_order_entity, current_batch_for,
                      family_map, get_active_line, price_items, priced_line_for,
                      recompute_credit, release_slot, select_slots_strict)
from util import add_weeks, parse_week, week_of

bp = Blueprint("orders", __name__)

READ_ROLES = ("PlatformAdmin", "ProgramManager", "PlantScheduler",
              "LogisticsCoordinator", "ClaimsAdjuster", "RetailDesigner", "DealerRep")

# Per-transition role pins (PRD 2.9 stage 2 / scaffold validations priority 2).
TRANSITION_ROLE_PINS = {
    "ACKNOWLEDGED": "ProgramManager",
    "SCHEDULED": "PlantScheduler",
    "IN_PRODUCTION": "PlantScheduler",
    "MFG_COMPLETE": "PlantScheduler",
}

FULFILLMENT_EDGES = {
    "SUBMITTED": {"ACKNOWLEDGED"},
    "ACKNOWLEDGED": {"SCHEDULED"},
    "SCHEDULED": {"IN_PRODUCTION"},
    "IN_PRODUCTION": {"MFG_COMPLETE"},
}


def serialize(order):
    return dict(order)


@bp.route("/cabinet/orders", methods=["POST"])
def create_order():
    uid, _ = require_roles("DealerRep")
    body = get_body()
    account_id = body.get("account_id")
    if account_id is None:
        raise api_error("ERR_INVALID_REQUEST", "account_id is required")
    # Entity-backed ownership: DealerRep X-User-ID is the Account id.
    if uid != account_id:
        raise api_error("ERR_FORBIDDEN",
                        "DealerRep may only place orders for their own account")
    account = store.accounts.get(account_id)
    if account is None:
        raise api_error("ERR_NOT_FOUND", "account not found")
    program_id = body.get("program_id")
    if program_id is None:
        raise api_error("ERR_INVALID_REQUEST", "program_id is required")
    program = store.programs.get(program_id)
    if program is None:
        raise api_error("ERR_NOT_FOUND", "program not found")
    if account["status"] != "ACTIVE":
        raise api_error("ERR_ACCOUNT_NOT_ACTIVE", "account is not ACTIVE")
    if program["status"] not in ("ACTIVE", "TRANSITIONING"):
        raise api_error("ERR_PROGRAM_NOT_ACTIVE",
                        "program must be ACTIVE or TRANSITIONING")
    if account["channel"] == "RETAIL":
        raise api_error("ERR_CHANNEL_REQUIRES_DESIGN_JOB",
                        "RETAIL accounts order via design-job conversion")
    if body.get("design_job_id") is not None:
        raise api_error("ERR_CHANNEL_REQUIRES_DESIGN_JOB",
                        "dealer/builder orders never carry design_job_id")
    destination_type = body.get("destination_type")
    if destination_type not in ("JOB_SITE", "STORE"):
        raise api_error("ERR_INVALID_REQUEST",
                        "destination_type must be JOB_SITE or STORE")
    store_code = None
    jobsite_address = None
    if destination_type == "STORE":
        store_code = body.get("store_code")
        if store_code is None:
            raise api_error("ERR_INVALID_REQUEST",
                            "store_code is required for STORE destinations")
        if store_code not in account["store_codes"]:
            raise api_error("ERR_STORE_NOT_SERVICED",
                            "store_code is not an element of the account's store_codes")
    else:
        jobsite_address = body.get("jobsite_address")
        if jobsite_address is None:
            raise api_error("ERR_INVALID_REQUEST",
                            "jobsite_address is required for JOB_SITE destinations")
    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise api_error("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    lines = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise api_error("ERR_INVALID_REQUEST", "each order line must be an object")
        fam_code = raw.get("family_code")
        fin_code = raw.get("finish_code")
        qty = raw.get("quantity")
        if not isinstance(fam_code, str) or not fam_code:
            raise api_error("ERR_INVALID_REQUEST", "family_code is required on every line")
        if not isinstance(fin_code, str) or not fin_code:
            raise api_error("ERR_INVALID_REQUEST", "finish_code is required on every line")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise api_error("ERR_INVALID_REQUEST", "quantity must be a positive integer")
        lines.append({"family_code": fam_code, "finish_code": fin_code, "quantity": qty})
    active_line = get_active_line(program["id"])
    if active_line is None:
        raise api_error("ERR_NO_ACTIVE_LINE", "program has no ACTIVE line")
    fmap = family_map(active_line)
    for line in lines:
        if line["family_code"] not in fmap:
            raise api_error("ERR_LINE_NOT_COVERED",
                            "family_code {} is not covered by the program's ACTIVE "
                            "line".format(line["family_code"]))
    requested_week = body.get("requested_delivery_week")
    if parse_week(requested_week) is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "requested_delivery_week must be an ISO week 'YYYY-Www'")
    min_lead = min(fmap[fc]["base_lead_weeks"] for fc in {l["family_code"] for l in lines})
    if parse_week(add_weeks(requested_week, -min_lead)) < parse_week(week_of(store.clock)):
        raise api_error("ERR_DELIVERY_WEEK_INVALID",
                        "requested_delivery_week minus the smallest base lead lands "
                        "before the current week")
    order = create_order_entity(account, program, lines, destination_type,
                                store_code, jobsite_address, requested_week, None)
    recompute_credit(account["id"])
    return ok(order, 201)


@bp.route("/cabinet/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_roles(*READ_ROLES)
    order = store.orders.get(order_id)
    if order is None:
        raise api_error("ERR_NOT_FOUND", "order not found")
    return ok(serialize(order))


@bp.route("/cabinet/orders", methods=["GET"])
def list_orders():
    require_roles(*READ_ROLES)
    account_id = request.args.get("account_id")
    program_id = request.args.get("program_id")
    design_job_id = request.args.get("design_job_id")
    status = request.args.get("status")
    items = [o for o in store.orders.values()
             if (account_id is None or o["account_id"] == account_id)
             and (program_id is None or o["program_id"] == program_id)
             and (design_job_id is None or o["design_job_id"] == design_job_id)
             and (status is None or o["status"] == status)]
    items = sorted(items, key=lambda o: o["created_at"])
    page, meta = paginate([serialize(o) for o in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/orders/<order_id>/transition", methods=["POST"])
def transition_order(order_id):
    _, role = require_roles("ProgramManager", "PlantScheduler")
    order = store.orders.get(order_id)
    if order is None:
        raise api_error("ERR_NOT_FOUND", "order not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    if to_status in TRANSITION_ROLE_PINS and role != TRANSITION_ROLE_PINS[to_status]:
        raise api_error("ERR_FORBIDDEN",
                        "role {} may not drive the {} transition".format(role, to_status))
    if to_status not in FULFILLMENT_EDGES.get(order["status"], set()):
        raise api_error("ERR_INVALID_STATE",
                        "cannot move order from {} to {}".format(order["status"], to_status))
    account = store.accounts[order["account_id"]]
    program = store.programs[order["program_id"]]

    if to_status == "ACKNOWLEDGED":
        if account["status"] != "ACTIVE":
            raise api_error("ERR_ACCOUNT_NOT_ACTIVE", "account is not ACTIVE")
        if program["status"] not in ("ACTIVE", "TRANSITIONING"):
            raise api_error("ERR_PROGRAM_NOT_ACTIVE",
                            "program must be ACTIVE or TRANSITIONING")
        order["price_lock"] = True
        order["status"] = "ACKNOWLEDGED"
        bump(order)
        recompute_credit(account["id"])
        # PRD 3.4: acknowledgement runs the credit evaluation of 2.8 — if
        # including this order pushes the account's open_exposure_cents
        # strictly above its credit_limit_cents, THIS order's payment_status
        # becomes CREDIT_HOLD; otherwise it stays UNINVOICED.
        if (order["payment_status"] == "UNINVOICED"
                and account["open_exposure_cents"] > account["credit_limit_cents"]):
            order["payment_status"] = "CREDIT_HOLD"
            bump(order)
        return ok(serialize(order))

    if to_status == "SCHEDULED":
        priced = priced_line_for(order)
        fmap = family_map(priced) if priced is not None else {}
        demands = {}
        for li in order["lines"]:
            fc = li["family_code"]
            fam = fmap.get(fc)
            if fam is None:
                raise api_error("ERR_LINE_NOT_COVERED",
                                "family_code {} is not resolvable".format(fc))
            if fc in demands:
                demands[fc][0] += li["units"]
            else:
                demands[fc] = [li["units"], fam["base_lead_weeks"]]
        picks = select_slots_strict({k: (v[0], v[1]) for k, v in demands.items()},
                                    order["requested_delivery_week"])
        # Fiscal gate (PRD 2.9 stage 9): evaluated strictly after the capacity
        # constraint stage (stage 8) — a request violating both is answered
        # ERR_NO_CAPACITY. Selection above commits nothing, so a rejected
        # request leaves every slot untouched.
        if order["payment_status"] != "UNINVOICED":
            raise api_error("ERR_CREDIT_HOLD", "order is on CREDIT_HOLD")
        picked_records = []
        for fc, slot in picks.items():
            commit_slot(slot, demands[fc][0])
            picked_records.append((slot["id"], fc, demands[fc][0]))
        store.order_slot_picks[order["id"]] = picked_records
        latest_week = max((p["week"] for p in picks.values()),
                          key=lambda w: parse_week(w))
        order["scheduled_week"] = latest_week
        max_lead = max(fmap[li["family_code"]]["base_lead_weeks"] for li in order["lines"])
        order["scheduled_delivery_week"] = add_weeks(latest_week, max_lead)
        order["status"] = "SCHEDULED"
        bump(order)
        return ok(serialize(order))

    if to_status == "IN_PRODUCTION":
        for li in order["lines"]:
            batch = current_batch_for(li["finish_code"])
            if batch is None:
                raise api_error("ERR_NO_CURRENT_BATCH",
                                "no CURRENT finish batch for {}".format(li["finish_code"]))
            li["finish_batch_id"] = batch["id"]
        order["status"] = "IN_PRODUCTION"
        bump(order)
        return ok(serialize(order))

    # MFG_COMPLETE: auto-create the order's 1:1 shipment in PLANNED.
    shipment = new_entity()
    shipment.update({
        "order_id": order["id"],
        "destination_type": order["destination_type"],
        "store_code": order["store_code"],
        "jobsite_address": order["jobsite_address"],
        "status": "PLANNED",
        "attempt_count": 0,
        "delivered_at": None,
    })
    store.shipments[shipment["id"]] = shipment
    order["status"] = "MFG_COMPLETE"
    bump(order)
    return ok(serialize(order))


@bp.route("/cabinet/orders/<order_id>/financial", methods=["POST"])
def financial_order(order_id):
    require_roles("ProgramManager")
    order = store.orders.get(order_id)
    if order is None:
        raise api_error("ERR_NOT_FOUND", "order not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    if to_status == "INVOICED":
        if (order["payment_status"] != "UNINVOICED"
                or order["status"] not in ("MFG_COMPLETE", "SHIPPED", "DELIVERED")):
            raise api_error("ERR_INVALID_STATE",
                            "invoicing requires payment UNINVOICED and fulfillment "
                            "MFG_COMPLETE, SHIPPED or DELIVERED")
        if order["price_lock"]:
            # Price lock: the invoice repeats the quote verbatim.
            order["invoiced_total_cents"] = order["quoted_total_cents"]
            for li in order["lines"]:
                li["unit_invoiced_cents"] = li["unit_quoted_cents"]
        else:
            account = store.accounts[order["account_id"]]
            program = store.programs[order["program_id"]]
            items = [{"family_code": li["family_code"], "quantity": li["quantity"]}
                     for li in order["lines"]]
            total, unit_nets, line = price_items(account, program, items)
            order["invoiced_total_cents"] = total
            for li, unit_net in zip(order["lines"], unit_nets):
                li["unit_invoiced_cents"] = unit_net
            store.order_priced_line[order["id"]] = line["id"]
        order["payment_status"] = "INVOICED"
        bump(order)
        recompute_credit(order["account_id"])
        return ok(serialize(order))
    if to_status == "PAID":
        if order["payment_status"] != "INVOICED":
            raise api_error("ERR_INVALID_STATE",
                            "payment requires payment_status INVOICED")
        order["payment_status"] = "PAID"
        bump(order)
        recompute_credit(order["account_id"])
        return ok(serialize(order))
    raise api_error("ERR_INVALID_STATE",
                    "unsupported financial transition {}".format(to_status))


@bp.route("/cabinet/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = require_roles("DealerRep", "ProgramManager")
    order = store.orders.get(order_id)
    if order is None:
        raise api_error("ERR_NOT_FOUND", "order not found")
    if role == "DealerRep" and order["account_id"] != uid:
        raise api_error("ERR_FORBIDDEN",
                        "DealerRep may only cancel their own account's orders")
    if order["status"] not in ("SUBMITTED", "ACKNOWLEDGED", "SCHEDULED"):
        raise api_error("ERR_ORDER_NOT_CANCELLABLE",
                        "order cannot be cancelled from {}".format(order["status"]))
    if order["status"] == "SCHEDULED":
        # Compensating release of committed slot units (slot may auto-OPEN).
        for slot_id, _fam, units in store.order_slot_picks.get(order["id"], []):
            slot = store.slots.get(slot_id)
            if slot is not None:
                release_slot(slot, units)
        store.order_slot_picks.pop(order["id"], None)
    order["status"] = "CANCELLED"
    bump(order)
    recompute_credit(order["account_id"])
    return ok(serialize(order))
