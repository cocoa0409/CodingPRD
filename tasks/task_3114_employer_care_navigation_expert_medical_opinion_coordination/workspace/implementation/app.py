"""Application entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from common import error_envelope
import routes_core
import routes_nav
import routes_records
import routes_claims

app = Flask(__name__)
app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_nav.bp)
app.register_blueprint(routes_records.bp)
app.register_blueprint(routes_claims.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_envelope(err)


@app.errorhandler(404)
def handle_404(err):
    return error_envelope(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_envelope(ApiError("ERR_NOT_FOUND", 404, "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_envelope(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
