"""Entry point for the Convenience Franchise Gross-Profit Split API.

The store is in-memory and starts empty on every boot: nothing is seeded,
preloaded or hardcoded here. Every entity is constructed by a caller through
the API surface defined in the PRD.
"""

import os

from flask import Flask, request

import db
import middleware
from errors import ApiError
from response import err, ok

from routes.agreements import bp as agreements_bp
from routes.delivery import bp as delivery_bp
from routes.draws import bp as draws_bp
from routes.franchisees import bp as franchisees_bp
from routes.fresh_orders import bp as fresh_orders_bp
from routes.rebates import bp as rebates_bp
from routes.settlements import bp as settlements_bp, line_bp as revenue_lines_bp
from routes.shrink import bp as shrink_bp
from routes.stores import bp as stores_bp

API_PREFIX = "/franchise"

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["PROPAGATE_EXCEPTIONS"] = False


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return err("ERR_RESOURCE_NOT_FOUND",
               "A path-segment id resolves to no resource of the expected type.", 404)


@app.errorhandler(405)
def handle_bad_method(_exc):
    return err("ERR_INVALID_REQUEST", "The HTTP method is not allowed on this path.", 400)


@app.errorhandler(500)
def handle_server_error(_exc):
    return err("ERR_INVALID_REQUEST", "The request could not be processed.", 400)


@app.before_request
def _serialize_writes():
    # Every mutation runs under one lock so a cascade cannot interleave with a
    # concurrent request; the store is a single in-process ledger.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        db.LOCK.acquire()


@app.after_request
def _release_lock(response):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass
    return response


@app.post("/franchise/_clock/set_current_utc")
@middleware.auth(("FranchisorAdmin",))
def set_current_utc():
    payload = middleware.body(required=("current_utc",))
    db.set_clock(payload["current_utc"])
    return ok({})


for blueprint in (franchisees_bp, stores_bp, agreements_bp, settlements_bp,
                  revenue_lines_bp, draws_bp, rebates_bp, shrink_bp,
                  delivery_bp, fresh_orders_bp):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)