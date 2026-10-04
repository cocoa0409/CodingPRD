"""Flask entry point: blueprint registration, error handlers, server start."""
import os
from flask import Flask, jsonify

from errors import ApiError
from response import envelope_error

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope_error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return envelope_error("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return envelope_error("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return envelope_error(e.error_id, e.message, e.http_status)
    return envelope_error("ERR_INVALID_REQUEST", str(e), 400)


from routes.talents import bp as talents_bp
from routes.buyers import bp as buyers_bp
from routes.orders import bp as orders_bp
from routes.payouts import bp as payouts_bp
from routes.admin import bp as admin_bp

app.register_blueprint(talents_bp)
app.register_blueprint(buyers_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(payouts_bp)
app.register_blueprint(admin_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
