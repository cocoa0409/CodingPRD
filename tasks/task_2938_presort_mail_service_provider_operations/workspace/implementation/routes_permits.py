"""Permit accounts: opening, funding, lifecycle and statement reverse lookup."""

from flask import Blueprint

import domain
import enums
import serialize
import shape
from envelope import listed, single
from errors import ApiError
from store import db, order_by_created, touch
from util import parse_instant

bp = Blueprint("permits", __name__)


@bp.post("/permit-accounts")
def create_permit_account():
    shape.authenticate(("PostageManager",))
    body = shape.validate_body(
        {
            "client_id": {"type": "string"},
            "permit_number": {"type": "string", "check": shape.non_blank_len(4, 24)},
            "payment_method": {"type": "enum", "values": enums.PAYMENT_METHODS},
            "annual_fee_paid_through_utc": {"type": "datetime"},
        }
    )
    domain.get_client(body["client_id"])
    for existing in db.permit_accounts.values():
        if existing["permit_number"] == body["permit_number"]:
            raise ApiError("ERR_DUPLICATE_PERMIT_NUMBER")
    record = db.insert(
        "permit_accounts",
        {
            "client_id": body["client_id"],
            "permit_number": body["permit_number"],
            "payment_method": body["payment_method"],
            "annual_fee_paid_through_utc": parse_instant(
                body["annual_fee_paid_through_utc"]
            ),
            "balance_cents": 0,
            "reserved_cents": 0,
            "status": "ACTIVE",
        },
    )
    return single(serialize.permit_account(record), 201)


@bp.get("/permit-accounts/<permit_id>")
def read_permit_account(permit_id):
    shape.authenticate(
        ("BureauAdmin", "PostageManager", "AcceptanceClerk", "ClientContact")
    )
    return single(serialize.permit_account(domain.get_permit(permit_id)))


@bp.post("/permit-accounts/<permit_id>/funding")
def fund_permit_account(permit_id):
    shape.authenticate(("PostageManager",))
    body = shape.validate_body(
        {
            "amount_cents": {"type": "integer"},
            "expected_permit_account_version": {"type": "integer"},
            "reference": {"type": "string", "required": False, "nullable": True},
        }
    )
    record = domain.get_permit(permit_id)
    # rung 16
    if body["expected_permit_account_version"] != record["version"]:
        raise ApiError("ERR_STALE_PERMIT_VERSION")
    # rung 19
    if record["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    # rung 31
    if body["amount_cents"] < 1:
        raise ApiError("ERR_INVALID_PIECE_COUNT")
    record["balance_cents"] += body["amount_cents"]
    touch(record)
    return single(serialize.permit_account(record))


@bp.post("/permit-accounts/<permit_id>/status")
def set_permit_status(permit_id):
    shape.authenticate(("PostageManager",))
    body = shape.validate_body(
        {
            "status": {"type": "enum", "values": enums.PERMIT_STATUSES},
            "reason": {"type": "string", "required": False, "nullable": True},
        }
    )
    record = domain.get_permit(permit_id)
    target = body["status"]
    if target == "HOLD":
        if record["status"] != "ACTIVE":
            raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    elif target == "ACTIVE":
        if record["status"] != "HOLD":
            raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    else:
        if record["status"] not in ("ACTIVE", "HOLD"):
            raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
        # rung 45
        if record["reserved_cents"] != 0:
            raise ApiError("ERR_PERMIT_HAS_RESERVED_FUNDS")
    record["status"] = target
    touch(record)
    return single(serialize.permit_account(record))


@bp.get("/permit-accounts/<permit_id>/postage-statements")
def list_permit_statements(permit_id):
    shape.authenticate(("BureauAdmin", "PostageManager", "AcceptanceClerk"))
    domain.get_permit(permit_id)
    records = order_by_created(
        [
            s
            for s in db.postage_statements.values()
            if s["permit_account_id"] == permit_id
        ]
    )
    return listed(records, serialize.postage_statement)
