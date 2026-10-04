"""Flask app entry point: registers all routes and error handlers."""
import os
import threading

from flask import Flask

import db
from errors import ApiError
from helpers import error_body
import routes_projects
import routes_site_control
import routes_interconnection
import routes_offtake
import routes_supply
import routes_procurement
import routes_milestones
import routes_tcq
import routes_partnerships
import routes_debt

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize all request handling (in-memory store; tests may run concurrent clients)
_lock = threading.RLock()


@app.before_request
def _serialize():
    _lock.acquire()


@app.teardown_request
def _release(exc=None):
    _lock.release()


@app.errorhandler(ApiError)
def _api_error(e):
    body = error_body(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def _nf(e):
    return error_body("ERR_NOT_FOUND", "Not found"), 404


@app.errorhandler(405)
def _mna(e):
    return error_body("ERR_NOT_FOUND", "Not found"), 404


@app.errorhandler(400)
def _bad(e):
    return error_body("ERR_VALIDATION", "Bad request"), 400


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return error_body(e.error_id, e.message), e.http_status
    return error_body("ERR_VALIDATION", str(e)), 400


routes_projects.register(app)
routes_site_control.register(app)
routes_interconnection.register(app)
routes_offtake.register(app)
routes_supply.register(app)
routes_procurement.register(app)
routes_milestones.register(app)
routes_tcq.register(app)
routes_partnerships.register(app)
routes_debt.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
