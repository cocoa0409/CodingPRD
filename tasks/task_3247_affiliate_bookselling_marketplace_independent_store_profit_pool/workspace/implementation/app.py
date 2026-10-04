"""Flask application entry point."""
import os

from flask import Flask, jsonify

import response
from errors import ApiError

app = Flask(__name__)

from routes import catalog, affiliates, lists, orders, ledger, pools, payouts, promotions

app.register_blueprint(catalog.bp)
app.register_blueprint(affiliates.bp)
app.register_blueprint(lists.bp)
app.register_blueprint(orders.bp)
app.register_blueprint(ledger.bp)
app.register_blueprint(pools.bp)
app.register_blueprint(payouts.bp)
app.register_blueprint(promotions.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return response.error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return response.error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    import traceback
    traceback.print_exc()
    return response.error_response(ApiError("ERR_VALIDATION", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
