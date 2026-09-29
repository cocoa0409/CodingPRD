"""Device Installment Upgrade Program API (PRD.md).

Entry point: registers every blueprint, runs the authentication band of the
validation ladder before each request, and renders every rejection through the
error envelope of PRD 2.2.  Storage is in-memory only and starts empty on every
boot -- nothing is ever seeded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from middleware import authenticate
from routes import applications, catalog, customers, devices, loans, postings
from routes import servicing, tradeins, upgrades

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for blueprint in (customers.bp, catalog.bp, applications.bp, loans.bp,
                  postings.bp, devices.bp, upgrades.bp, tradeins.bp,
                  servicing.bp):
    app.register_blueprint(blueprint)


@app.before_request
def _before():
    db.begin_request()
    authenticate()


@app.errorhandler(ApiError)
def _api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return response.error_response(
            "ERR_INVALID_REQUEST", "The requested resource path does not exist.", 404)
    if exc.code == 405:
        return response.error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed on this path.", 405)
    return response.error_response(
        "ERR_INVALID_REQUEST", exc.description or "Request could not be processed.",
        exc.code or 400)


@app.errorhandler(Exception)
def _unhandled(exc):  # pragma: no cover - defensive
    return response.error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
