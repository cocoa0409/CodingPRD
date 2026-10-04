"""Flask app entry point: blueprint registration and error handling."""
import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)

import routes_base
import routes_catalog
import routes_audience
import routes_disputes

app.register_blueprint(routes_base.bp)
app.register_blueprint(routes_catalog.bp)
app.register_blueprint(routes_audience.bp)
app.register_blueprint(routes_disputes.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(500)
def handle_500(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Internal error", 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
