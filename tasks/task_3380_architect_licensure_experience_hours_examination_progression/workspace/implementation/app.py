"""Entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask

from envelope import err
from errors import ApiError

API_PREFIX = "/licensure"


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return err("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, "internal server error")

    from routes_certificate import bp as certificate_bp
    from routes_clock import bp as clock_bp
    from routes_disciplinary import bp as disciplinary_bp
    from routes_education import bp as education_bp
    from routes_exam import bp as exam_bp
    from routes_experience import bp as experience_bp
    from routes_registry import bp as registry_bp
    from routes_supplemental import bp as supplemental_bp
    from routes_transmittal import bp as transmittal_bp

    for blueprint in (clock_bp, registry_bp, education_bp, experience_bp,
                      exam_bp, supplemental_bp, certificate_bp,
                      transmittal_bp, disciplinary_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
