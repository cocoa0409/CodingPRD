"""Entry point: error handlers and route registration."""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    from routes.hospitals import bp as hospitals_bp
    from routes.methodology import bp as methodology_bp
    from routes.surveys import bp as surveys_bp
    from routes.cycles import bp as cycles_bp
    from routes.employers import bp as employers_bp

    app.register_blueprint(hospitals_bp)
    app.register_blueprint(methodology_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(employers_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error_response(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        code = ERR_INVALID_REQUEST
        if error.code == 404:
            return jsonify(error_response(
                "ERR_NOT_FOUND", "The requested path does not exist."
            )), 404
        return jsonify(error_response(code, error.description or "Invalid request.")), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return jsonify(error_response(ERR_INVALID_REQUEST, str(error))), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)