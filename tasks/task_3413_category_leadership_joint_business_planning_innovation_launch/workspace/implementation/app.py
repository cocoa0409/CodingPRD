"""Application factory: blueprint registration and the error envelope.

Run directly (`python3 app.py`) to serve on 0.0.0.0:$PORT (default 10000).
Importing this module does not start the server.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import analyses
    import clock
    import deductions
    import events
    import forecasts
    import funds
    import launches
    import phases
    import plans
    import pricepacks
    import reference
    import reviews
    import shelf

    for mod in (
        clock,
        reference,
        plans,
        events,
        analyses,
        shelf,
        launches,
        phases,
        funds,
        deductions,
        forecasts,
        pricepacks,
        reviews,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_RESOURCE_NOT_FOUND", 404, "route or resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")

    @app.errorhandler(HTTPException)
    def _http_error(e):
        return error_response("ERR_VALIDATION", e.code or 400, e.name)

    @app.errorhandler(Exception)
    def _unexpected(e):
        return error_response("ERR_INTERNAL", 500, "internal error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
