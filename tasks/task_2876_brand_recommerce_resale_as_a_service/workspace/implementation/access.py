"""Ownership scoping for the entity-backed Customer role (PRD 2.10)."""

import store
from errors import ApiError


def require_owner(role, user_id, customer_id):
    """A Customer caller may only reach rows whose customer reference is theirs."""
    if role == "Customer" and customer_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def unit_customer_id(unit):
    """The participant whose trade-in produced this resale unit."""
    trade_in = store.get("trade_ins", unit.get("trade_in_id"))
    if trade_in is None:
        return None
    return trade_in.get("customer_id")


def grant_customer_id(grant):
    return grant.get("customer_id")


def scope_customer_filter(role, user_id, requested_customer_id):
    """Resolve the effective customer filter for a list endpoint.

    A Customer caller may filter only by their own identifier; when they supply
    no filter at all the listing is silently narrowed to their own rows.
    """
    if role != "Customer":
        return requested_customer_id
    if requested_customer_id is not None and requested_customer_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return user_id
