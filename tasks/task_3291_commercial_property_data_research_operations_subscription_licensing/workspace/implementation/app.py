"""Flask application wiring, error handlers and startup (INSTRUCTION.md contract)."""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import core
import responses
import routes_analytics
import routes_deals
import routes_enforcement
import routes_licensing
import routes_listings
import routes_org
import routes_property
import routes_reports
import routes_sources
import routes_usage

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for blueprint in (
    routes_org.bp,
    routes_property.bp,
    routes_sources.bp,
    routes_deals.bp,
    routes_licensing.bp,
    routes_usage.bp,
    routes_enforcement.bp,
    routes_listings.bp,
    routes_analytics.bp,
    routes_reports.bp,
):
    app.register_blueprint(blueprint)

app.register_blueprint(routes_reports.clock_bp)


@app.errorhandler(core.ApiError)
def handle_api_error(error):
    return responses.error_body(error.error_id, error.message), error.http_status


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if error.code == 404:
        return responses.error_body("ERR_INVALID_REQUEST", error.description), 404
    if error.code == 405:
        return responses.error_body("ERR_INVALID_REQUEST", error.description), 405
    return responses.error_body("ERR_INVALID_REQUEST", error.description), error.code


@app.errorhandler(Exception)
def handle_unexpected(error):
    return responses.error_body("ERR_INVALID_REQUEST", str(error)), 400


@app.get("/_health")
def health():
    return responses.ok_object({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)