"""Actuarial Exam Progression API — application wiring.

All resources are mounted under /actuarial. The store is in-memory and starts
empty on every boot (per-test-server isolation re-launches this process before
every test). Listens on $PORT (default 10000), bound to 0.0.0.0, foreground.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from helpers import error_envelope

import domains_clock
import domains_candidates
import domains_syllabus
import domains_windows
import domains_registrations
import domains_vee
import domains_tracks
import domains_projects
import domains_course
import domains_transfer
import domains_cpd
import domains_discipline
import domains_credentials

API_PREFIX = "/actuarial"

_BLUEPRINTS = [
    domains_clock.bp,
    domains_candidates.bp,
    domains_syllabus.bp,
    domains_windows.bp,
    domains_registrations.bp,
    domains_vee.bp,
    domains_tracks.bp,
    domains_projects.bp,
    domains_course.bp,
    domains_transfer.bp,
    domains_cpd.bp,
    domains_discipline.bp,
    domains_credentials.bp,
]


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return jsonify(error_envelope(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def _handle_404(err):
        return jsonify(error_envelope("ERR_NOT_FOUND",
                                      "path does not resolve")), 404

    @app.errorhandler(405)
    def _handle_405(err):
        return jsonify(error_envelope("ERR_METHOD_NOT_ALLOWED",
                                      "method not allowed")), 405

    @app.errorhandler(HTTPException)
    def _handle_http(err):
        return jsonify(error_envelope("ERR_HTTP_%s" % (err.code or 500),
                                      err.description)), (err.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return jsonify(error_envelope(err.error_id, err.message)), err.http_status
        return jsonify(error_envelope("ERR_INTERNAL", str(err))), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
