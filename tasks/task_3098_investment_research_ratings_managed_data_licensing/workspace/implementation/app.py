"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
import routes_research
import routes_licensing

app = Flask(__name__)
app.register_blueprint(routes_research.bp)
app.register_blueprint(routes_licensing.bp)


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(_err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Never leak stack traces; malformed requests surface as ERR_VALIDATION.
    return error_response("ERR_VALIDATION", 400, f"Malformed request: {err}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
