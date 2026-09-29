"""Response envelope helpers (PRD 2.2, 2.3, 2.4)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import g, jsonify

from store import fmt_instant, store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def public(record):
    """Serialize a stored record: drop private keys, JSON-ify Decimals."""
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --- version / updated_at bookkeeping ---------------------------------------
def touch(record, force=False):
    """Refresh updated_at and bump version at most once per HTTP request.

    PRD 2.9: every record touched anywhere in a cascade has its own
    updated_at refreshed and its own version incremented by 1.
    """
    record["updated_at"] = store.next_created_at()
    if "version" not in record:
        return record
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = record["id"]
    if force or key not in seen:
        record["version"] += 1
        seen.add(key)
    return record
