"""Response envelope construction (PRD 2.2, SCAFFOLD response_envelope)."""

from flask import jsonify

from util import format_utc, new_request_id


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_utc(_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _now():
    # The envelope timestamp is a server stamp, not the logical clock: the
    # logical clock governs business deadlines only.
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def ok(data, status=200, page_meta=None):
    envelope = {
        "meta": _meta(page_meta),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(envelope), status


def created(data):
    return ok(data, status=201)


def page(items, meta):
    return ok(items, status=200, page_meta=meta)


def empty(status=200):
    return ok({}, status=status)


def fail(error_id, message, status):
    envelope = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(envelope), status