"""Rheumatology Biologic Coordination API.

Storage is purely in-memory (see store.py) and NOTHING is seeded: every
collection starts empty on every fresh process, which is what the harness's
per-test server reboot relies on.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import BLUEPRINTS


def create_app():
    # No static surface: the API is the whole application.
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Routing-level failures (unknown path, wrong method) still answer in
        # the documented envelope rather than in Werkzeug's HTML.
        return error(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be routed.",
            422 if exc.code == 400 else exc.code,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
