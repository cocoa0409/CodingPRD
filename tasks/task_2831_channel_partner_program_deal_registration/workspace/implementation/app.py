"""Channel Partner Program API - in-memory Flask service.

Storage is process-local and volatile: every launch of start.sh begins with a
completely empty database and the logical clock at 2026-08-01T00:00:00Z.
Nothing is seeded, cached or written to disk.
"""
import os

from flask import Flask, g, request

import routes_account
import routes_conflict
import routes_mdf
import routes_order
import routes_partner
import routes_registration
import routes_review
import routes_spr
import store
from errors import ApiError
from response import error_response

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False


@app.before_request
def _open_transaction():
    """A mutating request is atomic: either every cascade hop lands or none.

    PRD 2.9 requires cascade atomicity, and several endpoints run an expiry
    sweep before a precondition that may still reject the request, so the
    whole database is snapshotted and restored on any failure.
    """
    if request.method != "GET":
        g.db_snapshot = store.snapshot()


def _rollback():
    snapshot = g.pop("db_snapshot", None)
    if snapshot is not None:
        store.restore(snapshot)


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    _rollback()
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _handle_missing_route(exc):
    _rollback()
    return error_response("ERR_NOT_FOUND", "No such resource.", 404)


@app.errorhandler(405)
def _handle_bad_method(exc):
    _rollback()
    return error_response("ERR_NOT_FOUND", "No such resource.", 404)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    _rollback()
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response("ERR_INVALID_REQUEST", "The request could not be "
                          "processed: %s" % exc, 422)


routes_partner.register(app)
routes_account.register(app)
routes_registration.register(app)
routes_conflict.register(app)
routes_spr.register(app)
routes_mdf.register(app)
routes_order.register(app)
routes_review.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
