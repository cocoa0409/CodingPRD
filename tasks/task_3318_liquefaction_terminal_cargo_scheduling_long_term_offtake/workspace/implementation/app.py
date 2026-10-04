"""Entry point: Flask app, route registration, error handling."""
import os
from flask import Flask, jsonify

from errors import ApiError, error_response, fail
import routes_commercial
import routes_trains
import routes_adps
import routes_marine
import routes_gas

app = Flask(__name__)
app.register_blueprint(routes_commercial.bp)
app.register_blueprint(routes_trains.bp)
app.register_blueprint(routes_adps.bp)
app.register_blueprint(routes_marine.bp)
app.register_blueprint(routes_gas.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
