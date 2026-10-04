"""Entry point: app factory, error handlers, blueprint registration."""
import os
from flask import Flask

from db import db
from errors import ApiError, err_not_found
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes_athletes import bp as athletes_bp
    from routes_subscriptions import bp as subs_bp
    from routes_zones import bp as zones_bp
    from routes_activities import bp as activities_bp
    from routes_segments import bp as segments_bp
    from routes_clubs import bp as clubs_bp
    from routes_events import bp as events_bp
    from routes_safety import bp as safety_bp

    for bp in (athletes_bp, subs_bp, zones_bp, activities_bp,
               segments_bp, clubs_bp, events_bp, safety_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err_not_found("Resource does not exist"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err_not_found("Resource does not exist"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        from errors import err_validation
        return error_response(err_validation(str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
