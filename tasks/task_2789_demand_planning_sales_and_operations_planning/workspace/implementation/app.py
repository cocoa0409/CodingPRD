"""Demand Planning & S&OP API -- entry point.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded. Every entity is built by callers through the declared endpoints.
"""
import os

from flask import Flask

from envelope import respond_error
from errors import ERROR_HTTP, ApiError
from routes.accuracy import bp as accuracy_bp
from routes.adjustments import bp as adjustments_bp
from routes.capacity import bp as capacity_bp
from routes.clock import bp as clock_bp
from routes.cycles import bp as cycles_bp
from routes.forecasts import bp as forecasts_bp
from routes.master import bp as master_bp
from routes.promotions import bp as promotions_bp
from routes.scenarios import bp as scenarios_bp
from routes.supply import bp as supply_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (master_bp, capacity_bp, promotions_bp, cycles_bp,
                  forecasts_bp, adjustments_bp, supply_bp, scenarios_bp,
                  accuracy_bp, clock_bp):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return respond_error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(400)
def handle_400(exc):
    return respond_error("ERR_INVALID_REQUEST", "Malformed request", 400)


@app.errorhandler(404)
def handle_404(exc):
    return respond_error("ERR_NOT_FOUND", "No such route",
                         ERROR_HTTP["ERR_NOT_FOUND"])


@app.errorhandler(405)
def handle_405(exc):
    return respond_error("ERR_METHOD_NOT_ALLOWED", "Method not allowed",
                         ERROR_HTTP["ERR_METHOD_NOT_ALLOWED"])


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unhandled error")
    return respond_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc,
                         500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
