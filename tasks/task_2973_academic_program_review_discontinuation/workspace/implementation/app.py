"""Provost Review API — application entry point.

Storage is process memory only (see store.py), so a fresh process always
starts with an empty portfolio and the logical clock at its mandatory startup
default of 2026-08-01T00:00:00Z.
"""

import os
from datetime import datetime
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider

import envelope
import r_cycles
import r_decisions
import r_faculty
import r_misc
import r_plans
import r_programs
import r_reviewers
import r_selfstudy
import r_students
from errors import ApiError
from store import iso


class Provider(DefaultJSONProvider):
    sort_keys = False

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return iso(value)
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__)
    app.json = Provider(app)

    for module in (r_misc, r_programs, r_cycles, r_selfstudy, r_reviewers,
                   r_decisions, r_plans, r_students, r_faculty):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return envelope.error_response(
            ApiError("ERR_VALIDATION", "No such route."))

    @app.errorhandler(405)
    def handle_method(_err):
        return envelope.error_response(
            ApiError("ERR_VALIDATION", "Method not allowed for this route."))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err)
        body = {
            "meta": envelope._meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL",
                     "message": "Unexpected server error: %s" % err},
        }
        return body, 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
