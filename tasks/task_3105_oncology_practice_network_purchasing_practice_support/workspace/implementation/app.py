"""Oncology Practice Network Purchasing & Practice Support API.

Entry point: builds the Flask app, installs the envelope-aware error handlers,
dispatches every request through the registry, and serves on 0.0.0.0:$PORT.

The store is in-memory and starts empty on every boot; nothing is seeded.
"""

import os
import sys

from flask import Flask, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import registry  # noqa: E402
import response  # noqa: E402
from auth import extract_user, check_role  # noqa: E402
from ctx import Request  # noqa: E402
from errors import ApiError  # noqa: E402
from utils import reset_clock  # noqa: E402

import routes.clock  # noqa: E402,F401
import routes.networks  # noqa: E402,F401
import routes.practices  # noqa: E402,F401
import routes.providers  # noqa: E402,F401
import routes.drug_products  # noqa: E402,F401
import routes.pricing_agreements  # noqa: E402,F401
import routes.purchase_orders  # noqa: E402,F401
import routes.inventory  # noqa: E402,F401
import routes.treatments  # noqa: E402,F401
import routes.claims  # noqa: E402,F401
import routes.rebates  # noqa: E402,F401
import routes.pathways  # noqa: E402,F401
import routes.management  # noqa: E402,F401
import routes.research  # noqa: E402,F401
import routes.shortages  # noqa: E402,F401
import routes.contracts  # noqa: E402,F401

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def _fresh_boot():
    """Every process start begins from an empty store and the logical clock at
    exactly 2026-09-01T00:00:00Z."""
    db.reset()
    reset_clock()


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(path):
    full_path = "/" + path if path else "/"
    try:
        return _dispatch(request.method, full_path)
    except ApiError as exc:
        return response.error_body(exc.error_id, exc.message, exc.http_status)
    except Exception as exc:  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return response.error_body("ERR_INTERNAL_ERROR", str(exc), 500)


def _dispatch(method, path):
    matched, params = registry.match(method, path)
    if matched is None:
        if registry.unknown_path(method, path):
            raise ApiError("ERR_INVALID_REQUEST", "method not allowed for this path")
        raise ApiError("ERR_NOT_FOUND", "no such resource path")

    principal = extract_user(request.headers)
    check_role(principal, matched["roles"])

    payload = request.get_json(silent=True)
    ctx = Request(method, path, params, payload, request.args, request.headers, principal)

    result = matched["fn"](ctx)
    body = result[0] if isinstance(result, tuple) else result
    status = result[1] if isinstance(result, tuple) else matched["status"]
    if isinstance(body, response.ListPayload):
        rendered, _ = body.render()
        return rendered if status == 200 else (rendered, status)
    return response.object_success(body, status)


# Every process boot is a fresh boot: the store is empty and the logical clock
# reads its startup instant. Nothing is ever seeded or preloaded.
_fresh_boot()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)