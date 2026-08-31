"""Citizen Science Data Collection API — entry point."""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError, ERROR_STATUS
from routes.core import bp as core_bp
from routes.campaigns import bp as campaigns_bp
from routes.observations import bp as observations_bp
from routes.equipment import bp as equipment_bp
from routes.publications import bp as publications_bp
from routes.ops import bp as ops_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

_lock = threading.RLock()


@app.before_request
def _acquire():
    _lock.acquire()
    db.begin_request()


@app.teardown_request
def _release(exc=None):
    try:
        _lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return response.error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(err):
    if err.code == 404:
        return response.error_response(
            "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404)
    if err.code == 405:
        return response.error_response(
            "ERR_INVALID_REQUEST", "Method not allowed for this resource.", 405)
    if err.code in (400, 415):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request payload is malformed.",
            ERROR_STATUS["ERR_INVALID_REQUEST"])
    return response.error_response(
        "ERR_INVALID_REQUEST", err.description or "Request failed.", err.code or 500)


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return response.error_response("ERR_INVALID_REQUEST", str(err), 500)


app.register_blueprint(core_bp)
app.register_blueprint(campaigns_bp)
app.register_blueprint(observations_bp)
app.register_blueprint(equipment_bp)
app.register_blueprint(publications_bp)
app.register_blueprint(ops_bp)


@app.get("/health")
def health():
    return response.object_response({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
