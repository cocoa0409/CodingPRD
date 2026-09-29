"""Trade Promotion Deductions API.

Flask application factory and error envelope wiring.  All state lives in
process memory (see db.py) and the store is EMPTY on every boot: nothing is
seeded, preloaded or registered at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.allocations import bp as allocations_bp
from routes.analyses import bp as analyses_bp
from routes.audits import bp as audits_bp
from routes.deductions import bp as deductions_bp
from routes.documents import bp as documents_bp
from routes.ledger import bp as ledger_bp
from routes.programs import bp as programs_bp
from routes.promotions import bp as promotions_bp
from routes.tactics import bp as tactics_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in (
        programs_bp,
        allocations_bp,
        promotions_bp,
        tactics_bp,
        documents_bp,
        analyses_bp,
        ledger_bp,
        deductions_bp,
        audits_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "No such resource path.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method not allowed on this path.", 405)
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request is not well formed.", 400)
        if exc.code == 415:
            return error_response(
                "ERR_INVALID_REQUEST", "Unsupported media type.", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "Unexpected server condition: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
