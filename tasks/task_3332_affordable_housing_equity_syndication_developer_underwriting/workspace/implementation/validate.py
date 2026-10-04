"""Authentication, request-shape, existence and referential-scope checks.

These are the first five tiers of the fixed priority order in PRD 2.9 and are
applied in exactly that order by every route.
"""

import clock
import errors
import store

# Exactly seven role names are recognised, and no others (PRD 2.1).
ROLES = ("Developer", "Investor", "Underwriter", "AssetManager",
         "ComplianceOfficer", "Anonymous", "PlatformAdmin")
ENTITY_BACKED = ("Developer", "Investor")

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


# --- tier 1 / tier 2: authentication and role authority ----------------------
def authenticate(request):
    """Returns (role, user_id).  Raises ERR_UNAUTHENTICATED when unusable."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(ID_HEADER)
    if role is None or role not in ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "X-User-Role must name one of the seven declared roles.")
    if role == "Anonymous":
        errors.fail(errors.ERR_UNAUTHENTICATED, "Anonymous is never a usable role.")
    if role in ENTITY_BACKED and not user_id:
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "X-User-ID is required for an entity-backed role.")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        errors.fail(errors.ERR_FORBIDDEN, "The acting role may not call this endpoint.")


# --- tier 3: request shape ---------------------------------------------------
def body(request):
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def required(payload, names):
    for name in names:
        if name not in payload or payload[name] is None:
            errors.fail(errors.ERR_INVALID_REQUEST, "Missing required input: %s" % name)


def optional(payload, name, default=None):
    value = payload.get(name)
    return default if value is None else value


def as_int(payload, name, required_field=True):
    if name not in payload or payload[name] is None:
        if required_field:
            errors.fail(errors.ERR_INVALID_REQUEST, "Missing required input: %s" % name)
        return None
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must be a number." % name)
    if isinstance(value, float) and not float(value).is_integer():
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must be a whole number." % name)
    return int(value)


def as_number(payload, name, required_field=True):
    if name not in payload or payload[name] is None:
        if required_field:
            errors.fail(errors.ERR_INVALID_REQUEST, "Missing required input: %s" % name)
        return None
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must be a number." % name)
    return float(value)


def as_string(payload, name, required_field=True):
    if name not in payload or payload[name] is None:
        if required_field:
            errors.fail(errors.ERR_INVALID_REQUEST, "Missing required input: %s" % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or value == "":
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must be a non-empty string." % name)
    return value


def non_negative(value, name):
    if value is not None and value < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must not be negative." % name)
    return value


def in_enum(value, allowed, name):
    if value not in allowed:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def as_datetime(payload, name, required_field=True):
    if name not in payload or payload[name] is None:
        if required_field:
            errors.fail(errors.ERR_INVALID_REQUEST, "Missing required input: %s" % name)
        return None
    try:
        return clock.fmt(clock._parse(payload[name]))
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must be an ISO 8601 instant." % name)


def as_state_code(payload, name="state_code"):
    value = as_string(payload, name)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        errors.fail(errors.ERR_INVALID_REQUEST, "state_code must be exactly two uppercase letters.")
    return value


def as_absorption(payload, name="market_study_absorption_score"):
    value = as_number(payload, name)
    if value < 0 or value > 1:
        errors.fail(errors.ERR_INVALID_REQUEST, "%s must be between 0 and 1 inclusive." % name)
    return value


def as_payin_schedule(payload, name="payin_schedule"):
    value = payload.get(name)
    if not isinstance(value, list) or not value:
        errors.fail(errors.ERR_INVALID_REQUEST, "payin_schedule must be a non-empty array.")
    total = 0.0
    for entry in value:
        if not isinstance(entry, dict) or "milestone" not in entry or "share_pct" not in entry:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "each payin_schedule element needs milestone and share_pct.")
        share = entry["share_pct"]
        if isinstance(share, bool) or not isinstance(share, (int, float)) or share < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "share_pct must be a non-negative number.")
        total += float(share)
    if abs(total - 1.0) > 1e-9:
        errors.fail(errors.ERR_INVALID_REQUEST, "payin_schedule share_pct values must sum to 1.0.")
    return value


# --- tier 4: existence, resolved left to right -------------------------------
def get_developer(developer_id):
    row = store.developers.get(developer_id)
    if row is None:
        errors.fail(errors.ERR_DEVELOPER_NOT_FOUND, "No Developer carries that id.")
    return row


def get_investor(investor_id):
    row = store.investors.get(investor_id)
    if row is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "No Investor carries that id.")
    return row


def get_fund(fund_id):
    row = store.funds.get(fund_id)
    if row is None:
        errors.fail(errors.ERR_FUND_NOT_FOUND, "No SyndicationFund carries that id.")
    return row


def get_project(project_id):
    row = store.projects.get(project_id)
    if row is None:
        errors.fail(errors.ERR_PROJECT_NOT_FOUND, "No Project carries that id.")
    return row


def get_subscription(subscription_id):
    row = store.subscriptions.get(subscription_id)
    if row is None:
        errors.fail(errors.ERR_SUBSCRIPTION_NOT_FOUND, "No FundSubscription carries that id.")
    return row


def get_call(call_id):
    row = store.calls.get(call_id)
    if row is None:
        errors.fail(errors.ERR_CAPITAL_CALL_NOT_FOUND, "No CapitalCall carries that id.")
    return row


def get_guarantee(guarantee_id):
    row = store.guarantees.get(guarantee_id)
    if row is None:
        errors.fail(errors.ERR_GUARANTEE_NOT_FOUND, "No Guarantee carries that id.")
    return row


def get_review(review_id):
    row = store.reviews.get(review_id)
    if row is None:
        errors.fail(errors.ERR_REVIEW_NOT_FOUND, "No PortfolioReview carries that id.")
    return row


def get_exit_event(exit_event_id):
    row = store.exits.get(exit_event_id)
    if row is None:
        errors.fail(errors.ERR_EXIT_EVENT_NOT_FOUND, "No ExitEvent carries that id.")
    return row


def get_child(collection, child_id, project_id, error_id):
    """A nested child is addressable only within its own project."""
    row = collection.get(child_id)
    if row is None or row.get("project_id") != project_id:
        errors.fail(error_id, "No such child under the path project.")
    return row


# --- tier 5: referential scope ----------------------------------------------
def scope_developer(role, user_id, developer_id):
    if role == "Developer" and user_id != developer_id:
        errors.fail(errors.ERR_FORBIDDEN_SCOPE, "A Developer may act only on its own record.")


def scope_project(role, user_id, project):
    """A Developer may reach only its own projects."""
    if role == "Developer" and project["developer_id"] != user_id:
        errors.fail(errors.ERR_FORBIDDEN_SCOPE, "A Developer may act only on its own projects.")


def scope_subscription(role, user_id, subscription):
    if role == "Investor" and subscription["investor_id"] != user_id:
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may act only on its own subscriptions.")


def investor_holds_fund(investor_id, fund_id):
    return any(s["investor_id"] == investor_id and s["fund_id"] == fund_id
               for s in store.subscriptions.values())
