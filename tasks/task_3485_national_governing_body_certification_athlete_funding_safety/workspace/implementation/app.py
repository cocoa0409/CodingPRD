"""USOPC NGB Certification API — Flask entry point."""
import os
import traceback

from flask import Flask

import db
from envelope import respond_error
from errors import ApiError, ERR_INTERNAL, ERR_NOT_FOUND


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_appeals
    import routes_athletes
    import routes_clock
    import routes_commercial
    import routes_funding
    import routes_gb
    import routes_rosters
    import routes_safety
    import routes_selection

    for module in (routes_clock, routes_gb, routes_athletes, routes_funding,
                   routes_safety, routes_selection, routes_rosters,
                   routes_appeals, routes_commercial):
        app.register_blueprint(module.bp)

    @app.before_request
    def _begin_request():
        db.reset_marks()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return respond_error(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return respond_error(ERR_NOT_FOUND, 404, "resource does not exist")

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return respond_error(ERR_NOT_FOUND, 404, "resource does not exist")

    @app.errorhandler(Exception)
    def _unhandled(err):
        traceback.print_exc()
        return respond_error(ERR_INTERNAL, 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
