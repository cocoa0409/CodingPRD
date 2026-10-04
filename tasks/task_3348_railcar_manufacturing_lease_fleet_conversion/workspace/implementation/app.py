"""Entry point: builds the Flask app, registers every route group and the
error handlers, then serves in the foreground on 0.0.0.0:$PORT.

State lives only in this process (see store.py).  Nothing is seeded at boot
except the singleton PortfolioLedger, which PRD section 2.4 declares is always
present in status OPEN and which has no creation endpoint.
"""

import os
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from store import now_iso
import svc_catalog
import svc_lease
import svc_retrofit
import svc_sales

app = Flask(__name__)
app.json.sort_keys = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify({
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


@app.errorhandler(HTTPException)
def handle_http_error(err):
    """Unknown path / wrong method: still answer with the standard envelope."""
    error_id = "ERR_NOT_FOUND" if err.code == 404 else "ERR_INVALID_REQUEST"
    return jsonify({
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": err.description or err.name},
    }), err.code


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return jsonify({
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST",
                 "message": "Unhandled server error: %s" % (err,)},
    }), 500


def _request_id():
    from web import new_request_id
    return new_request_id()


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "object",
        "data": {"service": "railcar-manufacturing-lease-fleet-conversion",
                 "status": "ok"},
    }), 200


svc_catalog.register(app)
svc_lease.register(app)
svc_retrofit.register(app)
svc_sales.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
