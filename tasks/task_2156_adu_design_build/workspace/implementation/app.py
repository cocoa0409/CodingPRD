"""ADU Design-Build API — entry point."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response, _meta
import routes_core
import routes_permit
import routes_finance
import routes_build


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_permit.bp)
    app.register_blueprint(routes_finance.bp)
    app.register_blueprint(routes_build.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_VALIDATION" if err.code in (400, 405, 415) else "ERR_NOT_FOUND",
                "message": err.description or "Request could not be handled.",
            },
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
