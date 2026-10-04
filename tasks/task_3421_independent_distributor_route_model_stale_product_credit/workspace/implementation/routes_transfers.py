"""Territory transfer routes: list under an agreement, settle."""
from flask import Blueprint

import auth
import domain
import store
from constants import (
    ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR,
)
from errors import ERR_NOT_FOUND, ERR_INVALID_STATE, raise_err
from response import ok_object, ok_list, pagination_params

bp = Blueprint("transfers", __name__)

ALL = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)


@bp.route("/agreements/<rid>/transfers", methods=["GET"])
def list_transfers(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    auth.check_resource_owner(user_id, role, agreement["distributor_id"])
    transfers = [t for t in store.all_of("transfers") if t["agreement_id"] == rid]
    page = pagination_params()
    total = len(transfers)
    window = transfers[page["offset"]:page["offset"] + page["limit"]]
    return ok_list(window, total, page)


@bp.route("/transfers/<rid>/settle", methods=["POST"])
def settle(rid):
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_CREDIT_ANALYST,))
    transfer = store.get("transfers", rid)
    if transfer is None:
        raise_err(ERR_NOT_FOUND, "Territory transfer not found")
    if transfer["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING transfer can be settled")
    domain.settle_transfer(transfer)
    return ok_object(transfer)
