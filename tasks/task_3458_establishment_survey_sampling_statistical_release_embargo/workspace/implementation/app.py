"""Establishment Survey Embargo API — Flask entry point.

All 40 business endpoints live under /survey; the logical-clock control is
mounted unprefixed at /_clock/set_current_utc. The store is in-memory and
starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask, jsonify

from envelope import err_body
from errors import ApiError

import store
from bp_programs import bp as programs_bp
from bp_frames import bp as frames_bp
from bp_establishments import bp as establishments_bp
from bp_enrollments import bp as enrollments_bp
from bp_cycles import bp as cycles_bp
from bp_reports import bp as reports_bp
from bp_followups import bp as followups_bp
from bp_estimates import bp as estimates_bp
from bp_seasonal import bp as seasonal_bp
from bp_benchmark import bp as benchmark_bp
from bp_notices import bp as notices_bp
from bp_releases import bp as releases_bp
from bp_outlets import bp as outlets_bp
from bp_grants import bp as grants_bp
from bp_clock import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    programs_bp, frames_bp, establishments_bp, enrollments_bp, cycles_bp,
    reports_bp, followups_bp, estimates_bp, seasonal_bp, benchmark_bp,
    notices_bp, releases_bp, outlets_bp, grants_bp,
):
    app.register_blueprint(bp, url_prefix="/survey")
app.register_blueprint(clock_bp)  # unprefixed by design


@app.before_request
def _acquire_lock():
    store.LOCK.acquire()


@app.teardown_request
def _release_lock(_exc):
    store.LOCK.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(err_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(_err):
    return jsonify(err_body("ERR_NOT_FOUND", "route not found")), 404


@app.errorhandler(405)
def handle_405(_err):
    return jsonify(err_body("ERR_METHOD_NOT_ALLOWED", "method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    app.logger.exception(err)
    return jsonify(err_body("ERR_INTERNAL", "internal server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
