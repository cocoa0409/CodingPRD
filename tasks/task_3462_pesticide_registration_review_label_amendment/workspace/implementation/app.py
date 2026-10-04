"""Application factory and entry point.

Thin wiring layer: registers the per-domain blueprints and the error handlers
that emit the PRD 2.2 envelope for every failure mode.
"""
import os

from flask import Flask

import constants
from envelope import error_body
from errors import ApiError
from flask import jsonify
from routes import (
    active_ingredients,
    amendments,
    applications,
    bulletins,
    certifications,
    clock_route,
    data_call_ins,
    proceedings,
    products,
    review_cases,
    risk_assessments,
    state_registrations,
    studies,
    tolerances,
)


def create_app():
    app = Flask(__name__)

    # Platform endpoint lives OUTSIDE the /pesticide-registry prefix (PRD 2.4).
    app.register_blueprint(clock_route.bp)

    prefix = constants.API_PREFIX
    app.register_blueprint(active_ingredients.bp, url_prefix=prefix)
    app.register_blueprint(products.bp, url_prefix=prefix)
    app.register_blueprint(applications.bp, url_prefix=prefix)
    app.register_blueprint(studies.bp, url_prefix=prefix)
    app.register_blueprint(risk_assessments.bp, url_prefix=prefix)
    app.register_blueprint(tolerances.bp, url_prefix=prefix)
    app.register_blueprint(amendments.bp, url_prefix=prefix)
    app.register_blueprint(certifications.bp, url_prefix=prefix)
    app.register_blueprint(bulletins.bp, url_prefix=prefix)
    app.register_blueprint(review_cases.bp, url_prefix=prefix)
    app.register_blueprint(data_call_ins.bp, url_prefix=prefix)
    app.register_blueprint(proceedings.bp, url_prefix=prefix)
    app.register_blueprint(state_registrations.bp, url_prefix=prefix)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        body = error_body("ERR_NOT_FOUND", "The requested resource does not exist.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        body = error_body("ERR_NOT_FOUND", "The requested resource does not exist.")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_body("ERR_INTERNAL", "Internal server error: %s" % exc)
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
