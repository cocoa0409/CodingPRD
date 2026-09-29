"""Refined Products Pipeline Nomination & Scheduling API — Flask entrypoint.

State lives entirely in process memory; every fresh boot starts empty and no
entity data is ever seeded.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, base_meta, respond_error
import routes_cycles
import routes_maintenance
import routes_master
import routes_nominations
import routes_settlements
import routes_tickets


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(routes_master.bp)
    app.register_blueprint(routes_cycles.bp)
    app.register_blueprint(routes_nominations.bp)
    app.register_blueprint(routes_tickets.bp)
    app.register_blueprint(routes_maintenance.bp)
    app.register_blueprint(routes_settlements.bp)

    @app.before_request
    def _prepare():
        g.bumped = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return respond_error("ERR_REFERENCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return respond_error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        return respond_error(error_id, exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return respond_error("ERR_INTERNAL", "Unexpected server error: {}".format(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
