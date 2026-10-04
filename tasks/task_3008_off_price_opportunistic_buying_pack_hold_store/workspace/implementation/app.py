"""Entry point: Flask app assembly, error handlers, blueprint registration."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

import errors as err
from errors import ApiError
from response import error, success

from routes.foundation import bp as foundation_bp
from routes.lots import bp as lots_bp
from routes.warehouses_holds import bp as warehouses_holds_bp
from routes.stores_plans import bp as stores_plans_bp
from routes.tickets import bp as tickets_bp
from routes.store_skus import bp as store_skus_bp
from routes.receipts import bp as receipts_bp
from routes.shrink import bp as shrink_bp
from routes.liquidation import bp as liquidation_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (foundation_bp, lots_bp, warehouses_holds_bp, stores_plans_bp,
                  tickets_bp, store_skus_bp, receipts_bp, shrink_bp, liquidation_bp):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc)


@app.errorhandler(404)
def handle_404(exc):
    return error(err.not_found("resource not found"))


@app.errorhandler(405)
def handle_405(exc):
    return error(err.not_found("resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error(exc)
    app.logger.exception("unexpected error")
    return error(ApiError("ERR_INVALID_REQUEST", f"malformed request: {exc}"))


@app.get("/health")
def health():
    return success({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
