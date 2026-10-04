"""Shared route helpers: ordering, filtering and paginated list responses."""

from http_util import pagination, q
from response import success_array


def ordered(rows):
    """List responses are ordered by creation timestamp ascending (PRD §2.3)."""
    return sorted(rows, key=lambda row: (row["created_at"], row["id"]))


def filtered(rows, **criteria):
    """Apply only the filters the caller actually supplied (None == absent)."""
    result = []
    for row in rows:
        keep = True
        for field, value in criteria.items():
            if value is None:
                continue
            if row.get(field) != value:
                keep = False
                break
        if keep:
            result.append(row)
    return result


def arg(name):
    return q(name)


def list_response(rows, serializer, has_limit=True):
    page = pagination(has_limit)
    total = len(rows)
    slice_ = page.slice(rows)
    return success_array(
        [serializer(row) for row in slice_], page.limit, page.offset, total)