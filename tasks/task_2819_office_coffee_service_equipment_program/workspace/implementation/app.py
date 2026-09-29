"""Office Coffee Service & Equipment Program API.

Boots a fresh, entirely in-memory server on every invocation: no collection is ever
seeded, preloaded or read back from disk, so a newly started process answers every
listing with an empty page.
"""
import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError
from routes import (accounts, adjustments, catalog, invoicelines, invoices, parlevels,
                    placements, sites, testing, visits, workorders)

BLUEPRINTS = (
    testing.bp,
    catalog.bp,
    accounts.bp,
    sites.bp,
    parlevels.bp,
    placements.bp,
    visits.bp,
    workorders.bp,
    invoices.bp,
    invoicelines.bp,
    adjustments.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "No such endpoint.")), 404

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this endpoint.")), 405

    @app.errorhandler(400)
    def _bad_request(exc):
        return jsonify(error_body("ERR_VALIDATION", "The request could not be parsed.")), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        return jsonify(error_body("ERR_INTERNAL", str(exc) or "Internal error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
