"""Special Olympics Local Program API -- Flask entry point."""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_body
import routes_program
import routes_medical
import routes_workforce
import routes_practice
import routes_competition
import routes_health


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _init_request_scope():
        g.created_ids = set()
        g.touched_ids = set()

    for module in (routes_program, routes_medical, routes_workforce,
                   routes_practice, routes_competition, routes_health):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST", "No such route.")), 404
        if exc.code == 405:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST", "Method not allowed for this route.")), 405
        return jsonify(error_body(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.")), (
                exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return jsonify(error_body(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
