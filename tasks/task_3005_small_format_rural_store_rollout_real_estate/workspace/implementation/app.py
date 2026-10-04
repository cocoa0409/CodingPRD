"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes_programs import bp as programs_bp
from routes_stores import bp as stores_bp
from routes_distribution import bp as distribution_bp
from routes_capital import bp as capital_bp

app = Flask(__name__)

app.register_blueprint(programs_bp)
app.register_blueprint(stores_bp)
app.register_blueprint(distribution_bp)
app.register_blueprint(capital_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "method not allowed", 404)


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
