"""Logical clock endpoint (PRD §3.6, §4).

The server never reads wall-clock time: the clock starts fixed at
2026-09-01T00:00:00Z and only this endpoint moves it.
"""

import flask

import db
import response
from errors import fail
from middleware import require
from services import cascades


def register_routes(app):

    @app.route("/_clock/set_current_utc", methods=["POST"])
    @require(["AccreditationBody"])
    def set_current_utc(principal):
        payload = common_body()
        if "current_utc" not in payload or payload["current_utc"] is None:
            fail("ERR_INVALID_REQUEST", "missing required field: current_utc")
        supplied = payload["current_utc"]
        try:
            db.parse_ts(supplied)
        except Exception:
            fail("ERR_INVALID_REQUEST", "current_utc is not a valid instant")
        db.set_clock(supplied if isinstance(supplied, str) else db.fmt_ts(supplied))
        cascades.run_clock_cascades()
        return response.ok({
            "current_utc": db.current_utc_string(),
            "default_utc": db.default_utc_string(),
        })


def common_body():
    payload = flask.request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}