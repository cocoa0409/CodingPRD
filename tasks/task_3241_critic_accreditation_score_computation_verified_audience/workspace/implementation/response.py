"""Response envelope helpers (PRD 2.2 / 2.3) and entity serialization."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify
from db import _fmt_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _fmt_iso(datetime.now(timezone.utc)),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


# ---------------- entity serialization ----------------

def publication_view(p):
    return dict(p)


def critic_view(c):
    return dict(c)


def accreditation_review_view(r):
    return dict(r)


def title_view(t):
    return dict(t)


def release_view(rel, db):
    out = dict(rel)
    if out.get("audience_display_suspended"):
        out["audience_display"] = "SUSPENDED"
        out["audience_score_pct"] = None
    else:
        out["audience_display"] = "ACTIVE"
    return out


def review_view(r):
    return dict(r)


def audience_member_view(m):
    return dict(m)


def ticket_verification_view(t):
    return dict(t)


def audience_rating_view(r):
    return dict(r)


def score_snapshot_view(s):
    return dict(s)


def bombing_incident_view(i):
    return dict(i)


def dispute_view(d):
    return dict(d)
