"""Flask application entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.clock import bp as clock_bp
from routes.projects import bp as projects_bp
from routes.esas import bp as esas_bp
from routes.milestones import bp as milestones_bp
from routes.permits import bp as permits_bp
from routes.tests import bp as tests_bp
from routes.augmentations import bp as augmentations_bp
from routes.ltsas import bp as ltsas_bp
from routes.orders import bp as orders_bp
from routes.claims import bp as claims_bp
from routes.bids import bp as bids_bp

for bp in (clock_bp, projects_bp, esas_bp, milestones_bp, permits_bp, tests_bp,
           augmentations_bp, ltsas_bp, orders_bp, claims_bp, bids_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
