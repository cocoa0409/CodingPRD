"""Shared helpers for the route layer.

Each view resolves the actor from the request headers and checks the role
against the endpoint's declared roles before any business logic runs, which is
exactly the ordering PRD 2.11 fixes: authentication first, then role permission,
then payload inspection, then reference resolution, then the business cascade.
"""

from functools import wraps

from flask import request

from middleware import extract_actor, require_role
from response import (
    paginate,
    parse_pagination,
    success_array,
    success_object,
)
from services import public, public_list


class RawPayload:
    """Marks an already-shaped response payload.

    Summary and preview endpoints return computed views rather than entity
    records, so the wrapper emits them verbatim inside ``data`` instead of
    filtering them as entities.
    """

    def __init__(self, payload):
        self.payload = payload


def endpoint(roles, status=200):
    """Guard a view with the endpoint's role list and wrap its return value.

    The wrapped callable receives the resolved ``actor`` as its first argument
    and returns either a single record (wrapped as an ``object`` envelope) or a
    ``(records, params)`` pair for a paginated ``array`` envelope.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = extract_actor()
            require_role(actor, tuple(roles))
            result = fn(actor, *args, **kwargs)

            if isinstance(result, RawPayload):
                return success_object(result.payload), status

            if isinstance(result, tuple):
                records, params = result
                limit, offset = parse_pagination(params)
                page, total_count = paginate(records, limit, offset)
                return success_array(public_list(page), limit, offset, total_count), status

            if result is None:
                return success_object({}), status
            return success_object(public(result)), status

        return wrapper

    return decorator


def query_params():
    return request.args


def json_body():
    return request.get_json(silent=True)