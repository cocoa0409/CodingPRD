"""Certified Collision Repair Network API -- Flask entry point."""
import os
import traceback

from flask import Flask, jsonify, request

from util import ApiError, err_response

VALID_ROLES = {"NetworkAdmin", "NetworkAuditor", "ShopManager", "DealerRep",
               "InsurerRep", "Anonymous"}
ANONYMOUS_PATHS = {("/network/locator/search", "POST")}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def authenticate():
        if (request.path, request.method) in ANONYMOUS_PATHS:
            return None
        user_id = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        if not user_id or not role or role not in VALID_ROLES or role == "Anonymous":
            body, status = err_response(
                "ERR_UNAUTHENTICATED", 401,
                "X-User-ID and a recognized X-User-Role header are required")
            return jsonify(body), status
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body, status = err_response(e.error_id, e.status, e.message)
        return jsonify(body), status

    @app.errorhandler(404)
    def handle_404(e):
        body, status = err_response("ERR_NOT_FOUND", 404, "Resource not found")
        return jsonify(body), status

    @app.errorhandler(405)
    def handle_405(e):
        body, status = err_response("ERR_NOT_FOUND", 404, "Resource not found")
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        body, status = err_response("ERR_INVALID_REQUEST", 400, str(e))
        return jsonify(body), status

    from routes.shops import bp as shops_bp
    from routes.requirements import bp as requirements_bp
    from routes.audits import bp as audits_bp
    from routes.technicians import bp as technicians_bp
    from routes.repairs import bp as repairs_bp
    from routes.warranty import bp as warranty_bp
    from routes.insurers import bp as insurers_bp
    from routes.referrals import bp as referrals_bp
    for module_bp in (shops_bp, requirements_bp, audits_bp, technicians_bp,
                      repairs_bp, warranty_bp, insurers_bp, referrals_bp):
        app.register_blueprint(module_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
