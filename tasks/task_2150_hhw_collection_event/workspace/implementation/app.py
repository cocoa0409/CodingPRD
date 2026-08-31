"""Household Hazardous Waste Collection Event API.

All state lives in process memory (see store.py) and the store starts empty on
every boot — nothing is ever seeded, preloaded or persisted.
"""

import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import routes_appointment
import routes_clock
import routes_container
import routes_dropoff
import routes_event
import routes_manifest
import routes_material
import routes_program
import routes_resident
import routes_site
import routes_staff
from envelope import error_body, error_response
from errors import ApiError
from store import LOCK

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (
    routes_program,
    routes_site,
    routes_material,
    routes_resident,
    routes_event,
    routes_staff,
    routes_appointment,
    routes_dropoff,
    routes_container,
    routes_manifest,
    routes_clock,
):
    app.register_blueprint(module.bp)


@app.before_request
def _begin_request():
    LOCK.acquire()
    g._holds_lock = True
    g._bumped_rows = set()


@app.teardown_request
def _end_request(exc=None):
    if g.pop("_holds_lock", False):
        try:
            LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def _handle_http_error(err):
    status = err.code or 500
    if status == 404:
        error_id = "ERR_INVALID_REQUEST"
    elif status == 405:
        error_id = "ERR_INVALID_REQUEST"
    elif status == 400:
        error_id = "ERR_INVALID_REQUEST"
    else:
        error_id = "ERR_INVALID_REQUEST"
    return jsonify(error_body(error_id, err.description or "Request failed.")), status


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return jsonify(error_body("ERR_INVALID_REQUEST", str(err))), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
