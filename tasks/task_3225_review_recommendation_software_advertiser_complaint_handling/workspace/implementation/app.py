"""Flask application entry point."""
import os
from flask import Flask, jsonify

from errors import ApiError
from response import err_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_core
import routes_pages
import routes_reviews
import routes_claims
import routes_ads
import routes_ad_events
import routes_complaints
import routes_cases
import routes_alerts
import routes_identity
import routes_merges

for mod in (routes_core, routes_pages, routes_reviews, routes_claims,
            routes_ads, routes_ad_events, routes_complaints, routes_cases,
            routes_alerts, routes_identity, routes_merges):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_INVALID_REQUEST", 400, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
