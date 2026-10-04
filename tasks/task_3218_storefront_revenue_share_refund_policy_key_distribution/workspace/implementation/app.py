"""Flask entry point: response envelope, error handlers, route registration."""

import os
from datetime import datetime, timezone

from flask import Flask, jsonify

import core
from core import ApiError, new_req_id

app = Flask(__name__)
app.url_map.strict_slashes = False


def envelope(data, response_type, status=200, meta_extra=None):
    meta = {
        "api_request_id": new_req_id(),
        "api_request_timestamp": core.iso(datetime.now(timezone.utc)),
    }
    if meta_extra:
        meta.update(meta_extra)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok(rec, status=200):
    return envelope(rec, "object", status)


def ok_list(records):
    page, meta = core.list_page(records)
    return envelope([core.pub(r) for r in page], "array", 200, meta)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": {
            "api_request_id": new_req_id(),
            "api_request_timestamp": core.iso(datetime.now(timezone.utc)),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


@app.errorhandler(404)
def handle_404(err):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return handle_api_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.before_request
def auth_middleware():
    core.authenticate()


import routes  # noqa: E402,F401  (registers blueprints on import)
routes.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
