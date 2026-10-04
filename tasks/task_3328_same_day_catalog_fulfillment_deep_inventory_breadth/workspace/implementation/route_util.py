"""Shared glue for the route layer: auth gating and list responses.

Every route runs the same first two validation priorities (PRD section 2.9):
authentication, then authorization. The path template passed to `gate` is the
key into auth.PERMISSIONS, so the template must match the registration
decorator exactly.
"""

from auth import authorize, identify
from common import page, pagination
from response import ok_array


def gate(method, template):
    """Priorities 1 and 2; returns (user_id, role) for ownership checks."""
    user_id, role = identify()
    authorize(role, method, template)
    return user_id, role


def paginated(rows, serializer):
    """Apply declared pagination, order deterministically, wrap as an array."""
    limit, offset = pagination()
    window, total = page(rows, limit, offset)
    return ok_array([serializer(row) for row in window], limit, offset, total)