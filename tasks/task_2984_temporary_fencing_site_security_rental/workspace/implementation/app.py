"""Temporary Fencing & Site Security Rental API.

Boots a stateless Flask process: every row lives in process-local dictionaries
(see store.py), so relaunching this module through start.sh discards all state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes_contracts import bp as contracts_bp
from routes_ledger import bp as ledger_bp
from routes_permits import bp as permits_bp
from routes_quotes import bp as quotes_bp
from routes_reference import bp as reference_bp
from routes_work_orders import bp as work_orders_bp
from store import store


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(reference_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(ledger_bp)

    @app.before_request
    def _serialise_requests():
        """One request at a time: every derived figure is recomputed in-request."""
        store.lock.acquire()

    @app.teardown_request
    def _release(_exc=None):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "No such route.", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "Method not allowed for this route.", 405)
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "The request could not be parsed.", 400)
        return error_response("ERR_VALIDATION", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_VALIDATION", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
