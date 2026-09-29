"""Institutional Research Federal Data Reporting API — entry point.

The in-memory store starts empty on every boot: no entity is seeded, preloaded or
hardcoded here. Tests build all state through the declared endpoints.
"""
import os

from flask import Flask, jsonify

from auth import authenticate, require_roles
from db import store
from errors import ApiError
from response import error_body, ok
from routes_cohort import bp as cohort_bp
from routes_component import bp as component_bp
from routes_cycle import bp as cycle_bp
from routes_disclosure import bp as disclosure_bp
from routes_external import bp as external_bp
from routes_library import bp as library_bp
from routes_pub import bp as publication_bp
from util import parse_instant
from validation import get_body, req_instant

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (cycle_bp, component_bp, cohort_bp, library_bp, external_bp,
                  publication_bp, disclosure_bp):
    app.register_blueprint(blueprint, url_prefix="/ir")


@app.before_request
def _authenticate():
    """Priority 1 runs ahead of routing resolution, per PRD 2.12."""
    authenticate()


@app.post("/_clock/set_current_utc")
def set_clock():
    """Test-driving endpoint for the logical clock of PRD 2.5. Mutates no business row."""
    require_roles()
    body = get_body()
    value = req_instant(body, "to_iso8601")
    store.clock = parse_instant(value)
    return ok({"current_utc": store.now_iso()})


@app.errorhandler(ApiError)
def _api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def _not_found(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "no such route")), 404


@app.errorhandler(405)
def _method_not_allowed(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST",
                              "the method is not allowed for this route")), 405


@app.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, ApiError):
        return _api_error(exc)
    app.logger.exception("unhandled error")
    return jsonify(error_body("ERR_INVALID_REQUEST", "unexpected server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
