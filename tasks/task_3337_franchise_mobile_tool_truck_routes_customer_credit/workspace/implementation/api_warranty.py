"""Warranty claims filed, priced and adjudicated at the truck."""

from flask import Blueprint

import auth
import calc
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("warranty", __name__, url_prefix="/retail")

CLAIM_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
               "RouteSalesRep", "WarrantyAdmin")
KINDS = ("WARRANTY_REPLACEMENT", "CLAIM")
CLAIM_ACTIONS = ("SUBMIT", "APPROVE", "REJECT", "REOPEN")
NON_TERMINAL = ("OPEN", "SUBMITTED")


@bp.post("/sales-orders/<order_id>/warranty-claims")
def file_claim(order_id):
    user_id, role = auth.require("RouteSalesRep")
    order = lookup.sales_order(order_id)
    auth.ensure_owned(user_id, role, auth.order_owner_id(order))
    payload = envelope.body()
    line_index = envelope.as_int(payload, "line_index", minimum=0)
    claim_kind = envelope.as_enum(payload, "claim_kind", KINDS)
    idempotency_key = envelope.as_str(payload, "idempotency_key")

    if order.get("order_status") not in ("DELIVERED", "SETTLED"):
        fail("ERR_WARRANTY_ORDER_NOT_DELIVERED")

    for existing in store.claims.values():
        if (existing.get("order_id") == order["id"]
                and existing.get("idempotency_key") == idempotency_key):
            store.set_field(existing, "is_idempotent_replay", True)
            return envelope.ok(existing, 201)

    if line_index >= len(order.get("lines", [])):
        fail("ERR_WARRANTY_LINE_OUT_OF_RANGE")
    for existing in store.claims.values():
        if (existing.get("order_id") == order["id"]
                and existing.get("line_index") == line_index
                and existing.get("claim_status") in NON_TERMINAL):
            fail("ERR_WARRANTY_ALREADY_CLAIMED")

    apply_to_account_id = None
    if payload.get("apply_to_account_id") is not None:
        target = lookup.account(envelope.as_str(payload, "apply_to_account_id"))
        apply_to_account_id = target["id"]

    draft = {
        "order_id": order["id"],
        "line_index": line_index,
        "claim_kind": claim_kind,
        "claim_status": "OPEN",
    }
    replacement, credit = recompute.claim_amounts(draft)
    claim = store.create(
        store.claims,
        order_id=order["id"],
        route_id=order.get("route_id"),
        line_index=line_index,
        claim_kind=claim_kind,
        claim_status="OPEN",
        idempotency_key=idempotency_key,
        apply_to_account_id=apply_to_account_id,
        filed_iso_week=clock.fmt_week(clock.current_week_start()),
        resolved_iso_week=None,
        replacement_charge_cents=replacement,
        warranty_credit_amount_cents=credit,
        principal_allocated_cents=0,
        is_idempotent_replay=False,
    )
    return envelope.ok(claim, 201)


@bp.get("/warranty-claims")
def list_claims():
    auth.require(*CLAIM_ROLES)
    rows = envelope.filter_query(store.ordered(store.claims), {
        "order_id": "order_id",
        "apply_to_account_id": "apply_to_account_id",
        "claim_status": "claim_status",
        "claim_kind": "claim_kind",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.post("/sales-orders/<order_id>/warranty-claims/<claim_id>/status")
def advance_claim(order_id, claim_id):
    user_id, role = auth.require("RouteSalesRep", "WarrantyAdmin")
    order = lookup.sales_order(order_id)
    auth.ensure_owned(user_id, role, auth.order_owner_id(order))
    claim = lookup.claim(order, claim_id)
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", CLAIM_ACTIONS)

    if action == "SUBMIT" and role != "RouteSalesRep":
        fail("ERR_UNAUTHORIZED")
    if action in ("APPROVE", "REJECT", "REOPEN") and role != "WarrantyAdmin":
        fail("ERR_UNAUTHORIZED")

    status = claim.get("claim_status")
    if action == "SUBMIT":
        if status == "APPROVED":
            fail("ERR_CLAIM_ALREADY_TERMINAL")
        if status not in ("OPEN", "REJECTED"):
            fail("ERR_INVALID_STATE")
        _require_order_delivered(order)
        if claim.get("line_index", -1) >= len(order.get("lines", [])):
            fail("ERR_WARRANTY_LINE_OUT_OF_RANGE")
        store.set_field(claim, "claim_status", "SUBMITTED")
        store.set_field(claim, "resolved_iso_week", None)
    elif action == "APPROVE":
        if status in ("APPROVED", "REJECTED"):
            fail("ERR_CLAIM_ALREADY_TERMINAL")
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE")
        _require_order_delivered(order)
        _approve(claim, order)
    elif action == "REJECT":
        if status in ("APPROVED", "REJECTED"):
            fail("ERR_CLAIM_ALREADY_TERMINAL")
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE")
        _require_order_delivered(order)
        store.set_field(claim, "claim_status", "REJECTED")
        store.set_field(claim, "resolved_iso_week", clock.fmt_week(clock.current_week_start()))
        store.set_field(claim, "principal_allocated_cents", 0)
    else:
        if status != "APPROVED":
            fail("ERR_CLAIM_NOT_TERMINAL")
        _reverse_allocation(claim, order)
        store.set_field(claim, "claim_status", "SUBMITTED")
        store.set_field(claim, "resolved_iso_week", None)

    store.stamp(claim)
    recompute.recompute_claim(claim)
    recompute.recompute_order(order)
    return envelope.ok(claim)


def _require_order_delivered(order):
    if order.get("order_status") not in ("DELIVERED", "SETTLED"):
        fail("ERR_WARRANTY_ORDER_NOT_DELIVERED")


def _approve(claim, order):
    if claim.get("claim_kind") == "CLAIM":
        account = lookup.account(claim.get("apply_to_account_id") or "")
        allocated = claim.get("replacement_charge_cents", 0)
        account["principal_balance_cents"] = account.get("principal_balance_cents", 0) + allocated
        store.stamp(account)
        recompute.recompute_account(account)
        recompute.recompute_account_dependants(account)
    else:
        allocated = 0
    store.set_field(claim, "claim_status", "APPROVED")
    store.set_field(claim, "resolved_iso_week", clock.fmt_week(clock.current_week_start()))
    store.set_field(claim, "principal_allocated_cents", allocated)


def _reverse_allocation(claim, order):
    allocated = claim.get("principal_allocated_cents", 0)
    if claim.get("claim_kind") == "CLAIM" and allocated:
        account = store.accounts.get(claim.get("apply_to_account_id"))
        if account is not None:
            account["principal_balance_cents"] = max(
                0, account.get("principal_balance_cents", 0) - allocated)
            store.stamp(account)
            recompute.recompute_account(account)
            recompute.recompute_account_dependants(account)
    store.set_field(claim, "principal_allocated_cents", 0)
