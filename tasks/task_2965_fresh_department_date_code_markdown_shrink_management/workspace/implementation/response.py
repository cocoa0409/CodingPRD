"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

from db import db
from util import fmt_instant

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(db.now()),
    }


def public(record):
    """Strip internal bookkeeping keys before serialisation."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(page, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page)) < total_count
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
