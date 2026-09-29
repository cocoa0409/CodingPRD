"""Consumer Device Security Labeling API.

The process starts with a completely empty store and a logical clock parked at
2026-08-01T00:00:00Z.  Nothing is seeded: every row a caller can read was
created through the declared API surface.
"""

import os
import threading

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import routes_assessments
import routes_config
import routes_display
import routes_enforcement
import routes_engagements
import routes_grants
import routes_participants
import routes_products
import routes_program
from envelope import error_body
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

# One writer at a time: every business rule in this program reads and writes
# several rows and must observe a consistent snapshot.
_request_lock = threading.RLock()

for blueprint in (
    routes_config.bp,
    routes_participants.bp,
    routes_products.bp,
    routes_assessments.bp,
    routes_engagements.bp,
    routes_grants.bp,
    routes_display.bp,
    routes_enforcement.bp,
    routes_program.bp,
):
    app.register_blueprint(blueprint)


@app.before_request
def _acquire():
    _request_lock.acquire()
    g._holds_request_lock = True


@app.teardown_request
def _release(exception=None):
    if g.pop("_holds_request_lock", False):
        try:
            _request_lock.release()
        except RuntimeError:
            pass


def _envelope(error_id, message, status):
    response = jsonify(error_body(error_id, message))
    response.status_code = status
    return response


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return _envelope(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def _handle_not_found(error):
    return _envelope("ERR_NOT_FOUND", "No such route.", 404)


@app.errorhandler(405)
def _handle_method_not_allowed(error):
    return _envelope("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405)


@app.errorhandler(HTTPException)
def _handle_http_exception(error):
    if error.code == 400:
        return _envelope("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
    return _envelope(
        "ERR_REQUEST_FAILED", error.description or "Request failed.", error.code or 500
    )


@app.errorhandler(Exception)
def _handle_unexpected(error):
    return _envelope("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
