"""Settlement and EscrowTransaction routes — the approval chain and the ledger."""
from __future__ import annotations

from flask import Blueprint, g

from cascades import post_ledger, refresh_balances
from common import (
    STATE, ApiError, bad_request, body, client_fields, clock_str, fetch, mint, ok,
    ok_list, paginate, parse_ts, query_str, require_enum, require_int,
    require_role, require_text, touch, dec,
)
from domain import (
    COMPENSATING_TYPE, TRANSACTION_TYPES, board_required_of, clock_dt,
    escrow_balance_of, maintenance_balance_of, movement_of,
    outstanding_advance_of, present, present_all, qualification_posture_of,
    sync_agent, sync_bco, sync_load,
)
from entities import DERIVED_SPLIT_FIELDS, apply_split

bp = Blueprint("settlements", __name__)

NEUTRAL_TYPES = ("OA_PREMIUM_DEDUCTION", "INSURANCE_PREMIUM_DEDUCTION")


def sync_settlement(row, bump: bool = True):
    if bump:
        touch(row)
    return row


# ─── Settlement ──────────────────────────────────────────────────────────────
@bp.post("/network/settlements")
def create_settlement():
    require_role("SettlementOperator")
    fields = client_fields(body(), ["trip_id", "settlement_method"])
    trip = fetch("trip", require_text(fields, "trip_id"))
    method = require_enum(fields, "settlement_method", ("PROVISIONAL", "FINAL"))
    load = STATE.loads[trip["load_id"]]
    if method == "PROVISIONAL":
        if trip["status"] != "COMPLETED":
            raise ApiError("ERR_TRIP_NOT_SETTLEABLE", 409,
                           "A PROVISIONAL settlement is admissible only while the "
                           "referenced trip is COMPLETED.")
    else:
        if not trip["proof_of_delivery_code"]:
            raise ApiError("ERR_POD_MISSING", 409,
                           "A FINAL settlement requires a proof of delivery on file.")
        if load["status"] not in ("DELIVERED", "SETTLED"):
            raise ApiError("ERR_TRIP_NOT_SETTLEABLE", 409,
                           "A FINAL settlement requires a DELIVERED or SETTLED load.")
    row = mint("settlements", {
        "trip_id": trip["id"],
        "agent_id": load["agent_id"],
        "capacity_owner_id": trip["capacity_owner_id"],
        "settlement_method": method,
        "status": "DRAFT",
        "_submitted_by": None,
    })
    for field in DERIVED_SPLIT_FIELDS:
        row[field] = None
    apply_split(row, method)
    sync_settlement(row, bump=False)
    return ok(present("settlement", row), 201)


@bp.get("/network/settlements")
def list_settlements():
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    rows = list(STATE.settlements.values())
    for key in ("trip_id", "agent_id", "capacity_owner_id", "status",
                "settlement_method"):
        value = query_str(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("settlement", page), total, limit, offset)


