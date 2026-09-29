"""Collection reads: ordering, pagination and the array envelope (PRD 2.3)."""
import db
import response
import validate


def respond(records, serializer, descending=False, key=None):
    limit, offset = validate.pagination()
    if key is not None:
        items = sorted(records, key=key)
    else:
        items = db.ordered(records, descending)
    total_count = len(items)
    page = items[offset : offset + limit]
    return response.collection([serializer(r) for r in page], limit, offset, total_count)
