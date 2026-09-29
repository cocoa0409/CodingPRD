"""Field-Erected Storage Tank Construction API.

Entry point: registers every route blueprint, installs the PRD 2.2 error
envelope handlers and serves the app in the foreground with waitress.

The store is entirely in memory (see store.py) and starts completely empty on
every boot: no entity is ever seeded, preloaded or hardcoded at startup.
"""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from envelope import error_response
from errors import ApiError

import routes_coating
import routes_final
import routes_found
import routes_nde
import routes_plate
import routes_tank
import routes_water
import routes_weld

BLUEPRINTS = (
    routes_tank.bp,
    routes_found.bp,
    routes_plate.bp,
    routes_weld.bp,
    routes_nde.bp,
    routes_water.bp,
    routes_coating.bp,
    routes_final.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        message = exc.description or exc.name
        return error_response(errors.ERR_INVALID_REQUEST, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc(file=sys.stderr)
        return error_response(errors.ERR_INVALID_REQUEST, str(exc), 500)

    return app


app = create_app()


def main():
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=16,
              channel_timeout=120, clear_untrusted_proxy_headers=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
