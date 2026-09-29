"""The price change approval cycle (PRD 3.3)."""
from flask import Blueprint

import auth
import calc
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, append_audit, new_row, touch
from errors import fail
from routes.common import fk, listing, path_row

bp = Blueprint("pricing", __name__)

READ_ROLES = ("PlatformAdmin", "PricingAnalyst", "PricingApprover", "ComplianceOfficer")
ANALYST_VERBS = ("SUBMIT", "APPLY", "WITHDRAW")
APPROVER_VERBS = ("APPROVE", "REJECT", "REQUEST_CHANGES", "ROLLBACK")
ALL_VERBS = ANALYST_VERBS + APPROVER_VERBS


@bp.post("/price-change-requests")
def open_request():
    ctx = auth.enter(["PricingAnalyst"])
    data = shapes.body()
    item_id = fk(data, "menu_item_id", "menu_items")
    zone_id = fk(data, "price_zone_id", "price_zones")
    if item_id is None:
        shapes.req_str(data, "menu_item_id", 1, None)
    if zone_id is None:
        shapes.req_str(data, "price_zone_id", 1, None)
    proposed = shapes.req_int(data, "proposed_price_cents", 1, 100000)
    justification = shapes.req_str(data, "justification", 1, 280)
    effective = shapes.req_instant(data, "effective_from_utc")
    expected = shapes.req_int(data, "expected_menu_item_version", 0, None)
    item = DB.menu_items[item_id]
    zone = DB.price_zones[zone_id]
    if expected != item.get("version"):
        fail("ERR_STALE_MENU_ITEM_VERSION", "expected_menu_item_version does not match")
    if effective < clockmod.now():
        fail("ERR_EFFECTIVE_DATE_IN_PAST", "effective_from_utc is earlier than the clock")
    if not any(s.get("price_zone_id") == zone_id for s in DB.stores.values()):
        fail("ERR_PRICE_ZONE_MISMATCH", "no store uses this price zone")
    baseline = calc.effective_zone_price(item, zone)
    uplift = calc.round_half_up((proposed - baseline) * C.BP_DENOMINATOR, baseline)
    required = 2 if uplift >= C.DUAL_APPROVAL_UPLIFT_BP else 1
    if uplift > zone["max_uplift_bp"]:
        fail("ERR_UPLIFT_CAP_EXCEEDED", "the uplift exceeds the zone's cap")
    touch(item)
    derive.recompute_item(item, bump=False)
    row = new_row({
        "menu_item_id": item_id,
        "price_zone_id": zone_id,
        "proposed_price_cents": proposed,
        "justification": justification,
        "effective_from_utc": clockmod.iso(effective),
        "state": "DRAFT",
        "requested_by_user_id": ctx["user_id"],
        "approval_user_ids": [],
        "baseline_price_cents": baseline,
        "uplift_bp": uplift,
        "required_approvals": required,
        "revision_round": 0,
        "pinned_menu_item_version": item["version"],
        "applied_price_cents": None,
        "last_decision_comment": None,
    })
    DB.price_requests[row["id"]] = row
    derive.recompute_item(item, bump=False)
    append_audit("PRICE_CHANGE_REQUEST", row["id"], "REQUEST_OPENED", ctx["role"],
                 ctx["user_id"], detail=justification)
    return response.created(serialize.dump("price_request", row))


@bp.get("/price-change-requests")
def list_requests():
    auth.enter(READ_ROLES)
    return listing("price_requests", "price_request")


@bp.get("/price-change-requests/<request_id>")
def get_request(request_id):
    auth.enter(READ_ROLES)
    row = path_row("price_requests", request_id)
    return response.ok(serialize.dump("price_request", row))


def _verb_roles(verb):
    if verb in ANALYST_VERBS:
        return ("PricingAnalyst", "PlatformAdmin")
    return ("PricingApprover", "PlatformAdmin")


def _record_comment(row, comment):
    if comment is not None:
        row["last_decision_comment"] = comment


def _refresh_item(item):
    """Rejection, withdrawal and application all bump the item once."""
    touch(item)
    derive.recompute_item(item, bump=False)


