"""List read helper: filter -> order created_at DESC -> paginate -> project."""

from envelope import listing
from serializers import dump_all
from shapes import pagination
from store import sort_desc


def paged(records):
    """Ladder step 8 then the standard ordered, paginated array response."""
    limit, offset = pagination()
    ordered = sort_desc(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return listing(dump_all(page), limit, offset, total)
