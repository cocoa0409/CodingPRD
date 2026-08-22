"""Judgment Enforcement API - entry point.

Storage is entirely in-memory and starts EMPTY on every boot: no entity is
seeded, preloaded or hardcoded anywhere in this process.
"""

import os

from flask import Flask

from envelope import error_response
import routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this resource.", 405)

    @app.errorhandler(500)
    def _server_error(_e):
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
