"""Application entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import catalog, orders, promo, settlement, storeside, territory

app = Flask(__name__)

app.register_blueprint(catalog.bp)
app.register_blueprint(territory.bp)
app.register_blueprint(orders.bp)
app.register_blueprint(storeside.bp)
app.register_blueprint(promo.bp)
app.register_blueprint(settlement.bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error)


@app.errorhandler(404)
def handle_not_found(error):
    class _Err:
        error_id = "ERR_NOT_FOUND"
        message = "Resource not found"
        http_status = 404

    return error_response(_Err())


@app.errorhandler(405)
def handle_method_not_allowed(error):
    class _Err:
        error_id = "ERR_METHOD_NOT_ALLOWED"
        message = "Method not allowed"
        http_status = 405

    return error_response(_Err())


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return error_response(error)

    class _Err:
        error_id = "ERR_INTERNAL"
        message = "Internal server error"
        http_status = 500

    return error_response(_Err())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
