"""Franchise Supply Chain API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, error_response
import routes as R

app = Flask(__name__)
app.url_map.strict_slashes = False

ADMIN = ("SupplyChainAdmin",)
STORE_MANAGER = ("StoreManager",)
COORDINATOR = ("RouteCoordinator",)
READ = R.READ_ROLES


def reg(path, methods, handler, roles, **kw):
    endpoint = f"{methods[0]} {path} {' '.join(sorted(kw.values()))}".replace(" ", "_").replace("/", "_").replace("<", "").replace(">", "")
    app.add_url_rule(path, endpoint, R.require(*roles)(handler), methods=methods, **kw)


# --- SupplyCenter ---
reg("/supply-centers", ["POST"], R.create_center, ADMIN)
reg("/supply-centers/<center_id>", ["GET"], R.get_center_ep, READ)
reg("/supply-centers/<center_id>/activate", ["POST"], R.activate_center, ADMIN)
reg("/supply-centers/<center_id>/suspend", ["POST"], R.suspend_center, ADMIN)
reg("/supply-centers/<center_id>/decommission", ["POST"], R.decommission_center, ADMIN)
reg("/supply-centers/<center_id>/run_ops", ["POST"], R.run_ops, ADMIN)

# --- Store ---
reg("/supply-centers/<center_id>/stores", ["POST"], R.create_store, ADMIN)
reg("/supply-centers/<center_id>/stores/<store_id>", ["GET"], R.get_store_ep, READ)
reg("/supply-centers/<center_id>/stores", ["GET"], R.list_stores_scoped, READ)
reg("/supply-centers/<center_id>/stores/<store_id>/activate", ["POST"], R.activate_store, ADMIN)
reg("/supply-centers/<center_id>/stores/<store_id>/suspend", ["POST"], R.suspend_store, ADMIN)
reg("/supply-centers/<center_id>/stores/<store_id>/terminate", ["POST"], R.terminate_store, ADMIN)

# --- Product ---
reg("/supply-centers/<center_id>/products", ["POST"], R.create_product, ADMIN)
reg("/supply-centers/<center_id>/products/<product_id>", ["GET"], R.get_product_ep, READ)
reg("/supply-centers/<center_id>/products", ["GET"], R.list_products_scoped, READ)
reg("/supply-centers/<center_id>/products/<product_id>/discontinue", ["POST"], R.discontinue_product, ADMIN)
reg("/supply-centers/<center_id>/products/<product_id>/recall", ["POST"], R.recall_product, ADMIN)

# --- PriceBook ---
reg("/supply-centers/<center_id>/price-books", ["POST"], R.create_price_book, ADMIN)
reg("/supply-centers/<center_id>/price-books/<price_book_id>", ["GET"], R.get_price_book_ep, READ)
reg("/supply-centers/<center_id>/price-books", ["GET"], R.list_price_books_scoped, READ)

# --- DeliveryRoute ---
reg("/supply-centers/<center_id>/routes", ["POST"], R.create_route, COORDINATOR)
reg("/supply-centers/<center_id>/routes/<route_id>", ["GET"], R.get_route_ep, READ)
reg("/supply-centers/<center_id>/routes", ["GET"], R.list_routes_scoped, READ)
reg("/supply-centers/<center_id>/routes/<route_id>/dispatch", ["POST"], R.dispatch_route, COORDINATOR)
reg("/supply-centers/<center_id>/routes/<route_id>/cancel", ["POST"], R.cancel_route, COORDINATOR)

# --- DeliveryStop ---
reg("/supply-centers/<center_id>/routes/<route_id>/stops/<stop_id>", ["GET"], R.get_stop_ep, READ)
reg("/supply-centers/<center_id>/routes/<route_id>/stops", ["GET"], R.list_stops_scoped, READ)
reg("/supply-centers/<center_id>/routes/<route_id>/stops/<stop_id>/arrive", ["POST"], R.arrive_stop, COORDINATOR)
reg("/supply-centers/<center_id>/routes/<route_id>/stops/<stop_id>/complete", ["POST"], R.complete_stop, COORDINATOR)
reg("/supply-centers/<center_id>/routes/<route_id>/stops/<stop_id>/skip", ["POST"], R.skip_stop, COORDINATOR)

# --- PurchaseOrder / OrderLine ---
reg("/supply-centers/<center_id>/stores/<store_id>/purchase-orders", ["POST"], R.create_order, STORE_MANAGER)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>", ["GET"], R.get_order_ep, READ)
reg("/supply-centers/<center_id>/purchase-orders", ["GET"], R.list_orders_scoped, READ)
reg("/supply-centers/<center_id>/stores/<store_id>/purchase-orders/<order_id>/lines", ["POST"], R.add_order_line, STORE_MANAGER)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/lines", ["GET"], R.list_order_lines, READ)
reg("/supply-centers/<center_id>/stores/<store_id>/purchase-orders/<order_id>/submit", ["POST"], R.submit_order, STORE_MANAGER)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/confirm", ["POST"], R.confirm_order, ADMIN)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/load", ["POST"], R.load_order, COORDINATOR)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/deliver", ["POST"], R.deliver_order, COORDINATOR)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/settle", ["POST"], R.settle_order_ep, ADMIN)
reg("/supply-centers/<center_id>/stores/<store_id>/purchase-orders/<order_id>/cancel", ["POST"], R.cancel_order, STORE_MANAGER)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/reject", ["POST"], R.reject_order, ADMIN)
reg("/supply-centers/<center_id>/purchase-orders/<order_id>/lines/<line_id>/mark-shorted", ["POST"], R.mark_line_shorted, COORDINATOR)

# --- PromotionEvent ---
reg("/supply-centers/<center_id>/promotions", ["POST"], R.create_promotion, ADMIN)
reg("/supply-centers/<center_id>/promotions/<promotion_id>", ["GET"], R.get_promotion_ep, READ)
reg("/supply-centers/<center_id>/promotions", ["GET"], R.list_promotions_scoped, READ)
reg("/supply-centers/<center_id>/promotions/<promotion_id>/confirm", ["POST"], R.confirm_promotion, ADMIN)
reg("/supply-centers/<center_id>/promotions/<promotion_id>/close", ["POST"], R.close_promotion, ADMIN)
reg("/supply-centers/<center_id>/promotions/<promotion_id>/cancel", ["POST"], R.cancel_promotion, ADMIN)

# --- RebatePool ---
reg("/supply-centers/<center_id>/rebate-pools", ["POST"], R.create_pool, ADMIN)
reg("/supply-centers/<center_id>/rebate-pools/<pool_id>", ["GET"], R.get_pool_ep, READ)
reg("/supply-centers/<center_id>/rebate-pools", ["GET"], R.list_pools_scoped, READ)
reg("/supply-centers/<center_id>/rebate-pools/<pool_id>/calculate", ["POST"], R.calculate_pool, ADMIN)
reg("/supply-centers/<center_id>/rebate-pools/<pool_id>/settle", ["POST"], R.settle_pool, ADMIN)

# --- RebateLedger ---
reg("/supply-centers/<center_id>/rebate-ledgers/<ledger_id>", ["GET"], R.get_ledger_ep, READ)
reg("/supply-centers/<center_id>/rebate-ledgers", ["GET"], R.list_ledgers_scoped, READ)
reg("/supply-centers/<center_id>/rebate-ledgers/<ledger_id>/void", ["POST"], R.void_ledger, ADMIN)

# --- ComplianceAgreement ---
reg("/supply-centers/<center_id>/stores/<store_id>/compliance-agreements", ["POST"], R.create_agreement, ADMIN)
reg("/supply-centers/<center_id>/compliance-agreements/<agreement_id>", ["GET"], R.get_agreement_ep, READ)
reg("/supply-centers/<center_id>/compliance-agreements", ["GET"], R.list_agreements_scoped, READ)
reg("/supply-centers/<center_id>/stores/<store_id>/compliance-agreements/<agreement_id>/activate", ["POST"], R.activate_agreement, ADMIN)
reg("/supply-centers/<center_id>/stores/<store_id>/compliance-agreements/<agreement_id>/cure", ["POST"], R.cure_agreement, ADMIN)
reg("/supply-centers/<center_id>/stores/<store_id>/compliance-agreements/<agreement_id>/terminate", ["POST"], R.terminate_agreement, ADMIN)

# --- CapacityPlan ---
reg("/supply-centers/<center_id>/capacity-plans", ["POST"], R.create_plan, ADMIN)
reg("/supply-centers/<center_id>/capacity-plans/<plan_id>", ["GET"], R.get_plan_ep, READ)
reg("/supply-centers/<center_id>/capacity-plans", ["GET"], R.list_plans_scoped, READ)
reg("/supply-centers/<center_id>/capacity-plans/<plan_id>/lock", ["POST"], R.lock_plan, ADMIN)

# --- FoodCostVariance ---
reg("/supply-centers/<center_id>/stores/<store_id>/food-cost-variances/<variance_id>", ["GET"], R.get_variance_ep, READ)
reg("/supply-centers/<center_id>/food-cost-variances", ["GET"], R.list_variances_scoped, READ)
reg("/supply-centers/<center_id>/stores/<store_id>/food-cost-variances", ["POST"], R.create_variance, ADMIN)

# --- Compliance Report ---
reg("/supply-centers/<center_id>/stores/<store_id>/compliance-reports", ["POST"], R.create_compliance_report, STORE_MANAGER)

# --- Clock ---
reg("/_clock/set_current_utc", ["POST"], R.set_clock, ADMIN)

# --- Flat FK reverse-reachability endpoints ---
reg("/stores/<store_id>", ["GET"], R.flat_get_store, READ)
reg("/stores", ["GET"], R.flat_list_stores, READ)
reg("/products/<product_id>", ["GET"], R.flat_get_product, READ)
reg("/products", ["GET"], R.flat_list_products, READ)
reg("/routes/<route_id>", ["GET"], R.flat_get_route, READ)
reg("/routes", ["GET"], R.flat_list_routes, READ)
reg("/delivery-stops/<stop_id>", ["GET"], R.flat_get_stop, READ)
reg("/delivery-stops", ["GET"], R.flat_list_stops, READ)
reg("/purchase-orders/<order_id>", ["GET"], R.flat_get_order, READ)
reg("/purchase-orders", ["GET"], R.flat_list_orders, READ)
reg("/order-lines/<line_id>", ["GET"], R.flat_get_line, READ)
reg("/order-lines", ["GET"], R.flat_list_lines, READ)
reg("/price-books/<price_book_id>", ["GET"], R.flat_get_price_book, READ)
reg("/price-books", ["GET"], R.flat_list_price_books, READ)
reg("/rebate-pools/<pool_id>", ["GET"], R.flat_get_pool, READ)
reg("/rebate-pools", ["GET"], R.flat_list_pools, READ)
reg("/rebate-ledgers/<ledger_id>", ["GET"], R.flat_get_ledger, READ)
reg("/rebate-ledgers", ["GET"], R.flat_list_ledgers, READ)
reg("/compliance-agreements/<agreement_id>", ["GET"], R.flat_get_agreement, READ)
reg("/compliance-agreements", ["GET"], R.flat_list_agreements, READ)
reg("/promotions/<promotion_id>", ["GET"], R.flat_get_promotion, READ)
reg("/promotions", ["GET"], R.flat_list_promotions, READ)
reg("/capacity-plans/<plan_id>", ["GET"], R.flat_get_plan, READ)
reg("/capacity-plans", ["GET"], R.flat_list_plans, READ)
reg("/food-cost-variances/<variance_id>", ["GET"], R.flat_get_variance, READ)
reg("/food-cost-variances", ["GET"], R.flat_list_variances, READ)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Resource not found", 404))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 400))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
