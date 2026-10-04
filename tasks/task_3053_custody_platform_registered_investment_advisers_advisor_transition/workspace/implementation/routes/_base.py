"""Shared handler scaffolding: identity, pagination and row loaders."""

from flask import request

from core.context import Params, parse_identity
from core.errors import fail
from core.store import STORE


def identity():
    return parse_identity()


def params():
    return Params(request.args)


def load(entity, row_id, error_id="ERR_RESOURCE_NOT_FOUND"):
    row = STORE.get(entity, row_id)
    if row is None:
        fail(error_id)
    return row


def load_firm(firm_id):
    return load("AdvisorFirm", firm_id, "ERR_FIRM_NOT_FOUND")


def load_child(entity, row_id, parent_field, parent_id):
    row = load(entity, row_id)
    if parent_id is not None and row.get(parent_field) != parent_id:
        fail("ERR_PARENT_CHILD_MISMATCH")
    return row


def load_via_account(entity, row_id, ident):
    """Load an account-scoped row and apply the Client ownership guard."""
    row = load(entity, row_id)
    account_id = row.get("account_id")
    if account_id is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if ident.is_client:
        account = STORE.get("HouseholdAccount", account_id)
        if account is None or account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
    return row