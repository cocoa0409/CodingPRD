"""Flask app object, in-memory stores and row plumbing.

Storage is in-memory only: every dict below is rebuilt empty on process start,
so a fresh `start.sh` boot always begins with an empty database.
"""

import uuid

from flask import Flask, jsonify, request

import clock
from errors import ApiError, fail
from response import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False

STORE_KEYS = [
    "schools",
    "course_audits",
    "students",
    "exam_orders",
    "exam_registrations",
    "accommodation_requests",
    "alternate_exam_requests",
    "exam_scores",
    "readers",
    "material_shipments",
    "score_sends",
    "irregularity_cases",
]

DB = {key: {} for key in STORE_KEYS}
_SEQ = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def insert(store_key, row):
    """Stamp a new row with the common fields and store it."""
    row["id"] = new_id()
    stamp = clock.now_iso()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = _next_seq()
    DB[store_key][row["id"]] = row
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by 1."""
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def get(store_key, rid):
    if not isinstance(rid, str):
        return None
    return DB[store_key].get(rid)


def require(store_key, rid):
    row = get(store_key, rid)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "No %s with id %s." % (store_key, rid))
    return row


def rows(store_key):
    return list(DB[store_key].values())


def ordered(items):
    """created_at ascending, with insertion order as the stable tie-break."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def filtered(store_key, **criteria):
    out = []
    for row in rows(store_key):
        if all(row.get(k) == v for k, v in criteria.items() if v is not None):
            out.append(row)
    return ordered(out)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def require_field(payload, name):
    value = payload.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return value


def enum_field(payload, name, allowed, required=True, default=None):
    value = payload.get(name, default)
    if value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def int_field(payload, name, required=True, default=None, minimum=None, maximum=None):
    value = payload.get(name, default)
    if value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def number_field(payload, name, required=True, default=None, minimum=None, maximum=None):
    value = payload.get(name, default)
    if value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    value = float(value)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def bool_field(payload, name, default=False):
    value = payload.get(name, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def str_field(payload, name, required=True, default=None):
    value = payload.get(name, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def _handle_404(_exc):
    return jsonify(error_body("ERR_RESOURCE_NOT_FOUND", "No such endpoint.")), 404


@app.errorhandler(405)
def _handle_405(_exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed for this endpoint.")), 405


@app.errorhandler(500)
def _handle_500(_exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Internal server error.")), 500
