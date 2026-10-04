"""Standard response envelope (§1.0 response_envelope / PRD §2.2).

Success:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "object" | "array", "data": {...} }
Error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": ..., "message": ... } }

List responses additionally carry limit / offset / total_count / has_more in
`meta` (§2.3). The error envelope's `meta` carries only the request id and
timestamp.
"""

from utils import now_iso, request_id


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return {"meta": _meta(), "response_type": "object", "data": data}, status


def list_response(rows, limit, offset, status=200):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })
    return {"meta": meta, "response_type": "array", "data": page}, status


def array_response(rows, status=200):
    """Unpaginated array body (sub-resource reads whose contract declares none)."""
    return {"meta": _meta(), "response_type": "array", "data": rows}, status


def empty_response(status=200):
    return {"meta": _meta(), "response_type": "object", "data": {}}, status


def error_response(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(rows, args, default_sort_key=None):
    """Slice a list for a paginated response.

    `limit` defaults to 10, min 1, max 100; `offset` defaults to 0 (§2.3).
    Rows come back ordered by creation timestamp ascending, oldest first,
    unless the listing is described otherwise.
    """
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
    if offset < 0:
        offset = 0

    ordered = list(rows)
    if default_sort_key is not None:
        ordered.sort(key=default_sort_key)
    return ordered[offset:offset + limit], limit, offset, len(ordered)