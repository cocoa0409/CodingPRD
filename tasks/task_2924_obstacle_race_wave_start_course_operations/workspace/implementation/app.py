"""Obstacle Course Racing wave-start and course operations service.

Boots a completely empty in-memory world on every process start: no seeding,
no persistence, no disk state of any kind (PRD 2.5).
"""

import os

from flask import Flask, jsonify

import db
import response
from errors import ApiError
from routes import (
    courses,
    divisions,
    entries,
    obstacles,
    participants,
    permits,
    restoration,
    staff,
    venues,
    waves,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    db.reset()

    for module in (
        venues,
        permits,
        courses,
        obstacles,
        divisions,
        waves,
        participants,
        entries,
        staff,
        restoration,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this resource.", 405
        )

    @app.errorhandler(400)
    def _bad_request(_exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return response.error_response(
            "ERR_INTERNAL", "The service failed to process the request.", 500
        )

    @app.get("/ocr/_health")
    def _health():
        return jsonify({"status": "ok", "current_utc": db.iso(db.now())}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, use_reloader=False)
