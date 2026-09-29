"""New Markets Tax Credit allocation & deployment API (Flask, in-memory)."""
import os

from flask import Flask

import response
from errors import ApiError
from routes import (awards, cbas, cdes, clock_control, funds, obligations,
                    qalicbs, qeis, qlicis, tracts, unwinds)

BLUEPRINTS = (
    clock_control.bp,
    cdes.bp,
    awards.bp,
    tracts.bp,
    qalicbs.bp,
    funds.bp,
    qeis.bp,
    qlicis.bp,
    obligations.bp,
    cbas.bp,
    unwinds.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED",
            "The HTTP method is not allowed for this resource.", 405)

    @app.errorhandler(Exception)
    def _internal(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
