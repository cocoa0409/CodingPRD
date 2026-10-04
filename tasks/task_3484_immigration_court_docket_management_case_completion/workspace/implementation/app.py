# app.py — Flask bootstrap: error handlers, route registration, and the
# foreground server bound to 0.0.0.0:$PORT (default 10000).
import os
import traceback

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "Internal error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded=False: the in-memory store needs no locking when requests are
    # serialized; the harness restarts the server per test anyway.
    app.run(host="0.0.0.0", port=port, threaded=False)
