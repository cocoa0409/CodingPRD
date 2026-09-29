"""Brand-currency grants, their immutable ledger and the expiry sweep
(PRD 3.9)."""

from flask import Blueprint

import access
import constants as C
import serialize
import services
import store
import validators as V
from envelope import list_response, object_response, paginate

bp = Blueprint("credit", __name__)


@bp.post("/credit-grants/expiry-runs")
def run_expiry_sweep():
    V.guard("ProgramAdmin")
    return object_response(services.expiry_sweep())


@bp.get("/credit-grants/<grant_id>")
def get_credit_grant(grant_id):
    user_id, role = V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    grant = store.require("credit_grants", grant_id)
    access.require_owner(role, user_id, grant["customer_id"])
    return object_response(serialize.out(grant))


@bp.get("/credit-grants")
def list_credit_grants():
    user_id, role = V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    limit, offset = V.pagination()
    status = V.enum_query("status", C.GRANT_STATUSES)
    customer_id = V.id_query("customer_id")
    trade_in_id = V.id_query("trade_in_id")
    credit_policy_id = V.id_query("credit_policy_id")
    if customer_id is not None:
        store.require("customers", customer_id)
    if trade_in_id is not None:
        store.require("trade_ins", trade_in_id)
    if credit_policy_id is not None:
        store.require("credit_policies", credit_policy_id)
    customer_id = access.scope_customer_filter(role, user_id, customer_id)

    rows = store.rows("credit_grants")
    if customer_id is not None:
        rows = [g for g in rows if g["customer_id"] == customer_id]
    if trade_in_id is not None:
        rows = [g for g in rows if g["trade_in_id"] == trade_in_id]
    if credit_policy_id is not None:
        rows = [g for g in rows if g["credit_policy_id"] == credit_policy_id]
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.get("/credit-grants/<grant_id>/ledger-entries")
def list_grant_entries(grant_id):
    user_id, role = V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    limit, offset = V.pagination()
    entry_type = V.enum_query("entry_type", C.ENTRY_TYPES)
    grant = store.require("credit_grants", grant_id)
    access.require_owner(role, user_id, grant["customer_id"])
    rows = services.grant_entries(grant["id"])
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)
