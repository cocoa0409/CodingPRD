"""Neighborhood Swim Club — Membership, Swim Team and Facility Operations API.

Flask application factory and the global error handlers.  Every route lives
under the /swim-club prefix (PRD §4).  All state is in-memory (see store.py):
a fresh process starts with an empty store and a logical clock reading exactly
2026-08-01T00:00:00.000Z.
"""
import os

from flask import Flask, jsonify

import clock
import envelope
import routes_book
import routes_deck
import routes_facility
import routes_seasons
import routes_team
from errors import ApiError
from store import DB

PREFIX = "/swim-club"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        routes_seasons,
        routes_book,
        routes_deck,
        routes_team,
        routes_facility,
    ):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.before_request
    def _open_request_scope():
        # A row's version advances by exactly one per request that changes it,
        # however many cascade hops reach it (PRD §2.4).
        DB.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error(
            "ERR_VALIDATION", "No such route on this API.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return envelope.error(
            "ERR_VALIDATION", "That method is not allowed on this route.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        return envelope.error("ERR_VALIDATION", "Unhandled server error: %s" % exc, 500)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "now": clock.now_iso()}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
