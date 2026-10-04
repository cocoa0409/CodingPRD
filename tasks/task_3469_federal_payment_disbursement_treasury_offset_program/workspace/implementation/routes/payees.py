"""Payee endpoints (PRD §3.1)."""
from flask import Blueprint

from constants import ROLE_TREASURY_OPERATOR, ROLE_TREASURY_SUPERVISOR, TIN_TYPES
from db import STORE, new_entity
from errors import err_duplicate_tin
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_payee
from util import gen_id

bp = Blueprint("payees", __name__)


@bp.post("/payees")
def create_payee():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR, ROLE_TREASURY_OPERATOR)
    data = validate_body(get_body(), [
        spec_field("tin", "str", required=True),
        spec_field("tin_type", "enum", required=True, enum=TIN_TYPES),
        spec_field("legal_name", "str", required=True),
        spec_field("routing_number", "str", required=False),
        spec_field("account_last4", "str", required=False),
    ])
    for existing in STORE["payees"].values():
        if existing["tin"] == data["tin"]:
            raise err_duplicate_tin()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "tin": data["tin"],
        "tin_type": data["tin_type"],
        "legal_name": data["legal_name"],
        "routing_number": data["routing_number"],
        "account_last4": data["account_last4"],
    })
    STORE["payees"][ent["id"]] = ent
    return ok(serialize_payee(ent), 201)
