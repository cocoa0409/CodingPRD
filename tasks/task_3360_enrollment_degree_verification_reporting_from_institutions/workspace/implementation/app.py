"""Enrollment Verification Clearinghouse API — Flask entry point.

Boots from a fresh process with an empty in-memory store; the logical clock
reads exactly 2026-09-01T00:00:00Z until advanced (PRD §2.4).
"""
import os

from flask import Flask

import r_clock
import r_corrections
import r_degrees
import r_enrollment
import r_institutions
import r_notifications
import r_research
import r_requesters
import r_students
import r_verification
from core import ApiError, error_response

app = Flask(__name__)
app.json.sort_keys = False

for module in (
    r_institutions,
    r_enrollment,
    r_corrections,
    r_degrees,
    r_requesters,
    r_verification,
    r_students,
    r_notifications,
    r_research,
    r_clock,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_err):
    return error_response(ApiError(("ERR_VALIDATION", 404), "route not found"))


@app.errorhandler(405)
def _handle_405(_err):
    return error_response(ApiError(("ERR_VALIDATION", 405), "method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(("ERR_VALIDATION", 500), "internal error: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
