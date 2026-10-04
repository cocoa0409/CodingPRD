"""App entry point: Flask app, error handlers, route registration."""
import os
import traceback
from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.delivery_years import bp as dy_bp
from routes.owners import bp as owners_bp
from routes.resources import bp as resources_bp
from routes.accreditations import bp as acc_bp
from routes.auction_runs import bp as runs_bp
from routes.offers import bp as offers_bp
from routes.commitments import bp as commits_bp
from routes.events import bp as events_bp
from routes.measurements import bp as meas_bp
from routes.clock import bp as clock_bp

for bp in (dy_bp, owners_bp, resources_bp, acc_bp, runs_bp, offers_bp,
           commits_bp, events_bp, meas_bp, clock_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found.", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found.", 404))


@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", str(e), 400))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
