"""Flask app entry point: blueprint registration + error handlers."""
import os
from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)

import routes_platform
import routes_regions
import routes_contributors
import routes_listings
import routes_attempts
import routes_edits
import routes_tickets
import routes_reviews
import routes_cases
import services_hours
import routes_imagery
import routes_routing

for bp in (routes_platform.bp, routes_regions.bp, routes_contributors.bp,
           routes_listings.bp, routes_attempts.bp, routes_edits.bp,
           routes_tickets.bp, routes_reviews.bp, routes_cases.bp,
           services_hours.bp, routes_imagery.bp, routes_routing.bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "method not allowed", 404))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
