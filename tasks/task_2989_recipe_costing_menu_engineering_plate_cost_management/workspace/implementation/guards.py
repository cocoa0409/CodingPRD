"""Authentication, role authorisation, request-schema validation, pagination.

The numbered comments refer to the global validation order of PRD 2.10.
"""
import re

from flask import g, request

from core import ROLES, db, order_key, parse_instant
from errors import fail

_MISSING = object()


# --- 1 & 2: authentication and authorisation -------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ROLES:
        fail("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role '%s' is not authorised on this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


ANY_ROLE = tuple(ROLES)


# --- 3: request body / query string ---------------------------------------
def get_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    if name not in body:
        return _MISSING
    value = body[name]
    if value is None:
        return _MISSING
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return _as_int(name, value, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return _as_int(name, value, minimum, maximum)


def _as_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %d." % (name, maximum))
    return value


def req_str(body, name, pattern=None, min_len=1, max_len=None):
    value = _present(body, name)
    if value is _MISSING:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return _as_str(name, value, pattern, min_len, max_len)


def opt_str(body, name, default=None, pattern=None, min_len=1, max_len=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return _as_str(name, value, pattern, min_len, max_len)


def _as_str(name, value, pattern, min_len, max_len):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    if pattern is not None and re.match(pattern, value) is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' does not match the required format." % name)
    return value


def req_id(body, name):
    """A foreign-key identifier: required, string typed, no format constraint."""
    return req_str(body, name, min_len=1)


def opt_id(body, name, default=None):
    return opt_str(body, name, default=default, min_len=1)


def req_enum(body, name, choices):
    value = req_str(body, name, min_len=None)
    if value not in choices:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def opt_enum(body, name, choices, default=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return req_enum(body, name, choices)


def req_bool(body, name):
    value = _present(body, name)
    if value is _MISSING:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=False):
    value = _present(body, name)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_instant(body, name):
    value = _present(body, name)
    if value is _MISSING:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return _as_instant(name, value)


def opt_instant(body, name, default=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return _as_instant(name, value)


def _as_instant(name, value):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant string." % name)
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a well-formed ISO 8601 instant." % name)
    return parsed


def require_null(body, name):
    if name in body and body[name] is not None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be null for this change type." % name)


def window(start, end, start_name, end_name):
    if start is not None and end is not None and not start < end:
        fail("ERR_INVALID_REQUEST", "%s must be strictly before %s." % (start_name, end_name))


# --- 3: pagination ---------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    try:
        return int(text, 10)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def query_enum(name, choices):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in choices:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, ", ".join(choices)))
    return raw


def query_str(name):
    return request.args.get(name)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serializer(row) for row in page], limit, offset, total


def sorted_rows(rows, key=None):
    return sorted(rows, key=key or order_key)


# --- 4..13: existence -----------------------------------------------------
def find_unit(unit_id):
    row = db.units.get(unit_id)
    if row is None:
        fail("ERR_UNIT_NOT_FOUND", "No unit with id %s." % unit_id)
    return row


def find_ingredient(ingredient_id):
    row = db.ingredients.get(ingredient_id)
    if row is None:
        fail("ERR_INGREDIENT_NOT_FOUND", "No ingredient with id %s." % ingredient_id)
    return row


def find_feed(price_feed_id):
    row = db.price_feeds.get(price_feed_id)
    if row is None:
        fail("ERR_PRICE_FEED_NOT_FOUND", "No price feed with id %s." % price_feed_id)
    return row


def find_recipe(recipe_id):
    row = db.recipes.get(recipe_id)
    if row is None:
        fail("ERR_RECIPE_NOT_FOUND", "No recipe with id %s." % recipe_id)
    return row


def find_component(component_id):
    row = db.recipe_components.get(component_id)
    if row is None:
        fail("ERR_COMPONENT_NOT_FOUND", "No recipe component with id %s." % component_id)
    return row


def find_menu_item(menu_item_id):
    row = db.menu_items.get(menu_item_id)
    if row is None:
        fail("ERR_MENU_ITEM_NOT_FOUND", "No menu item with id %s." % menu_item_id)
    return row


def find_proposal(proposal_id):
    row = db.proposals.get(proposal_id)
    if row is None:
        fail("ERR_PROPOSAL_NOT_FOUND", "No price change proposal with id %s." % proposal_id)
    return row


def find_order(order_id):
    row = db.spec_change_orders.get(order_id)
    if row is None:
        fail("ERR_SPEC_CHANGE_ORDER_NOT_FOUND", "No spec change order with id %s." % order_id)
    return row


def find_review(review_id):
    row = db.period_reviews.get(review_id)
    if row is None:
        fail("ERR_PERIOD_REVIEW_NOT_FOUND", "No menu period review with id %s." % review_id)
    return row


def find_campaign(campaign_id):
    row = db.lto_campaigns.get(campaign_id)
    if row is None:
        fail("ERR_LTO_NOT_FOUND", "No LTO campaign with id %s." % campaign_id)
    return row
