"""Reemployment Rights Case Handling & Employer Outreach API — entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from store import db
from util import error_body

import routes_clock
import routes_parties
import routes_ombudsmen
import routes_service_periods
import routes_cases
import routes_analysis
import routes_rounds
import routes_notes
import routes_referrals
import routes_recognition
import routes_events

app = Flask(__name__)

for bp in (
    routes_clock.bp,
    routes_parties.bp,
    routes_ombudsmen.bp,
    routes_service_periods.bp,
    routes_cases.bp,
    routes_analysis.bp,
    routes_rounds.bp,
    routes_notes.bp,
    routes_referrals.bp,
    routes_recognition.bp,
    routes_events.bp,
):
    app.register_blueprint(bp)


@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    db.lock.release()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def _handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def _handle_405(e):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed")), 405


@app.errorhandler(Exception)
def _handle_exception(e):
    return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
