"""Entry point: blueprint registration, error handlers and the request sweeps."""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import envelope
import recompute
import store
from errors import ApiError

import api_accounts
import api_applications
import api_clock
import api_franchisees
import api_inventory
import api_launch
import api_payments
import api_pledges
import api_product_orders
import api_products
import api_routes
import api_sales_orders
import api_shops
import api_technicians
import api_warranty

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (api_clock, api_products, api_franchisees, api_routes, api_shops,
               api_technicians, api_applications, api_accounts, api_payments,
               api_sales_orders, api_warranty, api_inventory, api_product_orders,
               api_pledges, api_launch):
    app.register_blueprint(module.bp)


@app.before_request
def _sweeps():
    """The charge-off sweep and the weekly accrual run on every request."""
    store.begin_unit()
    recompute.run_sweeps()
    # The handler is its own unit of work: a row it modifies is stamped once,
    # independently of anything the sweep moved on the same row.
    store.begin_unit()


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(HTTPException)
def _http_error(exc):
    return envelope.error_body("ERR_INVALID_REQUEST", exc.description), exc.code


@app.errorhandler(Exception)
def _unexpected(exc):  # pragma: no cover - defensive
    return envelope.error_body("ERR_INVALID_REQUEST", str(exc)), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
