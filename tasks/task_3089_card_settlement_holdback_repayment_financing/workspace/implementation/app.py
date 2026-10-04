"""Flask entry point for the card-settlement holdback financing API."""
import os

from flask import Flask

from core import ApiError, error_body
from routes import bp

app = Flask(__name__)
app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e)


@app.errorhandler(404)
def handle_404(e):
    return error_body(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_body(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_body(e)
    return error_body(ApiError("ERR_INVALID_REQUEST", str(e), 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
