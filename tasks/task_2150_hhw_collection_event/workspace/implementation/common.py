"""Shared route helpers: posture gates and filtered list handling."""

from envelope import ok_list, paginate, parse_pagination
from errors import ApiError
from rollups import effective_posture
from store import ordered


def gate_frozen(program):
    """Ladder rung 14 — the program must not be frozen."""
    if program is not None and effective_posture(program) == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN")


def gate_restricted(program):
    """Ladder rung 15 — the program must be fully open."""
    if program is not None and effective_posture(program) != "OPEN":
        raise ApiError("ERR_PROGRAM_RESTRICTED")


def list_response(args, rows, serializer, filters=None):
    """List endpoints: validate pagination first (rung 3), then filter, order
    by created_at ascending and page."""
    limit, offset = parse_pagination(args)
    selected = []
    for row in ordered(rows):
        keep = True
        for field, wanted in (filters or {}).items():
            if wanted is None:
                continue
            value = row.get(field)
            if value is None:
                keep = False
                break
            if str(value) != str(wanted):
                keep = False
                break
        if keep:
            selected.append(row)
    page, total = paginate(selected, limit, offset)
    return ok_list([serializer(row) for row in page], limit, offset, total)
