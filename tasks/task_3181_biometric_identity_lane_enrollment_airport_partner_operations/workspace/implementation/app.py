"""Flask entry point: error handlers + blueprint registration."""
import os

from flask import Flask

from errors import ApiError
from response import error

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(405)
def handle_405(exc):
    return error("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Never leak a bare 500 without the envelope.
    return error("ERR_INTERNAL", 500, "Internal server error")


import routes_admin
import routes_airports
import routes_kiosks
import routes_members
import routes_subscriptions
import routes_venues

app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_airports.bp)
app.register_blueprint(routes_kiosks.bp)
app.register_blueprint(routes_members.bp)
app.register_blueprint(routes_subscriptions.bp)
app.register_blueprint(routes_venues.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
