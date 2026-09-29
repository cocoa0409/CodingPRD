"""Supermarket in-store bakery production planning API.

Flask application factory and error plumbing.  All state lives in process
memory (see store.py); nothing is persisted and nothing is seeded.
"""

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from store import db


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    from routes.bake_days import bp as bake_days_bp
    from routes.cake_orders import bp as cake_orders_bp
    from routes.clock import bp as clock_bp
    from routes.departments import bp as departments_bp
    from routes.ingredient_orders import bp as ingredient_orders_bp
    from routes.ingredients import bp as ingredients_bp
    from routes.ovens import bp as ovens_bp
    from routes.pickup_slots import bp as pickup_slots_bp
    from routes.production_runs import bp as production_runs_bp
    from routes.products import bp as products_bp
    from routes.waste_records import bp as waste_records_bp

    for blueprint in (
        departments_bp,
        products_bp,
        ingredients_bp,
        ovens_bp,
        bake_days_bp,
        production_runs_bp,
        waste_records_bp,
        pickup_slots_bp,
        cake_orders_bp,
        ingredient_orders_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _snapshot():
        # Whole-store snapshot so a rejected write leaves no partial cascade.
        if request.method != "GET":
            db.snapshot()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        db.rollback()
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.after_request
    def _commit(response):
        if response.status_code < 400:
            db.commit()
        return response

    @app.errorhandler(404)
    def _not_found(_exc):
        db.rollback()
        return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404

    @app.errorhandler(405)
    def _not_allowed(_exc):
        db.rollback()
        return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed for this route.")), 405

    @app.errorhandler(400)
    def _bad_request(_exc):
        db.rollback()
        return jsonify(error_body("ERR_INVALID_REQUEST", "The request payload is malformed.")), 400

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        db.rollback()
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Request rejected.")), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):
        db.rollback()
        app.logger.exception("unhandled error: %s", exc)
        return jsonify(error_body("ERR_INVALID_REQUEST", "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