@bp.post("/price-change-requests/<request_id>/actions")
def drive_request(request_id):
    ctx = auth.enter(["PricingAnalyst", "PricingApprover", "PlatformAdmin"])
    data = shapes.body()
    raw_action = data.get("action")
    if isinstance(raw_action, str) and raw_action in ALL_VERBS:
        auth.require_roles(ctx, _verb_roles(raw_action))
    row = path_row("price_requests", request_id)
    action = shapes.req_enum(data, "action", ALL_VERBS)
    comment = shapes.opt_str(data, "comment", 1, 280, None)
    new_price = shapes.opt_int(data, "proposed_price_cents", 1, 100000, None)
    if row["state"] in C.PRICE_REQUEST_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "the request is already in a terminal state")
    item = DB.menu_items.get(row["menu_item_id"])
    zone = DB.price_zones.get(row["price_zone_id"])
    actor = ctx["user_id"]
    if action in ("SUBMIT", "WITHDRAW") and ctx["role"] != "PlatformAdmin":
        if actor != row.get("requested_by_user_id"):
            fail("ERR_UNAUTHORIZED_ROLE", "only the requesting analyst may drive this verb")

    if action == "SUBMIT":
        if row["state"] not in ("DRAFT", "CHANGES_REQUESTED"):
            fail("ERR_INVALID_STATE_TRANSITION", "SUBMIT is not declared out of %s" % row["state"])
        resubmission = row["state"] == "CHANGES_REQUESTED"
        row["state"] = "PENDING_APPROVAL"
        row["approval_user_ids"] = []
        if resubmission:
            row["revision_round"] = int(row.get("revision_round", 0)) + 1
            if new_price is not None:
                row["proposed_price_cents"] = new_price
        _record_comment(row, comment)
        touch(row)
        append_audit("PRICE_CHANGE_REQUEST", row["id"],
                     "PRICE_REQUEST_RESUBMITTED" if resubmission else "PRICE_REQUEST_SUBMITTED",
                     ctx["role"], actor, detail=comment)

    elif action == "APPROVE":
        if row["state"] != "PENDING_APPROVAL":
            fail("ERR_INVALID_STATE_TRANSITION", "APPROVE is not declared out of %s" % row["state"])
        if actor == row.get("requested_by_user_id") or actor in row.get("approval_user_ids", []):
            fail("ERR_SELF_APPROVAL_FORBIDDEN", "an approver may not approve twice or self-approve")
        approvals = list(row.get("approval_user_ids", []))
        approvals.append(actor)
        row["approval_user_ids"] = approvals
        _record_comment(row, comment)
        if len(approvals) >= int(row["required_approvals"]):
            row["state"] = "APPROVED"
            if item is not None:
                row["pinned_menu_item_version"] = item["version"]
            touch(row)
            append_audit("PRICE_CHANGE_REQUEST", row["id"], "PRICE_REQUEST_APPROVED",
                         ctx["role"], actor, detail=comment)
        else:
            touch(row)
            append_audit("PRICE_CHANGE_REQUEST", row["id"], "PRICE_REQUEST_APPROVAL_RECORDED",
                         ctx["role"], actor, detail=comment)

    elif action == "REQUEST_CHANGES":
        if row["state"] != "PENDING_APPROVAL":
            fail("ERR_INVALID_STATE_TRANSITION", "REQUEST_CHANGES is not declared out of %s" % row["state"])
        if actor == row.get("requested_by_user_id"):
            fail("ERR_SELF_APPROVAL_FORBIDDEN", "the requester may not return its own request")
        row["state"] = "CHANGES_REQUESTED"
        row["approval_user_ids"] = []
        _record_comment(row, comment)
        touch(row)
        append_audit("PRICE_CHANGE_REQUEST", row["id"], "PRICE_REQUEST_CHANGES_REQUESTED",
                     ctx["role"], actor, detail=comment)

    elif action == "REJECT":
        if row["state"] != "PENDING_APPROVAL":
            fail("ERR_INVALID_STATE_TRANSITION", "REJECT is not declared out of %s" % row["state"])
        if actor == row.get("requested_by_user_id"):
            fail("ERR_SELF_APPROVAL_FORBIDDEN", "the requester may not reject its own request")
        row["state"] = "REJECTED"
        _record_comment(row, comment)
        touch(row)
        if item is not None:
            _refresh_item(item)
        append_audit("PRICE_CHANGE_REQUEST", row["id"], "PRICE_REQUEST_REJECTED",
                     ctx["role"], actor, detail=comment)

    elif action == "WITHDRAW":
        if row["state"] not in ("DRAFT", "PENDING_APPROVAL", "CHANGES_REQUESTED"):
            fail("ERR_INVALID_STATE_TRANSITION", "WITHDRAW is not declared out of %s" % row["state"])
        row["state"] = "WITHDRAWN"
        _record_comment(row, comment)
        touch(row)
        if item is not None:
            _refresh_item(item)
        append_audit("PRICE_CHANGE_REQUEST", row["id"], "PRICE_REQUEST_WITHDRAWN",
                     ctx["role"], actor, detail=comment)

    elif action == "APPLY":
        if row["state"] in ("DRAFT", "PENDING_APPROVAL", "CHANGES_REQUESTED"):
            fail("ERR_REQUEST_NOT_APPROVED", "only an APPROVED request may be applied")
        if row["state"] != "APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION", "APPLY is not declared out of %s" % row["state"])
        effective = clockmod.parse_instant(row.get("effective_from_utc"))
        if effective is not None and clockmod.now() < effective:
            fail("ERR_EFFECTIVE_DATE_IN_PAST", "the clock has not reached effective_from_utc")
        if item is None or item["version"] != row.get("pinned_menu_item_version"):
            fail("ERR_STALE_MENU_ITEM_VERSION", "the menu item moved since approval")
        if len(row.get("approval_user_ids", [])) < int(row["required_approvals"]):
            fail("ERR_DUAL_APPROVAL_REQUIRED", "the request has too few recorded approvals")
        _record_comment(row, comment)
        derive.apply_price_request(row, ctx["role"], actor)

    else:  # ROLLBACK
        if row["state"] != "APPLIED":
            fail("ERR_INVALID_STATE_TRANSITION", "ROLLBACK is not declared out of %s" % row["state"])
        entry = None
        if item is not None:
            entry = calc.zone_override_entry(item, row["price_zone_id"])
        if entry is None or entry.get("applied_request_id") != row["id"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "a later request has overwritten this zone's override")
        item["zone_price_overrides"] = [e for e in item["zone_price_overrides"] if e is not entry]
        row["state"] = "ROLLED_BACK"
        _record_comment(row, comment)
        touch(row)
        _refresh_item(item)
        append_audit("MENU_ITEM", item["id"], "PRICE_OVERRIDE_ROLLED_BACK", ctx["role"], actor,
                     detail=comment,
                     before_value_cents=row.get("applied_price_cents"),
                     after_value_cents=row.get("baseline_price_cents"))
        derive.reconcile()

    return response.ok(serialize.dump("price_request", row))
