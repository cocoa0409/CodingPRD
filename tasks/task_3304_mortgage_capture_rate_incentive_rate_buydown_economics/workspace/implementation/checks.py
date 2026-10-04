"""The ordered validation ladder (PRD section 2.10) plus body coercions."""

import json

from flask import request

from db import db, ROLES, PRIORITY_ORDER
from errors import fail, ApiError
from services import common, selectors, calc

# ---------------------------------------------------------------------------
# Priority 1 / 2: authentication and authorization
# ---------------------------------------------------------------------------
PUBLIC_PATHS = {
    ("POST", "/housing/_clock/set_current_utc"),
    ("GET", "/housing/communities"),
}


def is_public(method, path):
    if (method, path) in PUBLIC_PATHS:
        return True
    if method == "GET" and path.startswith("/housing/communities/") and path.count("/") == 3:
        # GET /housing/communities/{id}
        return True
    return False


def authenticate(roles, allow_anonymous_listing=False):
    """Priority 1 then 2. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role and X-User-ID headers are required")
    if role not in roles:
        fail("ERR_FORBIDDEN", "the authenticated role may not perform this operation")
    return role, user_id


def gate_listing(roles):
    """Auth for the two endpoints reachable without credentials and for reads."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None:
        return None, None
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role names no declared role")
    if role not in roles:
        fail("ERR_FORBIDDEN", "the authenticated role may not perform this operation")
    return role, user_id


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body():
    raw = request.get_data(as_text=True)
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def require_fields(payload, fields):
    for field in fields:
        if field not in payload or payload[field] is None:
            fail("ERR_INVALID_REQUEST", "required field '%s' is missing or null" % field)


def int_field(payload, name, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        fail("ERR_INVALID_REQUEST", "required field '%s' is missing or null" % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_ENUM_VALUE", "field '%s' lies outside its declared bounds" % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_ENUM_VALUE", "field '%s' lies outside its declared bounds" % name)
    return value


def string_field(payload, name, max_length=None):
    if name not in payload or payload[name] is None:
        fail("ERR_INVALID_REQUEST", "required field '%s' is missing or null" % name)
    value = payload[name]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "field '%s' must be a non-empty string" % name)
    if max_length is not None and len(value) > max_length:
        fail("ERR_INVALID_ENUM_VALUE", "field '%s' exceeds its declared length" % name)
    return value


def enum_field(payload, name, allowed):
    if name not in payload or payload[name] is None:
        fail("ERR_INVALID_REQUEST", "required field '%s' is missing or null" % name)
    value = payload[name]
    if value not in allowed:
        fail("ERR_INVALID_ENUM_VALUE", "field '%s' carries a value outside its declared set" % name)
    return value


def iso_field(payload, name):
    from db import parse_iso

    if name not in payload or payload[name] is None:
        fail("ERR_INVALID_REQUEST", "required field '%s' is missing or null" % name)
    value = payload[name]
    if not isinstance(value, str) or parse_iso(value) is None:
        fail("ERR_INVALID_ENUM_VALUE", "field '%s' must be an ISO 8601 instant" % name)
    return value


def state_code_field(payload, name):
    value = string_field(payload, name)
    if len(value) != 2 or value != value.upper() or not value.isalpha():
        fail("ERR_INVALID_ENUM_VALUE", "field '%s' must be two uppercase letters" % name)
    return value


# ---------------------------------------------------------------------------
# Priority 3: existence, left to right along the path
# ---------------------------------------------------------------------------
def get_community(community_id):
    row = db.communities.get(community_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "community not found")
    return row


def get_home_site(home_site_id):
    row = db.home_sites.get(home_site_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "home site not found")
    return row


def get_buyer(buyer_id):
    row = db.buyers.get(buyer_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "buyer not found")
    return row


def get_contract(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "sale contract not found")
    return row


def get_application(application_id):
    row = db.loan_applications.get(application_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "loan application not found")
    return row


def get_rate_lock(rate_lock_id):
    row = db.rate_locks.get(rate_lock_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "rate lock not found")
    return row


def get_commitment(commitment_id):
    row = db.forward_commitments.get(commitment_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "forward commitment not found")
    return row


def get_allocation(allocation_id):
    row = db.incentive_allocations.get(allocation_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "incentive allocation not found")
    return row


def get_buydown(buydown_id):
    row = db.buydown_records.get(buydown_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "buydown cost record not found")
    return row


def get_disclosure(disclosure_id):
    row = db.disclosures.get(disclosure_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "disclosure not found")
    return row


def get_forfeiture(forfeiture_id):
    row = db.deposit_forfeitures.get(forfeiture_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "deposit settlement not found")
    return row


# ---------------------------------------------------------------------------
# Priority 4: state machine
# ---------------------------------------------------------------------------
def require_state(row, field, allowed, message=None):
    if row.get(field) not in allowed:
        fail("ERR_INVALID_STATE", message or "the resource is not in a state permitting this transition")
    return row


# ---------------------------------------------------------------------------
# Priority 23: optimistic concurrency
# ---------------------------------------------------------------------------
def check_contract_version(payload, contract):
    expected = payload.get("expected_contract_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_contract_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST", "expected_contract_version must be an integer")
    if expected != contract.get("version"):
        fail("ERR_STALE_CONTRACT_VERSION", "the contract version has advanced since it was read")


def check_application_version(payload, application):
    expected = payload.get("expected_application_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_application_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST", "expected_application_version must be an integer")
    if expected != application.get("version"):
        fail("ERR_STALE_APPLICATION_VERSION", "the application version has advanced since it was read")


# ---------------------------------------------------------------------------
# Buyer ownership (RBAC, entity-backed role)
# ---------------------------------------------------------------------------
def check_buyer_ownership(resource, buyer_id_field="buyer_id"):
    role = request.headers.get("X-User-Role")
    if role != "Buyer":
        return
    user_id = request.headers.get("X-User-ID")
    if resource.get(buyer_id_field) != user_id:
        fail("ERR_FORBIDDEN", "the buyer may only read their own resources")


def contract_owner_id(contract):
    return contract.get("buyer_id")


def application_owner_id(application):
    contract = db.contracts.get(application.get("contract_id"))
    return contract.get("buyer_id") if contract else None


def lock_owner_id(lock):
    application = db.loan_applications.get(lock.get("application_id"))
    return application_owner_id(application) if application else None