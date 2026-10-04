"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask

from errors import ApiError
from common import envelope_error, envelope_ok
import routes_core
import routes_ops

app = Flask(__name__)
app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body, status = envelope_error(err.error_id, err.message, err.http_status)
    return body, status


@app.errorhandler(404)
def handle_404(err):
    body, status = envelope_error("ERR_NOT_FOUND", "resource not found", 404)
    return body, status


@app.errorhandler(405)
def handle_405(err):
    body, status = envelope_error("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)
    return body, status


@app.errorhandler(Exception)
def handle_unexpected(err):
    body, status = envelope_error("ERR_INTERNAL", str(err), 500)
    return body, status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
