"""Flask app entry point: error handlers + route registration."""
import os
from flask import Flask
from errors import APIError, error_body

app = Flask(__name__)


@app.errorhandler(APIError)
def handle_api_error(e):
    return error_body(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_body("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_body("ERR_NOT_FOUND", "Method not allowed"), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, APIError):
        return error_body(e.error_id, e.message), e.http_status
    return error_body("ERR_VALIDATION", str(e)), 422


# Register blueprints
from routes.items import bp as items_bp
from routes.purchase_orders import bp as pos_bp
from routes.containers import bp as containers_bp
from routes.stores import bp as stores_bp
from routes.allocations import bp as allocations_bp
from routes.customers import bp as customers_bp
from routes.memberships import bp as memberships_bp
from routes.coupons import bp as coupons_bp
from routes.sales import bp as sales_bp
from routes import sale_actions  # noqa: F401  (registers extra rules on sales bp)
from routes.warranty_claims import bp as claims_bp
from routes.recalls import bp as recalls_bp
from routes.clock import bp as clock_bp

for bp in (items_bp, pos_bp, containers_bp, stores_bp, allocations_bp,
           customers_bp, memberships_bp, coupons_bp, sales_bp, claims_bp,
           recalls_bp, clock_bp):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
