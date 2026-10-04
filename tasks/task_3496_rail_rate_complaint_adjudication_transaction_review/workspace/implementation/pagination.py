"""Pagination (PRD 2.3) and list ordering.

limit defaults to 10, min 1, max 100; offset defaults to 0. Results are sorted
by created_at ascending (oldest first), ties broken by creation sequence.
"""
from flask import request

from envelope import ok_list
from errors import api_err


def page_params():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        if not raw_limit.isdigit():
            raise api_err('ERR_INVALID_REQUEST', 'limit must be an integer between 1 and 100')
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise api_err('ERR_INVALID_REQUEST', 'limit must be an integer between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        if not raw_offset.isdigit():
            raise api_err('ERR_INVALID_REQUEST', 'offset must be an integer of at least 0')
        offset = int(raw_offset)
    return limit, offset


def sort_entities(items):
    return sorted(items, key=lambda e: (e['created_at'], e['_seq']))


def status_filter(items, allowed_statuses):
    status = request.args.get('status')
    if status is None:
        return items
    if status not in allowed_statuses:
        raise api_err('ERR_INVALID_REQUEST', 'status must be one of {}'.format(sorted(allowed_statuses)))
    return [e for e in items if e['status'] == status]


def paged(views, limit, offset):
    total = len(views)
    window = views[offset:offset + limit]
    return ok_list(window, limit, offset, total)
