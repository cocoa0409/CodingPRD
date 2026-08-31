"""Logical clock, Vault, VaultInventory and cash-letter reconciliation routes."""

from flask import Blueprint

import calc
import core
from core import (
    DENOMINATIONS,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FED_AGENT,
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    VAULT_POSTURES,
    authorize,
    body_json,
    db,
    fail,
    fmt_dt,
    get_pagination,
    get_vault,
    inventory_of_vault,
    inventory_row,
    make_row,
    opt_int,
    paginate,
    parse_dt,
    query_enum,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    respond,
    touch,
)
from serializers import inventory_out, vault_out

bp = Blueprint("vaults", __name__)


# ---------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    _raw, parsed = req_datetime(body, "to_iso8601")
    db.clock = parsed
    return respond({"current_utc": fmt_dt(parsed)})


# ---------------------------------------------------------------------- Vault
@bp.post("/vaults")
def create_vault():
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    vault_code = req_str(body, "vault_code", min_len=1, max_len=32)
    name = req_str(body, "name")
    limit = opt_int(body, "pickup_concurrency_limit", default=2, minimum=1)

    # ladder 30 - duplicate business identifier
    for existing in db.vaults.values():
        if existing["vault_code"] == vault_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "vault_code '%s' already exists." % vault_code)

    row = make_row()
    row.update({
        "vault_code": vault_code,
        "name": name,
        "posture": "OPEN",
        "pickup_concurrency_limit": limit,
        "cash_letter_adjustment_cents": 0,
        "coin_face_value_on_hand_cents": 0,
    })
    db.vaults[row["id"]] = row
    return respond(vault_out(row), 201)


@bp.get("/vaults/<vault_id>")
def read_vault(vault_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_COMPLIANCE_OFFICER, ROLE_FED_AGENT)
    vault = get_vault(vault_id)
    return respond(vault_out(vault))


LEGAL_POSTURE_MOVES = {
    ("OPEN", "RESTRICTED"),
    ("RESTRICTED", "FROZEN"),
    ("OPEN", "FROZEN"),
    ("FROZEN", "OPEN"),
    ("RESTRICTED", "OPEN"),
}


@bp.post("/vaults/<vault_id>/posture")
def set_posture(vault_id):
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    target = req_enum(body, "posture", VAULT_POSTURES)
    vault = get_vault(vault_id)

    if (vault["posture"], target) not in LEGAL_POSTURE_MOVES:
        fail("ERR_INVALID_STATE", "Posture cannot move from %s to %s." % (vault["posture"], target))

    vault["posture"] = target
    touch(vault)
    return respond(vault_out(vault))


@bp.post("/vaults/<vault_id>/inventory-adjustments")
def adjust_inventory(vault_id):
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    denomination = req_enum(body, "denomination", DENOMINATIONS)
    delta = req_int(body, "delta_boxes")
    vault = get_vault(vault_id)

    inv = inventory_row(vault_id, denomination)
    current_on_hand = inv["on_hand_boxes"] if inv is not None else 0

    # ladder 37 - the row is left untouched when the delta would go negative
    if current_on_hand + delta < 0:
        fail("ERR_INVENTORY_NEGATIVE", "Adjustment would drive on_hand_boxes below zero.")

    if inv is None:
        inv = make_row()
        inv.update({
            "vault_id": vault_id,
            "denomination": denomination,
            "on_hand_boxes": 0,
            "reserved_boxes": 0,
            "available_boxes": 0,
        })
        db.inventory[inv["id"]] = inv

    inv["on_hand_boxes"] = inv["on_hand_boxes"] + delta
    calc.recompute_available_boxes(inv)
    touch(inv)

    calc.recompute_vault_coin_face_value(vault)
    touch(vault)
    return respond(inventory_out(inv))


@bp.get("/vaults/<vault_id>/inventory")
def list_inventory(vault_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER)
    limit, offset = get_pagination()
    denomination = query_enum("denomination", DENOMINATIONS)
    get_vault(vault_id)

    rows = inventory_of_vault(vault_id)
    if denomination is not None:
        rows = [r for r in rows if r["denomination"] == denomination]
    return paginate(rows, limit, offset, inventory_out)


@bp.get("/vaults/<vault_id>/cash-letter-reconciliation")
def cash_letter_reconciliation(vault_id):
    authorize(ROLE_VAULT_MANAGER)
    vault = get_vault(vault_id)

    letters = [f for f in db.fed_deposits.values() if f["vault_id"] == vault_id]
    shipped = sum(
        f["declared_total_cents"]
        for f in letters
        if f["status"] in ("SUBMITTED", "CONFIRMED", "CONFIRMED_WITH_ADJUSTMENT")
    )
    credited = sum(
        f["credited_total_cents"]
        for f in letters
        if f["status"] in ("CONFIRMED", "CONFIRMED_WITH_ADJUSTMENT")
    )
    outstanding = sum(
        f["declared_total_cents"] for f in letters if f["status"] == "SUBMITTED"
    )
    net_adjustment = sum(
        f["adjustment_cents"] for f in letters if f["status"] == "CONFIRMED_WITH_ADJUSTMENT"
    )
    reconciled = (outstanding == 0) and (net_adjustment == vault["cash_letter_adjustment_cents"])

    return respond({
        "vault_id": vault_id,
        "shipped_total_cents": shipped,
        "credited_total_cents": credited,
        "outstanding_cents": outstanding,
        "net_adjustment_cents": net_adjustment,
        "reconciled": reconciled,
    })
