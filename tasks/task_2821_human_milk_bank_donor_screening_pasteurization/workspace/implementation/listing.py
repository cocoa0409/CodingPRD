"""Query-string filtering shared by the list endpoints (PRD 2.3)."""

from flask import request


def apply_filters(rows, specs):
    """specs is a sequence of (query_param, row_key, kind) triples."""
    for param, key, kind in specs:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "int":
            try:
                wanted = int(raw)
            except (TypeError, ValueError):
                return []
            rows = [r for r in rows if r.get(key) == wanted]
        elif kind == "bool":
            lowered = raw.strip().lower()
            if lowered in ("true", "1"):
                wanted = True
            elif lowered in ("false", "0"):
                wanted = False
            else:
                return []
            rows = [r for r in rows if bool(r.get(key)) == wanted]
        else:
            rows = [r for r in rows if r.get(key) == raw]
    return rows


def sort_by(rows, keys):
    """Apply sort keys least-significant first so ties resolve as declared.

    `keys` is a sequence of (key_function, descending) pairs given in
    most-significant-first order.
    """
    for key_function, descending in reversed(keys):
        rows.sort(key=key_function, reverse=descending)
    return rows
