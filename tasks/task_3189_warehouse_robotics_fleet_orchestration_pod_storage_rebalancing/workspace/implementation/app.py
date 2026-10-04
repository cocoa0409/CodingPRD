"""Flask app factory + entrypoint."""

import os

from flask import Flask

import errors
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes_chargers import bp as chargers_bp
    from routes_clock import bp as clock_bp
    from routes_drive_units import bp as drive_units_bp
    from routes_exceptions import bp as exceptions_bp
    from routes_maintenance import bp as maintenance_bp
    from routes_orders import bp as orders_bp
    from routes_permits import bp as permits_bp
    from routes_pick_stations import bp as pick_stations_bp
    from routes_pick_tasks import bp as pick_tasks_bp
    from routes_pods_skus import bp as pods_skus_bp
    from routes_releases import bp as releases_bp
    from routes_shift_plans import bp as shift_plans_bp
    from routes_stow_tasks import bp as stow_tasks_bp
    from routes_zones import bp as zones_bp

    for bp in (
        zones_bp,
        drive_units_bp,
        chargers_bp,
        pods_skus_bp,
        pick_stations_bp,
        orders_bp,
        pick_tasks_bp,
        stow_tasks_bp,
        maintenance_bp,
        exceptions_bp,
        permits_bp,
        shift_plans_bp,
        releases_bp,
        clock_bp,
    ):
        app.register_blueprint(bp, url_prefix="/fleet")

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.not_found("route not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.not_found("method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err)
        return error_response(errors.ApiError("ERR_VALIDATION", str(err), 400))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
