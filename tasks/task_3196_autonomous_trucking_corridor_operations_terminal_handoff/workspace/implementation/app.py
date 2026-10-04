"""Entry point — registers every route and installs the error handlers.

`start.sh` runs this file in the foreground.  The store is wiped once here at
import time (`db.reset()`), and again on every fresh process, so a per-test
server restart always begins from an empty world.
"""

import os
import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import core
import error_handlers  # noqa: F401  (registers ApiError handler on import)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

# A fresh boot starts with an empty store and the default logical clock.
db.reset()
core.reset_clock()

import routes  # noqa: E402

routes.register_all(app)


@app.before_request
def _open_request():
    db.open_request()


@app.teardown_request
def _close_request(exc=None):
    db.close_request()


@app.errorhandler(Exception)
def _unhandled(exc):
    from response import error_envelope
    from core import ApiError
    if isinstance(exc, ApiError):
        return error_envelope(exc)
    if isinstance(exc, HTTPException):
        err = ApiError("ERR_INVALID_REQUEST",
                       exc.description or "Malformed request.",
                       exc.code or 400)
        return error_envelope(err)
    logging.exception("unhandled error")
    err = ApiError("ERR_INVALID_REQUEST", "Malformed request.", 500)
    return error_envelope(err)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)