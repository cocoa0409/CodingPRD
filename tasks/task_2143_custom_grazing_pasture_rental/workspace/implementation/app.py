"""Custom Grazing & Pasture Rental API — entry point."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
from store import db

from routes.parties import bp as parties_bp
from routes.pastures import bp as pastures_bp
from routes.contracts import bp as contracts_bp
from routes.lots import bp as lots_bp
from routes.health import bp as health_bp
from routes.infrastructure import bp as infrastructure_bp
from routes.settlements import bp as settlements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(parties_bp)
    app.register_blueprint(pastures_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(infrastructure_bp)
    app.register_blueprint(settlements_bp)

    @app.before_request
    def _serialize_requests():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(_exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return jsonify(error_body("ERR_VALIDATION", "Unknown resource path.")), 404
        if err.code == 405:
            return jsonify(error_body("ERR_VALIDATION", "Method not allowed.")), 405
        return jsonify(error_body("ERR_VALIDATION", err.description or "Request could not be processed.")), \
            err.code or 400

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        return jsonify(error_body("ERR_VALIDATION", "Unexpected server error: %s" % err)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
