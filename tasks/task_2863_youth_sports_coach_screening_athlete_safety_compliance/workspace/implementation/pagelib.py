"""List paging helper (PRD section 2.3)."""

import envelope
import validate


def page(rows, serializer, args):
    limit, offset = validate.pagination(args)
    total_count = len(rows)
    window = rows[offset:offset + limit]
    return envelope.listing([serializer(r) for r in window], limit, offset, total_count)


def match(row, args, field, param=None):
    """Optional equality filter on a query parameter."""
    value = args.get(param or field)
    if value is None or value == "":
        return True
    return row.get(field) == value
