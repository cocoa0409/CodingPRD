"""Entry point: blueprint registration, error handlers and the server bind.

The in-memory store starts empty on every boot -- nothing is seeded here.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import (batches, content, continuity, disputes, enrollments,
                    merges, passbacks, people, placements, rollovers, shells,
                    terms, testing, tools)

BLUEPRINTS = (
    terms.bp,
    people.bp,
    shells.bp,
    content.bp,
    enrollments.bp,
    batches.bp,
    merges.bp,
    rollovers.bp,
    tools.bp,
    placements.bp,
    passbacks.bp,
    disputes.bp,
    continuity.bp,
    testing.bp,
)

HTTP_ERROR_IDS = {
    400: "ERR_INVALID_REQUEST",
    401: "ERR_UNAUTHENTICATED",
    403: "ERR_ROLE_NOT_PERMITTED",
    404: "ERR_INVALID_REQUEST",
    405: "ERR_INVALID_REQUEST",
    415: "ERR_INVALID_REQUEST",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def on_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def on_http_error(exc):
        status = exc.code or 500
        error_id = HTTP_ERROR_IDS.get(status, "ERR_INVALID_REQUEST")
        message = exc.description or "The request could not be served."
        return jsonify(error_body(error_id, message)), status

    @app.errorhandler(Exception)
    def on_unexpected(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
