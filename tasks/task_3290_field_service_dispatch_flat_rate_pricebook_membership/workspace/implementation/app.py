"""Application entry point.

The Flask object is created at import time (NOT inside ``__main__``) so that the
blueprints registered by ``routes/*`` all attach to the same instance and an
``exec python3 app.py`` boot serves every route.

The store starts empty on every boot: nothing below seeds, preloads or hardcodes
an entity.  The harness kills and relaunches this process before every test, so
each fresh ``bash start.sh`` wipes every byte of state.
"""

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from constants import API_PREFIX
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body, success

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ------------------------------------------------------------------ routes
from routes.org import bp as org_bp
from routes.pricebook import bp as pricebook_bp
from routes.appointments import bp as appointments_bp
from routes.dispatch import bp as dispatch_bp
from routes.overrides import bp as overrides_bp
from routes.completion import bp as completion_bp
from routes.membership import bp as membership_bp
from routes.calls import bp as calls_bp
from routes.reporting import bp as reporting_bp

for blueprint in (org_bp, pricebook_bp, appointments_bp, dispatch_bp,
                  overrides_bp, completion_bp, membership_bp, calls_bp,
                  reporting_bp):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)


# ---------------------------------------------------------------- handlers
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    if err.code == 404:
        return error_body(ApiError(ERR_NOT_FOUND, "The requested route does not exist.", 404))
    if err.code == 405:
        return error_body(ApiError(ERR_NOT_FOUND, "The requested route does not exist.", 404))
    return error_body(ApiError(ERR_INVALID_REQUEST, err.description or "Bad request", err.code))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_body(ApiError(ERR_INVALID_REQUEST, str(err) or "Unexpected error", 400))


@app.errorhandler(500)
def handle_500(err):
    return error_body(ApiError(ERR_INVALID_REQUEST, "Unexpected server error", 500))


@app.route("/")
def root():
    return success({"service": "field-service-dispatch-pricebook-membership"})


@app.route(API_PREFIX)
def api_root():
    return success({"service": "field-service-dispatch-pricebook-membership"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)