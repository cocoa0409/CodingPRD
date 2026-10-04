"""Error types and standard response envelope helpers."""
import flask

import db


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, status):
    raise ApiError(error_id, message, status)


def meta_base():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": meta_base(),
        "response_type": response_type,
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return flask.make_response(flask.jsonify(body), status)


def error_response(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return flask.make_response(flask.jsonify(body), e.http_status)


def get_json_body():
    """Return request JSON object; {} when body absent. 400 on malformed/非-object."""
    raw = flask.request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = flask.request.get_json(force=True, silent=False)
    except Exception:
        err("ERR_INVALID_REQUEST", "Request body is not valid JSON.", 400)
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            err("ERR_INVALID_REQUEST", "Missing required field: %s" % f, 400)


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, "|".join(allowed)), 400)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field, 400)
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", "Field %s must be >= %d." % (field, minimum), 400)
    return v


def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0."""
    args = flask.request.args
    try:
        limit = int(args.get("limit", "10"))
    except ValueError:
        err("ERR_INVALID_REQUEST", "limit must be an integer.", 400)
    try:
        offset = int(args.get("offset", "0"))
    except ValueError:
        err("ERR_INVALID_REQUEST", "offset must be an integer.", 400)
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.", 400)
    if offset < 0:
        err("ERR_INVALID_REQUEST", "offset must be >= 0.", 400)
    return limit, offset


def list_response(items, limit, offset):
    items_sorted = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return success(
        page,
        status=200,
        response_type="array",
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + limit < total,
        },
    )


def stamp_new(record, with_version=True):
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = db.now_iso()
