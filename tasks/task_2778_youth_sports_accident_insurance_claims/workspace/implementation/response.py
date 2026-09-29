"""Response envelope helpers and the per-request mutation (version bump) set."""

from flask import g, jsonify

import db
import util
import serializers


# --------------------------------------------------- per-request dirty tracking

def _dirty():
    if not hasattr(g, "dirty_rows"):
        g.dirty_rows = {}
    return g.dirty_rows


def _fresh():
    if not hasattr(g, "fresh_rows"):
        g.fresh_rows = set()
    return g.fresh_rows


def mark_fresh(row):
    """Rows created during this request keep version 1 and are never bumped."""
    _fresh().add(row["id"])
    return row


def mark_dirty(row):
    """Record that this row changed; it gets exactly one version bump per request."""
    if row is None:
        return row
    if row["id"] in _fresh():
        row["updated_at"] = db.now_iso()
        return row
    _dirty()[row["id"]] = row
    return row


def commit_dirty():
    rows = _dirty()
    if not rows:
        return
    stamp = db.now_iso()
    for row in list(rows.values()):
        row["updated_at"] = stamp
        row["version"] = int(row["version"]) + 1
    g.dirty_rows = {}


# ------------------------------------------------------------------- envelope

def _meta(extra=None):
    meta = {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def respond_obj(row, status=200):
    commit_dirty()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serializers.serialize(row),
    }
    return jsonify(body), status


def respond_empty(status=200):
    commit_dirty()
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def respond_null(status=200):
    """2xx response whose declared output is null -> empty object per PRD 2.2."""
    return respond_empty(status)


def respond_list(rows, limit, offset, status=200):
    commit_dirty()
    total = len(rows)
    page = rows[offset:offset + limit]
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        }),
        "response_type": "array",
        "data": [serializers.serialize(r) for r in page],
    }
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
