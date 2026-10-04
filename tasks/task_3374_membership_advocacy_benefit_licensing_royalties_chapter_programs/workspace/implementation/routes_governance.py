"""Legal entities and fund transfers (segregation of duties + fiscal caps)."""

from flask import Blueprint, request

from auth import require_roles
from db import locked, mint, store, touch
from serializers import entity_view, transfer_view
from services import check_fiscal_rules, direction_permitted
from util import err, get_body, is_int, paginate, require_str, success_object

bp = Blueprint("governance", __name__)

ENTITY_KINDS = {"MEMBERSHIP_ORG", "FOUNDATION", "LOBBY_ARM"}
ENTITY_READ_ROLES = ("GovernanceOfficer", "FinanceController", "PlatformAdmin")
TRANSFER_DECISIONS = ("APPROVE", "REJECT")


@bp.post("/api/legal-entities")
@locked
def create_legal_entity():
    require_roles("GovernanceOfficer")
    body = get_body()
    kind = body.get("kind")
    if kind is None or kind not in ENTITY_KINDS:
        err("ERR_INVALID_REQUEST", 400, "kind must be one of MEMBERSHIP_ORG, FOUNDATION, LOBBY_ARM")
    display_name = require_str(body, "display_name")
    balance = body.get("balance_cents")
    if balance is None or not is_int(balance):
        err("ERR_INVALID_REQUEST", 400, "balance_cents is required and must be an integer")
    for existing in store.entities.values():
        if existing["kind"] == kind:
            err("ERR_ENTITY_KIND_EXISTS", 409, "A legal entity of kind %s already exists" % kind)
    entity = mint(store.entities)
    entity.update({"kind": kind, "display_name": display_name, "balance_cents": balance})
    return success_object(entity_view(entity), status=201)


@bp.get("/api/legal-entities/<entity_id>")
@locked
def get_legal_entity(entity_id):
    require_roles(*ENTITY_READ_ROLES)
    entity = store.entities.get(entity_id)
    if entity is None:
        err("ERR_NOT_FOUND", 404, "Legal entity not found")
    return success_object(entity_view(entity))


@bp.post("/api/fund-transfers")
@locked
def request_fund_transfer():
    user_id, _ = require_roles("GovernanceOfficer")
    body = get_body()
    from_entity_id = body.get("from_entity_id")
    to_entity_id = body.get("to_entity_id")
    if not isinstance(from_entity_id, str) or not isinstance(to_entity_id, str):
        err("ERR_INVALID_REQUEST", 400, "from_entity_id and to_entity_id are required strings")
    amount = body.get("amount_cents")
    if amount is None or not is_int(amount):
        err("ERR_INVALID_REQUEST", 400, "amount_cents is required and must be an integer")
    if amount < 1:
        err("ERR_INVALID_REQUEST", 400, "amount_cents must be at least 1")
    purpose = require_str(body, "purpose")
    if from_entity_id not in store.entities:
        err("ERR_NOT_FOUND", 404, "from_entity_id does not exist")
    if to_entity_id not in store.entities:
        err("ERR_NOT_FOUND", 404, "to_entity_id does not exist")
    transfer = mint(store.transfers)
    transfer.update(
        {
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "amount_cents": amount,
            "purpose": purpose,
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "status": "PENDING_APPROVAL",
            "from_balance_after_cents": None,
            "to_balance_after_cents": None,
            "executed_at": None,
        }
    )
    return success_object(transfer_view(transfer), status=201)


@bp.get("/api/legal-entities/<entity_id>/fund-transfers")
@locked
def list_entity_transfers(entity_id):
    require_roles(*ENTITY_READ_ROLES)
    if entity_id not in store.entities:
        err("ERR_NOT_FOUND", 404, "Legal entity not found")
    status_filter = request.args.get("status")
    transfers = [
        t
        for t in sorted(store.transfers.values(), key=lambda r: r["_seq"])
        if t["from_entity_id"] == entity_id or t["to_entity_id"] == entity_id
    ]
    if status_filter is not None:
        transfers = [t for t in transfers if t["status"] == status_filter]
    return paginate([transfer_view(t) for t in transfers])


@bp.post("/api/fund-transfers/<transfer_id>/approve")
@locked
def approve_fund_transfer(transfer_id):
    user_id, _ = require_roles("FinanceController")
    transfer = store.transfers.get(transfer_id)
    # Rung 4: segregation of duties runs before schema and before the state
    # check; it requires the transfer to exist (a missing id resolves as 404
    # at the existence rung below).
    if transfer is not None and transfer["requested_by_user_id"] == user_id:
        err("ERR_SELF_APPROVAL", 403, "The approver must differ from the requester")
    body = get_body()
    decision = body.get("decision")
    if decision not in TRANSFER_DECISIONS:
        err("ERR_INVALID_REQUEST", 400, "decision must be APPROVE or REJECT")
    if transfer is None:
        err("ERR_NOT_FOUND", 404, "Fund transfer not found")
    if transfer["status"] != "PENDING_APPROVAL":
        err("ERR_TRANSFER_STATE", 409, "Only a PENDING_APPROVAL transfer can be decided")

    transfer["decided_by_user_id"] = user_id
    if decision == "REJECT":
        transfer["status"] = "REJECTED"
        touch(transfer)
        return success_object(transfer_view(transfer))

    from_entity = store.entities.get(transfer["from_entity_id"])
    to_entity = store.entities.get(transfer["to_entity_id"])
    # Rung 10: governance direction matrix.
    if (
        from_entity is None
        or to_entity is None
        or not direction_permitted(from_entity, to_entity)
    ):
        err("ERR_PROHIBITED_ENTITY_PAIR", 422, "This transfer direction is prohibited by the governance matrix")
    # Rung 12: fiscal checks in pinned order (balance, per-transfer, annual).
    check_fiscal_rules(transfer, from_entity, to_entity)

    # APPROVE executes atomically: balance conservation across the two entities.
    from_entity["balance_cents"] -= transfer["amount_cents"]
    to_entity["balance_cents"] += transfer["amount_cents"]
    transfer["from_balance_after_cents"] = from_entity["balance_cents"]
    transfer["to_balance_after_cents"] = to_entity["balance_cents"]
    transfer["executed_at"] = store.clock_raw
    transfer["status"] = "EXECUTED"
    touch(from_entity)
    touch(to_entity)
    touch(transfer)
    return success_object(transfer_view(transfer))
