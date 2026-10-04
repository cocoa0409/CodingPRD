"""Flask application object, request gate, and error handlers.

Kept in a module separate from app.py so route modules can import it without
re-executing the entry point (python3 app.py runs as __main__).
"""
from flask import Flask, jsonify

import db
from errors import ApiError, ERR_INVALID_STATE
from middleware import auth_check
from util import error_body

app = Flask(__name__)


@app.before_request
def _gate():
    db.LOCK.acquire()
    try:
        auth_check()
    except Exception:
        db.LOCK.release()
        raise


@app.teardown_request
def _release(_exc):
    if db.LOCK._is_owned():
        db.LOCK.release()


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def _nf(_e):
    return jsonify(error_body(ERR_INVALID_STATE, "route not found")), 404


@app.errorhandler(405)
def _mna(_e):
    return jsonify(error_body(ERR_INVALID_STATE, "method not allowed")), 405


@app.errorhandler(Exception)
def _internal(e):
    import traceback
    traceback.print_exc()
    return jsonify(error_body("ERR_INTERNAL", f"{type(e).__name__}: {e}")), 500
