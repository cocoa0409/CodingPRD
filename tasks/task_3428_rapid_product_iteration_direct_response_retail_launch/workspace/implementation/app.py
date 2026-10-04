"""Rapid Launch DR Retail API — Flask entry point.

Boots cleanly from a fresh process: all state is in-memory in state.DB, empty
at startup; the logical clock reads CLOCK_DEFAULT_ISO until set via the API."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from state import LOCK
from util import error_response

import routes_admin
import routes_concepts
import routes_media
import routes_partners
import routes_patent
import routes_retail
import routes_studies
import routes_variants

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_admin, routes_concepts, routes_media, routes_partners,
               routes_patent, routes_retail, routes_studies, routes_variants):
    app.register_blueprint(module.bp)


@app.before_request
def _acquire_lock():
    LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(Exception)
def _handle_other(err):
    if isinstance(err, ApiError):
        return error_response(err)
    if isinstance(err, HTTPException):
        return error_response(ApiError("ERR_INVALID_REQUEST", err.code or 500, err.name))
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True,
            use_reloader=False)
