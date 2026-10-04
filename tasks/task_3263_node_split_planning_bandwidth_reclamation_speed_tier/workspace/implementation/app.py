"""Entry point: Flask app, error handlers, blueprint registration."""

import os

from flask import Flask

import db
from errors import ApiError
from response import error_response

app = Flask(__name__)

import routes_plant
import routes_capacity_actions
import routes_projects_waves
import routes_subscriber
import routes_complaints

app.register_blueprint(routes_plant.bp)
app.register_blueprint(routes_capacity_actions.bp)
app.register_blueprint(routes_projects_waves.bp)
app.register_blueprint(routes_subscriber.bp)
app.register_blueprint(routes_complaints.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError("ERR_VALIDATION", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
