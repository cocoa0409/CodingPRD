"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask

import errors
from response import error_response
from routes import bp

app = Flask(__name__)
app.register_blueprint(bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(errors.not_found("Resource not found."))


@app.errorhandler(405)
def handle_405(err):
    return error_response(errors.not_found("Resource not found."))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return error_response(err)
    return error_response(errors.invalid_request(str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
