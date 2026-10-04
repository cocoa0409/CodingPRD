"""Private Label Medsupply API — Flask entry point.

Boots from a fresh process with an empty in-memory store; the harness
relaunches start.sh before every test.
"""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND
from helpers import error_body
import routes_clock
import routes_facilities
import routes_products
import routes_lots
import routes_sterilization
import routes_conversion
import routes_trays
import routes_agreements
import routes_orders
import routes_rebates
import routes_disruptions
import routes_inventory

app = Flask(__name__)
app.json.sort_keys = False

for module in (routes_clock, routes_facilities, routes_products, routes_lots,
               routes_sterilization, routes_conversion, routes_trays,
               routes_agreements, routes_orders, routes_rebates,
               routes_disruptions, routes_inventory):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.status


@app.errorhandler(404)
def handle_404(_err):
    return jsonify(error_body(ERR_NOT_FOUND, 'Resource not found')), 404


@app.errorhandler(405)
def handle_405(_err):
    return jsonify(error_body(ERR_NOT_FOUND, 'Resource not found')), 404


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return jsonify(error_body('ERR_INTERNAL', 'Internal server error')), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
