"""Collection filtering, Driver narrowing and page assembly (PRD section 2.3)."""
import constants
import response
from errors import ApiError


def apply_filters(rows, args, specs):
    """`specs` is a sequence of (query_param, record_field, allowed_enum_or_None).

    A filter value outside the field's enumeration is ERR_INVALID_FIELD_VALUE.
    """
    for param, field, allowed in specs:
        raw = args.get(param)
        if raw is None:
            continue
        if allowed is not None and raw not in allowed:
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "Filter '%s' must be one of %s." % (param, ", ".join(allowed)),
            )
        rows = [r for r in rows if r.get(field) == raw]
    return rows


def narrow_to_driver(rows, role, user_id, field="driver_id"):
    """When the acting role is Driver every collection is narrowed to its own rows."""
    if role != constants.ROLE_DRIVER:
        return rows
    return [r for r in rows if r.get(field) == user_id]


def page(rows, args, serializer):
    limit, offset = response.pagination(args)
    window, total = response.paginate(rows, limit, offset)
    return response.list_response([serializer(r) for r in window], limit, offset, total)
