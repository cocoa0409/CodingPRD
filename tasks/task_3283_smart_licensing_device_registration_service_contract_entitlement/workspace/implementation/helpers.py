"""Shared request helpers: datetime parsing, body validation, auth context, RBAC."""
from datetime import datetime, timezone

from flask import request

import store
from errors import ApiError

ROLES = {"PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent"}


def parse_iso(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO8601 string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return b


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", f"{name} is required and must be a string")
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{name} must be a string")
    return v


def req_int(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{name} is required and must be an integer")
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return v


def req_dt(b, name):
    return parse_iso(b.get(name), name)


def opt_dt(b, name):
    v = b.get(name)
    if v is None:
        return None
    return parse_iso(v, name)


# ---------------------------------------------------------------- auth / RBAC

class Actor:
    def __init__(self):
        self.user_id = request.headers.get("X-User-ID")
        self.role = request.headers.get("X-User-Role")
        if not self.user_id or not self.role or self.role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")

    def require_roles(self, *roles):
        if self.role not in roles:
            raise ApiError("ERR_FORBIDDEN")


# Map resource kind -> (table, function row -> owning smart_account_id)
def owning_account_id(kind, row):
    if row is None:
        return None
    if kind == "smart_account":
        return row["id"]
    if kind == "virtual_account":
        return row["smart_account_id"]
    if kind == "license_pool":
        va = store.DB["virtual_accounts"].get(row["virtual_account_id"])
        return va["smart_account_id"] if va else None
    if kind == "device":
        va = store.DB["virtual_accounts"].get(row["virtual_account_id"])
        return va["smart_account_id"] if va else None
    if kind == "assignment":
        pool = store.DB["license_pools"].get(row["license_pool_id"])
        return owning_account_id("license_pool", pool)
    if kind == "usage_report" or kind == "rma_case":
        dev = store.DB["devices"].get(row["device_id"])
        return owning_account_id("device", dev)
    if kind == "compliance_event":
        pool = store.DB["license_pools"].get(row["license_pool_id"])
        return owning_account_id("license_pool", pool)
    if kind == "service_contract":
        return row["smart_account_id"]
    if kind == "contract_coverage":
        contract = store.DB["service_contracts"].get(row["service_contract_id"])
        return contract["smart_account_id"] if contract else None
    if kind == "transfer_request":
        pool = store.DB["license_pools"].get(row["source_pool_id"])
        return owning_account_id("license_pool", pool)
    return None


def _partner_delegation(actor, account_id, scope_needed):
    for d in store.DB["partner_delegations"].values():
        if (d["partner_org_id"] == actor.user_id
                and d["smart_account_id"] == account_id
                and d["status"] == "ACTIVE"):
            if d["scope"] == "FULL" or d["scope"] == scope_needed:
                return d
    return None


def authorize_resource(actor, kind, row, scope_needed=None, write=False):
    """Enforce AccountAdmin ownership and PartnerManager delegation+scope (PRD 2.1)."""
    if actor.role in ("PlatformAdmin", "LogisticsAgent"):
        return
    account_id = owning_account_id(kind, row)
    if actor.role == "AccountAdmin":
        if account_id is None or account_id != actor.user_id:
            raise ApiError("ERR_FORBIDDEN")
        return
    if actor.role == "PartnerManager":
        if not write:
            # Reads: allowed when the partner has any ACTIVE delegation on the account.
            if account_id is None:
                raise ApiError("ERR_FORBIDDEN")
            ok = any(
                d["partner_org_id"] == actor.user_id
                and d["smart_account_id"] == account_id
                and d["status"] == "ACTIVE"
                for d in store.DB["partner_delegations"].values()
            )
            if not ok:
                raise ApiError("ERR_FORBIDDEN")
            return
        if account_id is None or not _partner_delegation(actor, account_id, scope_needed):
            raise ApiError("ERR_FORBIDDEN")
        return


def require_row(table, row_id):
    row = store.DB[table].get(row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", f"{table} id not found")
    return row
