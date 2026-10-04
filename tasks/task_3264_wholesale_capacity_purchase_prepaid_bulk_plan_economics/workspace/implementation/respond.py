"""Response helpers producing the scaffold's fixed envelope."""

import store


def ok(data, status=200):
    body = {
        "meta": {
            "api_request_id": "req_" + _rid(),
            "api_request_timestamp": store.now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return body, status


def created(data):
    return ok(data, 201)


def listing(kind, records, limit, offset):
    window, pagination = store.paginate(records, limit, offset)
    body = {
        "meta": {
            "api_request_id": "req_" + _rid(),
            "api_request_timestamp": store.now_iso(),
            "limit": pagination["limit"],
            "offset": pagination["offset"],
            "total_count": pagination["total_count"],
            "has_more": pagination["has_more"],
        },
        "response_type": "array",
        "data": store.serialize_many(kind, window),
    }
    return body, 200


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": "req_" + _rid(),
            "api_request_timestamp": store.now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _rid():
    import uuid
    return uuid.uuid4().hex[:20].upper()