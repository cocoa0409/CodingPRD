"""Automation Task Metering, Partner Integration Review & Error Replay API.

Entry point: registers the /zapier blueprints, installs the error handlers and
runs the Flask server on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask, request

from clock import Clock
from errors import ApiError
from response import error_body, success
from routes import ALL_BLUEPRINTS

app = Flask(__name__)

# The logical clock always starts at exactly 2026-09-01T00:00:00Z and the store
# starts empty. Nothing is seeded; every entity is built through the API surface.
Clock.reset()

for blueprint in ALL_BLUEPRINTS:
    app.register_blueprint(blueprint, url_prefix="/zapier")


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(404)
def handle_not_found(exc):
    return error_body("ERR_ACCOUNT_NOT_FOUND", "No such route or resource."), 404


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_body("ERR_FORBIDDEN", "Method not allowed for this route."), 405


@app.errorhandler(500)
def handle_server_error(exc):
    return error_body("ERR_FORBIDDEN", "Internal server error."), 500


@app.route("/", methods=["GET"])
def root():
    return success({"service": "automation-task-metering", "prefix": "/zapier"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))