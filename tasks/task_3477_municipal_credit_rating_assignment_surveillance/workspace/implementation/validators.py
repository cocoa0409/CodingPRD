"""Request well-formedness helpers (validation priority 4) and existence
lookups (priority 3). Error IDs and statuses come from errors.py."""
from flask import request

import timeutil
from errors import (
    ERR_APPEAL_NOT_FOUND,
    ERR_BOND_SALE_NOT_FOUND,
    ERR_CRITERIA_VERSION_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ISSUER_NOT_FOUND,
    ERR_OBLIGATION_NOT_FOUND,
    ERR_RATING_NOT_FOUND,
    ERR_REVIEW_ITEM_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_UNDERWRITER_NOT_FOUND,
    raise_err,
)
from store import db


def body():
    """The JSON request body as a dict; anything else behaves as {}."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def present(body_dict, field):
    return field in body_dict and body_dict[field] is not None


def require_fields(body_dict, fields):
    for field in fields:
        if not present(body_dict, field):
            raise_err(ERR_INVALID_REQUEST, "required field missing: %s" % field)


def require_enum(body_dict, field, allowed):
    value = body_dict.get(field)
    if value not in allowed:
        raise_err(
            ERR_INVALID_REQUEST,
            "field %s must be one of %s" % (field, ", ".join(allowed)),
        )
    return value


def optional_enum(body_dict, field, allowed):
    if not present(body_dict, field):
        return None
    return require_enum(body_dict, field, allowed)


def require_int(body_dict, field):
    value = body_dict.get(field)
    if not is_int(value):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % field)
    return value


def optional_int(body_dict, field, default=None):
    if not present(body_dict, field):
        return default
    return require_int(body_dict, field)


def require_datetime(body_dict, field):
    value = body_dict.get(field)
    dt = timeutil.parse_iso(value)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "field %s must be an ISO 8601 timestamp" % field)
    return dt


# --- existence lookups (priority 3) -----------------------------------------

def get_issuer(issuer_id):
    ent = db.issuers.get(issuer_id)
    if ent is None:
        raise_err(ERR_ISSUER_NOT_FOUND, "issuer not found: %s" % issuer_id)
    return ent


def get_underwriter(underwriter_id):
    ent = db.underwriters.get(underwriter_id)
    if ent is None:
        raise_err(ERR_UNDERWRITER_NOT_FOUND, "underwriter not found: %s" % underwriter_id)
    return ent


def get_engagement(engagement_id):
    ent = db.engagements.get(engagement_id)
    if ent is None:
        raise_err(ERR_ENGAGEMENT_NOT_FOUND, "engagement not found: %s" % engagement_id)
    return ent


def get_criteria_version(criteria_version_id):
    ent = db.criteria_versions.get(criteria_version_id)
    if ent is None:
        raise_err(ERR_CRITERIA_VERSION_NOT_FOUND, "criteria version not found: %s" % criteria_version_id)
    return ent


def get_session(session_id):
    ent = db.sessions.get(session_id)
    if ent is None:
        raise_err(ERR_SESSION_NOT_FOUND, "committee session not found: %s" % session_id)
    return ent


def get_rating(rating_id):
    ent = db.ratings.get(rating_id)
    if ent is None:
        raise_err(ERR_RATING_NOT_FOUND, "rating not found: %s" % rating_id)
    return ent


def get_appeal(appeal_id):
    ent = db.appeals.get(appeal_id)
    if ent is None:
        raise_err(ERR_APPEAL_NOT_FOUND, "appeal not found: %s" % appeal_id)
    return ent


def get_obligation(obligation_id):
    ent = db.obligations.get(obligation_id)
    if ent is None:
        raise_err(ERR_OBLIGATION_NOT_FOUND, "disclosure obligation not found: %s" % obligation_id)
    return ent


def get_bond_sale(bond_sale_id):
    ent = db.bond_sales.get(bond_sale_id)
    if ent is None:
        raise_err(ERR_BOND_SALE_NOT_FOUND, "bond sale not found: %s" % bond_sale_id)
    return ent


def get_review_item(review_item_id):
    ent = db.review_items.get(review_item_id)
    if ent is None:
        raise_err(ERR_REVIEW_ITEM_NOT_FOUND, "review item not found: %s" % review_item_id)
    return ent
