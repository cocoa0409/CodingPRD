"""Shared route helpers: path-resource resolution and ownership checks."""

import db
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_STALE_VERSION,
    ApiError,
)


def must_get(table, row_id, label):
    """Check 3: every path resource must exist (validated left to right)."""
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND, "%s %s does not exist" % (label, row_id), 404)
    return row


def must_get_body(table, row_id, field):
    """Check 4: a body-supplied foreign key must resolve to a row."""
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(ERR_NOT_FOUND, "%s '%s' does not resolve to an existing row" % (field, row_id), 404)
    return row


def require_owner(actor, owner_id, label):
    """Check 8: an entity-backed actor must own the target row."""
    if actor["role"] in ("Student", "Partner") and actor["user_id"] != owner_id:
        raise ApiError(ERR_NOT_OWNER, "%s is not owned by the acting user" % label, 403)
    return True


def require_version(expected, actual, label):
    """Check 27: the optimistic-concurrency guard on partner writes."""
    if int(expected) != int(actual):
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_partner_version %s does not match the %s's current version %s"
            % (expected, label, actual),
            412,
        )


def terminal(error_message):
    raise ApiError(ERR_ALREADY_TERMINAL, error_message, 409)
