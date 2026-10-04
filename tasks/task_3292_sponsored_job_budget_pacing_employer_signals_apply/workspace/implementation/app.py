"""Flask application entry point: blueprint registration, error handling, boot."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request  # noqa: E402

from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.url_map.strict_slashes = False

# Every request starts from a clean per-request view only if a handler fails
# part-way; the store itself is process-local and rebuilt on every boot.
from db import restore, snapshot  # noqa: E402
from routes.applications import bp as applications_bp  # noqa: E402
from routes.assessments import bp as assessments_bp  # noqa: E402
from routes.campaigns import bp as campaigns_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402
from routes.employers import bp as employers_bp  # noqa: E402
from routes.job_postings import bp as job_postings_bp  # noqa: E402
from routes.job_seekers import bp as job_seekers_bp  # noqa: E402
from routes.sponsor_events import bp as sponsor_events_bp  # noqa: E402
from routes.sponsored_jobs import bp as sponsored_jobs_bp  # noqa: E402

API_PREFIX = "/api"

for blueprint in (employers_bp, job_seekers_bp, campaigns_bp, sponsored_jobs_bp,
                  job_postings_bp, assessments_bp, applications_bp,
                  sponsor_events_bp, clock_bp):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)


@app.before_request
def _stash_snapshot():
    """Take a rollback point so a mid-handler failure leaves no partial writes."""
    request.environ["_store_snapshot"] = snapshot()


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _handle_404(exc):
    return error_response("ERR_INVALID_REQUEST", "No such route.", 404)


@app.errorhandler(405)
def _handle_405(exc):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)


@app.errorhandler(500)
def _handle_500(exc):
    return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    snapshot_state = request.environ.get("_store_snapshot")
    if snapshot_state is not None:
        restore(snapshot_state)
    return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)


def _self_check():
    """Boot sanity check: no seeded rows, clock at the declared start."""
    from db import CLOCK_START, iso, store
    assert store.clock == __import__("db").parse_iso(CLOCK_START), "clock not at start"
    for table in ("employers", "job_seekers", "campaigns", "sponsored_jobs",
                  "job_postings", "applications", "sponsor_events", "budget_ledger",
                  "pacing_holds", "assessments", "job_alert_subscriptions",
                  "job_posting_versions", "apply_events"):
        assert len(getattr(store, table)) == 0, "table %s is not empty at boot" % table
    assert iso(store.clock) == "2026-09-01T00:00:00Z"


if __name__ == "__main__":
    _self_check()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)