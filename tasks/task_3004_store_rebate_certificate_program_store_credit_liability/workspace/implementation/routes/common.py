"""Shared route helpers."""

from middleware import pagination
from response import collection_response


def paginated(records, projector):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return collection_response([projector(r) for r in page],
                               limit, offset, total)
