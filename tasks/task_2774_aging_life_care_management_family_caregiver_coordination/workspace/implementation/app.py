"""Aging Life Care Coordination API — entry point and error envelopes."""
import os

from flask import Flask, jsonify

import envelope
from errors import ApiError
from routes import assessments, authorizations, care_plans, clients
from routes import clock_admin, conferences, crisis, invoices, people
from routes import time_entries

BLUEPRINTS = (
    clients.bp,
    people.bp,
    assessments.bp,
    care_plans.bp,
    authorizations.bp,
    conferences.bp,
    crisis.bp,
    time_entries.bp,
    invoices.bp,
    clock_admin.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(envelope.error_body(exc.error_id, exc.message)), \
            exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(envelope.error_body(
            "ERR_NOT_FOUND", "No such route on this server.")), 404

    @app.errorhandler(405)
    def _bad_method(exc):
        return jsonify(envelope.error_body(
            "ERR_INVALID_REQUEST",
            "That method is not allowed on this route.")), 405

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        return jsonify(envelope.error_body(
            "ERR_INTERNAL", "The server failed to process the request.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