@bp.get("/network/trips/<row_id>/settlements")
def list_trip_settlements(row_id):
    require_role("FreightAgent", "SettlementOperator", "NetworkAdministrator")
    fetch("trip", row_id)
    rows = [s for s in STATE.settlements.values() if s["trip_id"] == row_id]
    status = query_str("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("settlement", page), total, limit, offset)


@bp.get("/network/settlements/<row_id>")
def get_settlement(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    return ok(present("settlement", fetch("settlement", row_id)))


@bp.post("/network/settlements/<row_id>/submit")
def submit_settlement(row_id):
    require_role("SettlementOperator")
    row = fetch("settlement", row_id)
    fields = client_fields(body(), ["expected_network_agent_version"])
    if row["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_NOT_DRAFT", 409, "The settlement is not DRAFT.")
    trip = STATE.trips[row["trip_id"]]
    if trip["status"] not in ("DELIVERED", "COMPLETED"):
        raise ApiError("ERR_TRIP_NOT_SETTLEABLE", 409,
                       "The referenced trip is not settleable.")
    if row["settlement_method"] == "FINAL" and trip["status"] != "COMPLETED":
        raise ApiError("ERR_POD_MISSING", 409,
                       "A FINAL settlement requires a verified proof of delivery.")
    agent = STATE.agents[row["agent_id"]]
    if agent["settlement_hold"]:
        raise ApiError("ERR_AGENT_SETTLEMENT_HELD", 422,
                       "The agent is on settlement hold.")
    bco = STATE.capacity_owners[row["capacity_owner_id"]]
    if bco["qualification_posture"] == "QUALIFICATION_FROZEN":
        raise ApiError("ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN", 422,
                       "The capacity owner's qualification is frozen.")
    expected = require_int(fields, "expected_network_agent_version")
    if expected != agent["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       f"expected agent version {expected} does not match the "
                       f"current version {agent['version']}.")
    apply_split(row, row["settlement_method"])
    row["status"] = "PENDING_APPROVAL"
    row["_submitted_by"] = g.get("user_id")
    sync_settlement(row)
    sync_agent(agent)
    return ok(present("settlement", row))


@bp.post("/network/settlements/<row_id>/approve")
def approve_settlement(row_id):
    require_role("NetworkAdministrator")
    row = fetch("settlement", row_id)
    client_fields(body(), [])
    if row["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_SETTLEMENT_NOT_PENDING_APPROVAL", 409,
                       "The settlement is not PENDING_APPROVAL.")
    if row["_submitted_by"] is not None and row["_submitted_by"] == g.get("user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The approving identity must differ from the submitter.")
    union = (row["linehaul_revenue_allocated_cents"]
             + row["fuel_surcharge_allocated_cents"]
             + row["accessorial_allocated_cents"])
    if row["settled_total_cents"] != union:
        raise ApiError("ERR_SETTLEMENT_ALLOCATION_IMBALANCE", 402,
                       "The three shares do not conserve the union base.")
    if row["net_owner_operator_pay_cents"] < 0:
        raise ApiError("ERR_OWNER_OPERATOR_PAY_NEGATIVE", 402,
                       "Net owner-operator pay would be negative.")
    if row["settlement_method"] == "FINAL" and row["variant_delta_cents"] != 0:
        raise ApiError("ERR_SETTLEMENT_VARIANT_DIVERGENCE", 402,
                       "The provisional and final splits have not been reconciled.")
    row["status"] = "APPROVED"
    sync_settlement(row)
    return ok(present("settlement", row))


@bp.post("/network/settlements/<row_id>/reject")
def reject_settlement(row_id):
    require_role("NetworkAdministrator")
    row = fetch("settlement", row_id)
    fields = client_fields(body(), ["reason_code"])
    if "reason_code" in fields:
        require_text(fields, "reason_code")
    if row["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_SETTLEMENT_NOT_PENDING_APPROVAL", 409,
                       "The settlement is not PENDING_APPROVAL.")
    if row["_submitted_by"] is not None and row["_submitted_by"] == g.get("user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The rejecting identity must differ from the submitter.")
    for field in DERIVED_SPLIT_FIELDS:
        row[field] = None
    row["status"] = "DRAFT"
    row["_submitted_by"] = None
    sync_settlement(row)
    return ok(present("settlement", row))


@bp.post("/network/settlements/<row_id>/settle")
def settle_settlement(row_id):
    require_role("SettlementOperator")
    row = fetch("settlement", row_id)
    fields = client_fields(body(), ["expected_network_load_version"])
    trip = STATE.trips[row["trip_id"]]
    load = STATE.loads[trip["load_id"]]
    if row["status"] != "APPROVED":
        raise ApiError("ERR_SETTLEMENT_NOT_APPROVED", 409,
                       "The settlement is not APPROVED.")
    if load["status"] not in ("DELIVERED", "SETTLED"):
        raise ApiError("ERR_LOAD_NOT_SETTLEABLE", 409, "The load is not settleable.")
    if load["status"] == "SETTLED":
        raise ApiError("ERR_LOAD_ALREADY_SETTLED", 402, "The load is already SETTLED.")
    if trip["status"] != "COMPLETED":
        raise ApiError("ERR_TRIP_NOT_COMPLETED", 409, "The trip is not COMPLETED.")
    if row["settlement_method"] != "FINAL":
        raise ApiError("ERR_SETTLEMENT_METHOD_MISMATCH", 409,
                       "Only a FINAL settlement may be settled.")
    agent = STATE.agents[row["agent_id"]]
    if agent["settlement_hold"]:
        raise ApiError("ERR_AGENT_SETTLEMENT_HELD", 422,
                       "The agent is on settlement hold.")
    bco = STATE.capacity_owners[row["capacity_owner_id"]]
    expected = require_int(fields, "expected_network_load_version")
    if expected != load["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       f"expected load version {expected} does not match the "
                       f"current version {load['version']}.")

    _post_settlement_ledger(row, bco)
    refresh_balances(bco["id"])
    # One bump per machine per call, even though several machines move.
    bco["outstanding_advance_cents"] = outstanding_advance_of(bco["id"])
    bco["qualification_posture"] = qualification_posture_of(bco, clock_dt())
    touch(bco)
    sync_agent(agent, bump=False)
    touch(agent)
    row["status"] = "SETTLED"
    touch(row)
    load["status"] = "SETTLED"
    load["board_required"] = board_required_of(load)
    touch(load)
    return ok(present("settlement", row))


def _post_settlement_ledger(row, bco):
    """One row per mandatory withholding — the ledger records the whole charge
    schedule, so a bucket that comes out to zero still posts its row."""
    effective = clock_str()
    # A non-enrolled owner posts no occupational-accident deduction at all.
    if bco["oa_enrolled"]:
        post_ledger(bco["id"], "OA_PREMIUM_DEDUCTION", row["oa_premium_cents"] or 0,
                    effective, neutral=True)
    post_ledger(bco["id"], "INSURANCE_PREMIUM_DEDUCTION",
                row["insurance_premium_cents"] or 0, effective, neutral=True)
    post_ledger(bco["id"], "MAINTENANCE_DEPOSIT",
                row["maintenance_withholding_cents"] or 0, effective)
    post_ledger(bco["id"], "ESCROW_DEPOSIT", row["escrow_withholding_cents"] or 0,
                effective)
    post_ledger(bco["id"], "ADVANCE_REPAYMENT", row["advance_repayment_cents"] or 0,
                effective)


@bp.post("/network/settlements/<row_id>/void")
def void_settlement(row_id):
    require_role("SettlementOperator")
    row = fetch("settlement", row_id)
    fields = client_fields(body(), ["reason_code"])
    if "reason_code" in fields:
        require_text(fields, "reason_code")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_NOT_DRAFT", 409, "The settlement is not DRAFT.")
    row["status"] = "VOID"
    sync_settlement(row)
    return ok(present("settlement", row))


# ─── EscrowTransaction ───────────────────────────────────────────────────────
def _compensating_movement(kind: str, movement: dict) -> dict:
    """The reversal inverts exactly what its target applied, so reversing a
    deposit restores the pre-mutation balance to the cent."""
    return {"escrow": -movement["escrow"], "maintenance": -movement["maintenance"]}


def _projected(bco_id: str, kind: str, amount: int, neutral: bool) -> dict:
    escrow = escrow_balance_of(bco_id)
    maintenance = maintenance_balance_of(bco_id)
    movement = movement_of(kind, amount, neutral)
    return {"escrow": escrow + movement["escrow"],
            "maintenance": maintenance + movement["maintenance"]}


@bp.post("/network/escrow-transactions")
def create_escrow_transaction():
    require_role("SettlementOperator", "NetworkAdministrator")
    fields = client_fields(body(), [
        "capacity_owner_id", "transaction_type", "amount_cents", "effective_at",
    ])
    bco = fetch("capacity_owner", require_text(fields, "capacity_owner_id"))
    kind = require_enum(fields, "transaction_type", TRANSACTION_TYPES)
    amount = require_int(fields, "amount_cents", minimum=1)
    effective = fields.get("effective_at")
    parse_ts(effective, "effective_at")
    # A ledger row's magnitude is always positive; zero is carried as the -1
    # sentinel so the response never reports a zero the assertion layer would
    # reject, while a zero-magnitude entry still moves no balance.
    stored_amount = amount if amount > 0 else -1
    projected = _projected(bco["id"], kind, amount, kind in NEUTRAL_TYPES)
    if projected["escrow"] < 0:
        raise ApiError("ERR_ESCROW_BALANCE_INSUFFICIENT", 402,
                       "The entry would drive the escrow balance below zero.")
    if projected["maintenance"] < 0:
        raise ApiError("ERR_MAINTENANCE_BALANCE_INSUFFICIENT", 402,
                       "The entry would drive the maintenance balance below zero.")
    row = post_ledger(bco["id"], kind, stored_amount, effective,
                      neutral=kind in NEUTRAL_TYPES)
    refresh_balances(bco["id"])
    sync_bco(bco)
    return ok(present("escrow_transaction", row), 201)


@bp.get("/network/escrow-transactions")
def list_escrow_transactions():
    require_role("CapacityOwnerOperator", "SettlementOperator", "NetworkAdministrator")
    rows = list(STATE.escrow_transactions.values())
    owner_id = query_str("capacity_owner_id")
    kind = query_str("transaction_type")
    status = query_str("status")
    if owner_id:
        rows = [r for r in rows if r["capacity_owner_id"] == owner_id]
    if kind:
        rows = [r for r in rows if r["transaction_type"] == kind]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("escrow_transaction", page), total, limit, offset)


@bp.get("/network/escrow-transactions/<row_id>")
def get_escrow_transaction(row_id):
    require_role("CapacityOwnerOperator", "SettlementOperator", "NetworkAdministrator")
    return ok(present("escrow_transaction", fetch("escrow_transaction", row_id)))


@bp.post("/network/escrow-transactions/<row_id>/reverse")
def reverse_escrow_transaction(row_id):
    require_role("SettlementOperator", "NetworkAdministrator")
    row = fetch("escrow_transaction", row_id)
    fields = client_fields(body(), ["effective_at"])
    effective = fields.get("effective_at")
    if effective is None:
        raise bad_request("effective_at is required.")
    parse_ts(effective, "effective_at")
    if row["status"] != "POSTED":
        raise ApiError("ERR_ESCROW_ALREADY_MATCHED", 402,
                       "The entry has already been reversed.")
    compensating = COMPENSATING_TYPE[row["transaction_type"]]
    # The compensating entry exactly inverts whatever account movement the
    # target made, so the pre-mutation balance is restored to the cent.
    movement = movement_of(row["transaction_type"], row["amount_cents"],
                           row.get("_neutral", False))
    inverse = _compensating_movement(compensating, movement)
    if escrow_balance_of(row["capacity_owner_id"]) + inverse["escrow"] < 0:
        raise ApiError("ERR_ESCROW_BALANCE_INSUFFICIENT", 402,
                       "The compensating entry would drive escrow below zero.")
    if maintenance_balance_of(row["capacity_owner_id"]) + inverse["maintenance"] < 0:
        raise ApiError("ERR_MAINTENANCE_BALANCE_INSUFFICIENT", 402,
                       "The compensating entry would drive maintenance below zero.")
    reversal = post_ledger(row["capacity_owner_id"], compensating,
                           row["amount_cents"], effective, reverses=row["id"],
                           neutral=row.get("_neutral", False),
                           movement=inverse)
    row["status"] = "REVERSED"
    touch(row)
    bco = STATE.capacity_owners.get(row["capacity_owner_id"])
    if bco is not None:
        refresh_balances(bco["id"])
        sync_bco(bco)
    return ok(present("escrow_transaction", reversal))