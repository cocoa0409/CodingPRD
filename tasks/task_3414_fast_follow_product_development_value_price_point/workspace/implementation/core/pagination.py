"""Offset pagination (PRD 2.3) and the shared list-endpoint pipeline.

limit: page size, default 10, min 1, max 100. offset: records skipped,
default 0. Lists sort by created_at ascending (insertion order breaks ties on
a shared logical-clock instant). meta carries limit, offset, total_count,
has_more.
"""
from flask import request

from core.constants import (
    PAGE_DEFAULT_LIMIT,
    PAGE_DEFAULT_OFFSET,
    PAGE_MAX_LIMIT,
    PAGE_MIN_LIMIT,
)
from core.envelope import success_list
from core.errors import bad_request


def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("query parameter 'limit' must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise bad_request(
                "query parameter 'limit' must be between %d and %d"
                % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT)
            )
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("query parameter 'offset' must be >= 0")
    return limit, offset


def list_response(records, filters, serializer):
    """filters: dict of query-param name -> record field name. Records are
    filtered by exact match, sorted by (created_at, insertion seq), paginated,
    and serialized."""
    limit, offset = page_params()
    items = list(records)
    for param, field in filters.items():
        wanted = request.args.get(param)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)
