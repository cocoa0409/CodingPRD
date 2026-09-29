"""Electronic Resource Licensing & Consortium Purchasing API.

A single-process Flask application whose entire state lives in the in-memory
dictionaries of `store`. Nothing is seeded: every row is created through the
declared endpoints, so a fresh process starts with an empty world and the
logical clock reading exactly DEFAULT_CLOCK_UTC.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import auth
import envelope
from errors import ApiError
from routes import access, archival, clock, commitments, negotiations
from routes import registry, renewals, subscriptions, trials, usage

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False
app.config["PROPAGATE_EXCEPTIONS"] = False

for blueprint in (
    registry.bp,
    trials.bp,
    commitments.bp,
    negotiations.bp,
    subscriptions.bp,
    access.bp,
    usage.bp,
    renewals.bp,
    archival.bp,
    clock.bp,
):
    app.register_blueprint(blueprint)


API_PREFIX = "/erm"


def _is_api_path(path):
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


@app.before_request
def _authenticate_api_requests():
    """Priority 1 runs before the URL is resolved, so an unauthenticated call to
    a path that does not exist still answers 401 rather than 404."""
    from flask import request

    if _is_api_path(request.path):
        auth.authenticate()
    return None


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return envelope.error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def _handle_http_exception(error):
    if error.code == 404:
        return envelope.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )
    if error.code == 405:
        return envelope.error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "The HTTP method is not allowed for this path.",
            405,
        )
    if error.code == 400:
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "The request could not be understood.", 422
        )
    return envelope.error_response(
        "ERR_INTERNAL", error.description or "Request failed.", error.code or 500
    )


@app.errorhandler(Exception)
def _handle_unexpected(error):  # pragma: no cover - defensive
    return envelope.error_response(
        "ERR_INTERNAL", "An unexpected internal error occurred: %s" % error, 500
    )


@app.get("/")
def root():
    """Unauthenticated readiness probe; never part of the API surface."""
    return envelope.object_response({
        "service": "electronic-resource-licensing-consortium-purchasing",
        "status": "ok",
    })


@app.get("/health")
def health():
    return envelope.object_response({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
