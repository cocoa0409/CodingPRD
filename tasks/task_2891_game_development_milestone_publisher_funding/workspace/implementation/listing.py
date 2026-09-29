"""List-endpoint helpers: the pagination of PRD 2.3 applied to an ordered set."""

from envelope import collection
from validation import paging


def paged(rows, args, serializer):
    limit, offset = paging(args)
    return collection([serializer(row) for row in rows], limit, offset)


def matches(row, args, names):
    """Filter parameters are additive; a value matching nothing yields []."""
    for name in names:
        wanted = args.get(name)
        if wanted is None or wanted == "":
            continue
        if str(row.get(name)) != wanted:
            return False
    return True
