"""Cloud Backup Recovery API -- application factory and blueprint wiring.

Boot contract (INSTRUCTION.md): listen on $PORT (default 10000), bind
0.0.0.0, run in the foreground.  Storage is in-memory only and every fresh
process starts empty at the logical clock default 2026-09-01T00:00:00Z
(PRD 2.5) -- nothing is seeded here or anywhere else.
"""

import os
import uuid

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

import errors as E
import refresh
from response import error_response
from store import store

from routes_accounts import bp as accounts_bp
from routes_groups import bp as groups_bp
from routes_policies import bp as policies_bp
from routes_agents import bp as agents_bp
from routes_sets import bp as sets_bp
from routes_versions import bp as versions_bp
from routes_restores import bp as restores_bp
from routes_shipments import bp as shipments_bp
from routes_billing import bp as billing_bp
from routes_retention import bp as retention_bp
from routes_deletion import bp as deletion_bp
from routes_pods import bp as pods_bp
from routes_clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _request_context():
        g.request_id = store.request_id()
        # `is_expired` and everything derived from it are a pure function of
        # the logical clock (PRD 3.1, 3.3); re-evaluate them whenever the clock
        # has moved since the last request.
        refresh.refresh()

    for bp in (clock_bp, accounts_bp, groups_bp, policies_bp, agents_bp,
               sets_bp, versions_bp, restores_bp, shipments_bp, billing_bp,
               retention_bp, deletion_bp, pods_bp):
        app.register_blueprint(bp)

    @app.errorhandler(E.APIError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(E.ERR_INVALID_REQUEST,
                                  "no route matches %s" % request.path, 404)
        if exc.code == 405:
            return error_response(E.ERR_INVALID_REQUEST,
                                  "method not allowed for %s" % request.path, 405)
        return error_response(E.ERR_INVALID_REQUEST,
                              exc.description or "request rejected", exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response(E.ERR_INVALID_REQUEST, str(exc), 400)

    @app.route("/health", methods=["GET"])
    def _health():
        return jsonify({"meta": {"api_request_id": "req_HEALTH",
                                 "api_request_timestamp": None},
                        "response_type": "object",
                        "data": {"status": "ok"}})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)