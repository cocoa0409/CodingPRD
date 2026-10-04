"""Shared route plumbing: the auth gate and list-response assembly."""

import functools

from flask import request

import auth
from response import array_response, paginate, parse_pagination
from serializers import serialize, serialize_many
from services.changes import apply_time_triggered_transitions


def guard(roles):
    """Apply gate one (authentication) and gate two (authorization) before any
    business rule, then let any time-triggered transition whose precondition
    the current logical instant satisfies run."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            actor = auth.authenticate(request.headers)
            auth.authorize(actor, roles)
            apply_time_triggered_transitions()
            return view(actor, *args, **kwargs)
        return wrapper
    return decorator


def list_response(rows):
    """Pagination fields and envelope for a list endpoint.

    `rows` must already be in the endpoint's sort order; `total_count` is the
    size of the full matching set before pagination.
    """
    limit, offset = parse_pagination(request.args)
    window, total = paginate(rows, limit, offset)
    return array_response(serialize_many(window), limit, offset, total)


def one(record):
    return serialize(record)


def paging(rows):
    """Pagination parameters only, for endpoints that need the window itself."""
    limit, offset = parse_pagination(request.args)
    return paginate(rows, limit, offset), limit, offset